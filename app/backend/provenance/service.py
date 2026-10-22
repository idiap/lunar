# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""W3C provenance construction and deterministic graph projection."""

from __future__ import annotations
from domain_packages.context import require_context
from types import SimpleNamespace
from modules.common import json_value

import json
import uuid
from collections.abc import Mapping
from typing import Any

import asyncpg

from lunar_planner.provenance import render_prov_records
import hashlib


def canonical_digest(value):
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _attributes(label: str, kind: str, **values: Any) -> dict[str, Any]:
    return {
        "prov:label": label,
        "prov:type": f"lunar:{kind}",
        "lunar:kind": kind,
        **{f"lunar:{key}": value for key, value in values.items() if value is not None},
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _observed_rows(
    connection: asyncpg.Connection, run_id: uuid.UUID
) -> dict[str, Any]:
    context = require_context()
    run = await connection.fetchrow(
        """
        SELECT id, user_id, workflow_id, operation, mode, state,
               accepted_plan_digest, started_at, finished_at, error_summary,
               ai_model_id, ai_model_snapshot
        FROM prism_runs WHERE id = $1 AND user_id=$2 AND version_id=$3
        """,
        run_id,
        context.user_id,
        context.version_id,
    )
    if run is None:
        raise ValueError("Prism run not found")
    queries = {
        "sources": """
            SELECT id, resource_id, source_local_identifier, access_point_id,
                   operation_id, access_mode, version_or_snapshot, safe_locator,
                   content_digest, observed_at
            FROM prism_run_consumed_sources WHERE run_id = $1 AND user_id=$2 AND version_id=$3 ORDER BY observed_at, id
        """,
        "inputs": """
            SELECT id, input_key, kind, safe_locator, content_digest, observed_at
            FROM prism_run_input_entities WHERE run_id = $1 AND user_id=$2 AND version_id=$3 ORDER BY observed_at, id
        """,
        "events": """
            SELECT id, stage_id, component_id, status, started_at, finished_at,
                   safe_summary, detail
            FROM prism_run_events WHERE run_id = $1 AND user_id=$2 AND version_id=$3 ORDER BY started_at, id
        """,
        "artifacts": """
            SELECT id, artifact_key, safe_locator, media_type, content_digest,
                   provenance_entity_id
            FROM prism_run_artifacts WHERE run_id = $1 AND user_id=$2 AND version_id=$3 ORDER BY artifact_key, id
        """,
        "outputs": """
            SELECT id, output_key, component_id, media_type, content_digest,
                   provenance_entity_id, created_at
            FROM prism_run_outputs WHERE run_id = $1 AND user_id=$2 AND version_id=$3 ORDER BY output_key, id
        """,
    }
    result: dict[str, Any] = {"run": run}
    for key, query in queries.items():
        result[key] = await connection.fetch(
            query, run_id, context.user_id, context.version_id
        )
    return result


def observed_records(
    rows: Mapping[str, Any],
    adapter: Any,
    *,
    terminal_state: str | None = None,
) -> dict[str, Any]:
    """Build retrospective-only PROV records from persisted observations."""

    run = rows["run"]
    run_id = str(run["id"])
    run_activity = f"activity:run:{run_id}"
    adapter_agent = f"agent:runner:{adapter.workflow_id}"
    user_agent = f"agent:user:{run['user_id']}"
    model_snapshot = json_value(run.get("ai_model_snapshot"), {}) or {}
    model_agent = (
        f"agent:model:{model_snapshot['id']}" if model_snapshot.get("id") else None
    )
    records: dict[str, Any] = {
        "entities": {},
        "activities": {
            run_activity: _attributes(
                adapter.label,
                "PrismRun",
                workflow_id=adapter.workflow_id,
                operation=run["operation"],
                mode=run["mode"],
                status=terminal_state or run["state"],
                accepted_plan_digest=run["accepted_plan_digest"],
                started_at=_iso(run["started_at"]),
                finished_at=_iso(run["finished_at"]),
                omission=(
                    "runtime receipts unavailable after worker interruption"
                    if run["error_summary"] == "worker_interrupted"
                    else None
                ),
            )
        },
        "agents": {
            adapter_agent: _attributes(adapter.label, "LunarRunner"),
            user_agent: _attributes("authenticated Prism user", "AuthenticatedUser"),
        },
        "relations": [
            {
                "type": "wasAssociatedWith",
                "activity": run_activity,
                "agent": adapter_agent,
            },
            {
                "type": "wasAssociatedWith",
                "activity": run_activity,
                "agent": user_agent,
            },
        ],
    }
    if model_agent is not None:
        records["agents"][model_agent] = _attributes(
            str(model_snapshot["name"]),
            "SelectedAIModel",
            configured_model_id=model_snapshot["id"],
            provider=model_snapshot.get("provider"),
            provider_model_id=model_snapshot.get("model_id"),
        )
        records["relations"].append(
            {
                "type": "wasAssociatedWith",
                "activity": run_activity,
                "agent": model_agent,
            }
        )
    source_entities: list[str] = []
    input_entities: list[str] = []
    for index, source in enumerate(rows["sources"]):
        catalog_id = f"entity:catalog:{source['resource_id']}"
        entity_id = f"entity:run:{run_id}:source:{index}"
        records["entities"].setdefault(
            catalog_id,
            _attributes(
                source["resource_id"],
                "CatalogDataSource",
                resource_id=source["resource_id"],
            ),
        )
        records["entities"][entity_id] = _attributes(
            source["source_local_identifier"],
            "ConsumedDataSource",
            resource_id=source["resource_id"],
            source_local_identifier=source["source_local_identifier"],
            access_point_id=source["access_point_id"],
            operation_id=source["operation_id"],
            access_mode=source["access_mode"],
            version_or_snapshot=source["version_or_snapshot"],
            safe_locator=source["safe_locator"],
            content_digest=source["content_digest"],
            observed_at=_iso(source["observed_at"]),
        )
        records["relations"].extend(
            [
                {
                    "type": "specializationOf",
                    "specific_entity": entity_id,
                    "general_entity": catalog_id,
                },
                {"type": "used", "activity": run_activity, "entity": entity_id},
            ]
        )
        source_entities.append(entity_id)
    for index, entity in enumerate(rows["inputs"]):
        entity_id = f"entity:run:{run_id}:input:{index}"
        records["entities"][entity_id] = _attributes(
            entity["input_key"],
            "InputEntity",
            input_key=entity["input_key"],
            input_kind=entity["kind"],
            safe_locator=entity["safe_locator"],
            content_digest=entity["content_digest"],
            observed_at=_iso(entity["observed_at"]),
        )
        records["relations"].append(
            {"type": "used", "activity": run_activity, "entity": entity_id}
        )
        input_entities.append(entity_id)

    stage_activities: list[str] = []
    prism_activities: list[str] = []
    entity_by_occurrence: dict[str, str] = {}
    effect_entity_by_occurrence: dict[str, str] = {}
    for index, event in enumerate(rows["events"]):
        activity_id = f"activity:run:{run_id}:stage:{index}"
        detail = json_value(event.get("detail"), {})
        event_kind = str(detail.get("event_kind") or "adapter-stage")
        records["activities"][activity_id] = _attributes(
            event["stage_id"],
            "PrismExecutionEvent" if detail else "WorkflowStage",
            stage_id=event["stage_id"],
            component_id=event["component_id"],
            status=event["status"],
            event_kind=event_kind,
            workflow_occurrence=detail.get("workflow_occurrence"),
            effect_record_id=detail.get("effect_record_id"),
            input_digest=detail.get("input_digest"),
            output_digest=detail.get("output_digest"),
            started_at=_iso(event["started_at"]),
            finished_at=_iso(event["finished_at"]),
            summary=event["safe_summary"],
        )
        records["relations"].append(
            {
                "type": "wasAssociatedWith",
                "activity": activity_id,
                "agent": adapter_agent,
            }
        )
        occurrence = detail.get("workflow_occurrence")
        if detail:
            prism_activities.append(activity_id)
        if event_kind == "workflow-node" and occurrence:
            entity_id = f"entity:run:{run_id}:prism-value:{occurrence}"
            entity_by_occurrence[str(occurrence)] = entity_id
            records["entities"][entity_id] = _attributes(
                f"PRISM value {occurrence}",
                "PrismNodeValue",
                workflow_occurrence=occurrence,
                content_digest=detail.get("output_digest"),
            )
            records["relations"].append(
                {"type": "wasGeneratedBy", "entity": entity_id, "activity": activity_id}
            )
        if event_kind == "agent-invoked":
            agent_name = str(detail.get("agent_name") or event["component_id"])
            prism_agent = f"agent:prism:{agent_name}"
            records["agents"].setdefault(
                prism_agent, _attributes(agent_name, "PrismAgent")
            )
            records["relations"].append(
                {
                    "type": "wasAssociatedWith",
                    "activity": activity_id,
                    "agent": prism_agent,
                }
            )
            for skill_id in detail.get("activated_skill_ids") or []:
                skill_entity = f"entity:skill:{canonical_digest(str(skill_id)).removeprefix('sha256:')}"
                records["entities"].setdefault(
                    skill_entity,
                    _attributes(
                        str(skill_id), "ActivatedPrismSkill", skill_id=skill_id
                    ),
                )
                records["relations"].append(
                    {"type": "used", "activity": activity_id, "entity": skill_entity}
                )
        if event_kind == "ai-generate-effect":
            if model_agent is not None:
                records["relations"].append(
                    {
                        "type": "wasAssociatedWith",
                        "activity": activity_id,
                        "agent": model_agent,
                    }
                )
            record_id = detail.get("effect_record_id")
            if record_id:
                effect_entity = f"entity:run:{run_id}:effect:{record_id}"
                records["entities"][effect_entity] = _attributes(
                    f"PRISM effect {record_id}",
                    "PrismEffectResult",
                    effect_record_id=record_id,
                    input_digest=detail.get("input_digest"),
                    output_digest=detail.get("output_digest"),
                )
                records["relations"].append(
                    {
                        "type": "wasGeneratedBy",
                        "entity": effect_entity,
                        "activity": activity_id,
                    }
                )
                if occurrence:
                    effect_entity_by_occurrence[str(occurrence)] = effect_entity
        stage_activities.append(activity_id)

    first_reasoning_activity = next(
        (
            activity
            for activity, event in zip(stage_activities, rows["events"], strict=True)
            if json_value(event.get("detail"), {}).get("event_kind") == "agent-invoked"
        ),
        prism_activities[0] if prism_activities else run_activity,
    )
    for entity_id in source_entities + input_entities:
        records["relations"].append(
            {"type": "used", "activity": first_reasoning_activity, "entity": entity_id}
        )

    derived_occurrences: set[str] = set()
    for event in rows["events"]:
        detail = json_value(event.get("detail"), {})
        if detail.get("event_kind") != "reasoning-relation":
            continue
        target = str(detail.get("target_occurrence") or "")
        target_entity = entity_by_occurrence.get(target)
        for source in detail.get("source_occurrences") or []:
            source_entity = entity_by_occurrence.get(str(source))
            if target_entity and source_entity:
                records["relations"].append(
                    {
                        "type": "wasDerivedFrom",
                        "generated_entity": target_entity,
                        "used_entity": source_entity,
                    }
                )
                derived_occurrences.add(target)
    previous_entity: str | None = None
    for occurrence, entity_id in entity_by_occurrence.items():
        effect_entity = effect_entity_by_occurrence.get(occurrence)
        if effect_entity is not None:
            records["relations"].append(
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": entity_id,
                    "used_entity": effect_entity,
                }
            )
        if occurrence not in derived_occurrences:
            for used_entity in (
                [previous_entity]
                if previous_entity is not None
                else source_entities + input_entities
            ):
                records["relations"].append(
                    {
                        "type": "wasDerivedFrom",
                        "generated_entity": entity_id,
                        "used_entity": used_entity,
                    }
                )
        previous_entity = entity_id

    generating_activity = stage_activities[-1] if stage_activities else run_activity
    artifact_entities: list[str] = []
    for artifact in rows["artifacts"]:
        entity_id = artifact["provenance_entity_id"]
        artifact_entities.append(entity_id)
        records["entities"][entity_id] = _attributes(
            artifact["artifact_key"],
            "GeneratedArtifact",
            safe_locator=artifact["safe_locator"],
            media_type=artifact["media_type"],
            content_digest=artifact["content_digest"],
        )
        records["relations"].append(
            {
                "type": "wasGeneratedBy",
                "entity": entity_id,
                "activity": generating_activity,
            }
        )
        for used_id in (
            list(entity_by_occurrence.values()) or source_entities + input_entities
        ):
            records["relations"].append(
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": entity_id,
                    "used_entity": used_id,
                }
            )
    for output in rows["outputs"]:
        entity_id = output["provenance_entity_id"]
        records["entities"][entity_id] = _attributes(
            output["output_key"],
            "WorkflowOutput",
            output_key=output["output_key"],
            component_id=output["component_id"],
            media_type=output["media_type"],
            content_digest=output["content_digest"],
            created_at=_iso(output["created_at"]),
        )
        records["relations"].append(
            {
                "type": "wasGeneratedBy",
                "entity": entity_id,
                "activity": generating_activity,
            }
        )
        output_inputs = artifact_entities + list(entity_by_occurrence.values())
        if not output_inputs:
            output_inputs = source_entities + input_entities
        for used_id in output_inputs:
            records["relations"].append(
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": entity_id,
                    "used_entity": used_id,
                }
            )
    return records


