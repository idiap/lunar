# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Portable typed-report validation before any package becomes ready."""

from copy import deepcopy
import hashlib
import json

import pytest
from domain_packages.format.contract import PackageValidationError, validate_payloads
from typed_report_fixtures import staged


@pytest.mark.parametrize("template", [True, False])
def test_installed_contract_validates_real_execution(tmp_path, template):
    archive = staged(tmp_path, template=template)
    report = archive.documents["reports"][0]
    assert len(report["sections"]) == 8
    assert (report["template_snapshot"] is not None) == template


@pytest.mark.parametrize(
    "case", ["template", "asset", "entity", "payload", "inventory", "mapping"]
)
def test_invalid_typed_payloads_rejected(tmp_path, case):
    archive = staged(tmp_path)
    manifest = deepcopy(archive.manifest)
    payloads = {
        row["path"]: (archive.root / row["path"]).read_bytes()
        for row in manifest["files"]
    }
    path = manifest["collections"]["reports"][0]["document"]
    report = json.loads(payloads[path])
    if case == "template":
        report["template_snapshot"]["id"] = "different"
    elif case == "asset":
        report["attachments"] = []
    elif case == "entity":
        raw = json.loads(payloads["reports/provenance.json"])
        raw["entity"] = {}
        payloads["reports/provenance.json"] = json.dumps(raw).encode()
        report["provenance"][0]["sha256"] = hashlib.sha256(
            payloads["reports/provenance.json"]
        ).hexdigest()
    elif case == "payload":
        report["metadata"]["typed_report"]["report"]["title"] = "tampered"
    elif case == "inventory":
        report["sections"].pop()
    else:
        report["sections"][0]["metadata"]["native_reference"] = "missing"
    payloads[path] = json.dumps(report).encode()
    for row in manifest["files"]:
        row.update(
            size=len(payloads[row["path"]]),
            sha256=hashlib.sha256(payloads[row["path"]]).hexdigest(),
        )
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize("with_template", [True, False])
def test_example_zip_uses_real_execution(tmp_path, with_template):
    from pathlib import Path
    from scripts.build_typed_report_package import build_package
    from domain_packages.archive import validate_archive

    example = (
        Path(__file__).resolve().parents[4] / "prism/examples/language/typed_reports"
    )
    destination = tmp_path / "example.zip"
    typed = build_package(example, destination, with_template=with_template)
    archive = validate_archive(destination, tmp_path / "validated")
    doc = archive.documents["reports"][0]
    assert doc["metadata"]["typed_report"] == typed
    assert len(doc["sections"]) == 10
    assert (doc["template_snapshot"] is not None) == with_template
    assert {a["kind"] for a in typed["native"]["graph"]["activities"]} >= {
        "asserted",
        "computed",
    }
