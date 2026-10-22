# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
from typing import Literal, TypedDict, cast

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://reports:reports@db:5432/reports")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", PUBLIC_BASE_URL).rstrip("/")
AUTH_SECRET = os.getenv("AUTH_SECRET", "local-development-secret-change-me")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
BYPASS_VERIFICATION = os.getenv("BYPASS_VERIFICATION", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Lunar <onboarding@resend.dev>")
SESSION_COOKIE = os.getenv("SESSION_COOKIE", "report_session")
SESSION_COOKIE_SAMESITE = cast(
    Literal["lax", "strict", "none"],
    os.getenv("SESSION_COOKIE_SAMESITE", "lax"),
)
SESSION_SECONDS = int(os.getenv("SESSION_SECONDS", str(60 * 60 * 24 * 30)))
API_RATE_LIMIT_REQUESTS = int(os.getenv("API_RATE_LIMIT_REQUESTS", "120"))
API_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60"))


class ReasoningModelSettings(TypedDict):
    provider: str
    id: str
    api_key: str
    api_base: str
    api_version: str
    timeout: float
    identity: str


# Dedicated backend-only presentation model. Invalid settings disable enrichment.
def reasoning_model_settings() -> tuple[
    ReasoningModelSettings | None,
    Literal["not_configured", "invalid_configuration"] | None,
]:
    import math
    import re
    from urllib.parse import urlparse

    values = {
        "provider": os.getenv("LUNAR_REASONING_MODEL_PROVIDER", ""),
        "id": os.getenv("LUNAR_REASONING_MODEL_ID", ""),
        "api_key": os.getenv("LUNAR_REASONING_MODEL_API_KEY", ""),
        "api_base": os.getenv("LUNAR_REASONING_MODEL_API_BASE", ""),
        "api_version": os.getenv("LUNAR_REASONING_MODEL_API_VERSION", ""),
    }
    if not any(values.values()):
        return None, "not_configured"
    try:
        timeout = float(os.getenv("LUNAR_REASONING_MODEL_TIMEOUT_SECONDS", "20"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError()
        if not all(values[key] for key in ("provider", "id", "api_key")):
            raise ValueError()
        identity = f"{values['provider']}/{values['id']}"
        if len(identity) > 160 or not re.fullmatch(r"[a-zA-Z0-9._/-]+", identity):
            raise ValueError()
        if values["api_base"]:
            url = urlparse(values["api_base"])
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError()
    except ValueError:
        return None, "invalid_configuration"
    return ReasoningModelSettings(**values, timeout=timeout, identity=identity), None
