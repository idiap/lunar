# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Preserve planning of the source exporter operation profiles without execution."""

import json
from pathlib import Path
from lunar_planner.capability_profiles import plan_profile_operations


def test_registered_export_operations_plan_without_execution():
    """Frozen actual source registrations retain all four exact export operations."""
    rows = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/export-operation-profiles.json"
        ).read_text()
    )
    for row in rows:

        class Registry:
            def resolve(self, logical_id, operation):
                assert logical_id == row["profile"]["skill_id"]
                return row["bindings"][operation]

        profile = row["profile"]
        result = plan_profile_operations(
            profile["skill_id"],
            profile["skill_digest"],
            {profile["skill_id"]: profile},
            Registry(),
            operation_ids=row["operations"],
        )
        assert result["status"] == "ready" and result["tasks"] == []
        assert {item["operation_id"] for item in result["invocations"]} == set(
            row["operations"]
        )
        assert all(
            item["executed"] is False and item["observed_receipt"] is None
            for item in result["invocations"]
        )
