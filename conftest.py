# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest policy for opt-in long-running tests."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

EXPENSIVE_MODULES = frozenset(
    {
        "tests/evaluation/test_dialogue_workflow_benchmark.py",
        "tests/framework/test_computational_skill_readiness_audit.py",
        "tests/framework/test_skill_test_coverage.py",
        "tests/framework/test_workflow_control_registry.py",
        "tests/pharmaceutical_process/test_benchmark_harness.py",
        "tests/planner/test_provider_governance_hardening.py",
        "tests/planner/test_melanoma_sequential_quality_benchmark.py",
        "tests/reporting/test_fifth_manuscript_update_coordinator.py",
        "tests/reporting/test_notebooklm_visual_abstract.py",
        "tests/skills/test_causal_agents_catalog.py",
        "tests/skills/test_ported_skill_runtime_recovery.py",
        "tests/skills/test_skill_operation_profiles.py",
        "tests/workflows/test_prism_flow_generation.py",
        "tests/workflows/test_scenario11mod_reporting.py",
        "tests/workflows/test_scenario12_reporting.py",
        "tests/workflows/test_scenario13_analysis_consistency.py",
        "tests/workflows/test_scenario13_expert_publication.py",
        "tests/workflows/test_scenario13_reporting.py",
        "tests/workflows/test_scenario13_statistical_validity.py",
        "tests/workflows/test_scenario13_validation_followup.py",
        "tests/workflows/test_scenario14_multisolver_context.py",
        "tests/workflows/test_scenario14_multisolver_portfolio.py",
        "tests/workflows/test_scenario14_reporting.py",
    }
)

EXPENSIVE_TESTS = frozenset(
    {
        "tests/planner/test_capability_profiles.py::test_catalog_registry_and_reviewed_profile_plan_recovered_closure_assessor",
        "tests/planner/test_universal_component_corpus.py::test_frozen_corpus_is_current",
    }
)

SLOW_MODULES = frozenset(
    {
        "tests/framework/test_generated_workflow_execution_hooks.py",
        "tests/framework/test_mcp_skill_registry.py",
        "tests/framework/test_reasoning_logs.py",
        "tests/framework/test_reasoning_flow_maps.py",
        "tests/framework/test_repository_integration_contracts.py",
        "tests/framework/test_skill_conversation_probes.py",
        "tests/framework/test_skill_descriptors.py",
        "tests/framework/test_documentation_quality_audit.py",
        "tests/framework/test_skill_package_readmes.py",
        "tests/framework/test_skill_package_template.py",
        "tests/framework/test_skill_specificity_mock_audit.py",
        "tests/framework/test_workflow_runtime_binding_audit.py",
        "tests/integrations/bioconductor/test_builder_schemas.py",
        "tests/integrations/bioconductor/test_search_release_index.py",
        "tests/mcp_backend/test_scientific_tools.py",
        "tests/pharmaceutical_process/test_planner_workflows.py",
        "tests/planner/test_answer_trust_lifecycle_integration.py",
        "tests/planner/test_bioconductor_package_planning.py",
        "tests/planner/test_external_agentic_planner_generalization.py",
        "tests/planner/test_external_agentic_surface_integration.py",
        "tests/planner/test_planner_archetypes.py",
        "tests/planner/test_planner_adaptation.py",
        "tests/planner/test_planner_contracts.py",
        "tests/planner/test_planner_entrypoint.py",
        "tests/planner/test_post_plan_verification_profile_integration.py",
        "tests/planner/test_two_freeze_orchestration.py",
        "tests/planner/test_universal_component_corpus.py",
        "tests/skills/test_abstractive_rag_catalog.py",
        "tests/skills/test_bioreason_formal_reasoning_catalog.py",
        "tests/workflows/test_scenario10_reporting.py",
        "tests/workflows/test_scenario13mod_lmdln.py",
    }
)

