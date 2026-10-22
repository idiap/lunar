# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Browser regression checks with isolated API responses; no database or AI calls.

Run with: .venv/bin/python -m pytest app/frontend/tests/test_report_chat.py
"""

from package_fixture import initialize_package, package_response


import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")
RUN_ID = "843f075d-db1f-4fde-a311-e2d7c1422a93"
REPORT = "# Example report\n\n## Findings\n\nThe measured effect was 42%.\n\n## Limitations\n\nSmall sample size."
MODELS = [
    {"id": "model-a", "name": "Model A", "model_id": "alpha"},
    {"id": "model-b", "name": "Model B", "model_id": "beta"},
]


@pytest.fixture(scope="module")
def frontend_url(frontend_build):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [
            "npm",
            "run",
            "preview",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=frontend_build,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() >= deadline or process.poll() is not None:
                    pytest.fail("Frontend did not start")
                time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def chat_browser(frontend_url):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        options = {"headless": True}
        if chrome.is_file():
            options["executable_path"] = str(chrome)
        browser = runtime.chromium.launch(**options)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        state = {"models": MODELS, "requests": [], "errors": [], "fail_chat": False}
        initialize_package(page)
        page.on("pageerror", lambda error: state["errors"].append(str(error)))

        def api_route(route):
            path = urlparse(route.request.url).path
            package = package_response(path)
            if package is not None:
                data = package
            elif path == "/api/auth/me":
                data = {"user": {"id": "test-user", "email": "test@example.test"}}
            elif path.startswith("/api/prism/runs/"):
                data = {
                    "id": path.rsplit("/", 1)[1],
                    "workflow_id": "example-workflow",
                    "outputs": [{"markdown": REPORT}],
                }
            elif path == "/api/ai-models":
                data = state["models"]
            elif path == "/api/chat":
                payload = route.request.post_data_json
                state["requests"].append(payload)
                if state["fail_chat"]:
                    route.fulfill(status=500, json={"error": "Model unavailable"})
                    return
                events = [
                    {
                        "type": "TEXT_MESSAGE_START",
                        "messageId": f"reply-{len(state['requests'])}",
                    },
                    {
                        "type": "TEXT_MESSAGE_CONTENT",
                        "messageId": f"reply-{len(state['requests'])}",
                        "delta": "The report measured **42%**.",
                    },
                    {
                        "type": "CUSTOM",
                        "name": "chat_saved",
                        "value": {"id": "saved-chat"},
                    },
                    {"type": "RUN_FINISHED"},
                ]
                route.fulfill(
                    content_type="text/event-stream",
                    body="".join(f"data: {json.dumps(event)}\n\n" for event in events),
                )
                return
            elif path == "/api/chats/saved-chat":
                data = {
                    "id": "saved-chat",
                    "messages": state["requests"][-1]["messages"],
                }
            elif path in {"/api/chat/tools", "/api/chats"}:
                data = []
            else:
                pytest.fail(f"Unexpected API request: {path}")
            route.fulfill(json=data)

        page.route("**/api/**", api_route)
        yield page, state, frontend_url
        assert state["errors"] == []
        browser.close()


def open_report(page, url, run_id=RUN_ID):
    page.goto(f"{url}/prism/runs/{run_id}/report")
    page.get_by_role("button", name="Chat with the report", exact=True).click()
    dialog = page.get_by_role("dialog", name="Chat with the report")
    playwright.expect(dialog.get_by_label("AI model")).to_be_visible()
    return dialog


def test_report_chat_context_models_drag_and_collapse(chat_browser, tmp_path):
    page, state, url = chat_browser
    dialog = open_report(page, url)
    dialog.get_by_label("AI model").click()
    page.get_by_role("option", name="Model B · beta").click()
    draft = dialog.get_by_label("Chat message")
    draft.fill("What was measured?")
    before = dialog.bounding_box()
    handle = dialog.get_by_role("button", name="Move report chat")
    bounds = handle.bounding_box()
    page.mouse.move(bounds["x"] + 60, bounds["y"] + 20)
    page.mouse.down()
    page.mouse.move(bounds["x"] - 140, bounds["y"] - 80, steps=5)
    page.mouse.up()
    after = dialog.bounding_box()
    assert after["x"] == pytest.approx(before["x"] - 200, abs=1)
    assert after["y"] == pytest.approx(before["y"] - 100, abs=1)
    dialog.get_by_role("button", name="Collapse report chat").click()
    playwright.expect(dialog).not_to_be_visible()
    badge = page.get_by_role("button", name="Chat with the report", exact=True)
    playwright.expect(badge).to_be_focused()
    badge.click()
    playwright.expect(draft).to_have_value("What was measured?")
    playwright.expect(dialog.get_by_label("AI model")).to_contain_text("Model B")
    assert dialog.bounding_box()["x"] == after["x"]
    draft.press("Enter")
    playwright.expect(dialog.locator(".chat-message.assistant")).to_contain_text("42%")
    assert page.url.endswith(f"/prism/runs/{RUN_ID}/report")
    payload = state["requests"][0]
    assert payload["forwardedProps"]["aiModelId"] == "model-b"
    assert payload["forwardedProps"]["enabledTools"] == []
    context = json.loads(payload["messages"][0]["content"].split("\n\n", 1)[1])
    assert context == {
        "run_id": RUN_ID,
        "workflow_id": "example-workflow",
        "markdown": REPORT,
    }
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1]["content"] == "What was measured?"
    draft.fill("What are the limitations?")
    draft.press("Enter")
    playwright.expect(dialog.locator(".chat-message.assistant")).to_have_count(2)
    assert state["requests"][1]["forwardedProps"]["chatId"] == "saved-chat"
    assert state["requests"][1]["threadId"] == payload["threadId"]
    assert any(
        message["role"] == "assistant" for message in state["requests"][1]["messages"]
    )
    draft.press("Escape")
    badge.click()
    playwright.expect(dialog.locator(".chat-message.assistant")).to_have_count(2)
    handle.focus()
    handle.press("ArrowLeft")
    assert dialog.bounding_box()["x"] == after["x"] - 20
    page.set_viewport_size({"width": 390, "height": 700})
    page.wait_for_function("""() => {
        const bounds = document.querySelector('[role="dialog"]').getBoundingClientRect();
        return bounds.x >= 8 && bounds.right <= window.innerWidth;
    }""")
    bounds = dialog.bounding_box()
    assert bounds["x"] >= 8 and bounds["y"] >= 8
    assert bounds["x"] + bounds["width"] <= 390
    assert bounds["y"] + bounds["height"] <= 700
    playwright.expect(
        dialog.get_by_role("button", name="Send", exact=True)
    ).to_be_in_viewport()
    page.screenshot(path=str(tmp_path / "report-chat-mobile.png"))
    print(f"Screenshot: {tmp_path / 'report-chat-mobile.png'}")
    dialog = open_report(page, url, "another-run")
    playwright.expect(dialog.locator(".chat-message")).to_have_count(0)


def test_report_chat_empty_models_and_failed_response(chat_browser):
    page, state, url = chat_browser
    state["models"] = []
    dialog = open_report(page, url)
    playwright.expect(dialog.get_by_label("Chat message")).to_be_disabled()
    playwright.expect(
        dialog.get_by_role("link", name="AI model connection")
    ).to_be_visible()
    state["models"] = MODELS
    state["fail_chat"] = True
    dialog = open_report(page, url)
    dialog.get_by_label("Chat message").fill("Summarize")
    dialog.get_by_role("button", name="Send", exact=True).click()
    playwright.expect(page.get_by_text("Model unavailable", exact=True)).to_be_visible()
    playwright.expect(dialog.get_by_label("Chat message")).to_be_enabled()


def test_regular_chat_still_uses_shared_conversation(chat_browser):
    page, state, url = chat_browser
    page.goto(f"{url}/chat")
    playwright.expect(
        page.get_by_role("heading", name="Start a conversation")
    ).to_be_visible()
    playwright.expect(page.get_by_role("button", name="Tools 0")).to_be_visible()
    page.get_by_label("Chat message").fill("Hello")
    page.get_by_role("button", name="Send", exact=True).click()
    playwright.expect(page).to_have_url(f"{url}/chat/saved-chat")
    assert len(state["requests"][0]["messages"]) == 1
    assert state["requests"][0]["messages"][0]["role"] == "user"
