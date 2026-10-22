#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Exercise Lunar's planner module and resources outside the application checkout."""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _assert_no_host_imports(package_root: Path) -> None:
    """Assert no host imports."""
    violations: list[str] = []
    for source in sorted(package_root.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(
                name.split(".")[0] in {"catalog", "app", "bioagents_planner"}
                for name in names
            ):
                violations.append(f"{source.name}:{node.lineno}")
    if violations:
        raise RuntimeError("static catalog imports: " + ", ".join(violations))


def verify(planner_root: Path) -> dict[str, str]:
    """Verify."""
    planner_root = planner_root.resolve(strict=True)
    _assert_no_host_imports(planner_root)
    with tempfile.TemporaryDirectory(prefix="lunar-planner-module-") as raw:
        temporary = Path(raw).resolve()
        source_copy = temporary / "lunar_planner"
        shutil.copytree(
            planner_root,
            source_copy,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        probe = r"""
import json
from importlib.resources import files
from pathlib import Path
import importlib, importlib.abc, pkgutil, sys
class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"catalog", "app", "bioagents_planner"}:
            raise AssertionError("host import attempted: " + fullname)
sys.meta_path.insert(0, NoHost())
sys.path.insert(0, sys.argv[1])
import lunar_planner
assert Path(lunar_planner.__file__).resolve().parent == Path(sys.argv[1]) / "lunar_planner"
for module in pkgutil.iter_modules(lunar_planner.__path__):
    importlib.import_module("lunar_planner." + module.name)
from lunar_planner import run_planner_request
from lunar_planner.config import PlannerConfig, bind_planner
from lunar_planner.ports import PlannerPorts
from lunar_planner.answer_trust import ASSESSMENT_SCHEMA, READINESS_SCHEMA
from lunar_planner.answer_trust_calibration import calibrate_answer_trust
from lunar_planner.workflow_economics import (
    build_workflow_economics_report,
    compile_work_units,
    estimate_workflow_effort,
    load_workflow_economics_policy,
)
from lunar_planner.usage_accounting import estimate_workflow_resources
from lunar_planner.pricing import seal_price_book
from lunar_planner.budget_accounting import BudgetLedger
from lunar_planner.config import current_config, resource_path
from lunar_planner.post_plan_verification import SCHEMA_VERSION as POST_PLAN_SCHEMA_VERSION

assert current_config().repository_root is None
assert resource_path("schemas", "planner-request-v1.schema.json").is_file()
assert resource_path("schemas", "planner-post-plan-evidence-verification-v1.schema.json").is_file()
assert resource_path("schemas", "planner-answer-control-readiness-v1.schema.json").is_file()
assert resource_path("schemas", "planner-answer-trust-assessment-v1.schema.json").is_file()
assert resource_path("schemas", "planner-claim-trust-assessment-v1.schema.json").is_file()
assert resource_path("schemas", "planner-generative-transformation-receipt-v1.schema.json").is_file()
for schema_name in (
    "planner-workflow-comparator-disposition-v1.schema.json",
    "planner-workflow-workload-inventory-v1.schema.json",
    "planner-workflow-effort-estimate-v1.schema.json",
    "planner-workflow-effort-assessment-v1.schema.json",
    "planner-workflow-resource-estimate-v1.schema.json",
    "planner-workflow-resource-usage-v1.schema.json",
    "planner-workflow-cost-reconciliation-v1.schema.json",
    "planner-workflow-economics-report-v1.schema.json",
    "planner-price-book-v1.schema.json",
):
    assert resource_path("schemas", schema_name).is_file()
assert resource_path("profiles", "new-workflow.yaml").is_file()
assert resource_path("profiles", "post-plan-reasoning-verification.yaml").is_file()
assert resource_path("profiles", "answer-control-readiness.yaml").is_file()
assert resource_path("profiles", "workflow-economics.yaml").is_file()
assert resource_path("hooks", "planner-hooks.yaml").is_file()
assert resource_path("policies", "answer-trust-policy-v1.json").is_file()
assert resource_path("policies", "workflow-economics-policy-v1.json").is_file()
assert POST_PLAN_SCHEMA_VERSION == "lunar.planner.post-plan-evidence-verification/v1"
assert READINESS_SCHEMA == "lunar.planner.answer-control-readiness/v1"
assert ASSESSMENT_SCHEMA == "lunar.planner.answer-trust-assessment/v1"
assert callable(calibrate_answer_trust)
assert callable(compile_work_units)
assert callable(estimate_workflow_effort)
assert callable(estimate_workflow_resources)
assert callable(build_workflow_economics_report)
assert callable(seal_price_book)
assert BudgetLedger.__name__ == "BudgetLedger"
assert load_workflow_economics_policy()["execution_allowed"] is False
assert (files("lunar_planner") / "skills" / "post-plan-evidence-grounding-verifier" / "SKILL.md").is_file()
surface = {
    "schema_version": "lunar.planner.surface-index/v1",
    "authority": "derived_navigation_only",
    "counts": {},
    "workflow_packages": [],
    "subworkflows": [],
    "skills": [],
}
class InventoryCatalog:
    def snapshot(self):
        return surface
surface["skills"] = [{"id":"stock-count","name":"stock-count","kind":"skill",
    "scope":"package","description":"Summarize warehouse item counts",
    "source_path":"skills/stock.json","content_digest":"sha256:"+"1"*64,
    "interface":{"inputs":{"status":"documented","items":[]},
                 "outputs":{"status":"documented","items":[]}},
    "authority":{},"invocation_posture":"instruction_only"}]
assert run_planner_request("Build an inventory workflow")["status"] == "selection_required"
with bind_planner(PlannerConfig(context_identity=("owner","warehouse","version-1")),
                  PlannerPorts(surface=InventoryCatalog())):
    result = run_planner_request(
        "Build a workflow that reconciles warehouse item counts and reports discrepancies.",
        desired_outputs=("inventory discrepancies",),
    )
    assert result["executed"] is False
assert result["mode"] == "new_workflow"
assert result["resource_scan"]["snapshot_posture"] == "host_surface_only"
assert result["profile"].startswith("planner-resource://")
print(json.dumps({"mode": result["mode"], "status": result["status"]}))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe, str(temporary)],
            cwd=temporary,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        result = json.loads(completed.stdout)
        return {"module": "lunar_planner", **result}


def main() -> int:
    """Run the module entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--planner-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "app/backend/lunar_planner",
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.planner_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
