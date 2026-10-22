# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from openai import OpenAI
from modules.model_configuration import model_connection


@pytest.mark.parametrize("suffix", ["", "/", "/responses", "/chat/completions"])
def test_azure_v1_actual_sdk_request_path(suffix):
    arguments = model_connection(
        "azure",
        "gpt-5-mini",
        "https://example.services.ai.azure.com/openai/v1" + suffix,
        "2025-04-01-preview",
    )
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5-mini",
                "choices": [],
            },
        )

    with OpenAI(
        api_key="fixture-key",
        base_url=arguments["api_base"],
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        client.chat.completions.create(
            model="gpt-5-mini", messages=[{"role": "user", "content": "test"}]
        )
    assert (
        str(seen[0].url)
        == "https://example.services.ai.azure.com/openai/v1/chat/completions"
    )
    assert "api_version" not in arguments


def test_legacy_azure_retains_versioned_client():
    assert model_connection(
        "azure", "deployment", "https://example.openai.azure.com/", "2025-04-01-preview"
    ) == {
        "model": "azure/deployment",
        "api_base": "https://example.openai.azure.com",
        "api_version": "2025-04-01-preview",
    }


def test_worker_structured_call_through_litellm_uses_correct_v1_route(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import json
    import litellm
    from types import SimpleNamespace
    from domain_packages.worker.model_channel import model_channel

    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    selected = SimpleNamespace(
        provider="azure",
        model_id="gpt-5-mini",
        api_key="fixture",
        api_base="https://example.services.ai.azure.com/openai/v1/responses",
        api_version="2025-04-01-preview",
        config={},
    )
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "test",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }
    with OpenAI(
        api_key="fixture",
        base_url="https://example.services.ai.azure.com/openai/v1/",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        result = model_channel(
            selected,
            completion=lambda **kwargs: litellm.completion(client=client, **kwargs),
        )(
            {
                "messages": [{"role": "user", "content": "test"}],
                "response_format": schema,
            }
        )
    assert result["choices"][0]["message"]["content"] == '{"value":"ok"}'
    assert (
        str(seen[0].url)
        == "https://example.services.ai.azure.com/openai/v1/chat/completions"
    )
    assert json.loads(seen[0].content)["response_format"] == schema
