# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
from typing import Any

from rate_limit import RateLimitMiddleware
from starlette.responses import JSONResponse


async def _request(
    app: Any, path: str, method: str = "GET"
) -> tuple[int, dict[str, str], object]:
    messages = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("192.0.2.1", 1234),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )

    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    headers = {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in start["headers"]
    }
    return start["status"], headers, json.loads(body)


def test_api_rate_limit_rejects_excess_requests_and_excludes_health() -> None:
    async def endpoint(scope: Any, receive: Any, send: Any) -> None:
        response = JSONResponse({"status": "ok"})
        await response(scope, receive, send)

    application = RateLimitMiddleware(
        endpoint,
        requests=2,
        window_seconds=60,
    )

    async def exercise() -> None:
        for _ in range(3):
            assert (await _request(application, "/api/example", "OPTIONS"))[0] == 200

        first = await _request(application, "/api/example")
        second = await _request(application, "/api/example")
        rejected = await _request(application, "/api/example")

        assert first[0] == 200
        assert first[1]["x-ratelimit-limit"] == "2"
        assert first[1]["x-ratelimit-remaining"] == "1"
        assert second[1]["x-ratelimit-remaining"] == "0"
        assert rejected[0] == 429
        assert rejected[1]["retry-after"] == "60"
        assert rejected[2] == {"detail": "Rate limit exceeded. Try again later."}

        for _ in range(3):
            assert (await _request(application, "/health"))[0] == 200

    asyncio.run(exercise())
