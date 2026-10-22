# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Public live reasoning contracts."""

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

import pytest
from pydantic import ValidationError
from platform_runtime.reasoning_log import validate_reasoning_log
from prism_runs.reasoning import (
    HelperOutput,
    LEGACY_ICONS,
    ICON_IDS,
    STATUS_MAP,
    MISSING_RATIONALE,
    Presentation,
    ReasoningEntry,
    canonical_snapshot,
    project_source,
    source_digest,
)


def entry(status="running", **kwargs):
    source = project_source(stage="analysis", status=status, **kwargs)
    return ReasoningEntry(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        sequence=1,
        source_event_key="stage:1",
        event_kind="stage",
        observed_at=datetime.now(timezone.utc),
        source=source,
        source_digest=source_digest(source),
    )


@pytest.mark.parametrize("status", STATUS_MAP)
def test_reasoning_log_canonical(status):
    row = entry(status)
    validate_reasoning_log(canonical_snapshot(str(row.run_id), "running", [row]))
    assert row.source.rationale_summary == MISSING_RATIONALE


def test_reasoning_log_projection_excludes_nested_sensitive_payloads():
    row = entry(
        result={
            "summary": {"patient_id": "secret"},
            "scratchpad": "secret",
            "rationale_summary": "Based on the declared checks.",
            "limitations": [
                {"api_key": "secret"},
                # Construct a synthetic sensitive path without a local dependency.
                str(PurePosixPath("/", "Users", "example-user", "data")),
                "Limited evidence.",
            ],
        }
    )
    assert "secret" not in row.model_dump_json()
    assert row.source.limitations == ["Limited evidence."]
    assert row.source.rationale_summary == "Based on the declared checks."
    with pytest.raises(ValidationError, match="digest mismatch"):
        ReasoningEntry.model_validate({**row.model_dump(), "source_digest": "wrong"})


@pytest.mark.parametrize("icon", ICON_IDS)
def test_reasoning_log_presentation(icon):
    assert Presentation(
        status="ready", helper_text="Checking has completed.", icon_id=icon
    )


@pytest.mark.parametrize(
    "fields",
    [
        dict(icon_id="unknown"),
        dict(svg="bad"),
        dict(status="ready", helper_text="<script>bad</script>"),
        dict(status="pending", helper_text="fabricated"),
        dict(status="unavailable"),
    ],
)
def test_reasoning_log_invalid_presentation(fields):
    with pytest.raises(ValidationError):
        Presentation(**fields)


def test_reasoning_log_icon_catalog_matches_frontend():
    import re
    from pathlib import Path

    frontend = (
        Path(__file__).resolve().parents[2] / "app/frontend/src/lib/prism-reasoning.js"
    ).read_text()
    declared = re.search(r"reasoningIconIds = \[(.*?)\]", frontend).group(1)
    assert tuple(re.findall(r'"([^\"]+)"', declared)) == ICON_IDS


@pytest.mark.parametrize("legacy, current", LEGACY_ICONS.items())
def test_reasoning_log_legacy_icons_only_supported_for_persisted_presentations(
    legacy, current
):
    assert (
        Presentation(
            status="ready", helper_text="Analysis completed.", icon_id=legacy
        ).icon_id
        == current
    )
    with pytest.raises(ValidationError):
        HelperOutput(helper_text="Analysis completed.", icon_id=legacy)
