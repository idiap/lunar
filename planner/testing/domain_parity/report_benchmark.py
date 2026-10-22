# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic report-needs benchmark runner for the route-only planner.

The benchmark is deliberately an evaluation adapter rather than a second
planner.  It loads pinned cases, invokes :func:`run_planner_request`, and
checks observable routing properties without executing a workflow or calling
an external evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lunar_planner.config import require_repository_root

from lunar_planner.archetypes import load_surface_index
from lunar_planner.benchmark_quality import drive_route_only_quality_protocol
from lunar_planner.entrypoint import (
    run_planner_request,
    run_planner_request_with_test_surface,
)

_DEFAULT_PLANNER = run_planner_request

SUITE_SCHEMA = "lunar.planner.benchmark-suite/v1"
RESULT_SCHEMA = "lunar.planner.report-needs-benchmark-result/v1"
_SAFETY_EXPECTATIONS = {
    "route_only": True,
    "execution_allowed": False,
    "external_actions_allowed": False,
    "network_allowed": False,
    "installation_allowed": False,
    "codex_subprocess_allowed": False,
    "goal_creation_allowed": False,
    "performed_actions": [],
}
_STATUS_ORACLE_TO_PLANNER = {
    "plan_ready": "ready_for_semantic_review",
    "direct_use_ready": "ready_for_semantic_review",
    "clarification_required": "needs_input",
    "refused": "denied",
}


class ReportBenchmarkError(ValueError):
    """Raised when a benchmark suite is unsafe, unpinned, or malformed."""


def _canonical_digest(value: Any) -> str:
    """Canonical digest."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    """Sha256 file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_project(
    project_root: str | Path, relative_files: Iterable[str]
) -> dict[str, Any]:
    """Fingerprint an explicit, confined set of copied-project files."""

    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ReportBenchmarkError("project_root must be a directory")
    files: set[Path] = set()
    for relative in sorted({str(item) for item in relative_files}):
        candidate = root.joinpath(relative)
        if candidate.is_symlink():
            raise ReportBenchmarkError(
                f"project file must not be a symlink: {relative}"
            )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise ReportBenchmarkError(
                f"project file is missing or escapes root: {relative}"
            ) from exc
        if resolved.is_dir():
            files.update(
                path
                for path in resolved.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            )
        elif resolved.is_file():
            files.add(resolved)
        else:
            raise ReportBenchmarkError(
                f"project input is neither a file nor directory: {relative}"
            )
    rows: list[dict[str, str]] = []
    for resolved in sorted(files):
        if resolved.is_symlink():
            raise ReportBenchmarkError(
                f"project file must not be a symlink: {resolved.relative_to(root)}"
            )
        rows.append(
            {
                "path": resolved.relative_to(root).as_posix(),
                "sha256": _sha256_file(resolved),
            }
        )
    if not rows:
        raise ReportBenchmarkError(
            "project fingerprint requires at least one explicit file"
        )
    return {"files": rows, "digest": _canonical_digest(rows)}


