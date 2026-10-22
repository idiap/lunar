# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Server-owned quality runtime profiles for the canonical MCP service."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def canonical_digest(value):
    from lunar_planner.contracts import canonical_digest as digest

    return digest(value)


_LOCAL_KEY = secrets.token_urlsafe(32).encode("ascii")


class LocalDeterministicQualityAdapter:
    """Conservatively evaluate committed, typed local execution artifacts."""

    identity = {
        "id": "lunar-local-deterministic-evaluator",
        "configuration": "bundled-local-v1",
        "adapter": "in_process",
    }

    @staticmethod
    def _plan_review(plan: Mapping[str, Any]) -> dict[str, Any]:
        criteria = [row for row in plan.get("criteria", ()) if isinstance(row, Mapping)]
        requirement_ids = set(map(str, plan.get("requirement_ids", ())))
        covered = {
            str(requirement_id)
            for row in criteria
            for requirement_id in row.get("requirement_ids", ())
        }
        criterion_ids = [str(row.get("criterion_id", "")) for row in criteria]
        checks = {
            "coverage": bool(criteria) and requirement_ids <= covered,
            "specificity": all(
                isinstance(row.get("observable"), str)
                and len(str(row["observable"]).strip()) >= 24
                for row in criteria
            ),
            "feasibility": all(bool(row.get("allowed_evidence")) for row in criteria),
            "authority": all(bool(row.get("authority_ceiling")) for row in criteria),
            "conflicts": bool(criterion_ids)
            and all(criterion_ids)
            and len(criterion_ids) == len(set(criterion_ids)),
            "architecture_bias": all(
                isinstance(row.get("source"), Mapping)
                and bool(row["source"].get("pointer"))
                for row in criteria
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return {
            "status": "pass" if not failed else "fail",
            "checks": checks,
            "findings": [
                f"local deterministic plan check failed: {name}" for name in failed
            ],
        }

    @staticmethod
    def _artifact_assessment(packet: Mapping[str, Any]) -> dict[str, Any]:
        data = packet.get("untrusted_data", {})
        plan = data.get("quality_plan", {}) if isinstance(data, Mapping) else {}
        candidate = (
            data.get("candidate_artifact") if isinstance(data, Mapping) else None
        )
        evidence = (
            data.get("authorized_evidence", ()) if isinstance(data, Mapping) else ()
        )
        deterministic = (
            data.get("deterministic_results", ()) if isinstance(data, Mapping) else ()
        )
        deterministic_by_id = {
            str(row.get("criterion_id")): row
            for row in deterministic
            if isinstance(row, Mapping)
        }
        source_anchors = [
            str(row["source_id"])
            for row in evidence
            if isinstance(row, Mapping) and row.get("source_id")
        ]
        typed_success = bool(
            isinstance(candidate, Mapping)
            and candidate.get("status") in {"success", "completed"}
            and (
                (
                    isinstance(candidate.get("records"), list)
                    and candidate.get("records")
                )
                or (candidate.get("execution_performed") is True and len(candidate) > 3)
            )
        )
        from lunar_planner.policy import policy_value

        rows: list[dict[str, Any]] = []
        for criterion in plan.get("criteria", ()) if isinstance(plan, Mapping) else ():
            criterion_id = str(criterion.get("criterion_id", ""))
            mode = str(criterion.get("evaluator_mode", ""))
            deterministic_result = deterministic_by_id.get(criterion_id, {})
            if mode == "deterministic":
                verdict = str(deterministic_result.get("verdict", "inconclusive"))
                uncertainty = "low" if verdict == "pass" else "high"
            elif not typed_success:
                verdict = "inconclusive"
                uncertainty = "high"
            elif (
                policy_value(
                    "quality_granularity",
                    {"criterion": criterion, "candidate": candidate},
                    {},
                )
                or {}
            ).get("missing_required_detail"):
                verdict = "fail"
                uncertainty = "low"
            elif not source_anchors:
                verdict = "inconclusive"
                uncertainty = "high"
            else:
                verdict = "pass"
                uncertainty = "medium"
            rows.append(
                {
                    "criterion_id": criterion_id,
                    "verdict": verdict,
                    "artifact_anchors": ["candidate:complete"],
                    "source_anchors": source_anchors,
                    "uncertainty": uncertainty,
                }
            )
        verdicts = {row["verdict"] for row in rows}
        status = (
            "fail"
            if "fail" in verdicts
            else ("pass" if verdicts == {"pass"} else "inconclusive")
        )
        return {"status": status, "criterion_results": rows}

    def evaluate(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        phase = packet.get("phase")
        if phase == "plan_review":
            data = packet.get("untrusted_data", {})
            plan = data.get("quality_plan", {}) if isinstance(data, Mapping) else {}
            value = self._plan_review(plan if isinstance(plan, Mapping) else {})
        elif phase in {"artifact_assessment", "composition_assessment"}:
            value = self._artifact_assessment(packet)
        else:
            value = {
                "status": "inconclusive",
                "criteria": [],
                "reason": "the bundled local profile does not synthesize criteria",
            }
        result = {
            **value,
            "schema_version": "lunar.planner.quality-evaluator-result/v1",
            "phase": phase,
            "request_digest": packet.get("digest"),
            "evaluator": dict(self.identity),
        }
        result["digest"] = canonical_digest(result)
        return result


@dataclass(frozen=True)
class QualityRuntime:
    profile: str
    attestation_key: bytes | None
    adapter: Any | None
    status: str

    def public_descriptor(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "status": self.status,
            "adapter_id": (
                self.adapter.identity.get("id") if self.adapter is not None else None
            ),
            "server_owned": True,
            "required_for_material_scientific_release": True,
        }


def configure_quality_runtime(profile: str) -> None:
    """Select a process-wide server profile before accepting MCP requests."""

    if profile not in {"local", "production"}:
        raise ValueError("quality profile must be 'local' or 'production'")
    os.environ["LUNAR_PROFILE"] = profile


def _production_runtime() -> QualityRuntime:
    raw = os.environ.get("LUNAR_QUALITY_ADAPTER_ARGV", "")
    key_value = os.environ.get("LUNAR_QUALITY_ATTESTATION_KEY", "")
    key = key_value.encode("utf-8") if len(key_value.encode("utf-8")) >= 32 else None
    if not raw:
        return QualityRuntime("production", key, None, "unconfigured")
    if key is None:
        return QualityRuntime("production", None, None, "unconfigured")
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LUNAR_QUALITY_ADAPTER_ARGV must be a JSON argv array"
        ) from exc
    if not isinstance(command, list) or not all(
        isinstance(item, str) and item for item in command
    ):
        raise ValueError("LUNAR_QUALITY_ADAPTER_ARGV must be a JSON argv array")
    configuration = (
        os.environ.get("LUNAR_QUALITY_ADAPTER_CONFIGURATION")
        or "deployment-configured-v1"
    )
    from lunar_planner.quality_evaluation import ConfiguredCommandQualityAdapter

    adapter = ConfiguredCommandQualityAdapter(
        command,
        evaluator_id=(
            os.environ.get("LUNAR_QUALITY_ADAPTER_ID")
            or "lunar-production-quality-adapter"
        ),
        configuration=configuration,
    )
    return QualityRuntime("production", key, adapter, "configured")


def get_quality_runtime() -> QualityRuntime:
    """Resolve the active server-owned runtime without exposing secrets."""

    profile = os.environ.get("LUNAR_PROFILE", "local")
    if profile == "local":
        os.environ["LUNAR_QUALITY_ATTESTATION_KEY"] = _LOCAL_KEY.decode("ascii")
        return QualityRuntime(
            "local", _LOCAL_KEY, LocalDeterministicQualityAdapter(), "configured"
        )
    if profile == "production":
        return _production_runtime()
    raise ValueError("LUNAR_PROFILE must be 'local' or 'production'")
