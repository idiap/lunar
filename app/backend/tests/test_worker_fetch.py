# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Public downloads cannot address private networks or escape their run scope."""

import base64
import io
import socket
from types import SimpleNamespace

import pytest
from domain_packages.worker import fetch


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "fc00::1"],
)
def test_private_dns_answers_are_denied(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
        ],
    )
    with pytest.raises(ValueError, match="private or local"):
        fetch._public_target("https://public.example.invalid/data")


@pytest.mark.parametrize(
    "url",
    [
        "http://public.invalid/data",
        "https://user:password@public.invalid/data",
        "https://public.invalid:5432/data",
        "https://public.invalid/data#fragment",
    ],
)
def test_unsafe_urls_rejected_before_dns(monkeypatch, url):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid URL reached DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected)
    with pytest.raises(ValueError, match="uncredentialed public HTTPS"):
        fetch._public_target(url)


class Response(io.BytesIO):
    def getheader(self, name):
        return {"Content-Length": "4", "Content-Type": "text/plain"}.get(name)


def test_declared_streams_are_bounded_and_tokens_do_not_cross_runs(monkeypatch):
    opened = []

    def opener(url, timeout, **kwargs):
        opened.append(url)
        return Response(b"data"), SimpleNamespace(sock=None, close=lambda: None)

    monkeypatch.setattr(fetch, "_open_public", opener)
    first = fetch.PublicFetch(["https://public.invalid/data"], max_bytes=3)
    other = fetch.PublicFetch(["https://public.invalid/data"])
    with pytest.raises(PermissionError, match="not declared"):
        first({"operation": "open", "url": "https://foreign.invalid/data"})
    assert opened == []
    token = first({"operation": "open", "url": "https://public.invalid/data"})["token"]
    with pytest.raises(PermissionError, match="token"):
        other({"operation": "read", "token": token, "size": 1})
    data = first({"operation": "read", "token": token, "size": 2})["data"]
    assert isinstance(data, str)
    assert base64.b64decode(data) == b"da"
    with pytest.raises(ValueError, match="byte limit"):
        first({"operation": "read", "token": token, "size": 2})
    assert first.closed and first.stream is None
    with pytest.raises(PermissionError, match="closed"):
        first({"operation": "open", "url": "https://public.invalid/data"})


def test_closed_run_discards_a_late_opened_connection(monkeypatch):
    channel = fetch.PublicFetch(["https://public.invalid/data"])
    stream = Response(b"data")
    closed = []

    def opener(*args, **kwargs):
        channel.close()
        return stream, SimpleNamespace(sock=None, close=lambda: closed.append(True))

    monkeypatch.setattr(fetch, "_open_public", opener)
    with pytest.raises(PermissionError, match="closed"):
        channel({"operation": "open", "url": "https://public.invalid/data"})
    assert stream.closed and closed == [True] and channel.stream is None


def test_reads_and_normal_close_allow_next_declared_file(monkeypatch):
    monkeypatch.setattr(
        fetch,
        "_open_public",
        lambda *args, **kwargs: (
            Response(b"data"),
            SimpleNamespace(sock=None, close=lambda: None),
        ),
    )
    channel = fetch.PublicFetch(["https://public.invalid/data"])
    token = channel({"operation": "open", "url": "https://public.invalid/data"})[
        "token"
    ]
    with pytest.raises(ValueError, match="1 MiB"):
        channel({"operation": "read", "token": token, "size": 2 * 1024 * 1024})
    assert channel({"operation": "close", "token": token}) == {"closed": True}
    assert (
        channel({"operation": "open", "url": "https://public.invalid/data"})["token"]
        != token
    )
    channel.close()


def test_database_source_documents_are_hash_verified_without_filesystem_reads():
    import hashlib

    payload = b'{"remote_references":[{"uri":"https://public.invalid/data"}]}'
    path = "data-sources/documents/source.json"
    runtime = SimpleNamespace(
        manifest={
            "files": [
                {
                    "path": path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
            "collections": {"data-sources": [{"document": path}]},
        },
        source_documents={path: payload},
    )
    assert fetch.declared_public_urls(runtime) == {"https://public.invalid/data"}
    runtime.source_documents[path] = payload.replace(b"public", b"secret")
    with pytest.raises(ValueError, match="changed after import"):
        fetch.declared_public_urls(runtime)
    runtime.source_documents.clear()
    with pytest.raises(ValueError, match="missing from package storage"):
        fetch.declared_public_urls(runtime)


def test_load_runtime_reads_source_bytes_for_only_the_owned_version(
    monkeypatch, tmp_path
):
    import asyncio
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from domain_packages.worker import runtime as module

    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    path = "data-sources/documents/source.json"
    manifest = {
        "runtime": {},
        "files": [],
        "collections": {"repository": [], "data-sources": [{"document": path}]},
    }
    connection = AsyncMock()
    connection.fetchrow.return_value = {
        "manifest": manifest,
        "runtime_state": "ready",
        "runtime_image": "fixture-image",
    }
    connection.fetch.return_value = [{"path": path, "payload": b"{}"}]
    monkeypatch.setattr(module, "owned_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        module,
        "ensure_current_worker_code",
        AsyncMock(return_value="fixture-image"),
    )
    runtime = asyncio.run(
        module.load_runtime(
            connection,
            context.user_id,
            context.version_id,
            SimpleNamespace(version_root=lambda _: tmp_path),
        )
    )
    assert runtime.source_documents == {path: b"{}"}
    query, owner, version, paths = connection.fetch.call_args.args
    assert "user_id=$1 AND version_id=$2" in query
    assert (owner, version, paths) == (context.user_id, context.version_id, [path])
