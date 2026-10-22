# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Run-scoped acknowledged thread-to-loop bridge for committed public entries."""

import asyncio
from datetime import datetime, timezone

from modules.common import connect
from prism_runs.reasoning import project_source
from prism_runs.reasoning_repository import insert_entry


class ReasoningWriter:
    def __init__(self, run_id, *, enrich=True):
        self.enrich = enrich
        self.run_id = run_id
        self.loop = asyncio.get_running_loop()

    async def write(
        self,
        *,
        source_event_key,
        event_kind,
        stage,
        status,
        observed_at=None,
        result=None,
        evidence_references=(),
        model_call=None,
        reasoning_step=None,
    ):
        source = project_source(
            stage=stage,
            status=status,
            result=result,
            evidence_references=evidence_references,
            model_call=model_call,
            reasoning_step=reasoning_step,
        )
        connection = await connect()
        try:
            row = await insert_entry(
                connection,
                run_id=self.run_id,
                source_event_key=source_event_key,
                event_kind=event_kind,
                observed_at=observed_at or datetime.now(timezone.utc),
                source=source,
            )
            if row is None:
                raise RuntimeError("reasoning run no longer exists")
            from prism_runs.reasoning_enrichment import schedule_enrichment

            if self.enrich:
                schedule_enrichment(row)
            return row
        finally:
            await connection.close()

    def observe(self, **event):
        try:
            return asyncio.run_coroutine_threadsafe(
                self.write(**event), self.loop
            ).result()
        except Exception:
            raise RuntimeError("Reasoning log persistence failed") from None
