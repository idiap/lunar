# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Fresh Lunar startup and authentication without any domain checkout."""

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse

import pytest


def test_isolated_startup_does_not_import_or_seed_a_domain(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    target = tmp_path / "app/backend"
    shutil.copytree(
        backend, target, ignore=shutil.ignore_patterns("__pycache__", "tests")
    )
    script = """
import asyncio, importlib.abc, sys
from starlette.testclient import TestClient
class NoDomain(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "catalog" or fullname.startswith(("catalog.", "bioagents_planner")):
            raise AssertionError("domain import at startup: " + fullname)
sys.meta_path.insert(0, NoDomain())
sys.path.insert(0, sys.argv[1])
import server
# Unit startup has no database; real recovery/auth startup is tested below.
async def no_database_recovery():
    pass
server.prepare_application = no_database_recovery
import asyncpg
async def forbidden_database(*args, **kwargs):
    raise AssertionError("Unit import/anonymous startup must not access a database")
asyncpg.connect = forbidden_database
with TestClient(server.app, base_url="http://localhost:8080") as client:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/skills").status_code == 401
result = asyncio.run(server.mcp.call_tool("planner", {"command_text": "Plan stock counts"}))
assert "Import and select a package version" in str(result)
assert not any(k == "catalog" or k.startswith("catalog.") for k in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(target)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_postgres_authentication_has_no_seeded_catalog(monkeypatch):
    url = os.getenv("LUNAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("LUNAR_TEST_DATABASE_URL is required for fresh PostgreSQL startup")
    if not urlparse(url).path.lower().endswith("_test"):
        pytest.fail("fresh startup requires a dedicated database ending in _test")
    import asyncpg
    from alembic import command
    from alembic.config import Config
    import auth
    import schema
    import server
    from starlette.testclient import TestClient

    async def reset():
        connection = await asyncpg.connect(url)
        try:
            await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        finally:
            await connection.close()

    asyncio.run(reset())
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(config, "head")
    asyncio.run(schema.ensure_schema())
    verification = []
    monkeypatch.setattr(
        auth, "send_verification_email", lambda email, token: verification.append(token)
    )
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/api/auth/signup",
            json={"email": "shell@example.invalid", "password": "local-test-password"},
        )
        assert response.status_code == 201, response.text
        assert len(verification) == 1
        response = client.get(
            "/api/auth/verify-email",
            params={"token": verification[0]},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text
        response = client.post(
            "/api/auth/signin",
            json={"email": "shell@example.invalid", "password": "local-test-password"},
        )
        assert response.status_code == 200, response.text
        assert client.get("/api/auth/me").status_code == 200
        response = client.get("/api/skills")
        assert response.status_code == 409
        assert response.json()["code"] == "selection_required"
        assert client.get("/api/prompts").json() == []

    async def counts():
        connection = await asyncpg.connect(url)
        try:
            return [
                await connection.fetchval(f"SELECT COUNT(*) FROM {table}")
                for table in ("skills", "data_sources", "prism_runs", "reports")
            ]
        finally:
            await connection.close()

    assert asyncio.run(counts()) == [0, 0, 0, 0]
