# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bounded ZIP validation and streaming extraction without executing package code."""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import zipfile

from .format.contract import (
    COLLECTIONS,
    PackageValidationError,
    _json,
    archive_path,
    validate_documents,
    validate_manifest,
)


@dataclass(frozen=True)
class ArchiveLimits:
    compressed_bytes: int = 2 * 1024**3
    expanded_bytes: int = 8 * 1024**3
    file_bytes: int = 2 * 1024**3
    manifest_bytes: int = 32 * 1024**2
    document_bytes: int = 32 * 1024**2
    directory_bytes: int = 64 * 1024**2
    entries: int = 100_000

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("archive limits must be positive finite integers")

    @classmethod
    def from_environment(cls):
        return cls(
            **{
                name: int(
                    os.environ.get("LUNAR_IMPORT_MAX_" + name.upper(), str(default))
                )
                for name, default in vars(cls()).items()
            }
        )


@dataclass(frozen=True)
class ValidatedArchive:
    root: Path
    manifest: dict
    documents: dict
    archive_digest: str


class Documents(Mapping):
    """Read only bounded collection documents from a private validated snapshot."""

    def __init__(self, root, names, limit):
        self.root, self.names, self.limit = root, names, limit

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)

    def __getitem__(self, name):
        if name not in self.names:
            raise KeyError(name)
        if (self.root / name).stat().st_size > self.limit:
            raise PackageValidationError("JSON document size limit exceeded")
        return (self.root / name).read_bytes()


def _directory_bounds(path, limits):
    """Bound central-directory allocation before Python constructs ZipInfo objects."""
    size = path.stat().st_size
    if size > limits.compressed_bytes or size < 22:
        raise PackageValidationError("compressed archive size limit or truncated ZIP")
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read()
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail) - offset < 22:
            raise PackageValidationError("missing ZIP end record")
        fields = struct.unpack("<4s4H2LH", tail[offset : offset + 22])
        (
            _,
            disk,
            directory_disk,
            disk_count,
            count,
            directory_size,
            directory_offset,
            comment,
        ) = fields
        end = size - len(tail) + offset
        if offset + 22 + comment != len(tail) or disk or directory_disk:
            raise PackageValidationError(
                "unsupported trailing data or multi-volume ZIP"
            )
        if (
            count == 65535
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        ):
            stream.seek(end - 20)
            locator = stream.read(20)
            if len(locator) != 20:
                raise PackageValidationError("invalid ZIP64 locator")
            signature, start_disk, record_offset, disks = struct.unpack(
                "<4sLQL", locator
            )
            if signature != b"PK\x06\x07" or start_disk or disks != 1:
                raise PackageValidationError("unsupported ZIP64 volume")
            stream.seek(record_offset)
            record = stream.read(56)
            if len(record) != 56:
                raise PackageValidationError("truncated ZIP64 end record")
            (
                signature,
                length,
                made,
                needed,
                disk,
                directory_disk,
                disk_count,
                count,
                directory_size,
                directory_offset,
            ) = struct.unpack("<4sQ2H2L4Q", record)
            if (
                signature != b"PK\x06\x06"
                or length != 44
                or disk
                or directory_disk
                or record_offset + 56 != end - 20
            ):
                raise PackageValidationError("unsupported ZIP64 end record")
            end = record_offset
        if (
            disk_count != count
            or count > limits.entries
            or directory_size > limits.directory_bytes
        ):
            raise PackageValidationError(
                "ZIP entry or central-directory limit exceeded"
            )
        if directory_offset + directory_size != end or directory_offset < 0:
            raise PackageValidationError("invalid ZIP directory offsets")
        return count