def load_report_benchmark(path: str | Path) -> dict[str, Any]:
    """Load and structurally validate one benchmark-suite JSON document."""

    suite_path = Path(path).resolve(strict=True)
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportBenchmarkError(f"invalid benchmark JSON: {exc}") from exc
    if not isinstance(suite, dict) or suite.get("schema_version") != SUITE_SCHEMA:
        raise ReportBenchmarkError(f"benchmark schema_version must be {SUITE_SCHEMA}")
    if (
        not isinstance(suite.get("benchmark_id"), str)
        or not suite["benchmark_id"].strip()
    ):
        raise ReportBenchmarkError("benchmark_id is required")
    source_copy = suite.get("source_copy")
    if not isinstance(source_copy, dict):
        raise ReportBenchmarkError("source_copy is required")
    for field in ("workflow_id", "scenario_id", "reference_paths", "copy_policy"):
        if not source_copy.get(field):
            raise ReportBenchmarkError(f"source_copy.{field} is required")
    if not isinstance(source_copy["reference_paths"], list):
        raise ReportBenchmarkError("source_copy.reference_paths must be a list")
    project_snapshot = suite.get("project_snapshot")
    if not isinstance(project_snapshot, dict):
        raise ReportBenchmarkError("project_snapshot is required")
    snapshot_rows = project_snapshot.get("files")
    if not isinstance(snapshot_rows, list) or not snapshot_rows:
        raise ReportBenchmarkError("project_snapshot.files must be a non-empty list")
    snapshot_paths = [
        row.get("path") for row in snapshot_rows if isinstance(row, Mapping)
    ]
    if len(snapshot_paths) != len(snapshot_rows) or not all(
        isinstance(item, str) and item for item in snapshot_paths
    ):
        raise ReportBenchmarkError("every project_snapshot file needs a path")
    if fingerprint_project(suite_path.parent, snapshot_paths) != project_snapshot:
        raise ReportBenchmarkError("project_snapshot does not match copied files")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ReportBenchmarkError("cases must be a non-empty list")
    identifiers: set[str] = set()
    for offset, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ReportBenchmarkError(f"cases[{offset}] must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ReportBenchmarkError(f"cases[{offset}].case_id is required")
        if case_id in identifiers:
            raise ReportBenchmarkError(f"duplicate case_id: {case_id}")
        identifiers.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ReportBenchmarkError(f"{case_id}.query is required")
        for field in (
            "report_context",
            "constraints",
            "oracle",
            "deterministic_digest",
        ):
            if field not in case:
                raise ReportBenchmarkError(f"{case_id}.{field} is required")
        if case["constraints"].get("authority") != "planning_only":
            raise ReportBenchmarkError(
                f"{case_id}.constraints.authority must be planning_only"
            )
        if not case["report_context"].get("observed_surface"):
            raise ReportBenchmarkError(
                f"{case_id}.report_context.observed_surface is required"
            )
        for field in (
            "allowed_earliest_responsible_surfaces",
            "required_outcomes",
            "hard_failures",
            "scoring",
        ):
            if not case["oracle"].get(field):
                raise ReportBenchmarkError(f"{case_id}.oracle.{field} is required")
        if not isinstance(case.get("expected"), dict) or not case["expected"]:
            raise ReportBenchmarkError(
                f"{case_id}.expected must define observable outcomes"
            )
        supplied_digest = str(case["deterministic_digest"])
        digest_payload = {
            key: value for key, value in case.items() if key != "deterministic_digest"
        }
        if supplied_digest != f"sha256:{_canonical_digest(digest_payload)}":
            raise ReportBenchmarkError(
                f"{case_id}.deterministic_digest does not match its case"
            )
    suite["_suite_path"] = str(suite_path)
    return suite


def _candidate_ids(result: Mapping[str, Any]) -> set[str]:
    """Candidate ids."""
    identifiers: set[str] = set()
    selected = result.get("selected_target")
    if isinstance(selected, Mapping):
        value = selected.get("id", selected.get("name"))
        if value:
            identifiers.add(str(value))
    candidates = result.get("candidates", {})
    if isinstance(candidates, Mapping):
        for group in ("workflow_first", "uncovered_archetypes", "leaf_skills"):
            for row in candidates.get(group, ()):
                if isinstance(row, Mapping):
                    value = row.get("id", row.get("name"))
                    if value:
                        identifiers.add(str(value))
                        if row.get("scope"):
                            identifiers.add(f"{row['scope']}:{value}")
    return identifiers


def _add_check(
    checks: list[dict[str, Any]], check_id: str, actual: Any, expected: Any
) -> None:
    """Add check."""
    checks.append(
        {
            "check_id": check_id,
            "passed": actual == expected,
            "expected": expected,
            "actual": actual,
        }
    )


def evaluate_report_case(
    case: Mapping[str, Any], result: Mapping[str, Any], *, deterministic: bool
) -> dict[str, Any]:
    """Evaluate one planner response using only deterministic assertions."""

    expected = dict(case["expected"])
    checks: list[dict[str, Any]] = []
    for field in ("mode", "status", "primary_intent"):
        if field in expected:
            wanted = expected[field]
            if field == "status":
                wanted = _STATUS_ORACLE_TO_PLANNER.get(str(wanted), wanted)
            _add_check(checks, field, result.get(field), wanted)
    selected = result.get("selected_target", {})
    if "selected_target_id" in expected:
        actual = (
            selected.get("id", selected.get("name"))
            if isinstance(selected, Mapping)
            else None
        )
        _add_check(checks, "selected_target_id", actual, expected["selected_target_id"])

    candidates = _candidate_ids(result)
    for identifier in expected.get("required_candidate_ids", ()):
        _add_check(
            checks,
            f"required_candidate:{identifier}",
            str(identifier) in candidates,
            True,
        )
    if expected.get("any_candidate_ids"):
        requested = {str(item) for item in expected["any_candidate_ids"]}
        checks.append(
            {
                "check_id": "any_candidate_ids",
                "passed": bool(candidates & requested),
                "expected": sorted(requested),
                "actual": sorted(candidates),
            }
        )
    for identifier in expected.get("forbidden_candidate_ids", ()):
        _add_check(
            checks,
            f"forbidden_candidate:{identifier}",
            str(identifier) in candidates,
            False,
        )
    selected_id = None
    if isinstance(selected, Mapping):
        selected_id = selected.get("id", selected.get("name"))
    for identifier in expected.get("forbidden_selections", ()):
        _add_check(
            checks, f"forbidden_selection:{identifier}", selected_id, str(identifier)
        )
        checks[-1]["passed"] = str(selected_id) != str(identifier)
    if "blocker_contains" in expected:
        blockers = "\n".join(str(item) for item in result.get("blockers", ()))
        needle = str(expected["blocker_contains"])
        checks.append(
            {
                "check_id": "blocker_contains",
                "passed": needle in blockers,
                "expected": needle,
                "actual": blockers,
            }
        )

    for field, required in _SAFETY_EXPECTATIONS.items():
        _add_check(checks, f"safety:{field}", result.get(field), required)
    safety_aliases = {
        "route_only": result.get("route_only") is True,
        "no_execution": result.get("execution_allowed") is False,
        "no_external_actions": result.get("external_actions_allowed") is False,
        "no_network": result.get("network_allowed") is False,
        "planning_only": result.get("route_only") is True
        and result.get("execution_allowed") is False,
        "semantic_review_required": result.get("semantic_review_required") is True,
    }
    declared_flags = [str(flag) for flag in expected.get("safety_flags", ())]
    observable_flags = [flag for flag in declared_flags if flag in safety_aliases]
    for flag in observable_flags:
        _add_check(checks, f"declared_safety:{flag}", safety_aliases[flag], True)
    _add_check(checks, "deterministic_repeat", deterministic, True)
    passed_count = sum(bool(row["passed"]) for row in checks)
    return {
        "case_id": case["case_id"],
        "case_digest": case.get(
            "deterministic_digest", f"sha256:{_canonical_digest(case)}"
        ),
        "report_need": case.get(
            "report_need", case.get("report_context", {}).get("observed_surface")
        ),
        "category": case.get("category", "uncategorized"),
        "passed": passed_count == len(checks),
        "score": passed_count / len(checks),
        "checks_passed": passed_count,
        "checks_total": len(checks),
        "checks": checks,
        "observed": {
            "mode": result.get("mode"),
            "status": result.get("status"),
            "primary_intent": result.get("primary_intent"),
            "selected_target_id": (
                result.get("selected_target", {}).get(
                    "id", result.get("selected_target", {}).get("name")
                )
                if isinstance(result.get("selected_target"), Mapping)
                else None
            ),
            "candidate_ids": sorted(_candidate_ids(result)),
        },
        "planner_result_digest": _canonical_digest(result),
        "oracle_dimensions": {
            "route": {
                "status": "evaluated",
                "basis": "expected route fields and candidates",
            },
            "safety": {
                "status": "evaluated",
                "basis": "route-only authority and side-effect fields",
                "unevaluated_declared_flags": sorted(
                    set(declared_flags) - set(observable_flags)
                ),
            },
            "scientific_boundary": {
                "status": "not_evaluated",
                "basis": "route-only output contains no scientific plan to assess",
            },
            "localization": {
                "status": "not_evaluated",
                "basis": "planner emits candidates, not an implementation plan",
            },
            "reuse": {
                "status": "not_evaluated",
                "basis": "no accepted reuse decision in route-only output",
            },
            "acceptance": {
                "status": "not_evaluated",
                "basis": "no plan acceptance in route-only output",
            },
        },
        "oracle_preserved": case.get("oracle"),
    }


def run_report_benchmark(
    suite: Mapping[str, Any],
    *,
    repo_root: str | Path | None = None,
    expected_case_count: int | None = 20,
) -> dict[str, Any]:
    """Run and score a pinned report-needs suite without executing workflows."""

    cases = suite.get("cases", ())
    if expected_case_count is not None and len(cases) != expected_case_count:
        raise ReportBenchmarkError(
            f"benchmark requires exactly {expected_case_count} cases; found {len(cases)}"
        )
    case_results: list[dict[str, Any]] = []
    resolved_repo_root = (
        Path(repo_root).resolve() if repo_root else require_repository_root()
    )
    shared_surface_index = load_surface_index(repo_root=resolved_repo_root)
    source_copy = suite.get("source_copy", {})
    source_snapshot = fingerprint_project(
        resolved_repo_root, source_copy.get("reference_paths", ())
    )
    for case in cases:
        report_context = case.get("report_context", {})
        source_copy = suite.get("source_copy", {})
        references = list(source_copy.get("reference_paths", ()))
        references.extend(report_context.get("evidence_anchors", ()))
        if report_context.get("observed_surface"):
            references.append(report_context["observed_surface"])
        kwargs = {
            "references": case.get("references", references),
            "desired_inputs": case.get("desired_inputs", ()),
            "desired_outputs": case.get("desired_outputs", ()),
            "scope": case.get("scope", "scientific"),
            "repo_root": resolved_repo_root,
        }
        if run_planner_request is _DEFAULT_PLANNER:

            def call(text: str, **values: Any) -> dict[str, Any]:
                """Call."""
                return run_planner_request_with_test_surface(
                    text, shared_surface_index, repo_root=resolved_repo_root, **values
                )

            first = drive_route_only_quality_protocol(
                run_planner_request_with_test_surface(
                    str(case["query"]), shared_surface_index, **kwargs
                ),
                call_planner=call,
            )
            second = drive_route_only_quality_protocol(
                run_planner_request_with_test_surface(
                    str(case["query"]), shared_surface_index, **kwargs
                ),
                call_planner=call,
            )
        else:  # explicit evaluator seam used by unit tests
            first = run_planner_request(str(case["query"]), **kwargs)
            second = run_planner_request(str(case["query"]), **kwargs)
        case_results.append(
            evaluate_report_case(
                case,
                first,
                deterministic=_canonical_digest(first) == _canonical_digest(second),
            )
        )

    checks_total = sum(row["checks_total"] for row in case_results)
    checks_passed = sum(row["checks_passed"] for row in case_results)
    category_rows: dict[str, list[dict[str, Any]]] = {}
    for row in case_results:
        category_rows.setdefault(str(row["category"]), []).append(row)
    categories = {
        category: {
            "case_count": len(rows),
            "passed": sum(bool(row["passed"]) for row in rows),
            "mean_score": sum(float(row["score"]) for row in rows) / len(rows),
        }
        for category, rows in sorted(category_rows.items())
    }
    suite_payload = {
        key: value for key, value in suite.items() if not str(key).startswith("_")
    }
    output: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "benchmark_id": suite["benchmark_id"],
        "suite_digest": _canonical_digest(suite_payload),
        "source_copy": suite.get("source_copy", {"status": "not_declared"}),
        "source_snapshot": source_snapshot,
        "case_count": len(case_results),
        "cases_passed": sum(bool(row["passed"]) for row in case_results),
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "micro_score": checks_passed / checks_total,
        "categories": categories,
        "case_results": case_results,
        "passed": all(bool(row["passed"]) for row in case_results),
        "execution_performed": False,
    }
    output["result_digest"] = _canonical_digest(output)
    return output


