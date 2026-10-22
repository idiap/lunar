# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Blind benchmark for external-framework-aware workflow extension planning.

The runner checks only observable planner output. Queries must not name the
frameworks or packages expected by their oracles, so candidate discovery and
resource-coverage evidence cannot be prompted by explicit user vocabulary.
No package is installed and no workflow or external framework is executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
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

SUITE_SCHEMA = "lunar.planner.blind-external-reuse-suite/v1"
RESULT_SCHEMA = "lunar.planner.blind-external-reuse-result/v1"
PACKAGE_ORACLE_SCHEMA = "lunar.planner.blind-external-reuse-package-oracles/v1"
PACKAGE_EXTENSION_SCHEMA = "lunar.planner.blind-external-reuse-package-extension/v1"
DEFAULT_REQUIRED_SURFACES = (
    "local_workflows",
    "promoted_subworkflows",
    "local_scientific_skills",
    "bioconductor",
    "biomni",
)
_SAFETY = {
    "route_only": True,
    "execution_allowed": False,
    "external_actions_allowed": False,
    "network_allowed": False,
    "installation_allowed": False,
    "performed_actions": [],
}


class ExternalReuseBenchmarkError(ValueError):
    """Raised when a blind external-reuse benchmark is malformed or leaks."""


def _digest(value: Any) -> str:
    """Digest."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    """File digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(value: str) -> str:
    """Normalized."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _candidate_ids(result: Mapping[str, Any]) -> set[str]:
    """Candidate ids."""
    identifiers: set[str] = set()
    selected = result.get("selected_target")
    rows: list[Mapping[str, Any]] = []
    if isinstance(selected, Mapping):
        rows.append(selected)
    candidates = result.get("candidates")
    if isinstance(candidates, Mapping):
        for group in ("workflow_first", "uncovered_archetypes", "leaf_skills"):
            rows.extend(
                row for row in candidates.get(group, ()) if isinstance(row, Mapping)
            )
    for row in rows:
        identifier = row.get("id", row.get("name"))
        if identifier:
            identifiers.add(str(identifier))
            if row.get("scope"):
                identifiers.add(f"{row['scope']}:{identifier}")
            for alias in row.get("aliases", ()):
                legacy = str(alias)
                identifiers.add(legacy)
                # Layout@1 aliases used ``<scope>-<name>`` while benchmark
                # oracles used the equivalent logical ``<scope>:<name>`` ID.
                # Credit both during the bounded compatibility window.
                legacy_scope, separator, legacy_name = legacy.partition("-")
                if separator and legacy_scope in {
                    "scientific",
                    "planner",
                    "project_support",
                }:
                    identifiers.add(f"{legacy_scope}:{legacy_name}")
    return identifiers


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    expected: Any,
    actual: Any,
) -> None:
    """Check."""
    checks.append(
        {"check_id": check_id, "passed": passed, "expected": expected, "actual": actual}
    )


def _validate_case(
    case: Mapping[str, Any], *, index: int, forbidden: Sequence[str]
) -> None:
    """Validate case."""
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ExternalReuseBenchmarkError(f"cases[{index}].case_id is required")
    query = case.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ExternalReuseBenchmarkError(f"{case_id}.query is required")
    expected = case.get("expected")
    if not isinstance(expected, Mapping):
        raise ExternalReuseBenchmarkError(f"{case_id}.expected is required")
    planner_visible = " ".join(
        [
            query,
            *(str(item) for item in case.get("references", ())),
            *(str(item) for item in case.get("desired_inputs", ())),
            *(str(item) for item in case.get("desired_outputs", ())),
        ]
    )
    leaked_terms = sorted(
        term for term in forbidden if _normalized(term) in _normalized(planner_visible)
    )
    if leaked_terms:
        raise ExternalReuseBenchmarkError(
            f"{case_id} leaks forbidden framework/package terms: {', '.join(leaked_terms)}"
        )
    supplied = case.get("deterministic_digest")
    payload = {
        key: value for key, value in case.items() if key != "deterministic_digest"
    }
    if supplied != f"sha256:{_digest(payload)}":
        raise ExternalReuseBenchmarkError(f"{case_id}.deterministic_digest mismatch")


def _load_package_oracles(
    path: Path, cases: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Load evaluator-only package judgments anchored to the immutable v1 queries."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalReuseBenchmarkError(
            f"invalid package oracle JSON: {exc}"
        ) from exc
    if payload.get("schema_version") != PACKAGE_ORACLE_SCHEMA:
        raise ExternalReuseBenchmarkError(
            f"package oracle schema_version must be {PACKAGE_ORACLE_SCHEMA}"
        )
    source_suite = payload.get("source_suite")
    if source_suite != "cases.json":
        raise ExternalReuseBenchmarkError(
            "package oracle source_suite must be cases.json"
        )
    source_path = path.with_name(source_suite)
    if not source_path.is_file() or _file_digest(source_path) != payload.get(
        "source_suite_sha256"
    ):
        raise ExternalReuseBenchmarkError("package oracle source suite digest mismatch")
    case_map = {str(case["case_id"]): case for case in cases}
    legacy_queries = payload.get("legacy_queries")
    if not isinstance(legacy_queries, list) or len(legacy_queries) != len(cases):
        raise ExternalReuseBenchmarkError("all legacy query digests must be pinned")
    pinned_queries = {
        str(row.get("case_id")): str(row.get("query_sha256"))
        for row in legacy_queries
        if isinstance(row, Mapping)
    }
    if set(pinned_queries) != set(case_map):
        raise ExternalReuseBenchmarkError(
            "legacy query identities differ from source suite"
        )
    for case_id, case in case_map.items():
        observed = hashlib.sha256(case["query"].encode()).hexdigest()
        if pinned_queries[case_id] != observed:
            raise ExternalReuseBenchmarkError(f"{case_id} legacy query changed")
    rows = payload.get("oracles")
    if not isinstance(rows, list):
        raise ExternalReuseBenchmarkError("package oracle rows are required")
    oracles: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("case_id") not in case_map:
            raise ExternalReuseBenchmarkError(
                "package oracle references an unknown case"
            )
        case_id = str(row["case_id"])
        if case_id in oracles:
            raise ExternalReuseBenchmarkError(f"duplicate package oracle: {case_id}")
        query_digest = hashlib.sha256(case_map[case_id]["query"].encode()).hexdigest()
        if row.get("query_sha256") != query_digest:
            raise ExternalReuseBenchmarkError(
                f"{case_id} package oracle query digest mismatch"
            )
        primary = row.get("acceptable_primary_packages")
        secondary = row.get("acceptable_secondary_packages")
        if (
            not isinstance(primary, list)
            or not primary
            or not isinstance(secondary, list)
        ):
            raise ExternalReuseBenchmarkError(
                f"{case_id} package families are malformed"
            )
        if set(primary).intersection(secondary):
            raise ExternalReuseBenchmarkError(
                f"{case_id} primary and secondary families overlap"
            )
        disposition = case_map[case_id]["expected"]["external_framework_dispositions"][
            "bioconductor"
        ]
        if disposition != ["selected"]:
            raise ExternalReuseBenchmarkError(
                f"{case_id} does not scientifically select package discovery"
            )
        oracles[case_id] = row
    selected = {
        case_id
        for case_id, case in case_map.items()
        if case["expected"]["external_framework_dispositions"]["bioconductor"]
        == ["selected"]
    }
    if set(oracles) != selected:
        raise ExternalReuseBenchmarkError(
            "package oracles must cover exactly the selected legacy cases"
        )
    return oracles


def load_package_search_extension(path: str | Path) -> dict[str, Any]:
    """Load and validate the separate eight-family blind package extension."""
    suite_path = Path(path).resolve(strict=True)
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalReuseBenchmarkError(
            f"invalid package extension JSON: {exc}"
        ) from exc
    if suite.get("schema_version") != PACKAGE_EXTENSION_SCHEMA:
        raise ExternalReuseBenchmarkError(
            f"package extension schema_version must be {PACKAGE_EXTENSION_SCHEMA}"
        )
    cases = suite.get("cases")
    oracles = suite.get("oracles")
    if not isinstance(cases, list) or len(cases) != 8:
        raise ExternalReuseBenchmarkError(
            "package extension requires exactly eight cases"
        )
    if not isinstance(oracles, list) or len(oracles) != 8:
        raise ExternalReuseBenchmarkError(
            "package extension requires exactly eight oracles"
        )
    forbidden = [str(value) for value in suite.get("forbidden_query_terms", ())]
    if not forbidden:
        raise ExternalReuseBenchmarkError(
            "package extension forbidden_query_terms are required"
        )
    oracle_map = {
        str(row.get("case_id")): row for row in oracles if isinstance(row, Mapping)
    }
    if len(oracle_map) != 8:
        raise ExternalReuseBenchmarkError(
            "package extension oracle identities are invalid"
        )
    families: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id", ""))
        family = str(case.get("family", ""))
        query = str(case.get("query", ""))
        if not case_id or not family or not query or case_id not in oracle_map:
            raise ExternalReuseBenchmarkError("package extension case is malformed")
        if family in families:
            raise ExternalReuseBenchmarkError(
                f"duplicate package extension family: {family}"
            )
        families.add(family)
        planner_visible = " ".join(
            [
                query,
                *(str(value) for value in case.get("references", ())),
                *(str(value) for value in case.get("desired_inputs", ())),
                *(str(value) for value in case.get("desired_outputs", ())),
            ]
        )
        normalized_query = _normalized(planner_visible)
        leaked = sorted(
            term for term in forbidden if _normalized(term) in normalized_query
        )
        if leaked:
            raise ExternalReuseBenchmarkError(
                f"{case_id} leaks forbidden framework/package terms: {', '.join(leaked)}"
            )
        supplied = case.get("deterministic_digest")
        case_payload = {
            key: value for key, value in case.items() if key != "deterministic_digest"
        }
        if supplied != f"sha256:{_digest(case_payload)}":
            raise ExternalReuseBenchmarkError(
                f"{case_id}.deterministic_digest mismatch"
            )
        oracle = oracle_map[case_id]
        if oracle.get("query_sha256") != hashlib.sha256(query.encode()).hexdigest():
            raise ExternalReuseBenchmarkError(f"{case_id} oracle query digest mismatch")
        if not oracle.get("acceptable_primary_packages"):
            raise ExternalReuseBenchmarkError(
                f"{case_id} requires a primary package family"
            )
    return suite


def load_external_reuse_benchmark(
    path: str | Path, *, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Load a pinned suite and fail if any query reveals its reuse oracle."""

    suite_path = Path(path).resolve(strict=True)
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalReuseBenchmarkError(f"invalid benchmark JSON: {exc}") from exc
    if not isinstance(suite, dict) or suite.get("schema_version") != SUITE_SCHEMA:
        raise ExternalReuseBenchmarkError(f"schema_version must be {SUITE_SCHEMA}")
    policy = suite.get("blind_policy")
    if not isinstance(policy, Mapping) or not policy.get("forbidden_query_terms"):
        raise ExternalReuseBenchmarkError(
            "blind_policy.forbidden_query_terms is required"
        )
    snapshot = suite.get("resource_snapshot")
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("files"), list):
        raise ExternalReuseBenchmarkError("resource_snapshot.files is required")
    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else require_repository_root()
    )
    observed_files: list[dict[str, str]] = []
    for row in snapshot["files"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise ExternalReuseBenchmarkError("resource_snapshot file path is required")
        candidate = root / row["path"]
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise ExternalReuseBenchmarkError(
                f"resource snapshot path is missing or unconfined: {row['path']}"
            ) from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise ExternalReuseBenchmarkError(
                f"resource snapshot path must be a regular file: {row['path']}"
            )
        observed_files.append({"path": row["path"], "sha256": _file_digest(resolved)})
    observed_snapshot = {"files": observed_files, "digest": _digest(observed_files)}
    if observed_snapshot != snapshot:
        raise ExternalReuseBenchmarkError(
            "resource_snapshot does not match available resources"
        )
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) != 20:
        raise ExternalReuseBenchmarkError("benchmark requires exactly 20 cases")
    identifiers: set[str] = set()
    forbidden = [str(item) for item in policy["forbidden_query_terms"]]
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ExternalReuseBenchmarkError(f"cases[{index}] must be an object")
        _validate_case(case, index=index, forbidden=forbidden)
        if case["case_id"] in identifiers:
            raise ExternalReuseBenchmarkError(f"duplicate case_id: {case['case_id']}")
        identifiers.add(case["case_id"])
    suite["_package_search_oracles"] = _load_package_oracles(
        suite_path.with_name("package-search-oracles-v1.json"), cases
    )
    suite["_suite_path"] = str(suite_path)
    return suite


