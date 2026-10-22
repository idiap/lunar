# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real ZIP import, PostgreSQL runtime preparation, and isolated Prism execution."""

import asyncio
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4
import zipfile

import asyncpg
import pytest

from domain_packages.archive import validate_archive
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker.preparation import (
    prepare_runtime,
    recover_runtime_preparations,
)
from domain_packages.worker.sandbox import WorkerLimits, WorkerUnavailable
from domain_packages.worker.transport import invoke_worker

pytestmark = pytest.mark.e2e

PREPARE = b"""import base64,hashlib,json,os,time
from pathlib import Path

def prepare(**values):
    request=values["inputs"]
    action=request.get("action")
    if action == "fetch":
        fetch=values["public_fetch"]
        token=fetch("open",url="https://public.invalid/data")["token"]
        data=base64.b64decode(fetch("read",token=token,size=1024)["data"])
        Path("/output/download.txt").write_bytes(data)
        fetch("close",token=token)
    if action == "interrupt":
        values["on_reasoning"](stage="waiting",status="running")
        time.sleep(120)
    if action == "symlink":
        Path("/output/escape").symlink_to("/etc/passwd")
    return {"prepared_input":{"entry_argument_name":"request","value":{"count":request["count"]},
        "request_digest":hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest(),"analysis_results":{}},"state":None}

def plan(request):
    try:
        Path("/package/repository/forbidden").write_text("changed")
        readonly=False
    except OSError:
        readonly=True
    if request.get("operation")=="probe":
        return {"marker":Path("/package/repository/private.txt").read_text(),
            "visible":[Path(path).exists() for path in request["input"]["paths"]]}
    if request.get("operation")=="invalid-json":
        return {"value":float("nan")}
    return {"readonly":readonly,"host_secret":os.environ.get("LUNAR_WORKER_TEST_SECRET"),
        "host_socket":Path("/var/run/docker.sock").exists(),
        "collections":sorted(path.name for path in Path("/package").iterdir())}
"""
PRISM = b"""type InventoryRequest:
    count: Int

type InventoryResult:
    count: Int

def count_items(request: InventoryRequest) -> InventoryResult:
    return InventoryResult(count = request.count + 1)

type CountItems = (request: InventoryRequest) -> InventoryResult

reasoning InventoryReasoning(request: InventoryRequest) -> InventoryResult:
    [counted: CountItems(request)]
    return counted

workflow inventory(request: InventoryRequest) -> InventoryResult:
    [counted: count_items(request)]
    return counted

def main(request: InventoryRequest) -> InventoryResult:
    return solve inventory(request)
"""


