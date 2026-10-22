# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, TypeVar

import asyncpg
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import current_user
from config import DATABASE_URL

ModelT = TypeVar("ModelT", bound=BaseModel)


async def authenticated_user(request: Request) -> asyncpg.Record | JSONResponse:
    user = getattr(request.state, "authenticated_user", None)
    if user is None:
        user = await current_user(request)
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return user


async def request_model(request: Request, model: type[ModelT]) -> ModelT | JSONResponse:
    try:
        return model.model_validate(await request.json())
    except (ValueError, ValidationError) as error:
        details = error.errors() if isinstance(error, ValidationError) else str(error)
        return JSONResponse(
            {"error": "Invalid request", "details": details}, status_code=422
        )


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def json_value(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def record_json(record: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(DATABASE_URL)
