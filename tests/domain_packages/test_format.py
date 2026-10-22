# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Offline contract cases shared by domain exporters and Lunar's importer."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from domain_packages.format.contract import (
    PackageValidationError,
    archive_path,
    validate_manifest,
    validate_payloads,
)


def package_fixture():
    manifest = {
        "format_version": 1,
        "package": {"key": "warehouse", "display_name": "Warehouse operations"},
        "runtime": {
            "contract_version": 1,
            "python": ">=3.12,<3.14",
            "requirements_lock": None,
            "entrypoints": [],
            "planning_hooks": [],
        },
        "collections": {
            k: [] for k in ("repository", "reports", "skills", "data-sources")
        },
        "files": [],
    }
    return manifest, {}


def add_file(manifest, payloads, path, value, media_type="application/json"):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    payloads[path] = raw
    manifest["files"].append(
        {
            "path": path,
            "size": len(raw),
            "media_type": media_type,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    return hashlib.sha256(raw).hexdigest()


def add_resource(manifest, payloads, collection, document, *, files=(), references=()):
    path = f"{collection}/{document['id']}.json"
    add_file(manifest, payloads, path, document)
    manifest["collections"][collection].append(
        {
            "id": document["id"],
            "document": path,
            "files": list(files),
            "references": list(references),
        }
    )


def complete_fixture():
    manifest, payloads = package_fixture()
    add_file(
        manifest,
        payloads,
        "data-sources/shared.csv",
        b"item,count\nbox,3\n",
        "text/csv",
    )
    add_resource(
        manifest,
        payloads,
        "data-sources",
        {
            "id": "stock",
            "name": "Stock",
            "descriptor": {"kind": "inventory"},
            "local_files": [
                {"id": "morning", "file": "data-sources/shared.csv"},
                {"id": "backup", "file": "data-sources/shared.csv"},
            ],
            "remote_references": [
                {"id": "reference", "uri": "https://example.invalid/stock.csv"}
            ],
        },
        files=["data-sources/shared.csv"],
    )
    add_resource(
        manifest,
        payloads,
        "skills",
        {
            "id": "stock",
            "name": "Stock summary",
            "instructions": "Summarize item counts.",
            "capabilities": [{"operation": "summarize"}],
            "invocation": {"mode": "planning"},
            "groups": [],
            "metadata": {},
        },
        references=[{"collection": "data-sources", "id": "stock"}],
    )
    add_resource(
        manifest,
        payloads,
        "repository",
        {
            "id": "warehouse",
            "name": "Warehouse",
            "kind": "project",
            "metadata": {},
        },
    )
    provenance = b'{"entity":{"original:stock":{"prov:label":"Stock"}}}'
    digest = add_file(manifest, payloads, "reports/original-prov.json", provenance)
    add_file(manifest, payloads, "reports/plot.svg", b"<svg/>", "image/svg+xml")
    add_resource(
        manifest,
        payloads,
        "reports",
        {
            "id": "stock",
            "name": "Stock report",
            "content": "![Stock](plot.svg)\nThree boxes.",
            "version": 2,
            "revisions": [{"version": 1, "content": "Two boxes.", "metadata": {}}],
            "attachments": [{"link": "plot.svg", "file": "reports/plot.svg"}],
            "sections": [
                {
                    "id": "counts",
                    "ordinal": 0,
                    "output_id": "old-output",
                    "content_digest": hashlib.sha256(b"Three boxes.").hexdigest(),
                    "metadata": {},
                }
            ],
            "runs": [{"id": "old-run", "facts": {"state": "completed"}}],
            "outputs": [
                {
                    "id": "old-output",
                    "run_id": "old-run",
                    "content": "Three boxes.",
                    "metadata": {},
                }
            ],
            "provenance": [
                {
                    "format": "PROV-JSON",
                    "file": "reports/original-prov.json",
                    "sha256": digest,
                }
            ],
            "template_snapshot": {"section": "counts"},
            "metadata": {},
        },
        files=["reports/original-prov.json", "reports/plot.svg"],
        references=[{"collection": "data-sources", "id": "stock"}],
    )
    return manifest, payloads


def replace_document(manifest, payloads, path, update):
    document = json.loads(payloads[path])
    update(document)
    manifest["files"] = [row for row in manifest["files"] if row["path"] != path]
    add_file(manifest, payloads, path, document)


def test_empty_package_is_valid():
    assert validate_payloads(*package_fixture()) == {
        k: [] for k in package_fixture()[0]["collections"]
    }


def test_complete_neutral_package_preserves_shared_bytes_history_and_provenance(
    monkeypatch,
):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("validation attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    manifest, payloads = complete_fixture()
    original = copy.deepcopy(payloads)
    result = validate_payloads(manifest, payloads)
    assert result["reports"][0]["version"] == 2
    assert len(result["data-sources"][0]["local_files"]) == 2
    assert payloads == original


@pytest.mark.parametrize(
    "field", ["format_version", "runtime.contract_version", "runtime.python"]
)
def test_incompatible_contracts_fail(field):
    manifest, payloads = package_fixture()
    if field == "format_version":
        manifest[field] = 2
    else:
        manifest["runtime"][field.split(".")[1]] = (
            ">=4" if field.endswith("python") else 2
        )
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize(
    "path",
    [
        "/repository/a",
        "repository/../a",
        "repository//a",
        "repository/./a",
        "repository/a\\b",
        "C:/a",
        "repository/NUL.txt",
        "repository/a.",
        "repository/a\x00",
        "repository/e\u0301",
    ],
)
def test_nonportable_paths_fail(path):
    with pytest.raises(PackageValidationError):
        archive_path(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-id",
        "missing-reference",
        "missing-file",
        "bad-hash",
        "extra-file",
        "owner-override",
        "case-collision",
        "file-directory-collision",
    ],
)
def test_manifest_and_payload_failure_boundaries(mutation):
    manifest, payloads = complete_fixture()
    if mutation == "duplicate-id":
        manifest["collections"]["reports"] *= 2
    elif mutation == "missing-reference":
        manifest["collections"]["skills"][0]["references"][0]["id"] = "missing"
    elif mutation == "missing-file":
        del payloads["reports/plot.svg"]
    elif mutation == "bad-hash":
        payloads["reports/plot.svg"] = b"<svg >"
    elif mutation == "extra-file":
        payloads["repository/hidden.py"] = b"raise AssertionError"
    elif mutation == "owner-override":
        manifest["user_id"] = "foreign-owner"
    elif mutation == "case-collision":
        add_file(manifest, payloads, "reports/Plot.svg", b"<svg/>")
    elif mutation == "file-directory-collision":
        add_file(manifest, payloads, "reports/plot.svg/child", b"x")
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-output",
        "missing-run",
        "missing-attachment",
        "provenance-digest",
        "duplicate-revision",
        "undeclared-local-file",
        "credential-reference",
    ],
)
def test_report_and_source_closure_errors_fail(mutation):
    manifest, payloads = complete_fixture()

    def change_report(doc):
        if mutation == "missing-output":
            doc["sections"][0]["output_id"] = "missing"
        elif mutation == "missing-run":
            doc["outputs"][0]["run_id"] = "missing"
        elif mutation == "missing-attachment":
            doc["attachments"][0]["file"] = "reports/missing.svg"
        elif mutation == "provenance-digest":
            doc["provenance"][0]["sha256"] = "0" * 64
        elif mutation == "duplicate-revision":
            doc["revisions"] *= 2

    replace_document(manifest, payloads, "reports/stock.json", change_report)
    if mutation == "undeclared-local-file":
        manifest["collections"]["data-sources"][0]["files"] = []
    elif mutation == "credential-reference":
        replace_document(
            manifest,
            payloads,
            "data-sources/stock.json",
            lambda doc: doc["remote_references"][0].update(
                uri="https://user:secret@example.invalid/file"
            ),
        )
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


