# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Ten-workflow live scientific/provider gate through imported packages and HTTP.

Only account setup uses SQL. Import, preparation, model selection, dispatch and
provenance use the application; no provider fixture or scientific import is used.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import hashlib
import subprocess
import zipfile
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4
from urllib.parse import urlencode

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
import httpx
from playwright.sync_api import expect
from test_package_browser import browser_session
import auth
import modules.common as common
import reports
import schema
from domain_packages.context import owned_context
from domain_packages.storage import VersionStorage
from modules.ai_models import load_owned_ai_model
from test_bioagents_workers import NoDomainImports
from prism.runtime import EffectRecorder, FileArtifactStore
from prism.runtime.replay import effect_record_from_dict

pytestmark = [pytest.mark.e2e, pytest.mark.live]
ROOT = Path(__file__).resolve().parents[2]

ACCEPTANCE_PATH = "repository/runtime/tests/fixtures/e2e/prism-live-acceptance.json"


def acceptance_manifest():
    package = os.getenv("LUNAR_E2E_BIOAGENTS_ZIP")
    if not package:
        return None
    with zipfile.ZipFile(package) as archive:
        return json.loads(archive.read(ACCEPTANCE_PATH))


def campaign_cases():
    manifest = acceptance_manifest()
    if manifest is None:
        if "--run-prism-llm-e2e" in sys.argv:
            raise pytest.UsageError("Live campaign requires LUNAR_E2E_BIOAGENTS_ZIP")
        return [
            pytest.param(
                "package-not-configured",
                marks=pytest.mark.skip(reason="requires exported live package"),
            )
        ]
    required = manifest["campaign_scope"]["required_workflow_ids"]
    assert len(required) == len(set(required)) == 10
    assert not set(required) & set(manifest["campaign_scope"]["deferred_workflows"])
    return required


ADMISSION_PROGRAM = r"""
import json, pathlib, runpy, sys
root, data_root = map(pathlib.Path, sys.argv[1:3])
sys.path.insert(0, str(root))
from catalog.integrations.domain_package.runtime.config import configure
configure(root, data_root=data_root)
from catalog.integrations.domain_package.runtime.adapters import ADAPTERS
admission = runpy.run_path(str(root/'tests/workflow_export/live_acceptance.py'))
manifest = json.loads((root/admission['MANIFEST_PATH']).read_text())
admission['require_campaign_admission'](manifest, root, ADAPTERS, workflow_ids=json.loads(sys.argv[3]), data_root=data_root)
print('Selected live input admission passed')
"""


