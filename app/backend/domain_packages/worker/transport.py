# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bounded host transport for one isolated worker invocation."""

import json
import os
import select
import queue
import subprocess
import threading
import time
from uuid import uuid4

from ..format.contract import validate_document
from .sandbox import WorkerLimits, WorkerUnavailable, worker_command
from .model_channel import ModelRequestError


def invoke_worker(
    *,
    image,
    package_root,
    run_root,
    manifest,
    request,
    model_handler=None,
    model_snapshot=None,
    fetch_handler=None,
    on_event=None,
    cancelled=None,
    limits=WorkerLimits(),
):
    """Exchange typed frames without granting package code a host execution API."""
    from ..source_workflows import runtime_manifest

    manifest = runtime_manifest(manifest, package_root)
    validate_document(request, "worker-request")
    name = "lunar-worker-" + uuid4().hex
    command = worker_command(
        image=image,
        name=name,
        package_root=package_root,
        run_root=run_root,
        limits=limits,
    )
    frames = queue.Queue(maxsize=2)
    errors = []
    events = []
    received = 0
    stopped = threading.Event()
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
    if stdin is None or stdout is None or stderr is None:
        raise WorkerUnavailable("worker transport pipes are unavailable")

    def enqueue(value):
        while not stopped.is_set():
            try:
                frames.put(value, timeout=0.2)
                return
            except queue.Full:
                pass

    def reader():
        try:
            while True:
                line = stdout.readline(limits.transport_bytes + 1)
                enqueue(line)
                if not line or len(line) > limits.transport_bytes:
                    return
        except Exception as exc:
            enqueue(exc)

    def stderr_reader():
        remaining = 8192
        for data in iter(lambda: stderr.read(4096), b""):
            if remaining:
                errors.append(data[:remaining])
                remaining -= min(remaining, len(data))

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=stderr_reader, daemon=True).start()
    deadline = time.monotonic() + limits.timeout_seconds
    os.set_blocking(stdin.fileno(), False)

    def check_active():
        if cancelled is not None and cancelled.is_set():
            raise WorkerUnavailable("worker interrupted")
        if time.monotonic() >= deadline:
            raise WorkerUnavailable("worker timed out")

    def send(value):
        data = json.dumps(value, allow_nan=False).encode() + b"\n"
        if len(data) > limits.request_bytes:
            raise WorkerUnavailable("worker transport size limit exceeded")
        pending = memoryview(data)
        while pending:
            check_active()
            if select.select([], [stdin], [], 0.2)[1]:
                try:
                    count = os.write(stdin.fileno(), pending[:65536])
                    pending = pending[count:]
                except BlockingIOError:
                    continue

    try:
        send({"request": request, "manifest": manifest, "model": model_snapshot or {}})
        while True:
            if cancelled is not None and cancelled.is_set():
                raise WorkerUnavailable("worker interrupted")
            if time.monotonic() >= deadline:
                raise WorkerUnavailable("worker timed out")
            try:
                line = frames.get(
                    timeout=min(0.2, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            if isinstance(line, Exception) or not line:
                raise WorkerUnavailable("worker terminated without a result")
            received += len(line)
            if received > limits.transport_bytes:
                raise WorkerUnavailable("worker transport size limit exceeded")
            try:
                from ..format.contract import _json

                frame = _json(line)
                if not isinstance(frame, dict):
                    raise ValueError("frame must be an object")
            except (ValueError, UnicodeError) as exc:
                raise WorkerUnavailable("invalid worker transport frame") from exc
            if frame.get("kind") == "event":
                event = frame["event"]
                if event.get("sequence") != len(events):
                    raise WorkerUnavailable("invalid worker event sequence")
                validate_document(
                    {
                        "contract_version": 1,
                        "request_id": request["request_id"],
                        "status": "failed",
                        "prepared_input": None,
                        "result": None,
                        "events": [event],
                        "artifacts": [],
                        "error": None,
                    },
                    "worker-result",
                )
                events.append(event)
                if on_event:
                    on_event(event)
            elif frame.get("kind") == "request":
                operation = frame.get("operation")
                handler = None
                if (
                    operation == "model"
                    and request["operation"] == "execute"
                    and request["authority"]["model_access"]
                ):
                    handler = model_handler
                elif (
                    operation == "fetch"
                    and request["operation"] in {"prepare", "execute"}
                    and request["authority"]["network"]
                ):
                    handler = fetch_handler
                allowed = handler is not None
                if not allowed:
                    send(
                        {
                            "kind": "response",
                            "id": frame.get("id"),
                            "value": None,
                            "error": "host operation is not authorized",
                        }
                    )
                    continue
                try:
                    value = _channel_result(handler, frame["arguments"], check_active)
                    send(
                        {
                            "kind": "response",
                            "id": frame["id"],
                            "value": value,
                            "error": None,
                        }
                    )
                except WorkerUnavailable:
                    raise
                except ModelRequestError as exc:
                    send(
                        {
                            "kind": "response",
                            "id": frame["id"],
                            "value": None,
                            "error": str(exc),
                        }
                    )
                except Exception:
                    send(
                        {
                            "kind": "response",
                            "id": frame["id"],
                            "value": None,
                            "error": "authorized " + str(operation) + " request failed",
                        }
                    )
            elif frame.get("kind") == "result":
                result = frame["payload"]
                validate_document(result, "worker-result")
                if (
                    result["request_id"] != request["request_id"]
                    or result["events"] != events
                ):
                    raise WorkerUnavailable(
                        "worker result identity or event history mismatch"
                    )
                stdin.close()
                try:
                    code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as exc:
                    raise WorkerUnavailable(
                        "worker did not terminate after its result"
                    ) from exc
                if result["status"] == "succeeded" and code != 0:
                    raise WorkerUnavailable(
                        "worker exited unsuccessfully after claiming success"
                    )
                from .results import validate_worker_result

                return validate_worker_result(result, request, run_root)
            else:
                raise WorkerUnavailable("unknown worker transport frame")
    except Exception as exc:
        if isinstance(exc, WorkerUnavailable):
            exc.events = events
            exc.diagnostics = b"".join(errors).decode(errors="replace")
            raise
        failure = WorkerUnavailable("worker response violated its transport contract")
        failure.events = events
        raise failure from exc
    finally:
        stopped.set()
        # Terminating the Docker client alone does not reliably terminate its container.
        try:
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


def _channel_result(handler, arguments, check_active):
    """Keep interruption responsive while the bounded provider request finishes."""
    result = queue.Queue(maxsize=1)

    def call():
        try:
            result.put((True, handler(arguments)))
        except Exception as exc:
            result.put((False, exc))

    threading.Thread(target=call, daemon=True).start()
    while True:
        check_active()
        try:
            succeeded, value = result.get(timeout=0.2)
        except queue.Empty:
            continue
        if not succeeded:
            raise value
        return value
