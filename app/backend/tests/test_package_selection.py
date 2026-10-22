# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated selections remain bound through streaming and cannot cross owners."""

import asyncio
from uuid import uuid4

import asyncpg
import auth
import modules.common as common
from domain_packages.context import CURRENT_VERSION
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_importer import user, staged


def test_http_and_mcp_selection_require_owned_explicit_versions(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(auth, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(common, "DATABASE_URL", postgres_url)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            storage = VersionStorage(tmp_path / "store")
            versions = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                versions.append(
                    await import_validated(
                        connection,
                        storage,
                        user_id=owner,
                        archive=staged(tmp_path, str(index)),
                    )
                )
            tokens = [await auth.create_session(owner) for owner in owners]
            return owners, versions, tokens
        finally:
            await connection.close()

    owners, versions, tokens = asyncio.run(setup())

    async def selected(request):
        context = CURRENT_VERSION.get()
        return JSONResponse(
            {"version_id": str(context.version_id) if context else None}
        )

    async def stream(request):
        async def values():
            await asyncio.sleep(0)
            context = CURRENT_VERSION.get()
            assert context is not None
            yield str(context.version_id)

        return StreamingResponse(values())

    app = Starlette(
        routes=[
            Route("/api/skills", selected),
            Route("/api/prism/stream", stream),
            Route("/api/chat", selected),
            Route("/mcp", selected),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        assert client.get("/api/skills").status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        assert client.get("/api/skills").status_code == 409
        assert (
            client.get(
                "/api/skills",
                headers={"X-Lunar-Package-Version": str(versions[2].version_id)},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/skills", headers={"X-Lunar-Package-Version": str(uuid4())}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/skills", headers={"X-Lunar-Package-Version": "invalid"}
            ).status_code
            == 400
        )
        for version in versions[:2]:
            header = {"X-Lunar-Package-Version": str(version.version_id)}
            assert client.get("/api/skills", headers=header).json() == {
                "version_id": str(version.version_id)
            }
            assert client.get("/api/prism/stream", headers=header).text == str(
                version.version_id
            )
            assert client.get(
                "/api/prism/stream",
                params={"package_version_id": str(version.version_id)},
            ).text == str(version.version_id)
        assert (
            client.get(
                "/api/skills",
                headers={"X-Lunar-Package-Version": str(versions[0].version_id)},
                params={"package_version_id": str(versions[1].version_id)},
            ).status_code
            == 400
        )
        assert client.get("/api/chat").json() == {"version_id": None}
        client.cookies.clear()
        header = {
            "Authorization": "Bearer " + auth.mcp_token_for_user(str(owners[0])),
            "X-Lunar-Package-Version": str(versions[0].version_id),
        }
        assert client.get("/mcp", headers=header).json() == {
            "version_id": str(versions[0].version_id)
        }
        header["X-Lunar-Package-Version"] = str(versions[2].version_id)
        assert client.get("/mcp", headers=header).status_code == 404
    assert CURRENT_VERSION.get() is None
