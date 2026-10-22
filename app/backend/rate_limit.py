# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Any

from starlette.responses import JSONResponse


class RateLimitMiddleware:
    """Limit requests per client IP within a rolling time window."""

    def __init__(
        self,
        app: Any,
        *,
        requests: int,
        window_seconds: int,
        paths: tuple[str, ...] = ("/api", "/mcp"),
    ) -> None:
        if requests < 1 or window_seconds < 1:
            raise ValueError("rate-limit requests and window must be positive")
        self.app = app
        self.requests = requests
        self.window_seconds = window_seconds
        self.paths = paths
        self._clients: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._last_sweep = monotonic()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self._should_limit(scope):
            await self.app(scope, receive, send)
            return

        now = monotonic()
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        with self._lock:
            self._sweep(now)
            attempts = self._clients.setdefault(client_ip, deque())
            cutoff = now - self.window_seconds
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            if len(attempts) >= self.requests:
                retry_after = max(1, ceil(attempts[0] + self.window_seconds - now))
                response = JSONResponse(
                    {"detail": "Rate limit exceeded. Try again later."},
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.requests),
                        "X-RateLimit-Remaining": "0",
                    },
                )
            else:
                attempts.append(now)
                remaining = self.requests - len(attempts)
                response = None

        if response is not None:
            await response(scope, receive, send)
            return

        async def send_with_rate_limit_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-ratelimit-limit", str(self.requests).encode("ascii")),
                        (b"x-ratelimit-remaining", str(remaining).encode("ascii")),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)

    def _should_limit(self, scope: dict[str, Any]) -> bool:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            return False
        path = scope.get("path", "")
        return any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in self.paths
        )

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self.window_seconds:
            return
        cutoff = now - self.window_seconds
        for client_ip, attempts in list(self._clients.items()):
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._clients[client_ip]
        self._last_sweep = now
