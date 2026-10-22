# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit request context for migrated MCP unit tests."""

import pytest
from uuid import uuid4
from domain_packages.context import PackageContext, bind_context
from lunar_planner.config import PlannerConfig, bind_planner
from lunar_planner.ports import PlannerPorts
from tests.planner.neutral_fixture import NeutralSurface


@pytest.fixture(autouse=True)
def selected_context():
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    with (
        bind_context(context),
        bind_planner(
            PlannerConfig(
                context_identity=tuple(
                    str(value)
                    for value in (
                        context.user_id,
                        context.package_id,
                        context.version_id,
                    )
                )
            ),
            PlannerPorts(surface=NeutralSurface()),
        ),
    ):
        yield
