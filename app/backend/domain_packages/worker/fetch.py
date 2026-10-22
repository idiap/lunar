# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Read-only public HTTPS channel restricted to selected-package declarations."""

import base64
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import threading
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from ..format.public_queries import validate_declaration, validate_query


class PublicFetch:
    """One run's bounded streams; package code receives no socket or credentials."""

    def __init__(
        self,
        allowed_urls,
        *,
        queries=(),
        max_bytes=2 * 1024**3,
        timeout: float = 120,
    ):
        self.allowed_urls = frozenset(allowed_urls)
        self.queries = {
            (item["resource_id"], item["route"]["id"]): item["route"]
            for item in queries
        }
        if len(self.queries) != len(queries):
            raise ValueError("duplicate public query declaration")
        for route in self.queries.values():
            validate_declaration(route)
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.received = 0
        self.stream = None
        self.connection = None
        self.token = None
        self.closed = False
        self.lock = threading.Lock()

    def __call__(self, arguments):
        if self.closed:
            raise PermissionError("public download channel is closed")
        operation = arguments.get("operation")
        if operation == "open":
            if self.stream is not None:
                raise ValueError(
                    "close the current public download before opening another"
                )
            url = arguments["url"]
            query_arguments = {}
            if "query_id" in arguments:
                route = self.queries.get(
                    (arguments.get("resource_id"), arguments["query_id"])
                )
                if route is None:
                    raise PermissionError(
                        "query is not declared by the selected workflow"
                    )
                body = base64.b64decode(arguments.get("body_base64", ""), validate=True)
                query_arguments = {
                    "method": arguments.get("method"),
                    "headers": arguments.get("headers", {}),
                    "body": body,
                }
                validate_query(route, url=url, **query_arguments)
                query_arguments["allow_redirects"] = False
            elif url not in self.allowed_urls or set(arguments) - {"operation", "url"}:
                raise PermissionError(
                    "URL or request options are not declared by the selected package"
                )
            stream, connection = _open_public(
                url, self.timeout, check_active=self._check_active, **query_arguments
            )
            with self.lock:
                if self.closed:
                    _dispose(connection, stream)
                    raise PermissionError("public download channel is closed")
                self.stream, self.connection = stream, connection
                self.token = uuid4().hex
            return {
                "token": self.token,
                "headers": {
                    name: self.stream.getheader(name)
                    for name in ("Content-Length", "Content-Type")
                    if self.stream.getheader(name) is not None
                },
            }
        if not self.token or arguments.get("token") != self.token:
            raise PermissionError("public download token is unavailable")
        if operation == "read":
            size = arguments.get("size", 1024 * 1024)
            if type(size) is not int or not 1 <= size <= 1024 * 1024:
                raise ValueError("public download reads must be at most 1 MiB")
            stream = self.stream
            if stream is None:
                raise PermissionError("public download token is unavailable")
            chunk = stream.read(size)
            self.received += len(chunk)
            if self.received > self.max_bytes:
                self.close()
                raise ValueError("public downloads exceed the run byte limit")
            return {"data": base64.b64encode(chunk).decode("ascii")}
        if operation == "close":
            self._close_stream()
            return {"closed": True}
        raise ValueError("unsupported public download operation")

    def _check_active(self):
        if self.closed:
            raise PermissionError("public download channel is closed")

    def close(self):
        self._close_stream(final=True)

    def _close_stream(self, *, final=False):
        with self.lock:
            self.closed = self.closed or final
            connection, self.connection = self.connection, None
            stream, self.stream = self.stream, None
            self.token = None
        _dispose(connection, stream)


def _dispose(connection, stream):
    if connection is not None:
        sock = getattr(connection, "lunar_socket", connection.sock)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()
    if stream is not None:
        stream.close()


def _public_target(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ValueError("only uncredentialed public HTTPS on port 443 is allowed")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(row[4][0]).is_global for row in addresses
    ):
        raise ValueError("public downloads cannot address private or local networks")
    return parsed, str(addresses[0][4][0])


def _open_public(
    url,
    timeout,
    *,
    check_active=lambda: None,
    method="GET",
    headers=None,
    body=None,
    allow_redirects=True,
):
    """Pin the checked address to the TLS socket; recheck every same-host redirect."""
    original_host = urlsplit(url).hostname
    for attempt in range(6):
        check_active()
        parsed, address = _public_target(url)
        check_active()
        if parsed.hostname != original_host:
            raise ValueError("public download redirected outside its declared host")
        connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=timeout)
        sock = socket.create_connection((address, 443), timeout=timeout)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=parsed.hostname
            )
            check_active()
            setattr(connection, "lunar_socket", connection.sock)
            target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request(
                method,
                target,
                body=body,
                headers={
                    "User-Agent": "Lunar/1.0 (registered public scientific read)",
                    **(headers or {}),
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                if not allow_redirects:
                    response.close()
                    connection.close()
                    raise ValueError("declared scientific queries cannot redirect")
                location = response.getheader("Location")
                response.close()
                connection.close()
                if not location:
                    raise ValueError("public download redirect omitted its location")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(
                    "public dataset server did not return a complete response"
                )
            return response, connection
        except BaseException:
            sock.close()
            connection.close()
            raise
    raise ValueError("public dataset redirect limit exceeded")


def declared_public_urls(runtime):
    """Resolve only hash-verified source documents from this imported version."""
    entries = {row["path"]: row for row in runtime.manifest["files"]}
    urls = set()
    for resource in runtime.manifest["collections"]["data-sources"]:
        # Import moves these exact bytes into package_files, not worker mounts.
        data = runtime.source_documents.get(resource["document"])
        if data is None:
            raise ValueError("selected source document is missing from package storage")
        expected = entries[resource["document"]]
        if (
            len(data) != expected["size"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]
        ):
            raise ValueError("selected source document changed after import")
        document = json.loads(data)
        urls.update(row["uri"] for row in document["remote_references"])
    return urls


def declared_public_queries(runtime, workflow):
    """Load only hash-verified query declarations selected by this workflow."""
    entries = {row["path"]: row for row in runtime.manifest["files"]}
    selected = set(workflow.get("metadata", {}).get("public_query_resources", []))
    queries = []
    found = set()
    for resource in runtime.manifest["collections"]["data-sources"]:
        if resource["id"] not in selected:
            continue
        data = runtime.source_documents.get(resource["document"])
        if data is None:
            raise ValueError(
                "selected query source document is missing from package storage"
            )
        expected = entries[resource["document"]]
        if (
            len(data) != expected["size"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]
        ):
            raise ValueError("selected query source document changed after import")
        document = json.loads(data)
        if document["id"] != resource["id"]:
            raise ValueError("selected query source identity differs")
        found.add(resource["id"])
        for route in document.get("descriptor", {}).get("public_queries", []):
            validate_declaration(route)
            queries.append({"resource_id": resource["id"], "route": route})
    if found != selected:
        raise ValueError("selected public query resource is unavailable")
    return queries
