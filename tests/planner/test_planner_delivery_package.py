# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for completed-task artifact delivery packages.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations
from control_plane.packaging import package_completed_artifacts_tool
from domain_packages.context import PackageContext, bind_context
from domain_packages.storage import VersionStorage
from uuid import uuid4

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from lunar_planner.contracts import validate_contract
from lunar_planner.delivery_package import (
    DeliveryPackageError,
    assess_delivery_package_requirement,
    build_delivery_package,
    plan_delivery_package,
)
from lunar_planner.entrypoint import run_planner_request

SkillRegistryError = ValueError


def _completed_result() -> dict:
    """Completed result."""
    return {
        "mode": "direct_use",
        "status": "complete",
        "planner_receipt": {"digest": "sha256:" + "1" * 64},
        "delivery_package_policy": plan_delivery_package(
            "Return the generated files as a package with provenance."
        ),
    }


def test_planner_declares_package_policy_without_packaging() -> None:
    """Verify planner declares package policy without packaging."""
    explicit = plan_delivery_package("Bundle the report and tables for download")
    ordinary = plan_delivery_package("Explain the result in the chat")
    assert explicit["disposition"] == "required_when_complete"
    assert explicit["explicitly_requested"] is True
    assert ordinary["disposition"] == "conditional_on_artifact_set"
    assert ordinary["explicitly_requested"] is False

    result = run_planner_request("Explain the result in the chat")
    assert result["delivery_package_policy"]["explicitly_requested"] is False
    assert "archive_path" not in result["delivery_package_policy"]


def test_incomplete_task_defers_and_cannot_be_packaged(tmp_path: Path) -> None:
    """Verify incomplete task defers and cannot be packaged."""
    artifact = tmp_path / "draft.md"
    artifact.write_text("draft", encoding="utf-8")
    result = {**_completed_result(), "status": "needs_quality_review"}
    assessment = assess_delivery_package_requirement(result, [artifact])
    assert assessment["disposition"] == "defer"
    with pytest.raises(DeliveryPackageError, match="not complete"):
        build_delivery_package(result, [artifact], output_dir=tmp_path / "packages")


def test_single_unrequested_file_does_not_create_package(tmp_path: Path) -> None:
    """Verify single unrequested file does not create package."""
    artifact = tmp_path / "answer.md"
    artifact.write_text("answer", encoding="utf-8")
    result = {
        **_completed_result(),
        "delivery_package_policy": plan_delivery_package("Explain the result in chat"),
    }
    assessment = assess_delivery_package_requirement(result, [artifact])
    assert assessment["disposition"] == "omit"


def test_completed_package_contains_files_manifest_and_provenance(
    tmp_path: Path,
) -> None:
    """Verify completed package contains files manifest and provenance."""
    report = tmp_path / "report.md"
    table = tmp_path / "results.csv"
    report.write_text("# Result\n", encoding="utf-8")
    table.write_text("gene,score\nBRAF,0.9\n", encoding="utf-8")
    receipt = build_delivery_package(
        _completed_result(),
        [
            {"path": report, "role": "narrative_report"},
            {"path": table, "role": "result_table"},
        ],
        output_dir=tmp_path / "packages",
    )

    assert receipt["status"] == "ready_for_user"
    assert validate_contract(receipt).valid
    archive_path = Path(receipt["archive_path"])
    assert (
        hashlib.sha256(archive_path.read_bytes()).hexdigest()
        == receipt["archive_digest"].split(":", 1)[1]
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["artifact_count"] == 2
        assert "provenance/planner.prov.json" in names
        assert all(row["package_path"] in names for row in manifest["artifacts"])
        assert all(row["provenance_path"] in names for row in manifest["artifacts"])
        assert str(tmp_path) not in archive.read("manifest.json").decode("utf-8")
        for row in manifest["artifacts"]:
            descriptor = json.loads(archive.read(row["provenance_path"]))
            assert descriptor["standard"] == "W3C PROV"
            assert descriptor["artifact_content_digest"] == row["content_digest"]
            assert descriptor["producer_claim"].startswith("not_inferred")
            assert "used" in descriptor["document"]
            assert "hadMember" in descriptor["document"]
            assert "wasGeneratedBy" in descriptor["document"]


def test_package_bytes_are_deterministic_across_destinations(tmp_path: Path) -> None:
    """Verify package bytes are deterministic across destinations."""
    first = tmp_path / "a.md"
    second = tmp_path / "b.tsv"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    one = build_delivery_package(
        _completed_result(), [first, second], output_dir=tmp_path / "one"
    )
    two = build_delivery_package(
        _completed_result(), [second, first], output_dir=tmp_path / "two"
    )
    assert one["archive_digest"] == two["archive_digest"]
    assert (
        Path(one["archive_path"]).read_bytes() == Path(two["archive_path"]).read_bytes()
    )


def test_unsafe_or_duplicate_artifacts_are_rejected(tmp_path: Path) -> None:
    """Verify unsafe or duplicate artifacts are rejected."""
    artifact = tmp_path / "result.txt"
    artifact.write_text("result", encoding="utf-8")
    with pytest.raises(DeliveryPackageError, match="duplicate"):
        build_delivery_package(
            _completed_result(), [artifact, artifact], output_dir=tmp_path / "packages"
        )
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(artifact)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(DeliveryPackageError, match="non-symlink"):
        build_delivery_package(
            _completed_result(),
            [link],
            output_dir=tmp_path / "packages",
            requested=True,
        )


def test_mcp_packaging_requires_enablement_and_confines_sources(tmp_path: Path) -> None:
    """Verify mcp packaging requires enablement and confines sources."""
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    storage = VersionStorage(tmp_path / "store")
    artifact_root = storage.version_root(context) / "runs"
    artifact_root.mkdir(parents=True)
    inside = artifact_root / "result.md"
    inside.write_text("result", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    with bind_context(context):
        with pytest.raises(SkillRegistryError, match="disabled"):
            package_completed_artifacts_tool(
                _completed_result(), [{"path": str(inside)}], storage=storage
            )
        with pytest.raises(
            SkillRegistryError, match="only files under selected version artifacts"
        ):
            package_completed_artifacts_tool(
                _completed_result(),
                [{"path": str(outside)}],
                requested=True,
                storage=storage,
                allow_write=True,
            )
        receipt = package_completed_artifacts_tool(
            _completed_result(),
            [{"path": str(inside)}],
            requested=True,
            storage=storage,
            allow_write=True,
        )
        assert Path(str(receipt["archive_path"])).is_relative_to(artifact_root)
