# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import os
import time

import asyncpg


async def wait_for_database() -> None:
    database_url = os.environ["DATABASE_URL"]
    deadline = time.monotonic() + 120
    while True:
        try:
            connection = await asyncpg.connect(database_url)
            await connection.close()
            return
        except (OSError, asyncpg.PostgresError):
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(wait_for_database())
