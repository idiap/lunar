# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Validate declared public read queries without executing package code."""

import json
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from jsonschema import Draft202012Validator

MAX_QUERY_BYTES = 1024 * 1024


def validate_declaration(route):
    """Require a fixed HTTPS host/path, with optional bounded identifier segments."""
    fields = {
        "id",
        "url",
        "method",
        "query_schema",
        "body_schema",
        "content_type",
        "read_only",
    }
    if (
        set(route) not in (fields, fields | {"path_parameters"})
        or not isinstance(route["id"], str)
        or not route["id"]
    ):
        raise ValueError("invalid public query declaration")
    parsed = urlsplit(route["url"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or route["method"] not in {"GET", "POST"}
        or route["read_only"] is not True
    ):
        raise ValueError("public queries require a declared read-only HTTPS endpoint")
    parameters = route.get("path_parameters", [])
    if (
        not isinstance(parameters, list)
        or any(
            not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
            for key in parameters
        )
        or len(set(parameters)) != len(parameters)
    ):
        raise ValueError("invalid public query path parameters")
    segments = parsed.path.split("/")
    if (
        any(segments.count("{" + key + "}") != 1 for key in parameters)
        or any(
            "{" in segment or "}" in segment
            for segment in segments
            if segment not in {"{" + key + "}" for key in parameters}
        )
        or "{" in parsed.netloc
        or "}" in parsed.netloc
    ):
        raise ValueError("query placeholders must be declared whole path segments")
    if route["content_type"] not in {None, "application/json", "text/plain"}:
        raise ValueError("unsupported public query content type")
    if (
        route["method"] == "GET"
        and (route["body_schema"] is not None or route["content_type"] is not None)
    ) or (
        route["method"] == "POST"
        and (route["body_schema"] is None or route["content_type"] is None)
    ):
        raise ValueError("public query body declaration disagrees with method")
    for schema in (route["query_schema"], route["body_schema"]):
        if schema is not None:
            Draft202012Validator.check_schema(schema)
    if (
        route["query_schema"].get("type") != "object"
        or route["query_schema"].get("additionalProperties") is not False
    ):
        raise ValueError("public query parameters must be explicitly declared")


def matches_endpoint(route, endpoint):
    """Allow only safe opaque identifiers inside declared path segments."""
    expected, actual = urlsplit(route["url"]), urlsplit(endpoint)
    if (expected.scheme, expected.netloc) != (actual.scheme, actual.netloc):
        return False
    left, right = expected.path.split("/"), actual.path.split("/")
    parameters = {"{" + key + "}" for key in route.get("path_parameters", [])}
    return len(left) == len(right) and all(
        (
            bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,159}", value))
            if segment in parameters
            else segment == value
        )
        for segment, value in zip(left, right)
    )


def validate_query(route, *, url, method, headers, body):
    """Check caller bytes against the reviewed endpoint and request schema."""
    validate_declaration(route)
    parsed = urlsplit(url)
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if (
        not matches_endpoint(route, endpoint)
        or parsed.fragment
        or method != route["method"]
    ):
        raise PermissionError("query differs from its declared endpoint or method")
    if len(url.encode()) + len(body) > MAX_QUERY_BYTES:
        raise ValueError("public query exceeds request byte limit")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if len(dict(pairs)) != len(pairs):
        raise ValueError("duplicate public query parameter")
    Draft202012Validator(route["query_schema"]).validate(dict(pairs))
    headers = {key.lower(): value for key, value in headers.items()}
    if (
        set(headers) - {"accept", "content-type"}
        or headers.get("accept", "application/json")
        not in {"application/json", "text/plain", "application/xml", "*/*"}
        or headers.get("content-type") != route["content_type"]
    ):
        raise PermissionError("query headers are outside the public read contract")
    if route["body_schema"] is None:
        if body:
            raise PermissionError("GET query cannot carry a body")
    else:
        value = body.decode("utf-8")
        if route["content_type"] == "application/json":
            value = json.loads(value)
        Draft202012Validator(route["body_schema"]).validate(value)