def evaluate_external_reuse_case(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    deterministic: bool,
    resource_snapshot_digest: str | None = None,
    package_oracle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score routing, reuse discovery, coverage receipts, and safety."""

    expected = case["expected"]
    checks: list[dict[str, Any]] = []
    for field in ("mode", "status", "primary_intent"):
        _check(
            checks,
            field,
            result.get(field) == expected[field],
            expected[field],
            result.get(field),
        )
    candidates = _candidate_ids(result)
    for identifier in expected.get("required_candidate_ids", ()):
        _check(
            checks,
            f"required_candidate:{identifier}",
            str(identifier) in candidates,
            True,
            str(identifier) in candidates,
        )
    for identifier in expected.get("forbidden_candidate_ids", ()):
        _check(
            checks,
            f"forbidden_candidate:{identifier}",
            str(identifier) not in candidates,
            False,
            str(identifier) in candidates,
        )

    scan = result.get("resource_scan")
    scan = scan if isinstance(scan, Mapping) else {}
    surfaces = scan.get("surfaces")
    surfaces = surfaces if isinstance(surfaces, Mapping) else {}
    required_surfaces = expected.get(
        "required_resource_surfaces", DEFAULT_REQUIRED_SURFACES
    )
    for surface in required_surfaces:
        row = surfaces.get(surface)
        considered = isinstance(row, Mapping) and row.get("considered") is True
        _check(checks, f"resource_surface:{surface}", considered, True, row)
    _check(
        checks,
        "coverage_receipt",
        scan.get("coverage_receipt") is not None,
        "present",
        scan.get("coverage_receipt"),
    )
    if resource_snapshot_digest is not None:
        _check(
            checks,
            "resource_snapshot_digest",
            scan.get("resource_snapshot_digest") == resource_snapshot_digest,
            resource_snapshot_digest,
            scan.get("resource_snapshot_digest"),
        )
    _check(
        checks,
        "reuse_first",
        result.get("reuse_first") is True,
        True,
        result.get("reuse_first"),
    )
    _check(
        checks,
        "custom_work_deferred",
        result.get("custom_implementation_allowed") is False,
        False,
        result.get("custom_implementation_allowed"),
    )
    dispositions = scan.get("external_framework_dispositions")
    dispositions = dispositions if isinstance(dispositions, Mapping) else {}
    for framework, allowed in expected.get(
        "external_framework_dispositions", {}
    ).items():
        actual = dispositions.get(framework)
        _check(
            checks,
            f"framework_disposition:{framework}",
            actual in allowed,
            list(allowed),
            actual,
        )
    for field, wanted in _SAFETY.items():
        _check(
            checks,
            f"safety:{field}",
            result.get(field) == wanted,
            wanted,
            result.get(field),
        )
    _check(checks, "deterministic_repeat", deterministic, True, deterministic)
    if package_oracle is not None:
        checks.extend(_package_receipt_checks(result, package_oracle))
    passed = sum(bool(row["passed"]) for row in checks)
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "passed": passed == len(checks),
        "checks_passed": passed,
        "checks_total": len(checks),
        "score": passed / len(checks),
        "checks": checks,
        "observed": {
            "mode": result.get("mode"),
            "status": result.get("status"),
            "candidate_ids": sorted(candidates),
            "resource_scan_present": bool(scan),
        },
        "planner_result_digest": _digest(result),
        "expert_oracle": case.get("expert_oracle"),
        "package_oracle_applied": package_oracle is not None,
    }


def _package_receipt_checks(
    result: Mapping[str, Any], package_oracle: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Evaluate package discovery without exposing oracle values to planning."""
    checks: list[dict[str, Any]] = []
    receipt = result.get("package_search_receipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    search = receipt.get("search_result")
    search = search if isinstance(search, Mapping) else {}
    candidates = search.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    ranked = [
        str(row.get("package")) for row in candidates[:10] if isinstance(row, Mapping)
    ]
    acceptable = {
        *(
            str(value)
            for value in package_oracle.get("acceptable_primary_packages", ())
        ),
        *(
            str(value)
            for value in package_oracle.get("acceptable_secondary_packages", ())
        ),
    }
    snapshot = search.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    _check(checks, "package_receipt:present", bool(receipt), True, bool(receipt))
    _check(
        checks,
        "package_receipt:relevance",
        receipt.get("relevance_disposition") == "selected",
        "selected",
        receipt.get("relevance_disposition"),
    )
    _check(
        checks,
        "package_receipt:search_status",
        receipt.get("search_status") in {"ok", "ambiguous"},
        ["ok", "ambiguous"],
        receipt.get("search_status"),
    )
    _check(
        checks,
        "package_receipt:index_pinned",
        bool(snapshot.get("index_digest")),
        "non-empty index digest",
        snapshot.get("index_digest"),
    )
    _check(
        checks,
        "package_receipt:family_recall_at_10",
        bool(acceptable.intersection(ranked)),
        sorted(acceptable),
        ranked,
    )
    return checks


def run_package_search_extension_benchmark(
    suite: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Run the separate eight-case package-discovery extension planning-only."""
    cases = suite.get("cases", ())
    oracle_map = {row["case_id"]: row for row in suite.get("oracles", ())}
    if len(cases) != 8 or len(oracle_map) != 8:
        raise ExternalReuseBenchmarkError("validated package extension is required")
    root = Path(repo_root).resolve() if repo_root else require_repository_root()
    rows = []
    for case in cases:
        kwargs = {
            "references": case.get("references", ()),
            "desired_inputs": case.get("desired_inputs", ()),
            "desired_outputs": case.get("desired_outputs", ()),
            "scope": "scientific",
            "repo_root": root,
        }
        first = run_planner_request(case["query"], **kwargs)
        second = run_planner_request(case["query"], **kwargs)
        checks = _package_receipt_checks(first, oracle_map[case["case_id"]])
        _check(
            checks,
            "deterministic_repeat",
            _digest(first) == _digest(second),
            True,
            _digest(first) == _digest(second),
        )
        _check(
            checks,
            "execution_not_performed",
            not first.get("execution_allowed", False)
            and not first.get("performed_actions", ()),
            True,
            first.get("performed_actions"),
        )
        passed = sum(bool(check["passed"]) for check in checks)
        rows.append(
            {
                "case_id": case["case_id"],
                "family": case["family"],
                "passed": passed == len(checks),
                "checks_passed": passed,
                "checks_total": len(checks),
                "checks": checks,
            }
        )
    return {
        "schema_version": "lunar.planner.blind-external-reuse-package-extension-result/v1",
        "benchmark_id": suite["benchmark_id"],
        "case_count": len(rows),
        "cases_passed": sum(row["passed"] for row in rows),
        "passed": all(row["passed"] for row in rows),
        "case_results": rows,
    }


def run_external_reuse_benchmark(
    suite: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Run all blind cases twice against the route-only planner."""

    cases = suite.get("cases", ())
    if len(cases) != 20:
        raise ExternalReuseBenchmarkError("benchmark requires exactly 20 cases")
    root = Path(repo_root).resolve() if repo_root else require_repository_root()
    index = load_surface_index(repo_root=root)
    rows: list[dict[str, Any]] = []
    for case in cases:
        kwargs = {
            "references": case.get("references", ()),
            "desired_inputs": case.get("desired_inputs", ()),
            "desired_outputs": case.get("desired_outputs", ()),
            "scope": "scientific",
            "repo_root": root,
        }
        if run_planner_request is _DEFAULT_PLANNER:

            def call(text: str, **values: Any) -> dict[str, Any]:
                """Call."""
                return run_planner_request_with_test_surface(
                    text, index, repo_root=root, **values
                )

            first = drive_route_only_quality_protocol(
                run_planner_request_with_test_surface(case["query"], index, **kwargs),
                call_planner=call,
            )
            second = drive_route_only_quality_protocol(
                run_planner_request_with_test_surface(case["query"], index, **kwargs),
                call_planner=call,
            )
        else:  # explicit evaluator seam used by unit tests
            first = run_planner_request(case["query"], **kwargs)
            second = run_planner_request(case["query"], **kwargs)
        rows.append(
            evaluate_external_reuse_case(
                case,
                first,
                deterministic=_digest(first) == _digest(second),
                resource_snapshot_digest=suite["resource_snapshot"]["digest"],
                package_oracle=(suite.get("_package_search_oracles") or {}).get(
                    case["case_id"]
                ),
            )
        )
    total = sum(row["checks_total"] for row in rows)
    passed = sum(row["checks_passed"] for row in rows)
    payload = {
        key: value for key, value in suite.items() if not str(key).startswith("_")
    }
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "benchmark_id": suite["benchmark_id"],
        "suite_digest": _digest(payload),
        "case_count": len(rows),
        "cases_passed": sum(bool(row["passed"]) for row in rows),
        "checks_passed": passed,
        "checks_total": total,
        "micro_score": passed / total,
        "passed": all(bool(row["passed"]) for row in rows),
        "blind_policy_verified": True,
        "execution_performed": False,
        "case_results": rows,
    }
    result["result_digest"] = _digest(result)
    return result


def render_external_reuse_markdown(result: Mapping[str, Any]) -> str:
    """Render a stable Markdown report with coverage failures visible."""

    lines = [
        f"# Blind external-reuse planner benchmark: {result['benchmark_id']}",
        "",
        f"- Cases: {result['cases_passed']}/{result['case_count']} strict passes",
        f"- Checks: {result['checks_passed']}/{result['checks_total']}",
        f"- Micro score: {float(result['micro_score']):.4f}",
        "- Query leakage check: passed",
        "- Workflow/package execution: none",
        "",
        "| Case | Category | Score | Route | Resource receipt |",
        "|---|---|---:|---|---:|",
    ]
    for row in result["case_results"]:
        observed = row["observed"]
        lines.append(
            f"| `{row['case_id']}` | {row['category']} | {row['score']:.4f} | "
            f"`{observed['mode']}/{observed['status']}` | "
            f"{'yes' if observed['resource_scan_present'] else 'no'} |"
        )
    lines.extend(["", "## Observed candidates", ""])
    for row in result["case_results"]:
        candidates = row["observed"]["candidate_ids"]
        rendered = ", ".join(f"`{item}`" for item in candidates) or "None."
        lines.append(f"- `{row['case_id']}`: {rendered}")
    lines.extend(["", "## Failed checks", ""])
    failures = [
        (row["case_id"], check)
        for row in result["case_results"]
        for check in row["checks"]
        if not check["passed"]
    ]
    for case_id, check in failures:
        lines.append(
            f"- `{case_id}` / `{check['check_id']}`: expected "
            f"`{json.dumps(check['expected'], sort_keys=True)}`, observed "
            f"`{json.dumps(check['actual'], sort_keys=True)}`."
        )
    lines.extend(
        [
            "",
            "A missing resource receipt is a planner observability failure: hidden search is not credited.",
            "Package names in the oracle are never supplied to the planner query.",
            "",
        ]
    )
    return "\n".join(lines)


def write_external_reuse_benchmark(
    result: Mapping[str, Any], output_directory: str | Path
) -> dict[str, str]:
    """Write deterministic JSON and Markdown result artifacts."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "benchmark-result.json"
    markdown_path = output / "benchmark-report.md"
    json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_external_reuse_markdown(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _main(argv: Sequence[str] | None = None) -> int:
    """Main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    result = run_external_reuse_benchmark(
        load_external_reuse_benchmark(args.suite, repo_root=args.repo_root),
        repo_root=args.repo_root,
    )
    if args.output_dir:
        write_external_reuse_benchmark(result, args.output_dir)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if args.require_pass and not result["passed"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = [
    "ExternalReuseBenchmarkError",
    "evaluate_external_reuse_case",
    "load_external_reuse_benchmark",
    "load_package_search_extension",
    "run_package_search_extension_benchmark",
    "render_external_reuse_markdown",
    "run_external_reuse_benchmark",
    "write_external_reuse_benchmark",
]
