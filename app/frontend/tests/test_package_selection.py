# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Browser races use delayed API fixtures, separately from the real E0 journey."""

from pathlib import Path
from urllib.parse import urlparse
from test_report_chat import frontend_url as frontend_url, playwright
from package_fixture import VERSION


def test_selection_discards_late_same_id_content_and_failed_upload(frontend_url):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = runtime.chromium.launch(
            headless=True,
            **({"executable_path": str(chrome)} if chrome.exists() else {}),
        )
        page = browser.new_page()
        second = "22222222-2222-4222-8222-222222222222"
        available = [VERSION, second]
        pending = []
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlparse(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"id": "owner", "email": "owner@example.test"}}
            elif path == "/api/packages/versions":
                data = {
                    "versions": [
                        {
                            "id": identity,
                            "display_name": "Warehouse",
                            "version": (VERSION, second).index(identity) + 1,
                            "runtime_state": "unprepared",
                        }
                        for identity in available
                    ]
                }
            elif (
                path.startswith("/api/packages/versions/")
                and route.request.method == "DELETE"
            ):
                identity = path.rsplit("/", 1)[1]
                assert identity in available
                available.remove(identity)
                data = {"success": True, "message": "Package deleted successfully"}
            elif path == "/api/skills":
                identity = route.request.headers.get("x-lunar-package-version")
                assert identity in (VERSION, second)
                if identity == VERSION:
                    pending.append(route)
                    return
                data = hierarchy("New version content")
            elif path == "/api/repository/catalog":
                identity = route.request.headers.get("x-lunar-package-version")
                assert identity in (VERSION, second)
                data = {
                    "schema_version": 1,
                    "visibility": "package",
                    "modules": [
                        {
                            "id": "inventory",
                            "name": "Inventory workflow",
                            "description": "Count warehouse stock",
                            "primary_file": "repository/main.prism",
                            "file_count": 1,
                            "skill_count": 0,
                        }
                    ],
                    "skills": [],
                    "resources": [],
                }
            elif path == "/api/packages/import":
                route.fulfill(status=400, json={"error": "Invalid package checksum"})
                return
            else:
                raise AssertionError(path)
            route.fulfill(json=data)

        def hierarchy(label):
            skill = {
                "skill_id": "same",
                "display_name": label,
                "description": "Same logical ID",
                "role": None,
                "theme": None,
                "cluster": None,
            }
            return {
                "total": 1,
                "items": [skill],
                "roles": [
                    {
                        "id": "ungrouped",
                        "label": "Ungrouped",
                        "count": 1,
                        "themes": [
                            {
                                "id": "ungrouped",
                                "label": "Ungrouped",
                                "count": 1,
                                "clusters": [
                                    {
                                        "id": "ungrouped",
                                        "label": "Ungrouped",
                                        "count": 1,
                                        "skills": [skill],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/skills")
        playwright.expect(
            page.get_by_text("Select or import a package to open this view.")
        ).to_be_visible()
        selector = page.get_by_label("Package version", exact=True)
        page.goto(frontend_url + "/repository")
        playwright.expect(
            page.get_by_role("button", name="Warehouse v1", exact=True)
        ).to_be_visible()
        playwright.expect(
            page.get_by_role("button", name="Warehouse v2", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Warehouse v1", exact=True).click()
        playwright.expect(
            page.get_by_role(
                "link",
                name="Inventory workflow Count warehouse stock repository/main.prism · 1 file · 0 skills",
                exact=True,
            )
        ).to_be_visible()
        playwright.expect(selector).to_have_value("")
        page.goto(frontend_url + "/skills")
        selector.select_option(VERSION)
        page.wait_for_timeout(100)
        assert pending
        selector.select_option(second)
        playwright.expect(
            page.get_by_role("link").filter(has_text="New version content")
        ).to_be_visible()
        for route in pending:
            route.fulfill(json=hierarchy("Stale private content"))
        page.wait_for_timeout(100)
        playwright.expect(page.get_by_text("Stale private content")).to_have_count(0)
        # Package import is owned by the repository view.
        page.goto(frontend_url + "/repository")
        page.get_by_label("Package ZIP").set_input_files(
            {"name": "broken.zip", "mimeType": "application/zip", "buffer": b"bad"}
        )
        playwright.expect(
            page.get_by_text("Invalid package checksum", exact=True)
        ).to_be_visible()
        playwright.expect(selector).to_have_value(second)
        assert selector.locator("option").count() == 3
        page.goto(frontend_url + "/repository")
        page.get_by_role("button", name="Delete Warehouse v1", exact=True).click()
        dialog = page.get_by_role("alertdialog")
        playwright.expect(
            dialog.get_by_text("This action cannot be undone.", exact=False)
        ).to_be_visible()
        dialog.get_by_role("button", name="Delete", exact=True).click()
        playwright.expect(
            page.get_by_role("button", name="Delete Warehouse v1", exact=True)
        ).to_have_count(0)
        playwright.expect(selector).to_have_value(second)
        playwright.expect(selector.locator("option")).to_have_count(2)
        page.get_by_role("button", name="Delete Warehouse v2", exact=True).click()
        page.get_by_role("alertdialog").get_by_role(
            "button", name="Delete", exact=True
        ).click()
        playwright.expect(
            page.get_by_role("heading", name="No packages available", exact=True)
        ).to_be_visible()
        playwright.expect(selector).to_have_value("")
        assert selector.locator("option").count() == 1
        assert not errors
        browser.close()


def test_package_deletion_stays_disabled_after_reload(frontend_url):
    with playwright.sync_playwright() as runtime:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = runtime.chromium.launch(
            headless=True,
            **({"executable_path": str(chrome)} if chrome.exists() else {}),
        )
        page = browser.new_page()
        other = "22222222-2222-4222-8222-222222222222"
        state = {"deleting": False, "requests": 0}

        def respond(route):
            path = urlparse(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"id": "owner", "email": "owner@example.test"}}
            elif path == "/api/packages/versions":
                data = {
                    "versions": [
                        {
                            "id": VERSION,
                            "display_name": "Warehouse",
                            "version": 1,
                            "deletion_started_at": (
                                "2026-09-24T10:00:00Z" if state["deleting"] else None
                            ),
                        },
                        {
                            "id": other,
                            "display_name": "Warehouse",
                            "version": 2,
                            "deletion_started_at": None,
                        },
                    ]
                }
            elif (
                path == f"/api/packages/versions/{VERSION}"
                and route.request.method == "DELETE"
            ):
                state["requests"] += 1
                state["deleting"] = True
                route.fulfill(status=202, json={"success": True, "state": "deleting"})
                return
            else:
                raise AssertionError(path)
            route.fulfill(json=data)

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/repository")
        page.get_by_role("button", name="Delete Warehouse v1").click()
        page.get_by_role("alertdialog").get_by_role(
            "button", name="Delete", exact=True
        ).click()
        deleting = page.get_by_role("button", name="Deleting Warehouse v1")
        playwright.expect(deleting).to_be_disabled()
        playwright.expect(deleting.locator("svg.spin")).to_be_visible()
        page.reload()
        playwright.expect(
            page.get_by_role("button", name="Deleting Warehouse v1")
        ).to_be_disabled()
        playwright.expect(
            page.get_by_role("button", name="Delete Warehouse v2")
        ).to_be_enabled()
        assert state["requests"] == 1
        browser.close()