def test_registered_hook_is_validated_without_execution():
    manifest, payloads = package_fixture()
    add_file(
        manifest,
        payloads,
        "repository/hook.py",
        b"raise AssertionError('must not execute on upload')",
        "text/x-python",
    )
    manifest["runtime"]["entrypoints"] = [
        {
            "id": "policy",
            "operation": "plan",
            "file": "repository/hook.py",
            "callable": "plan",
        }
    ]
    manifest["runtime"]["planning_hooks"] = ["policy"]
    validate_payloads(manifest, payloads)
    manifest["runtime"]["entrypoints"][0]["callable"] = "os.system"
    with pytest.raises(PackageValidationError):
        validate_manifest(manifest)


def test_unsupported_entrypoint_target_fails():
    manifest, payloads = package_fixture()
    manifest["runtime"]["entrypoints"] = [
        {
            "id": "policy",
            "operation": "plan",
            "file": "repository/missing.py",
            "callable": "plan",
        }
    ]
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing-project",
        "wrong-hook",
        "external-schema",
        "invalid-schema",
        "execution-modes",
    ],
)
def test_workflow_contract(mutation):
    manifest, payloads = complete_fixture()
    add_file(
        manifest,
        payloads,
        "repository/main.prism",
        b"type Count = (request: Int) -> Int\nworkflow count(request: Int) -> Int:\n    [counted: Count(request)]\n    return counted\ndef main(request: Int) -> Int:\n    return solve count(request)\n",
        "text/plain",
    )
    add_file(
        manifest,
        payloads,
        "repository/hook.py",
        b"raise AssertionError",
        "text/x-python",
    )
    manifest["runtime"]["entrypoints"] = [
        {
            "id": "input",
            "operation": "prepare",
            "file": "repository/hook.py",
            "callable": "prepare",
        }
    ]
    workflow = {
        "id": "count",
        "repository_id": "warehouse",
        "name": "Count boxes",
        "entry_file": "repository/main.prism",
        "entry_argument": "request",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "prepare_hook": "input",
        "verify_hook": None,
        "metadata": {},
    }
    if mutation == "missing-project":
        workflow["repository_id"] = "missing"
    elif mutation == "wrong-hook":
        manifest["runtime"]["entrypoints"][0]["operation"] = "plan"
    elif mutation == "external-schema":
        workflow["input_schema"] = {"$ref": "https://example.invalid/schema.json"}
    elif mutation == "invalid-schema":
        workflow["output_schema"] = {"type": 5}
    elif mutation == "execution-modes":
        workflow["modes"] = ["reasoning", "materialization"]
    options = {
        key: value
        for key, value in workflow.items()
        if key not in {"repository_id", "name", "entry_file"}
    }
    options["declaration"] = "count"
    if mutation == "missing-project":
        options["repository_id"] = "missing"
    raw = ("# lunar-runtime: " + json.dumps(options) + "\n").encode() + payloads[
        "repository/main.prism"
    ]
    payloads["repository/main.prism"] = raw
    manifest["collections"]["repository"][0]["files"].append("repository/main.prism")
    next(
        row for row in manifest["files"] if row["path"] == "repository/main.prism"
    ).update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if mutation:
        with pytest.raises(PackageValidationError):
            validate_payloads(manifest, payloads)
    else:
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize(
    "raw", [b'{"id":"one","id":"two"}', b'{"value":NaN}', b'{"value":1e999}']
)
def test_ambiguous_json_is_rejected(raw):
    manifest, payloads = complete_fixture()
    path = "repository/warehouse.json"
    manifest["files"] = [row for row in manifest["files"] if row["path"] != path]
    add_file(manifest, payloads, path, raw)
    with pytest.raises(PackageValidationError):
        validate_payloads(manifest, payloads)


@pytest.mark.parametrize("name", ["empty", "neutral-complete"])
def test_published_fixture_validates(name):
    root = Path(__file__).parent / "fixtures/domain-package-v1" / name
    manifest = json.loads((root / "manifest.json").read_text())
    payloads = {f["path"]: (root / f["path"]).read_bytes() for f in manifest["files"]}
    validate_payloads(manifest, payloads)


def test_exporter_pin_matches_format_bytes():
    from domain_packages.format import contract

    root = Path(contract.__file__).parent
    pin = json.loads((root / "FORMAT-PIN.json").read_text())
    assert pin["format_version"] == 1
    for name, digest in pin["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
