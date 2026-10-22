# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Typed source selection metadata and its authenticated repository scope."""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from data_sources.repository import get_source, list_sources
from data_sources.serialization import serialize_source, source_selection
from domain_packages.context import PackageContext, SelectionRequired, bind_context


def document(version="v1", **updates):
    return {
        "descriptor": {
            "package_version": version,
            "content_kind": "json",
            "native_schema": {"type": "integer"},
            "digest": "sha256:" + "a" * 64,
            **updates,
        },
        "local_files": [{"id": "payload", "file": "data-sources/count.json"}],
    }


def test_summary_and_detail_expose_identical_selection_without_payload_paths():
    row = {"resource_id": "count", "descriptor": json.dumps(document())}
    summary = serialize_source(row)
    assert summary["selection"] == serialize_source(row, detail=True)["selection"]
    assert summary["selection"] == {
        "reference": {
            "source_id": "count",
            "package_version": "v1",
            "digest": "sha256:" + "a" * 64,
        },
        "content_kind": "json",
        "native_schema": {"type": "integer"},
        "materialized": True,
    }
    assert "descriptor" not in summary
    assert "data-sources/count.json" not in json.dumps(summary)


@pytest.mark.parametrize(
    "updates",
    [
        {"package_version": ""},
        {"digest": "bad"},
        {"native_schema": None},
        {"content_kind": "unknown"},
    ],
)
def test_incomplete_contracts_are_not_selectable(updates):
    assert source_selection("count", document(**updates)) is None


def test_legacy_remote_and_empty_directory_sources():
    assert source_selection("legacy", {"descriptor": {"kind": "inventory"}}) is None
    remote = document()
    remote["local_files"] = []
    remote["remote_references"] = [{"url": "https://example.org/payload"}]
    remote_selection = source_selection("remote", remote)
    assert remote_selection is not None
    assert remote_selection["materialized"] is False
    directory = document(
        content_kind="directory",
        native_schema={"type": "string"},
        payload_root="data-sources/tree",
        tree={"directories": [], "files": []},
    )
    directory["local_files"] = []
    directory_selection = source_selection("empty-directory", directory)
    assert directory_selection is not None
    assert directory_selection["materialized"] is True
    version_selection = source_selection("count", document("v2"))
    assert version_selection is not None
    assert version_selection["reference"]["package_version"] == "v2"


def test_selection_queries_keep_version_and_owner_scope():
    async def check():
        connection = AsyncMock()
        connection.fetchval.return_value = 1
        connection.fetch.return_value = [{"resource_id": "count"}]
        context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
        with bind_context(context):
            await list_sources(connection, query="count", page=2, page_size=40)
            query, *args = connection.fetch.call_args.args
            assert "descriptor" in query and "version_id=$3 AND user_id=$4" in query
            assert args == [
                "count",
                "%count%",
                context.version_id,
                context.user_id,
                40,
                40,
            ]
            await get_source(connection, "count")
            query, *args = connection.fetchrow.call_args.args
            assert "version_id=$2 AND user_id=$3" in query
            assert args == ["count", context.version_id, context.user_id]
        with bind_context(None), pytest.raises(SelectionRequired):
            await list_sources(connection, query="", page=1, page_size=40)

    asyncio.run(check())
