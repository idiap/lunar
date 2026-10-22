#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed validation for deterministic, UI-runnable Lunar PRISM archives."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

FORBIDDEN_RUNNABLE_TEXT = (
    "fixture:",
    "fake handler",
    "not_executed_by_structural_fixture",
    "native implementation not executed",
    "not produced by structural fixture",
    "canonical placeholder",
)
TERMINAL_FAILURES = {"blocked", "failed", "rejected", "cancelled", "interrupted"}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def lunar_modules(lunar_root: Path):
    backend = lunar_root.resolve(strict=True) / "app" / "backend"
    if not (backend / "domain_packages" / "archive.py").is_file():
        raise ValueError(f"Lunar backend not found below {lunar_root}")
    sys.path.insert(0, str(backend))
    try:
        archive = importlib.import_module("domain_packages.archive")
        source_workflows = importlib.import_module(
            "domain_packages.format.source_workflows"
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Lunar validation dependencies are unavailable; run this script with "
            "the Lunar backend environment"
        ) from exc
    finally:
        sys.path.pop(0)
    return (
        archive.validate_archive,
        source_workflows.derive,
        source_workflows.SourceProject,
    )


def read_documents(
    manifest: dict[str, Any], payloads: dict[str, bytes]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for collection, rows in manifest.get("collections", {}).items():
        documents: list[dict[str, Any]] = []
        for row in rows:
            try:
                documents.append(json.loads(payloads[row["document"]]))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid {collection} resource document: {exc}"
                ) from exc
        result[collection] = documents
    return result


def annotation(content: bytes, label: str) -> dict[str, Any]:
    text = content.decode("utf-8")
    matches = re.findall(r"(?m)^\s*#\s*lunar-runtime:\s*(\{.*\})\s*$", text)
    if len(matches) != 1:
        raise ValueError(f"{label}: expected exactly one # lunar-runtime annotation")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}: invalid lunar-runtime JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label}: lunar-runtime annotation must be an object")
    return value


def walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


def validate_required_inputs(registration: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    schema = registration.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return [f"{label}: input_schema must be an object schema"]
    if schema.get("additionalProperties") is not False:
        errors.append(f"{label}: input_schema must set additionalProperties=false")
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return errors + [
            f"{label}: input_schema properties and required must be explicit"
        ]
    for name in required:
        spec = properties.get(name)
        if not isinstance(spec, dict):
            errors.append(f"{label}: required input {name!r} has no property schema")
            continue
        candidates = [spec.get("default"), *(spec.get("examples") or [])]
        meaningful = [item for item in candidates if item not in (None, "", [], {})]
        if not meaningful:
            errors.append(f"{label}: required input {name!r} has no UI default/example")
            continue
        joined = " ".join(walk_strings(meaningful)).lower()
        if any(token in joined for token in FORBIDDEN_RUNNABLE_TEXT):
            errors.append(
                f"{label}: required input {name!r} uses a fixture/placeholder value"
            )
    return errors


def completion_errors(registration: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    metadata = registration.get("metadata")
    if not isinstance(metadata, dict):
        return [f"{label}: runtime metadata is required"]
    if metadata.get("reasoning_required") is not True:
        errors.append(f"{label}: metadata.reasoning_required must be true")
    reasoning = metadata.get("reasoning_contract")
    if (
        not isinstance(reasoning, dict)
        or not isinstance(reasoning.get("workflow"), str)
        or not reasoning["workflow"]
        or not isinstance(reasoning.get("steps"), list)
        or not reasoning["steps"]
        or any(not isinstance(step, str) or not step for step in reasoning["steps"])
        or len(reasoning["steps"]) != len(set(reasoning["steps"]))
    ):
        errors.append(f"{label}: a non-empty unique reasoning_contract is required")
    completion = metadata.get("completion_contract")
    if not isinstance(completion, dict):
        return errors + [f"{label}: metadata.completion_contract is required"]
    if completion.get("terminal_state") != "completed":
        errors.append(f"{label}: completion terminal_state must be completed")
    if (
        not isinstance(completion.get("reasoning_events_min"), int)
        or completion["reasoning_events_min"] < 1
    ):
        errors.append(f"{label}: reasoning_events_min must be at least 1")
    if completion.get("reasoning_complete") is not True:
        errors.append(f"{label}: reasoning_complete must be true")
    statuses = completion.get("allowed_final_statuses")
    if (
        not isinstance(statuses, list)
        or not statuses
        or any(item in TERMINAL_FAILURES for item in statuses)
    ):
        errors.append(
            f"{label}: allowed_final_statuses must be non-empty and non-blocking"
        )
    if completion.get("forbid_blockers") is not True:
        errors.append(f"{label}: completion must forbid final blockers")
    if metadata.get("native_backend_execution") is True:
        native = completion.get("native_backend")
        if not isinstance(native, dict):
            errors.append(
                f"{label}: native workflow requires completion_contract.native_backend"
            )
        else:
            expected = {
                "backend_executed": True,
                "backend_verified": True,
                "exit_code": 0,
            }
            for key, value in expected.items():
                if native.get(key) != value:
                    errors.append(f"{label}: native_backend.{key} must equal {value!r}")
            if not isinstance(native.get("backend"), str) or not native["backend"]:
                errors.append(f"{label}: native_backend.backend is required")
            if not isinstance(native.get("version"), str) or not native["version"]:
                errors.append(f"{label}: native_backend.version is required")
    return errors


def call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def runtime_execute_errors(
    payloads: dict[str, bytes], entrypoint: dict[str, Any], label: str
) -> list[str]:
    errors: list[str] = []
    path = entrypoint.get("file")
    callable_name = entrypoint.get("callable")
    if path not in payloads:
        return [f"{label}: execute hook file is missing"]
    try:
        tree = ast.parse(payloads[path].decode("utf-8"), filename=path)
    except (UnicodeDecodeError, SyntaxError) as exc:
        return [f"{label}: execute hook is not valid UTF-8 Python: {exc}"]
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == callable_name
        ),
        None,
    )
    if function is None:
        return [f"{label}: execute callable {callable_name!r} is missing"]
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    prism_calls = [node for node in calls if call_name(node) == "execute_prism"]
    if not prism_calls:
        errors.append(f"{label}: execute hook does not call execute_prism")
        return errors
    if not any(
        any(keyword.arg == "on_reasoning" for keyword in node.keywords)
        for node in prism_calls
    ):
        errors.append(f"{label}: execute_prism call does not install on_reasoning")
    first_prism = min(node.lineno for node in prism_calls)
    early_native = [
        node
        for node in calls
        if call_name(node) == "execute_artifact" and node.lineno < first_prism
    ]
    if early_native:
        errors.append(
            f"{label}: native execute_artifact shortcut occurs before PRISM reasoning"
        )
    return errors


