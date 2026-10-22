# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Actual HTTP workflow dispatch, failure artifacts and provenance in real workers."""

import asyncio
import json
import time
import asyncpg
import auth
import modules.common as common
import reports
import pytest
from starlette.testclient import TestClient
from domain_packages.importer import import_validated
from domain_packages.worker.preparation import prepare_runtime
import test_package_workers as fixtures

pytestmark = pytest.mark.e2e


def test_worker_http_preserves_failed_artifacts_and_provenance(
    e2e_database_url, tmp_path, worker_image, monkeypatch
):
    for module in (auth, common, reports):
        monkeypatch.setattr(module, "DATABASE_URL", e2e_database_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(
        fixtures,
        "PREPARE",
        fixtures.PREPARE.replace(
            b'    if action == "fetch":',
            b"""    if action == "invalid-reasoning":
        values["on_reasoning"](stage="invalid observation",status="invalid")
    if action == "fail":
        Path("/output/failure.txt").write_text("Observed failure artifact")
        values["on_reasoning"](stage="verification",status="failed")
        raise ValueError("Deliberate verification failure")
    if action == "fetch":""",
        ),
    )

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            first, storage, _ = await fixtures.imported(
                connection, tmp_path, "http-first", ""
            )
            second = await import_validated(
                connection,
                storage,
                user_id=first.user_id,
                archive=fixtures.archive(tmp_path, "http-second", ""),
            )
            foreign, _, _ = await fixtures.imported(
                connection, tmp_path, "http-foreign", ""
            )
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            for context in (first, second, foreign):
                await prepare_runtime(
                    connection, context, storage, base_image=worker_image
                )
            return first, second, foreign, await auth.create_session(first.user_id)
        finally:
            await connection.close()

    first, second, foreign, token = asyncio.run(setup())
    import importlib
    import server

    server = importlib.reload(server)
    with TestClient(server.app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        header = {"X-Lunar-Package-Version": str(first.version_id)}
        assert (
            client.get("/api/prism/workflows", headers=header).json()[0]["id"]
            == "inventory"
        )
        assert (
            client.get(
                "/api/prism/workflows",
                headers={"X-Lunar-Package-Version": str(foreign.version_id)},
            ).status_code
            == 404
        )
        before = client.get("/api/report", headers=header).json()
        for action, state in (
            (None, "completed"),
            ("fail", "failed"),
            ("invalid-reasoning", "failed"),
        ):
            accepted = client.post(
                "/api/prism/workflows/inventory/runs",
                headers=header,
                json={"inputs": {"count": 41, "action": action}},
            )
            assert accepted.status_code == 202, accepted.text
            run_id = accepted.json()["run_id"]
            deadline = time.monotonic() + 45
            while True:
                response = client.get("/api/prism/runs/" + run_id, headers=header)
                assert response.status_code == 200, response.text
                run = response.json()
                if run["state"] in {"completed", "failed", "cancelled"}:
                    break
                assert time.monotonic() < deadline, run
                time.sleep(0.05)
            assert run["state"] == state, run
            assert (
                run["version_id"] == str(first.version_id) and run["imported"] is False
            )
            assert len(run["outputs"]) == (1 if state == "completed" else 0)
            if state == "completed":
                assert run["outputs"][0]["structured_value"] == {"count": 42}
            for fmt in ("prov-json", "json-ld"):
                export = client.get(
                    "/api/prism/runs/" + run_id + "/provenance",
                    headers=header,
                    params={"format": fmt},
                )
                assert export.status_code == 200, export.text
                assert export.json()["format"] == fmt and state in json.dumps(
                    export.json()["document"]
                )
            if action == "invalid-reasoning":
                assert (
                    run["events"][0]["detail"]["worker_event"]["payload"]["status"]
                    == "invalid"
                )
            if action == "fail":
                artifact = next(
                    row
                    for row in run["artifacts"]
                    if row["artifact_key"] == "failure.txt"
                )
                assert client.get(artifact["url"]).text == "Observed failure artifact"
                reasoning = client.get(
                    "/api/prism/runs/reasoning",
                    headers=header,
                    params={"workflow_id": "inventory", "run_ids": run_id},
                )
                assert reasoning.status_code == 200, reasoning.text
                assert (
                    "verification" in reasoning.text
                    and '"state":"failed"' in reasoning.text
                )
            other = {"X-Lunar-Package-Version": str(second.version_id)}
            assert (
                client.get("/api/prism/runs/" + run_id, headers=other).status_code
                == 404
            )
            assert (
                client.get(
                    "/api/prism/runs/" + run_id + "/provenance", headers=other
                ).status_code
                == 404
            )
        after = client.get("/api/report", headers=header).json()
        assert len([row for row in after if row["generation_type"] != "prism"]) == len(
            [row for row in before if row["generation_type"] != "prism"]
        )
