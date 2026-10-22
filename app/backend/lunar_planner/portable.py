# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Small deterministic primitives owned by the portable planner.

Purpose: provide the `portable` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class PlatformSupportError(RuntimeError):
    """Report a missing platform primitive required for safe persistence."""

    pass


def canonical_json(value: Any) -> str:
    """Encode a JSON-compatible value deterministically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_hash(value: Any, algorithm: str = "sha256") -> str:
    """Return a stable content hash using an explicitly selected algorithm."""

    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:
        raise ValueError(f"unsupported digest algorithm: {algorithm}") from exc
    digest.update(canonical_json(value).encode("utf-8"))
    return f"{algorithm}:" + digest.hexdigest()


def atomic_write_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    """Replace a file atomically using a sibling temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold a cross-platform exclusive advisory lock for a context."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
