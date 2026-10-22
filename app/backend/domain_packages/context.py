# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated immutable package selection, bound to one request."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


class SelectionRequired(ValueError):
    pass


class VersionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class PackageContext:
    user_id: UUID
    package_id: UUID
    version_id: UUID
    version: int

    def __post_init__(self):
        if not all(
            isinstance(v, UUID)
            for v in (self.user_id, self.package_id, self.version_id)
        ):
            raise ValueError("package context requires server UUID identities")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("invalid imported version number")

    @classmethod
    def from_record(cls, row):
        return cls(row["user_id"], row["package_id"], row["id"], row["version"])


CURRENT_VERSION: ContextVar[PackageContext | None] = ContextVar(
    "lunar_package_version", default=None
)


async def owned_context(connection, user_id: UUID, version_id: UUID | None):
    if version_id is None:
        raise SelectionRequired("Select an imported package version")
    row = await connection.fetchrow(
        "SELECT id,user_id,package_id,version FROM package_versions WHERE id=$1 AND user_id=$2 AND status='ready' AND deletion_started_at IS NULL",
        version_id,
        user_id,
    )
    if row is None:
        raise VersionNotFound("Package version not found")
    return PackageContext.from_record(row)


@contextmanager
def bind_context(context: PackageContext | None):
    token = CURRENT_VERSION.set(context)
    try:
        yield context
    finally:
        CURRENT_VERSION.reset(token)


def require_context(user_id=None):
    context = CURRENT_VERSION.get()
    if context is None:
        raise SelectionRequired("Select an imported package version")
    if user_id is not None and context.user_id != user_id:
        raise VersionNotFound("Package version not found")
    return context
