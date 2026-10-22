# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""A stop request is scoped to an owned active run and interrupts execution."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from domain_packages.worker import runs as worker_runs
from prism_runs import routes, service


def reasoning_row(sequence, name, status, *, workflow="ReviewedReasoning"):
    return {
        "source_event_key": f"reasoning-step:trace:{sequence}:{status}",
        "event_kind": "stage",
        "source": json.dumps(
            {
                "stage": "Reasoning step",
                "status": status,
                "reasoning_step": {
                    "name": name,
                    "component": "steps." + name,
                    "workflow": workflow,
                },
            }
        ),
    }


def reasoning_workflow(*steps):
    return {
        "id": "example",
        "metadata": {
            "viewer_workflow_id": "source:0123456789abcdef01234567:ReviewedReasoning",
            "reasoning_contract": {
                "workflow": "ReviewedReasoning",
                "steps": list(steps),
            },
        },
    }


def test_required_reasoning_log_accepts_only_complete_declared_steps():
    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    run_id = uuid4()

    class Connection:
        async def fetch(self, *_args):
            return [
                reasoning_row(0, "first", "running"),
                reasoning_row(0, "first", "completed"),
                reasoning_row(1, "second", "running"),
                reasoning_row(1, "second", "completed"),
                reasoning_row(2, "native_helper", "completed", workflow="NativeHelper"),
            ]

    asyncio.run(
        worker_runs.require_complete_reasoning_log(
            Connection(), context, run_id, reasoning_workflow("first", "second")
        )
    )


@pytest.mark.parametrize(
    "rows,message",
    [
        ([], "no reasoning steps"),
        ([reasoning_row(0, "first", "running")], "incomplete step transitions"),
        (
            [
                reasoning_row(0, "first", "running"),
                reasoning_row(0, "first", "completed"),
            ],
            "missing required steps",
        ),
        (
            [
                reasoning_row(0, "first", "running", workflow="NativeHelper"),
                reasoning_row(0, "first", "completed", workflow="NativeHelper"),
            ],
            "no reasoning steps",
        ),
        (
            [
                reasoning_row(0, "first", "running"),
                reasoning_row(0, "first", "completed"),
                reasoning_row(1, "first", "running"),
                reasoning_row(1, "first", "completed"),
                reasoning_row(2, "second", "running"),
                reasoning_row(2, "second", "completed"),
            ],
            "missing required steps",
        ),
    ],
)
def test_required_reasoning_log_fails_closed(rows, message):
    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())

    class Connection:
        async def fetch(self, *_args):
            return rows

    with pytest.raises(worker_runs.WorkerUnavailable, match=message):
        asyncio.run(
            worker_runs.require_complete_reasoning_log(
                Connection(),
                context,
                uuid4(),
                reasoning_workflow("first", "second"),
            )
        )


def test_successful_worker_result_cannot_complete_without_required_reasoning(
    monkeypatch,
):
    run_id = uuid4()
    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    updates = []

    class Connection:
        async def fetchval(self, *_args):
            return True

        async def fetchrow(self, *_args):
            return {
                "workflow_id": "example",
                "safe_input_manifest": {
                    "runtime_image": "sha256:runtime",
                    "inputs": {},
                    "network_authority": False,
                },
                "ai_model_id": None,
            }

        async def fetch(self, *_args):
            return []

        async def execute(self, query, *args):
            if "UPDATE prism_runs SET state=" in query:
                updates.append((query, args))
                return "UPDATE 1"
            return "SELECT 1"

        @asynccontextmanager
        async def transaction(self):
            yield

    workflow = reasoning_workflow("first")

    class Runtime:
        image = "sha256:runtime"

        def __init__(self):
            self.context = context

        def workflow(self, _workflow_id):
            return workflow

        def execute(self, *_args, **_kwargs):
            return {
                "status": "succeeded",
                "error": None,
                "events": [],
                "artifacts": [],
                "result": {"markdown": "unreleased", "structured_value": {}},
            }

    async def provenance(*_args, **_kwargs):
        pass

    monkeypatch.setattr("provenance.service.persist_run_provenance", provenance)
    result = asyncio.run(worker_runs.execute_queued(Connection(), Runtime(), run_id))
    assert result["state"] == "failed"
    assert "no reasoning steps were recorded" in result["error"]
    assert len(updates) == 1
    assert updates[0][1][3] == "failed"


def test_stop_route_requires_owned_active_run(monkeypatch):
    target_id = uuid4()
    signal = threading.Event()
    service.ACTIVE_RUNS[target_id] = signal
    state = {"value": "running", "owned": True}

    class Connection:
        async def close(self):
            pass

    async def authenticated(_request):
        return {"id": "owner"}

    async def connect():
        return Connection()

    async def get_run(_connection, *, run_id, user_id):
        assert run_id == target_id and user_id == "owner"
        return {"state": state["value"]} if state["owned"] else None

    monkeypatch.setattr(routes, "authenticated_user", authenticated)
    monkeypatch.setattr(routes, "connect", connect)
    monkeypatch.setattr(routes, "get_run", get_run)
    app = Starlette(
        routes=[
            Route(
                "/api/prism/runs/{run_id}/stop", routes.prism_run_stop, methods=["POST"]
            )
        ]
    )
    try:
        with TestClient(app) as client:
            state["owned"] = False
            assert client.post(f"/api/prism/runs/{target_id}/stop").status_code == 404
            assert not signal.is_set()
            state["owned"] = True
            state["value"] = "completed"
            assert client.post(f"/api/prism/runs/{target_id}/stop").status_code == 409
            assert not signal.is_set()
            state["value"] = "running"
            response = client.post(f"/api/prism/runs/{target_id}/stop")
            assert response.status_code == 202
            assert response.json()["state"] == "stopping"
            assert signal.is_set()
    finally:
        service.ACTIVE_RUNS.pop(target_id, None)


def test_queued_run_stopped_before_worker_starts(monkeypatch):
    run_id = uuid4()
    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    cancelled = threading.Event()
    cancelled.set()

    class Connection:
        def __init__(self):
            self.updates = []

        async def fetchval(self, *_args):
            return True

        async def fetchrow(self, *_args):
            return {
                "workflow_id": "example",
                "safe_input_manifest": {},
                "ai_model_id": None,
            }

        async def execute(self, query, *args):
            if "UPDATE prism_runs" in query:
                self.updates.append(args)
                return "UPDATE 1"
            return "SELECT 1"

        @asynccontextmanager
        async def transaction(self):
            yield

    async def provenance(*_args, **_kwargs):
        pass

    monkeypatch.setattr("provenance.service.persist_run_provenance", provenance)
    connection = Connection()
    runtime = SimpleNamespace(context=context, workflow=lambda _id: {"id": "example"})
    result = asyncio.run(
        worker_runs.execute_queued(connection, runtime, run_id, cancelled=cancelled)
    )
    assert result["state"] == "cancelled"
    assert connection.updates[-1][3] == "cancelled"
