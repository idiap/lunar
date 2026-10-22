# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Read query dispatch preserves the same host socket and authority boundary."""

import base64
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from domain_packages.worker import fetch


@pytest.fixture
def route():
    return {
        "id": "lookup",
        "url": "https://public.invalid/search",
        "method": "POST",
        "query_schema": {"type": "object", "additionalProperties": False},
        "body_schema": {
            "type": "object",
            "properties": {"query": {"const": "query { value }"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "content_type": "application/json",
        "read_only": True,
    }


class Response(io.BytesIO):
    def getheader(self, name):
        return {"Content-Length": "2", "Content-Type": "application/json"}.get(name)


def request(route):
    return {
        "operation": "open",
        "url": route["url"],
        "query_id": route["id"],
        "resource_id": "source",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body_base64": base64.b64encode(b'{"query":"query { value }"}').decode(),
    }


def test_declared_read_post_reaches_checked_socket_with_unchanged_bytes(
    monkeypatch, route
):
    calls = []

    def opener(url, timeout, **kwargs):
        calls.append((url, kwargs))
        return Response(b"{}"), SimpleNamespace(sock=None, close=lambda: None)

    monkeypatch.setattr(fetch, "_open_public", opener)
    channel = fetch.PublicFetch([], queries=[{"resource_id": "source", "route": route}])
    opened = channel(request(route))
    assert calls[0][0] == route["url"]
    assert calls[0][1]["method"] == "POST" and calls[0][1]["allow_redirects"] is False
    assert json.loads(calls[0][1]["body"]) == {"query": "query { value }"}
    data = channel({"operation": "read", "token": opened["token"], "size": 2})["data"]
    assert isinstance(data, str)
    assert base64.b64decode(data) == b"{}"
    channel.close()


@pytest.mark.parametrize(
    "change",
    ["resource", "endpoint", "method", "header", "mutation", "download_options"],
)
def test_query_cannot_expand_declared_authority(monkeypatch, route, change):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid query reached a socket")

    monkeypatch.setattr(fetch, "_open_public", unexpected)
    channel = fetch.PublicFetch(
        [route["url"]], queries=[{"resource_id": "source", "route": route}]
    )
    value = request(route)
    if change == "resource":
        value["resource_id"] = "foreign"
    elif change == "endpoint":
        value["url"] = "https://foreign.invalid/search"
    elif change == "method":
        value["method"] = "DELETE"
    elif change == "header":
        value["headers"]["Authorization"] = "never-send"
    elif change == "mutation":
        value["body_base64"] = base64.b64encode(
            b'{"query":"mutation { delete }"}'
        ).decode()
    else:
        value.pop("query_id")
    with pytest.raises((PermissionError, ValueError, ValidationError)):
        channel(value)


def test_workflow_selects_hash_verified_query_resources_only(route):
    documents = {}
    resources = []
    files = []
    for identity in ["selected", "unselected"]:
        path = identity + ".json"
        payload = json.dumps(
            {"id": identity, "descriptor": {"public_queries": [route]}}
        ).encode()
        documents[path] = payload
        resources.append({"id": identity, "document": path})
        files.append(
            {
                "path": path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    runtime = SimpleNamespace(
        manifest={"files": files, "collections": {"data-sources": resources}},
        source_documents=documents,
    )
    workflow = {"metadata": {"public_query_resources": ["selected"]}}
    assert fetch.declared_public_queries(runtime, workflow) == [
        {"resource_id": "selected", "route": route}
    ]
    assert fetch.declared_public_queries(runtime, {}) == []
    documents["selected.json"] += b" "
    with pytest.raises(ValueError, match="changed after import"):
        fetch.declared_public_queries(runtime, workflow)


def test_missing_query_resource_is_not_ignored():
    runtime = SimpleNamespace(
        manifest={"files": [], "collections": {"data-sources": []}}, source_documents={}
    )
    with pytest.raises(ValueError, match="unavailable"):
        fetch.declared_public_queries(
            runtime, {"metadata": {"public_query_resources": ["absent"]}}
        )
