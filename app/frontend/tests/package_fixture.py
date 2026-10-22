# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit owned package selection for retained API-fixture rendering oracles."""

import json
from pathlib import Path

VERSION = "11111111-1111-4111-8111-111111111111"


def initialize_package(page, user_id="test-user"):
    page.add_init_script(
        f"localStorage.setItem('lunar-package:{user_id}', '{VERSION}')"
    )


def package_response(path):
    if path == "/api/packages/versions":
        return {
            "versions": [
                {
                    "id": VERSION,
                    "display_name": "Rendering fixture",
                    "version": 1,
                    "runtime_state": "ready",
                }
            ]
        }
    if path.endswith("/context") and path.startswith("/api/chats/"):
        return {"version_id": VERSION}
    if path in {"/api/repository/catalog", "/api/repository/bundle"}:
        return json.loads(
            (
                Path(__file__).parent
                / "fixtures/prism-assets"
                / (path.rsplit("/", 1)[1] + ".json")
            ).read_text()
        )
    return None