@pytest.fixture(scope="module")
def live_installation(request, worker_image):
    database_url = os.environ["LUNAR_E2E_DATABASE_URL"]
    from urllib.parse import urlparse

    assert (
        urlparse(database_url).path.lower().endswith("_e2e_test")
    ), "E1 requires its explicit disposable database"
    package = Path(os.environ["LUNAR_E2E_BIOAGENTS_ZIP"])
    manifest = acceptance_manifest()
    selected = [
        item.callspec.params["workflow_id"]
        for item in request.session.items
        if item.module.__name__ == __name__
    ]
    explicit = bool(request.config.option.keyword) or any(
        "::" in arg for arg in request.config.args
    )
    if not explicit:
        assert set(selected) == set(
            manifest["campaign_scope"]["required_workflow_ids"]
        ), "unfiltered campaign must contain all ten cases"
    root = ROOT / "artifacts/runs" / ("prism-live-" + uuid4().hex)
    root.mkdir(parents=True)
    storage = VersionStorage(root / "store")
    patch = pytest.MonkeyPatch()
    for module in (auth, common, reports, schema):
        patch.setattr(module, "DATABASE_URL", database_url)
    patch.setenv("DATABASE_URL", database_url)
    patch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(root / "store"))
    patch.setenv("LUNAR_WORKER_IMAGE", worker_image)
    patch.setenv("API_RATE_LIMIT_REQUESTS", "10000")
    patch.setenv("LUNAR_ALLOW_LIVE_NETWORK", "1")
    guard = NoDomainImports()
    sys.meta_path.insert(0, guard)

    async def reset():
        connection = await asyncpg.connect(database_url)
        try:
            await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        finally:
            await connection.close()

    async def account():
        await schema.ensure_schema()
        owner, foreign_owner = uuid4(), uuid4()
        connection = await asyncpg.connect(database_url)
        try:
            for identity in (owner, foreign_owner):
                await connection.execute(
                    "INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",
                    identity,
                    str(identity) + "@example.invalid",
                )
        finally:
            await connection.close()
        return (
            owner,
            await auth.create_session(owner),
            await auth.create_session(foreign_owner),
        )

    try:
        asyncio.run(reset())
        backend = ROOT / "app/backend"
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "migrations"))
        command.upgrade(config, "head")
        owner, token, foreign_token = asyncio.run(account())
        import server

        server = importlib.reload(server)
        with (
            browser_session(server.app, root, token) as (page, errors, url),
            httpx.Client(base_url=url, timeout=7200) as client,
            ThreadPoolExecutor(max_workers=1) as database,
        ):
            client.cookies.set(auth.SESSION_COOKIE, token)
            with package.open("rb") as stream:
                imported = client.post(
                    "/api/packages/import",
                    files={"file": (package.name, stream, "application/zip")},
                )
            assert imported.status_code == 201, imported.text
            version = imported.json()["version"]["id"]
            client.headers["X-Lunar-Package-Version"] = version

            # Admission runs in a fresh child process against imported files, never
            # importing domain code into the API or reading the authoring checkout.
            async def imported_context():
                connection = await asyncpg.connect(database_url)
                try:
                    return await owned_context(connection, owner, UUID(version))
                finally:
                    await connection.close()

            imported_context_value = database.submit(
                asyncio.run, imported_context()
            ).result()
            version_root = storage.version_root(imported_context_value)
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("PYTHON", "BIOAGENTS_", "LUNAR_"))
            }
            admission = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    ADMISSION_PROGRAM,
                    str(version_root / "repository/runtime"),
                    str(version_root / "data-sources/local"),
                    json.dumps(selected if explicit else None),
                ],
                env=environment,
                cwd=root,
                text=True,
                capture_output=True,
                timeout=180,
            )
            assert admission.returncode == 0, admission.stderr[-4000:]
            prepared = client.post(f"/api/packages/versions/{version}/prepare")
            assert prepared.status_code == 200, prepared.text
            created = client.post(
                "/api/ai-models",
                json={
                    "name": "PRISM live E2E model",
                    "provider": os.environ["LUNAR_E2E_MODEL_PROVIDER"],
                    "model_id": os.environ["LUNAR_E2E_MODEL_ID"],
                    "api_key": os.environ["LUNAR_E2E_MODEL_API_KEY"],
                    "api_base": os.getenv("LUNAR_E2E_MODEL_API_BASE"),
                    "api_version": os.getenv("LUNAR_E2E_MODEL_API_VERSION"),
                    "config": json.loads(os.getenv("LUNAR_E2E_MODEL_CONFIG", "{}")),
                },
            )
            assert created.status_code == 201, created.text
            model_id = UUID(created.json()["id"])

            async def context_and_model():
                connection = await asyncpg.connect(database_url)
                try:
                    return (
                        await owned_context(connection, owner, UUID(version)),
                        await load_owned_ai_model(
                            connection, model_id=model_id, user_id=owner
                        ),
                    )
                finally:
                    await connection.close()

            context, model = database.submit(asyncio.run, context_and_model()).result()
            available = {row["id"] for row in client.get("/api/prism/workflows").json()}
            assert set(selected) <= available
            # Exercise actual graph-backed Run forms without submitting; setup-only
            # can validate UI admission while genuine model execution awaits approval.
            for workflow_id in selected:
                packet = {
                    **manifest["workflows"][workflow_id]["admission"]["request"],
                    "operation": "run",
                    "ai_model_id": str(model.id),
                }
                dialog = prepare_browser_run(
                    page, client, url, version, workflow_id, model, packet
                )
                dialog.get_by_role("button", name="Cancel", exact=True).click()
            assert not errors, errors
            (root / "campaign").mkdir()
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            (root / "campaign/identity.json").write_text(
                json.dumps(
                    {
                        "package_sha256": digest,
                        "package_path": str(package.resolve()),
                        "worker_base_image": worker_image,
                        "version_id": str(context.version_id),
                        "owner_id": str(owner),
                        "model": {
                            "id": str(model.id),
                            "provider": model.provider,
                            "model_id": model.model_id,
                        },
                        "selected_workflow_ids": selected,
                        "run_forms_checked_without_submission": selected,
                        "acceptance_manifest": manifest,
                    },
                    indent=2,
                )
            )
            yield client, storage, context, model, manifest, root / "campaign", digest, page, errors, url, foreign_token
    finally:
        sys.meta_path.remove(guard)
        patch.undo()


