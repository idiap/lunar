# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import AUTH_SECRET, ENCRYPTION_KEY
from modules.common import (
    authenticated_user,
    connect,
    json_value,
    parse_uuid,
    record_json,
    request_model,
)
from modules.schemas import AIModelInput, AIModelUpdate


@dataclass(frozen=True)
class ResolvedAIModel:
    """One user-owned model, including host-only provider configuration."""

    id: uuid.UUID
    name: str
    provider: str
    model_id: str
    api_base: str | None
    api_version: str | None
    api_key: str = field(repr=False)
    config: dict[str, Any] = field(repr=False)

    @property
    def safe_snapshot(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "name": self.name,
            "provider": self.provider,
            "model_id": self.model_id,
        }


async def load_owned_ai_model(
    connection: Any, *, model_id: uuid.UUID, user_id: uuid.UUID
) -> ResolvedAIModel | None:
    """Resolve one model only when both its ID and owner match."""
    row = await connection.fetchrow(
        """
        SELECT id, name, provider, model_id, api_base, api_version,
               encrypted_api_key, config
        FROM ai_models WHERE id = $1 AND user_id = $2
        """,
        model_id,
        user_id,
    )
    if row is None:
        return None
    return ResolvedAIModel(
        id=row["id"],
        name=str(row["name"]),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        api_base=row["api_base"],
        api_version=row["api_version"],
        api_key=decrypt_api_key(str(row["encrypted_api_key"])),
        config=json_value(row["config"], {}),
    )


def _fernet() -> Fernet:
    key = ENCRYPTION_KEY
    if not key:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(AUTH_SECRET.encode()).digest()
        ).decode()
    return Fernet(key.encode())


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    return _fernet().decrypt(encrypted_key.encode()).decode()


def _model_json(row) -> dict:
    result = record_json(row)
    result["config"] = json_value(result.get("config"), {})
    result.pop("encrypted_api_key", None)
    result.pop("user_id", None)
    return result


async def create_ai_model(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, AIModelInput)
    if isinstance(body, JSONResponse):
        return body
    try:
        encrypted_api_key = encrypt_api_key(body.api_key)
    except ValueError:
        return JSONResponse(
            {
                "error": "Cannot save model credentials: the server ENCRYPTION_KEY must be a valid Fernet key (32 bytes encoded as URL-safe Base64)."
            },
            status_code=503,
        )
    connection = await connect()
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO ai_models
                (id, user_id, name, provider, model_id, api_base, api_version,
                 encrypted_api_key, config)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
            RETURNING id, name, provider, model_id, api_base, api_version,
                      config, created_at, updated_at
            """,
            uuid.uuid4(),
            user["id"],
            body.name.strip(),
            body.provider.strip(),
            body.model_id.strip(),
            body.api_base,
            body.api_version,
            encrypted_api_key,
            json.dumps(body.config),
        )
    finally:
        await connection.close()
    return JSONResponse(_model_json(row), status_code=201)


async def list_ai_models(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    limit = min(max(int(request.query_params.get("limit", "100")), 1), 500)
    offset = max(int(request.query_params.get("offset", "0")), 0)
    connection = await connect()
    try:
        rows = await connection.fetch(
            """
            SELECT id, name, provider, model_id, api_base, api_version,
                   config, created_at, updated_at
            FROM ai_models WHERE user_id = $1
            ORDER BY created_at DESC LIMIT $2 OFFSET $3
            """,
            user["id"],
            limit,
            offset,
        )
    finally:
        await connection.close()
    return JSONResponse([_model_json(row) for row in rows])


async def get_ai_model(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    model_id = parse_uuid(request.path_params["model_id"])
    if model_id is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            """
            SELECT id, name, provider, model_id, api_base, api_version,
                   config, created_at, updated_at
            FROM ai_models WHERE id = $1 AND user_id = $2
            """,
            model_id,
            user["id"],
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    return JSONResponse(_model_json(row))


async def update_ai_model(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    model_id = parse_uuid(request.path_params["model_id"])
    if model_id is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    body = await request_model(request, AIModelUpdate)
    if isinstance(body, JSONResponse):
        return body
    values = body.model_dump(exclude_unset=True)
    if not values:
        return await get_ai_model(request)
    allowed = {"name", "provider", "model_id", "api_base", "api_version", "config"}
    fields: list[str] = []
    args: list[object] = []
    for name, value in values.items():
        if name not in allowed:
            continue
        args.append(json.dumps(value) if name == "config" else value)
        cast = "::jsonb" if name == "config" else ""
        fields.append(f"{name} = ${len(args)}{cast}")
    args.extend([model_id, user["id"]])
    connection = await connect()
    try:
        row = await connection.fetchrow(
            f"""
            UPDATE ai_models SET {', '.join(fields)}, updated_at = NOW()
            WHERE id = ${len(args) - 1} AND user_id = ${len(args)}
            RETURNING id, name, provider, model_id, api_base, api_version,
                      config, created_at, updated_at
            """,
            *args,
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    return JSONResponse(_model_json(row))


async def delete_ai_model(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    model_id = parse_uuid(request.path_params["model_id"])
    if model_id is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM ai_models WHERE id = $1 AND user_id = $2", model_id, user["id"]
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "AI model deleted successfully"})


def register_ai_model_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/ai-models", methods=["GET"])(list_ai_models)
    mcp.custom_route("/api/ai-models", methods=["POST"])(create_ai_model)
    mcp.custom_route("/api/ai-models/{model_id}", methods=["GET"])(get_ai_model)
    mcp.custom_route("/api/ai-models/{model_id}", methods=["PUT"])(update_ai_model)
    mcp.custom_route("/api/ai-models/{model_id}", methods=["DELETE"])(delete_ai_model)
