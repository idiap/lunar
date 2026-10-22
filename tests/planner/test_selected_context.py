# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Selection, concurrent request isolation and foreign continuation/state rejection."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from lunar_planner.config import PlannerConfig, bind_planner, current_config
from lunar_planner.entrypoint import run_planner_request
from lunar_planner.ports import PlannerPorts, current_ports
from lunar_planner.staged_routing import validate_continuation
from tests.planner.neutral_fixture import surface


class SelectedSurface:
    def __init__(self, label):
        self.value = surface()
        self.value["skills"][0]["description"] = label + " warehouse stock observations"
        self.value["skills"][0]["purpose"] = self.value["skills"][0]["description"]
        self.value["selection_label"] = label

    def snapshot(self):
        return deepcopy(self.value)


def test_missing_selection_is_explicit_and_has_no_candidates():
    with bind_planner(PlannerConfig(), PlannerPorts()):
        result = run_planner_request("Plan warehouse inventory counts")
        assert result["status"] == "selection_required"
        assert not result.get("selected_target") and not result["executed"]


def test_concurrent_planners_do_not_share_config_catalog_or_continuations():
    first = PlannerConfig(context_identity=("owner-a", "package", "version-1"))
    second = PlannerConfig(context_identity=("owner-b", "package", "version-1"))

    async def task(config, label):
        ports = PlannerPorts(surface=SelectedSurface(label))
        with bind_planner(config, ports):
            await asyncio.sleep(0)
            assert current_config() == config and current_ports() is ports
            result = run_planner_request(
                "Explain warehouse stock-count results and preserve uncertainty"
            )
            continuation = result["planner_receipt"]["continuation"]
            assert continuation["context_identity"] == config.context_identity
            assert result["resource_scan"]["snapshot_posture"] == "host_surface_only"
            assert (
                not result["executed"]
                and not result["installation_allowed"]
                and not result["network_allowed"]
            )
            return continuation, continuation["snapshot_digest"]

    async def run():
        return await asyncio.gather(task(first, "first"), task(second, "second"))

    results = asyncio.run(run())
    with bind_planner(first, PlannerPorts(surface=SelectedSurface("first"))):
        validate_continuation(results[0][0], results[0][1])
        with pytest.raises(ValueError, match="another owner/package/version"):
            validate_continuation(results[1][0], results[1][1])


def test_identical_content_does_not_make_a_foreign_version_continuation_valid():
    selected = PlannerConfig(context_identity=("owner", "package", "version-1"))
    ports = PlannerPorts(surface=SelectedSurface("identical"))
    with bind_planner(selected, ports):
        receipt = run_planner_request("Explain warehouse stock counts")[
            "planner_receipt"
        ]
    with bind_planner(
        replace(selected, context_identity=("owner", "package", "version-2")), ports
    ):
        with pytest.raises(ValueError, match="another owner/package/version"):
            validate_continuation(
                receipt["continuation"], receipt["continuation"]["snapshot_digest"]
            )


def test_opaque_references_cannot_be_read_taken_or_cleared_in_another_context():
    from domain_packages.context import PackageContext, SelectionRequired, bind_context
    from state import OpaqueStateStore

    store = OpaqueStateStore()
    owner, package, version = uuid4(), uuid4(), uuid4()
    selected = PackageContext(owner, package, version, 1)
    with pytest.raises(SelectionRequired):
        store.put("continuation", {})
    with bind_context(selected):
        reference = store.put("continuation", {"private": "selected content"})
    for other in (
        PackageContext(uuid4(), package, version, 1),
        PackageContext(owner, uuid4(), version, 1),
        PackageContext(owner, package, uuid4(), 2),
    ):
        with bind_context(other):
            with pytest.raises(ValueError):
                store.get(reference, "continuation")
            with pytest.raises(ValueError):
                store.take(reference, "continuation")
            store.clear()
    with bind_context(selected):
        assert store.take(reference, "continuation") == {"private": "selected content"}
        with pytest.raises(ValueError):
            store.get(reference, "continuation")


def test_opaque_reference_can_be_consumed_only_once_across_threads():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from domain_packages.context import PackageContext, bind_context
    from state import OpaqueStateStore

    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    state = OpaqueStateStore()
    with bind_context(context):
        reference = state.put("review", {"verdict": "pass"})
    barrier = Barrier(8)

    def consume(_):
        with bind_context(context):
            barrier.wait()
            try:
                return state.take(reference, "review")
            except ValueError:
                return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(consume, range(8)))
    assert results.count({"verdict": "pass"}) == 1
    assert results.count(None) == 7
