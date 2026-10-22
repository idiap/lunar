# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Placeholder parsing, template execution, and report composition."""

from __future__ import annotations
from reports import build_report
from domain_packages.context import require_context
from prism_runs.runtime import text_digest
from reporting.repository import output_for_binding, template_for_user

import re
import json
import uuid
from collections import Counter
from collections.abc import Mapping
from typing import Any

import asyncpg


def render_prov_records(*args, **kwargs):
    from lunar_planner.provenance import render_prov_records as render

    return render(*args, **kwargs)


PLACEHOLDER = re.compile(r"^[ \t]*\{\{([a-z][a-z0-9_]*)\}\}[ \t]*(?:\r?\n)?$")
RESERVED = frozenset(
    {
        "if",
        "else",
        "endif",
        "for",
        "endfor",
        "include",
        "extends",
        "set",
        "python",
        "javascript",
        "shell",
    }
)


class TemplateValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("invalid template placeholders")


def parse_template(content: str) -> dict[str, Any]:
    """Parse standalone placeholders without evaluating the template text."""

    occurrences: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    markdown: list[str] = []

    def flush_markdown() -> None:
        if markdown:
            segments.append({"kind": "markdown", "content": "".join(markdown)})
            markdown.clear()

    lines = content.splitlines(keepends=True)
    if not lines and content == "":
        lines = []
    for line_number, line in enumerate(lines, 1):
        match = PLACEHOLDER.fullmatch(line)
        if match:
            name = match.group(1)
            if name in RESERVED:
                errors.append(
                    {
                        "line": line_number,
                        "message": f"reserved placeholder name: {name}",
                    }
                )
                markdown.append(line)
                continue
            flush_markdown()
            occurrence = {
                "name": name,
                "line": line_number,
                "ordinal": len(occurrences),
                "line_ending": (
                    "\r\n"
                    if line.endswith("\r\n")
                    else "\n" if line.endswith("\n") else ""
                ),
            }
            occurrences.append(occurrence)
            segments.append({"kind": "placeholder", **occurrence})
            continue
        if "{{" in line or "}}" in line or "{%" in line or "{#" in line:
            errors.append(
                {
                    "line": line_number,
                    "message": "placeholders must occupy a whole line and use a lowercase variable_name",
                }
            )
        markdown.append(line)
    flush_markdown()
    if errors:
        raise TemplateValidationError(errors)
    names: list[str] = []
    for occurrence in occurrences:
        if occurrence["name"] not in names:
            names.append(occurrence["name"])
    counts = Counter(item["name"] for item in occurrences)
    return {
        "variables": names,
        "occurrences": occurrences,
        "duplicates": {name: count for name, count in counts.items() if count > 1},
        "segments": segments,
    }


class TemplateNotFoundError(ValueError):
    pass


class BindingValidationError(ValueError):
    def __init__(self, message: str, details: Any = None):
        self.details = details
        super().__init__(message)


class BindingConflictError(RuntimeError):
    pass


def _attributes(label: str, kind: str, **values: Any) -> dict[str, Any]:
    return {
        "prov:label": label,
        "prov:type": f"lunar:{kind}",
        "lunar:kind": kind,
        **{f"lunar:{key}": value for key, value in values.items() if value is not None},
    }


