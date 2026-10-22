# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real browser -> API -> PostgreSQL/filesystem/worker package journey.

Only the external chat provider is a local deterministic HTTP fixture (E0).
Application routes, ZIP parsing, persistence, preparation and execution are real.
The separate E1 suite is responsible for genuine provider evidence.
"""

import asyncio
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4
import zipfile

import asyncpg
import auth
import modules.common as common
import reports
import pytest
import uvicorn
from playwright.sync_api import sync_playwright, expect
from domain_packages.archive import validate_archive
import test_package_workers as fixtures

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def chat_provider():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/event-stream" if request.get("stream") else "application/json",
            )
            self.end_headers()
            common = {"id": "local-e0-chat", "created": 1, "model": "local-e0"}
            if request.get("stream"):
                for delta, finish in (
                    (
                        {
                            "role": "assistant",
                            "content": "Saved inventory discussion: 42 items.",
                        },
                        None,
                    ),
                    ({}, "stop"),
                ):
                    packet = {
                        **common,
                        "object": "chat.completion.chunk",
                        "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish}
                        ],
                    }
                    self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            **common,
                            "object": "chat.completion",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": "Inventory discussion",
                                    },
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    ).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port) + "/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def browser_zip(tmp_path, label):
    fixtures.archive(tmp_path, label, planning_hooks=False)
    path = tmp_path / (label + ".zip")
    with zipfile.ZipFile(path) as source:
        payloads = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    # This E0 arithmetic workflow exercises the current Run form; it has no
    # scientific inputs or model effects and is not E1 provider evidence.
    source = payloads["repository/main.prism"].decode().splitlines()
    payloads["repository/main.prism"] = ("\n".join(source) + "\n").encode()
    # A real, renderable imported attachment and visible version-specific content.
    payloads["reports/plot.svg"] = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect width="120" height="40" fill="teal"/></svg>'
    )
    report = json.loads(payloads["reports/stock.json"])
    report["content"] += " " + label
    payloads["reports/stock.json"] = json.dumps(report).encode()
    for row in manifest["files"]:
        data = payloads[row["path"]]
        row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as target:
        for name, data in payloads.items():
            target.writestr(name, data)
    return path


@contextmanager
def browser_session(app, root, token):
    backend_port, frontend_port = port(), port()
    backend = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=backend_port, log_level="warning")
    )
    thread = threading.Thread(target=backend.run, daemon=True)
    thread.start()
    log = (root / "vite.log").open("w")
    frontend = subprocess.Popen(
        [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(frontend_port),
            "--strictPort",
        ],
        cwd=ROOT / "app/frontend",
        env={**os.environ, "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{backend_port}"},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{frontend_port}"
    try:
        deadline = time.monotonic() + 25
        for selected_port in (backend_port, frontend_port):
            while True:
                try:
                    with socket.create_connection(
                        ("127.0.0.1", selected_port), timeout=0.2
                    ):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
        with sync_playwright() as runtime:
            chrome = Path(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )
            browser = runtime.chromium.launch(
                headless=True,
                **({"executable_path": str(chrome)} if chrome.exists() else {}),
            )
            page = browser.new_page(
                base_url=url, viewport={"width": 1440, "height": 900}
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.context.add_cookies(
                [{"name": auth.SESSION_COOKIE, "value": token, "url": url}]
            )
            try:
                yield page, errors, url
            finally:
                browser.close()
    finally:
        frontend.terminate()
        frontend.wait(10)
        log.close()
        backend.should_exit = True
        thread.join(15)


def test_browser_upload_select_collections_execute_and_restore_chat(
    e2e_database_url, tmp_path, worker_image, monkeypatch
):
    for module in (auth, common, reports):
        monkeypatch.setattr(module, "DATABASE_URL", e2e_database_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("LUNAR_WORKER_IMAGE", worker_image)

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            owner = uuid4()
            other = uuid4()
            for identity in (owner, other):
                await connection.execute(
                    "INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",
                    identity,
                    str(identity) + "@example.invalid",
                )
            return (
                owner,
                await auth.create_session(owner),
                await auth.create_session(other),
            )
        finally:
            await connection.close()

    owner, token, foreign_token = asyncio.run(setup())
    first_zip, second_zip = browser_zip(tmp_path, "first-version"), browser_zip(
        tmp_path, "second-version"
    )
    import server

    server = importlib.reload(server)
    with (
        chat_provider() as model_url,
        browser_session(server.app, tmp_path, token) as (page, errors, url),
    ):
        page.goto(url + "/skills")
        expect(
            page.get_by_text("Select or import a package to open this view.")
        ).to_be_visible()

        def upload(path):
            page.get_by_label("Package ZIP").set_input_files(path)
            expect(
                page.get_by_role("status").filter(has_text="Package imported")
            ).to_be_visible(timeout=30000)
            return page.get_by_label("Package version", exact=True).input_value()

        first = upload(first_zip)
        expect(page.get_by_label("Package version", exact=True)).not_to_have_value("")
        page.get_by_role("link", name="Skills", exact=True).click()
        page.get_by_role("link").filter(has_text="Stock summary").click()
        expect(page.get_by_text("Summarize item counts.")).to_be_visible()
        page.get_by_role("link", name="Data Sources", exact=True).click()
        page.get_by_role("link").filter(has_text="Stock").click()
        source_link = page.get_by_label("Local source files").get_by_role("link").first
        source = page.request.get(source_link.get_attribute("href"))
        assert source.status == 200 and source.body() == b"item,count\nbox,3\n"
        page.get_by_role("link", name="Repository", exact=True).click()
        page.get_by_text("Warehouse", exact=True).click()
        expect(
            page.get_by_role("link", name="repository/main.prism", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="Reports", exact=True).click()
        page.get_by_role("link").filter(has_text="Stock report").click()
        expect(page.get_by_label("Report preview")).to_contain_text("first-version")
        image = page.get_by_role("img", name="Stock")
        expect(image).to_be_visible()
        assert image.evaluate("(image) => image.complete && image.naturalWidth > 0")
        page.get_by_label("Report revision").select_option("1")
        expect(page.get_by_label("Report preview")).to_contain_text("Two boxes.")
        page.get_by_label("Report revision").select_option("")
        page.get_by_role("link", name="Provenance", exact=True).click()
        expect(page.get_by_role("heading", name="Report lineage")).to_be_visible()
        page.get_by_role("button", name="PROV-JSON", exact=True).click()
        # Explicit preparation through the real UI/API/container boundary.
        page.get_by_role("button", name="Prepare runtime", exact=True).click()
        expect(page.get_by_text("Runtime: ready", exact=True)).to_be_visible(
            timeout=60000
        )
        page.get_by_role("link", name="Prism", exact=True).click()
        expect(page.get_by_label("Workflow", exact=True)).to_contain_text(
            "InventoryReasoning"
        )
        page.get_by_role("button", name="Run", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("spinbutton", name="count").fill("41")
        dialog.get_by_role("button", name="Run", exact=True).click()
        expect(page.locator(".prism-run-row")).to_contain_text(
            "completed", timeout=45000
        )
        run_link = page.locator(".prism-run-row-header > a")
        run_id = run_link.get_attribute("href").split("/")[-1]
        result = page.request.get(
            "/api/prism/runs/" + run_id, headers={"X-Lunar-Package-Version": first}
        ).json()
        assert result["outputs"][0]["structured_value"] == {"count": 42}
        page.get_by_role("link", name="Repository", exact=True).click()
        with page.expect_download() as download_info:
            page.locator(f'a[href="/api/packages/versions/{first}/export"]').click()
        download = download_info.value
        assert download.suggested_filename.endswith("-v1.zip")
        download_path = tmp_path / "browser-export.zip"
        download.save_as(download_path)
        exported = validate_archive(download_path, tmp_path / "browser-export")
        assert len(exported.documents["reports"]) == 2
        assert any(
            row["metadata"].get("generation_type") == "prism"
            for row in exported.documents["reports"]
        )
        # Actual chat routing and saved history, with only the external provider fixture local.
        created = page.request.post(
            "/api/ai-models",
            data={
                "name": "Local E0 model",
                "provider": "openai",
                "model_id": "local-e0",
                "api_base": model_url,
                "api_key": "local-fixture",
            },
        )
        assert created.status == 201, created.text()
        page.get_by_role("link", name="Chat", exact=True).click()
        page.get_by_label("Chat message").fill("Discuss the inventory run: " + run_id)
        page.get_by_label("Chat message").press("Enter")
        expect(page.locator(".chat-message.assistant")).to_contain_text(
            "42 items", timeout=30000
        )
        page.wait_for_url("**/chat/*")
        saved_url = page.url
        chat_id = saved_url.rsplit("/", 1)[1]
        chat = page.request.get(
            "/api/chats/" + chat_id, headers={"X-Lunar-Package-Version": first}
        ).json()
        assert chat["version_id"] == first and chat["messages"]
        second = upload(second_zip)
        assert second != first
        expect(page.get_by_label("Package version", exact=True)).to_have_value(second)
        page.goto(saved_url)
        expect(page.get_by_label("Package version", exact=True)).to_have_value(first)
        expect(page.locator(".chat-message.assistant")).to_contain_text("42 items")
        page.get_by_label("Package version", exact=True).select_option(second)
        assert page.url == url + "/chat"
        expect(page.locator(".chat-message.assistant")).to_have_count(0)
        # Failed import leaves both successful versions and selection intact.
        bad = tmp_path / "invalid.zip"
        bad.write_bytes(b"invalid")
        page.get_by_label("Package ZIP").set_input_files(bad)
        expect(
            page.get_by_role("button", name="Import ZIP", exact=True)
        ).to_be_enabled()
        expect(page.get_by_label("Package version", exact=True)).to_have_value(second)
        assert (
            page.get_by_label("Package version", exact=True).locator("option").count()
            == 3
        )
        expect(page.get_by_label("Chat message")).to_be_enabled()
        page.screenshot(path=str(tmp_path / "workspace.png"), full_page=True)
        page.get_by_role("button", name="Sign out").click()
        expect(
            page.get_by_role("heading", name="Welcome back", exact=True)
        ).to_be_visible()
        page.context.add_cookies(
            [{"name": auth.SESSION_COOKIE, "value": foreign_token, "url": url}]
        )
        page.goto(url + "/skills")
        expect(page.get_by_label("Package version", exact=True)).to_have_value("")
        expect(
            page.get_by_text("Select or import a package to open this view.")
        ).to_be_visible()
        assert (
            page.get_by_label("Package version", exact=True).locator("option").count()
            == 1
        )
        assert not errors
