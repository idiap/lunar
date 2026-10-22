# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Strict, planning-only contracts shared by planner services.

JSON Schema owns portable document shape.  This module supplies the semantic
checks that JSON Schema cannot express: duplicate-key-safe YAML loading,
catalog owner resolution, producer/consumer wiring, graph reachability, and
the non-executing authority boundary.  It never imports a workflow runtime or
invokes a referenced skill.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import resource_path
from .ports import skill_descriptors

PROFILE_SCHEMA_VERSION = "lunar.planner.profile/v1"
PLANNING_STATUS = "planning_only_non_executing"
PLANNING_RUNTIME_OWNERS = frozenset(
    {
        "lunar_planner.ports.resolve_intent",
        "lunar_planner.ports.build_invocation_plan",
        "lunar_planner.staged_routing.plan_stages",
    }
)
SCHEMA_VERSION_TO_FILE = {
    "lunar.planner.request/v1": "planner-request-v1.schema.json",
    "lunar.planner.route/v1": "planner-route-v1.schema.json",
    "lunar.planner.run-manifest/v1": "planner-run-manifest-v1.schema.json",
    "lunar.planner.plan/v1": "planner-plan-v1.schema.json",
    "lunar.planner.todo-event/v1": "planner-todo-event-v1.schema.json",
    "lunar.planner.acceptance/v1": "planner-acceptance-v1.schema.json",
    "lunar.planner.provenance-reconciliation/v1": "planner-provenance-reconciliation-v1.schema.json",
    "lunar.planner.w3c-provenance-export/v1": "planner-w3c-provenance-export-v1.schema.json",
    "lunar.planner.next-step-guidance/v1": "planner-next-step-guidance-v1.schema.json",
    "lunar.planner.delivery-package/v1": "planner-delivery-package-v1.schema.json",
    "lunar.planner.external-source-plan/v1": "planner-external-source-plan-v1.schema.json",
    "lunar.planner.dialogue-state/v1": "planner-dialogue-state-v1.schema.json",
    "lunar.planner.requirement-ledger/v1": "planner-requirement-ledger-v1.schema.json",
    "lunar.planner.workflow-draft/v1": "planner-workflow-draft-v1.schema.json",
    "lunar.planner.workflow-instantiation/v1": "planner-workflow-instantiation-v1.schema.json",
    "lunar.planner.proposed-skill-test-plan/v1": "planner-proposed-skill-test-plan-v1.schema.json",
    "lunar.planner.workflow-refinement-cycle/v1": "planner-workflow-refinement-cycle-v1.schema.json",
    "lunar.planner.post-plan-evidence-verification/v1": "planner-post-plan-evidence-verification-v1.schema.json",
    "lunar.planner.answer-control-readiness/v1": "planner-answer-control-readiness-v1.schema.json",
    "lunar.planner.answer-trust-assessment/v1": "planner-answer-trust-assessment-v1.schema.json",
    "lunar.planner.claim-trust-assessment/v1": "planner-claim-trust-assessment-v1.schema.json",
    "lunar.planner.generative-transformation-receipt/v1": "planner-generative-transformation-receipt-v1.schema.json",
    "lunar.planner.workflow-comparator-disposition/v1": "planner-workflow-comparator-disposition-v1.schema.json",
    "lunar.planner.workflow-workload-inventory/v1": "planner-workflow-workload-inventory-v1.schema.json",
    "lunar.planner.workflow-effort-estimate/v1": "planner-workflow-effort-estimate-v1.schema.json",
    "lunar.planner.workflow-effort-assessment/v1": "planner-workflow-effort-assessment-v1.schema.json",
    "lunar.planner.workflow-effort-card/v1": "planner-workflow-effort-card-v1.schema.json",
    "lunar.planner.workflow-effort-invalidation/v1": "planner-workflow-effort-invalidation-v1.schema.json",
    "lunar.planner.workflow-resource-estimate/v1": "planner-workflow-resource-estimate-v1.schema.json",
    "lunar.planner.workflow-resource-usage/v1": "planner-workflow-resource-usage-v1.schema.json",
    "lunar.planner.workflow-cost-reconciliation/v1": "planner-workflow-cost-reconciliation-v1.schema.json",
    "lunar.planner.workflow-economics-report/v1": "planner-workflow-economics-report-v1.schema.json",
    "lunar.planner.workflow-effort-calibration/v1": "planner-workflow-effort-calibration-v1.schema.json",
    "lunar.planner.workflow-resource-profile/v1": "planner-workflow-resource-profile-v1.schema.json",
    "lunar.planner.price-book/v1": "planner-price-book-v1.schema.json",
    "lunar.planner.report-workflow-inheritance/v1": "planner-report-workflow-inheritance-v1.schema.json",
    "lunar.planner.contextual-outcome-quality-contract/v1": "planner-contextual-outcome-quality-contract-v1.schema.json",
    "lunar.planner.route-delivery-quality-plan/v1": "planner-route-delivery-quality-plan-v1.schema.json",
    "lunar.planner.quality-plan-review/v1": "planner-quality-plan-review-v1.schema.json",
    "lunar.planner.contextual-quality-criterion/v1": "planner-contextual-quality-criterion-v1.schema.json",
    "lunar.planner.quality-assessment/v1": "planner-quality-assessment-v1.schema.json",
    "lunar.planner.final-delivery-decision/v1": "planner-final-delivery-decision-v1.schema.json",
    "bioagents.provider-family/v1": "provider-family-v1.schema.json",
    "bioagents.provider-preflight/v1": "provider-preflight-v1.schema.json",
    "bioagents.provider-result/v1": "provider-result-v1.schema.json",
    "bioagents.provider-error/v1": "provider-error-v1.schema.json",
    "bioagents.wrapper-portfolio/v1": "wrapper-portfolio-v1.schema.json",
    PROFILE_SCHEMA_VERSION: "planner-profile-v1.schema.json",
}
NAMESPACED_VERSION = re.compile(r"^lunar\.planner\.[a-z][a-z0-9-]*/v[1-9][0-9]*$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
QUALITY_ROLES = frozenset(
    {
        "user_request",
        "criterion_synthesis",
        "criterion_review",
        "delivery",
        "artifact_assessment",
        "render",
        "final_delivery",
    }
)
INTERNAL_QUALITY_ROLES = QUALITY_ROLES - {"user_request", "delivery", "final_delivery"}
QUALITY_LIFECYCLES = frozenset({"provisional", "frozen", "superseded", "withdrawn"})
QUALITY_VERDICTS = frozenset({"pass", "fail", "inconclusive", "not_applicable"})
_GENERIC_QUALITY = re.compile(
    r"^(?:be |is |must be )?(?:accurate|complete|correct|high quality|satisfy the request)[.!]?$",
    flags=re.IGNORECASE,
)
_TAUTOLOGICAL_QUALITY = re.compile(
    r"\b(?:explicitly and faithfully addresses|satisf(?:y|ies) (?:the|this) (?:request|obligation)|fully addresses)\b",
    flags=re.IGNORECASE,
)


def canonical_digest(value: Mapping[str, Any]) -> str:
    """Return the stable digest of a contract, excluding its digest field."""

    payload = {key: item for key, item in value.items() if key != "digest"}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal_quality_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy and content-address a quality document using canonical JSON v1."""

    result = dict(value)
    result["digest"] = canonical_digest(result)
    return result


def validate_quality_lineage_chain(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Reject cycles, mixed roots, and final-role escalation across receipts."""

    errors: list[str] = []
    by_digest = {
        str(row.get("digest")): row
        for row in documents
        if isinstance(row.get("digest"), str)
    }
    roots = {str(row.get("root_interaction_id")) for row in documents}
    if len(roots) > 1:
        errors.append("quality lineage mixes root interactions")
    for digest, row in by_digest.items():
        parent = row.get("parent_digest")
        if parent == digest:
            errors.append("quality lineage contains a self-cycle")
        visited = {digest}
        while parent in by_digest:
            if parent in visited:
                errors.append("quality lineage contains a cycle")
                break
            visited.add(str(parent))
            parent = by_digest[str(parent)].get("parent_digest")
        if (
            row.get("operation_role") == "final_delivery"
            and row.get("schema_version") != "lunar.planner.final-delivery-decision/v1"
        ):
            errors.append(
                "only a final-delivery-decision contract may use final_delivery role"
            )
    return tuple(dict.fromkeys(errors))


class PlannerContractError(ValueError):
    """Raised when planner input is ambiguous or violates its contract."""


@dataclass(frozen=True)
class PlannerValidationReport:
    """Deterministic semantic validation result."""

    errors: tuple[str, ...]
    order: tuple[str, ...] = ()
    producers: tuple[tuple[str, str], ...] = ()

    @property
    def valid(self) -> bool:
        """Return true only when all contract checks passed."""

        return not self.errors


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader which rejects duplicate and merge keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    """Construct unique mapping."""
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge" or key_node.value == "<<":
            raise PlannerContractError(
                "YAML merge keys are forbidden in planner contracts"
            )
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise PlannerContractError(
                "planner YAML mapping keys must be scalar"
            ) from exc
        if duplicate:
            raise PlannerContractError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _schema_root() -> Path:
    """Schema root."""
    return resource_path("schemas", "planner-request-v1.schema.json").parent


def load_planner_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML mapping with no object construction, merges, or duplicates."""

    source = Path(path)
    try:
        value = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except PlannerContractError:
        raise
    except (OSError, yaml.YAMLError) as exc:
        raise PlannerContractError(
            f"cannot parse planner YAML {source}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise PlannerContractError("planner YAML root must be a mapping")
    return value


def load_schema(schema: str) -> dict[str, Any]:
    """Load one checked-in planner schema by version or file name."""

    filename = SCHEMA_VERSION_TO_FILE.get(schema, schema)
    if filename not in SCHEMA_VERSION_TO_FILE.values():
        raise PlannerContractError(f"unknown planner schema: {schema}")
    path = _schema_root() / filename
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlannerContractError(
            f"cannot load planner schema {filename}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise PlannerContractError(f"planner schema is not a mapping: {filename}")
    return value


def _external_schema(ref: str) -> dict[str, Any]:
    """Resolve only the finite set of repository-owned schema identifiers."""

    filename = ref.rsplit("/", 1)[-1]
    if filename == "subworkflow-manifest-v1.json":
        path = _schema_root() / "subworkflow-manifest-v1.schema.json"
    else:
        path = _schema_root() / filename
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlannerContractError(
            f"cannot resolve schema reference {ref}: {exc}"
        ) from exc
    declared_id = value.get("$id") if isinstance(value, dict) else None
    if not isinstance(declared_id, str) or not (
        declared_id == ref or declared_id.rsplit("/", 1)[-1] == ref
    ):
        raise PlannerContractError(
            f"schema reference does not resolve to its declared $id: {ref}"
        )
    return value


def _json_type_matches(value: Any, expected: str) -> bool:
    """JSON type matches."""
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _resolve_pointer(root: Mapping[str, Any], pointer: str) -> Mapping[str, Any]:
    """Resolve pointer."""
    value: Any = root
    for token in pointer.removeprefix("#/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or token not in value:
            raise PlannerContractError(f"unresolved local schema reference: {pointer}")
        value = value[token]
    if not isinstance(value, Mapping):
        raise PlannerContractError(f"schema reference is not an object: {pointer}")
    return value


def _validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[str]:
    """Validate the JSON-Schema vocabulary used by repository contracts."""

    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str):
            return [f"{path}: $ref must be a string"]
        if ref.startswith("#/"):
            return _validate_schema_value(
                value, _resolve_pointer(root, ref), root, path
            )
        external = _external_schema(ref)
        return _validate_schema_value(value, external, external, path)
    if "oneOf" in schema:
        matches = [
            branch
            for branch in schema["oneOf"]
            if not _validate_schema_value(value, branch, root, path)
        ]
        return (
            []
            if len(matches) == 1
            else [f"{path}: must match exactly one allowed contract"]
        )

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")
    expected = schema.get("type")
    if expected is not None:
        choices = [expected] if isinstance(expected, str) else expected
        if not isinstance(choices, list) or not any(
            _json_type_matches(value, item) for item in choices
        ):
            return [f"{path}: has invalid type"]

    if isinstance(value, Mapping):
        for required in schema.get("required", ()):
            if required not in value:
                errors.append(f"{path}: missing required field {required}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                errors.extend(
                    _validate_schema_value(
                        child, properties[key], root, f"{path}.{key}"
                    )
                )
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field {key}")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                errors.extend(
                    _validate_schema_value(
                        child, schema["additionalProperties"], root, f"{path}.{key}"
                    )
                )
        minimum_properties = schema.get("minProperties")
        if isinstance(minimum_properties, int) and len(value) < minimum_properties:
            errors.append(f"{path}: must contain at least {minimum_properties} fields")
    elif isinstance(value, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{path}: must contain at least {minimum_items} items")
        if schema.get("uniqueItems"):
            canonical = [
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(canonical) != len(set(canonical)):
                errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(
                    _validate_schema_value(item, item_schema, root, f"{path}[{index}]")
                )
    elif isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{path}: must not be empty")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path}: does not match required pattern")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: must be at least {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: must be at most {maximum}")
    return errors


def _strings(value: Any, label: str, errors: list[str]) -> list[str]:
    """Strings."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        errors.append(f"{label} must be a list of non-empty strings")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{label} must contain unique values")
    return list(value)


