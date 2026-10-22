# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Viewer/execution compatibility checks with mocked APIs and no scientific runs."""

from package_fixture import initialize_package, package_response


from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from test_report_chat import frontend_url as frontend_url, playwright

OPERATIONS = {
    "pharmaceutical-process-capture": "Protein A Capture Development",
    "pharmaceutical-process-clone": "mAb Clone-to-Fed-Batch Strategy",
    "pharmaceutical-process-deviation": "Pharmaceutical Batch-Deviation Investigation",
}


@pytest.fixture
def workflow_browser(frontend_url):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        options = {"headless": True}
        if chrome.is_file():
            options["executable_path"] = str(chrome)
        browser = runtime.chromium.launch(**options)
        page = browser.new_page()
        state = {
            "requests": [],
            "errors": [],
            "runs": [],
            "network_enabled": False,
            "payloads": [],
        }
        initialize_package(page)
        page.on("pageerror", lambda error: state["errors"].append(str(error)))

        def respond(route):
            request = route.request
            url = urlparse(request.url)
            state["requests"].append((request.method, url.path, parse_qs(url.query)))
            package = package_response(url.path)
            if package is not None:
                data = package
            elif url.path == "/api/auth/me":
                data = {"user": {"id": "test-user", "email": "test@example.test"}}
            elif url.path == "/api/prism/workflows":
                data = [
                    {
                        "id": key,
                        "name": name,
                        "downloads_enabled": state["network_enabled"],
                        "datasets": [],
                        "sources": [],
                        "metadata": {
                            "model_required": True,
                            "viewer_workflow_id": (
                                "pharmaceutical-process" if key in OPERATIONS else key
                            ),
                        },
                    }
                    for key, name in {
                        **OPERATIONS,
                        "melanoma-resistance": "Melanoma Resistance",
                        "biomedical-research-ethics": "Biomedical Research Ethics",
                        "biostatistical-experimental-design": "Biostatistical Experimental Design",
                        "workflow-methodology-description": "Workflow Methodology Description",
                    }.items()
                ]
            elif url.path == "/api/ai-models":
                data = [
                    {
                        "id": "model-a",
                        "name": "Model A",
                        "provider": "test",
                        "model_id": "test",
                    }
                ]
            elif url.path == "/api/prism/runs/reasoning":
                route.fulfill(
                    content_type="text/event-stream", body='data: {"type":"done"}\n\n'
                )
                return
            elif url.path == "/api/prism/runs":
                workflow_id = parse_qs(url.query)["workflow_id"][0]
                data = {
                    "items": [
                        r for r in state["runs"] if r["workflow_id"] == workflow_id
                    ]
                }
            elif request.method == "GET" and url.path.startswith("/api/prism/runs/"):
                run_id = url.path.rsplit("/", 1)[1]
                data = {
                    **next(r for r in state["runs"] if r["id"] == run_id),
                    "outputs": [],
                }
            elif request.method == "POST" and url.path.endswith("/runs"):
                state["payloads"].append(request.post_data_json)
                workflow_id = url.path.split("/")[-2]
                run_id = "843f075d-db1f-4fde-a311-e2d7c1422a93"
                state["runs"].append(
                    {
                        "id": run_id,
                        "workflow_id": workflow_id,
                        "state": "completed",
                        "created_at": "2026-09-09T10:00:00Z",
                    }
                )
                data = {"run_id": run_id}
            else:
                pytest.fail(f"Unexpected API request: {url.path}")
            route.fulfill(json=data)

        page.route("**/api/**", respond)
        yield page, state, frontend_url
        assert not state["errors"]
        browser.close()


