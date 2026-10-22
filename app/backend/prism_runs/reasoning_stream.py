# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authoritative snapshots over one PostgreSQL listener per visible run set."""

import asyncio
import json
import uuid

from modules.common import connect
from prism_runs.repository import get_run
from prism_runs.reasoning import ICON_IDS, ReasoningEntry, canonical_snapshot
from prism_runs.reasoning_repository import CHANNEL, read_entries

TERMINAL = {"completed", "failed", "cancelled"}


def sse(value):
    return "data: " + json.dumps(value, separators=(",", ":")) + "\n\n"


async def reasoning_snapshots(*, user_id, workflow_id, run_ids):
    connection = await connect()
    visible = set(run_ids)
    dirty = set(visible)
    wake = asyncio.Event()
    settled = set()

    def changed(_connection, _pid, _channel, payload):
        try:
            run_id = uuid.UUID(payload)
        except ValueError:
            return
        if run_id in visible:
            dirty.add(run_id)
            wake.set()

    try:
        # Listen first; notifications during reads remain in dirty for the next pass.
        await connection.add_listener(CHANNEL, changed)
        while visible:
            wake.clear()
            current = sorted(dirty, key=str)
            dirty.difference_update(current)
            for run_id in current:
                async with connection.transaction(
                    isolation="repeatable_read", readonly=True
                ):
                    run = await get_run(connection, run_id=run_id, user_id=user_id)
                    if run is None or run["workflow_id"] != workflow_id:
                        snapshot = {"type": "deleted", "run_id": str(run_id)}
                        visible.discard(run_id)
                    else:
                        entries = await read_entries(connection, run_id)
                        snapshot = {
                            "type": "snapshot",
                            "run_id": str(run_id),
                            "state": run["state"],
                            "entries": entries,
                            "icon_ids": ICON_IDS,
                            "canonical_log": canonical_snapshot(
                                str(run_id),
                                run["state"],
                                [ReasoningEntry.model_validate(row) for row in entries],
                            ),
                        }
                        if run["state"] in TERMINAL and all(
                            row["presentation"]["status"] != "pending"
                            for row in entries
                        ):
                            settled.add(run_id)
                        else:
                            settled.discard(run_id)
                yield sse(snapshot)
            if dirty:
                continue
            if visible <= settled:
                break
            try:
                await asyncio.wait_for(wake.wait(), 15)
            except TimeoutError:
                yield ": keepalive\n\n"
        yield sse({"type": "done"})
    finally:
        try:
            await connection.remove_listener(CHANNEL, changed)
        finally:
            await connection.close()
