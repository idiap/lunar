# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Normalized, user-surfaceable decision traces for Lunar components.

Purpose: provide the `reasoning log` component of the Lunar runtime. Key concepts: typed execution boundaries, explicit availability, reproducible provenance, and fail-closed behavior. Principal I/O is defined by this module's public runtime interfaces.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("reasoning-log-v1.schema.json")
FORBIDDEN_DETAIL_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "private_reasoning",
    "scratchpad",
}


class ReasoningLogError(ValueError):
    """Raised when a reasoning log is unsafe or structurally invalid."""


def _digest(value: Mapping[str, Any]) -> str:
    """Return a deterministic content digest for one JSON-compatible mapping."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _strings(values: Iterable[Any] | None) -> list[str]:
    """Normalize a sequence into unique, non-empty human-readable strings."""

    return list(
        dict.fromkeys(
            str(value).strip() for value in (values or ()) if str(value).strip()
        )
    )


def _assert_no_private_reasoning(value: Any, path: str = "log") -> None:
    """Reject fields that attempt to store hidden chain-of-thought content."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_DETAIL_KEYS:
                raise ReasoningLogError(
                    f"{path}.{key} is not permitted in a user-facing reasoning log"
                )
            _assert_no_private_reasoning(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_private_reasoning(child, f"{path}[{index}]")


def build_reasoning_log(
    *,
    subject_kind: str,
    subject_id: str,
    summary: str,
    status: str,
    events: Iterable[Mapping[str, Any]],
    assumptions: Iterable[str] = (),
    evidence_references: Iterable[Mapping[str, Any]] = (),
    blockers: Iterable[str] = (),
    limitations: Iterable[str] = (),
    redactions: Iterable[str] = (),
) -> dict[str, Any]:
    """Build and validate a normalized decision trace from component events."""

    raw_events = list(events)
    _assert_no_private_reasoning(raw_events, "events")
    entries: list[dict[str, Any]] = []
    for sequence, raw in enumerate(raw_events, start=1):
        decision = dict(raw.get("decision", {}))
        entries.append(
            {
                "entry_id": str(raw.get("entry_id") or f"entry-{sequence}"),
                "sequence": sequence,
                "stage": str(raw.get("stage") or "unspecified"),
                "actor": {
                    "kind": str(dict(raw.get("actor", {})).get("kind") or subject_kind),
                    "id": str(dict(raw.get("actor", {})).get("id") or subject_id),
                },
                "action": str(raw.get("action") or "recorded component decision"),
                "rationale_summary": str(
                    raw.get("rationale_summary")
                    or "The recorded outcome follows the declared inputs, contract, and checks."
                ),
                "inputs_used": _strings(raw.get("inputs_used")),
                "decision": {
                    "status": str(decision.get("status") or "informational"),
                    "outcome": str(
                        decision.get("outcome") or "No material decision recorded."
                    ),
                    "alternatives_considered": _strings(
                        decision.get("alternatives_considered")
                    ),
                },
                "outputs": _strings(raw.get("outputs")),
                "checks": _strings(raw.get("checks")),
                "blockers": _strings(raw.get("blockers")),
            }
        )
    if not entries:
        raise ReasoningLogError("at least one reasoning-log event is required")
    payload: dict[str, Any] = {
        "schema_version": "lunar.reasoning-log/v1",
        "log_id": f"reasoning-log:{subject_kind}:{subject_id}",
        "subject": {"kind": subject_kind, "id": subject_id},
        "status": status,
        "summary": summary.strip(),
        "entries": entries,
        "assumptions": _strings(assumptions),
        "evidence_references": [dict(row) for row in evidence_references],
        "blockers": _strings(blockers),
        "limitations": _strings(limitations),
        "visibility": {
            "user_surfaceable": True,
            "detail_level": "decision_trace",
            "contains_hidden_chain_of_thought": False,
            "redactions": _strings(redactions),
        },
    }
    _assert_no_private_reasoning(payload)
    payload["digest"] = _digest(payload)
    validate_reasoning_log(payload)
    return payload


def validate_reasoning_log(log: Mapping[str, Any]) -> None:
    """Validate schema, digest integrity, sequencing, and visibility boundaries."""

    _assert_no_private_reasoning(log)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(log)),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ReasoningLogError("; ".join(error.message for error in errors))
    unsigned = {key: value for key, value in log.items() if key != "digest"}
    if log.get("digest") != _digest(unsigned):
        raise ReasoningLogError("reasoning-log digest mismatch")
    sequences = [entry["sequence"] for entry in log["entries"]]
    if sequences != list(range(1, len(sequences) + 1)):
        raise ReasoningLogError(
            "reasoning-log entries must have contiguous sequence numbers"
        )


def render_reasoning_log_markdown(log: Mapping[str, Any]) -> str:
    """Render a validated reasoning log as compact, human-readable Markdown."""

    validate_reasoning_log(log)
    lines = [
        f"# Reasoning log: {log['subject']['id']}",
        "",
        str(log["summary"]),
        "",
        f"Status: **{log['status']}**  ",
        "Detail: decision trace; hidden chain-of-thought is not included.",
    ]
    for entry in log["entries"]:
        lines.extend(
            [
                "",
                f"## {entry['sequence']}. {entry['stage']}",
                "",
                f"- Actor: `{entry['actor']['kind']}:{entry['actor']['id']}`",
                f"- Action: {entry['action']}",
                f"- Why: {entry['rationale_summary']}",
                f"- Decision: **{entry['decision']['status']}** — {entry['decision']['outcome']}",
            ]
        )
        for label, values in (
            ("Inputs used", entry["inputs_used"]),
            ("Alternatives", entry["decision"]["alternatives_considered"]),
            ("Outputs", entry["outputs"]),
            ("Checks", entry["checks"]),
            ("Blockers", entry["blockers"]),
        ):
            if values:
                lines.append(f"- {label}: " + "; ".join(values))
    for label, values in (
        ("Assumptions", log["assumptions"]),
        ("Blockers", log["blockers"]),
        ("Limitations", log["limitations"]),
    ):
        if values:
            lines.extend(["", f"## {label}", "", *[f"- {value}" for value in values]])
    if log["evidence_references"]:
        lines.extend(["", "## Evidence and artifacts", ""])
        for reference in log["evidence_references"]:
            lines.append(
                f"- `{reference['id']}` ({reference['kind']}): {reference['locator']}"
            )
    return "\n".join(lines).rstrip() + "\n"