def _headers(archive, count, limits):
    entries = archive.infolist()
    if len(entries) != count:
        raise PackageValidationError("ZIP entry count mismatch")
    seen, regular, roots = set(), {}, set()
    expanded = 0
    for entry in entries:
        name = entry.filename
        if name != entry.orig_filename or name.casefold() in seen:
            raise PackageValidationError("duplicate or noncanonical ZIP entry")
        seen.add(name.casefold())
        mode = entry.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if entry.flag_bits & ~(0x800 | 0x8) or entry.compress_type not in {
            zipfile.ZIP_STORED,
            zipfile.ZIP_DEFLATED,
        }:
            raise PackageValidationError("encrypted or unsupported ZIP feature")
        if entry.is_dir():
            if (
                name not in {root + "/" for root in COLLECTIONS}
                or kind not in {0, stat.S_IFDIR}
                or entry.file_size
            ):
                raise PackageValidationError("unsupported ZIP directory entry")
            roots.add(name)
            continue
        if kind not in {0, stat.S_IFREG} or entry.external_attr & 0x10:
            raise PackageValidationError("symlink or special ZIP file")
        if name != "manifest.json":
            archive_path(name)
        bound = limits.manifest_bytes if name == "manifest.json" else limits.file_bytes
        if entry.file_size > bound:
            raise PackageValidationError("ZIP file size limit exceeded")
        expanded += entry.file_size
        if expanded > limits.expanded_bytes:
            raise PackageValidationError("expanded archive limit exceeded")
        regular[name] = entry
    if roots != {root + "/" for root in COLLECTIONS} or "manifest.json" not in regular:
        raise PackageValidationError("missing manifest or collection roots")
    if entries and min(entry.header_offset for entry in entries) != 0:
        raise PackageValidationError("prefixed ZIP archives are unsupported")
    return regular


def _stream_member(archive, entry, destination, expected, budget):
    """Enforce actual byte consumption and hashes while writing one private file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    with archive.open(entry) as source, destination.open("xb") as target:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            count += len(chunk)
            budget[0] -= len(chunk)
            if count > expected["size"] or budget[0] < 0:
                raise PackageValidationError("expanded payload limit exceeded")
            target.write(chunk)
            digest.update(chunk)
    if count != expected["size"] or digest.hexdigest() != expected["sha256"]:
        raise PackageValidationError(
            "payload digest or size mismatch: " + entry.filename
        )


def validate_archive(
    path: Path, destination: Path, limits: ArchiveLimits | None = None
) -> ValidatedArchive:
    """Validate and stage an archive; every failure removes its private extraction."""
    limits = limits or ArchiveLimits.from_environment()
    if path.is_symlink() or not path.is_file():
        raise PackageValidationError("upload must be a private regular file")
    before = path.stat()
    count = _directory_bounds(path, limits)
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = _headers(archive, count, limits)
            manifest_entry = entries.pop("manifest.json")
            # The declared and actual manifest size are independently bounded.
            with archive.open(manifest_entry) as source:
                raw = source.read(limits.manifest_bytes + 1)
            if len(raw) > limits.manifest_bytes or len(raw) != manifest_entry.file_size:
                raise PackageValidationError("manifest byte limit exceeded")
            manifest = _json(raw)
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            validate_manifest(manifest, python_version=python_version)
            expected = {row["path"]: row for row in manifest["files"]}
            if set(entries) != set(expected):
                raise PackageValidationError("payload inventory mismatch")
            document_names = {
                row["document"]
                for rows in manifest["collections"].values()
                for row in rows
            }
            if any(
                expected[name]["size"] > limits.document_bytes
                for name in document_names
            ):
                raise PackageValidationError("collection document size limit exceeded")
            budget = [limits.expanded_bytes - len(raw)]
            (destination / "manifest.json").write_bytes(raw)
            for root in COLLECTIONS:
                (destination / root).mkdir()
            for name, entry in entries.items():
                if entry.file_size != expected[name]["size"]:
                    raise PackageValidationError(
                        "manifest and ZIP byte lengths disagree"
                    )
                _stream_member(
                    archive, entry, destination / name, expected[name], budget
                )
            documents = validate_documents(
                manifest,
                Documents(destination, expected, limits.document_bytes),
                python_version=python_version,
            )
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise PackageValidationError("upload changed during validation")
        return ValidatedArchive(destination, manifest, documents, digest.hexdigest())
    except BaseException as exc:
        shutil.rmtree(destination)
        if isinstance(
            exc,
            (
                zipfile.BadZipFile,
                NotImplementedError,
                UnicodeError,
                RecursionError,
                struct.error,
            ),
        ):
            raise PackageValidationError(
                "invalid or unsupported archive encoding"
            ) from exc
        raise
