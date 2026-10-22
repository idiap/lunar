# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic prospective-versus-observed planner provenance utilities.

Prospective rows describe responsibility.  They are deliberately never used as
evidence that a component was produced.  Only retrospective rows can establish
observation, and privacy-limited rows remain visible as explicit omissions.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from typing import Any, cast

from .portable import stable_hash

_PRIVATE_KEY_PARTS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "credential",
        "password",
        "private_content",
        "raw_prompt",
        "secret",
        "token",
    }
)
_OMISSION = {"status": "redacted", "reason": "privacy_boundary"}

_PROV_PREFIXES = {
    "prov": "http://www.w3.org/ns/prov#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "lunar": "https://lunar.local/ns/prov#",
}

_PLANNER_ARTIFACT_KEYS = (
    "external_source_plan",
    "requirement_ledger",
    "workflow_draft",
    "workflow_instantiation",
    "proposed_skill_test_plans",
    "workflow_refinement_cycle",
    "delivery_handoff",
    "reasoning_log",
    "next_step_guidance",
    "delivery_package_policy",
    "delivery_package",
)


def _private_key(key: object) -> bool:
    """Private key."""
    normalized = str(key).strip().lower().replace("-", "_")
    return any(
        normalized == part
        or normalized.startswith(f"{part}_")
        or normalized.endswith(f"_{part}")
        for part in _PRIVATE_KEY_PARTS
    )


