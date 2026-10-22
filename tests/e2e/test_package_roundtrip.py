# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Cross-owner export/import retains fresh execution and original source evidence."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import auth
import modules.common as common
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from domain_packages.archive import validate_archive
from domain_packages.context import bind_context
from domain_packages.exporter import export_version
from domain_packages.export_routes import export_package
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker.preparation import prepare_runtime
from domain_packages.worker.runtime import load_runtime
from domain_packages.worker.runs import enqueue, execute_queued, recover_runs
from reporting.service import execute_template
import test_package_workers as fixtures

pytestmark = pytest.mark.e2e


def test_fresh_worker_output_template_and_provenance_survive_roundtrip(
    e2e_database_url, tmp_path, worker_image
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, _ = await fixtures.imported(
                connection, tmp_path, "executed", planning_hooks=False
            )
            await prepare_runtime(connection, context, storage, base_image=worker_image)
            runtime = await load_runtime(
                connection, context.user_id, context.version_id, storage
            )
            run_id, _ = await enqueue(
                connection, runtime, "inventory", inputs={"count": 41}
            )
            result = await execute_queued(connection, runtime, run_id)
            assert (
                await connection.fetchval(
                    "SELECT state FROM prism_runs WHERE id=$1", run_id
                )
                == "completed"
            ), result
            output_id = await connection.fetchval(
                "SELECT id FROM prism_run_outputs WHERE run_id=$1", run_id
            )
            template = uuid4()
            await connection.execute(
                "INSERT INTO templates(id,user_id,name,content) VALUES($1,$2,'Stock template','# Inventory\n{{result}}\n')",
                template,
                context.user_id,
            )
            with bind_context(context):
                report_id = await execute_template(
                    connection,
                    template_id=template,
                    user_id=context.user_id,
                    report_name="Verified stock report",
                    supplied_bindings={"result": output_id},
                )
            workspace = tmp_path / "export"
            workspace.mkdir()
            path, _ = await export_version(
                connection,
                storage,
                user_id=context.user_id,
                version_id=context.version_id,
                workspace=workspace,
            )
            archive = validate_archive(path, tmp_path / "validated-export")
            document = next(
                row
                for row in archive.documents["reports"]
                if row["name"] == "Verified stock report"
            )
            assert document["metadata"]["generation_type"] == "template"
            assert document["sections"] and document["outputs"][0]["metadata"][
                "structured_value"
            ] == {"count": 42}
            assert {item["format"] for item in document["provenance"]} == {
                "PROV-JSON",
                "JSON-LD",
            }
            assert (
                len(document["runs"]) == 1
                and document["runs"][0]["facts"]["state"] == "completed"
            )
            serialized = json.dumps(document)
            assert str(context.user_id) not in serialized
            # The accepted input receipt retains its original version as a historical fact.
            # Removing it would change the evidence covered by the accepted-plan digest.
            assert document["runs"][0]["facts"]["safe_input_manifest"][
                "version_id"
            ] == str(context.version_id)
            assert document["runs"][0]["facts"]["import_posture"] == "historical_only"
            other = uuid4()
            await connection.execute(
                "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
                other,
                str(other) + "@example.invalid",
            )
            imported = await import_validated(
                connection, storage, user_id=other, archive=archive
            )
            projected = await connection.fetchrow(
                "SELECT * FROM reports WHERE version_id=$1 AND name=$2",
                imported.version_id,
                "Verified stock report",
            )
            assert (
                projected["id"] != report_id
                and projected["generation_type"] == "template"
                and projected["imported"] is True
            )
            sections = await connection.fetch(
                "SELECT * FROM report_sections WHERE report_id=$1", projected["id"]
            )
            assert len(sections) == 1 and sections[0]["run_output_id"] != output_id
            assert (
                await connection.fetchval(
                    "SELECT output_key FROM prism_run_outputs WHERE id=$1",
                    sections[0]["run_output_id"],
                )
                == "result"
            )
            exports = await connection.fetch(
                "SELECT * FROM report_provenance_exports WHERE report_id=$1",
                projected["id"],
            )
            assert {row["format"] for row in exports} == {"prov-json", "json-ld"}
            assert await recover_runs(connection) == []
            assert not list(storage.version_root(imported).glob("runs/*"))
            again = tmp_path / "again"
            again.mkdir()
            second, _ = await export_version(
                connection,
                storage,
                user_id=other,
                version_id=imported.version_id,
                workspace=again,
            )
            checked = validate_archive(second, tmp_path / "checked-again")
            assert len(checked.documents["reports"]) == len(
                archive.documents["reports"]
            )
            repeated = next(
                row
                for row in checked.documents["reports"]
                if row["name"] == "Verified stock report"
            )
            for key in (
                "content",
                "sections",
                "runs",
                "outputs",
                "provenance",
                "template_snapshot",
            ):
                assert repeated[key] == document[key], key
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_bioagents_source_zip_export_and_fresh_import_keep_original_bytes(
    e2e_database_url, tmp_path, monkeypatch
):
    filename = os.getenv("LUNAR_E2E_BIOAGENTS_REPORT_ZIP")
    if not filename:
        pytest.fail(
            "LUNAR_E2E_BIOAGENTS_REPORT_ZIP must name the actual report-inclusive source CLI export"
        )
    source = validate_archive(Path(filename), tmp_path / "source")
    assert source.documents["reports"] and len(source.documents["skills"]) > 100
    original_documents = source.documents
    original_files = {item["path"]: item for item in source.manifest["files"]}
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", e2e_database_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            owner = uuid4()
            other = uuid4()
            for identity in (owner, other):
                await connection.execute(
                    "INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",
                    identity,
                    str(identity) + "@example.invalid",
                )
            context = await import_validated(
                connection, storage, user_id=owner, archive=source
            )
            return context, other, await auth.create_session(owner)
        finally:
            await connection.close()

    context, other, token = asyncio.run(setup())
    app = Starlette(
        routes=[Route("/api/packages/versions/{version_id}/export", export_package)]
    )
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        response = client.get(
            "/api/packages/versions/" + str(context.version_id) + "/export"
        )
        assert response.status_code == 200, (
            response.text[:1000] if response.status_code != 200 else ""
        )
    path = tmp_path / "lunar-export.zip"
    path.write_bytes(response.content)
    exported = validate_archive(path, tmp_path / "exported")
    for kind in ("repository", "skills", "data-sources"):
        assert exported.documents[kind] == original_documents[kind], kind
    original_reports = {row["id"]: row for row in original_documents["reports"]}
    assert len(exported.documents["reports"]) == len(original_reports)
    for document in exported.documents["reports"]:
        original = original_reports[document["id"]]
        for key in (
            "content",
            "revisions",
            "attachments",
            "sections",
            "runs",
            "outputs",
            "provenance",
            "template_snapshot",
        ):
            assert document[key] == original[key], (document["id"], key)
        for item in document["provenance"]:
            assert (
                hashlib.sha256((exported.root / item["file"]).read_bytes()).hexdigest()
                == item["sha256"]
            )
    report_documents = {
        row["document"] for row in source.manifest["collections"]["reports"]
    }
    assert set(original_files) - report_documents <= {
        row["path"] for row in exported.manifest["files"]
    }
    for item in exported.manifest["files"]:
        if item["path"] in original_files and item["path"] not in report_documents:
            assert item == original_files[item["path"]], item["path"]

    async def reimport():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            fresh = await import_validated(
                connection, storage, user_id=other, archive=exported
            )
            assert fresh.user_id != context.user_id
            assert await connection.fetchval(
                "SELECT COUNT(*) FROM skills WHERE version_id=$1", fresh.version_id
            ) == len(original_documents["skills"])
            assert await connection.fetchval(
                "SELECT COUNT(*) FROM reports WHERE version_id=$1", fresh.version_id
            ) == len(original_reports)
            assert await recover_runs(connection) == []
            assert not list(storage.version_root(fresh).glob("runs/*"))
        finally:
            await connection.close()

    asyncio.run(reimport())