def _mapping(value: Any, label: str, errors: list[str]) -> Mapping[str, Any]:
    """Mapping."""
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be a mapping")
        return {}
    return value


def _topological_order(
    ids: Sequence[str], dependencies: Mapping[str, Sequence[str]]
) -> tuple[str, ...]:
    """Topological order."""
    indegree = {stage_id: 0 for stage_id in ids}
    consumers: dict[str, list[str]] = defaultdict(list)
    for stage_id in ids:
        for dependency in dependencies.get(stage_id, ()):
            if dependency in indegree:
                indegree[stage_id] += 1
                consumers[dependency].append(stage_id)
    queue = deque(stage_id for stage_id in ids if indegree[stage_id] == 0)
    order: list[str] = []
    while queue:
        stage_id = queue.popleft()
        order.append(stage_id)
        for consumer in consumers[stage_id]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
    return tuple(order)


def _ancestors(stage_id: str, dependencies: Mapping[str, Sequence[str]]) -> set[str]:
    """Ancestors."""
    result: set[str] = set()
    pending = list(dependencies.get(stage_id, ()))
    while pending:
        candidate = pending.pop()
        if candidate in result:
            continue
        result.add(candidate)
        pending.extend(dependencies.get(candidate, ()))
    return result


def _owner_identities(repo_root: Path) -> set[tuple[str, str]]:
    """Owner identities."""
    return {
        (str(descriptor["scope"]), str(descriptor["name"]))
        for descriptor in skill_descriptors(("package", "planner"))
    }


