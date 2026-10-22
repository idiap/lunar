# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Planner persistence and public reasoning checks moved from BioAgents B2."""

from pathlib import Path
from lunar_planner.entrypoint import run_planner_request
from lunar_planner.store import PlannerStore
from platform_runtime.reasoning_log import validate_reasoning_log


def test_planner_receipt_surfaces_normalized_reasoning_log() -> None:
    """Require the conversational planner entrypoint to expose its decision trace."""

    result = run_planner_request(
        "Turn this checked formal claim into a bounded explanation"
    )
    receipt = result["planner_receipt"]
    validate_reasoning_log(receipt["reasoning_log"])
    assert receipt["reasoning_log"]["subject"]["kind"] == "planner"
    assert len(receipt["reasoning_log"]["entries"]) == 3
    assert "reuse discovery and adjudication" in receipt["reasoning_log_markdown"]
    assert (
        receipt["reasoning_log"]["visibility"]["contains_hidden_chain_of_thought"]
        is False
    )
    assert result["reasoning_log"]["digest"] == receipt["reasoning_log"]["digest"]
    assert result["reasoning_log_markdown"] == receipt["reasoning_log_markdown"]


def test_planner_store_uses_portable_lock_and_atomic_replace(tmp_path: Path) -> None:
    """Keep planner persistence functional without a top-level fcntl dependency."""

    store = PlannerStore("portable-plan", root=tmp_path)
    event = store.append_event(
        "version",
        {"status": "planning", "version": 1},
        idempotency_key="portable-event",
    )
    assert event["sequence"] == 1
    assert store.read_events("version")[0]["event_hash"] == event["event_hash"]
