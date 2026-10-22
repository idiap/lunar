#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Validate a completed Lunar UI workflow run and its rendered-report contract."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TERMINAL = {"completed", "failed", "cancelled"}
PASSING = {"passed", "completed", "accepted", "succeeded", "success"}
FAILING = {"blocked", "failed", "rejected", "cancelled", "interrupted", "error"}


def cookie_header(path: Path | None, literal: str | None) -> str | None:
    if literal:
        return literal.strip()
    if path is None:
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("cookie file is empty")
    if "\t" not in text:
        return text
    cookies = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:
            cookies.append(f"{fields[5]}={fields[6]}")
    if not cookies:
        raise ValueError("cookie file contains no usable cookies")
    return "; ".join(cookies)


class Client:
    def __init__(
        self,
        base_url: str,
        package_version_id: str,
        *,
        cookie: str | None,
        bearer_token: str | None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "X-Lunar-Package-Version": package_version_id,
        }
        if cookie:
            self.headers["Cookie"] = cookie
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"

    def request(
        self, path: str, *, accept: str = "application/json", timeout: float = 30
    ):
        headers = {**self.headers, "Accept": accept}
        request = urllib.request.Request(self.base_url + path, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Lunar returned HTTP {exc.code} for {path}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"cannot reach Lunar at {self.base_url}: {exc}") from exc

    def json(self, path: str) -> Any:
        with self.request(path) as response:
            return json.loads(response.read().decode("utf-8"))


def dictionaries(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from dictionaries(item)
    elif isinstance(value, list):
        for item in value:
            yield from dictionaries(item)


def output_values(run: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for output in run.get("outputs", []):
        if not isinstance(output, dict):
            continue
        if "structured_value" in output:
            values.append(output["structured_value"])
        if "markdown" in output:
            values.append(output["markdown"])
    return values


def reasoning_snapshot(
    client: Client, workflow_id: str, run_id: str
) -> dict[str, Any] | None:
    query = urllib.parse.urlencode([("workflow_id", workflow_id), ("run_ids", run_id)])
    latest = None
    with client.request(
        f"/api/prism/runs/reasoning?{query}",
        accept="text/event-stream",
        timeout=45,
    ) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="strict").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line.removeprefix("data:").strip())
            if event.get("type") == "snapshot" and event.get("run_id") == run_id:
                latest = event
            if event.get("type") == "done":
                break
    return latest


def reasoning_errors(
    snapshot: dict[str, Any] | None, contract: dict[str, Any]
) -> list[str]:
    if snapshot is None:
        return ["no reasoning snapshot was returned"]
    entries = snapshot.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["reasoning log is required but contains no entries"]
    minimum = contract.get("reasoning_events_min", 1)
    if len(entries) < minimum:
        return [
            f"reasoning log has {len(entries)} entries; contract requires {minimum}"
        ]
    transitions: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("event_kind") != "stage":
            continue
        source = entry.get("source")
        if not isinstance(source, dict):
            continue
        step = source.get("reasoning_step")
        if not isinstance(step, dict):
            continue
        name = step.get("name")
        status = source.get("status")
        key = entry.get("source_event_key")
        if not all(isinstance(item, str) and item for item in (name, status, key)):
            continue
        occurrence, separator, key_status = key.rpartition(":")
        if not separator or key_status != status:
            return [f"reasoning event key/status mismatch: {key!r} / {status!r}"]
        row = transitions.setdefault(occurrence, {"name": name, "statuses": []})
        if row["name"] != name:
            return [f"reasoning occurrence {occurrence!r} changed step identity"]
        row["statuses"].append(status)
    if not transitions:
        return ["reasoning log has entries but no reasoning-step transitions"]
    errors = []
    for occurrence, row in sorted(transitions.items()):
        if row["statuses"] != ["running", "completed"]:
            errors.append(
                f"reasoning occurrence {occurrence!r} has incomplete transitions {row['statuses']!r}"
            )
    return errors


