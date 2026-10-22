# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Generic skill helpers never read catalogs from the filesystem or execute tools."""

import json
from pathlib import Path
import subprocess
import sys

import pytest
from lunar_planner.navigation import reference_scan, reuse_review_packet
from tests.planner.neutral_fixture import surface


def test_nomination_and_review_keep_the_selected_identity_and_contract():
    result = reference_scan("Explain warehouse stock-count results")
    assert result["status"] == "requires_semantic_review" and not result["executed"]
    assert result["context_identity"] == [
        "test-owner",
        "neutral-inventory",
        "version-1",
    ]
    identity = surface()["skills"][0]["id"]
    review = reuse_review_packet("Explain warehouse stock-count results", [identity])
    assert review["review_candidates"] == surface()["skills"]
    assert review["review_verdict"] is None and not review["implementation_authorized"]
    review["review_candidates"].clear()
    assert reuse_review_packet("Explain stock counts", [identity])["review_candidates"]
    with pytest.raises(ValueError, match="absent"):
        reuse_review_packet("Explain stock counts", ["foreign-version-skill"])


@pytest.mark.parametrize(
    "skill,script",
    [
        ("workflow-reference-scout", "scan.py"),
        ("skill-reuse-critical-reasoner", "review.py"),
    ],
)
def test_snapshot_cli_works_outside_checkouts(tmp_path, skill, script):
    root = Path(__file__).resolve().parents[2]
    helper = root / "app/backend/lunar_planner/skills" / skill / "scripts" / script
    packet = {
        "context_identity": ["owner", "warehouse", "v1"],
        "surface": surface(),
        "objective": "Explain warehouse stock-count results",
        "candidate_ids": [surface()["skills"][0]["id"]],
    }
    result = subprocess.run(
        [sys.executable, "-I", str(helper)],
        input=json.dumps(packet),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["context_identity"] == packet["context_identity"]
    assert not output["executed"] and not output["external_actions_performed"]
    assert not list(tmp_path.iterdir())
