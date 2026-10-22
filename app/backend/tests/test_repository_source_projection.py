# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""The viewer endpoint always regenerates graphs from owned source bytes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from domain_packages import repository_routes as module

SOURCE = b"""type Step = (value: Int) -> Int
reasoning ActualSource(request: Int) -> Int:
    [result: Step(request)]
    return result
"""


def test_endpoint_ignores_legacy_graph_and_resolves_shared_modules(monkeypatch):
    context = SimpleNamespace(version_id="selected-version")
    request = SimpleNamespace(query_params={})
    connection = AsyncMock()
    monkeypatch.setattr(
        module, "authenticated_user", AsyncMock(return_value={"id": "owner"})
    )
    monkeypatch.setattr(module, "require_context", lambda _: context)
    monkeypatch.setattr(module, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        module,
        "resources",
        AsyncMock(
            return_value=[
                {
                    "id": "local",
                    "document": {
                        "id": "project",
                        "name": "Project",
                        "metadata": {"bundle": "repository/stale.json"},
                    },
                }
            ]
        ),
    )
    monkeypatch.setattr(
        module,
        "resource_files",
        AsyncMock(
            return_value=[
                {"id": "source", "path": "repository/main.prism"},
                {"id": "stale", "path": "repository/stale.json"},
            ]
        ),
    )
    records = AsyncMock(return_value={"payload": SOURCE})
    monkeypatch.setattr(module, "file_record", records)
    monkeypatch.setattr(module, "configured_storage", lambda: None)
    monkeypatch.setattr(
        module, "verified_payload", lambda row, storage, owner: row["payload"]
    )
    response = asyncio.run(module.repository_bundle(request))
    import json

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["projects"][0]["workflows"][0]["graph"]["reasoning"] == "ActualSource"
    assert records.call_args.args == (connection, context, "source")
    records.return_value = {"payload": b"reasoning invalid\n"}
    assert asyncio.run(module.repository_bundle(request)).status_code == 409
