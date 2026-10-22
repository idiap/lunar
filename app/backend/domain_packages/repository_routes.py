# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Inspect declared repository assets through owned, digest-verified package files."""

import json
import asyncio
from typing import Any

from starlette.responses import JSONResponse
from modules.common import authenticated_user, connect, json_value
from domain_packages.context import require_context
from domain_packages.files import resource_files, file_record, verified_payload
from domain_packages.repository import resources
from domain_packages.routes import configured_storage


async def repository_view(request, kind):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    connection = await connect()
    try:
        entries = []
        assets = []
        for row in await resources(connection, context, "repository"):
            document = json_value(row["document"], {})
            files = await resource_files(connection, context, row["id"])
            entries.append({**document, "resource_id": str(row["id"]), "files": files})
            reference = document["metadata"].get(kind) if kind != "bundle" else None
            if reference is not None:
                matching = next(
                    (item for item in files if item["path"] == reference), None
                )
                if matching is None:
                    return JSONResponse(
                        {"error": "Repository asset is not linked to its resource"},
                        status_code=409,
                    )
                if request.query_params.get("repository_id") in {None, document["id"]}:
                    assets.append(matching)
        selected = request.query_params.get("repository_id")
        if selected is not None and not any(row["id"] == selected for row in entries):
            return JSONResponse(
                {"error": "Repository resource not found"}, status_code=404
            )
        if kind == "bundle":
            from .source_workflows import derive
            from .format.contract import PackageValidationError

            payloads = {}
            declarations = []
            try:
                for entry in entries:
                    paths = []
                    for item in entry["files"]:
                        if item["path"].endswith(".prism"):
                            record = await file_record(connection, context, item["id"])
                            raw = verified_payload(
                                record, configured_storage(), context
                            )
                            payloads[item["path"]] = (
                                raw if isinstance(raw, bytes) else raw.read_bytes()
                            )
                            paths.append(item["path"])
                    declarations.append({"id": entry["id"], "files": paths})
                value: dict[str, Any]
                value, _ = await asyncio.to_thread(
                    derive,
                    {"collections": {"repository": declarations}},
                    payloads,
                    entries,
                )
                if selected is not None:
                    value["projects"] = [
                        p for p in value["projects"] if p["id"] == selected
                    ]
            except (PackageValidationError, ValueError, OSError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            return JSONResponse(value, headers={"Cache-Control": "private, no-cache"})
        if len(assets) > 1:
            return JSONResponse(
                {"error": "Select repository_id for this view"}, status_code=400
            )
        if assets:
            record = await file_record(connection, context, assets[0]["id"])
            try:
                payload = verified_payload(record, configured_storage(), context)
                value = json.loads(
                    payload if isinstance(payload, bytes) else payload.read_bytes()
                )
                if not isinstance(value, dict):
                    raise ValueError("object required")
            except (ValueError, OSError):
                return JSONResponse(
                    {"error": "Repository asset integrity check failed"},
                    status_code=409,
                )
        elif kind == "catalog":
            value = {
                "schema_version": 1,
                "visibility": "package",
                "modules": [],
                "skills": [],
            }
        else:
            value = {"kind": "prism-viewer-bundle", "schema_version": 1, "projects": []}
        if kind == "catalog":
            value = {
                **value,
                "resources": entries,
                "version_id": str(context.version_id),
            }
        return JSONResponse(value, headers={"Cache-Control": "private, no-cache"})
    finally:
        await connection.close()


async def repository_catalog(request):
    return await repository_view(request, "catalog")


async def repository_bundle(request):
    return await repository_view(request, "bundle")


def register_repository_routes(mcp):
    mcp.custom_route("/api/repository/catalog", methods=["GET"])(repository_catalog)
    mcp.custom_route("/api/repository/bundle", methods=["GET"])(repository_bundle)
