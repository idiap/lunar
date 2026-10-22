# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Historical run reads remain bound to the selected package and owner."""

import asyncio
import asyncpg
import auth
import modules.common as common
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from prism_runs.routes import (
    prism_run_list,
    prism_run_detail,
    prism_reasoning_stream,
    prism_run_artifact,
    workflow_list,
)
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_resource_api import variant
from test_package_importer import user


def test_historical_run_api_and_reasoning_selection(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            contexts = []
            rows = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                context = await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=variant(tmp_path, index),
                )
                contexts.append(context)
                rows.append(
                    dict(
                        await connection.fetchrow(
                            "SELECT id,workflow_id FROM prism_runs WHERE user_id=$1 AND version_id=$2",
                            owner,
                            context.version_id,
                        )
                    )
                )
            return (
                contexts,
                rows,
                [await auth.create_session(owner) for owner in owners],
            )
        finally:
            await connection.close()

    contexts, rows, tokens = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/prism/workflows", workflow_list),
            Route("/api/prism/runs", prism_run_list),
            Route("/api/prism/runs/reasoning", prism_reasoning_stream),
            Route("/api/prism/runs/{run_id}", prism_run_detail),
            Route(
                "/api/prism/runs/{run_id}/artifacts/{artifact_id}", prism_run_artifact
            ),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        for index in range(2):
            query = {"package_version_id": str(contexts[index].version_id)}
            listing = client.get("/api/prism/runs", params=query)
            assert listing.status_code == 200, listing.text
            assert listing.json()["total"] == 1
            run = listing.json()["items"][0]
            assert run["id"] == str(rows[index]["id"]) and run["imported"] is True
            assert run["state"] == "completed"
            detail = client.get("/api/prism/runs/" + run["id"], params=query)
            assert detail.status_code == 200, detail.text
            assert detail.json()["outputs"][0]["markdown"] == "Three boxes."
            assert "artifact_root" not in detail.json()
            reasoning = client.get(
                "/api/prism/runs/reasoning",
                params={
                    **query,
                    "run_ids": run["id"],
                    "workflow_id": rows[index]["workflow_id"],
                },
            )
            assert reasoning.status_code == 200, reasoning.text
            assert (
                '"state":"completed"' in reasoning.text
                and '"type":"done"' in reasoning.text
            )
            for other in range(3):
                if other == index:
                    continue
                assert (
                    client.get(
                        "/api/prism/runs/" + str(rows[other]["id"]), params=query
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        "/api/prism/runs/reasoning",
                        params={
                            **query,
                            "run_ids": str(rows[other]["id"]),
                            "workflow_id": rows[other]["workflow_id"],
                        },
                    ).status_code
                    == 404
                )
            workflows = client.get("/api/prism/workflows", params=query)
            assert workflows.status_code == 200, workflows.text
            assert not any(item.get("historical_only") for item in workflows.json())
        assert (
            client.get(
                "/api/prism/runs",
                params={"package_version_id": str(contexts[2].version_id)},
            ).status_code
            == 404
        )
