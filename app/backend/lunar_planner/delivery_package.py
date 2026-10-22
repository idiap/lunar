# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic post-completion artifact packages with W3C provenance.

Planning and packaging are separate authority boundaries. The planner may
declare that a package will be useful, but files are read and an archive is
written only when a host explicitly calls :func:`build_delivery_package`
after completion with the generated artifact paths and an output directory.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import re
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .portable import atomic_write_bytes, canonical_json, stable_hash
from .provenance import export_w3c_provenance

_COMPLETE_STATUSES = frozenset({"complete", "completed", "accepted", "released"})
_PACKAGE_SIGNALS = re.compile(
    r"\b(?:archive|bundle|download(?:able)?|package|"
    r"return (?:the )?(?:generated |output )?files?|"
    r"deliver (?:the )?(?:generated |output )?files?|"
    r"provenance descriptors?)\b",
    flags=re.IGNORECASE,
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class DeliveryPackageError(ValueError):
    """Raised when package policy or an artifact boundary is invalid."""


def _task_complete(planner_result: Mapping[str, Any]) -> bool:
    """Task complete."""
    status = str(planner_result.get("status", "")).strip().lower()
    if status in _COMPLETE_STATUSES:
        return True
    decision = planner_result.get("final_delivery_decision")
    return isinstance(decision, Mapping) and str(
        decision.get("decision", decision.get("status", ""))
    ).strip().lower() in {"release", "released", "accepted"}


def plan_delivery_package(
    command_text: str,
    *,
    desired_outputs: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a planning-only package policy without reading or writing files."""

    outputs = tuple(str(item).strip() for item in desired_outputs if str(item).strip())
    explicit = bool(_PACKAGE_SIGNALS.search(command_text)) or any(
        _PACKAGE_SIGNALS.search(item) for item in outputs
    )
    policy: dict[str, Any] = {
        "schema_version": "lunar.planner.delivery-package-policy/v1",
        "disposition": (
            "required_when_complete" if explicit else "conditional_on_artifact_set"
        ),
        "explicitly_requested": explicit,
        "trigger": (
            "the request asks for packaged or file-based delivery"
            if explicit
            else "package only when completion yields multiple user-facing files or the host explicitly requests it"
        ),
        "completion_gate": "task completion must be evidenced before packaging",
        "contents": [
            "generated files",
            "integrity manifest",
            "one W3C PROV descriptor per generated file",
            "planner-level W3C PROV export",
        ],
        "authority": "explicit post-completion host invocation",
    }
    policy["digest"] = stable_hash(policy)
    return policy


def assess_delivery_package_requirement(
    planner_result: Mapping[str, Any],
    generated_files: Iterable[str | Path | Mapping[str, Any]],
    *,
    requested: bool | None = None,
) -> dict[str, Any]:
    """Decide whether a completed result and its artifacts warrant a package."""

    artifacts = tuple(generated_files)
    policy = planner_result.get("delivery_package_policy")
    explicit = bool(
        isinstance(policy, Mapping) and policy.get("explicitly_requested") is True
    )
    demanded = (
        bool(requested) if requested is not None else explicit or len(artifacts) > 1
    )
    complete = _task_complete(planner_result)
    if not artifacts:
        disposition, reason = "omit", "no generated files were supplied"
    elif not demanded:
        disposition, reason = (
            "omit",
            "a single artifact does not require a package and no package was requested",
        )
    elif not complete:
        disposition, reason = (
            "defer",
            "the task is not complete; partial outputs must not be presented as a final package",
        )
    else:
        disposition, reason = (
            "package",
            "completed user-facing artifacts require consolidated delivery with provenance",
        )
    result = {
        "schema_version": "lunar.planner.delivery-package-requirement/v1",
        "disposition": disposition,
        "reason": reason,
        "task_complete": complete,
        "package_demanded": demanded,
        "artifact_count": len(artifacts),
    }
    result["digest"] = stable_hash(result)
    return result


def _safe_name(value: object, *, fallback: str) -> str:
    """Safe name."""
    name = Path(str(value)).name.strip()
    cleaned = _SAFE_NAME.sub("-", name).strip(".-")
    return cleaned or fallback


def _artifact_rows(
    artifacts: Iterable[str | Path | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Artifact rows."""
    rows: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for position, value in enumerate(artifacts, 1):
        packet = dict(value) if isinstance(value, Mapping) else {"path": value}
        if "path" not in packet:
            raise DeliveryPackageError("each artifact requires a path")
        path = Path(str(packet["path"]))
        if path.is_symlink() or not path.is_file():
            raise DeliveryPackageError(
                f"artifact must be an existing non-symlink file: {path}"
            )
        resolved = path.resolve(strict=True)
        if resolved in seen_paths:
            raise DeliveryPackageError(f"duplicate artifact path: {path}")
        seen_paths.add(resolved)
        content = resolved.read_bytes()
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        name = _safe_name(
            packet.get("name", resolved.name), fallback=f"artifact-{position}"
        )
        rows.append(
            {
                "name": name,
                "role": str(packet.get("role", "generated_output")).strip()
                or "generated_output",
                "media_type": str(
                    packet.get("media_type")
                    or mimetypes.guess_type(name)[0]
                    or "application/octet-stream"
                ),
                "content": content,
                "content_digest": digest,
                "size_bytes": len(content),
            }
        )
    rows.sort(key=lambda row: (str(row["name"]).casefold(), str(row["content_digest"])))
    used: set[str] = set()
    for index, row in enumerate(rows, 1):
        candidate = str(row["name"])
        if candidate in used:
            stem, suffix = Path(candidate).stem, Path(candidate).suffix
            candidate = (
                f"{stem}-{str(row['content_digest']).split(':', 1)[1][:8]}{suffix}"
            )
        used.add(candidate)
        row["package_path"] = f"files/{index:03d}-{candidate}"
        row["artifact_id"] = (
            "artifact-" + str(row["content_digest"]).split(":", 1)[1][:16]
        )
    return rows


def _artifact_provenance(
    row: Mapping[str, Any], *, package_id: str, planner_digest: str
) -> dict[str, Any]:
    """Artifact provenance."""
    artifact_id = f"lunar:{row['artifact_id']}"
    activity_id = f"lunar:{package_id}"
    package_entity_id = f"lunar:{package_id}-collection"
    document = {
        "prefix": {
            "prov": "http://www.w3.org/ns/prov#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "lunar": "https://lunar.local/ns/prov#",
        },
        "entity": {
            artifact_id: {
                "prov:label": row["name"],
                "prov:type": "lunar:GeneratedArtifact",
                "lunar:packagePath": row["package_path"],
                "lunar:mediaType": row["media_type"],
                "lunar:sizeBytes": row["size_bytes"],
                "lunar:sha256": str(row["content_digest"]).split(":", 1)[1],
            },
            package_entity_id: {
                "prov:label": "Lunar completed-task delivery package",
                "prov:type": "prov:Collection",
            },
        },
        "activity": {
            activity_id: {
                "prov:label": "Lunar completed-task packaging",
                "prov:type": "lunar:DeliveryPackaging",
                "lunar:plannerResultDigest": planner_digest,
            }
        },
        "used": {
            f"lunar:usage-{row['artifact_id']}": {
                "prov:activity": activity_id,
                "prov:entity": artifact_id,
            }
        },
        "wasGeneratedBy": {
            f"lunar:package-generation-{row['artifact_id']}": {
                "prov:entity": package_entity_id,
                "prov:activity": activity_id,
            }
        },
        "hadMember": {
            f"lunar:membership-{row['artifact_id']}": {
                "prov:collection": package_entity_id,
                "prov:entity": artifact_id,
            }
        },
    }
    descriptor: dict[str, Any] = {
        "schema_version": "lunar.planner.artifact-provenance-descriptor/v1",
        "standard": "W3C PROV",
        "format": "prov-json",
        "media_type": "application/provenance+json",
        "artifact_id": row["artifact_id"],
        "artifact_content_digest": row["content_digest"],
        "producer_claim": "not_inferred; the descriptor records observed bytes and package membership",
        "document": document,
    }
    descriptor["digest"] = stable_hash(descriptor)
    return descriptor


def _zip_bytes(entries: Mapping[str, bytes]) -> bytes:
    """Zip bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])
    return buffer.getvalue()


def build_delivery_package(
    planner_result: Mapping[str, Any],
    generated_files: Iterable[str | Path | Mapping[str, Any]],
    *,
    output_dir: str | Path,
    requested: bool | None = None,
    package_name: str | None = None,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one immutable ZIP package for a completed task."""

    supplied = tuple(generated_files)
    requirement = assess_delivery_package_requirement(
        planner_result, supplied, requested=requested
    )
    if requirement["disposition"] != "package":
        raise DeliveryPackageError(requirement["reason"])
    rows = _artifact_rows(supplied)
    planner_digest = stable_hash(planner_result)
    package_seed = {
        "planner_result_digest": planner_digest,
        "artifacts": [
            {
                "name": row["name"],
                "role": row["role"],
                "content_digest": row["content_digest"],
                "size_bytes": row["size_bytes"],
            }
            for row in rows
        ],
    }
    package_id = "delivery-" + stable_hash(package_seed).split(":", 1)[1][:20]
    descriptors = [
        _artifact_provenance(row, package_id=package_id, planner_digest=planner_digest)
        for row in rows
    ]
    manifest: dict[str, Any] = {
        "schema_version": "lunar.planner.delivery-package-manifest/v1",
        "package_id": package_id,
        "planner_result_digest": planner_digest,
        "artifact_count": len(rows),
        "artifacts": [
            {
                "artifact_id": row["artifact_id"],
                "name": row["name"],
                "role": row["role"],
                "package_path": row["package_path"],
                "media_type": row["media_type"],
                "size_bytes": row["size_bytes"],
                "content_digest": row["content_digest"],
                "provenance_path": f"provenance/{row['artifact_id']}.prov.json",
                "provenance_digest": descriptor["digest"],
            }
            for row, descriptor in zip(rows, descriptors, strict=True)
        ],
    }
    manifest["digest"] = stable_hash(manifest)
    planner_provenance = export_w3c_provenance(
        planner_result, reconciliation=reconciliation, output_format="prov-json"
    )
    entries: dict[str, bytes] = {
        "manifest.json": (canonical_json(manifest) + "\n").encode("utf-8"),
        "provenance/planner.prov.json": (
            canonical_json(planner_provenance) + "\n"
        ).encode("utf-8"),
    }
    for row, descriptor in zip(rows, descriptors, strict=True):
        entries[str(row["package_path"])] = bytes(row["content"])
        entries[f"provenance/{row['artifact_id']}.prov.json"] = (
            canonical_json(descriptor) + "\n"
        ).encode("utf-8")
    archive_bytes = _zip_bytes(entries)
    archive_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    destination_root = Path(output_dir)
    if destination_root.exists() and (
        destination_root.is_symlink() or not destination_root.is_dir()
    ):
        raise DeliveryPackageError(f"output directory is unsafe: {destination_root}")
    destination_root.mkdir(parents=True, exist_ok=True)
    resolved_root = destination_root.resolve(strict=True)
    archive_name = _safe_name(
        package_name or f"{package_id}.zip", fallback=f"{package_id}.zip"
    )
    if not archive_name.lower().endswith(".zip"):
        archive_name += ".zip"
    archive_path = resolved_root / archive_name
    if archive_path.exists() and archive_path.is_symlink():
        raise DeliveryPackageError(f"archive target is a symlink: {archive_path}")
    atomic_write_bytes(archive_path, archive_bytes, mode=0o600)
    receipt: dict[str, Any] = {
        "schema_version": "lunar.planner.delivery-package/v1",
        "status": "ready_for_user",
        "package_id": package_id,
        "archive_path": str(archive_path),
        "archive_media_type": "application/zip",
        "archive_digest": archive_digest,
        "manifest": manifest,
        "planner_provenance_path": "provenance/planner.prov.json",
        "requirement": requirement,
        "skill_route": ["completed-artifact-packager"],
    }
    receipt["digest"] = stable_hash(receipt)
    return receipt


__all__ = [
    "DeliveryPackageError",
    "assess_delivery_package_requirement",
    "build_delivery_package",
    "plan_delivery_package",
]
