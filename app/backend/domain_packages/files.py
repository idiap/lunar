# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Owned file identities, verified bytes, and protected package downloads."""

import hashlib
from urllib.parse import urlencode
from uuid import UUID

from starlette.responses import Response, FileResponse, JSONResponse
from modules.common import authenticated_user, connect, record_json
from .context import require_context
from .routes import configured_storage


async def package_file_options(request):
    """Search only the selected owner's imported inventory, never the host filesystem."""
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    query = request.query_params.get("query", "")
    prefix = request.query_params.get("prefix", "")
    try:
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        return JSONResponse({"error": "Invalid file search"}, status_code=400)
    extensions = [
        part.lower()
        for part in request.query_params.get("extensions", "").split(",")
        if part
    ]
    if (
        offset < 0
        or offset > 2147483647
        or len(query) > 200
        or len(prefix) > 500
        or len(extensions) > 20
        or any(
            not part.startswith(".")
            or len(part) > 20
            or not part[1:].replace(".", "").isalnum()
            for part in extensions
        )
    ):
        return JSONResponse({"error": "Invalid file search"}, status_code=400)
    connection = await connect()
    try:
        rows = await connection.fetch(
            """SELECT id,path,size,sha256,media_type FROM package_files
            WHERE user_id=$1 AND version_id=$2
            AND strpos(lower(path),lower($3)) > 0 AND starts_with(path,$4)
            AND (cardinality($5::text[])=0 OR EXISTS
                (SELECT 1 FROM unnest($5::text[]) ext WHERE right(lower(path),length(ext))=ext))
            ORDER BY path LIMIT 41 OFFSET $6""",
            context.user_id,
            context.version_id,
            query,
            prefix,
            extensions,
            offset,
        )
        return JSONResponse(
            {
                "items": [
                    {**record_json(row), "url": file_url(context, row["id"])}
                    for row in rows[:40]
                ],
                "has_more": len(rows) > 40,
            },
            headers={"Cache-Control": "private, no-cache"},
        )
    finally:
        await connection.close()


def file_url(context, file_id):
    return (
        "/api/package-files/"
        + str(file_id)
        + "?"
        + urlencode({"package_version_id": str(context.version_id)})
    )


async def resource_files(connection, context, resource_id):
    rows = await connection.fetch(
        """SELECT f.id,f.path,f.size,f.sha256,f.media_type
        FROM package_files f JOIN package_resource_files links ON links.file_id=f.id
        AND links.version_id=f.version_id AND links.user_id=f.user_id
        WHERE links.resource_id=$1 AND f.version_id=$2 AND f.user_id=$3 ORDER BY f.path""",
        resource_id,
        context.version_id,
        context.user_id,
    )
    return [{**record_json(row), "url": file_url(context, row["id"])} for row in rows]


async def file_record(connection, context, file_id):
    return await connection.fetchrow(
        "SELECT * FROM package_files WHERE id=$1 AND version_id=$2 AND user_id=$3",
        file_id,
        context.version_id,
        context.user_id,
    )


def verified_payload(record, storage, context):
    if record["storage_kind"] == "database":
        data = bytes(record["payload"])
        if (
            len(data) != record["size"]
            or hashlib.sha256(data).hexdigest() != record["sha256"]
        ):
            raise ValueError("Package file bytes differ from the imported receipt")
        return data
    path = storage.package_file(context, record["path"])
    if not path.is_file() or path.stat().st_size != record["size"]:
        raise ValueError("Package file bytes differ from the imported receipt")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != record["sha256"]:
        raise ValueError("Package file bytes differ from the imported receipt")
    return path


async def package_file(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    try:
        identity = UUID(request.path_params["file_id"])
    except ValueError:
        return JSONResponse({"error": "File not found"}, status_code=404)
    connection = await connect()
    try:
        row = await file_record(connection, context, identity)
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        payload = verified_payload(row, configured_storage(), context)
    except (ValueError, OSError):
        return JSONResponse(
            {"error": "Package file integrity check failed"}, status_code=409
        )
    headers = {
        "ETag": '"' + row["sha256"] + '"',
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    inline = row["media_type"] in {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "text/plain",
        "application/json",
    }
    filename = row["path"].rsplit("/", 1)[-1]
    if isinstance(payload, bytes):
        response = Response(payload, media_type=row["media_type"], headers=headers)
        from urllib.parse import quote

        response.headers["Content-Disposition"] = (
            ("inline" if inline else "attachment")
            + "; filename*=utf-8''"
            + quote(filename)
        )
        return response
    return FileResponse(
        payload,
        media_type=row["media_type"],
        filename=filename,
        headers=headers,
        content_disposition_type="inline" if inline else "attachment",
    )


def register_file_routes(mcp):
    mcp.custom_route("/api/package-files", methods=["GET"])(package_file_options)
    mcp.custom_route("/api/package-files/{file_id}", methods=["GET"])(package_file)
