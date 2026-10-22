# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402
# Imports follow sys.path setup for standalone execution.

"""Test completed artifact packager module.

Purpose: Assemble generated files from a completed task into a deterministic delivery archive with an integrity manifest, one W3C PROV descriptor per file, and planner-level provenance. Use only when file-based delivery is requested or multiple user-facing files need consolidated delivery; never package partial work as final. This module's responsibility is to verify observable content, failure behavior, invariants, and interface stability. Key concepts: planner, declared authority, and deterministic execution. Boundary: inputs, outputs, evidence, and failures remain governed by the `completed-artifact-packager` skill contract. Principal I/O: consumes contract-defined values and emits contract-defined values.
"""

from pathlib import Path
import sys
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / "src"), str(SKILL.parents[2])]
from completed_artifact_packager import (  # pyright: ignore[reportMissingImports]
    build_delivery_package,
)


def test_content_package_manifest(tmp_path):
    """Verify content package manifest."""
    item = tmp_path / "result.txt"
    item.write_text("grounded", encoding="utf-8")
    result = build_delivery_package(
        {"status": "complete"}, [item], output_dir=tmp_path / "out", requested=True
    )
    assert (result["status"], result["manifest"]["artifact_count"]) == (
        "ready_for_user",
        1,
    )


def test_invalid_incomplete_result_is_rejected(tmp_path):
    """Verify invalid incomplete result is rejected."""
    item = tmp_path / "result.txt"
    item.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        build_delivery_package(
            {"status": "running"}, [item], output_dir=tmp_path / "out", requested=True
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("content", [b"alpha", b"beta"])
def test_property_content_digest_tracks_bytes(tmp_path, content):
    """Verify property content digest tracks bytes."""
    item = tmp_path / "result.bin"
    item.write_bytes(content)
    result = build_delivery_package(
        {"status": "complete"},
        [item],
        output_dir=tmp_path / content.decode(),
        requested=True,
    )
    assert result["manifest"]["artifacts"][0]["size_bytes"] == len(content)