def validate_profile(
    profile: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> PlannerValidationReport:
    """Validate one explicit planner profile without executing its route."""

    errors: list[str] = []
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {PROFILE_SCHEMA_VERSION}")
    if profile.get("kind") != "planner_profile":
        errors.append("kind must be planner_profile")
    if profile.get("status") != PLANNING_STATUS:
        errors.append(f"status must be {PLANNING_STATUS}")
    if profile.get("catalog_scope") != "selected_package_skills_and_workflows":
        errors.append("catalog_scope must cover all Lunar skills and workflows")
    root_inputs = set(_strings(profile.get("root_inputs"), "root_inputs", errors))
    raw_stages = profile.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        errors.append("stages must be a non-empty list")
        return PlannerValidationReport(tuple(errors))

    stages: dict[str, Mapping[str, Any]] = {}
    stage_ids: list[str] = []
    dependencies: dict[str, list[str]] = {}
    producer_lists: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    try:
        admitted = _owner_identities(
            Path(repo_root).resolve() if repo_root else Path.cwd()
        )
    except Exception as exc:  # preserve a planner-specific error boundary
        errors.append(f"cannot resolve Lunar owners: {exc}")
        admitted = set()

    for index, raw_stage in enumerate(raw_stages):
        stage = _mapping(raw_stage, f"stages[{index}]", errors)
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"stages[{index}].id must be a non-empty string")
            continue
        if stage_id in stages:
            errors.append(f"duplicate stage id: {stage_id}")
            continue
        stages[stage_id] = stage
        stage_ids.append(stage_id)
        scope = stage.get("owner_scope", "package")
        owner = stage.get("owner_skill")
        if scope not in {"package", "planner"}:
            errors.append(f"stage {stage_id} has invalid owner_scope: {scope!r}")
        if not isinstance(owner, str) or (scope, owner) not in admitted:
            errors.append(f"stage {stage_id} owner does not resolve: {scope}:{owner}")
        runtime_owner = stage.get("runtime_owner")
        if runtime_owner is not None and runtime_owner not in PLANNING_RUNTIME_OWNERS:
            errors.append(
                f"stage {stage_id} runtime_owner is not planning-only: {runtime_owner}"
            )
        _strings(stage.get("inputs"), f"stage {stage_id} inputs", errors)
        outputs = _strings(stage.get("outputs"), f"stage {stage_id} outputs", errors)
        deps = _strings(
            stage.get("dependencies"), f"stage {stage_id} dependencies", errors
        )
        dependencies[stage_id] = deps
        for dependency in deps:
            if dependency not in seen:
                errors.append(
                    f"stage {stage_id} dependency is not an earlier stage: {dependency}"
                )
        for output in outputs:
            producer_lists[output].append(stage_id)
            if output in root_inputs:
                errors.append(f"stage {stage_id} output shadows root input: {output}")
        seen.add(stage_id)

    for output, owners in sorted(producer_lists.items()):
        if len(owners) != 1:
            errors.append(
                f"output {output} must have exactly one producer; found {owners}"
            )

    order = _topological_order(stage_ids, dependencies)
    if len(order) != len(stage_ids):
        errors.append("stage dependency graph must be acyclic")

    for stage_id, stage in stages.items():
        available = root_inputs.copy()
        for ancestor in _ancestors(stage_id, dependencies):
            ancestor_stage = stages.get(ancestor)
            if ancestor_stage:
                available.update(
                    item
                    for item in ancestor_stage.get("outputs", ())
                    if isinstance(item, str)
                )
        for input_name in stage.get("inputs", ()):
            if isinstance(input_name, str) and input_name not in available:
                if input_name in producer_lists:
                    errors.append(
                        f"stage {stage_id} input {input_name} is not produced by a dependency"
                    )
                else:
                    errors.append(f"stage {stage_id} has implicit input: {input_name}")

    release = profile.get("release_stage_id")
    if not isinstance(release, str) or release not in stages:
        errors.append("release_stage_id must name a stage")
    else:
        ancestors = _ancestors(release, dependencies)
        unreachable = sorted(set(stage_ids) - ancestors - {release})
        if unreachable:
            errors.append(f"stages do not reach release stage {release}: {unreachable}")
        consumers = {
            dependency for deps in dependencies.values() for dependency in deps
        }
        terminals = sorted(set(stage_ids) - consumers)
        if terminals != [release]:
            errors.append(f"release stage must be the only terminal; found {terminals}")

    return PlannerValidationReport(
        errors=tuple(dict.fromkeys(errors)),
        order=order,
        producers=tuple(
            (output, owners[0])
            for output, owners in sorted(producer_lists.items())
            if len(owners) == 1
        ),
    )


