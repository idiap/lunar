# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Provider selection inside the asset modal, with isolated API responses."""

from pathlib import Path
from urllib.parse import urlparse

import pytest

from package_fixture import package_response
from test_report_chat import frontend_url as frontend_url, playwright


@pytest.mark.parametrize("interaction", ["mouse", "keyboard"])
def test_provider_selection_and_submission(frontend_url, interaction):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = runtime.chromium.launch(
            headless=True,
            **({"executable_path": str(chrome)} if chrome.exists() else {}),
        )
        page = browser.new_page()
        submissions = []
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlparse(route.request.url).path
            data = package_response(path)
            if path == "/api/auth/me":
                data = {"user": {"id": "owner", "email": "owner@example.test"}}
            elif path == "/api/ai-models":
                if route.request.method == "POST":
                    submissions.append(route.request.post_data_json)
                    route.fulfill(
                        status=400, json={"error": "Fixture submission received"}
                    )
                    return
                data = []
            elif data is None:
                pytest.fail(f"Unexpected API request: {path}")
            route.fulfill(json=data)

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/ai-models")
        page.get_by_role("button", name="New ai model", exact=True).click()
        dialog = page.get_by_role("dialog")
        provider = dialog.get_by_role("combobox")
        if interaction == "mouse":
            provider.click()
            page.get_by_role("option", name="anthropic", exact=True).click(timeout=3000)
            selected = "anthropic"
        else:
            provider.focus()
            provider.press("ArrowDown")
            page.get_by_role("option", name="openai", exact=True).wait_for()
            page.keyboard.press("Home")
            page.keyboard.press("Enter")
            selected = "openai"
        playwright.expect(provider).to_contain_text(selected)
        playwright.expect(dialog).to_be_visible()
        dialog.get_by_label("Model ID", exact=True).fill("fixture-model")
        dialog.get_by_label("API key", exact=True).fill("fixture-key")
        dialog.get_by_role("button", name="Create", exact=True).click()
        playwright.expect(
            dialog.get_by_text("Fixture submission received")
        ).to_be_visible()
        assert submissions == [
            {
                "provider": selected,
                "model_id": "fixture-model",
                "api_key": "fixture-key",
                "api_base": "",
                "api_version": "",
                "name": f"{selected}/fixture-model",
            }
        ]
        assert not errors
        browser.close()
