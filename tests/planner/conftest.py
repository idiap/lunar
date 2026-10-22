# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Planner-test trust root for authenticated quality fixtures.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import pytest

TEST_ONLY_QUALITY_KEY = "lunar-public-test-fixture-key-not-for-production"


@pytest.fixture(autouse=True)
def _test_only_quality_attestation_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production fail-closed behavior while enabling signed test receipts."""

    monkeypatch.setenv("LUNAR_QUALITY_ATTESTATION_KEY", TEST_ONLY_QUALITY_KEY)


@pytest.fixture(autouse=True)
def _explicit_neutral_selection():
    """Retained generic tests use an explicit in-memory package, never a production default."""
    from lunar_planner.config import PlannerConfig, bind_planner
    from lunar_planner.ports import PlannerPorts
    from tests.planner.neutral_fixture import NeutralSurface

    with bind_planner(
        PlannerConfig(
            context_identity=("test-owner", "neutral-inventory", "version-1")
        ),
        PlannerPorts(surface=NeutralSurface()),
    ):
        yield