def report_errors(
    run: dict[str, Any], completion: dict[str, Any], metadata: dict[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    values = output_values(run)
    objects = [item for value in values for item in dictionaries(value)]
    allowed = set(completion.get("allowed_final_statuses", ["passed", "completed"]))
    final = next(
        (
            item
            for item in objects
            if item.get("reasoning_complete") is True
            and isinstance(item.get("status"), str)
        ),
        None,
    )
    if final is None:
        errors.append(
            "no authoritative final disposition with reasoning_complete=true was found"
        )
        final = {}
    else:
        if final.get("status") not in allowed:
            errors.append(
                f"final disposition {final.get('status')!r} is outside allowed statuses {sorted(allowed)!r}"
            )
        if final.get("status") in FAILING:
            errors.append(f"final disposition is blocking: {final.get('status')}")
        if completion.get("forbid_blockers", True) and final.get("blockers") not in (
            None,
            [],
        ):
            errors.append(
                f"final disposition contains blockers: {final.get('blockers')!r}"
            )

    native = completion.get("native_backend")
    evidence = None
    if isinstance(native, dict):
        candidates = [
            item
            for item in objects
            if item.get("backend_executed") is True
            and item.get("backend_verified") is True
            and item.get("status") in PASSING
        ]
        evidence = max(
            candidates,
            key=lambda item: sum(
                (
                    "backend" in item,
                    "exit_code" in item,
                    isinstance(item.get("runtime"), dict),
                    "command" in item,
                    "source_sha256" in item,
                )
            ),
            default=None,
        )
        if evidence is None:
            errors.append("native backend evidence is missing or not verified")
            evidence = {}
        for key in ("backend", "version", "exit_code"):
            expected = native.get(key)
            if expected is not None:
                actual = evidence.get(key)
                if (
                    key == "version"
                    and actual is None
                    and isinstance(evidence.get("runtime"), dict)
                ):
                    actual = evidence["runtime"].get("version")
                if actual != expected:
                    errors.append(
                        f"native evidence {key}={actual!r}; expected {expected!r}"
                    )
        for key in ("backend_executed", "backend_verified"):
            if native.get(key) is True and evidence.get(key) is not True:
                errors.append(f"native evidence {key} is not true")

    markdown = "\n".join(value for value in values if isinstance(value, str))
    if markdown:
        lowered = markdown.lower()
        if "final disposition" not in lowered:
            errors.append(
                "rendered report does not contain a Final disposition section"
            )
        if (
            metadata.get("native_backend_execution") is True
            and "backend result: passed" not in lowered
        ):
            errors.append(
                "rendered native report does not state Backend result: passed"
            )
    return errors, {"final_disposition": final, "backend_evidence": evidence}


def provenance_errors(
    run: dict[str, Any], metadata: dict[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    """Compare runtime provenance contracts with the receipts rendered by Lunar.

    Package catalogs describe available resources. This gate verifies actual per-run
    evidence, preventing custom hooks from dropping native agent traces or claiming a
    required source that was never read.
    """
    errors: list[str] = []
    contract = metadata.get("provenance_contract")
    if not isinstance(contract, dict):
        return ["workflow metadata has no provenance_contract"], {
            "agent_invocation_count": 0,
            "consumed_source_count": len(run.get("consumed_sources", [])),
        }
    expected_agents = contract.get("agent_invocations")
    required_sources = contract.get("required_source_reads")
    if not isinstance(expected_agents, list):
        errors.append("provenance_contract.agent_invocations must be an array")
        expected_agents = []
    if not isinstance(required_sources, list):
        errors.append("provenance_contract.required_source_reads must be an array")
        required_sources = []

    observed_agent_details = [
        event.get("detail", {})
        for event in run.get("events", [])
        if isinstance(event, dict)
        and isinstance(event.get("detail"), dict)
        and event["detail"].get("event_kind") == "agent-invoked"
    ]

    def agent_projection(value: Any, label: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            errors.append(f"{label} must be an object")
            return None
        name = value.get("agent_name")
        occurrence = value.get("workflow_occurrence")
        skills = value.get("activated_skill_ids")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}.agent_name must be a non-empty string")
        if not isinstance(occurrence, str) or not occurrence:
            errors.append(f"{label}.workflow_occurrence must be a non-empty string")
        if (
            not isinstance(skills, list)
            or any(not isinstance(skill, str) or not skill for skill in skills)
            or len(skills) != len(set(skills))
        ):
            errors.append(f"{label}.activated_skill_ids must contain unique strings")
            skills = []
        return {
            "agent_name": name,
            "workflow_occurrence": occurrence,
            "activated_skill_ids": skills,
        }

    expected_projection = [
        projected
        for index, row in enumerate(expected_agents)
        if (projected := agent_projection(row, f"expected agent {index}")) is not None
    ]
    observed_projection = [
        projected
        for index, row in enumerate(observed_agent_details)
        if (projected := agent_projection(row, f"observed agent {index}")) is not None
    ]
    if observed_projection != expected_projection:
        errors.append(
            "agent/skill receipts do not match provenance_contract: "
            f"expected {expected_projection!r}, observed {observed_projection!r}"
        )
    for index, detail in enumerate(observed_agent_details):
        if not detail.get("effect_record_id"):
            errors.append(f"observed agent {index} has no native effect_record_id")

    consumed_sources = [
        source for source in run.get("consumed_sources", []) if isinstance(source, dict)
    ]
    for index, source in enumerate(consumed_sources):
        if not isinstance(source.get("resource_id"), str) or not source["resource_id"]:
            errors.append(f"consumed source {index} has no resource_id")
        digest = source.get("content_digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            errors.append(f"consumed source {index} has no SHA-256 content digest")
    for index, required in enumerate(required_sources):
        if not isinstance(required, dict):
            errors.append(f"required source {index} must be an object")
            continue
        resource_id = required.get("resource_id")
        local_id = required.get("source_local_identifier")
        if not isinstance(resource_id, str) or not resource_id:
            errors.append(
                f"required source {index}.resource_id must be a non-empty string"
            )
            continue
        if local_id is not None and (not isinstance(local_id, str) or not local_id):
            errors.append(
                f"required source {index}.source_local_identifier must be a non-empty string"
            )
            continue
        if not any(
            source.get("resource_id") == resource_id
            and (local_id is None or source.get("source_local_identifier") == local_id)
            for source in consumed_sources
        ):
            suffix = f"/{local_id}" if local_id else ""
            errors.append(
                f"required source read was not observed: {resource_id}{suffix}"
            )

    return errors, {
        "agent_invocation_count": len(observed_projection),
        "consumed_source_count": len(consumed_sources),
        "agent_invocations": observed_projection,
        "consumed_source_ids": sorted(
            {
                source.get("resource_id")
                for source in consumed_sources
                if source.get("resource_id")
            }
        ),
    }


def validate(
    client: Client,
    workflow_id: str,
    run_id: str,
    *,
    wait_seconds: int,
) -> dict[str, Any]:
    workflows = client.json("/api/prism/workflows")
    workflow = next((row for row in workflows if row.get("id") == workflow_id), None)
    if workflow is None:
        return {
            "valid": False,
            "errors": [f"workflow {workflow_id!r} is not exposed by Lunar"],
        }
    metadata = workflow.get("metadata", {})
    completion = metadata.get("completion_contract", {})
    deadline = time.monotonic() + wait_seconds
    while True:
        run = client.json(f"/api/prism/runs/{run_id}")
        if run.get("state") in TERMINAL:
            break
        if time.monotonic() >= deadline:
            return {
                "valid": False,
                "errors": [
                    f"run did not reach a terminal state within {wait_seconds} seconds"
                ],
                "state": run.get("state"),
            }
        time.sleep(min(2, max(0, deadline - time.monotonic())))

    errors: list[str] = []
    if run.get("workflow_id") != workflow_id:
        errors.append(
            f"run workflow {run.get('workflow_id')!r} does not match {workflow_id!r}"
        )
    expected_state = completion.get("terminal_state", "completed")
    if run.get("state") != expected_state:
        errors.append(f"run state is {run.get('state')!r}; expected {expected_state!r}")
    if run.get("error_summary"):
        errors.append(f"run recorded an error: {run['error_summary']}")
    snapshot = reasoning_snapshot(client, workflow_id, run_id)
    errors.extend(reasoning_errors(snapshot, completion))
    report_failures, selected = report_errors(run, completion, metadata)
    errors.extend(report_failures)
    provenance_failures, provenance = provenance_errors(run, metadata)
    errors.extend(provenance_failures)
    unique = list(dict.fromkeys(errors))
    return {
        "valid": not unique,
        "errors": unique,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "state": run.get("state"),
        "reasoning_event_count": len(snapshot.get("entries", [])) if snapshot else 0,
        **provenance,
        **selected,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--package-version-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cookie")
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--bearer-token")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = Client(
        args.base_url,
        args.package_version_id,
        cookie=cookie_header(args.cookie_file, args.cookie),
        bearer_token=args.bearer_token,
    )
    report = validate(
        client,
        args.workflow_id,
        args.run_id,
        wait_seconds=max(0, args.wait_seconds),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"run {args.run_id}: {'valid' if report['valid'] else 'invalid'}")
        print(f"  state: {report.get('state')}")
        print(f"  reasoning events: {report.get('reasoning_event_count', 0)}")
        print(f"  agent invocations: {report.get('agent_invocation_count', 0)}")
        print(f"  consumed sources: {report.get('consumed_source_count', 0)}")
        for error in report["errors"]:
            print(f"  - {error}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
