# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Runtime preparation must reject undeployed native capabilities."""

from unittest.mock import patch
import pytest
from domain_packages.worker.preparation import check_capabilities
from domain_packages.worker.sandbox import WorkerUnavailable


def manifest(required):
    return {
        "runtime": {"workflows": [{"metadata": {"required_capabilities": required}}]}
    }


def test_native_capability_missing_rejects_preparation():
    with patch(
        "domain_packages.worker.preparation.subprocess.check_output",
        return_value="backend.sympy",
    ):
        with pytest.raises(WorkerUnavailable, match="backend.isabelle"):
            check_capabilities(
                manifest(["backend.sympy", "backend.isabelle"]), "sha256:test"
            )


def test_native_capability_present_accepts_preparation():
    with patch(
        "domain_packages.worker.preparation.subprocess.check_output",
        return_value="backend.sympy,backend.lean",
    ):
        check_capabilities(manifest(["backend.sympy"]), "sha256:test")


def test_reasoning_only_needs_no_native_probe():
    with patch("domain_packages.worker.preparation.subprocess.check_output") as probe:
        check_capabilities(manifest([]), "sha256:test")
        probe.assert_not_called()