_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "lunar.planner.request/v1": (
        "request_id",
        "objective",
        "inputs",
        "constraints",
        "authority",
    ),
    "lunar.planner.route/v1": (
        "route_id",
        "request_id",
        "profile",
        "invocation_plan",
        "authority",
    ),
    "lunar.planner.run-manifest/v1": (
        "run_id",
        "request_id",
        "route_id",
        "status",
        "authority",
        "artifacts",
        "created_at",
    ),
    "lunar.planner.plan/v1": (
        "plan_id",
        "version",
        "request_id",
        "digest",
        "previous_digest",
        "invocation_plan",
        "components",
        "todos",
        "authority",
    ),
    "lunar.planner.todo-event/v1": (
        "event_id",
        "run_id",
        "todo_id",
        "operation",
        "sequence",
        "timestamp",
        "idempotency_key",
        "payload",
    ),
    "lunar.planner.acceptance/v1": (
        "acceptance_id",
        "run_id",
        "plan_id",
        "plan_digest",
        "decision",
        "actor",
        "timestamp",
        "authority",
    ),
    "lunar.planner.provenance-reconciliation/v1": (
        "components",
        "summary",
        "boundary",
        "prospective_digest",
        "observed_digest",
        "reconciliation_digest",
    ),
    "lunar.planner.w3c-provenance-export/v1": (
        "format",
        "media_type",
        "standard",
        "prospective_is_observation",
        "document",
        "digest",
    ),
    "lunar.planner.next-step-guidance/v1": (
        "closure_state",
        "disposition",
        "reason",
        "source_state_digest",
        "skill_route",
        "suggestions",
        "digest",
    ),
    "lunar.planner.delivery-package/v1": (
        "status",
        "package_id",
        "archive_path",
        "archive_digest",
        "manifest",
        "requirement",
        "skill_route",
        "digest",
    ),
    "lunar.planner.external-source-plan/v1": (
        "packet_id",
        "activation",
        "original_request",
        "request_digest",
        "problem_digest",
        "snapshot_digests",
        "data_needs",
        "candidate_matrix",
        "coverage_receipts",
        "query_plans",
        "acquisition_dag",
        "handoffs",
        "sufficiency",
        "zero_io",
    ),
    "lunar.planner.dialogue-state/v1": (
        "dialogue_id",
        "turn_index",
        "snapshot_digest",
        "turns",
        "active_goal",
        "requirement_ledger",
        "workflow_draft",
        "planning_phase",
        "digest",
    ),
    "lunar.planner.requirement-ledger/v1": ("requirements", "digest"),
    "lunar.planner.workflow-draft/v1": (
        "dialogue_id",
        "turn_index",
        "status",
        "nodes",
        "edges",
        "unresolved_requirement_ids",
        "route_only",
        "digest",
    ),
    "lunar.planner.workflow-instantiation/v1": (
        "dialogue_id",
        "turn_index",
        "status",
        "requirement_coverage_complete",
        "nodes",
        "edges",
        "blockers",
        "route_only",
        "execution_authorized",
        "digest",
    ),
    "lunar.planner.proposed-skill-test-plan/v1": (
        "test_plan_id",
        "gap_id",
        "requirement_id",
        "proposed_component_class",
        "implementation_authorized",
        "test_files_written",
        "test_cases",
        "digest",
    ),
    "lunar.planner.workflow-refinement-cycle/v1": (
        "dialogue_id",
        "iteration",
        "max_iterations",
        "status",
        "input_instantiation_digest",
        "pre_execution_ready",
        "execution_validated",
        "findings",
        "repair_actions",
        "workflow_test_specifications",
        "required_test_ids",
        "verified_test_ids",
        "release_gate",
        "route_only",
        "planner_executed_workflow",
        "digest",
    ),
    "lunar.planner.post-plan-evidence-verification/v1": (
        "overlay_id",
        "base_plan_digest",
        "computed_base_plan_digest",
        "base_plan_digest_preserved",
        "status",
        "claim_atoms",
        "evidence_atoms",
        "computation_atoms",
        "derivation_edges",
        "authority_profiles",
        "verification_obligations",
        "grounding_matrix",
        "findings",
        "proposed_repairs",
        "summary_event",
        "route_only",
        "digest",
    ),
    "lunar.planner.answer-control-readiness/v1": (
        "polarity",
        "base_plan_digest",
        "verification_digest",
        "policy_version",
        "policy_digest",
        "attainable_control_band",
        "realized_trust_score",
        "claims_considered",
        "required_receipts",
        "findings",
        "mutates_initial_plan",
        "digest",
    ),
    "lunar.planner.answer-trust-assessment/v1": (
        "assessment_id",
        "polarity",
        "answer_digest",
        "base_plan_digest",
        "evidence_manifest_digest",
        "provenance_digest",
        "policy_version",
        "policy_digest",
        "status",
        "score",
        "score_interval",
        "band",
        "denominator_frozen",
        "claim_assessments",
        "evidence_atoms",
        "derivation_edges",
        "exemptions",
        "diagnostics",
        "binding",
        "blocking_reasons",
        "digest",
    ),
    "lunar.planner.claim-trust-assessment/v1": (
        "claim_id",
        "claim_class",
        "component_ids",
        "release_critical",
        "materiality_weight",
        "decision_risk_weight",
        "dimensions",
        "score",
        "score_interval",
        "gates",
        "caps",
        "evidence_ids",
        "grounded",
        "memory_only",
        "citation_lineage_mismatch",
        "unsupported_generative_additions",
        "preservation_failures",
        "remediation",
    ),
    "lunar.planner.generative-transformation-receipt/v1": (
        "receipt_id",
        "observed_only",
        "operation_id",
        "provider",
        "provider_version",
        "input_digests",
        "output_digest",
        "allowed_evidence_ids",
        "generated_ancestor_ids",
        "protected_field_checks",
        "missing_fields",
        "lossy_fields",
        "abstained",
        "violations",
        "independent_verifier",
        "verification_status",
        "provenance_digest",
        "digest",
    ),
    "lunar.planner.workflow-comparator-disposition/v1": (
        "status",
        "workflow_digest",
        "workload_manifest_digest",
        "missing_dimensions",
        "mismatched_dimensions",
        "experienced_practitioner",
        "ordinary_non_agentic_tools",
        "digest",
    ),
    "lunar.planner.workflow-workload-inventory/v1": (
        "plan_digest",
        "work_units",
        "unresolved_drivers",
        "duplicate_operations",
        "estimable",
        "digest",
    ),
    "lunar.planner.workflow-effort-estimate/v1": (
        "status",
        "evidence_state",
        "comparator_disposition",
        "workload_inventory_digest",
        "headline",
        "components",
        "blockers",
        "digest",
    ),
    "lunar.planner.workflow-effort-assessment/v1": (
        "status",
        "evidence_state",
        "comparator_disposition",
        "workload_inventory_digest",
        "headline",
        "components",
        "blockers",
        "digest",
    ),
    "lunar.planner.workflow-effort-card/v1": (
        "estimate_digest",
        "status",
        "evidence_state",
        "headline",
        "clocks",
        "top_sensitivity_drivers",
        "component_count",
        "caveat",
        "digest",
    ),
    "lunar.planner.workflow-effort-invalidation/v1": (
        "estimate_digest",
        "changed_artifact_digests",
        "invalidated_work_unit_ids",
        "retained_work_unit_ids",
        "headline_invalidated",
        "digest",
    ),
    "lunar.planner.workflow-resource-estimate/v1": (
        "plan_digest",
        "seed",
        "resource_profile_digest",
        "lines",
        "assumptions",
        "estimate_digest",
    ),
    "lunar.planner.workflow-resource-usage/v1": (
        "polarity",
        "plan_digest",
        "status",
        "observed_attempt_coverage",
        "aggregate",
        "budget_treated_as_usage",
        "digest",
    ),
    "lunar.planner.workflow-cost-reconciliation/v1": (
        "polarity",
        "resource_usage_digest",
        "price_book_digest",
        "reservation_digest",
        "invoice_digest",
        "status",
        "currency",
        "priced_total_nano",
        "priced_lines",
        "unpriced_lines",
        "cost_line_coverage",
        "missing_price_as_zero",
        "digest",
    ),
    "lunar.planner.workflow-economics-report/v1": (
        "status",
        "rollout",
        "effort",
        "resource",
        "cost",
        "labor_value",
        "scalar_roi",
        "scientific_release_effect",
        "interpretation",
        "digest",
    ),
    "lunar.planner.workflow-effort-calibration/v1": (
        "corpus_id",
        "corpus_digest",
        "frozen",
        "blinded",
        "partition",
        "estimate_count",
        "review_count",
        "thresholds",
        "metrics",
        "adjudication",
        "promotion_blockers",
        "status",
        "policy_tuned_on_evaluation_cases",
        "digest",
    ),
    "lunar.planner.workflow-resource-profile/v1": (
        "profile_id",
        "as_of",
        "provider_revision",
        "status",
        "sample_size",
        "excluded_stale_count",
        "excluded_revision_mismatch_count",
        "privacy_cohort_count",
        "distribution",
        "calibration",
        "fallback",
        "promotion_blockers",
        "digest",
    ),
    "lunar.planner.price-book/v1": ("retrieved_at", "rates", "digest"),
    "lunar.planner.report-workflow-inheritance/v1": (
        "blueprint_id",
        "blueprint_version",
        "status",
        "request",
        "inheritance_boundary",
        "source_workflows",
        "mandatory_control_bindings",
        "stages",
        "section_critiques",
        "cross_artifact_gates",
        "completion_invariants",
        "route_only",
        "digest",
    ),
    "lunar.planner.contextual-quality-criterion/v1": (
        "criterion_id",
        "lifecycle",
        "created_in_version",
        "requirement_ids",
        "consumer",
        "source",
        "observable",
        "required_anchors",
        "allowed_evidence",
        "evaluator_mode",
        "separation_required",
        "severity",
        "pass_condition",
        "failure_consequence",
        "allowed_variability",
        "prohibited_outcomes",
        "authority_ceiling",
        "examples",
        "invalidation_inputs",
        "user_confirmable",
    ),
    "lunar.planner.contextual-outcome-quality-contract/v1": (
        "contract_id",
        "version",
        "lifecycle",
        "root_interaction_id",
        "operation_role",
        "parent_digest",
        "principal",
        "canonical_serialization",
        "evidence_manifest_digest",
        "requirement_ids",
        "criteria",
        "criterion_consumer_trace",
        "evidence_whitelist",
        "risk_tier",
        "review_status",
        "digest",
    ),
    "lunar.planner.route-delivery-quality-plan/v1": (
        "plan_id",
        "version",
        "lifecycle",
        "root_interaction_id",
        "operation_role",
        "parent_digest",
        "principal",
        "canonical_serialization",
        "evidence_manifest_digest",
        "outcome_contract_digest",
        "outcome_contract_lifecycle",
        "selected_target",
        "criteria",
        "criterion_consumer_trace",
        "evidence_whitelist",
        "evaluator_plan",
        "release_policy",
        "risk_tier",
        "review_status",
        "digest",
    ),
    "lunar.planner.quality-plan-review/v1": (
        "review_id",
        "root_interaction_id",
        "operation_role",
        "parent_digest",
        "principal",
        "canonical_serialization",
        "evidence_manifest_digest",
        "plan_digest",
        "reviewer",
        "independent",
        "checks",
        "verdict",
        "digest",
    ),
    "lunar.planner.quality-assessment/v1": (
        "assessment_id",
        "root_interaction_id",
        "operation_role",
        "parent_digest",
        "principal",
        "canonical_serialization",
        "evidence_manifest_digest",
        "quality_plan_digest",
        "artifact_digest",
        "evaluator",
        "independent",
        "criterion_results",
        "verdict",
        "digest",
    ),
    "lunar.planner.final-delivery-decision/v1": (
        "decision_id",
        "root_interaction_id",
        "operation_role",
        "parent_digest",
        "principal",
        "canonical_serialization",
        "evidence_manifest_digest",
        "quality_plan_digest",
        "assessment_digest",
        "artifact_digest",
        "decision",
        "reasons",
        "next_action",
        "digest",
    ),
}