def archive(tmp_path, label, requirements=None, *, planning_hooks=True):
    fixture = (
        Path(__file__).resolve().parents[1]
        / "domain_packages/fixtures/domain-package-v1/neutral-complete"
    )
    manifest = json.loads((fixture / "manifest.json").read_text())
    payloads = {
        row["path"]: (fixture / row["path"]).read_bytes() for row in manifest["files"]
    }
    additions = {
        "repository/prepare.py": PREPARE,
        "repository/main.prism": PRISM,
        "repository/private.txt": label.encode(),
    }
    if requirements is not None:
        additions["repository/requirements.lock"] = requirements.encode()
        manifest["runtime"]["requirements_lock"] = "repository/requirements.lock"
    payloads.update(additions)
    for name, content in additions.items():
        manifest["files"].append(
            {
                "path": name,
                "size": len(content),
                "media_type": "text/plain",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        manifest["collections"]["repository"][0]["files"].append(name)
    manifest["runtime"]["entrypoints"] = [
        {
            "id": operation,
            "operation": operation,
            "file": "repository/prepare.py",
            "callable": operation,
        }
        for operation in ("prepare", "plan")
    ]
    manifest["runtime"]["planning_hooks"] = ["plan"] if planning_hooks else []
    execution = {
        "declaration": "inventory",
        "id": "inventory",
        "entry_argument": "request",
        "prepare_hook": "prepare",
        "verify_hook": None,
        "metadata": {},
        "input_schema": {
            "type": "object",
            "required": ["count"],
            "properties": {
                "count": {"type": "integer"},
                "action": {"type": ["string", "null"]},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["structured_value"],
            "properties": {
                "structured_value": {
                    "type": "object",
                    "required": ["count"],
                    "properties": {"count": {"type": "integer"}},
                }
            },
        },
    }
    payloads["repository/main.prism"] = (
        "# lunar-runtime: " + json.dumps(execution) + "\n"
    ).encode() + PRISM
    content = payloads["repository/main.prism"]
    next(
        row for row in manifest["files"] if row["path"] == "repository/main.prism"
    ).update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    path = tmp_path / (label + ".zip")
    with zipfile.ZipFile(path, "w") as stream:
        for collection in ("repository", "reports", "skills", "data-sources"):
            stream.writestr(collection + "/", b"")
        stream.writestr("manifest.json", json.dumps(manifest))
        for name, content in payloads.items():
            stream.writestr(name, content)
    return validate_archive(path, tmp_path / (label + "-validated"))


async def imported(
    connection, tmp_path, label, requirements=None, *, planning_hooks=True
):
    owner = uuid4()
    await connection.execute(
        "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
        owner,
        str(owner) + "@example.invalid",
    )
    value = archive(tmp_path, label, requirements, planning_hooks=planning_hooks)
    storage = VersionStorage(tmp_path / "store")
    context = await import_validated(connection, storage, user_id=owner, archive=value)
    return context, storage, value.manifest


def request(operation="execute", action=None):
    return {
        "contract_version": 1,
        "request_id": uuid4().hex,
        "operation": operation,
        "workflow_id": "inventory" if operation != "plan" else None,
        "hook_id": "plan" if operation == "plan" else None,
        "input": (
            {"operation": "inspect", "input": {}}
            if operation == "plan"
            else {"inputs": {"count": 41, "action": action}}
        ),
        "authority": {"network": False, "model_access": False},
    }


def invoke(context, storage, manifest, image, packet, **kwargs):
    output = storage.run_root(context, uuid4())
    output.mkdir(parents=True)
    return invoke_worker(
        image=image,
        package_root=storage.version_root(context),
        run_root=output,
        manifest=manifest,
        request=packet,
        **kwargs,
    )


def test_imported_neutral_workflow_prepares_and_executes_in_real_container(
    e2e_database_url, tmp_path, worker_image, monkeypatch
):
    monkeypatch.setenv("LUNAR_WORKER_TEST_SECRET", "host-only-marker")

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, manifest = await imported(connection, tmp_path, "neutral")
            image = await prepare_runtime(
                connection, context, storage, base_image=worker_image
            )
            assert (
                await connection.fetchval(
                    "SELECT runtime_state FROM package_versions WHERE id=$1",
                    context.version_id,
                )
                == "ready"
            )
            assert (
                await prepare_runtime(
                    connection, context, storage, base_image=worker_image
                )
                == image
            )
            result = await asyncio.to_thread(
                invoke, context, storage, manifest, image, request()
            )
            assert result["status"] == "succeeded", result
            assert result["result"]["structured_value"] == {"count": 42}
            policy = await asyncio.to_thread(
                invoke, context, storage, manifest, image, request("plan")
            )
            value = policy["result"]["structured_value"]["policy_value"]
            assert value == {
                "readonly": True,
                "host_secret": None,
                "host_socket": False,
                "collections": ["data-sources", "reports", "repository", "skills"],
            }
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["interrupt", "symlink"])
def test_interrupted_and_escaping_workers_cannot_return_success(
    e2e_database_url, tmp_path, worker_image, action
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, manifest = await imported(connection, tmp_path, action)
            cancelled = threading.Event()

            def observed(event):
                cancelled.set()

            with pytest.raises(WorkerUnavailable) as failure:
                await asyncio.to_thread(
                    invoke,
                    context,
                    storage,
                    manifest,
                    worker_image,
                    request(action=action),
                    cancelled=cancelled,
                    on_event=observed if action == "interrupt" else None,
                    limits=WorkerLimits(timeout_seconds=10),
                )
            if action == "interrupt":
                assert failure.value.events[0]["payload"]["stage"] == "waiting"
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_real_unavailable_dependency_leaves_runtime_failed(
    e2e_database_url, tmp_path, worker_image
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, _ = await imported(
                connection,
                tmp_path,
                "missing",
                "lunar-nonexistent-worker-test-package==0.0.0 --hash=sha256:"
                + "0" * 64,
            )
            with pytest.raises(
                WorkerUnavailable, match="dependency preparation failed"
            ):
                await prepare_runtime(
                    connection, context, storage, base_image=worker_image
                )
            row = await connection.fetchrow(
                "SELECT runtime_state,runtime_image,error FROM package_versions WHERE id=$1",
                context.version_id,
            )
            assert (
                row["runtime_state"] == "failed"
                and row["runtime_image"] is None
                and row["error"]
            )
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_concurrent_users_and_versions_have_only_selected_files(
    e2e_database_url, tmp_path, worker_image
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            first, storage, manifest = await imported(
                connection, tmp_path, "owner-one-version-one"
            )
            second_archive = archive(tmp_path, "owner-one-version-two")
            second = await import_validated(
                connection, storage, user_id=first.user_id, archive=second_archive
            )
            foreign, _, foreign_manifest = await imported(
                connection, tmp_path, "owner-two-version-one"
            )
            assert (
                first.version == 1
                and second.version == 2
                and foreign.user_id != first.user_id
            )
            contexts = [first, second, foreign]
            manifests = [manifest, second_archive.manifest, foreign_manifest]
            roots = [storage.version_root(context) for context in contexts]

            async def probe(index):
                packet = request("plan")
                packet["input"] = {
                    "policy_calls": [
                        {
                            "operation": "probe",
                            "input": {
                                "paths": [
                                    str(root / "repository/private.txt")
                                    for root in roots
                                ]
                                + [
                                    "/package/../other-version/private.txt",
                                    "/var/run/docker.sock",
                                ]
                            },
                        }
                    ]
                }
                result = await asyncio.to_thread(
                    invoke,
                    contexts[index],
                    storage,
                    manifests[index],
                    worker_image,
                    packet,
                )
                return result["result"]["structured_value"]["policy_value"]

            values = await asyncio.gather(*(probe(index) for index in range(3)))
            assert values == [
                [{"marker": label, "visible": [False] * 5}]
                for label in (
                    "owner-one-version-one",
                    "owner-one-version-two",
                    "owner-two-version-one",
                )
            ]
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_invalid_package_json_returns_typed_failure(
    e2e_database_url, tmp_path, worker_image
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, manifest = await imported(
                connection, tmp_path, "invalid-json"
            )
            packet = request("plan")
            packet["input"] = {"operation": "invalid-json", "input": {}}
            result = await asyncio.to_thread(
                invoke, context, storage, manifest, worker_image, packet
            )
            assert result["status"] == "failed" and result["result"] is None
            assert result["error"]["code"] == "InvalidJSONResult"
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_malformed_dependency_lock_persists_failed_preparation(
    e2e_database_url, tmp_path, worker_image
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, _ = await imported(
                connection,
                tmp_path,
                "malformed-lock",
                "--extra-index-url https://untrusted.invalid/simple",
            )
            with pytest.raises(ValueError):
                await prepare_runtime(
                    connection, context, storage, base_image=worker_image
                )
            row = await connection.fetchrow(
                "SELECT runtime_state,runtime_image,error FROM package_versions WHERE id=$1",
                context.version_id,
            )
            assert (
                row["runtime_state"] == "failed"
                and row["runtime_image"] is None
                and row["error"]
            )
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_recovery_skips_live_preparation_and_fails_abandoned_work(
    e2e_database_url, tmp_path
):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        live = await asyncpg.connect(e2e_database_url)
        try:
            first, storage, _ = await imported(connection, tmp_path, "live-preparation")
            second, _, _ = await imported(connection, tmp_path, "abandoned-preparation")
            await connection.execute(
                "UPDATE package_versions SET runtime_state='preparing'"
            )
            key = int.from_bytes(
                hashlib.sha256(("runtime:" + str(first.version_id)).encode()).digest()[
                    :8
                ],
                signed=True,
            )
            await live.execute("SELECT pg_advisory_lock($1)", key)
            assert await recover_runtime_preparations(connection) == [second.version_id]
            assert (
                await connection.fetchval(
                    "SELECT runtime_state FROM package_versions WHERE id=$1",
                    first.version_id,
                )
                == "preparing"
            )
            await live.execute("SELECT pg_advisory_unlock($1)", key)
            assert await recover_runtime_preparations(connection) == [first.version_id]
            assert await recover_runtime_preparations(connection) == []
        finally:
            await live.close()
            await connection.close()

    asyncio.run(scenario())


def test_timeout_retains_observed_provenance(e2e_database_url, tmp_path, worker_image):
    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, manifest = await imported(connection, tmp_path, "timeout")
            with pytest.raises(WorkerUnavailable, match="timed out") as failure:
                await asyncio.to_thread(
                    invoke,
                    context,
                    storage,
                    manifest,
                    worker_image,
                    request(action="interrupt"),
                    limits=WorkerLimits(timeout_seconds=2),
                )
            assert failure.value.events[0]["payload"]["stage"] == "waiting"
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "action,expected",
    [("normal", "completed"), ("symlink", "failed"), ("interrupt", "failed")],
)
def test_durable_worker_run_releases_only_valid_output(
    e2e_database_url, tmp_path, worker_image, action, expected
):
    from domain_packages.worker.runtime import load_runtime
    from domain_packages.worker.runs import enqueue, execute_queued

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            context, storage, _ = await imported(
                connection, tmp_path, "durable-" + action
            )
            await prepare_runtime(connection, context, storage, base_image=worker_image)
            runtime = await load_runtime(
                connection, context.user_id, context.version_id, storage
            )
            run_id, accepted = await enqueue(
                connection,
                runtime,
                "inventory",
                inputs={"count": 41, "action": action},
            )
            assert accepted.startswith("sha256:")
            result = await execute_queued(
                connection,
                runtime,
                run_id,
                limits=WorkerLimits(timeout_seconds=2 if action == "interrupt" else 30),
            )
            assert result["state"] == expected, result
            row = await connection.fetchrow(
                "SELECT state,terminal_result_digest,error_summary FROM prism_runs WHERE id=$1",
                run_id,
            )
            assert (
                row["state"] == expected
                and row["terminal_result_digest"] == result["terminal_digest"]
            )
            outputs = await connection.fetch(
                "SELECT * FROM prism_run_outputs WHERE run_id=$1", run_id
            )
            assert len(outputs) == (1 if expected == "completed" else 0)
            if outputs:
                assert json.loads(outputs[0]["structured_value"]) == {"count": 42}
                assert (
                    outputs[0]["user_id"] == context.user_id
                    and outputs[0]["version_id"] == context.version_id
                )
            if action == "interrupt":
                event = await connection.fetchval(
                    "SELECT detail FROM prism_run_events WHERE run_id=$1", run_id
                )
                assert (
                    json.loads(event)["worker_event"]["payload"]["stage"] == "waiting"
                )
            with pytest.raises(WorkerUnavailable, match="queued run"):
                await execute_queued(connection, runtime, run_id)
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_foreign_worker_cannot_start_an_owned_queued_run(
    e2e_database_url, tmp_path, worker_image
):
    from domain_packages.worker.runtime import PackageRuntime
    from domain_packages.worker.runs import enqueue, execute_queued

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            first, storage, manifest = await imported(
                connection, tmp_path, "queued-owner"
            )
            second, _, other_manifest = await imported(
                connection, tmp_path, "queued-foreign"
            )
            owned = PackageRuntime(first, storage, manifest, worker_image)
            foreign = PackageRuntime(second, storage, other_manifest, worker_image)
            run_id, _ = await enqueue(
                connection, owned, "inventory", inputs={"count": 41}
            )
            with pytest.raises(WorkerUnavailable, match="queued run"):
                await execute_queued(connection, foreign, run_id)
            assert (
                await connection.fetchval(
                    "SELECT state FROM prism_runs WHERE id=$1", run_id
                )
                == "queued"
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM prism_run_outputs WHERE run_id=$1", run_id
                )
                == 0
            )
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_execution_service_uses_bound_version_and_owned_model(
    e2e_database_url, tmp_path, worker_image, monkeypatch
):
    from domain_packages.context import bind_context
    from prism_runs import service
    from prism_runs.schemas import PrismRunRequest

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)

        async def connect():
            return await asyncpg.connect(e2e_database_url)

        monkeypatch.setattr(service, "connect", connect)
        try:
            context, storage, _ = await imported(connection, tmp_path, "service")
            monkeypatch.setattr(service, "configured_storage", lambda: storage)
            await prepare_runtime(connection, context, storage, base_image=worker_image)
            with bind_context(context):
                with pytest.raises(service.AIModelNotFoundError):
                    await service.accept_run(
                        user_id=context.user_id,
                        workflow_id="inventory",
                        request=PrismRunRequest(
                            ai_model_id=uuid4(), inputs={"count": 41}
                        ),
                    )
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM prism_runs WHERE imported=FALSE"
                    )
                    == 0
                )
                run_id, _ = await service.accept_run(
                    user_id=context.user_id,
                    workflow_id="inventory",
                    request=PrismRunRequest(inputs={"count": 41}),
                )
                await asyncio.gather(*list(service.ACTIVE_TASKS))
            assert (
                await connection.fetchval(
                    "SELECT state FROM prism_runs WHERE id=$1", run_id
                )
                == "completed"
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM prism_run_outputs WHERE run_id=$1", run_id
                )
                == 1
            )
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("authorized", [False, True])
def test_real_worker_requires_explicit_public_fetch_authority(
    e2e_database_url, tmp_path, worker_image, authorized
):
    import base64

    async def scenario():
        connection = await asyncpg.connect(e2e_database_url)
        calls = []

        def fetch(arguments):
            calls.append(arguments["operation"])
            return {
                "open": {"token": "run-scoped", "headers": {}},
                "read": {"data": base64.b64encode(b"public fixture").decode()},
                "close": {"closed": True},
            }[arguments["operation"]]

        try:
            context, storage, manifest = await imported(
                connection, tmp_path, "fetch-" + str(authorized)
            )
            packet = request(action="fetch")
            packet["authority"]["network"] = authorized
            result = await asyncio.to_thread(
                invoke,
                context,
                storage,
                manifest,
                worker_image,
                packet,
                fetch_handler=fetch,
            )
            assert result["status"] == ("succeeded" if authorized else "failed")
            assert calls == (["open", "read", "close"] if authorized else [])
            if authorized:
                assert result["artifacts"][0]["path"] == "download.txt"
                assert (
                    result["artifacts"][0]["sha256"]
                    == hashlib.sha256(b"public fixture").hexdigest()
                )
        finally:
            await connection.close()

    asyncio.run(scenario())
