# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
import asyncio
from prism_runs.reasoning import Presentation, project_source
import prism_runs.reasoning_enrichment as enrichment


def test_reasoning_log_enrichment_does_not_block_and_deduplicates(monkeypatch):
    settled = []
    called = []
    pending = {}

    class Connection:
        async def close(self):
            pass

    async def connect():
        return Connection()

    async def settle(connection, entry_id, presentation):
        settled.append((entry_id, presentation.status))
        pending.pop(entry_id, None)
        return entry_id != "deleted"

    async def load_pending(connection, entry_id):
        return pending.get(entry_id)

    monkeypatch.setattr(enrichment, "pending_entry", load_pending)
    monkeypatch.setattr(enrichment, "connect", connect)
    monkeypatch.setattr(enrichment, "settle_presentation", settle)

    async def scenario():
        release = asyncio.Event()

        async def generate(source):
            called.append(source.stage)
            if source.stage == "Slow":
                await release.wait()
            return Presentation(
                status="ready", helper_text="Recorded outcome.", icon_id="information"
            )

        monkeypatch.setattr(enrichment, "generate_presentation", generate)

        def row(id, run, stage):
            value = dict(
                id=id,
                run_id=run,
                source=project_source(stage=stage, status="completed").model_dump(),
                presentation={"status": "pending"},
            )
            pending[id] = value
            return value

        first = row("one", "a", "Slow")
        enrichment.schedule_enrichment(first)
        enrichment.schedule_enrichment(first)
        enrichment.schedule_enrichment(row("two", "a", "Next"))
        enrichment.schedule_enrichment(row("deleted", "b", "Independent"))
        tasks = [worker.task for worker in enrichment.WORKERS.values()]
        await asyncio.sleep(0.02)
        assert called == ["Slow", "Independent"]
        assert settled == [("deleted", "ready")]
        release.set()
        await asyncio.gather(*tasks)
        assert called.count("Slow") == 1
        assert settled == [("deleted", "ready"), ("one", "ready"), ("two", "ready")]
        assert enrichment.WORKERS == {}
        # A stale pending snapshot delivered after settlement must not call again.
        enrichment.schedule_enrichment(first)
        await enrichment.WORKERS["a"].task
        assert called.count("Slow") == 1
        assert enrichment.WORKERS == {}

    asyncio.run(scenario())
