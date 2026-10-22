# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Every baseline workflow retains its typed fixture inputs and report contract."""

import uuid
import pytest
from catalog.integrations.domain_package.runtime.adapters import (
    ADAPTERS,
    validate_run_request,
)
from catalog.integrations.domain_package.runtime.schemas import PrismRunRequest
from catalog.integrations.domain_package.runtime.runtime import RuntimeContext
from catalog.integrations.domain_package.runtime.report_packages import (
    build_verified_report_package,
)


@pytest.mark.parametrize("workflow_id", sorted(ADAPTERS))
def test_every_workflow_prepares_and_verifies_its_reviewed_fixture(
    workflow_id, tmp_path
):
    """Verify every workflow prepares and verifies its reviewed fixture."""
    adapter, inputs = validate_run_request(
        workflow_id, PrismRunRequest(ai_model_id=uuid.uuid4())
    )
    context = RuntimeContext(adapter, str(uuid.uuid4()), tmp_path / "run", "fixture")
    prepared = adapter.fixture_preparer(context, inputs, "fixture")
    assert prepared.entry_argument_name == adapter.request_argument
    assert prepared.request_digest.startswith("sha256:")
    assert prepared.analysis_results
    package = build_verified_report_package(
        workflow_id=workflow_id,
        context=context,
        analysis_results=prepared.analysis_results,
        compact_prism_input=prepared.value,
        raw_narrative_slots=[],
        allowed_slot_ids=set(),
        provenance={},
    )
    assert package.verification.status == "passed"
    assert package.markdown
    assert context.artifacts
