# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bind an explicit authenticated package selection for the entire ASGI response."""

from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import ReportTokenVerifier
from modules.common import authenticated_user, connect
from .context import bind_context, owned_context, VersionNotFound
from .selection import SELECTION_MESSAGE

HEADER = "x-lunar-package-version"
QUERY = "package_version_id"


def package_route(path):
    roots = (
        "/api/skills",
        "/api/data-sources",
        "/api/repository",
        "/api/prism",
        "/api/report",
        "/api/reports",
        "/api/package-files",
    )
    return any(path == root or path.startswith(root + "/") for root in roots) or (
        path.startswith("/api/templates/") and path.endswith(("/runs", "/outputs"))
    )


class PackageSelectionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        required = package_route(path)
        optional = path in {
            "/mcp",
            "/mcp/",
            "/api/chat",
            "/api/chat/tools",
            "/api/chats",
        } or path.startswith("/api/chats/")
        if not required and not optional:
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        headers = request.headers.getlist(HEADER)
        queries = request.query_params.getlist(QUERY)
        if (
            len(headers) > 1
            or len(queries) > 1
            or (headers and queries and headers[0] != queries[0])
        ):
            return await JSONResponse(
                {"error": "Conflicting package selections"}, status_code=400
            )(scope, receive, send)
        selection = (headers or queries or [None])[0]
        if not required and selection is None:
            with bind_context(None):
                return await self.app(scope, receive, send)
        if path.rstrip("/") == "/mcp":
            authorization = request.headers.get("authorization", "")
            token = (
                await ReportTokenVerifier().verify_token(authorization[7:])
                if authorization.lower().startswith("bearer ")
                else None
            )
            user = {"id": UUID(token.subject)} if token else None
            if user is None:
                return await JSONResponse(
                    {"error": "Not authenticated"}, status_code=401
                )(scope, receive, send)
        else:
            user = await authenticated_user(request)
            if isinstance(user, JSONResponse):
                return await user(scope, receive, send)
        if selection is None:
            return await JSONResponse(
                {"error": SELECTION_MESSAGE, "code": "selection_required"},
                status_code=409,
            )(scope, receive, send)
        try:
            version_id = UUID(selection)
        except ValueError:
            return await JSONResponse(
                {"error": "Invalid package selection"}, status_code=400
            )(scope, receive, send)
        connection = await connect()
        try:
            context = await owned_context(connection, user["id"], version_id)
        except VersionNotFound:
            return await JSONResponse(
                {"error": "Package version not found"}, status_code=404
            )(scope, receive, send)
        finally:
            await connection.close()
        request.state.package_context = context
        request.state.authenticated_user = user
        with bind_context(context):
            await self.app(scope, receive, send)
