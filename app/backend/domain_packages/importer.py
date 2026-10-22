# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Transactional records plus recoverable same-filesystem version publication."""

from dataclasses import replace
import errno
import os
import shutil
import time
from uuid import uuid4

from .context import PackageContext
from .records import historical_facts, insert_records
from .repository import allocate_version

LOCK = "SELECT pg_advisory_lock(hashtextextended($1,0))"
UNLOCK = "SELECT pg_advisory_unlock(hashtextextended($1,0))"


def remove_version_files(storage, context):
    """Remove only server-generated paths for this version.

    Finder can recreate .DS_Store while rmtree walks a host-mounted tree.
    Retry only that transient non-empty-directory race.
    """
    for path in (storage.staging_root(context), storage.version_root(context)):
        for attempt in range(5):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except OSError as exc:
                if exc.errno != errno.ENOTEMPTY or attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))


async def import_validated(connection, storage, *, user_id, archive, checkpoint=None):
    """Publish a validated snapshot with no reader-visible partial version.

    Session advisory locks keep reconciliation away from active imports. A
    committed staging identity survives transaction rollback, so process death
    is recoverable even after filesystem rename but before database commit.
    """
    historical_facts(archive.documents)
    identity = uuid4()
    await connection.execute(LOCK, str(identity))
    context = None

    async def reached(stage):
        if checkpoint:
            await checkpoint(stage, context)

    try:
        context = await allocate_version(
            connection,
            user_id=user_id,
            manifest=archive.manifest,
            archive_digest=archive.archive_digest,
            version_id=identity,
        )
        await reached("allocated")
        staging = storage.staging_root(context)
        final = storage.version_root(context)
        staging.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if staging.exists() or final.exists():
            raise RuntimeError("new import storage already exists")
        os.rename(archive.root, staging)
        staged = replace(archive, root=staging)
        await reached("staged")
        async with connection.transaction():
            database_paths = await insert_records(connection, context, staged)
            await reached("records_inserted")
            for path in database_paths:
                (staging / path).unlink()
            await reached("before_publication")
            os.rename(staging, final)
            # Persist directory publication before committing reader visibility.
            descriptor = os.open(final.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            await reached("after_publication")
            await connection.execute(
                "UPDATE package_versions SET status='ready' WHERE id=$1 AND user_id=$2 AND status='staging'",
                identity,
                user_id,
            )
            await reached("before_commit")
        await reached("after_commit")
        return context
    except Exception:
        # If a connection dies during COMMIT, its outcome is uncertain. Leave
        # bytes intact for reconciliation instead of deleting a possible success.
        if context is not None and not connection.is_closed():
            status = await connection.fetchval(
                "SELECT status FROM package_versions WHERE id=$1 AND user_id=$2",
                identity,
                user_id,
            )
            if status == "staging":
                remove_version_files(storage, context)
                await connection.execute(
                    "UPDATE package_versions SET status='failed',error='Import failed before publication completed' WHERE id=$1 AND status='staging'",
                    identity,
                )
        raise
    finally:
        if not connection.is_closed():
            await connection.execute(UNLOCK, str(identity))


async def reconcile_imports(connection, storage):
    """Fail interrupted imports and remove their inaccessible staged/published bytes."""
    rows = await connection.fetch(
        "SELECT id,user_id,package_id,version FROM package_versions WHERE status='staging' ORDER BY created_at"
    )
    recovered = []
    for row in rows:
        identity = str(row["id"])
        acquired = await connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1,0))", identity
        )
        if not acquired:
            continue
        try:
            status = await connection.fetchval(
                "SELECT status FROM package_versions WHERE id=$1", row["id"]
            )
            if status != "staging":
                continue
            context = PackageContext.from_record(row)
            remove_version_files(storage, context)
            await connection.execute(
                "UPDATE package_versions SET status='failed',error='Interrupted import recovered; upload again to create a new version' WHERE id=$1 AND status='staging'",
                row["id"],
            )
            recovered.append(row["id"])
        finally:
            await connection.execute(UNLOCK, identity)
    return recovered
