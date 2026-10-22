# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Offline real creation -> ZIP input -> persistence -> interactive report journey."""

import asyncio
import hashlib
import importlib
import json
from pathlib import Path
from uuid import uuid4
import zipfile

import asyncpg
import auth
import modules.common as common
import reports
import pytest
from playwright.sync_api import expect
from scripts.build_typed_report_package import build_package
from test_package_browser import browser_session

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT.parent / "prism/examples/language/typed_reports"


def mismatched_zip(source, destination):
    with zipfile.ZipFile(source) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    path = manifest["collections"]["reports"][0]["document"]
    report = json.loads(payloads[path])
    report["metadata"]["typed_report"]["report"]["template"]["sections"][0][
        "id"
    ] = "mismatched-slot"
    payloads[path] = json.dumps(report).encode()
    for row in manifest["files"]:
        row.update(
            size=len(payloads[row["path"]]),
            sha256=hashlib.sha256(payloads[row["path"]]).hexdigest(),
        )
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w") as archive:
        for name, raw in payloads.items():
            archive.writestr(name, raw)


def expected_references(typed, section):
    graph = typed["native"]["graph"]
    values = {v["identity"]: v for v in graph["values"]}
    activities = {a["identity"]: a for a in graph["activities"]}
    pending = [typed["sections"][section]["reference"]]
    seen = set()
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        value = values[identity]
        pending.extend(value["dependencies"])
        pending.extend(child for _, child in value["children"])
        pending.extend(activities[value["activity"]]["inputs"])
    return seen


