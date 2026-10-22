# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""A package cannot replace the selected provider or obtain its credential."""

from types import SimpleNamespace
import pytest
from domain_packages.worker.model_channel import model_channel


def model():
    return SimpleNamespace(
        provider="openai",
        model_id="owned-model",
        api_key="private-test-key",
        api_base=None,
        api_version=None,
        config={"temperature": 0, "api_key": "untrusted-stored-override"},
    )


def test_package_connection_overrides_never_reach_provider():
    calls = []

    def completion(**arguments):
        calls.append(arguments)
        return {"choices": [{"message": {"content": "private-test-key"}}]}

    result = model_channel(model(), completion=completion)(
        {
            "model": "foreign-provider",
            "api_key": "package-override",
            "api_base": "http://localhost:5432",
            "api_version": "bad",
            "messages": [{"role": "user", "content": "Count items"}],
        }
    )
    assert (
        calls[0]["model"] == "openai/owned-model"
        and calls[0]["api_key"] == "private-test-key"
    )
    assert "api_base" not in calls[0] and "api_version" not in calls[0]
    assert result["choices"][0]["message"]["content"] == "[redacted]"
    assert calls[0]["timeout"] == 120 and calls[0]["stream"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": [{"type": "function"}]},
        {"stream": True},
        {"headers": {"Authorization": "override"}},
    ],
)
def test_unsupported_provider_controls_are_rejected(extra):
    with pytest.raises(ValueError, match="not supported"):
        model_channel(model())(
            {"messages": [{"role": "user", "content": "Count items"}], **extra}
        )


@pytest.mark.parametrize(
    "secret", ['key"quoted', "key\\slash", "key\nnewline", "clé-unicode"]
)
def test_json_escaped_credentials_are_redacted(secret):
    selected = model()
    selected.api_key = secret
    result = model_channel(
        selected,
        completion=lambda **kwargs: {"content": "prefix " + secret + " suffix"},
    )({"messages": [{"role": "user", "content": "Count items"}]})
    assert result == {"content": "prefix [redacted] suffix"}


def test_azure_v1_endpoint_uses_compatible_base_url():
    selected = model()
    selected.provider = "azure"
    selected.model_id = "gpt-5-mini"
    selected.api_base = "https://example.services.ai.azure.com/openai/v1/responses"
    selected.api_version = "2025-04-01-preview"
    calls = []
    model_channel(selected, completion=lambda **kwargs: calls.append(kwargs) or {})(
        {"messages": [{"role": "user", "content": "test"}]}
    )
    assert calls[0]["model"] == "openai/gpt-5-mini"
    assert calls[0]["api_base"] == "https://example.services.ai.azure.com/openai/v1/"
    assert "api_version" not in calls[0]


@pytest.mark.parametrize(
    "status,text",
    [(401, "API key"), (404, "endpoint"), (429, "quota"), (400, "parameters")],
)
def test_provider_errors_expose_only_safe_categories(status, text):
    from domain_packages.worker.model_channel import ModelRequestError

    class ProviderError(Exception):
        status_code = status

    def fail(**kwargs):
        raise ProviderError("private-test-key and confidential prompt")

    with pytest.raises(ModelRequestError, match=text) as error:
        model_channel(model(), completion=fail)(
            {"messages": [{"role": "user", "content": "test"}]}
        )
    assert "private-test-key" not in str(error.value)
    assert "confidential" not in str(error.value)


def test_native_reasoning_effort_and_bounded_timeout_reach_selected_model():
    calls = []
    model_channel(
        model(), completion=lambda **kw: calls.append(kw) or {}, timeout_seconds=600
    )(
        {
            "messages": [{"role": "user", "content": "branch"}],
            "reasoning_effort": "high",
            "timeout": 300,
        }
    )
    assert calls[0]["reasoning_effort"] == "high" and calls[0]["timeout"] == 300
    for invalid in (601, 0, -1, True, "300", float("nan"), float("inf")):
        with pytest.raises(ValueError, match="timeout"):
            model_channel(model(), timeout_seconds=600)(
                {
                    "messages": [{"role": "user", "content": "branch"}],
                    "timeout": invalid,
                }
            )
