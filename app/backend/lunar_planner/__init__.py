# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Portable planner contracts, routing, quality, and evidence helpers.

All routing and compilation exports are planning-only.  Persistence is an
explicit caller-authorized operation; no export executes scientific skills,
workflow CLIs, external actions, subprocesses, or platform goal functions.
Low-level assessment and final-decision constructors in ``staged_routing`` are
internal primitives and intentionally absent from ``__all__``. Hosts provide
catalogs, runtime bindings, domain planners, and external sources via ports.
"""

from .config import (
    PlannerConfig,
    PlannerPaths,
    bind_planner as bind_planner,
    configure,
    current_config,
)
from .ports import (
    PlannerPorts,
    configure_ports,
    current_ports,
    plan_skill_operations,
    resolve_runtime_binding,
)
from .capability_profiles import (
    BINDING_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION as SKILL_CAPABILITY_PROFILE_SCHEMA_VERSION,
    derive_skill_posture,
    load_capability_profiles,
    plan_profile_operations,
    record_observed_invocation,
    validate_capability_profile,
    validate_runtime_binding,
    verification_method_for,
)
from .next_steps import assess_closure_readiness, build_next_step_guidance
from .delivery_package import (
    DeliveryPackageError,
    assess_delivery_package_requirement,
    build_delivery_package,
    plan_delivery_package,
)
from .post_plan_verification import (
    build_post_plan_verification,
    build_verification_summary_event,
    selectively_invalidate_verification,
)
from .answer_trust import (
    AnswerTrustError,
    DEFAULT_POLICY as DEFAULT_ANSWER_TRUST_POLICY,
    assess_answer_trust,
    build_answer_control_readiness,
    build_readiness_card,
    build_trust_card,
    invalidate_answer_trust,
    resolve_answer_trust_rollout,
)
from .answer_trust_calibration import calibrate_answer_trust
from .workflow_economics import (
    WorkflowEconomicsError,
    build_workflow_cost_reconciliation,
    build_workflow_economics_report,
    build_workflow_effort_card,
    build_workflow_resource_usage,
    compile_work_units,
    estimate_workflow_effort,
    invalidate_workflow_effort,
    load_workflow_economics_policy,
    resolve_workflow_economics_rollout,
    validate_comparator_equivalence,
)
from .workflow_economics_calibration import (
    build_resource_profile,
    calibrate_workflow_effort,
)
from .usage_accounting import (
    aggregate_usage,
    allocate_shared_line,
    estimate_workflow_resources,
    normalize_meter_receipt,
    normalize_provider_usage,
)
from .pricing import convert_nano, price_usage_lines, resolve_rate, seal_price_book
from .budget_accounting import BudgetLedger

from .archetypes import build_archetype_index, load_surface_index, match_archetypes
from .benchmark import BenchmarkPlanError, plan_paired_skill_benchmark
from .contracts import (
    PlannerContractError,
    PlannerValidationReport,
    load_planner_yaml,
    load_profile,
    load_schema,
    require_valid_contract,
    validate_contract,
    validate_profile,
)
from .control import ControlPlaneError, project_milestones, reconcile_control_plane
from .entrypoint import (
    route_planner_request,
    run_planner_request,
    run_planner_request_with_test_surface,
)
from .quality_evaluation import (
    ConfiguredCommandQualityAdapter,
    QualityAdapterLimits,
    QualityEvaluatorAdapter,
    evaluate_with_adapter,
    prepare_quality_evaluation_packet,
    reconcile_quality_evaluator_results,
)
from .quality_governance import (
    RISK_POLICIES,
    classify_quality_policy,
    criterion_transition_errors,
    material_quality_elicitation,
    normalize_consequence_profile,
    revise_quality_contract,
    update_quality_question_states,
)
from .staged_routing import (
    adjudicate,
    bind_inputs,
    build_elicitation,
    build_workflow_refinement_cycle,
    build_workflow_draft,
    gather_candidates,
    instantiate_workflow,
    normalize_request,
    plan_capability_gaps,
    plan_stages,
    preflight,
    reduce_dialogue_state,
    validate_continuation,
)
from .quality_authorization import (
    assess_authorized_workflow_economics,
    issue_workflow_economics_authorization,
    persist_authorized_workflow_economics,
)

from .provenance import (
    build_invalidation_report,
    export_w3c_provenance,
    planner_result_to_prov_records,
    propagate_invalidation,
    reconcile_components,
    redact_private_values,
    render_prov_records,
)
from .store import (
    IdempotencyCollisionError,
    IntegrityError,
    PathConfinementError,
    PlannerStore,
    PlannerStoreError,
)

__all__ = [
    "PlannerConfig",
    "PlannerPaths",
    "PlannerPorts",
    "configure",
    "configure_ports",
    "current_config",
    "current_ports",
    "resolve_runtime_binding",
    "plan_skill_operations",
    "BINDING_SCHEMA_VERSION",
    "SKILL_CAPABILITY_PROFILE_SCHEMA_VERSION",
    "derive_skill_posture",
    "load_capability_profiles",
    "plan_profile_operations",
    "record_observed_invocation",
    "validate_capability_profile",
    "validate_runtime_binding",
    "verification_method_for",
    "BenchmarkPlanError",
    "AnswerTrustError",
    "WorkflowEconomicsError",
    "ControlPlaneError",
    "DeliveryPackageError",
    "IdempotencyCollisionError",
    "IntegrityError",
    "PathConfinementError",
    "PlannerContractError",
    "PlannerStore",
    "PlannerStoreError",
    "PlannerValidationReport",
    "DEFAULT_ANSWER_TRUST_POLICY",
    "ConfiguredCommandQualityAdapter",
    "QualityAdapterLimits",
    "QualityEvaluatorAdapter",
    "RISK_POLICIES",
    "assess_closure_readiness",
    "assess_answer_trust",
    "assess_delivery_package_requirement",
    "build_invalidation_report",
    "build_next_step_guidance",
    "build_post_plan_verification",
    "build_answer_control_readiness",
    "build_readiness_card",
    "build_trust_card",
    "calibrate_answer_trust",
    "calibrate_workflow_effort",
    "build_resource_profile",
    "build_workflow_cost_reconciliation",
    "build_workflow_economics_report",
    "build_workflow_effort_card",
    "build_workflow_resource_usage",
    "compile_work_units",
    "estimate_workflow_effort",
    "estimate_workflow_resources",
    "invalidate_workflow_effort",
    "load_workflow_economics_policy",
    "resolve_workflow_economics_rollout",
    "validate_comparator_equivalence",
    "normalize_provider_usage",
    "normalize_meter_receipt",
    "aggregate_usage",
    "allocate_shared_line",
    "seal_price_book",
    "resolve_rate",
    "price_usage_lines",
    "convert_nano",
    "BudgetLedger",
    "issue_workflow_economics_authorization",
    "assess_authorized_workflow_economics",
    "persist_authorized_workflow_economics",
    "build_verification_summary_event",
    "build_delivery_package",
    "export_w3c_provenance",
    "render_prov_records",
    "build_archetype_index",
    "load_planner_yaml",
    "load_profile",
    "load_schema",
    "load_surface_index",
    "match_archetypes",
    "plan_paired_skill_benchmark",
    "plan_delivery_package",
    "planner_result_to_prov_records",
    "project_milestones",
    "propagate_invalidation",
    "reconcile_components",
    "reconcile_control_plane",
    "redact_private_values",
    "require_valid_contract",
    "route_planner_request",
    "run_planner_request",
    "run_planner_request_with_test_surface",
    "normalize_request",
    "plan_capability_gaps",
    "gather_candidates",
    "instantiate_workflow",
    "adjudicate",
    "bind_inputs",
    "build_elicitation",
    "build_workflow_refinement_cycle",
    "build_workflow_draft",
    "classify_quality_policy",
    "criterion_transition_errors",
    "evaluate_with_adapter",
    "material_quality_elicitation",
    "normalize_consequence_profile",
    "prepare_quality_evaluation_packet",
    "reconcile_quality_evaluator_results",
    "preflight",
    "plan_stages",
    "reduce_dialogue_state",
    "revise_quality_contract",
    "update_quality_question_states",
    "validate_continuation",
    "selectively_invalidate_verification",
    "invalidate_answer_trust",
    "resolve_answer_trust_rollout",
    "validate_contract",
    "validate_profile",
]