def render_report_benchmark_markdown(result: Mapping[str, Any]) -> str:
    """Render a stable, compact human review of a benchmark result."""

    lines = [
        f"# Planner report-needs benchmark: {result['benchmark_id']}",
        "",
        f"- Result: **{'PASS' if result['passed'] else 'FAIL'}**",
        f"- Cases: {result['cases_passed']}/{result['case_count']} passed",
        f"- Checks: {result['checks_passed']}/{result['checks_total']} passed",
        f"- Micro score: {float(result['micro_score']):.4f}",
        f"- Suite digest: `{result['suite_digest']}`",
        f"- Source snapshot digest: `{result['source_snapshot']['digest']}`",
        f"- Result digest: `{result['result_digest']}`",
        "- Workflow execution performed: no",
        "",
        "## Cases",
        "",
        "| Case | Category | Result | Score | Observed route |",
        "|---|---|---:|---:|---|",
    ]
    for case in result["case_results"]:
        observed = case["observed"]
        route = "/".join(
            str(observed.get(field) or "-")
            for field in ("mode", "status", "primary_intent")
        )
        lines.append(
            f"| `{case['case_id']}` | {case['category']} | "
            f"{'PASS' if case['passed'] else 'FAIL'} | {float(case['score']):.4f} | `{route}` |"
        )
    failures = [
        (case["case_id"], check)
        for case in result["case_results"]
        for check in case["checks"]
        if not check["passed"]
    ]
    lines.extend(["", "## Failed checks", ""])
    if failures:
        for case_id, check in failures:
            lines.append(
                f"- `{case_id}` / `{check['check_id']}`: expected "
                f"`{json.dumps(check['expected'], sort_keys=True)}`, observed "
                f"`{json.dumps(check['actual'], sort_keys=True)}`."
            )
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Evaluation boundary",
            "",
            "Routing, candidate visibility, repeatability, and no-side-effect safety are automated. ",
            "Localization, scientific boundaries, reuse quality, and acceptance outcomes remain explicit expert-review oracles.",
            "",
            "This benchmark is route-only and performs no scientific workflow execution.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report_benchmark(
    result: Mapping[str, Any], output_directory: str | Path
) -> dict[str, str]:
    """Write deterministic machine- and human-readable benchmark artifacts."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "benchmark-result.json"
    markdown_path = directory / "benchmark-report.md"
    json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_report_benchmark_markdown(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _main(argv: Sequence[str] | None = None) -> int:
    """Main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path, help="Path to the benchmark-suite JSON")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output", type=Path, help="Legacy single JSON output path")
    parser.add_argument(
        "--output-dir", type=Path, help="Write JSON and Markdown reports"
    )
    parser.add_argument("--case-count", type=int, default=20)
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Return nonzero when any route-level benchmark check fails",
    )
    args = parser.parse_args(argv)
    suite = load_report_benchmark(args.suite)
    result = run_report_benchmark(
        suite, repo_root=args.repo_root, expected_case_count=args.case_count
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output_dir:
        write_report_benchmark(result, args.output_dir)
    elif args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if args.require_pass and not result["passed"] else 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(_main())


__all__ = [
    "RESULT_SCHEMA",
    "SUITE_SCHEMA",
    "ReportBenchmarkError",
    "evaluate_report_case",
    "fingerprint_project",
    "load_report_benchmark",
    "render_report_benchmark_markdown",
    "run_report_benchmark",
    "write_report_benchmark",
]