SLOW_TESTS = frozenset(
    {
        "tests/evaluation/test_external_capability_benchmark.py::test_schema_digests_manifest_and_lexical_firewall",
        "tests/planner/test_capability_profiles.py::test_configured_host_attaches_reviewed_profiles_and_plans_real_unavailable_bindings",
        "tests/planner/test_external_kb_query_benchmark.py::test_external_kb_development_cases_pass_public_planner",
        "tests/planner/test_provider_family_infrastructure.py::test_full_benchmark_runs_through_planner_with_contract_critic",
        "tests/source_queries/test_external_query_integration.py::test_five_planner_first_commands_reach_every_reviewed_nl_route",
    }
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add explicit opt-ins for tests unsuitable for the default feedback loop."""

    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run offline application E2E tests against LUNAR_E2E_DATABASE_URL",
    )
    parser.addoption(
        "--run-prism-llm-e2e",
        action="store_true",
        default=False,
        help="run all registered genuine PRISM provider tests (also requires --run-e2e)",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="run tests marked slow (expensive tests remain skipped)",
    )
    parser.addoption(
        "--run-expensive",
        action="store_true",
        default=False,
        help="run tests marked slow or expensive",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip long-running classes by default while keeping them directly runnable."""

    run_expensive = config.getoption("--run-expensive")
    run_e2e = config.getoption("--run-e2e")
    run_prism_llm_e2e = config.getoption("--run-prism-llm-e2e")
    run_slow = config.getoption("--run-slow") or run_expensive
    skip_slow = pytest.mark.skip(reason="needs --run-slow or --run-expensive")
    skip_expensive = pytest.mark.skip(reason="needs --run-expensive")
    skip_e2e = pytest.mark.skip(reason="needs --run-e2e")

    for item in items:
        module = item.nodeid.partition("::")[0]
        if module.startswith("tests/e2e/") and not item.get_closest_marker("e2e"):
            raise pytest.UsageError(
                f"E2E test is missing @pytest.mark.e2e: {item.nodeid}"
            )
        node = item.nodeid.partition("[")[0]
        is_expensive_module = (
            module in EXPENSIVE_MODULES
            or module.startswith("tests/runtime_bindings/")
            or "benchmark" in module.rsplit("/", 1)[-1]
            or "end_to_end" in module.rsplit("/", 1)[-1]
        )
        if is_expensive_module or node in EXPENSIVE_TESTS:
            item.add_marker(pytest.mark.expensive)
        elif module in SLOW_MODULES or node in SLOW_TESTS:
            item.add_marker(pytest.mark.slow)

        if item.get_closest_marker("live") and not run_prism_llm_e2e:
            item.add_marker(
                pytest.mark.skip(reason="needs --run-e2e and --run-prism-llm-e2e")
            )
        elif item.get_closest_marker("e2e") and not run_e2e:
            item.add_marker(skip_e2e)
        elif item.get_closest_marker("expensive") and not run_expensive:
            item.add_marker(skip_expensive)
        elif item.get_closest_marker("slow") and not run_slow:
            item.add_marker(skip_slow)


def pytest_configure(config: pytest.Config) -> None:
    application_test_database = os.getenv("LUNAR_TEST_DATABASE_URL")
    if application_test_database and "test" in application_test_database.lower():
        os.environ["DATABASE_URL"] = application_test_database
    run_e2e = config.getoption("--run-e2e")
    run_prism_llm_e2e = config.getoption("--run-prism-llm-e2e")
    if run_prism_llm_e2e and not run_e2e:
        raise pytest.UsageError("--run-prism-llm-e2e also requires --run-e2e")
    if not run_e2e:
        return
    database_url = os.getenv("LUNAR_E2E_DATABASE_URL")
    if not database_url:
        raise pytest.UsageError(
            "--run-e2e requires LUNAR_E2E_DATABASE_URL for an isolated PostgreSQL database"
        )
    if "test" not in database_url.lower():
        raise pytest.UsageError(
            "LUNAR_E2E_DATABASE_URL must identify an isolated test database"
        )
    os.environ["DATABASE_URL"] = database_url
    os.environ["LUNAR_ALLOW_LIVE_NETWORK"] = "0"
    if run_prism_llm_e2e:
        required = (
            "LUNAR_E2E_MODEL_PROVIDER",
            "LUNAR_E2E_MODEL_ID",
            "LUNAR_E2E_MODEL_API_KEY",
        )
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise pytest.UsageError(
                "--run-prism-llm-e2e requires " + ", ".join(missing)
            )
        raw_config = os.getenv("LUNAR_E2E_MODEL_CONFIG", "{}")
        try:
            model_config = json.loads(raw_config)
        except json.JSONDecodeError as exc:
            raise pytest.UsageError(
                "LUNAR_E2E_MODEL_CONFIG must be valid JSON"
            ) from exc
        if not isinstance(model_config, dict):
            raise pytest.UsageError("LUNAR_E2E_MODEL_CONFIG must contain a JSON object")
    try:
        import asyncpg

        async def check_database() -> None:
            connection = await asyncpg.connect(database_url, timeout=5)
            await connection.close()

        asyncio.run(check_database())
    except Exception as exc:
        raise pytest.UsageError(
            f"PostgreSQL is unavailable at LUNAR_E2E_DATABASE_URL: {exc}"
        ) from exc