def validate_archive_shape(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"invalid ZIP archive: {exc}"]
    names = [info.filename for info in infos]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate ZIP members: {duplicates}")
    for info in infos:
        pure = PurePosixPath(info.filename)
        if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:
            errors.append(f"unsafe ZIP member path: {info.filename}")
        if info.date_time != (1980, 1, 1, 0, 0, 0):
            errors.append(f"non-deterministic ZIP timestamp: {info.filename}")
    return errors


def validate(path: Path, lunar_root: Path) -> dict[str, Any]:
    errors = validate_archive_shape(path)
    validate_archive, derive, SourceProject = lunar_modules(lunar_root)
    with tempfile.TemporaryDirectory(prefix="prism-package-validation-") as temporary:
        extracted = Path(temporary) / "validated"
        try:
            validated = validate_archive(path, extracted)
        except Exception as exc:  # noqa: BLE001 - Lunar owns the exception boundary.
            return {"archive": str(path), "valid": False, "errors": errors + [str(exc)]}
        manifest = validated.manifest
        payloads = {
            row["path"]: (extracted / row["path"]).read_bytes()
            for row in manifest["files"]
        }
        documents = read_documents(manifest, payloads)
        try:
            bundle, registrations = derive(
                manifest, payloads, documents.get("repository", [])
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - PRISM parser exceptions are host-owned.
            errors.append(f"PRISM source derivation failed: {exc}")
            return {"archive": str(path), "valid": False, "errors": errors}
        prism_sources = {
            name: content.decode("utf-8")
            for name, content in payloads.items()
            if name.endswith(".prism")
        }
        source_project = SourceProject(prism_sources)

        lock_path = "repository/conversion-lock.json"
        if lock_path not in payloads:
            errors.append("deterministic conversion lock is missing")
        else:
            try:
                lock = json.loads(payloads[lock_path])
                lock_rows = lock["files"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid deterministic conversion lock: {exc}")
                lock_rows = []
            seen_targets: set[str] = set()
            for row in lock_rows:
                target = row.get("archive_path")
                if target in seen_targets:
                    errors.append(f"conversion lock repeats archive path: {target}")
                    continue
                seen_targets.add(target)
                if target not in payloads:
                    errors.append(
                        f"conversion lock references missing payload: {target}"
                    )
                elif sha256(payloads[target]) != row.get("archive_sha256"):
                    errors.append(f"conversion lock digest mismatch: {target}")
            if lock_rows != sorted(lock_rows, key=lambda item: item["archive_path"]):
                errors.append("conversion lock rows are not deterministically sorted")

        project_documents = {
            row["id"]: row
            for row in documents.get("repository", [])
            if row.get("kind") == "project"
            and isinstance(row.get("metadata", {}).get("entrypoint"), str)
        }
        project_views = {
            workflow["id"]: workflow
            for project in bundle.get("projects", [])
            for workflow in project.get("workflows", [])
        }
        mapped: dict[str, list[dict[str, Any]]] = {}
        for registration in registrations:
            viewer_id = registration.get("metadata", {}).get(
                "viewer_workflow_id", registration["id"]
            )
            mapped.setdefault(viewer_id, []).append(registration)
            errors.extend(validate_required_inputs(registration, registration["id"]))
            errors.extend(completion_errors(registration, registration["id"]))

        runtime_entries = {
            row["id"]: row for row in manifest.get("runtime", {}).get("entrypoints", [])
        }
        checked_hooks: set[str] = set()
        for view_id in sorted(project_views):
            bound = mapped.get(view_id, [])
            if not bound:
                errors.append(
                    f"{view_id}: visible workflow has no runtime registration"
                )
                continue
            for registration in bound:
                for field, operation in (
                    ("prepare_hook", "prepare"),
                    ("execute_hook", "execute"),
                    ("verify_hook", "verify"),
                ):
                    hook = registration.get(field)
                    if not hook:
                        errors.append(
                            f"{registration['id']}: reasoning workflow has no {field}"
                        )
                    elif hook not in runtime_entries:
                        errors.append(
                            f"{registration['id']}: {field} {hook!r} is not registered"
                        )
                    elif runtime_entries[hook].get("operation") != operation:
                        errors.append(
                            f"{registration['id']}: {field} {hook!r} does not provide {operation}"
                        )
                execute_hook = registration.get("execute_hook")
                if (
                    execute_hook in runtime_entries
                    and execute_hook not in checked_hooks
                ):
                    errors.extend(
                        runtime_execute_errors(
                            payloads, runtime_entries[execute_hook], registration["id"]
                        )
                    )
                    checked_hooks.add(execute_hook)

        for identifier, document in sorted(project_documents.items()):
            metadata = document.get("metadata", {})
            entrypoint = metadata.get("entrypoint")
            reasoning = metadata.get("reasoning_entrypoint")
            for label, target in (
                ("material entrypoint", entrypoint),
                ("reasoning entrypoint", reasoning),
            ):
                if not isinstance(target, str) or target not in payloads:
                    errors.append(f"{identifier}: {label} is missing from the archive")
            if isinstance(entrypoint, str) and entrypoint in payloads:
                try:
                    declared = annotation(payloads[entrypoint], identifier)
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    if declared.get("id") not in {row["id"] for row in registrations}:
                        errors.append(
                            f"{identifier}: annotated runtime id was not derived"
                        )
            runnable_paths = (
                source_project.source_closure(entrypoint)
                if isinstance(entrypoint, str) and entrypoint in prism_sources
                else []
            )
            for filename in runnable_paths:
                content = payloads[filename]
                lowered = content.decode("utf-8", errors="replace").lower()
                for token in FORBIDDEN_RUNNABLE_TEXT:
                    if token in lowered:
                        errors.append(
                            f"{identifier}: forbidden runnable placeholder {token!r} in {filename}"
                        )

    unique = list(dict.fromkeys(errors))
    return {
        "archive": str(path.resolve()),
        "archive_sha256": sha256(path.read_bytes()),
        "valid": not unique,
        "errors": unique,
        "project_count": len(project_documents),
        "runtime_workflow_count": len(registrations),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--lunar-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = validate(args.archive.resolve(strict=True), args.lunar_root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['archive']}: {'valid' if report['valid'] else 'invalid'}")
        for error in report["errors"]:
            print(f"  - {error}")
        if report["valid"]:
            print(
                f"Validated {report['project_count']} project(s) and "
                f"{report['runtime_workflow_count']} runnable workflow(s)."
            )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