async def terminalize_run_provenance(
    connection: asyncpg.Connection,
    *,
    run_id: uuid.UUID,
    adapter: Any,
    context: Any,
    output_id: uuid.UUID | None,
    failed: bool,
) -> str:
    """Persist both standards exports before terminal completion."""

    del context, output_id
    selected = require_context()
    records = observed_records(
        await _observed_rows(connection, run_id),
        adapter,
        terminal_state="failed" if failed else "completed",
    )
    outputs = await connection.fetch(
        "SELECT structured_value,provenance_entity_id FROM prism_run_outputs WHERE run_id=$1 AND user_id=$2 AND version_id=$3",
        run_id,
        selected.user_id,
        selected.version_id,
    )
    for output in outputs:
        typed = (json_value(output["structured_value"], {}) or {}).get("typed_report")
        if typed is None:
            continue
        document = typed["provenance"]
        records["entities"].update(document["entity"])
        records["activities"].update(document["activity"])
        fields = {
            "used": {"activity": "prov:activity", "entity": "prov:entity"},
            "wasGeneratedBy": {"activity": "prov:activity", "entity": "prov:entity"},
            "wasDerivedFrom": {
                "generated_entity": "prov:generatedEntity",
                "used_entity": "prov:usedEntity",
            },
        }
        for kind, mapping in fields.items():
            for relation in document[kind].values():
                records["relations"].append(
                    {
                        "type": kind,
                        **{key: relation[value] for key, value in mapping.items()},
                    }
                )
        root = next(
            key
            for key, value in document["entity"].items()
            if value["prism:native_reference"] == typed["native"]["graph"]["result"]
        )
        records["relations"].append(
            {
                "type": "wasDerivedFrom",
                "generated_entity": output["provenance_entity_id"],
                "used_entity": root,
            }
        )
    receipts = [
        render_prov_records(records, output_format=output_format)
        for output_format in ("prov-json", "json-ld")
    ]
    if any(
        (json_value(output["structured_value"], {}) or {}).get("typed_report")
        for output in outputs
    ):
        for receipt in receipts:
            key = "prefix" if receipt["format"] == "prov-json" else "@context"
            receipt["document"][key]["prism"] = "https://idiap.ch/prism/recorded/"
            receipt.pop("digest")
            receipt["digest"] = canonical_digest(receipt)
    for receipt in receipts:
        await connection.execute(
            """
            INSERT INTO prism_run_provenance_exports
                (id, run_id, format, media_type, document, wrapper_digest,user_id,version_id)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)
            ON CONFLICT (run_id, format) DO UPDATE SET
                media_type = EXCLUDED.media_type,
                document = EXCLUDED.document,
                wrapper_digest = EXCLUDED.wrapper_digest,
                generated_at = NOW()
            """,
            uuid.uuid4(),
            run_id,
            receipt["format"],
            receipt["media_type"],
            json.dumps(receipt["document"], sort_keys=True),
            receipt["digest"],
            selected.user_id,
            selected.version_id,
        )
    return canonical_digest(
        {receipt["format"]: receipt["digest"] for receipt in receipts}
    )


