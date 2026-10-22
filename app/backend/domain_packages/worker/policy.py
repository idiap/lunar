# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Invocation-local policy results from one immutable package worker."""

from copy import deepcopy
import json

from .sandbox import WorkerUnavailable


class WorkerPolicy:
    def __init__(self, runtime, component_ids, *, hook_id=None):
        hooks = runtime.manifest["runtime"]["planning_hooks"]
        if hook_id is None:
            if len(hooks) != 1:
                raise WorkerUnavailable("Select exactly one registered planning hook")
            hook_id = hooks[0]
        if hook_id not in hooks:
            raise WorkerUnavailable(
                "Planning hook is not registered in the selected version"
            )
        self.runtime = runtime
        self.hook_id = hook_id
        self.component_ids = tuple(dict.fromkeys(component_ids))
        self.cache = {}

    @staticmethod
    def key(operation, inputs):
        return json.dumps(
            [operation, inputs], sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def evaluate(self, operation, inputs):
        key = self.key(operation, inputs)
        if key not in self.cache:
            if (
                operation == "candidate_adjustment"
                and inputs["component_id"] in self.component_ids
            ):
                calls = [
                    {
                        "operation": operation,
                        "input": {**inputs, "component_id": identity},
                    }
                    for identity in self.component_ids
                ]
                values = []
                for start in range(0, len(calls), 4096):
                    batch = calls[start : start + 4096]
                    returned = self.runtime.policy_many(self.hook_id, batch)
                    if not isinstance(returned, list) or len(returned) != len(batch):
                        raise WorkerUnavailable("Invalid package policy batch response")
                    values.extend(returned)
                for call, value in zip(calls, values):
                    self.cache[self.key(operation, call["input"])] = deepcopy(value)
            else:
                self.cache[key] = deepcopy(
                    self.runtime.policy(self.hook_id, operation, inputs)
                )
        return deepcopy(self.cache[key])
