# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Read-only selected-package policy ports; the generic host retains authority."""

from collections.abc import Mapping
from .ports import current_ports


def policy_value(operation, inputs, default=None):
    """Request a domain policy value only from the current selected provider."""
    provider = current_ports().domain_policy
    return default if provider is None else provider.evaluate(operation, inputs)


def build_report_workflow_inheritance(command_text, surface, **kwargs):
    """Ask the selected domain for optional report controls without granting authority."""
    result = policy_value(
        "report_inheritance",
        {"command_text": command_text, "surface": surface, **kwargs},
    )
    if result is not None and not isinstance(result, Mapping):
        raise ValueError("invalid package report policy")
    return result


def project_report_inheritance_plans(inheritance):
    """Project generic workflow control fields from a domain-supplied artifact."""
    return {
        key: list(inheritance.get(key, ()))
        for key in (
            "inheritance_sources",
            "section_plan",
            "control_plan",
            "critic_plan",
            "release_gate_plan",
            "adaptation_decisions",
            "communication_plan",
        )
    }
