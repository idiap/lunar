# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Host-owned container launch and wheel-only dependency preparation policy."""

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement


class WorkerUnavailable(RuntimeError):
    """Preparation or execution cannot satisfy the declared worker boundary."""

    def __init__(self, message: str):
        super().__init__(message)
        self.events: list[Any] = []
        self.diagnostics = ""


def checked_requirements(text):
    """Admit hash-pinned index wheels without executable source builds or pip options."""
    logical = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        continued = line.endswith("\\")
        pending += " " + (line[:-1] if continued else line)
        if not continued:
            logical.append(pending.strip())
            pending = ""
    if pending:
        raise ValueError("unterminated dependency declaration")
    normalized = []
    for line in logical:
        parts = re.split(r"\s+--hash=", line)
        declaration = parts[0]
        try:
            requirement = Requirement(declaration)
        except InvalidRequirement as exc:
            raise ValueError("invalid pinned dependency declaration") from exc
        specifiers = list(requirement.specifier)
        if (
            requirement.url
            or len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise ValueError("worker dependencies require exact index versions")
        if len(parts) < 2 or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in parts[1:]
        ):
            raise ValueError("worker dependencies require SHA-256 wheel hashes")
        normalized.append(
            declaration + "".join(" --hash=" + value for value in parts[1:])
        )
    return "\n".join(normalized) + ("\n" if normalized else "")


@dataclass(frozen=True)
class WorkerLimits:
    memory: str = "2g"
    cpus: float = 2
    pids: int = 256
    timeout_seconds: float = 1800
    transport_bytes: int = 32 * 1024 * 1024
    request_bytes: int = 32 * 1024 * 1024


def worker_command(*, image, name, package_root, run_root, limits=WorkerLimits()):
    """Construct an argv without package-controlled flags, mounts, or environment."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("worker image must be an immutable Docker image ID")
    if not re.fullmatch(r"lunar-worker-[0-9a-f]{32}", name):
        raise ValueError("worker container name must be host-generated")
    roots = []
    for value in (package_root, run_root):
        path = Path(value)
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("worker mounts must not contain symlinks")
        path = path.resolve(strict=True)
        if not path.is_dir() or "," in str(path) or "\n" in str(path):
            raise ValueError("invalid worker mount directory")
        roots.append(path)
    package, output = roots
    mounts = []
    for collection in ("repository", "reports", "skills", "data-sources"):
        directory = package / collection
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("worker input collection is unavailable")
        if (
            directory == output
            or directory in output.parents
            or output in directory.parents
        ):
            raise ValueError("worker input and output mounts must be separate")
        mounts.extend(
            ["--mount", f"type=bind,src={directory},dst=/package/{collection},readonly"]
        )
    return [
        "docker",
        "run",
        "--rm",
        "--init",
        "--interactive",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        limits.memory,
        "--cpus",
        str(limits.cpus),
        "--ulimit",
        "nofile=1024:1024",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        *mounts,
        "--mount",
        f"type=bind,src={output},dst=/output",
        "--workdir",
        "/output",
        image,
        "python",
        "-I",
        "/opt/lunar-worker/main.py",
    ]