def assert_provenance(document, run, model, workflow_id):
    encoded = json.dumps(document, sort_keys=True)
    for kind in (
        "AuthenticatedUser",
        "LunarRunner",
        "SelectedAIModel",
        "PrismAgent",
        "ActivatedPrismSkill",
        "PrismEffectResult",
        "InputEntity",
        "WorkflowOutput",
        str(model.id),
    ):
        assert kind in encoded
    assert "ConsumedDataSource" in encoded
    output_id = run["outputs"][0]["provenance_entity_id"]
    assert any(
        row["prov:generatedEntity"] == output_id
        and ":prism-value:" in row["prov:usedEntity"]
        for row in document.get("wasDerivedFrom", {}).values()
    )


@pytest.mark.parametrize("workflow_id", campaign_cases())
def test_public_workflow_executes_with_real_litellm_provider(
    workflow_id, live_installation
):
    (
        client,
        storage,
        context,
        model,
        manifest,
        evidence_root,
        package_digest,
        page,
        errors,
        url,
        foreign_token,
    ) = live_installation
    case = manifest["workflows"][workflow_id]
    request = {
        **{
            key: value
            for key, value in case["admission"]["request"].items()
            if key != "mode"
        },
        "operation": "run",
        "ai_model_id": str(model.id),
    }
    assert "mode" not in request
    run_id = submit_browser_run(
        page, client, url, str(context.version_id), workflow_id, model, request
    )
    (evidence_root / (workflow_id + ".json")).write_text(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "request": request,
                "package_sha256": package_digest,
                "version_id": str(context.version_id),
                "run_id": run_id,
                "verification": "pending",
            },
            indent=2,
        )
    )
    started = time.monotonic()
    deadline = started + case["timeout_seconds"]
    while True:
        response = client.get("/api/prism/runs/" + run_id)
        assert response.status_code == 200, response.text
        run = response.json()
        if run["state"] in {"completed", "failed", "cancelled"}:
            break
        assert time.monotonic() < deadline, "Genuine-provider workflow timed out"
        time.sleep(1)
    assert model.api_key not in json.dumps(run, sort_keys=True)
    (evidence_root / (workflow_id + ".json")).write_text(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "request": request,
                "package_sha256": package_digest,
                "version_id": str(context.version_id),
                "run_id": run_id,
                "elapsed_seconds": time.monotonic() - started,
                "run": run,
            },
            indent=2,
        )
    )
    assert run["state"] == "completed", run.get("error_summary")
    assert run["ai_model_snapshot"] == {
        "id": str(model.id),
        "name": model.name,
        "provider": model.provider,
        "model_id": model.model_id,
    }
    assert run["version_id"] == str(context.version_id) and not run["imported"]
    result = next(
        event["detail"]["worker_result"]
        for event in run["events"]
        if event["stage_id"] == "worker:result"
    )
    assert_live_result(
        result, storage.run_root(context, UUID(run_id)), workflow_id, model, case
    )
    assert run["outputs"][0]["structured_value"]["status"] == "accepted"
    assert {"report-verification.json", "report-persistence-verification.json"} <= {
        row["artifact_key"] for row in run["artifacts"]
    }

    for fmt in ("prov-json", "json-ld"):
        exported = client.get(
            "/api/prism/runs/" + run_id + "/provenance", params={"format": fmt}
        )
        assert exported.status_code == 200, exported.text
        document = exported.json()["document"]
        if fmt == "prov-json":
            assert_provenance(document, run, model, workflow_id)
        else:
            assert "SelectedAIModel" in json.dumps(
                document
            ) and "PrismEffectResult" in json.dumps(document)
    assert model.api_key not in json.dumps(run, sort_keys=True)
    try:
        verify_browser_report(page, url, run, case, foreign_token, evidence_root)
        assert not errors, errors
    finally:
        page.screenshot(
            path=str(evidence_root / (workflow_id + "-browser.png")), full_page=True
        )
        (evidence_root / (workflow_id + "-browser-errors.json")).write_text(
            json.dumps(errors)
        )
    evidence = evidence_root / (workflow_id + ".json")
    recorded = json.loads(evidence.read_text())
    recorded["verification"] = {
        "scientific": "passed",
        "persistence": "passed",
        "provenance": "passed",
        "browser": "passed",
    }
    evidence.write_text(json.dumps(recorded, indent=2))