@pytest.mark.parametrize(
    "workflow_id",
    [
        "biomedical-research-ethics",
        "biostatistical-experimental-design",
        "workflow-methodology-description",
    ],
)
def test_every_workflow_has_material_execution_and_reads_history(
    workflow_browser, workflow_id
):
    page, state, url = workflow_browser
    page.goto(f"{url}/prism?workflow={workflow_id}&view=run")
    playwright.expect(
        page.get_by_text("Execution is not available", exact=False)
    ).to_have_count(0)
    playwright.expect(
        page.get_by_role("button", name="Run", exact=True)
    ).to_be_enabled()
    page.wait_for_timeout(2700)  # Cover a polling interval, not only initial loading.
    assert any(
        path == "/api/prism/runs" and query.get("workflow_id") == [workflow_id]
        for _, path, query in state["requests"]
    )
    assert all(method == "GET" for method, _, _ in state["requests"])


@pytest.mark.parametrize("execution_id", OPERATIONS)
def test_pharmaceutical_operation_routes_history_run_and_reasoning(
    workflow_browser, execution_id
):
    page, state, url = workflow_browser
    page.goto(f"{url}/prism?workflow=pharmaceutical-process&view=run")
    selector = page.get_by_role("combobox", name="Select operation")
    playwright.expect(selector).to_be_visible()
    selector.click()
    page.get_by_role("option", name=OPERATIONS[execution_id], exact=True).click()
    page.get_by_role("button", name="Run", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("combobox", name="Run AI model").click()
    page.get_by_role("option", name="Model A (test/test)", exact=True).click()
    dialog.get_by_role("button", name="Run", exact=True).click()
    playwright.expect(
        page.get_by_text("Workflow run accepted", exact=True)
    ).to_be_visible()
    page.wait_for_timeout(300)
    assert ("POST", f"/api/prism/workflows/{execution_id}/runs", {}) in state[
        "requests"
    ]
    assert any(
        path == "/api/prism/runs" and query.get("workflow_id") == [execution_id]
        for _, path, query in state["requests"]
    )
    assert any(
        path == "/api/prism/runs/reasoning"
        and query.get("workflow_id") == [execution_id]
        for _, path, query in state["requests"]
    )
    assert not any(
        method == "POST" and path == "/api/prism/workflows/pharmaceutical-process/runs"
        for method, path, _ in state["requests"]
    )


@pytest.mark.parametrize(
    "enabled,opt_in", [(False, False), (True, False), (True, True)]
)
def test_network_authority_respects_deployment_and_run_opt_in(
    workflow_browser, enabled, opt_in
):
    page, state, url = workflow_browser
    state["network_enabled"] = enabled
    page.goto(f"{url}/prism?workflow=pharmaceutical-process&view=run")
    page.get_by_role("button", name="Run", exact=True).click()
    dialog = page.get_by_role("dialog")
    checkbox = dialog.get_by_role(
        "checkbox", name="Allow declared public network reads for this run"
    )
    playwright.expect(checkbox).not_to_be_checked()
    if enabled:
        playwright.expect(checkbox).to_be_enabled()
        if opt_in:
            checkbox.check()
    else:
        playwright.expect(checkbox).to_be_disabled()
        playwright.expect(
            dialog.get_by_text(
                "Public network reads are disabled on this server.", exact=False
            )
        ).to_be_visible()
    dialog.get_by_role("combobox", name="Run AI model").click()
    page.get_by_role("option", name="Model A (test/test)", exact=True).click()
    dialog.get_by_role("button", name="Run", exact=True).click()
    playwright.expect(
        page.get_by_text("Workflow run accepted", exact=True)
    ).to_be_visible()
    assert state["payloads"][0]["network_authority"] is (enabled and opt_in)


def test_failed_run_shows_recorded_error_without_reasoning(workflow_browser):
    page, state, url = workflow_browser
    state["runs"] = [
        {
            "id": "843f075d-db1f-4fde-a311-e2d7c1422a93",
            "workflow_id": "pharmaceutical-process-capture",
            "state": "failed",
            "created_at": "2026-09-11T07:41:21Z",
            "error_summary": "Selected source document is missing from package storage",
        }
    ]
    page.goto(f"{url}/prism?workflow=pharmaceutical-process&view=run")
    playwright.expect(
        page.get_by_role("alert").filter(has_text="Selected source document is missing")
    ).to_be_visible()
