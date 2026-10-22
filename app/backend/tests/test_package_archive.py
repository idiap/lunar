# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Archive attacks and finite-consumption tests exercise the real ZIP reader."""

import hashlib
import json
from pathlib import Path
import stat
import struct
import zipfile

import pytest

from domain_packages.archive import ArchiveLimits, validate_archive
from domain_packages.format.contract import PackageValidationError

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "tests/domain_packages/fixtures/domain-package-v1"
)


def write_zip(path, fixture="neutral-complete", *, mutate=None, extra=()):
    root = FIXTURES / fixture
    manifest = json.loads((root / "manifest.json").read_text())
    payloads = [
        (row["path"], (root / row["path"]).read_bytes()) for row in manifest["files"]
    ]
    if mutate:
        manifest, payloads = mutate(manifest, payloads)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in ("repository/", "reports/", "skills/", "data-sources/"):
            archive.writestr(directory, b"")
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in [*payloads, *extra]:
            archive.writestr(name, content)
    return manifest


def test_real_zip_preserves_all_collections_and_original_bytes(tmp_path):
    path = tmp_path / "neutral.zip"
    manifest = write_zip(path)
    result = validate_archive(path, tmp_path / "private")
    assert result.manifest == manifest
    assert set(result.documents) == {"repository", "reports", "skills", "data-sources"}
    assert result.archive_digest == hashlib.sha256(path.read_bytes()).hexdigest()
    for row in manifest["files"]:
        assert (
            hashlib.sha256((result.root / row["path"]).read_bytes()).hexdigest()
            == row["sha256"]
        )


def test_empty_package_is_valid(tmp_path):
    path = tmp_path / "empty.zip"
    write_zip(path, "empty")
    result = validate_archive(path, tmp_path / "private")
    assert all(not rows for rows in result.documents.values())


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "repository/../outside",
        "repository/a\\b",
        "repository/CON",
        "repository/a:stream",
        "repository/a.",
        "repository/e\u0301",
        "repository/./a",
        "repository//a",
        "repository/a?b",
        "repository/a*b",
        "repository/a|b",
        "repository/a\x7fb",
        "repository/" + "a" * 256,
    ],
)
def test_malicious_paths_never_escape_staging(tmp_path, name):
    path = tmp_path / "bad.zip"
    write_zip(path, extra=[(name, b"attack")])
    with pytest.raises(PackageValidationError):
        validate_archive(path, tmp_path / "private")
    assert not (tmp_path / "private").exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK]
)
def test_special_entries_are_rejected(tmp_path, kind):
    path = tmp_path / "bad.zip"
    entry = zipfile.ZipInfo("repository/special")
    entry.create_system = 3
    entry.external_attr = (kind | 0o777) << 16
    write_zip(path, extra=[(entry, b"/another/version")])
    with pytest.raises(PackageValidationError, match="special"):
        validate_archive(path, tmp_path / "private")
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "case_collision",
        "missing",
        "digest",
        "declared_size",
        "reference",
        "unknown_version",
        "duplicate_json",
    ],
)
def test_inventory_contract_failures_remove_private_files(tmp_path, failure):
    path = tmp_path / "bad.zip"

    def mutate(manifest, payloads):
        if failure == "duplicate":
            payloads.append(payloads[0])
        elif failure == "case_collision":
            payloads.append((payloads[0][0].upper(), payloads[0][1]))
        elif failure == "missing":
            payloads.pop()
        elif failure == "digest":
            name, content = payloads[0]
            payloads[0] = (name, b"x" * len(content))
        elif failure == "declared_size":
            manifest["files"][0]["size"] += 1
        elif failure == "reference":
            manifest["collections"]["repository"][0]["files"].append(
                "repository/missing"
            )
        elif failure == "unknown_version":
            manifest["format_version"] = 999
        elif failure == "duplicate_json":
            row = manifest["collections"]["repository"][0]
            name = row["document"]
            content = b'{"id":"a","id":"b"}'
            payloads = [
                (key, content if key == name else value) for key, value in payloads
            ]
            for entry in manifest["files"]:
                if entry["path"] == name:
                    entry.update(
                        size=len(content), sha256=hashlib.sha256(content).hexdigest()
                    )
        return manifest, payloads

    write_zip(path, mutate=mutate)
    with pytest.raises(PackageValidationError):
        validate_archive(path, tmp_path / "private")
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize(
    "limit",
    [
        "compressed_bytes",
        "expanded_bytes",
        "file_bytes",
        "manifest_bytes",
        "document_bytes",
        "directory_bytes",
        "entries",
    ],
)
def test_each_deployment_limit_is_enforced(tmp_path, limit):
    path = tmp_path / "bounded.zip"
    write_zip(path)
    limits = ArchiveLimits(**{**vars(ArchiveLimits()), limit: 1})
    with pytest.raises(PackageValidationError):
        validate_archive(path, tmp_path / "private", limits)
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize(
    "failure",
    ["trailing", "prefix", "encryption", "bad_count", "bad_offset", "truncated"],
)
def test_unsupported_container_encodings_are_rejected(tmp_path, failure):
    path = tmp_path / "encoding.zip"
    write_zip(path)
    raw = bytearray(path.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    if failure == "trailing":
        raw.extend(b"undeclared trailer")
    elif failure == "prefix":
        raw = b"pretend executable" + raw
    elif failure == "encryption":
        central = raw.find(b"PK\x01\x02")
        struct.pack_into("<H", raw, central + 8, 1)
    elif failure == "bad_count":
        struct.pack_into("<H", raw, end + 10, 60000)
    elif failure == "bad_offset":
        struct.pack_into("<L", raw, end + 16, 0)
    else:
        raw = raw[:-25]
    path.write_bytes(raw)
    with pytest.raises(PackageValidationError):
        validate_archive(path, tmp_path / "private")
    assert not (tmp_path / "private").exists()


def test_payload_python_is_never_imported(tmp_path):
    path = tmp_path / "code.zip"
    marker = tmp_path / "executed"

    def mutate(manifest, payloads):
        name = "repository/malicious.py"
        content = f"from pathlib import Path\nPath({str(marker)!r}).touch()".encode()
        manifest["files"].append(
            dict(
                path=name,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                media_type="text/x-python",
            )
        )
        payloads.append((name, content))
        return manifest, payloads

    write_zip(path, mutate=mutate)
    validate_archive(path, tmp_path / "private")
    assert not marker.exists()


def test_case_insensitive_file_parent_collision_is_rejected(tmp_path):
    path = tmp_path / "collision.zip"

    def mutate(manifest, payloads):
        for name in ("repository/A", "repository/a/nested.txt"):
            content = b"collision"
            manifest["files"].append(
                dict(
                    path=name,
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    media_type="text/plain",
                )
            )
            payloads.append((name, content))
        return manifest, payloads

    write_zip(path, mutate=mutate)
    with pytest.raises(PackageValidationError, match="collision|alias"):
        validate_archive(path, tmp_path / "private")
    assert not (tmp_path / "private").exists()