def prepare_browser_run(page, client, url, version_id, workflow_id, model, request):
    registry = next(
        row
        for row in client.get("/api/prism/workflows").json()
        if row["id"] == workflow_id
    )
    viewer_id = registry.get("metadata", {}).get("viewer_workflow_id", workflow_id)
    page.goto(
        url
        + "/prism?"
        + urlencode(
            {"package_version_id": version_id, "workflow": viewer_id, "view": "run"}
        )
    )
    expect(page.get_by_label("Package version", exact=True)).to_have_value(version_id)
    page.get_by_role("button", name="Run", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(
        dialog.get_by_role("heading", name="Run " + registry["name"], exact=True)
    ).to_be_visible()
    datasets = {row["dataset_id"]: row for row in registry["datasets"]}
    assert set(request["inputs"]) == {
        "dataset_ids"
    }, "Add UI entry for newly admitted non-dataset inputs"
    for dataset_id in request["inputs"]["dataset_ids"]:
        dialog.get_by_role(
            "checkbox", name=datasets[dataset_id]["name"], exact=True
        ).check()
    dialog.get_by_role(
        "checkbox", name="Allow declared public network reads for this run"
    ).set_checked(request["network_authority"])
    dialog.get_by_label("Run AI model").click()
    page.get_by_role(
        "option", name=f"{model.name} ({model.provider}/{model.model_id})", exact=True
    ).click()
    expect(dialog.get_by_role("button", name="Run", exact=True)).to_be_enabled()
    return dialog


def submit_browser_run(page, client, url, version_id, workflow_id, model, request):
    dialog = prepare_browser_run(
        page, client, url, version_id, workflow_id, model, request
    )
    endpoint = f"/api/prism/workflows/{workflow_id}/runs"
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(endpoint)
    ) as response:
        dialog.get_by_role("button", name="Run", exact=True).click()
    accepted = response.value
    assert accepted.status == 202, accepted.text()
    assert accepted.request.post_data_json == request
    return accepted.json()["run_id"]