def redact_private_values(value: Any) -> Any:
    """Return a deterministic copy with secret-bearing fields omitted.

    Redaction is structural rather than a replacement string so downstream
    consumers cannot confuse an omitted value with an observed empty value.
    """

    if isinstance(value, Mapping):
        return {
            str(key): (
                dict(_OMISSION) if _private_key(key) else redact_private_values(item)
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [redact_private_values(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _component_rows(
    value: Iterable[Mapping[str, Any]] | Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Component rows."""
    if isinstance(value, Mapping):
        mapping_value = cast(Mapping[str, Any], value)
        source: Any = mapping_value.get("components")
        if source is None:
            source = value
        if isinstance(source, Mapping):
            rows = []
            for component_id, row in source.items():
                packet = dict(row) if isinstance(row, Mapping) else {"value": row}
                packet.setdefault("component_id", str(component_id))
                rows.append(packet)
            return rows
        value = source
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("components must be a mapping or iterable of mappings")
    rows = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("each component must be a mapping")
        rows.append({str(key): item for key, item in row.items()})
    return rows


def _index_components(
    value: Iterable[Mapping[str, Any]] | Mapping[str, Any], *, label: str
) -> dict[str, dict[str, Any]]:
    """Index components."""
    indexed: dict[str, dict[str, Any]] = {}
    for row in _component_rows(value):
        component_id = str(row.get("component_id", "")).strip()
        if not component_id:
            raise ValueError(f"{label} component is missing component_id")
        if component_id in indexed:
            raise ValueError(f"duplicate {label} component_id: {component_id}")
        indexed[component_id] = row
    return indexed


def _privacy_class(row: Mapping[str, Any]) -> str:
    """Privacy class."""
    return (
        str(row.get("privacy_class", row.get("redaction_class", "public")))
        .strip()
        .lower()
    )


def _observed_state(
    row: Mapping[str, Any], allowed_privacy_classes: frozenset[str]
) -> tuple[str, str | None]:
    """Observed state."""
    declared = str(row.get("status", row.get("observation_status", "observed"))).lower()
    if bool(row.get("redacted")) or declared == "redacted":
        return "redacted", str(row.get("omission_reason", "explicit_redaction"))
    privacy_class = _privacy_class(row)
    if privacy_class not in allowed_privacy_classes:
        return "redacted", "privacy_boundary"
    if declared in {
        "missing",
        "not_executed",
        "unavailable",
        "expired",
        "unauthorized",
    }:
        return declared, str(row.get("omission_reason", declared))
    return "observed", None


def _expected_digest(row: Mapping[str, Any]) -> object:
    """Expected digest."""
    return row.get("expected_artifact_digest", row.get("expected_digest"))


def _actual_digest(row: Mapping[str, Any]) -> object:
    """Actual digest."""
    return row.get("artifact_digest", row.get("content_digest", row.get("digest")))


def reconcile_components(
    prospective: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    observed: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    *,
    allowed_privacy_classes: Iterable[str] = ("public", "internal"),
) -> dict[str, Any]:
    """Reconcile intended component responsibility against run observations.

    An absent retrospective row is ``missing``, not ``observed``.  A redacted
    or unauthorized row is an explicit omission and is not counted as matched.
    Input packets are privacy-filtered before they enter the returned report.
    """

    planned = _index_components(prospective, label="prospective")
    actual = _index_components(observed, label="observed")
    allowed = frozenset(str(value).strip().lower() for value in allowed_privacy_classes)
    components: list[dict[str, Any]] = []

    for component_id in sorted(set(planned) | set(actual)):
        planned_row = planned.get(component_id)
        observed_row = actual.get(component_id)
        omission_reason: str | None = None
        if observed_row is None:
            observed_status = "missing"
            omission_reason = "no_retrospective_component"
        else:
            observed_status, omission_reason = _observed_state(observed_row, allowed)

        if planned_row is None:
            status = (
                "unexpected_observation"
                if observed_status == "observed"
                else "unexpected_omission"
            )
        elif observed_status != "observed":
            status = (
                "missing_observation"
                if observed_status == "missing"
                else observed_status
            )
        else:
            expected_digest = _expected_digest(planned_row)
            actual_digest = _actual_digest(observed_row or {})
            status = (
                "digest_mismatch"
                if expected_digest is not None
                and actual_digest is not None
                and expected_digest != actual_digest
                else "matched"
            )

        critical = bool((planned_row or {}).get("release_critical", False))
        release_blocking = status in {"digest_mismatch", "unexpected_observation"} or (
            planned_row is not None and status != "matched" and critical
        )
        row: dict[str, Any] = {
            "component_id": component_id,
            "prospective_status": (
                "planned" if planned_row is not None else "not_planned"
            ),
            "observed_status": observed_status,
            "reconciliation_status": status,
            "release_blocking": release_blocking,
            "prospective": (
                redact_private_values(planned_row) if planned_row is not None else None
            ),
            "observed": (
                {
                    "component_id": component_id,
                    "status": "redacted",
                    "reason": omission_reason,
                }
                if observed_status == "redacted"
                else (
                    redact_private_values(observed_row)
                    if observed_row is not None
                    else None
                )
            ),
        }
        if omission_reason is not None:
            row["omission_reason"] = omission_reason
        components.append(row)

    counts = Counter(row["reconciliation_status"] for row in components)
    report: dict[str, Any] = {
        "schema_version": "lunar.planner.provenance-reconciliation/v1",
        "components": components,
        "summary": {
            "component_count": len(components),
            "status_counts": dict(sorted(counts.items())),
            "release_blocking": any(row["release_blocking"] for row in components),
            "complete": all(
                row["reconciliation_status"] == "matched" for row in components
            ),
        },
        "boundary": {
            "prospective_is_observation": False,
            "allowed_privacy_classes": sorted(allowed),
            "redactions_are_explicit_omissions": True,
        },
    }
    report["prospective_digest"] = stable_hash(redact_private_values(planned))
    report["observed_digest"] = stable_hash(redact_private_values(actual))
    report["reconciliation_digest"] = stable_hash(report)
    return report


def propagate_invalidation(
    dependencies: Mapping[str, Iterable[str]], changed_ids: Iterable[str]
) -> list[str]:
    """Return changed nodes and all transitive dependents in stable BFS order.

    ``dependencies`` maps each source identifier to its direct consumers.  The
    result is independent of mapping and iterable insertion order.
    """

    graph = {
        str(source): tuple(sorted({str(target) for target in targets}))
        for source, targets in dependencies.items()
    }
    queue = deque(sorted({str(value) for value in changed_ids}))
    invalidated: list[str] = []
    seen: set[str] = set()
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        invalidated.append(node)
        queue.extend(target for target in graph.get(node, ()) if target not in seen)
    return invalidated


def build_invalidation_report(
    dependencies: Mapping[str, Iterable[str]],
    changed_ids: Iterable[str],
    *,
    reason: str,
) -> dict[str, Any]:
    """Build a content-addressed deterministic invalidation projection."""

    changed = sorted({str(value) for value in changed_ids})
    invalidated = propagate_invalidation(dependencies, changed)
    report: dict[str, Any] = {
        "schema_version": "lunar.planner.invalidation/v1",
        "changed_ids": changed,
        "invalidated_ids": invalidated,
        "reason": reason,
    }
    report["invalidation_digest"] = stable_hash(report)
    return report


def _prov_identifier(kind: str, value: Any) -> str:
    """Return a deterministic qualified name safe for W3C PROV serializations."""

    digest = stable_hash(redact_private_values(value)).split(":", 1)[1]
    return f"lunar:{kind}-{digest[:24]}"


def _prov_attributes(*, label: str, kind: str, payload: Any) -> dict[str, Any]:
    """Build portable literal attributes without embedding private structures."""

    redacted = redact_private_values(payload)
    return {
        "prov:label": label,
        "prov:type": f"lunar:{kind}",
        "lunar:payload": json.dumps(
            redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ),
    }


def _relation_id(relation: str, packet: Mapping[str, Any]) -> str:
    """Relation id."""
    return (
        "_:" + stable_hash({"relation": relation, **dict(packet)}).split(":", 1)[1][:24]
    )


def planner_result_to_prov_records(
    planner_result: Mapping[str, Any],
    *,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a planner result into conservative W3C PROV records.

    The planner invocation itself is an observed activity because its returned
    result is the input to this function. Candidate workflows, skills, stages,
    and prospective components remain entities describing plans. They never
    become activities unless a retrospective observation explicitly says that
    the component was observed.
    """

    if not isinstance(planner_result, Mapping):
        raise ValueError("planner_result must be a mapping")
    redacted_result = redact_private_values(planner_result)
    command_text = str(planner_result.get("command_text", "")).strip()
    if not command_text:
        request_frame = planner_result.get("planner_receipt", {})
        if isinstance(request_frame, Mapping):
            frame = request_frame.get("request_frame", {})
            if isinstance(frame, Mapping):
                command_text = str(
                    frame.get("command_text", frame.get("text", ""))
                ).strip()
    request_payload: dict[str, Any] = {
        "command_text": command_text,
        "references": redact_private_values(planner_result.get("references", [])),
    }
    request_id = _prov_identifier("request", request_payload)
    result_id = _prov_identifier("routing-decision", redacted_result)
    activity_id = _prov_identifier(
        "planning-activity",
        {
            "request": request_payload,
            "result_digest": planner_result.get(
                "digest",
                (
                    planner_result.get("planner_receipt", {}).get("digest")
                    if isinstance(planner_result.get("planner_receipt"), Mapping)
                    else None
                ),
            ),
        },
    )
    agent_id = "lunar:planner"

    records: dict[str, Any] = {
        "entities": {
            request_id: _prov_attributes(
                label="Lunar planner request",
                kind="PlannerRequest",
                payload=request_payload,
            ),
            result_id: _prov_attributes(
                label="Lunar routing decision",
                kind="PlannerRoutingDecision",
                payload=redacted_result,
            ),
        },
        "activities": {
            activity_id: _prov_attributes(
                label="Lunar route-only planning",
                kind="PlanningActivity",
                payload={
                    "status": planner_result.get("status"),
                    "mode": planner_result.get("mode"),
                    "route_only": planner_result.get("route_only"),
                    "performed_actions": planner_result.get("performed_actions", []),
                },
            )
        },
        "agents": {
            agent_id: {
                "prov:label": "Lunar planner",
                "prov:type": "prov:SoftwareAgent",
                "lunar:implementation": "lunar_planner",
            }
        },
        "relations": [],
    }
    records["relations"].extend(
        [
            {"type": "used", "activity": activity_id, "entity": request_id},
            {
                "type": "wasGeneratedBy",
                "entity": result_id,
                "activity": activity_id,
            },
            {
                "type": "wasAssociatedWith",
                "activity": activity_id,
                "agent": agent_id,
            },
            {
                "type": "wasDerivedFrom",
                "generated_entity": result_id,
                "used_entity": request_id,
            },
        ]
    )

    for key in _PLANNER_ARTIFACT_KEYS:
        value = planner_result.get(key)
        if value in (None, [], {}):
            continue
        entity_id = _prov_identifier(f"plan-{key.replace('_', '-')}", value)
        records["entities"][entity_id] = _prov_attributes(
            label=key.replace("_", " "),
            kind="ProspectivePlannerArtifact",
            payload={"artifact_kind": key, "prospective": True, "value": value},
        )
        records["relations"].extend(
            [
                {
                    "type": "wasGeneratedBy",
                    "entity": entity_id,
                    "activity": activity_id,
                },
                {
                    "type": "wasDerivedFrom",
                    "generated_entity": entity_id,
                    "used_entity": request_id,
                },
            ]
        )

    if reconciliation is not None:
        _add_reconciliation_records(records, reconciliation)
    return records


def _add_reconciliation_records(
    records: dict[str, Any], reconciliation: Mapping[str, Any]
) -> None:
    """Add prospective and retrospective component entities without polarity drift."""

    if (
        reconciliation.get("schema_version")
        != "lunar.planner.provenance-reconciliation/v1"
    ):
        raise ValueError(
            "reconciliation must use lunar.planner.provenance-reconciliation/v1"
        )
    for row in reconciliation.get("components", ()):
        if not isinstance(row, Mapping):
            raise ValueError("reconciliation components must be mappings")
        component_id = str(row.get("component_id", "")).strip()
        if not component_id:
            raise ValueError("reconciliation component is missing component_id")
        prospective = row.get("prospective")
        observed = row.get("observed")
        prospective_id: str | None = None
        if isinstance(prospective, Mapping):
            prospective_id = _prov_identifier(
                "prospective-component", {"component_id": component_id, **prospective}
            )
            records["entities"][prospective_id] = _prov_attributes(
                label=f"planned component {component_id}",
                kind="ProspectiveComponent",
                payload={"component_id": component_id, **prospective},
            )
        if isinstance(observed, Mapping):
            observed_id = _prov_identifier(
                "observed-component", {"component_id": component_id, **observed}
            )
            records["entities"][observed_id] = _prov_attributes(
                label=f"observed component {component_id}",
                kind="RetrospectiveComponentObservation",
                payload={
                    "component_id": component_id,
                    "observed_status": row.get("observed_status"),
                    "reconciliation_status": row.get("reconciliation_status"),
                    **observed,
                },
            )
            if prospective_id is not None:
                records["relations"].append(
                    {
                        "type": "specializationOf",
                        "specific_entity": observed_id,
                        "general_entity": prospective_id,
                    }
                )


def _prov_json_document(records: Mapping[str, Any]) -> dict[str, Any]:
    """Prov JSON document."""
    document: dict[str, Any] = {
        "prefix": dict(_PROV_PREFIXES),
        "entity": dict(records["entities"]),
        "activity": dict(records["activities"]),
        "agent": dict(records["agents"]),
    }
    relation_fields = {
        "used": {"activity": "prov:activity", "entity": "prov:entity"},
        "wasGeneratedBy": {"entity": "prov:entity", "activity": "prov:activity"},
        "wasAssociatedWith": {"activity": "prov:activity", "agent": "prov:agent"},
        "wasDerivedFrom": {
            "generated_entity": "prov:generatedEntity",
            "used_entity": "prov:usedEntity",
        },
        "specializationOf": {
            "specific_entity": "prov:specificEntity",
            "general_entity": "prov:generalEntity",
        },
    }
    for relation in records["relations"]:
        relation_type = str(relation.get("type", ""))
        fields = relation_fields.get(relation_type)
        if fields is None:
            raise ValueError(f"unsupported PROV relation: {relation_type}")
        packet = {
            prov_key: relation[input_key] for input_key, prov_key in fields.items()
        }
        document.setdefault(relation_type, {})[
            _relation_id(relation_type, packet)
        ] = packet
    return document


def _json_ld_document(records: Mapping[str, Any]) -> dict[str, Any]:
    """JSON ld document."""
    graph: list[dict[str, Any]] = []
    relation_properties: dict[str, dict[str, list[dict[str, str]]]] = {}

    def link(subject: str, predicate: str, target: str) -> None:
        """Link."""
        relation_properties.setdefault(subject, {}).setdefault(predicate, []).append(
            {"@id": target}
        )

    for relation in records["relations"]:
        relation_type = str(relation["type"])
        if relation_type == "used":
            link(str(relation["activity"]), "prov:used", str(relation["entity"]))
        elif relation_type == "wasGeneratedBy":
            link(
                str(relation["entity"]),
                "prov:wasGeneratedBy",
                str(relation["activity"]),
            )
        elif relation_type == "wasAssociatedWith":
            link(
                str(relation["activity"]),
                "prov:wasAssociatedWith",
                str(relation["agent"]),
            )
        elif relation_type == "wasDerivedFrom":
            link(
                str(relation["generated_entity"]),
                "prov:wasDerivedFrom",
                str(relation["used_entity"]),
            )
        elif relation_type == "specializationOf":
            link(
                str(relation["specific_entity"]),
                "prov:specializationOf",
                str(relation["general_entity"]),
            )
        else:
            raise ValueError(f"unsupported PROV relation: {relation_type}")

    for collection, prov_type in (
        (records["entities"], "prov:Entity"),
        (records["activities"], "prov:Activity"),
        (records["agents"], "prov:Agent"),
    ):
        for identifier, attributes in collection.items():
            row: dict[str, Any] = {"@id": identifier, "@type": prov_type}
            row.update(attributes)
            if isinstance(row.get("lunar:payload"), str):
                row["lunar:payload"] = {
                    "@value": json.loads(row["lunar:payload"]),
                    "@type": "@json",
                }
            row.update(relation_properties.get(identifier, {}))
            graph.append(row)
    return {
        "@context": {
            **_PROV_PREFIXES,
        },
        "@graph": sorted(graph, key=lambda row: str(row["@id"])),
    }


def _validate_generic_records(records: Mapping[str, Any]) -> None:
    """Validate identifiers, relations, endpoints, and privacy before rendering."""

    required = {"entities", "activities", "agents", "relations"}
    if set(records) != required:
        raise ValueError(
            "PROV records must contain entities, activities, agents, and relations"
        )
    collections = {
        "entity": records["entities"],
        "activity": records["activities"],
        "agent": records["agents"],
    }
    if not all(isinstance(value, Mapping) for value in collections.values()):
        raise ValueError(
            "PROV entity, activity, and agent collections must be mappings"
        )
    identifiers = [identifier for value in collections.values() for identifier in value]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate PROV identifier across record kinds")

    def private_fields(value: Any, location: str = "records") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if _private_key(key) and item != _OMISSION:
                    raise ValueError(
                        f"private unredacted field in PROV records: {location}.{key}"
                    )
                private_fields(item, f"{location}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                private_fields(item, f"{location}[{index}]")

    private_fields(records)
    endpoint_fields = {
        "used": (("activity", "activity"), ("entity", "entity")),
        "wasGeneratedBy": (("entity", "entity"), ("activity", "activity")),
        "wasAssociatedWith": (("activity", "activity"), ("agent", "agent")),
        "wasDerivedFrom": (("generated_entity", "entity"), ("used_entity", "entity")),
        "specializationOf": (
            ("specific_entity", "entity"),
            ("general_entity", "entity"),
        ),
    }
    if not isinstance(records["relations"], (list, tuple)):
        raise ValueError("PROV relations must be a list")
    for relation in records["relations"]:
        if not isinstance(relation, Mapping):
            raise ValueError("PROV relation must be a mapping")
        relation_type = str(relation.get("type", ""))
        fields = endpoint_fields.get(relation_type)
        if fields is None:
            raise ValueError(f"unsupported PROV relation: {relation_type}")
        for field, collection in fields:
            endpoint = relation.get(field)
            if endpoint not in collections[collection]:
                raise ValueError(
                    f"dangling PROV relation endpoint: {relation_type}.{field}={endpoint}"
                )


def render_prov_records(
    records: Mapping[str, Any], *, output_format: str = "prov-json"
) -> dict[str, Any]:
    """Render validated generic observed records as deterministic W3C PROV."""

    normalized_format = output_format.strip().lower().replace("_", "-")
    aliases = {
        "prov-json": "prov-json",
        "w3c-prov-json": "prov-json",
        "json-ld": "json-ld",
        "jsonld": "json-ld",
        "prov-o-json-ld": "json-ld",
    }
    resolved_format = aliases.get(normalized_format)
    if resolved_format is None:
        raise ValueError("output_format must be 'prov-json' or 'json-ld'")
    _validate_generic_records(records)
    document = (
        _prov_json_document(records)
        if resolved_format == "prov-json"
        else _json_ld_document(records)
    )
    receipt: dict[str, Any] = {
        "schema_version": "lunar.provenance-export/v1",
        "format": resolved_format,
        "media_type": (
            "application/provenance+json"
            if resolved_format == "prov-json"
            else "application/ld+json"
        ),
        "standard": "W3C PROV",
        "prospective_is_observation": False,
        "document": document,
    }
    receipt["digest"] = stable_hash(receipt)
    return receipt


def export_w3c_provenance(
    planner_result: Mapping[str, Any],
    *,
    reconciliation: Mapping[str, Any] | None = None,
    output_format: str = "prov-json",
) -> dict[str, Any]:
    """Export one planner result as deterministic W3C PROV-JSON or PROV-O JSON-LD.

    The returned wrapper is a Lunar transport receipt. ``document`` is the
    standards-based payload. Export is pure and read-only; it neither persists
    files nor upgrades planned components to observed execution.
    """

    records = planner_result_to_prov_records(
        planner_result, reconciliation=reconciliation
    )
    receipt = render_prov_records(records, output_format=output_format)
    receipt["schema_version"] = "lunar.planner.w3c-provenance-export/v1"
    receipt.pop("digest")
    receipt["digest"] = stable_hash(receipt)
    return receipt
