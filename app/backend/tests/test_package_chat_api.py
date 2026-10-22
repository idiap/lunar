# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Saved chats cannot be retargeted by changing the active package selection."""

import asyncio
import asyncpg
import auth
import modules.common as common
from modules.chat import (
    _create_chat,
    _save_chat_messages,
    list_chats,
    get_chat,
    delete_chat,
    chat_context,
)
from domain_packages.context import bind_context
from domain_packages.routes import prepare_package
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_importer import user, staged
import pytest


def test_chat_history_and_mutations_keep_original_selection(
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
            chats = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                context = await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=staged(tmp_path, str(index)),
                )
                contexts.append(context)
                with bind_context(context):
                    chats.append(
                        await _create_chat(
                            owner,
                            "Chat " + str(index),
                            [{"role": "user", "content": str(index)}],
                        )
                    )
            with bind_context(None):
                plain = await _create_chat(
                    owners[0], "Plain chat", [{"role": "user", "content": "Hello"}]
                )
            with bind_context(contexts[1]):
                with pytest.raises(ValueError, match="Chat not found"):
                    await _save_chat_messages(
                        chats[0]["id"],
                        owners[0],
                        [{"role": "user", "content": "overwritten"}],
                    )
            with bind_context(contexts[0]):
                saved = await _save_chat_messages(
                    chats[0]["id"],
                    owners[0],
                    [{"role": "user", "content": "Original version"}],
                )
                assert saved["version_id"] == str(contexts[0].version_id)
            return contexts, chats, plain, await auth.create_session(owners[0])
        finally:
            await connection.close()

    contexts, chats, plain, token = asyncio.run(setup())
    assert plain is not None
    app = Starlette(
        routes=[
            Route(
                "/api/packages/versions/{version_id}/prepare",
                prepare_package,
                methods=["POST"],
            ),
            Route("/api/chats/{chat_id}/context", chat_context),
            Route("/api/chats", list_chats),
            Route("/api/chats/{chat_id}", get_chat),
            Route("/api/chats/{chat_id}", delete_chat, methods=["DELETE"]),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        assert [row["id"] for row in client.get("/api/chats").json()] == [
            str(plain["id"])
        ]
        for index in range(2):
            header = {"X-Lunar-Package-Version": str(contexts[index].version_id)}
            listing = client.get("/api/chats", headers=header).json()
            assert len(listing) == 1 and listing[0]["id"] == str(chats[index]["id"])
            assert listing[0]["version_id"] == str(contexts[index].version_id)
            own = client.get("/api/chats/" + str(chats[index]["id"]), headers=header)
            assert own.status_code == 200 and own.json()["messages"]
            for other in range(3):
                if index == other:
                    continue
                assert (
                    client.get(
                        "/api/chats/" + str(chats[other]["id"]), headers=header
                    ).status_code
                    == 404
                )
                assert (
                    client.delete(
                        "/api/chats/" + str(chats[other]["id"]), headers=header
                    ).status_code
                    == 404
                )
            assert (
                client.get("/api/chats/" + str(plain["id"]), headers=header).status_code
                == 404
            )
        assert client.get("/api/chats/" + str(chats[0]["id"])).status_code == 404
        for index in range(2):
            result = client.get("/api/chats/" + str(chats[index]["id"]) + "/context")
            assert result.status_code == 200 and result.json() == {
                "version_id": str(contexts[index].version_id)
            }
        assert (
            client.get("/api/chats/" + str(chats[2]["id"]) + "/context").status_code
            == 404
        )

        monkeypatch.delenv("LUNAR_WORKER_IMAGE", raising=False)
        assert (
            client.post(
                "/api/packages/versions/" + str(contexts[2].version_id) + "/prepare"
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/packages/versions/" + str(contexts[0].version_id) + "/prepare",
                json={"base_image": "untrusted"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/packages/versions/" + str(contexts[0].version_id) + "/prepare"
            ).status_code
            == 503
        )
