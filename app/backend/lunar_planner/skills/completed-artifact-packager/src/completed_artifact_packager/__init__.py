# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Skill-owned completed-artifact packaging boundary.

Purpose: Assemble generated files from a completed task into a deterministic delivery archive with an integrity manifest, one W3C PROV descriptor per file, and planner-level provenance. Use only when file-based delivery is requested or multiple user-facing files need consolidated delivery; never package partial work as final. This module's responsibility is to support the skill implementation while preserving its documented contract. Key concepts: planner, declared authority, and deterministic execution. Boundary: inputs, outputs, evidence, and failures remain governed by the `completed-artifact-packager` skill contract. Principal I/O: consumes contract-defined values and emits contract-defined values.
"""

from lunar_planner.delivery_package import build_delivery_package

__all__ = ["build_delivery_package"]
