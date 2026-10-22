# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Fresh standalone Compose, recreation, and matched backup restore (real E0)."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from domain_packages.archive import validate_archive
from test_package_browser import browser_zip

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def command(argv, **kwargs):
    return subprocess.run(
        argv, check=True, capture_output=True, text=True, **kwargs
    ).stdout


def wait_ready(client):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if client.get("/api/packages/versions", timeout=1).status_code == 401:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    pytest.fail("Container installation did not start within 90 seconds")


def test_fresh_compose_recreation_and_matched_backup(
    tmp_path, worker_image, monkeypatch
):
    # Compose shell variables override env files; exclude the host pytest database.
    for key in (
        "DATABASE_URL",
        "LUNAR_PACKAGE_STORAGE_ROOT",
        "PORT",
        "PUBLIC_BASE_URL",
        "AUTH_SECRET",
        "LUNAR_WORKER_IMAGE",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    # The only bind mounts are this fresh storage root and the host-owned Docker socket.
    # Domain fixtures reach the API exclusively as ZIP bytes over HTTP.
    for image in ("lunar-backend:local", "lunar-frontend:local"):
        command(["docker", "image", "inspect", image])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    host = os.getenv("LUNAR_E2E_DOCKER_HOST_ADDRESS", "127.0.0.1")
    projects = []

    def installation(label):
        project = "lunar-e0-" + uuid4().hex[:12]
        storage = tmp_path / label / "packages"
        storage.mkdir(parents=True)
        env = tmp_path / (label + ".env")
        env.write_text(
            f"LUNAR_PACKAGE_STORAGE_ROOT={storage}\nLUNAR_WORKER_IMAGE={worker_image}\n"
            f"PORT={port}\nPUBLIC_BASE_URL=http://{host}:{port}\n"
            "AUTH_SECRET=disposable-container-test-only\nAPI_RATE_LIMIT_REQUESTS=10000\n"
        )
        argv = [
            "docker",
            "compose",
            "--env-file",
            str(env),
            "-p",
            project,
            "-f",
            str(ROOT / "app/docker-compose.yml"),
        ]
        projects.append(argv)
        return project, env, argv

    first, first_env, compose = installation("original")
    archive = browser_zip(tmp_path, "container-version")
    try:
        command(compose + ["up", "-d", "--no-build"])
        with httpx.Client(base_url=f"http://{host}:{port}", timeout=120) as client:
            wait_ready(client)
            command(
                compose
                + [
                    "exec",
                    "-T",
                    "backend",
                    "python",
                    "-c",
                    "import importlib.util; from pathlib import Path; assert importlib.util.find_spec('catalog') is None; assert not Path('/workspace/catalog').exists()",
                ]
            )
            # Set up only a verified test account; all domain operations use real routes.
            setup = """import asyncio,uuid,asyncpg,auth,json
async def main():
    connection=await asyncpg.connect(auth.DATABASE_URL)
    owner=uuid.uuid4()
    await connection.execute("INSERT INTO users(id,email,password_hash,email_verified_at) VALUES($1,$2,'disabled',NOW())",owner,str(owner)+'@example.invalid')
    await connection.close()
    print(json.dumps({'token':await auth.create_session(owner)}))
asyncio.run(main())
"""
            token = json.loads(
                command(compose + ["exec", "-T", "backend", "python", "-c", setup])
            )["token"]
            client.cookies.set("report_session", token)
            assert client.get("/api/packages/versions").json() == {"versions": []}
            uploaded = client.post(
                "/api/packages/import",
                files={
                    "file": ("package.zip", archive.read_bytes(), "application/zip")
                },
            )
            assert uploaded.status_code == 201, uploaded.text
            version = uploaded.json()["version"]["id"]
            headers = {"X-Lunar-Package-Version": version}
            prepared = client.post(f"/api/packages/versions/{version}/prepare")
            assert prepared.status_code == 200, prepared.text

            def execute():
                response = client.post(
                    "/api/prism/workflows/inventory/runs",
                    headers=headers,
                    json={"inputs": {"count": 41}},
                )
                assert response.status_code == 202, response.text
                run_id = response.json()["run_id"]
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    result = client.get(
                        "/api/prism/runs/" + run_id, headers=headers
                    ).json()
                    if result["state"] in ("completed", "failed"):
                        assert result["state"] == "completed", result
                        assert result["outputs"][0]["structured_value"] == {"count": 42}
                        return run_id
                    time.sleep(0.2)
                pytest.fail("Container worker did not finish")

            run_id = execute()
            export = client.get(f"/api/packages/versions/{version}/export")
            assert export.status_code == 200, export.text
            export_path = tmp_path / "before.zip"
            export_path.write_bytes(export.content)
            before = validate_archive(export_path, tmp_path / "before")
            assert len(before.documents["reports"]) == 2
            # Recreate every service, including PostgreSQL; retain its named volume.
            old = command(compose + ["ps", "-q"]).split()
            command(compose + ["up", "-d", "--force-recreate", "--no-build"])
            client.cookies.clear()
            wait_ready(client)
            client.cookies.set("report_session", token)
            assert not set(old).intersection(command(compose + ["ps", "-q"]).split())
            assert (
                client.get("/api/prism/runs/" + run_id, headers=headers).json()["state"]
                == "completed"
            )
            execute()  # A new worker after API/database recreation uses retained runtime bytes.
            checkpoint = tmp_path / "checkpoint"
            command(
                [
                    sys.executable,
                    str(ROOT / "scripts/installation_backup.py"),
                    "backup",
                    str(checkpoint),
                    "--project-name",
                    first,
                    "--env-file",
                    str(first_env),
                ]
            )
            command(
                compose + ["down"]
            )  # Keep original volume for comparison; fresh target is separate.
            second, second_env, restored = installation("restored")
            command(restored + ["up", "-d", "--wait", "db"])
            command(
                [
                    sys.executable,
                    str(ROOT / "scripts/installation_backup.py"),
                    "restore",
                    str(checkpoint),
                    "--project-name",
                    second,
                    "--env-file",
                    str(second_env),
                ]
            )
            client.cookies.clear()
            wait_ready(client)
            client.cookies.set("report_session", token)
            versions = client.get("/api/packages/versions").json()["versions"]
            assert [row["id"] for row in versions] == [version]
            assert (
                client.get("/api/prism/runs/" + run_id, headers=headers).json()["state"]
                == "completed"
            )
            execute()  # Restored package paths work at a different absolute storage root.
            exported = client.get(f"/api/packages/versions/{version}/export")
            assert exported.status_code == 200, exported.text
            path = tmp_path / "restored.zip"
            path.write_bytes(exported.content)
            after = validate_archive(path, tmp_path / "after")
            for kind in ("repository", "skills", "data-sources"):
                assert after.documents[kind] == before.documents[kind]
            original = next(
                row
                for row in before.documents["reports"]
                if row["name"] == "Stock report"
            )
            restored_report = next(
                row
                for row in after.documents["reports"]
                if row["name"] == "Stock report"
            )
            for key in (
                "content",
                "revisions",
                "attachments",
                "sections",
                "provenance",
            ):
                assert restored_report[key] == original[key]
            before_hashes = {
                item["path"]: item["sha256"] for item in before.manifest["files"]
            }
            after_hashes = {
                item["path"]: item["sha256"] for item in after.manifest["files"]
            }
            for name, digest in before_hashes.items():
                if not name.endswith(".json"):
                    assert after_hashes[name] == digest
            # Restore never overwrites a live installation.
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/installation_backup.py"),
                    "restore",
                    str(checkpoint),
                    "--project-name",
                    second,
                    "--env-file",
                    str(second_env),
                ],
                capture_output=True,
                text=True,
            )
            assert (
                rejected.returncode != 0 and "empty package storage" in rejected.stderr
            )
            with (checkpoint / "payload/database.dump").open("ab") as dump:
                dump.write(b"tampered")
            corrupted = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/installation_backup.py"),
                    "restore",
                    str(checkpoint),
                    "--project-name",
                    second,
                    "--env-file",
                    str(second_env),
                ],
                capture_output=True,
                text=True,
            )
            assert corrupted.returncode != 0 and "digest inventory" in corrupted.stderr
            assert client.get("/api/packages/versions").status_code == 200
    finally:
        for argv in projects:
            try:
                (tmp_path / (argv[5] + ".log")).write_text(
                    command(argv + ["logs", "--no-color"])
                )
            finally:
                command(argv + ["down", "--volumes", "--remove-orphans"])