def _validate_quality_lineage(document: Mapping[str, Any], errors: list[str]) -> None:
    """Validate the acyclic, typed one-hop quality-operation lineage."""

    role = document.get("operation_role")
    if role not in QUALITY_ROLES:
        errors.append("operation_role must be a recognized quality role")
    root = document.get("root_interaction_id")
    if not isinstance(root, str) or not IDENTIFIER.fullmatch(root):
        errors.append("root_interaction_id must be a portable identifier")
    parent = document.get("parent_digest")
    if parent is not None and (
        not isinstance(parent, str) or not DIGEST.fullmatch(parent)
    ):
        errors.append("parent_digest must be null or a canonical sha256 digest")
    if role == "user_request" and parent is not None:
        errors.append("a user_request operation cannot have a parent")
    if parent is not None and parent == document.get("digest"):
        errors.append("quality lineage cannot reference itself")
    if (
        role in INTERNAL_QUALITY_ROLES
        and document.get("presentable_as_user_answer") is True
    ):
        errors.append(
            "internal quality-operation output cannot be presented as the user answer"
        )
    if document.get("canonical_serialization") != "canonical-json-v1":
        errors.append("canonical_serialization must be canonical-json-v1")
    for field in ("evidence_manifest_digest",):
        value = document.get(field)
        if not isinstance(value, str) or not DIGEST.fullmatch(value):
            errors.append(f"{field} must be a canonical sha256 digest")
    principal = document.get("principal")
    if not isinstance(principal, Mapping) or not principal.get("id"):
        errors.append("principal must identify the authorized caller")


def _validate_criterion(
    criterion: Mapping[str, Any], errors: list[str], prefix: str = "criterion"
) -> None:
    """Validate criterion."""
    lifecycle = criterion.get("lifecycle")
    if lifecycle not in QUALITY_LIFECYCLES:
        errors.append(f"{prefix}.lifecycle is invalid")
    observable = criterion.get("observable")
    if not isinstance(observable, str) or not observable.strip():
        errors.append(f"{prefix}.observable must be context-specific")
    elif _GENERIC_QUALITY.fullmatch(observable.strip()) or _TAUTOLOGICAL_QUALITY.search(
        observable
    ):
        errors.append(f"{prefix}.observable is generic-only or tautological")
    requirement_ids = criterion.get("requirement_ids")
    if not isinstance(requirement_ids, list) or not requirement_ids:
        errors.append(f"{prefix} must cover at least one requirement")
    if not isinstance(criterion.get("consumer"), str) or not criterion.get("consumer"):
        errors.append(f"{prefix}.consumer must be explicit")
    source = criterion.get("source")
    if (
        not isinstance(source, Mapping)
        or source.get("kind")
        not in {
            "user",
            "user_feedback",
            "supplied_evidence",
            "component_contract",
            "domain_rule",
            "consumer_contract",
            "planner_inference",
        }
        or not source.get("pointer")
    ):
        errors.append(
            f"{prefix}.source must have an allowed kind and resolvable pointer"
        )
    mode = criterion.get("evaluator_mode")
    if mode not in {"deterministic", "generative", "hybrid", "human"}:
        errors.append(f"{prefix}.evaluator_mode is invalid")
    if criterion.get("severity") not in {"must_pass", "should_pass"}:
        errors.append(f"{prefix}.severity is invalid")
    if (
        mode in {"generative", "hybrid"}
        and criterion.get("severity") == "must_pass"
        and criterion.get("separation_required") is not True
    ):
        errors.append(f"{prefix} requires producer/evaluator separation")
    if mode in {"generative", "hybrid"}:
        examples = criterion.get("examples")
        if not isinstance(examples, Mapping) or not all(
            examples.get(key) for key in ("positive", "negative", "edge")
        ):
            errors.append(
                f"{prefix} semantic examples must include positive, negative, and edge cases"
            )
    for field in (
        "required_anchors",
        "allowed_evidence",
        "prohibited_outcomes",
        "invalidation_inputs",
    ):
        if not isinstance(criterion.get(field), list):
            errors.append(f"{prefix}.{field} must be a list")


def _validate_quality_semantics(document: Mapping[str, Any], errors: list[str]) -> None:
    """Validate quality semantics."""
    version = document.get("schema_version")
    if version == "lunar.planner.contextual-quality-criterion/v1":
        _validate_criterion(document, errors)
        return
    _validate_quality_lineage(document, errors)
    if version in {
        "lunar.planner.contextual-outcome-quality-contract/v1",
        "lunar.planner.route-delivery-quality-plan/v1",
    }:
        criteria = document.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            errors.append("quality plan must contain contextual criteria")
            return
        seen: set[str] = set()
        covered: set[str] = set()
        for index, criterion in enumerate(criteria):
            if not isinstance(criterion, Mapping):
                errors.append(f"criteria[{index}] must be a mapping")
                continue
            _validate_criterion(criterion, errors, f"criteria[{index}]")
            criterion_id = str(criterion.get("criterion_id", ""))
            if not criterion_id or criterion_id in seen:
                errors.append("criterion_id values must be non-empty and unique")
            seen.add(criterion_id)
            covered.update(str(item) for item in criterion.get("requirement_ids", ()))
        missing = set(map(str, document.get("requirement_ids", ()))) - covered
        if missing:
            errors.append(f"quality plan has uncovered requirements: {sorted(missing)}")
        trace = document.get("criterion_consumer_trace", {})
        if not isinstance(trace, Mapping) or seen - set(map(str, trace)):
            errors.append("every criterion must have a consumer trace")
        if (
            document.get("lifecycle") == "frozen"
            and document.get("review_status") != "passed"
        ):
            errors.append("a frozen quality plan requires a passed adequacy review")
        if version.endswith("route-delivery-quality-plan/v1"):
            if document.get("parent_digest") != document.get("outcome_contract_digest"):
                errors.append(
                    "delivery plan parent must be the frozen outcome contract"
                )
            if (
                document.get("lifecycle") == "frozen"
                and document.get("outcome_contract_lifecycle") != "frozen"
            ):
                errors.append("a frozen delivery plan requires a frozen outcome parent")
    elif version == "lunar.planner.quality-plan-review/v1":
        if document.get("verdict") not in {"pass", "fail", "inconclusive"}:
            errors.append("quality review verdict is invalid")
        checks = document.get("checks")
        required = {
            "coverage",
            "specificity",
            "feasibility",
            "authority",
            "conflicts",
            "architecture_bias",
        }
        if not isinstance(checks, Mapping) or required - set(checks):
            errors.append("quality review must report every adequacy check")
        if (
            document.get("verdict") == "pass"
            and document.get("independent") is not True
        ):
            errors.append("a passed quality-plan review must be independent")
    elif version == "lunar.planner.quality-assessment/v1":
        if document.get("verdict") not in {"pass", "fail", "inconclusive"}:
            errors.append("quality assessment verdict is invalid")
        results = document.get("criterion_results")
        if not isinstance(results, list) or not results:
            errors.append("quality assessment requires per-criterion results")
        else:
            for index, result in enumerate(results):
                if (
                    not isinstance(result, Mapping)
                    or result.get("verdict") not in QUALITY_VERDICTS
                ):
                    errors.append(f"criterion_results[{index}] verdict is invalid")
                if (
                    result.get("verdict") == "not_applicable"
                    and result.get("severity") == "must_pass"
                ):
                    errors.append("not_applicable is forbidden for must_pass criteria")
                if result.get("verdict") in {"pass", "fail"} and not result.get(
                    "artifact_anchors"
                ):
                    errors.append(
                        f"criterion_results[{index}] requires artifact anchors"
                    )
        if (
            document.get("verdict") == "pass"
            and document.get("independent") is not True
        ):
            errors.append("a passing artifact assessment must be independent")
    elif version == "lunar.planner.final-delivery-decision/v1":
        if document.get("operation_role") != "final_delivery":
            errors.append("final decision must use the final_delivery operation role")
        if document.get("decision") not in {
            "release",
            "revise",
            "needs_input",
            "inconclusive",
            "block",
        }:
            errors.append("final delivery decision is invalid")
        if document.get("presentable_as_user_answer") is not (
            document.get("decision") == "release"
        ):
            errors.append("only a release decision may authorize presentation")
    digest = document.get("digest")
    if (
        isinstance(digest, str)
        and DIGEST.fullmatch(digest)
        and digest != canonical_digest(document)
    ):
        errors.append("digest does not match canonical document content")


ANSWER_TRUST_POLICY_FILE = "answer-trust-policy-v1.json"
ANSWER_TRUST_VERSIONS = frozenset(
    {
        "lunar.planner.answer-control-readiness/v1",
        "lunar.planner.answer-trust-assessment/v1",
        "lunar.planner.claim-trust-assessment/v1",
        "lunar.planner.generative-transformation-receipt/v1",
    }
)