def test_typed_creation_upload_render_and_provenance(
    e2e_database_url, tmp_path, monkeypatch
):
    for module in (auth, common, reports):
        monkeypatch.setattr(module, "DATABASE_URL", e2e_database_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            owner = uuid4()
            await connection.execute(
                "INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",
                owner,
                str(owner) + "@example.invalid",
            )
            return owner, await auth.create_session(owner)
        finally:
            await connection.close()

    owner, token = asyncio.run(setup())
    paths = [tmp_path / "typed.zip", tmp_path / "without-template.zip"]
    exports = [
        build_package(EXAMPLE, path, with_template=index == 0)
        for index, path in enumerate(paths)
    ]
    invalid = tmp_path / "invalid-template.zip"
    mismatched_zip(paths[0], invalid)
    import server

    server = importlib.reload(server)
    with browser_session(server.app, tmp_path, token) as (page, errors, url):
        page.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            page.goto(url + "/reports")
            for index, (path, typed) in enumerate(zip(paths, exports)):
                with page.expect_response(
                    lambda r: "/api/packages/import" in r.url
                    and r.request.method == "POST"
                ) as uploaded:
                    page.get_by_label("Package ZIP").set_input_files(path)
                assert uploaded.value.status == 201, uploaded.value.text()
                version = uploaded.value.json()["version"]["id"]
                expect(
                    page.get_by_role("status").filter(has_text="Package imported")
                ).to_be_visible()
                expect(page.get_by_label("Package version", exact=True)).to_have_value(
                    version
                )
                page.get_by_role("link", name="Reports", exact=True).click()
                page.get_by_role("link").filter(has_text="Typed field report").click()
                expect(
                    page.get_by_role("heading", name="Typed field report", exact=True)
                ).to_be_visible()
                report_url = page.url.split("#")[0]
                identity = report_url.rsplit("/", 1)[-1]
                response = page.request.get(
                    f"{url}/api/report/{identity}",
                    headers={"X-Lunar-Package-Version": version},
                )
                assert response.status == 200, response.text()
                persisted = response.json()
                assert persisted["typed_report"] == typed
                assert persisted["template_snapshot"] == typed["report"]["template"]
                expect(
                    page.get_by_text(
                        (
                            "Template: Field survey (survey-layout)"
                            if index == 0
                            else "No structural template"
                        ),
                        exact=True,
                    )
                ).to_be_visible()
                expect(
                    page.get_by_text("The survey recorded twelve birds.", exact=True)
                ).to_be_visible()
                page.get_by_role("tab", name="Details", exact=True).click()
                expect(
                    page.frame_locator('iframe[title="HTML section html"]').get_by_text(
                        "Twelve birds were recorded during the morning survey.",
                        exact=True,
                    )
                ).to_be_visible()
                expect(page.locator("iframe")).to_have_attribute("sandbox", "")
                image = page.get_by_role(
                    "img", name="Twelve birds observed", exact=True
                )
                expect(image).to_be_visible()
                assert image.evaluate(
                    "(image) => image.complete && image.naturalWidth > 0"
                )
                assert image.get_attribute("src").startswith("/api/package-files/")
                assert page.request.get(image.get_attribute("src")).status == 200
                page.get_by_role("tab", name="Figure", exact=True).press("ArrowRight")
                expect(
                    page.get_by_role("tab", name="Method", exact=True)
                ).to_have_attribute("aria-selected", "true")
                expect(
                    page.get_by_text(
                        "The notebook is a source assertion. Formatting it does not prove the observation.",
                        exact=True,
                    )
                ).to_be_visible()
                page.get_by_role("tab", name="Details", exact=True).press("Home")
                expect(
                    page.get_by_role("tab", name="Overview", exact=True)
                ).to_have_attribute("aria-selected", "true")
                sections = (
                    typed["sections"].items()
                    if index == 0
                    else [("method", typed["sections"]["method"])]
                )
                for section, mapping in sections:
                    if section in {"overview", "summary"}:
                        page.get_by_role("tab", name="Overview", exact=True).click()
                    elif section != "outer":
                        page.get_by_role("tab", name="Details", exact=True).click()
                        if section in {"figure-tab", "image", "method-tab", "method"}:
                            page.get_by_role(
                                "tab",
                                name=(
                                    "Method"
                                    if section in {"method-tab", "method"}
                                    else "Figure"
                                ),
                                exact=True,
                            ).click()
                    with page.expect_response(
                        lambda r: f"/sections/{section}/provenance" in r.url
                    ) as lineage:
                        page.get_by_role(
                            "link", name="Show provenance for " + section, exact=True
                        ).click()
                    assert lineage.value.status == 200, lineage.value.text()
                    value = lineage.value.json()
                    assert value["native_reference"] == mapping["reference"]
                    assert value["recorded_execution"] == typed["native"]["run_id"]
                    actual = {
                        n["attributes"]["prism:native_reference"]
                        for n in value["graph"]["nodes"]
                        if n["kind"] == "entity"
                    }
                    assert actual == expected_references(typed, section)
                    origins = {
                        n["attributes"].get("prism:origin")
                        for n in value["graph"]["nodes"]
                        if n["kind"] == "activity"
                    }
                    assert ("asserted" in origins) == (
                        section in {"outer", "overview", "summary"}
                    )
                    expect(
                        page.get_by_role(
                            "heading", name="Section lineage · " + section, exact=True
                        )
                    ).to_be_visible()
                    expect(page.locator(".react-flow__node").first).to_be_visible()
                    page.get_by_role("link", name="Back", exact=True).click()
                    expect(
                        page.get_by_role(
                            "link", name="Show provenance for " + section, exact=True
                        )
                    ).to_be_visible()
                page.reload()
                expect(
                    page.get_by_role("tab", name="Method", exact=True)
                ).to_have_attribute("aria-selected", "true")
                with page.expect_response(
                    lambda r: "/sections/method/provenance" in r.url
                ) as reloaded:
                    page.get_by_role(
                        "link", name="Show provenance for method", exact=True
                    ).click()
                assert (
                    reloaded.value.json()["native_reference"]
                    == typed["sections"]["method"]["reference"]
                )
                page.get_by_role("link", name="Back", exact=True).click()
                expect(
                    page.get_by_role("tab", name="Method", exact=True)
                ).to_have_attribute("aria-selected", "true")
                page.screenshot(
                    path=str(tmp_path / f"report-{index}.png"), full_page=True
                )
                page.get_by_role("tab", name="Figure", exact=True).click()
                expect(
                    page.get_by_role("img", name="Twelve birds observed", exact=True)
                ).to_be_visible()
                page.screenshot(
                    path=str(tmp_path / f"report-figure-{index}.png"), full_page=True
                )
            with page.expect_response(
                lambda r: "/api/packages/import" in r.url and r.request.method == "POST"
            ) as rejected:
                page.get_by_label("Package ZIP").set_input_files(invalid)
            assert rejected.value.status == 400, rejected.value.text()
            assert "template" in rejected.value.json()["error"]
            expect(
                page.get_by_role("status").filter(has_text="template")
            ).to_be_visible()
            import psycopg

            with psycopg.connect(e2e_database_url) as connection:
                versions = connection.execute(
                    "SELECT COUNT(*) FROM package_versions WHERE user_id=%s", (owner,)
                ).fetchone()[0]
                report_count = connection.execute(
                    "SELECT COUNT(*) FROM reports WHERE user_id=%s", (owner,)
                ).fetchone()[0]
            assert (versions, report_count) == (2, 2)
            assert not errors, errors
            page.screenshot(path=str(tmp_path / "invalid-template.png"), full_page=True)
            (tmp_path / "acceptance.json").write_text(
                json.dumps(
                    {
                        "sections_checked": list(exports[0]["sections"]),
                        "template_states": [True, False],
                        "invalid_template_status": rejected.value.status,
                        "page_errors": errors,
                    },
                    indent=2,
                )
            )
        finally:
            page.context.tracing.stop(path=str(tmp_path / "browser-trace.zip"))
