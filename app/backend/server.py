# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Lunar's domain-independent application shell."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from pydantic import AnyHttpUrl

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from auth import ReportTokenVerifier, register_auth_routes
from config import (
    API_RATE_LIMIT_REQUESTS,
    API_RATE_LIMIT_WINDOW_SECONDS,
    FRONTEND_ORIGIN,
    PUBLIC_BASE_URL,
)
from control_plane.quality_runtime import configure_quality_runtime, get_quality_runtime
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.files import register_file_routes
from skills.routes import register_skill_routes
from data_sources.routes import register_data_source_routes
from domain_packages.repository_routes import register_repository_routes
from domain_packages.export_routes import register_export_routes
from domain_packages.routes import register_package_routes, recover_package_imports
from modules.ai_models import register_ai_model_routes
from modules.chat import LUNAR_INSTRUCTIONS, register_chat_routes
from modules.prompts import register_prompt_routes
from modules.reports import register_management_report_routes
from modules.templates import register_template_routes
from planner import register_planner_tool
from rate_limit import RateLimitMiddleware
from reports import register_report_routes
from prism_runs.routes import register_prism_run_routes
from provenance.routes import register_provenance_routes
from reporting.routes import register_reporting_routes

configure_quality_runtime(os.getenv("LUNAR_PROFILE", "local"))

public_host = urlparse(PUBLIC_BASE_URL).netloc
mcp = FastMCP(
    "lunar",
    instructions=LUNAR_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[public_host, "backend:8000", "localhost:*", "127.0.0.1:*"],
        allowed_origins=list({PUBLIC_BASE_URL, FRONTEND_ORIGIN}),
    ),
    token_verifier=ReportTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(PUBLIC_BASE_URL),
        resource_server_url=AnyHttpUrl(f"{PUBLIC_BASE_URL}/mcp"),
        required_scopes=["reports:create"],
    ),
)
for register in (
    register_auth_routes,
    register_planner_tool,
    register_report_routes,
    register_prompt_routes,
    register_management_report_routes,
    register_template_routes,
    register_ai_model_routes,
    register_chat_routes,
    register_repository_routes,
    register_package_routes,
    register_export_routes,
    register_file_routes,
    register_skill_routes,
    register_data_source_routes,
    register_prism_run_routes,
    register_provenance_routes,
    register_reporting_routes,
):
    register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
_mcp_lifespan = app.router.lifespan_context


async def prepare_application():
    """Recover interrupted imports without installing or executing any domain."""
    await recover_package_imports()
    from prism_runs.service import recover_runs

    await recover_runs()
    from modules.common import connect
    from prism_runs.reasoning_repository import recover_presentations

    connection = await connect()
    try:
        await recover_presentations(connection)
    finally:
        await connection.close()


@asynccontextmanager
async def application_lifespan(application):
    async with _mcp_lifespan(application):
        await prepare_application()
        yield


app.router.lifespan_context = application_lifespan
app.add_middleware(PackageSelectionMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests=API_RATE_LIMIT_REQUESTS,
    window_seconds=API_RATE_LIMIT_WINDOW_SECONDS,
)
if FRONTEND_ORIGIN != PUBLIC_BASE_URL:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Lunar MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MCP_PORT", "8000"))
    )
    parser.add_argument("--path", default=os.environ.get("MCP_PATH", "/mcp"))
    parser.add_argument(
        "--profile",
        choices=("local", "production"),
        default=os.getenv("LUNAR_PROFILE", "local"),
    )
    parser.add_argument("--check", action="store_true")
    return parser


async def _readiness_payload():
    tools = await mcp.list_tools()
    return {
        "service": "lunar",
        "status": "ready",
        "tool_count": len(tools),
        "tool_names": sorted(t.name for t in tools),
        "quality_runtime": get_quality_runtime().public_descriptor(),
    }


async def stdio_context():
    from uuid import UUID
    from domain_packages.context import owned_context
    from modules.common import connect

    owner = os.getenv("LUNAR_STDIO_USER_ID")
    version = os.getenv("LUNAR_STDIO_VERSION_ID")
    if not owner or not version:
        raise ValueError(
            "stdio requires LUNAR_STDIO_USER_ID and LUNAR_STDIO_VERSION_ID"
        )
    owner_id, version_id = UUID(owner), UUID(version)
    connection = await connect()
    try:
        return await owned_context(connection, owner_id, version_id)
    finally:
        await connection.close()


def main(argv=None):
    args = build_parser().parse_args(argv)
    configure_quality_runtime(args.profile)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if not args.path.startswith("/"):
        raise SystemExit("--path must start with '/'")
    if args.check:
        print(json.dumps(asyncio.run(_readiness_payload()), sort_keys=True))
        return
    mcp.settings.host, mcp.settings.port = args.host, args.port
    mcp.settings.streamable_http_path = args.path
    if args.transport == "stdio":
        from domain_packages.context import bind_context

        try:
            context = asyncio.run(stdio_context())
        except (ValueError, LookupError) as error:
            raise SystemExit(str(error)) from None
        with bind_context(context):
            mcp.run(transport=args.transport)
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