WORKFLOW_ECONOMICS_VERSIONS = frozenset(
    {
        "lunar.planner.workflow-comparator-disposition/v1",
        "lunar.planner.workflow-workload-inventory/v1",
        "lunar.planner.workflow-effort-estimate/v1",
        "lunar.planner.workflow-effort-assessment/v1",
        "lunar.planner.workflow-effort-card/v1",
        "lunar.planner.workflow-effort-invalidation/v1",
        "lunar.planner.workflow-resource-estimate/v1",
        "lunar.planner.workflow-resource-usage/v1",
        "lunar.planner.workflow-cost-reconciliation/v1",
        "lunar.planner.workflow-economics-report/v1",
        "lunar.planner.workflow-effort-calibration/v1",
        "lunar.planner.workflow-resource-profile/v1",
        "lunar.planner.price-book/v1",
    }
)


def load_answer_trust_policy() -> dict[str, Any]:
    """Load and fail closed on the packaged, data-only answer-trust policy."""

    path = resource_path("policies", ANSWER_TRUST_POLICY_FILE)
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlannerContractError(f"cannot load answer-trust policy: {exc}") from exc
    if not isinstance(policy, dict):
        raise PlannerContractError("answer-trust policy must be a mapping")
    if policy.get("schema_version") != "lunar.planner.answer-trust-policy/v1":
        raise PlannerContractError("unsupported answer-trust policy schema major")
    version = policy.get("policy_version")
    if not isinstance(version, str) or not version.startswith("1."):
        raise PlannerContractError("unsupported answer-trust policy major")
    if (
        policy.get("executable_payloads_allowed") is not False
        or policy.get("dynamic_imports_allowed") is not False
    ):
        raise PlannerContractError("answer-trust policy must remain data-only")
    weights = policy.get("dimension_weights")
    expected_dimensions = {
        "external_grounding",
        "lineage_closure",
        "preservation_fidelity",
        "authority_directness_applicability",
        "generative_containment",
        "uncertainty_conflict_control",
    }
    if (
        not isinstance(weights, Mapping)
        or set(weights) != expected_dimensions
        or any(
            not isinstance(value, (int, float)) or not 0 <= value <= 1
            for value in weights.values()
        )
        or not math.isclose(
            sum(weights.values()),
            1.0,
            abs_tol=1e-12,
        )
    ):
        raise PlannerContractError("answer-trust dimension weights must sum to one")
    compatibility = policy.get("compatible_contract_majors")
    if not isinstance(compatibility, Mapping) or set(compatibility.values()) != {1}:
        raise PlannerContractError(
            "unsupported answer-trust contract compatibility major"
        )
    digest = policy.get("digest")
    if (
        not isinstance(digest, str)
        or not DIGEST.fullmatch(digest)
        or digest != canonical_digest(policy)
    ):
        raise PlannerContractError(
            "answer-trust policy digest does not match canonical content"
        )
    return policy


def _trust_tier(score: float) -> str:
    """Trust tier."""
    if score >= 85:
        return "high_control"
    if score >= 70:
        return "substantiated"
    if score >= 50:
        return "guarded"
    if score >= 25:
        return "low"
    return "blocked_untrusted"


def _validate_interval(value: Any, errors: list[str], label: str) -> None:
    """Validate interval."""
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 2:
        return
    lower, upper = value
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        errors.append(f"{label} bounds must both be numeric or both null")
    elif lower > upper:
        errors.append(f"{label} lower bound cannot exceed upper bound")


def _validate_claim_trust_semantics(
    document: Mapping[str, Any], errors: list[str]
) -> None:
    """Validate claim trust semantics."""
    _validate_interval(document.get("score_interval"), errors, "score_interval")
    score = document.get("score")
    dimensions = document.get("dimensions")
    policy = load_answer_trust_policy()
    if isinstance(dimensions, Mapping) and dimensions:
        weights = policy["dimension_weights"]
        epsilon = policy["epsilon"]

        def computed(unknown: float) -> float:
            """Computed."""
            raw = 100 * math.exp(
                sum(
                    float(weights[key])
                    * math.log(
                        max(
                            (
                                unknown
                                if dimensions[key] is None
                                else float(dimensions[key])
                            ),
                            epsilon,
                        )
                    )
                    for key in weights
                )
            )
            ceilings = [
                float(row["maximum"])
                for row in document.get("caps", ())
                if isinstance(row, Mapping)
            ]
            if document.get("gates"):
                ceilings.append(0.0)
            return min([raw, *ceilings], default=raw)

        expected_interval = [computed(0.0), computed(1.0)]
        interval = document.get("score_interval")
        if not isinstance(interval, list) or any(
            not math.isclose(float(actual), expected, abs_tol=1e-6)
            for actual, expected in zip(interval, expected_interval, strict=True)
        ):
            errors.append(
                "claim score interval does not replay from dimensions and policy"
            )
        expected_score = (
            expected_interval[0]
            if math.isclose(*expected_interval, abs_tol=1e-9)
            else None
        )
        if expected_score is None and score is not None:
            errors.append("uncertain claim dimensions require a null crisp score")
        elif expected_score is not None and (
            not isinstance(score, (int, float))
            or not math.isclose(float(score), expected_score, abs_tol=1e-6)
        ):
            errors.append("claim score does not replay from its interval")


def _validate_receipt_semantics(document: Mapping[str, Any], errors: list[str]) -> None:
    """Validate receipt semantics."""
    if document.get("output_digest") in set(document.get("input_digests", ())):
        errors.append("generative receipt output cannot be one of its inputs")
    if document.get("receipt_id") in set(document.get("generated_ancestor_ids", ())):
        errors.append("generative receipt cannot be its own ancestor")
    verifier = document.get("independent_verifier")
    if document.get("verification_status") == "passed":
        if not isinstance(verifier, Mapping):
            errors.append(
                "a passed generative receipt requires an independent verifier"
            )
        elif verifier.get("provider") == document.get("provider"):
            errors.append("producer-only review is not independent verification")
    checks = document.get("protected_field_checks")
    violated = (
        any(
            isinstance(row, Mapping) and row.get("status") == "violated"
            for row in checks.values()
        )
        if isinstance(checks, Mapping)
        else False
    )
    if violated and document.get("verification_status") == "passed":
        errors.append("a protected-field violation cannot pass fidelity verification")
    if violated and not document.get("violations"):
        errors.append(
            "protected-field violations require explicit violation diagnostics"
        )


