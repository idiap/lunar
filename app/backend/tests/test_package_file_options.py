# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bounded inventory search without runtime execution or filesystem traversal."""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

from starlette.requests import Request
from domain_packages import files
from domain_packages.context import PackageContext, bind_context


def test_search_is_bounded_and_owner_version_scoped(monkeypatch):
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    records = [
        {
            "id": uuid4(),
            "path": f"repository/{i}.txt",
            "sha256": "a" * 64,
            "size": 1,
            "media_type": "text/plain",
        }
        for i in range(41)
    ]
    connection = AsyncMock()
    connection.fetch.return_value = records
    monkeypatch.setattr(files, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        files, "authenticated_user", AsyncMock(return_value={"id": context.user_id})
    )
    request = Request(
        {
            "type": "http",
            "query_string": b"query=some%25name&prefix=repository%2F&extensions=.txt",
        }
    )
    with bind_context(context):
        response = asyncio.run(files.package_file_options(request))
    result = json.loads(bytes(response.body))
    assert len(result["items"]) == 40 and result["has_more"] is True
    assert "payload" not in result["items"][0]
    assert str(context.version_id) in result["items"][0]["url"]
    sql, *parameters = connection.fetch.call_args.args
    assert "user_id=$1 AND version_id=$2" in sql and "LIMIT 41 OFFSET $6" in sql
    assert (
        "strpos" in sql
    )  # Percent and underscore searches are literal, not SQL wildcards.
    assert parameters == [
        context.user_id,
        context.version_id,
        "some%name",
        "repository/",
        [".txt"],
        0,
    ]
    connection.close.assert_awaited_once()


def test_rejects_unbounded_search_before_querying(monkeypatch):
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    connect = AsyncMock()
    monkeypatch.setattr(files, "connect", connect)
    monkeypatch.setattr(
        files, "authenticated_user", AsyncMock(return_value={"id": context.user_id})
    )
    with bind_context(context):
        for query in [
            b"query=" + b"x" * 201,
            b"prefix=" + b"x" * 501,
            b"extensions=../secret",
        ]:
            response = asyncio.run(
                files.package_file_options(
                    Request({"type": "http", "query_string": query})
                )
            )
            assert response.status_code == 400
    connect.assert_not_awaited()
