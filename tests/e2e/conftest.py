# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit disposable PostgreSQL and real worker prerequisites for E0/E1."""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.fixture
def e2e_database_url(monkeypatch):
    url = os.getenv("LUNAR_E2E_DATABASE_URL", "")
    if not url or not urlparse(url).path.lower().endswith("_e2e_test"):
        pytest.fail(
            "E2E requires an explicit disposable LUNAR_E2E_DATABASE_URL ending in _e2e_test"
        )
    monkeypatch.setenv("DATABASE_URL", url)
    import asyncpg
    from alembic import command
    from alembic.config import Config
    import schema

    monkeypatch.setattr(schema, "DATABASE_URL", url)

    async def reset():
        connection = await asyncpg.connect(url)
        try:
            await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        finally:
            await connection.close()

    asyncio.run(reset())
    backend = Path(__file__).resolve().parents[2] / "app/backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(config, "head")
    asyncio.run(schema.ensure_schema())
    return url


@pytest.fixture(scope="session")
def worker_image():
    reference = os.environ.get("LUNAR_WORKER_IMAGE", "")
    if not reference:
        pytest.fail(
            "E0 requires LUNAR_WORKER_IMAGE naming the built host-owned runner image"
        )
    from domain_packages.worker.preparation import _image_id

    return _image_id(reference)
