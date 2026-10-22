# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Isolated browser checks for planner result and reasoning rendering."""

from package_fixture import initialize_package, package_response

import json
from pathlib import Path
from urllib.parse import urlparse
import pytest
from test_report_chat import frontend_url as frontend_url, MODELS, playwright


@pytest.mark.parametrize(
    "status", ["completed", "blocked", "failed", "clarification_required"]
)
def test_inline_planner_and_saved_history(frontend_url, status):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = runtime.chromium.launch(
            headless=True,
            **({"executable_path": str(chrome)} if chrome.exists() else {}),
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        snapshot = {
            "type": "snapshot",
            "run_id": "run",
            "state": "completed" if status == "completed" else "blocked",
            "entries": [
                {
                    "id": "entry",
                    "run_id": "run",
                    "sequence": 1,
                    "source_event_key": "planning:1",
                    "event_kind": "stage",
                    "source": {
                        "stage": "planning",
                        "status": "completed",
                        "summary": "Evidence was checked.",
                        "rationale_summary": "The fixture supports a bounded interpretation.",
                        "limitations": ["Prediction is not experimental evidence."],
                    },
                    "presentation": {
                        "status": "unavailable",
                        "icon_id": "evaluating_evidence_strength",
                        "unavailable_reason": "not_configured",
                    },
                }
            ],
        }
        result = {
            "status": status,
            "reasoning": snapshot,
            "blockers": [] if status == "completed" else ["More evidence is needed."],
            "questions": (
                ["Which protein?"] if status == "clarification_required" else []
            ),
            "released_artifact": (
                {"answer": "GPC3 fixture confidence"} if status == "completed" else None
            ),
            "report": {"url": "/reports/result"} if status == "completed" else None,
        }
        saved = []
        errors = []
        initialize_package(page, "user")
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_api(route):
            path = urlparse(route.request.url).path
            package = package_response(path)
            if package is not None:
                data = package
            elif path == "/api/auth/me":
                data = {"user": {"id": "user", "email": "test@example.test"}}
            elif path == "/api/ai-models":
                data = MODELS
            elif path == "/api/chat/tools":
                data = [
                    {
                        "name": "planner",
                        "description": "Plan and execute automatically.",
                        "default_enabled": True,
                    }
                ]
            elif path == "/api/chats":
                data = []
            elif path == "/api/chats/saved":
                data = {
                    "id": "saved",
                    "messages": saved,
                    "pending_interrupt": {"thread_id": "retired"},
                }
            elif path == "/api/chat":
                request = route.request.post_data_json
                assert request["forwardedProps"]["enabledTools"] == ["planner"]
                saved[:] = [
                    *request["messages"],
                    {
                        "id": "a",
                        "role": "assistant",
                        "toolCalls": [
                            {
                                "id": "call",
                                "function": {"name": "planner", "arguments": "{}"},
                            }
                        ],
                    },
                    {
                        "id": "result",
                        "role": "tool",
                        "toolCallId": "call",
                        "content": json.dumps(result),
                    },
                ]
                events = [
                    {"type": "TEXT_MESSAGE_START", "messageId": "a"},
                    {
                        "type": "TOOL_CALL_START",
                        "toolCallId": "call",
                        "toolCallName": "planner",
                        "parentMessageId": "a",
                    },
                    {
                        "type": "CUSTOM",
                        "name": "planner_reasoning",
                        "value": {"tool_call_id": "call", "snapshot": snapshot},
                    },
                    {
                        "type": "TOOL_CALL_RESULT",
                        "toolCallId": "call",
                        "messageId": "result",
                        "content": json.dumps(result),
                    },
                    {"type": "CUSTOM", "name": "chat_saved", "value": {"id": "saved"}},
                    {"type": "RUN_FINISHED"},
                ]
                route.fulfill(
                    content_type="text/event-stream",
                    body="".join(f"data: {json.dumps(event)}\n\n" for event in events),
                )
                return
            else:
                pytest.fail(f"Unexpected API request: {path}")
            route.fulfill(json=data)

        page.route("**/api/**", route_api)
        page.goto(frontend_url + "/chat")
        page.get_by_role("button", name="Tools", exact=False).click()
        playwright.expect(page.get_by_role("checkbox")).to_have_count(1)
        playwright.expect(page.get_by_role("checkbox")).to_be_checked()
        page.keyboard.press("Escape")
        page.get_by_label("Chat message").fill("Assess GPC3")
        page.get_by_label("Chat message").press("Enter")
        timeline = page.get_by_label("Run reasoning timeline")
        playwright.expect(timeline).to_be_visible()
        timeline.get_by_text("Recorded detail", exact=True).click()
        playwright.expect(timeline).to_contain_text("bounded interpretation")
        playwright.expect(
            page.get_by_role("button", name="Approve", exact=True)
        ).to_have_count(0)
        playwright.expect(page.get_by_label("Chat message")).to_be_enabled()
        if status == "completed":
            playwright.expect(page.get_by_label("Released result")).to_contain_text(
                "GPC3 fixture confidence"
            )
            playwright.expect(
                page.get_by_role("link", name="Open report")
            ).to_have_attribute("href", "/reports/result")
        else:
            playwright.expect(
                page.get_by_role("link", name="Open report")
            ).to_have_count(0)
            playwright.expect(page.get_by_label("Planner activity")).to_contain_text(
                "More evidence is needed"
            )
        page.reload()
        playwright.expect(timeline).to_be_visible()
        playwright.expect(page.get_by_label("Chat message")).to_be_enabled()
        assert not errors
        browser.close()
