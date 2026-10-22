# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Selected policy batches stay local to one planner invocation."""

import pytest
from domain_packages.worker.policy import WorkerPolicy
from domain_packages.worker.sandbox import WorkerUnavailable


class Runtime:
    manifest = {"runtime": {"planning_hooks": ["domain-policy"]}}

    def __init__(self):
        self.calls = []

    def policy_many(self, hook, calls):
        self.calls.append((hook, calls))
        return [
            {"score": len(row["input"]["component_id"]), "reasons": []} for row in calls
        ]

    def policy(self, hook, operation, inputs):
        self.calls.append((hook, operation, inputs))
        return {"value": inputs}


def test_candidate_batch_is_cached_only_within_selected_provider():
    runtime = Runtime()
    policy = WorkerPolicy(runtime, ["skill:a", "skill:b"])
    inputs = {"frame": {"command_text": "inspect"}, "component_id": "skill:a"}
    first = policy.evaluate("candidate_adjustment", inputs)
    first["reasons"].append("caller mutation")
    assert policy.evaluate("candidate_adjustment", inputs)["reasons"] == []
    policy.evaluate("candidate_adjustment", {**inputs, "component_id": "skill:b"})
    assert len(runtime.calls) == 1
    assert [row["input"]["component_id"] for row in runtime.calls[0][1]] == [
        "skill:a",
        "skill:b",
    ]
    policy.evaluate(
        "candidate_adjustment", {**inputs, "frame": {"command_text": "changed"}}
    )
    assert len(runtime.calls) == 2
    WorkerPolicy(runtime, ["skill:a"]).evaluate("candidate_adjustment", inputs)
    assert len(runtime.calls) == 3


def test_unknown_candidate_is_never_substituted_for_selected_candidate():
    runtime = Runtime()
    value = WorkerPolicy(runtime, ["skill:a"]).evaluate(
        "candidate_adjustment", {"component_id": "foreign", "frame": {}}
    )
    assert value["value"]["component_id"] == "foreign"
    assert runtime.calls[0][1] == "candidate_adjustment"


def test_malformed_batch_is_not_cached():
    runtime = Runtime()
    runtime.policy_many = lambda hook, calls: []
    provider = WorkerPolicy(runtime, ["skill:a"])
    with pytest.raises(WorkerUnavailable, match="Invalid package policy batch"):
        provider.evaluate(
            "candidate_adjustment", {"component_id": "skill:a", "frame": {}}
        )
    assert provider.cache == {}


def test_multiple_hooks_require_explicit_selection():
    runtime = Runtime()
    runtime.manifest = {"runtime": {"planning_hooks": ["first", "second"]}}
    with pytest.raises(WorkerUnavailable, match="Select exactly one"):
        WorkerPolicy(runtime, [])
    assert WorkerPolicy(runtime, [], hook_id="second").hook_id == "second"