def graph_view_model(document: Mapping[str, Any]) -> dict[str, Any]:
    """Project stored PROV-JSON into the UI's stable graph contract."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    for collection, kind in (
        ("entity", "entity"),
        ("activity", "activity"),
        ("agent", "agent"),
    ):
        for identifier, attributes in document.get(collection, {}).items():
            nodes.append(
                {
                    "id": identifier,
                    "kind": kind,
                    "label": attributes.get("prov:label", identifier),
                    "type": attributes.get(
                        "lunar:kind",
                        attributes.get("prov:type", attributes.get("prism:origin")),
                    ),
                    "attributes": attributes,
                }
            )
    fields = {
        "used": ("prov:activity", "prov:entity"),
        "wasGeneratedBy": ("prov:activity", "prov:entity"),
        "wasAssociatedWith": ("prov:agent", "prov:activity"),
        "wasDerivedFrom": ("prov:usedEntity", "prov:generatedEntity"),
        "specializationOf": ("prov:generalEntity", "prov:specificEntity"),
    }
    for relation, (source_key, target_key) in fields.items():
        for value in document.get(relation, {}).values():
            edges.append(
                {
                    "id": canonical_digest({"relation": relation, **value}),
                    "source": value[source_key],
                    "target": value[target_key],
                    "relation": relation,
                }
            )
    return {
        "nodes": sorted(nodes, key=lambda row: row["id"]),
        "edges": sorted(
            edges, key=lambda row: (row["relation"], row["source"], row["target"])
        ),
        "legend": ["entity", "activity", "agent"],
    }


async def persist_run_provenance(connection, context, run_id, workflow, *, failed):
    from domain_packages.context import bind_context

    with bind_context(context):
        return await terminalize_run_provenance(
            connection,
            run_id=run_id,
            adapter=SimpleNamespace(
                workflow_id=workflow["id"], label=workflow.get("name", workflow["id"])
            ),
            context=None,
            output_id=None,
            failed=failed,
        )
