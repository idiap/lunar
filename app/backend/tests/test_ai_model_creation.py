# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Credential encryption and creation response regressions."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from starlette.requests import Request

from modules import ai_models


def model_request():
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "name": "azure/gpt-5-mini",
                    "provider": "azure",
                    "model_id": "gpt-5-mini",
                    "api_key": "fixture-secret",
                    "api_base": "https://example.test/openai/v1/responses",
                    "api_version": "2025-04-01-preview",
                }
            ).encode(),
        }

    return Request(
        {
            "type": "http",
            "state": {
                "authenticated_user": {"id": uuid.uuid4()},
            },
        },
        receive,
    )


@pytest.mark.parametrize("key", ["ab" * 32, "invalid!", "é"])
def test_invalid_encryption_key_returns_actionable_error(monkeypatch, key):
    monkeypatch.setattr(ai_models, "ENCRYPTION_KEY", key)
    connect = AsyncMock()
    monkeypatch.setattr(ai_models, "connect", connect)
    response = asyncio.run(ai_models.create_ai_model(model_request()))
    assert response.status_code == 503
    assert "ENCRYPTION_KEY" in json.loads(bytes(response.body))["error"]
    assert b"fixture-secret" not in response.body
    connect.assert_not_awaited()


@pytest.mark.parametrize("key", [None, Fernet.generate_key().decode()])
def test_creation_encrypts_key_and_returns_model(monkeypatch, key):
    monkeypatch.setattr(ai_models, "ENCRYPTION_KEY", key)
    row = {
        "id": uuid.uuid4(),
        "name": "azure/gpt-5-mini",
        "provider": "azure",
        "model_id": "gpt-5-mini",
        "config": "{}",
    }
    connection = AsyncMock()
    connection.fetchrow.return_value = row
    monkeypatch.setattr(ai_models, "connect", AsyncMock(return_value=connection))
    response = asyncio.run(ai_models.create_ai_model(model_request()))
    assert response.status_code == 201
    assert json.loads(bytes(response.body))["id"] == str(row["id"])
    encrypted = connection.fetchrow.call_args.args[8]
    assert encrypted != "fixture-secret"
    assert ai_models.decrypt_api_key(encrypted) == "fixture-secret"
    assert b"fixture-secret" not in response.body
    connection.close.assert_awaited_once()