async def _report_provenance_records(
    connection: asyncpg.Connection,
    *,
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    report_name: str,
    template: Mapping[str, Any],
    template_digest: str,
    sections: list[dict[str, Any]],
    bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    report_entity = f"entity:report:{report_id}"
    template_entity = f"entity:report:{report_id}:template"
    activity = f"activity:report:{report_id}:template-execution"
    app_agent = "agent:lunar:reporting"
    user_agent = f"agent:user:{user_id}"
    records: dict[str, Any] = {
        "entities": {
            template_entity: _attributes(
                template["name"],
                "TemplateSnapshot",
                template_id=str(template["id"]),
                content_digest=template_digest,
            ),
            report_entity: _attributes(
                report_name, "GeneratedReport", report_id=str(report_id)
            ),
        },
        "activities": {
            activity: _attributes(
                "template execution", "TemplateExecution", status="completed"
            )
        },
        "agents": {
            app_agent: _attributes("Lunar reporting service", "ApplicationSoftware"),
            user_agent: _attributes("authenticated report user", "AuthenticatedUser"),
        },
        "relations": [
            {"type": "used", "activity": activity, "entity": template_entity},
            {"type": "wasAssociatedWith", "activity": activity, "agent": app_agent},
            {"type": "wasAssociatedWith", "activity": activity, "agent": user_agent},
            {"type": "wasGeneratedBy", "entity": report_entity, "activity": activity},
            {
                "type": "wasDerivedFrom",
                "generated_entity": report_entity,
                "used_entity": template_entity,
            },
        ],
    }
    run_rows: dict[uuid.UUID, Mapping[str, Any]] = {}
    for output in bindings.values():
        run_rows[output["run_id"]] = output
        output_entity = output["provenance_entity_id"]
        records["entities"].setdefault(
            output_entity,
            _attributes(
                output["output_key"],
                "WorkflowOutput",
                output_key=output["output_key"],
                component_id=output["component_id"],
                content_digest=output["content_digest"],
                run_id=str(output["run_id"]),
                workflow_id=output["workflow_id"],
            ),
        )
        records["relations"].append(
            {"type": "used", "activity": activity, "entity": output_entity}
        )
    for run_id, output in run_rows.items():
        run_activity = f"activity:run:{run_id}"
        adapter_agent = f"agent:adapter:{output['workflow_id']}"
        records["activities"][run_activity] = _attributes(
            output["workflow_id"],
            "PrismRun",
            workflow_id=output["workflow_id"],
            status="completed",
        )
        records["agents"][adapter_agent] = _attributes(
            output["workflow_id"], "WorkflowAdapter"
        )
        records["relations"].extend(
            [
                {
                    "type": "wasAssociatedWith",
                    "activity": run_activity,
                    "agent": adapter_agent,
                },
                {
                    "type": "wasGeneratedBy",
                    "entity": output["provenance_entity_id"],
                    "activity": run_activity,
                },
            ]
        )
        sources = await connection.fetch(
            """
            SELECT resource_id, source_local_identifier, access_mode, version_or_snapshot,
                   safe_locator, content_digest, observed_at
            FROM prism_run_consumed_sources WHERE run_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY observed_at, id
            """,
            run_id,
            user_id,
            require_context(user_id).version_id,
        )
        inputs = await connection.fetch(
            """
            SELECT input_key, kind, safe_locator, content_digest, observed_at
            FROM prism_run_input_entities WHERE run_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY observed_at, id
            """,
            run_id,
            user_id,
            require_context(user_id).version_id,
        )
        used_entities: list[str] = []
        for index, source in enumerate(sources):
            catalog_id = f"entity:catalog:{source['resource_id']}"
            source_id = f"entity:run:{run_id}:source:{index}"
            records["entities"].setdefault(
                catalog_id,
                _attributes(
                    source["resource_id"],
                    "CatalogDataSource",
                    resource_id=source["resource_id"],
                ),
            )
            records["entities"][source_id] = _attributes(
                source["source_local_identifier"],
                "ConsumedDataSource",
                resource_id=source["resource_id"],
                access_mode=source["access_mode"],
                version_or_snapshot=source["version_or_snapshot"],
                safe_locator=source["safe_locator"],
                content_digest=source["content_digest"],
            )
            records["relations"].append(
                {
                    "type": "specializationOf",
                    "specific_entity": source_id,
                    "general_entity": catalog_id,
                }
            )
            used_entities.append(source_id)
        for index, entity in enumerate(inputs):
            input_id = f"entity:run:{run_id}:input:{index}"
            records["entities"][input_id] = _attributes(
                entity["input_key"],
                "InputEntity",
                input_key=entity["input_key"],
                input_kind=entity["kind"],
                safe_locator=entity["safe_locator"],
                content_digest=entity["content_digest"],
            )
            used_entities.append(input_id)
        for used_id in used_entities:
            records["relations"].extend(
                [
                    {"type": "used", "activity": run_activity, "entity": used_id},
                    {
                        "type": "wasDerivedFrom",
                        "generated_entity": output["provenance_entity_id"],
                        "used_entity": used_id,
                    },
                ]
            )
    for section in sections:
        section_entity = section["provenance_entity_id"]
        output_entity = bindings[section["placeholder_name"]]["provenance_entity_id"]
        records["entities"][section_entity] = _attributes(
            section["placeholder_name"],
            "ReportSection",
            section_id=section["section_id"],
            ordinal=section["ordinal"],
            content_digest=section["content_digest"],
        )
        records["relations"].extend(
            [
                {
                    "type": "wasGeneratedBy",
                    "entity": section_entity,
                    "activity": activity,
                },
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": section_entity,
                    "used_entity": output_entity,
                },
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": section_entity,
                    "used_entity": template_entity,
                },
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": report_entity,
                    "used_entity": section_entity,
                },
            ]
        )
    return records


