# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Transactional version allocation and owned resource queries."""

import json
from uuid import uuid4

from .context import PackageContext


async def allocate_version(
    connection, *, user_id, manifest, archive_digest, version_id=None
):
    """Reserve a distinct monotonic version; rollback cannot affect ready versions."""
    package = manifest["package"]
    async with connection.transaction():
        row = await connection.fetchrow(
            """INSERT INTO domain_packages(id,user_id,package_key,display_name)
               VALUES($1,$2,$3,$4)
               ON CONFLICT(user_id,package_key) DO UPDATE SET display_name=EXCLUDED.display_name
               RETURNING id""",
            uuid4(),
            user_id,
            package["key"],
            package["display_name"],
        )
        package_id = row["id"]
        number = await connection.fetchval(
            "UPDATE domain_packages SET next_version=next_version+1 WHERE id=$1 RETURNING next_version-1",
            package_id,
        )
        version_id = version_id or uuid4()
        await connection.execute(
            """INSERT INTO package_versions(id,package_id,user_id,version,status,archive_digest,manifest)
               VALUES($1,$2,$3,$4,'staging',$5,$6::jsonb)""",
            version_id,
            package_id,
            user_id,
            number,
            archive_digest,
            json.dumps(manifest),
        )
        return PackageContext(user_id, package_id, version_id, number)


async def list_versions(connection, user_id):
    return await connection.fetch(
        """SELECT v.id,v.package_id,v.version,v.status,v.runtime_state,v.error,v.created_at,
                  v.deletion_started_at,
                  p.package_key,p.display_name
           FROM package_versions v JOIN domain_packages p ON p.id=v.package_id AND p.user_id=v.user_id
           WHERE v.user_id=$1 AND v.status='ready'
           ORDER BY p.package_key,v.version DESC""",
        user_id,
    )


async def resources(connection, context, collection):
    return await connection.fetch(
        """SELECT r.id,r.logical_id,r.document FROM package_resources r
           JOIN package_versions v ON v.id=r.version_id AND v.user_id=r.user_id
           WHERE r.version_id=$1 AND r.user_id=$2 AND r.collection=$3 AND v.status='ready'
           ORDER BY r.logical_id""",
        context.version_id,
        context.user_id,
        collection,
    )