def _validate_answer_trust_semantics(
    document: Mapping[str, Any], errors: list[str]
) -> None:
    """Validate answer trust semantics."""
    version = document.get("schema_version")
    policy = load_answer_trust_policy()
    if version == "lunar.planner.answer-control-readiness/v1":
        if "score" in document or "trust_score" in document:
            errors.append("prospective readiness cannot emit a realized trust score")
    elif version == "lunar.planner.claim-trust-assessment/v1":
        _validate_claim_trust_semantics(document, errors)
        return
    elif version == "lunar.planner.generative-transformation-receipt/v1":
        _validate_receipt_semantics(document, errors)
    elif version == "lunar.planner.answer-trust-assessment/v1":
        _validate_interval(document.get("score_interval"), errors, "score_interval")
        status, score, band = (
            document.get("status"),
            document.get("score"),
            document.get("band"),
        )
        if status == "not_calculable" and (
            score is not None
            or document.get("score_interval") is not None
            or band is not None
        ):
            errors.append(
                "not_calculable answer assessment cannot emit score, interval, or band"
            )
        if status != "not_calculable" and not isinstance(
            document.get("answer_digest"), str
        ):
            errors.append(
                "a calculable answer assessment requires the exact answer digest"
            )
        interval = document.get("score_interval")
        if isinstance(interval, list):
            expected_band = _trust_tier(float(interval[0]))
            if band != expected_band and not (
                band == "substantiated" and expected_band == "high_control"
            ):
                errors.append("answer band does not match the lower score bound")
            if score is not None and not math.isclose(
                float(score), float(interval[0]), abs_tol=1e-6
            ):
                errors.append("crisp answer score must equal the lower interval bound")
        binding = document.get("binding")
        if (
            isinstance(binding, Mapping)
            and "policy_digest" in binding
            and binding.get("policy_digest") != document.get("policy_digest")
        ):
            errors.append("binding.policy_digest must match policy_digest")
        if (
            isinstance(binding, Mapping)
            and "answer_digest" in binding
            and binding.get("answer_digest") != document.get("answer_digest")
        ):
            errors.append("binding.answer_digest must match answer_digest")
        claims = document.get("claim_assessments", ())
        claim_ids = [row.get("claim_id") for row in claims if isinstance(row, Mapping)]
        if len(claim_ids) != len(set(claim_ids)):
            errors.append("claim assessment IDs must be unique")
        for row in claims:
            if isinstance(row, Mapping):
                _validate_claim_trust_semantics(row, errors)
        evidence = document.get("evidence_atoms", ())
        evidence_ids = [
            row.get("evidence_id") for row in evidence if isinstance(row, Mapping)
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            errors.append("evidence atom IDs must be unique")
        evidence_by_id = {
            str(row.get("evidence_id")): row
            for row in evidence
            if isinstance(row, Mapping)
        }
        non_evidence = set(policy["non_evidence_origins"])
        laundering_present = any(
            row.get("origin")
            not in {
                "generated",
                "generated_material",
                "independently_reproducible_derivation",
            }
            and row.get("generated_ancestor_ids")
            for row in evidence_by_id.values()
        )
        if laundering_present and document.get("status") != "blocked":
            errors.append(
                "generated ancestry cannot be recast as an external evidence origin"
            )
        edges = document.get("derivation_edges", ())
        edge_ids = [row.get("edge_id") for row in edges if isinstance(row, Mapping)]
        if len(edge_ids) != len(set(edge_ids)):
            errors.append("derivation edge IDs must be unique")
        graph: dict[str, list[str]] = defaultdict(list)
        invalid_edge_evidence = False
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            output = str(edge.get("output_id"))
            for source in edge.get("input_ids", ()):
                graph[str(source)].append(output)
            for evidence_id in edge.get("input_ids", ()):
                atom = evidence_by_id.get(str(evidence_id))
                if atom is not None and (
                    not atom.get("authorized") or not atom.get("observed_consumed")
                ):
                    invalid_edge_evidence = True
        if invalid_edge_evidence and document.get("status") != "blocked":
            errors.append(
                "derivation edge evidence must be authorized and observed as consumed"
            )
        cycle_present = False
        for root in graph:
            pending, visited = list(graph[root]), {root}
            while pending:
                node = pending.pop()
                if node in visited:
                    cycle_present = True
                    break
                visited.add(node)
                pending.extend(graph.get(node, ()))
        if cycle_present and document.get("status") != "blocked":
            errors.append("claim/evidence lineage must be acyclic")
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            atoms = [
                evidence_by_id.get(str(item)) for item in claim.get("evidence_ids", ())
            ]
            fatal = any(
                atom is not None
                and (
                    atom.get("origin") in non_evidence
                    or not atom.get("authorized")
                    or not atom.get("observed_consumed")
                )
                for atom in atoms
            )
            if (
                fatal
                and isinstance(claim.get("score"), (int, float))
                and claim["score"] > 0
            ):
                errors.append(
                    "non-evidence or unauthorized evidence cannot receive positive grounding credit"
                )
            unresolved = [
                atom
                for atom in atoms
                if atom is not None
                and (not atom.get("content_digest") or not atom.get("locator"))
            ]
            has_resolution_control = any(
                row.get("code") in {"missing_digest_or_locator", "invalid_evidence"}
                for row in (*claim.get("caps", ()), *claim.get("gates", ()))
                if isinstance(row, Mapping)
            )
            if unresolved and not has_resolution_control:
                errors.append(
                    "missing evidence digest or locator requires an explicit cap or gate"
                )
    digest = document.get("digest")
    if (
        isinstance(digest, str)
        and DIGEST.fullmatch(digest)
        and digest != canonical_digest(document)
    ):
        errors.append("digest does not match canonical document content")


def _validate_quantiles(value: Any, errors: list[str], label: str) -> None:
    """Validate quantiles."""
    if not isinstance(value, Mapping):
        return
    points = [value.get(name) for name in ("p10", "p50", "p90")]
    if any(
        not isinstance(point, (int, float)) or isinstance(point, bool)
        for point in points
    ):
        errors.append(f"{label} quantiles must be numeric")
    else:
        numeric_points = [
            float(point)
            for point in points
            if isinstance(point, (int, float)) and not isinstance(point, bool)
        ]
        if any(not math.isfinite(point) for point in numeric_points):
            errors.append(f"{label} quantiles must be finite")
        elif not numeric_points[0] <= numeric_points[1] <= numeric_points[2]:
            errors.append(f"{label} quantiles must be ordered")


def _validate_workflow_economics_semantics(
    document: Mapping[str, Any], errors: list[str]
) -> None:
    """Enforce polarity and replayable arithmetic for economics contracts."""

    version = document.get("schema_version")
    if version == "lunar.planner.workflow-comparator-disposition/v1":
        equivalent = not document.get("missing_dimensions") and not document.get(
            "mismatched_dimensions"
        )
        if (document.get("status") == "equivalent") is not equivalent:
            errors.append(
                "comparator status does not match its equivalence diagnostics"
            )
    elif version == "lunar.planner.workflow-workload-inventory/v1":
        unit_ids = [
            row.get("work_unit_id")
            for row in document.get("work_units", ())
            if isinstance(row, Mapping)
        ]
        if len(unit_ids) != len(set(unit_ids)):
            errors.append("workload inventory work_unit_ids must be unique")
        expected = (
            bool(unit_ids)
            and not document.get("unresolved_drivers")
            and not document.get("duplicate_operations")
        )
        if document.get("estimable") is not expected:
            errors.append("workload estimable flag does not match its diagnostics")
    elif version in {
        "lunar.planner.workflow-effort-estimate/v1",
        "lunar.planner.workflow-effort-assessment/v1",
    }:
        expected_state = (
            "prospective" if version.endswith("effort-estimate/v1") else "observed"
        )
        if document.get("evidence_state") != expected_state:
            errors.append(f"{version} requires {expected_state} evidence polarity")
        headline = document.get("headline")
        if document.get("status") == "not_estimable":
            if headline is not None or not document.get("blockers"):
                errors.append("not_estimable effort requires blockers and no headline")
        elif isinstance(headline, Mapping):
            for field in (
                "manual_person_hours",
                "assisted_person_hours",
                "net_saved_person_hours",
            ):
                _validate_quantiles(headline.get(field), errors, f"headline.{field}")
            manual = headline.get("manual_person_hours", {})
            assisted = headline.get("assisted_person_hours", {})
            saved = headline.get("net_saved_person_hours", {})
            if all(isinstance(row, Mapping) for row in (manual, assisted, saved)):
                expected_saved = float(manual.get("p50", 0)) - float(
                    assisted.get("p50", 0)
                )
                if not math.isclose(
                    float(saved.get("p50", 0)), expected_saved, abs_tol=1e-6
                ):
                    errors.append(
                        "net saved p50 does not equal manual p50 minus assisted p50"
                    )
                fraction = headline.get("saving_fraction_at_p50")
                expected_fraction = (
                    expected_saved / float(manual["p50"])
                    if float(manual.get("p50", 0)) > 0
                    else None
                )
                if expected_fraction is None:
                    if fraction is not None:
                        errors.append(
                            "saving fraction must be null when manual p50 is zero"
                        )
                elif not isinstance(fraction, (int, float)) or not math.isclose(
                    float(fraction), expected_fraction, abs_tol=1e-6
                ):
                    errors.append(
                        "saving fraction does not replay from headline effort"
                    )
                if headline.get("negative_savings") is not (
                    float(saved.get("p50", 0)) < 0
                ):
                    errors.append("negative_savings does not match net saved p50")
        component_ids = [
            row.get("work_unit_id")
            for row in document.get("components", ())
            if isinstance(row, Mapping)
        ]
        if len(component_ids) != len(set(component_ids)):
            errors.append("effort component work_unit_ids must be unique")
    elif version == "lunar.planner.workflow-resource-estimate/v1":
        for index, line in enumerate(document.get("lines", ())):
            if not isinstance(line, Mapping):
                continue
            if line.get("evidence_state") == "not_calculable":
                if any(name in line for name in ("p10", "p50", "p90", "quantity")):
                    errors.append(
                        f"resource estimate line {index} cannot encode unknown usage as a number"
                    )
            else:
                _validate_quantiles(line, errors, f"resource estimate line {index}")
                if any(float(line.get(name, 0)) < 0 for name in ("p10", "p50", "p90")):
                    errors.append(
                        f"resource estimate line {index} quantities must be nonnegative"
                    )
    elif version == "lunar.planner.workflow-resource-usage/v1":
        if document.get("polarity") != "observed_only":
            errors.append("resource usage must remain observed-only")
        if document.get("budget_treated_as_usage") is not False:
            errors.append("configured budgets cannot be treated as observed usage")
        coverage = document.get("observed_attempt_coverage")
        if coverage is not None and (
            not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1
        ):
            errors.append("observed attempt coverage must be in [0,1]")
        aggregate = document.get("aggregate")
        if isinstance(aggregate, Mapping):
            for line in aggregate.get("lines", ()):
                if isinstance(line, Mapping):
                    quantity = line.get("quantity")
                    if not isinstance(quantity, (int, float)) or quantity < 0:
                        errors.append("observed usage quantities must be nonnegative")
    elif version == "lunar.planner.workflow-cost-reconciliation/v1":
        if document.get("polarity") != "observed_only":
            errors.append("cost reconciliation must remain observed-only")
        if document.get("missing_price_as_zero") is not False:
            errors.append("missing prices cannot be represented as zero cost")
        priced_lines = document.get("priced_lines", ())
        total = sum(
            int(row.get("cost_nano", 0))
            for row in priced_lines
            if isinstance(row, Mapping)
        )
        if document.get("priced_total_nano") != total:
            errors.append("priced total does not equal priced line arithmetic")
        line_count = len(priced_lines) + len(document.get("unpriced_lines", ()))
        expected_coverage = len(priced_lines) / line_count if line_count else None
        actual_coverage = document.get("cost_line_coverage")
        if expected_coverage is None:
            if actual_coverage is not None:
                errors.append("empty cost reconciliation must have null coverage")
        elif not isinstance(actual_coverage, (int, float)) or not math.isclose(
            float(actual_coverage), expected_coverage, abs_tol=1e-12
        ):
            errors.append(
                "cost line coverage does not replay from priced and unpriced lines"
            )
    elif version == "lunar.planner.workflow-economics-report/v1":
        if document.get("scientific_release_effect") is not False:
            errors.append("workflow economics cannot affect scientific release")
        if document.get("scalar_roi") is not None:
            errors.append(
                "workflow economics cannot collapse unlike quantities into scalar ROI"
            )
        for field in ("effort", "resource", "cost"):
            nested = document.get(field)
            if isinstance(nested, Mapping):
                nested_report = validate_contract(nested)
                errors.extend(f"{field}: {error}" for error in nested_report.errors)
    elif version == "lunar.planner.workflow-effort-calibration/v1":
        if document.get("policy_tuned_on_evaluation_cases") is not False:
            errors.append("evaluation cases cannot tune the effort policy")
        if document.get("status") == "promotable" and document.get(
            "promotion_blockers"
        ):
            errors.append("promotable calibration cannot retain blockers")
    elif version == "lunar.planner.price-book/v1":
        try:
            from .pricing import seal_price_book

            seal_price_book(document)
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid price book semantics: {exc}")

    digest = document.get("digest")
    if (
        isinstance(digest, str)
        and DIGEST.fullmatch(digest)
        and digest != canonical_digest(document)
    ):
        errors.append("digest does not match canonical document content")


def validate_contract(
    document: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> PlannerValidationReport:
    """Validate minimum invariants for any versioned planner contract.

    Full portable shapes are packaged under ``resources/schemas``; this
    dependency-light check is the fail-closed boundary used by planner
    services that do not invoke a JSON Schema engine at runtime.
    """

    version = document.get("schema_version")
    if version == PROFILE_SCHEMA_VERSION:
        semantic = validate_profile(document, repo_root=repo_root)
        schema = load_schema(version)
        shape_errors = _validate_schema_value(document, schema, schema, "$")
        return PlannerValidationReport(
            errors=tuple(dict.fromkeys((*shape_errors, *semantic.errors))),
            order=semantic.order,
            producers=semantic.producers,
        )
    errors: list[str] = []
    if not isinstance(version, str) or not NAMESPACED_VERSION.fullmatch(version):
        errors.append(
            "schema_version must be namespaced as lunar.planner.<contract>/v<major>"
        )
        return PlannerValidationReport(tuple(errors))
    if version not in _REQUIRED_FIELDS:
        errors.append(f"unsupported planner schema_version: {version}")
        return PlannerValidationReport(tuple(errors))
    schema = load_schema(version)
    errors.extend(_validate_schema_value(document, schema, schema, "$"))
    for field in _REQUIRED_FIELDS[version]:
        if field not in document:
            errors.append(f"missing required field: {field}")

    if version in {
        "lunar.planner.contextual-outcome-quality-contract/v1",
        "lunar.planner.route-delivery-quality-plan/v1",
        "lunar.planner.quality-plan-review/v1",
        "lunar.planner.contextual-quality-criterion/v1",
        "lunar.planner.quality-assessment/v1",
        "lunar.planner.final-delivery-decision/v1",
    }:
        _validate_quality_semantics(document, errors)

    if version in ANSWER_TRUST_VERSIONS:
        _validate_answer_trust_semantics(document, errors)

    if version in WORKFLOW_ECONOMICS_VERSIONS:
        _validate_workflow_economics_semantics(document, errors)

    if version == "lunar.planner.request/v1":
        authority = document.get("authority")
        expected = {
            "mode": "planning_only",
            "execution": "forbidden",
            "external_actions": "forbidden",
            "mutation": "forbidden",
        }
        if authority != expected:
            errors.append("request authority must be the exact planning-only envelope")
    elif (
        version
        in {
            "lunar.planner.route/v1",
            "lunar.planner.run-manifest/v1",
            "lunar.planner.plan/v1",
        }
        and document.get("authority") != "planning_only"
    ):
        errors.append("authority must be planning_only")
    elif version == "lunar.planner.acceptance/v1":
        if document.get("authority") != "accept_plan_only":
            errors.append("acceptance authority must be accept_plan_only")
        if not isinstance(document.get("plan_digest"), str) or not DIGEST.fullmatch(
            document["plan_digest"]
        ):
            errors.append("acceptance must bind one exact sha256 plan_digest")

    if "digest" in document and (
        not isinstance(document.get("digest"), str)
        or not DIGEST.fullmatch(document["digest"])
    ):
        errors.append("digest must be a canonical sha256 digest")
    if "plan_digest" in document and (
        not isinstance(document.get("plan_digest"), str)
        or not DIGEST.fullmatch(document["plan_digest"])
    ):
        errors.append("plan_digest must be a canonical sha256 digest")
    for key in (
        "request_id",
        "route_id",
        "run_id",
        "plan_id",
        "event_id",
        "todo_id",
        "acceptance_id",
        "reconciliation_id",
        "idempotency_key",
    ):
        value = document.get(key)
        if value is not None and (
            not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
        ):
            errors.append(f"{key} must be a non-empty portable identifier")

    if version == "lunar.planner.provenance-reconciliation/v1":
        for index, component in enumerate(document.get("components", ())):
            if not isinstance(component, Mapping):
                errors.append(f"components[{index}] must be a mapping")
                continue
            if "prospective" not in component or "observed" not in component:
                errors.append(
                    f"components[{index}] must distinguish prospective and observed data"
                )
    return PlannerValidationReport(tuple(dict.fromkeys(errors)))


def require_valid_contract(
    document: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> Mapping[str, Any]:
    """Return ``document`` or raise one stable planner validation error."""

    report = validate_contract(document, repo_root=repo_root)
    if not report.valid:
        raise PlannerContractError("; ".join(report.errors))
    return document


def load_profile(
    path: str | Path, *, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Strictly load and validate one planning-only profile."""

    profile = load_planner_yaml(path)
    require_valid_contract(profile, repo_root=repo_root)
    return profile
