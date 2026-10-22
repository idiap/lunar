# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Portable, workflow-scoped visualization and provenance exports."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any, cast
from uuid import UUID
import zipfile
from xml.sax.saxutils import escape, quoteattr

from .archive_builder import ExportError, json_bytes
from .context import owned_context
from .files import file_record, resource_files, verified_payload
from .format.source_workflows import derive
from .repository import resources


class WorkflowNotFound(LookupError):
    """The requested workflow view does not belong to the selected version."""


RUN_FIELDS = (
    "workflow_id",
    "operation",
    "mode",
    "state",
    "safe_input_manifest",
    "accepted_plan_digest",
    "error_summary",
    "created_at",
    "started_at",
    "finished_at",
    "terminal_result_digest",
    "ai_model_snapshot",
    "prism_source_digest",
    "imported",
)


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return value[:120] or "workflow"


def _svg_label(node: dict[str, Any]) -> str:
    return str(
        node.get("method")
        or node.get("label")
        or node.get("output_type")
        or node.get("id")
        or "Step"
    )


def _graph_svg(workflow: dict[str, Any]) -> bytes:
    """Render a stable, dependency-layered SVG from the authoritative graph."""

    graph = workflow["graph"]
    nodes = list(graph.get("nodes", []))
    by_id = {str(node["id"]): node for node in nodes}
    edges = [
        edge
        for edge in graph.get("edges", [])
        if str(edge.get("source")) in by_id and str(edge.get("target")) in by_id
    ]
    incoming = {identity: set() for identity in by_id}
    outgoing = {identity: [] for identity in by_id}
    for edge in edges:
        source, target = str(edge["source"]), str(edge["target"])
        if source != target:
            incoming[target].add(source)
            outgoing[source].append(target)
    ranks = {identity: 0 for identity, parents in incoming.items() if not parents}
    queue = list(ranks)
    while queue:
        source = queue.pop(0)
        for target in outgoing[source]:
            ranks[target] = max(ranks.get(target, 0), ranks[source] + 1)
            incoming[target].discard(source)
            if not incoming[target] and target not in queue:
                queue.append(target)
    # Cycles retain their authored order in one final layer instead of changing
    # or inventing graph topology.
    final_rank = max(ranks.values(), default=-1) + 1
    for node in nodes:
        ranks.setdefault(str(node["id"]), final_rank)
    layers: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        layers.setdefault(ranks[str(node["id"])], []).append(node)

    node_width, node_height = 240, 76
    left, top, column_gap, row_gap = 54, 104, 110, 38
    max_rows = max((len(layer) for layer in layers.values()), default=1)
    width = max(
        520,
        left * 2
        + (max(layers, default=0) + 1) * node_width
        + max(0, len(layers) - 1) * column_gap,
    )
    height = max(
        260, top + max_rows * node_height + max(0, max_rows - 1) * row_gap + 64
    )
    positions: dict[str, tuple[int, int]] = {}
    for rank, layer in sorted(layers.items()):
        total = len(layer) * node_height + max(0, len(layer) - 1) * row_gap
        offset = top + max(0, (height - top - 64 - total) // 2)
        for index, node in enumerate(layer):
            positions[str(node["id"])] = (
                left + rank * (node_width + column_gap),
                offset + index * (node_height + row_gap),
            )

    title = escape(
        str(workflow.get("label") or graph.get("reasoning") or workflow["id"])
    )
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{title}</title>',
        '<desc id="desc">Lunar workflow visualization exported from the source-derived PRISM graph.</desc>',
        "<defs>",
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{left}" y="48" font-family="system-ui, sans-serif" font-size="24" font-weight="700" fill="#0f172a">{title}</text>',
    ]
    for edge in edges:
        source_id, target_id = str(edge["source"]), str(edge["target"])
        source_x, source_y = positions[source_id]
        target_x, target_y = positions[target_id]
        if source_id == target_id:
            path = (
                f"M {source_x + node_width} {source_y + node_height // 2} "
                f"C {source_x + node_width + 72} {source_y - 42}, "
                f"{source_x + node_width + 72} {source_y + node_height + 42}, "
                f"{source_x + node_width} {source_y + node_height // 2}"
            )
        else:
            start_x, start_y = source_x + node_width, source_y + node_height // 2
            end_x, end_y = target_x, target_y + node_height // 2
            control = max(46, abs(end_x - start_x) // 2)
            path = (
                f"M {start_x} {start_y} C {start_x + control} {start_y}, "
                f"{end_x - control} {end_y}, {end_x} {end_y}"
            )
        relation = escape(str(edge.get("label") or edge.get("kind") or ""))
        parts.append(
            f'<path d="{path}" fill="none" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"><title>{relation}</title></path>'
        )
    for node in nodes:
        identity = str(node["id"])
        x, y = positions[identity]
        kind = str(node.get("kind", "step"))
        fill = {"input": "#e0f2fe", "result": "#dcfce7", "topology": "#fef3c7"}.get(
            kind, "#ffffff"
        )
        label = escape(_svg_label(node)[:80])
        detail = escape(str(node.get("output_type") or kind)[:96])
        parts.extend(
            [
                f"<g id={quoteattr('node-' + identity)}>",
                f'<rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" rx="12" fill="{fill}" stroke="#94a3b8" stroke-width="1.5"/>',
                f'<text x="{x + 16}" y="{y + 31}" font-family="system-ui, sans-serif" font-size="15" font-weight="650" fill="#0f172a">{label}</text>',
                f'<text x="{x + 16}" y="{y + 55}" font-family="ui-monospace, monospace" font-size="12" fill="#475569">{detail}</text>',
                "</g>",
            ]
        )
    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _add(files: dict[str, bytes], path: str, value: Any) -> str:
    raw = value if isinstance(value, bytes) else json_bytes(value)
    existing = files.setdefault(path, raw)
    if existing != raw:
        raise ExportError(f"conflicting workflow export payload: {path}")
    return path


def _publish(
    destination: Path, files: dict[str, bytes], manifest: dict[str, Any]
) -> None:
    """Write a deterministic ZIP after its complete digest inventory is known."""

    if destination.exists():
        raise ExportError(f"export destination already exists: {destination}")
    manifest["files"] = [
        {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(files.items())
    ]
    payloads = {"manifest.json": json_bytes(manifest), **files}
    with zipfile.ZipFile(
        destination,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path, content in sorted(payloads.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)


async def _source_projection(
    connection, storage, context
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repository_rows = await resources(connection, context, "repository")
    declarations = []
    descriptions = []
    payloads: dict[str, bytes] = {}
    for row in repository_rows:
        document = row["document"]
        if isinstance(document, str):
            document = json.loads(document)
        linked = await resource_files(connection, context, row["id"])
        paths = []
        for item in linked:
            if not item["path"].endswith(".prism"):
                continue
            record = await file_record(connection, context, item["id"])
            if record is None:
                raise ExportError("Workflow source file is missing")
            payload = verified_payload(record, storage, context)
            payloads[item["path"]] = (
                payload if isinstance(payload, bytes) else payload.read_bytes()
            )
            paths.append(item["path"])
        declarations.append({"id": document["id"], "files": paths})
        descriptions.append(document)
    projected = {"collections": {"repository": declarations}}
    return cast(
        tuple[dict[str, Any], list[dict[str, Any]]],
        await asyncio.to_thread(derive, projected, payloads, descriptions),
    )


async def export_workflow(
    connection,
    storage,
    *,
    user_id,
    version_id,
    workflow_id: str,
    workspace: Path,
):
    """Export one source-derived workflow view and its observed provenance closure."""

    await connection.set_type_codec(
        "jsonb", schema="pg_catalog", encoder=json.dumps, decoder=json.loads
    )
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            context = await owned_context(connection, user_id, version_id)
            package = await connection.fetchrow(
                """SELECT v.archive_digest,transaction_timestamp() AS snapshot_at,
                          p.package_key,p.display_name
                   FROM package_versions v JOIN domain_packages p
                     ON p.id=v.package_id AND p.user_id=v.user_id
                   WHERE v.id=$1 AND v.user_id=$2""",
                version_id,
                user_id,
            )
            if package is None:
                raise WorkflowNotFound("Workflow not found")
            bundle, registrations = await _source_projection(
                connection, storage, context
            )
            view_id = workflow_id
            matches = [
                (project, workflow)
                for project in bundle["projects"]
                for workflow in project["workflows"]
                if workflow["id"] == view_id
            ]
            if not matches:
                bound_views = {
                    row.get("metadata", {}).get("viewer_workflow_id")
                    for row in registrations
                    if row["id"] == workflow_id
                }
                bound_views.discard(None)
                if len(bound_views) == 1:
                    (view_id,) = bound_views
                    matches = [
                        (project, workflow)
                        for project in bundle["projects"]
                        for workflow in project["workflows"]
                        if workflow["id"] == view_id
                    ]
            if len(matches) != 1:
                raise WorkflowNotFound("Workflow not found")
            project, workflow = matches[0]
            bindings = [
                deepcopy(row)
                for row in registrations
                if row.get("metadata", {}).get("viewer_workflow_id") == view_id
            ]
            execution_ids = sorted({row["id"] for row in bindings})
            runs = (
                await connection.fetch(
                    """SELECT * FROM prism_runs
                       WHERE user_id=$1 AND version_id=$2 AND workflow_id=ANY($3::text[])
                       ORDER BY created_at,id""",
                    user_id,
                    version_id,
                    execution_ids,
                )
                if execution_ids
                else []
            )

            files: dict[str, bytes] = {}
            visualization_path = _add(
                files,
                "visualization.json",
                {
                    "kind": bundle["kind"],
                    "schema_version": bundle["schema_version"],
                    "projects": [
                        {
                            "id": project["id"],
                            "label": project.get("label", project["id"]),
                            "workflows": [workflow],
                        }
                    ],
                },
            )
            visualization_svg_path = _add(
                files, "visualization.svg", _graph_svg(workflow)
            )
            source_paths = []
            for source in workflow["sources"]:
                path = "sources/" + source["path"]
                source_paths.append(
                    _add(files, path, source["content"].encode("utf-8"))
                )
            bindings_path = _add(
                files,
                "execution-bindings.json",
                {"workflow_view_id": view_id, "bindings": bindings},
            )

            run_entries = []
            for row in runs:
                run_id = str(row["id"])
                run_path = _add(
                    files,
                    f"runs/{run_id}.json",
                    {
                        "id": run_id,
                        **{
                            field: _plain(row.get(field))
                            for field in RUN_FIELDS
                            if field in row
                        },
                    },
                )
                provenance_entries = []
                provenance = await connection.fetch(
                    """SELECT format,media_type,document,wrapper_digest,generated_at
                       FROM prism_run_provenance_exports
                       WHERE run_id=$1 AND user_id=$2 AND version_id=$3
                       ORDER BY format""",
                    row["id"],
                    user_id,
                    version_id,
                )
                for item in provenance:
                    path = _add(
                        files,
                        f"provenance/{run_id}/{item['format']}.json",
                        item["document"],
                    )
                    provenance_entries.append(
                        {
                            "format": item["format"],
                            "media_type": item["media_type"],
                            "path": path,
                            "wrapper_digest": item["wrapper_digest"],
                            "generated_at": _plain(item["generated_at"]),
                        }
                    )
                run_entries.append(
                    {
                        "id": run_id,
                        "workflow_id": row["workflow_id"],
                        "state": row["state"],
                        "summary": run_path,
                        "provenance": provenance_entries,
                    }
                )

            snapshot_at = _plain(package["snapshot_at"])
            export_manifest = {
                "schema_version": "lunar.workflow-export/v1",
                "source_package": {
                    "key": package["package_key"],
                    "display_name": package["display_name"],
                    "version": context.version,
                    "version_id": str(context.version_id),
                    "archive_digest": package["archive_digest"],
                },
                "snapshot_at": snapshot_at,
                "workflow": {
                    "id": view_id,
                    "requested_id": workflow_id,
                    "label": workflow.get("label", view_id),
                    "project_id": project["id"],
                    "visualization": visualization_path,
                    "visualization_svg": visualization_svg_path,
                    "execution_bindings": bindings_path,
                    "sources": source_paths,
                    "execution_ids": execution_ids,
                },
                "runs": run_entries,
            }
            destination = workspace / "workflow.zip"
            await asyncio.to_thread(_publish, destination, files, export_manifest)
            return destination, {
                "source_archive_digest": package["archive_digest"],
                "snapshot_at": snapshot_at,
                "version": context.version,
                "package_key": package["package_key"],
                "workflow_id": view_id,
                "workflow_name": _safe_name(workflow.get("label", view_id)),
            }
    finally:
        await connection.reset_type_codec("jsonb", schema="pg_catalog")
