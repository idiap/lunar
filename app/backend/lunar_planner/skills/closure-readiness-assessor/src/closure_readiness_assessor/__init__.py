# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Skill-owned closure-readiness operation boundary.

Purpose: Decide whether a live planner state warrants a user-facing next-step suggestion by locating a concrete unresolved input, review, acceptance, repair, or gap obligation. Use near the end of a planning turn; omit suggestions when the request is closed, denied, merely informational, or lacks an actionable closure target. This module's responsibility is to support the skill implementation while preserving its documented contract. Key concepts: planner, declared authority, and deterministic execution. Boundary: inputs, outputs, evidence, and failures remain governed by the `closure-readiness-assessor` skill contract. Principal I/O: consumes contract-defined values and emits contract-defined values.
"""

from lunar_planner.next_steps import assess_closure_readiness

__all__ = ["assess_closure_readiness"]
