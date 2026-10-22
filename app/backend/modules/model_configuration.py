# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Translate stored provider endpoints into LiteLLM connection arguments."""

from urllib.parse import urlsplit, urlunsplit


def model_connection(provider, model_id, api_base=None, api_version=None):
    arguments = {"model": f"{provider}/{model_id}"}
    if api_base:
        base = api_base.strip().rstrip("/")
        parts = urlsplit(base)
        path = parts.path.rstrip("/")
        # Azure v1 uses the OpenAI-compatible client, without dated API versions.
        if provider == "azure" and path in {
            "/openai/v1",
            "/openai/v1/responses",
            "/openai/v1/chat/completions",
        }:
            arguments["model"] = f"openai/{model_id}"
            arguments["api_base"] = urlunsplit(
                (parts.scheme, parts.netloc, "/openai/v1/", "", "")
            )
            return arguments
        arguments["api_base"] = base
    if api_version:
        arguments["api_version"] = api_version
    return arguments
