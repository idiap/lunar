# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Container entrypoint: declared package hooks and the host-owned Prism runtime."""

from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict, is_dataclass
from datetime import datetime
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, cast, TYPE_CHECKING
import uuid

# This is a fixed image-owned path, never supplied by the package.
if TYPE_CHECKING:
    from .prism import execute_prism, observed_completion
else:
    sys.path.insert(0, "/opt/lunar-worker")
    from prism_engine import execute_prism, observed_completion

# Keep the protocol on a private descriptor. Redirecting only Python's stdout
# does not cover subprocesses spawned by native hooks and report builders.
WIRE = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)


@contextmanager
def subprocess_logs_to_stderr():
    """Prevent inherited child stdout from becoming an invalid protocol frame."""
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        os.dup2(saved, 1)
        os.close(saved)


def encoded(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("worker transport requires JSON values")


def send(value):
    WIRE.write(json.dumps(value, default=encoded, allow_nan=False) + "\n")
    WIRE.flush()


def rpc(operation, arguments):
    identity = uuid.uuid4().hex
    send(
        {
            "kind": "request",
            "id": identity,
            "operation": operation,
            "arguments": arguments,
        }
    )
    response = json.loads(sys.stdin.readline())
    if response.get("id") != identity or response.get("kind") != "response":
        raise RuntimeError("invalid host channel response")
    if response.get("error"):
        raise RuntimeError(response["error"])
    return response["value"]


def load_hook(manifest, identity, operation):
    registration = next(
        (
            row
            for row in manifest["runtime"]["entrypoints"]
            if row["id"] == identity and row["operation"] == operation
        ),
        None,
    )
    if registration is None:
        raise ValueError("hook is not registered for this operation")
    path = (Path("/package") / registration["file"]).resolve(strict=True)
    path.relative_to("/package/repository")
    expected = next(
        row for row in manifest["files"] if row["path"] == registration["file"]
    )
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
        raise ValueError("package hook digest changed")
    spec = importlib.util.spec_from_file_location(
        "lunar_package_" + uuid.uuid4().hex, path
    )
    if spec is None or spec.loader is None:
        raise ValueError("registered hook cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    hook = getattr(module, registration["callable"])
    if not callable(hook):
        raise ValueError("registered hook is not callable")
    return hook


def main():
    envelope: dict[str, Any] = json.loads(sys.stdin.readline())
    request: dict[str, Any] = envelope["request"]
    manifest: dict[str, Any] = envelope["manifest"]
    response: dict[str, Any] = {
        "contract_version": 1,
        "request_id": request["request_id"],
        "status": "failed",
        "prepared_input": None,
        "result": None,
        "events": [],
        "artifacts": [],
        "error": None,
    }

    def event(kind, payload):
        record = {"sequence": len(response["events"]), "kind": kind, "payload": payload}
        send({"kind": "event", "event": record})
        response["events"].append(record)

    def reasoning(**payload):
        event("reasoning", payload)

    def completion(**arguments):
        if not request["authority"]["model_access"]:
            raise PermissionError("model access is not authorized")
        return rpc("model", arguments)

    def public_fetch(operation, **arguments):
        if not request["authority"]["network"]:
            raise PermissionError("public network access is not authorized")
        return rpc("fetch", {"operation": operation, **arguments})

    snapshot = envelope.get("model", {})
    model = SimpleNamespace(
        provider=snapshot.get("provider", "host"),
        model_id=snapshot.get("model_id", "selected"),
        api_key="",
        api_base=None,
        api_version=None,
        config={},
        safe_snapshot=snapshot,
    )
    services = SimpleNamespace(
        model=model,
        completion=observed_completion(
            completion, f"{model.provider}/{model.model_id}", reasoning
        ),
        event=event,
        public_fetch=public_fetch,
    )
    try:
        with redirect_stdout(sys.stderr), subprocess_logs_to_stderr():
            operation = request["operation"]
            if operation == "plan":
                if request["hook_id"] not in manifest["runtime"]["planning_hooks"]:
                    raise ValueError("planning hook is not registered")
                if any(request["authority"].values()):
                    raise PermissionError(
                        "planning hooks cannot acquire network or model authority"
                    )
                hook = load_hook(manifest, request["hook_id"], "plan")
                if "policy_calls" in request["input"]:
                    calls = request["input"]["policy_calls"]
                    if not isinstance(calls, list) or not 1 <= len(calls) <= 4096:
                        raise ValueError("policy batch must contain 1 to 4096 calls")
                    value = [hook(call) for call in calls]
                else:
                    value = hook(request["input"])
                response["result"] = {
                    "markdown": "",
                    "structured_value": {"policy_value": value},
                    "analysis_results": {},
                    "compact_prism_input": {},
                    "narrative_slots": [],
                    "report_verification": None,
                }
            else:
                workflow = next(
                    row
                    for row in manifest["runtime"]["workflows"]
                    if row["id"] == request["workflow_id"]
                )
                values = request["input"]
                prepare = load_hook(manifest, workflow["prepare_hook"], "prepare")
                prepare_arguments = {
                    "workflow_id": workflow["id"],
                    "inputs": values["inputs"],
                    "run_id": request["request_id"],
                    "run_root": Path("/output"),
                    "network_authority": request["authority"]["network"],
                    "on_reasoning": reasoning,
                    **(
                        {"public_fetch": public_fetch}
                        if request["authority"]["network"]
                        else {}
                    ),
                }
                # Stored pre-single-contract packages may still require this
                # argument. It is a fixed compatibility value, never a choice.
                if "mode" in inspect.signature(prepare).parameters:
                    prepare_arguments["mode"] = "run"
                prepared = cast(dict[str, Any], prepare(**prepare_arguments))
                response["prepared_input"] = prepared["prepared_input"]
                for record in prepared.get("events", []):
                    event(record["kind"], record["payload"])
                if operation == "execute":
                    if workflow.get("execute_hook") is not None:
                        execution: Any = load_hook(
                            manifest, workflow["execute_hook"], "execute"
                        )(state=prepared.get("state"), services=services)
                    else:
                        execution = execute_prism(
                            source=Path("/package") / workflow["entry_file"],
                            entry_argument=workflow["entry_argument"],
                            prepared_input=prepared["prepared_input"],
                            selected_model=model,
                            artifact_root=Path("/output"),
                            completion=completion,
                            on_reasoning=reasoning,
                        )
                        if execution.status != "accepted":
                            raise RuntimeError("Prism execution did not complete")
                    if workflow["verify_hook"] is None:
                        value = execution.typed_result
                        while hasattr(value, "value"):
                            value = value.value
                        if hasattr(value, "fields"):
                            value = value.fields
                        encoded_value = json.loads(json.dumps(value, default=encoded))
                        structured = (
                            encoded_value
                            if isinstance(encoded_value, dict)
                            else {"value": encoded_value}
                        )
                        verified: dict[str, Any] = {
                            "result": {
                                "markdown": json.dumps(structured, indent=2),
                                "structured_value": structured,
                                "analysis_results": {},
                                "compact_prism_input": prepared["prepared_input"][
                                    "value"
                                ],
                                "narrative_slots": [],
                                "report_verification": None,
                            }
                        }
                    else:
                        verified = cast(
                            dict[str, Any],
                            load_hook(manifest, workflow["verify_hook"], "verify")(
                                state=prepared.get("state"),
                                execution=execution,
                                services=services,
                            ),
                        )
                    if (
                        workflow.get("metadata", {}).get("output_format")
                        == "prism-typed-report/v1"
                    ):
                        from prism_stdlib.report_codec import export_report

                        typed_report = export_report(execution.run_output)
                        verified["result"]["structured_value"] = {
                            "typed_report": typed_report
                        }
                        verified["result"]["markdown"] = (
                            "# " + typed_report["report"]["title"]
                        )
                        Path("/output/typed-report.json").write_text(
                            json.dumps(typed_report)
                        )
                    response["result"] = verified["result"]
                    for record in verified.get("events", []):
                        event(record["kind"], record["payload"])
                elif operation != "prepare":
                    raise ValueError(
                        "independent verification requires a package-defined replay contract"
                    )
            response["status"] = "succeeded"
    except Exception as exc:
        response["error"] = {
            "stage": request["operation"],
            "code": type(exc).__name__,
            "message": str(exc),
        }
        response["result"] = None
    for path in sorted(Path("/output").rglob("*")):
        if path.is_file() and not path.is_symlink():
            import mimetypes

            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            response["artifacts"].append(
                {
                    "path": path.relative_to("/output").as_posix(),
                    "sha256": digest.hexdigest(),
                    "size": path.stat().st_size,
                    "media_type": mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                }
            )
    try:
        send({"kind": "result", "payload": response})
    except (TypeError, ValueError):
        response.update(
            status="failed",
            prepared_input=None,
            result=None,
            error={
                "stage": request["operation"],
                "code": "InvalidJSONResult",
                "message": "Package result contains values unsupported by the JSON contract",
            },
        )
        send({"kind": "result", "payload": response})
    return 0 if response["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