async def execute_template(
    connection: asyncpg.Connection,
    *,
    template_id: uuid.UUID,
    user_id: uuid.UUID,
    report_name: str,
    supplied_bindings: Mapping[str, uuid.UUID],
) -> uuid.UUID:
    """Validate, assemble, and persist one immutable report transactionally."""

    context = require_context(user_id)
    async with connection.transaction():
        template = await template_for_user(connection, template_id, user_id)
        if template is None:
            raise TemplateNotFoundError("Template not found")
        inventory = parse_template(template["content"])
        required = set(inventory["variables"])
        supplied = set(supplied_bindings)
        if required != supplied:
            raise BindingValidationError(
                "bindings must match template variables exactly",
                {
                    "missing": sorted(required - supplied),
                    "unknown": sorted(supplied - required),
                },
            )
        bindings: dict[str, Mapping[str, Any]] = {}
        for name in inventory["variables"]:
            output = await output_for_binding(
                connection, supplied_bindings[name], user_id
            )
            if output is None:
                raise BindingValidationError(
                    f"binding for {name} is unavailable or not owned by the user"
                )
            if output["output_key"] != name:
                raise BindingValidationError(
                    f"binding for {name} has incompatible output key"
                )
            if output["state"] != "completed" or output["provenance_count"] != 2:
                raise BindingConflictError(f"binding for {name} is incomplete")
            if (
                output["markdown"] is None
                or text_digest(output["markdown"]) != output["content_digest"]
            ):
                raise BindingConflictError(f"binding for {name} is stale")
            bindings[name] = output

        report_id = uuid.uuid4()
        rendered: list[str] = []
        sections: list[dict[str, Any]] = []
        for segment in inventory["segments"]:
            if segment["kind"] == "markdown":
                rendered.append(segment["content"])
                continue
            output = bindings[segment["name"]]
            markdown = output["markdown"]
            rendered.append(markdown + segment["line_ending"])
            section_id = f"section-{segment['ordinal'] + 1}-{segment['name']}"
            sections.append(
                {
                    "id": uuid.uuid4(),
                    "section_id": section_id,
                    "ordinal": segment["ordinal"],
                    "placeholder_name": segment["name"],
                    "run_output_id": output["id"],
                    "rendered_markdown": markdown,
                    "content_digest": text_digest(markdown),
                    "provenance_entity_id": f"entity:report:{report_id}:section:{segment['ordinal'] + 1}",
                }
            )
        content = "".join(rendered)
        template_digest = text_digest(template["content"])
        await connection.execute(
            """
            INSERT INTO reports
                (id, query, html, user_id, name, content, version, template_id,
                 template_content_digest, generation_status, generation_type, generated_at,version_id)
            VALUES ($1,$2,$3,$4,$2,$5,1,$6,$7,'completed','template',NOW(),$8)
            """,
            report_id,
            report_name.strip(),
            build_report(report_name.strip(), content, str(report_id)),
            user_id,
            content,
            template_id,
            template_digest,
            context.version_id,
        )
        for section in sections:
            await connection.execute(
                """
                INSERT INTO report_sections
                    (id, section_id, report_id, ordinal, placeholder_name, run_output_id,
                     rendered_markdown, content_digest, provenance_entity_id,user_id,version_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                section["id"],
                section["section_id"],
                report_id,
                section["ordinal"],
                section["placeholder_name"],
                section["run_output_id"],
                section["rendered_markdown"],
                section["content_digest"],
                section["provenance_entity_id"],
                context.user_id,
                context.version_id,
            )
        records = await _report_provenance_records(
            connection,
            report_id=report_id,
            user_id=user_id,
            report_name=report_name.strip(),
            template=template,
            template_digest=template_digest,
            sections=sections,
            bindings=bindings,
        )
        for output_format in ("prov-json", "json-ld"):
            receipt = render_prov_records(records, output_format=output_format)
            await connection.execute(
                """
                INSERT INTO report_provenance_exports
                    (id, report_id, format, media_type, document, wrapper_digest,user_id,version_id)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)
                """,
                uuid.uuid4(),
                report_id,
                receipt["format"],
                receipt["media_type"],
                json.dumps(receipt["document"], sort_keys=True),
                receipt["digest"],
                context.user_id,
                context.version_id,
            )
        return report_id


def slice_prov_document(
    document: Mapping[str, Any], section_entity: str
) -> dict[str, Any]:
    """Return the exact backward lineage of one generated report section."""

    entities = {section_entity}
    derived = list(document.get("wasDerivedFrom", {}).values())
    changed = True
    while changed:
        changed = False
        for relation in derived:
            if (
                relation["prov:generatedEntity"] in entities
                and relation["prov:usedEntity"] not in entities
            ):
                entities.add(relation["prov:usedEntity"])
                changed = True
    for relation in document.get("specializationOf", {}).values():
        if relation["prov:specificEntity"] in entities:
            entities.add(relation["prov:generalEntity"])
    generated = [
        relation
        for relation in document.get("wasGeneratedBy", {}).values()
        if relation["prov:entity"] in entities
    ]
    activities = {relation["prov:activity"] for relation in generated}
    associated = [
        relation
        for relation in document.get("wasAssociatedWith", {}).values()
        if relation["prov:activity"] in activities
    ]
    agents = {relation["prov:agent"] for relation in associated}
    result = {
        "prefix": document.get("prefix", {}),
        "entity": {
            key: value
            for key, value in document.get("entity", {}).items()
            if key in entities
        },
        "activity": {
            key: value
            for key, value in document.get("activity", {}).items()
            if key in activities
        },
        "agent": {
            key: value
            for key, value in document.get("agent", {}).items()
            if key in agents
        },
    }
    relation_endpoints = {
        "used": ("prov:activity", activities, "prov:entity", entities),
        "wasGeneratedBy": ("prov:activity", activities, "prov:entity", entities),
        "wasAssociatedWith": ("prov:activity", activities, "prov:agent", agents),
        "wasDerivedFrom": (
            "prov:generatedEntity",
            entities,
            "prov:usedEntity",
            entities,
        ),
        "specializationOf": (
            "prov:specificEntity",
            entities,
            "prov:generalEntity",
            entities,
        ),
    }
    for relation, (left, left_ids, right, right_ids) in relation_endpoints.items():
        values = {
            key: value
            for key, value in document.get(relation, {}).items()
            if value[left] in left_ids and value[right] in right_ids
        }
        if values:
            result[relation] = values
    return result
