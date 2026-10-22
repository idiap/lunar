# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Serial per-run enrichment, independent of executor and browser lifetimes."""

import asyncio
import logging

from modules.common import connect
from prism_runs.reasoning import PublicSource
from prism_runs.reasoning_provider import generate_presentation
from prism_runs.reasoning_repository import pending_entry, settle_presentation

WORKERS = {}
logger = logging.getLogger(__name__)


class EnrichmentWorker:
    def __init__(self, run_id):
        self.run_id = run_id
        self.queue = asyncio.Queue()
        self.seen = set()
        self.task = asyncio.create_task(self.drain())

    async def drain(self):
        try:
            while not self.queue.empty():
                queued = self.queue.get_nowait()
                connection = await connect()
                try:
                    row = await pending_entry(connection, queued["id"])
                finally:
                    await connection.close()
                if row is None:
                    continue
                presentation = await generate_presentation(
                    PublicSource.model_validate(row["source"])
                )
                connection = await connect()
                try:
                    await settle_presentation(connection, row["id"], presentation)
                finally:
                    await connection.close()
        except Exception:
            # Persisted pending entries are settled by startup recovery after DB failure.
            logger.error(
                "Reasoning presentation persistence failed for run %s", self.run_id
            )
        finally:
            WORKERS.pop(self.run_id, None)


def schedule_enrichment(row):
    if row["presentation"]["status"] != "pending":
        return
    run_id = row["run_id"]
    worker = WORKERS.get(run_id)
    if worker is None:
        worker = WORKERS[run_id] = EnrichmentWorker(run_id)
    if row["id"] not in worker.seen:
        worker.seen.add(row["id"])
        worker.queue.put_nowait(row)
