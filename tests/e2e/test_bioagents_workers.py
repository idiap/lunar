# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Imported BioAgents retains native compiler, observations, and report gates."""

import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import asyncpg
import pytest
from prism.runtime import EffectRecorder, FileArtifactStore
from prism.runtime.replay import effect_record_from_dict

from domain_packages.archive import validate_archive
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker.preparation import prepare_runtime
from domain_packages.worker.runtime import load_runtime
from modules.ai_models import ResolvedAIModel, encrypt_api_key, load_owned_ai_model
from domain_packages.worker.runs import enqueue, execute_queued
from bioagents_parity import (
    EXPECTED_CALLS,
    ACCEPTED_TERMINAL,
    REQUIRED_SOURCE_IDENTIFIERS,
    REQUIRED_INPUT_KEYS,
    TOPOLOGY,
    _schema_value,
    _record_fields,
)

pytestmark = pytest.mark.e2e


class NoDomainImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"catalog", "bioagents_planner"}:
            raise AssertionError("Domain import in the API process: " + fullname)


def assert_native_result(result, root, workflow_id, model):
    assert result["status"] == "succeeded", result["error"]
    projected = result["result"]
    assert (
        projected["markdown"].strip()
        and projected["report_verification"]["status"] == "passed"
    )
    assert (
        projected["analysis_results"]["staged_analysis"]
        == result["prepared_input"]["analysis_results"]
    )
    assert projected["analysis_results"]["staged_analysis"]["derived_facts"]
    assert (
        projected["structured_value"]["report_layout"]["blocks"]
        and projected["narrative_slots"]
    )
    topology = TOPOLOGY[workflow_id]
    stages = [
        event["payload"] for event in result["events"] if event["kind"] == "stage"
    ]
    for kind, key, expected in [
        ("workflow-node", "workflow_occurrence", [row[0] for row in topology]),
        ("agent-invoked", "agent_name", [row[1] for row in topology]),
        ("agent-invoked", "workflow_occurrence", [row[0] for row in topology]),
        ("agent-invoked", "activated_skill_ids", [row[2] for row in topology]),
        ("ai-generate-effect", "workflow_occurrence", [row[0] for row in topology]),
    ]:
        matching = [
            row for row in stages if row.get("detail", {}).get("event_kind") == kind
        ]
        assert [row["detail"][key] for row in matching] == expected
    effects = [
        row
        for row in stages
        if row.get("detail", {}).get("event_kind") == "ai-generate-effect"
    ]
    assert all(row["status"] == "accepted" for row in effects)
    agents = [
        row
        for row in stages
        if row.get("detail", {}).get("event_kind") == "agent-invoked"
    ]
    assert all(row["detail"]["effect_record_id"] for row in agents)
    assert [row["id"] for row in projected["structured_value"]["occurrences"]] == [
        row[0] for row in topology
    ]
    sources = [
        event["payload"] for event in result["events"] if event["kind"] == "source"
    ]
    inputs = [
        event["payload"] for event in result["events"] if event["kind"] == "input"
    ]
    required = REQUIRED_SOURCE_IDENTIFIERS[workflow_id]
    if required is None:
        assert len(sources) >= 13
    else:
        assert {row["source_local_identifier"] for row in sources} == required
    # Frozen pre-migration _prepare already records the retained reporting input.
    assert {row["input_key"] for row in inputs} == REQUIRED_INPUT_KEYS[workflow_id] | {
        "saved_reporting_inputs"
    }
    assert all(row["content_digest"].startswith("sha256:") for row in sources + inputs)
    assert all(row["access_mode"] == "offline_fixture" for row in sources)
    for name in ("report-verification.json", "report-persistence-verification.json"):
        assert json.loads((root / name).read_text())["status"] == "passed"
    assert not list(root.rglob("*.md")) and not list(root.rglob("*.html"))
    native = json.loads((root / "prism-run-summary.json").read_text())
    assert (
        native["status"] == "accepted"
        and native["source_hash"].startswith("sha256:")
        and native["module_hashes"]
    )
    assert len(native["effect_records"]) == len(agents) == EXPECTED_CALLS[workflow_id]
    recorder = EffectRecorder(FileArtifactStore(root / "prism-effects"))
    for effect in native["effect_records"]:
        assert effect["invocation"]["handler"] == "litellm"
        assert effect["observation"]["status"] == "accepted"
        assert effect["observation"]["provenance"] == {
            "provider": "litellm",
            "model": f"{model.provider}/{model.model_id}",
        }
        assert (
            recorder.offline_verify(effect_record_from_dict(effect)).status
            == "verified"
        )
    assert model.api_key not in json.dumps(result)
    assert all(
        model.api_key.encode() not in path.read_bytes()
        for path in (root / "prism-effects").rglob("*.json")
    )


