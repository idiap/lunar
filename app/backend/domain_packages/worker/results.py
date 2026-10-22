# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Host validation of terminal worker results and their actual output bytes."""

import hashlib
from pathlib import Path
import stat

from ..format.contract import archive_path, validate_document
from .sandbox import WorkerUnavailable


def validate_worker_result(
    result, request, run_root, *, max_artifact_bytes=8 * 1024**3
):
    """Reject forged receipts, escaping files, and successful incomplete execution."""
    validate_document(result, "worker-result")
    if result["request_id"] != request["request_id"]:
        raise WorkerUnavailable("worker result belongs to another request")
    if [row["sequence"] for row in result["events"]] != list(
        range(len(result["events"]))
    ):
        raise WorkerUnavailable("worker event sequence is incomplete")
    if result["status"] == "succeeded":
        if result["error"] is not None:
            raise WorkerUnavailable("successful worker result contains an error")
        if (
            request["operation"] in {"prepare", "execute"}
            and result["prepared_input"] is None
        ):
            raise WorkerUnavailable("worker omitted the prepared input")
        if (
            request["operation"] in {"plan", "execute", "verify"}
            and result["result"] is None
        ):
            raise WorkerUnavailable("worker omitted its result")
    elif result["result"] is not None:
        raise WorkerUnavailable("failed worker cannot supply a released result")
    root = Path(run_root).resolve(strict=True)
    files = {}
    total = 0
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise WorkerUnavailable("worker emitted a symlink or special file")
        relative = path.relative_to(root).as_posix()
        archive_path("repository/" + relative)
        total += metadata.st_size
        if total > max_artifact_bytes:
            raise WorkerUnavailable("worker artifacts exceed the output limit")
        files[relative] = path
    seen = set()
    folded = set()
    for artifact in result["artifacts"]:
        path = archive_path("repository/" + artifact["path"]).removeprefix(
            "repository/"
        )
        if path in seen or path.casefold() in folded or path not in files:
            raise WorkerUnavailable("worker artifact identity is duplicated or absent")
        seen.add(path)
        folded.add(path.casefold())
        digest = hashlib.sha256()
        with files[path].open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if (
            digest.hexdigest() != artifact["sha256"]
            or files[path].stat().st_size != artifact["size"]
        ):
            raise WorkerUnavailable("worker artifact bytes differ from their receipt")
    if seen != set(files):
        raise WorkerUnavailable("worker omitted artifact receipts")
    return result
