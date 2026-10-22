# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Credential-retaining host channel to exactly one authorized model connection."""

import json
from collections.abc import Mapping
from typing import Any
from modules.model_configuration import model_connection


class ModelRequestError(RuntimeError):
    """A credential-free provider error safe to return across the worker channel."""


def model_channel(selected_model, *, completion=None, timeout_seconds: float = 120):
    """Bind provider credentials on the host and ignore package connection overrides."""

    def call(arguments):
        if not isinstance(arguments, Mapping):
            raise ValueError("model arguments must be an object")
        messages = arguments.get("messages")
        if (
            not isinstance(messages, list)
            or not messages
            or any(
                not isinstance(row, dict)
                or row.get("role") not in {"system", "user", "assistant"}
                or not isinstance(row.get("content"), str)
                for row in messages
            )
        ):
            raise ValueError("model channel requires text messages")
        allowed = {
            "messages",
            "response_format",
            "temperature",
            "max_tokens",
            "top_p",
            "seed",
            "stop",
            "reasoning_effort",
        }
        overrides = {"model", "api_key", "api_base", "api_version"}
        requested_timeout = arguments.get("timeout", timeout_seconds)
        if (
            isinstance(requested_timeout, bool)
            or not isinstance(requested_timeout, (int, float))
            or not 0 < requested_timeout <= timeout_seconds
        ):
            raise ValueError("model timeout exceeds the scoped host limit")
        if set(arguments) - allowed - overrides - {"timeout"}:
            raise ValueError("model channel argument is not supported")
        configuration = {
            key: value
            for key, value in selected_model.config.items()
            if key
            not in overrides | {"messages", "response_format", "stream", "timeout"}
        }
        configuration.update(
            {key: value for key, value in arguments.items() if key in allowed}
        )
        configuration.update(
            model_connection(
                selected_model.provider,
                selected_model.model_id,
                selected_model.api_base,
                selected_model.api_version,
            )
        )
        configuration.update(
            api_key=selected_model.api_key, timeout=requested_timeout, stream=False
        )
        provider = completion
        if provider is None:
            from litellm import completion as provider
        try:
            result = provider(**configuration)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            reason = {
                400: "The provider rejected the model parameters or output schema.",
                401: "The provider rejected the API key.",
                403: "The provider denied access to this model.",
                404: "The model endpoint or deployment was not found.",
                429: "The provider rate limit or quota was exceeded.",
            }.get(
                status if isinstance(status, int) else 0,
                "The provider request failed; check model configuration and availability.",
            )
            raise ModelRequestError(reason) from None
        dynamic_result: Any = result
        if hasattr(dynamic_result, "model_dump"):
            dynamic_result = dynamic_result.model_dump(mode="json")
        encoded = json.dumps(dynamic_result, allow_nan=False)
        if selected_model.api_key:
            encoded = encoded.replace(
                json.dumps(selected_model.api_key)[1:-1], "[redacted]"
            )
        return json.loads(encoded)

    return call
