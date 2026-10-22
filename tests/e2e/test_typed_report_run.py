# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real package -> isolated PRISM execution -> typed report -> native ancestry."""

import asyncio
import importlib
import shutil
from pathlib import Path
from uuid import uuid4

import asyncpg
import auth
import modules.common as common
import reports
import pytest
from playwright.sync_api import expect
from prism_stdlib.report_codec import decode_report
from scripts.build_typed_report_run_package import build_package
from domain_packages.archive import validate_archive
from test_package_browser import browser_session
from test_typed_report_upload import expected_references

pytestmark = pytest.mark.e2e
EXAMPLE = (
    Path(__file__).resolve().parents[3] / "prism/examples/language/typed_report_run"
)


def test_run_typed_report_and_inspect_provenance(
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
            await connection.execute(
                "INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",
                owner,
                str(owner) + "@example.invalid",
            )
            return await auth.create_session(owner)
        finally:
            await connection.close()

    token = asyncio.run(setup())
    example = tmp_path / "example"
    shutil.copytree(EXAMPLE, example)
    # The viewer requires authored reasoning; executable workflow declarations
    # alone are deliberately absent from its selector.
    with (example / "main.prism").open("a") as source:
        source.write("""
type ReadNotebook = (request: SurveyRequest) -> Evidence[String]
type FormatObservation = (observation: Evidence[String]) -> Computed[String]
type AssembleReport = (narrative: Computed[String]) -> r.Report
reasoning FieldSurvey(request: SurveyRequest) -> r.Report:
    sequence:
        [observation: ReadNotebook(request)]
        [narrative: FormatObservation(observation)]
        [report: AssembleReport(narrative)]
    return report
""")
    archive = build_package(example, tmp_path / "field-survey.zip")
    import server

    server = importlib.reload(server)
    with browser_session(server.app, tmp_path, token) as (page, errors, url):
        page.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            page.goto(url + "/prism")
            with page.expect_response(
                lambda r: "/api/packages/import" in r.url and r.request.method == "POST"
            ) as uploaded:
                page.get_by_label("Package ZIP").set_input_files(archive)
            assert uploaded.value.status == 201, uploaded.value.text()
            version = uploaded.value.json()["version"]["id"]
            expect(page.get_by_label("Package version", exact=True)).to_have_value(
                version
            )
            page.get_by_role("button", name="Prepare runtime", exact=True).click()
            expect(page.get_by_text("Runtime: ready", exact=True)).to_be_visible(
                timeout=90000
            )
            page.get_by_role("link", name="Prism", exact=True).click()
            expect(
                page.get_by_role("tab", name="Project atlas", exact=True)
            ).to_be_visible()
            page.get_by_role("tab", name="Workflow graph", exact=True).click()
            expect(page.get_by_role("tabpanel")).to_contain_text("Read Notebook")
            expect(page.get_by_role("tabpanel")).to_contain_text("Format Observation")
            expect(page.get_by_role("tabpanel")).to_contain_text("Assemble Report")
            page.screenshot(path=str(tmp_path / "workflow-graph.png"), full_page=True)
            page.get_by_role("tab", name="Prism files", exact=True).click()
            expect(page.get_by_label("Syntax-colored Prism file")).to_contain_text(
                "workflow field_survey"
            )
            page.get_by_role("tab", name="Input examples", exact=True).click()
            expect(page.get_by_role("tabpanel")).to_contain_text("FieldSurvey values")
            page.get_by_role("tab", name="Run", exact=True).click()
            page.get_by_role("button", name="Run", exact=True).click()
            dialog = page.get_by_role("dialog")
            observation = "The test survey recorded seven herons beside the lake."
            dialog.get_by_role("textbox", name="Field observation").fill(observation)
            dialog.get_by_role("button", name="Run", exact=True).click()
            expect(page.locator(".prism-run-row")).to_contain_text(
                "completed", timeout=60000
            )
            run_id = (
                page.locator(".prism-run-row-header > a")
                .get_attribute("href")
                .split("/")[-1]
            )
            headers = {"X-Lunar-Package-Version": version}
            result = page.request.get(
                "/api/prism/runs/" + run_id, headers=headers
            ).json()
            assert result["state"] == "completed"
            typed = result["outputs"][0]["structured_value"]["typed_report"]
            decode_report(typed, attachments={})
            assert typed["report"]["sections"][0]["text"].endswith(observation)
            page.goto(url + "/prism/runs/" + run_id + "/report")
            expect(page.locator(".typed-report")).to_contain_text(observation)
            expect(page.locator(".typed-report")).to_contain_text(
                "Template: Field survey (field-survey-v1)"
            )
            expect(page.get_by_label("Source files")).to_contain_text(
                "def main(request: SurveyRequest) -> r.Report:"
            )
            page.screenshot(path=str(tmp_path / "typed-run-report.png"), full_page=True)
            for section in ("observation", "method"):
                page.get_by_role(
                    "link", name="Show provenance for " + section, exact=True
                ).click()
                expect(
                    page.get_by_role("heading", name="Section lineage · " + section)
                ).to_be_visible()
                expect(page.get_by_label("Observed provenance graph")).to_be_visible()
                endpoint = (
                    "/api/prism/runs/" + run_id + "/provenance?section=" + section
                )
                provenance = page.request.get(endpoint, headers=headers)
                assert provenance.status == 200, provenance.text()
                body = provenance.json()
                assert (
                    body["native_reference"] == typed["sections"][section]["reference"]
                )
                references = {
                    node["attributes"]["prism:native_reference"]
                    for node in body["graph"]["nodes"]
                    if node["kind"] == "entity"
                    and "prism:native_reference" in node["attributes"]
                }
                assert references == expected_references(typed, section)
                if section == "observation":
                    assert any(
                        "assert" in str(node["attributes"]).lower()
                        for node in body["graph"]["nodes"]
                    )
                    assert any(
                        "compute" in str(node["attributes"]).lower()
                        for node in body["graph"]["nodes"]
                    )
                    page.screenshot(
                        path=str(tmp_path / "typed-run-provenance.png"), full_page=True
                    )
                page.reload()
                expect(
                    page.get_by_role("heading", name="Section lineage · " + section)
                ).to_be_visible()
                page.go_back()
                expect(page.locator(".typed-report")).to_contain_text(observation)
            for fmt in ("prov-json", "json-ld"):
                response = page.request.get(
                    "/api/prism/runs/" + run_id + "/provenance?format=" + fmt,
                    headers=headers,
                )
                assert response.status == 200, response.text()
                assert "prism" in str(response.json()["document"])
            assert (
                page.request.get(
                    "/api/prism/runs/" + run_id + "/provenance?section=missing",
                    headers=headers,
                ).status
                == 404
            )
            page.get_by_role("link", name="Repository", exact=True).click()
            with page.expect_download() as downloaded:
                page.locator(
                    f'a[href="/api/packages/versions/{version}/export"]'
                ).click()
            exported = tmp_path / "roundtrip.zip"
            downloaded.value.save_as(exported)
            validated = validate_archive(exported, tmp_path / "roundtrip")
            assert "workflows" not in validated.manifest["runtime"]
            assert "bundle" not in validated.documents["repository"][0]["metadata"]
            from domain_packages.source_workflows import runtime_manifest

            assert (
                runtime_manifest(validated.manifest, validated.root)["runtime"][
                    "workflows"
                ][0]["id"]
                == "field-survey"
            )
            with page.expect_response(
                lambda r: "/api/packages/import" in r.url and r.request.method == "POST"
            ) as restored:
                page.get_by_label("Package ZIP").set_input_files(exported)
            assert restored.value.status == 201, restored.value.text()
            restored_version = restored.value.json()["version"]["id"]
            expect(page.get_by_label("Package version", exact=True)).to_have_value(
                restored_version
            )
            page.goto(url + "/prism?workflow=field-survey&view=graph")
            expect(page.get_by_role("tabpanel")).to_contain_text("Assemble Report")
            page.get_by_role("tab", name="Run", exact=True).click()
            expect(page.locator(".typed-report")).to_contain_text(observation)
            page.get_by_role("link", name="Open report", exact=True).click()
            expect(page.get_by_label("Source files")).to_contain_text(
                "workflow field_survey"
            )
            page.get_by_role(
                "link", name="Show provenance for observation", exact=True
            ).click()
            expect(
                page.get_by_role("heading", name="Section lineage · observation")
            ).to_be_visible()
            expect(page.get_by_label("Observed provenance graph")).to_be_visible()
            assert not errors
        finally:
            page.context.tracing.stop(path=str(tmp_path / "typed-report-run-trace.zip"))