def test_all_imported_bioagents_workflows_preserve_compiler_contract(
    e2e_database_url, tmp_path, worker_image
):
    archive_path = os.getenv("LUNAR_E2E_BIOAGENTS_ZIP")
    if not archive_path:
        pytest.fail(
            "LUNAR_E2E_BIOAGENTS_ZIP must name an actual exported BioAgents package"
        )
    guard = NoDomainImports()
    sys.meta_path.insert(0, guard)

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            owner = uuid4()
            await connection.execute(
                "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
                owner,
                str(owner) + "@example.invalid",
            )
            storage = VersionStorage(tmp_path / "store")
            archive = validate_archive(Path(archive_path), tmp_path / "validated")
            context = await import_validated(
                connection, storage, user_id=owner, archive=archive
            )
            await prepare_runtime(connection, context, storage, base_image=worker_image)
            runtime = await load_runtime(connection, owner, context.version_id, storage)
            assert {
                row["id"] for row in runtime.manifest["runtime"]["workflows"]
            } == set(EXPECTED_CALLS)
            for workflow_id in EXPECTED_CALLS:
                calls = []
                model = ResolvedAIModel(
                    id=uuid4(),
                    name="Schema fixture",
                    provider="openai",
                    model_id="schema-stub",
                    api_key="executor-test-secret",
                    api_base="https://provider.invalid/v1",
                    api_version="2026-01-01",
                    config={"temperature": 0},
                )

                def completion(**arguments):
                    calls.append(arguments)
                    terminal = (
                        ACCEPTED_TERMINAL.get(workflow_id)
                        if len(calls) == EXPECTED_CALLS[workflow_id]
                        else None
                    )
                    value = _schema_value(
                        arguments["response_format"]["json_schema"]["schema"],
                        terminal=terminal,
                    )
                    return {"choices": [{"message": {"parsed": value}}]}

                await connection.execute(
                    """INSERT INTO ai_models
                    (id,user_id,name,provider,model_id,api_base,api_version,encrypted_api_key,config)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
                    model.id,
                    owner,
                    model.name,
                    model.provider,
                    model.model_id,
                    model.api_base,
                    model.api_version,
                    encrypt_api_key(model.api_key),
                    json.dumps(model.config),
                )
                model = await load_owned_ai_model(
                    connection, model_id=model.id, user_id=owner
                )
                run_id, _ = await enqueue(
                    connection,
                    runtime,
                    workflow_id,
                    inputs={},
                    selected_model=model,
                )
                terminal = await execute_queued(
                    connection,
                    runtime,
                    run_id,
                    selected_model=model,
                    completion=completion,
                )
                assert terminal["state"] == "completed", terminal
                raw = await connection.fetchval(
                    "SELECT detail FROM prism_run_events WHERE run_id=$1 AND stage_id='worker:result'",
                    run_id,
                )
                result = json.loads(raw)["worker_result"]
                outputs = await connection.fetch(
                    "SELECT user_id,version_id FROM prism_run_outputs WHERE run_id=$1",
                    run_id,
                )
                assert (
                    len(outputs) == 1
                    and outputs[0]["user_id"] == owner
                    and outputs[0]["version_id"] == context.version_id
                )
                assert len(calls) == EXPECTED_CALLS[workflow_id]
                for call in calls:
                    assert (
                        call["model"] == "openai/schema-stub"
                        and call["api_key"] == model.api_key
                    )
                    assert (
                        call["api_base"] == model.api_base
                        and call["api_version"] == model.api_version
                    )
                    assert (
                        call["temperature"] == 0
                        and call["response_format"]["json_schema"]["schema"]["type"]
                        == "object"
                    )
                    prompt = json.loads(json.loads(call["messages"][1]["content"]))
                    assert (
                        prompt["arguments"]
                        and prompt["skills"]
                        and all(row["instructions"] for row in prompt["skills"])
                    )
                first = json.loads(json.loads(calls[0]["messages"][1]["content"]))
                assert result["prepared_input"]["value"] in [
                    _record_fields(row) for row in first["arguments"].values()
                ]
                assert_native_result(
                    result, storage.run_root(context, run_id), workflow_id, model
                )
        finally:
            await connection.close()

    try:
        asyncio.run(scenario())
    finally:
        sys.meta_path.remove(guard)
