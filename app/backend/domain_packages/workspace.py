# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Database-leased private workspaces, independent of host filesystem locking."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import tempfile

import psycopg


def uploads_root(storage):
    path = storage.root / ".uploads"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("upload storage cannot be a symlink")
    return path


def lock_key(path):
    value = ("lunar-workspace:" + str(path.resolve())).encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:8], signed=True)


@contextmanager
def upload_workspace(storage, *, database_url):
    """Hold a PostgreSQL session lease until the upload/export response finishes."""
    uploads = uploads_root(storage)
    with psycopg.connect(database_url, autocommit=True) as connection:
        gate = lock_key(uploads)
        connection.execute("SELECT pg_advisory_lock(%s)", (gate,))
        try:
            directory = Path(tempfile.mkdtemp(dir=uploads, prefix="upload-"))
            connection.execute("SELECT pg_advisory_lock(%s)", (lock_key(directory),))
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (gate,))
        try:
            yield directory
        finally:
            if directory.exists():
                shutil.rmtree(directory)
        # Closing the connection releases its lease, including on process death.


def recover_uploads(storage, *, database_url):
    """Reap only workspaces whose PostgreSQL session lease has been released."""
    uploads = uploads_root(storage)
    recovered = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (lock_key(uploads),))
        for path in uploads.iterdir():
            if (
                not path.name.startswith("upload-")
                or path.is_symlink()
                or not path.is_dir()
            ):
                continue
            key = lock_key(path)
            lock_row = connection.execute(
                "SELECT pg_try_advisory_lock(%s)", (key,)
            ).fetchone()
            acquired = bool(lock_row and lock_row[0])
            if not acquired:
                continue
            try:
                shutil.rmtree(path)
                recovered.append(path.name)
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (key,))
    return recovered
