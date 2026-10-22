# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Disposable PostgreSQL fixtures; never reset a non-test database."""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.fixture
def postgres_url(monkeypatch):
    url = os.getenv("LUNAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("LUNAR_TEST_DATABASE_URL is required for PostgreSQL integration")
    if not urlparse(url).path.lower().endswith("_test"):
        pytest.fail("integration database name must end with _test")
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
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(config, "head")
    asyncio.run(schema.ensure_schema())
    return url