def verify_browser_report(page, url, run, case, foreign_token, evidence_root):
    run_path = "/prism/runs/" + run["id"]
    page.goto(url + run_path)
    page.get_by_role("link", name="View report", exact=True).click()
    report = page.locator(".run-report")
    expect(report.locator(".report-block").first).to_be_attached(timeout=30000)
    assert report.locator("table").count() >= len(case["report"]["table_keys"])
    assert report.locator("img").count() >= len(case["report"]["figure_keys"])
    page.wait_for_function(
        """() => [...document.querySelectorAll('.run-report img')].every(image => image.complete && image.naturalWidth > 0)""",
        timeout=30000,
    )
    expect(report.locator(".report-artifact-error")).to_have_count(0)
    # Check all local targets, including links in closed disclosures and tabs.
    links = report.locator("a").evaluate_all(
        '(links) => links.map(link => link.getAttribute("href"))'
    )
    for target in set(links):
        if target.startswith("#"):
            assert page.evaluate(
                "(target) => !!document.getElementById(decodeURIComponent(target.slice(1)))",
                target,
            ), target
        elif target.startswith("/"):
            response = page.request.get(target)
            assert response.status == 200, target
    for artifact in run["artifacts"]:
        response = page.request.get(artifact["url"])
        assert response.status == 200, artifact["safe_locator"]
    page.screenshot(path=str(evidence_root / (run["workflow_id"] + "-report.png")))
    page.goto(url + run_path)
    page.get_by_role("link", name="View provenance", exact=True).click()
    expect(page.get_by_role("button", name="PROV-JSON", exact=True)).to_be_visible()
    # An independently authenticated user must not read this same run or assets.
    foreign = page.context.browser.new_context(base_url=url)
    try:
        foreign.add_cookies(
            [{"name": auth.SESSION_COOKIE, "value": foreign_token, "url": url}]
        )
        denied = foreign.request.get("/api/prism/runs/" + run["id"])
        assert denied.status == 404
        for artifact in run["artifacts"]:
            assert foreign.request.get(artifact["url"]).status == 404
        other_page = foreign.new_page()
        other_page.goto(url + run_path + "/report")
        expect(
            other_page.get_by_role("heading", name="Report not found", exact=True)
        ).to_be_visible()
    finally:
        foreign.close()


def assert_live_result(result, root, workflow_id, model, case):
    assert result["status"] == "succeeded", result.get("error")
    projected = result["result"]
    assert (
        projected["markdown"].strip()
        and projected["report_verification"]["status"] == "passed"
    )
    assert (
        projected["analysis_results"]["staged_analysis"]
        == result["prepared_input"]["analysis_results"]
    )
    staged = projected["analysis_results"]["staged_analysis"]
    packet = staged["reporting_inputs"]
    assert (
        packet["workflow_id"] == workflow_id
        and packet["provenance"]["new_scientific_execution"] is True
    )
    assert (
        packet["provenance"]["selected_dataset_ids"] == case["registered_dataset_ids"]
    )
    assert [row["key"] for row in packet["tables"]] == case["report"]["table_keys"]
    assert [row["key"] for row in packet["figures"]] == case["report"]["figure_keys"]
    assert (
        projected["structured_value"]["report_layout"]["blocks"]
        and projected["narrative_slots"]
    )
    stages = [
        event["payload"] for event in result["events"] if event["kind"] == "stage"
    ]
    for required in case["required_stages"]:
        identity = required.get("worker_stage_id", required["stage_id"])
        matching = [
            row
            for row in stages
            if row["stage_id"] == identity and row["status"] == "completed"
        ]
        assert len(matching) == 1, identity
    sources = [
        event["payload"] for event in result["events"] if event["kind"] == "source"
    ]
    assert sources and all(row["access_mode"] != "offline_fixture" for row in sources)
    assert set(case["registered_dataset_ids"]) <= {
        row["source_local_identifier"] for row in sources
    }
    assert all(row["content_digest"].startswith("sha256:") for row in sources)
    for name in ("report-verification.json", "report-persistence-verification.json"):
        assert json.loads((root / name).read_text())["status"] == "passed"
    for path, expected in packet["files"].items():
        assert (
            hashlib.sha256((root / path).read_bytes()).hexdigest() == expected["sha256"]
        )
    native = json.loads((root / "prism-run-summary.json").read_text())
    assert (
        native["status"] == "accepted"
        and native["source_hash"].startswith("sha256:")
        and native["module_hashes"]
    )
    agents = [
        row
        for row in stages
        if row.get("detail", {}).get("event_kind") == "agent-invoked"
    ]
    assert agents and len(native["effect_records"]) == len(agents)
    assert all(row["detail"]["effect_record_id"] for row in agents)
    recorder = EffectRecorder(FileArtifactStore(root / "prism-effects"))
    for effect in native["effect_records"]:
        assert effect["invocation"]["handler"] == "litellm"
        assert effect["observation"]["status"] == "accepted"
        assert effect["observation"]["provenance"] == {
            "provider": "litellm",
            "model": f"{model.provider}/{model.model_id}",
        }
        assert (
            recorder.offline_verify(effect_record_from_dict(effect)).status
            == "verified"
        )
    assert model.api_key not in json.dumps(result)
