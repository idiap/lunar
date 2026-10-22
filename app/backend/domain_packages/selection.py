# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit no-selection boundary shared by HTTP and planning."""

from .context import CURRENT_VERSION as CURRENT_VERSION
from starlette.responses import JSONResponse
from modules.common import authenticated_user

SELECTION_MESSAGE = (
    "Import and select a package version before using package resources."
)


async def selection_required(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    return JSONResponse(
        {"error": SELECTION_MESSAGE, "code": "selection_required"}, status_code=409
    )


def register_unselected_routes(mcp):
    for path, methods in RESOURCE_ROUTES:
        if not path.startswith("/api/repository"):
            continue
        mcp.custom_route(path, methods=methods)(selection_required)


RESOURCE_ROUTES = [
    ("/api/data-sources", ["GET"]),
    ("/api/data-sources/{resource_id}", ["GET"]),
    ("/api/prism/workflows", ["GET"]),
    ("/api/prism/workflows/{workflow_id}/runs", ["POST"]),
    ("/api/prism/runs", ["GET"]),
    ("/api/prism/runs/reasoning", ["GET"]),
    ("/api/prism/runs/{run_id}", ["GET"]),
    ("/api/prism/runs/{run_id}/stop", ["POST"]),
    ("/api/prism/runs/{run_id}/artifacts/{artifact_id}", ["GET"]),
    ("/api/prism/runs/{run_id}", ["DELETE"]),
    ("/api/prism/runs/{run_id}/provenance", ["GET"]),
    ("/api/templates/{template_id}/outputs", ["GET"]),
    ("/api/templates/{template_id}/runs", ["POST"]),
    ("/api/report/{report_id}/provenance", ["GET"]),
    ("/api/report/{report_id}/sections/{section_id}/provenance", ["GET"]),
    ("/api/skills", ["GET"]),
    ("/api/skills/{skill_id}", ["GET"]),
    ("/api/repository/catalog", ["GET"]),
    ("/api/repository/bundle", ["GET"]),
]
