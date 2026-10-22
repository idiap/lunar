# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Server-generated version roots and confined payload/run paths."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .context import PackageContext
from .format.contract import archive_path


@dataclass(frozen=True)
class VersionStorage:
    root: Path

    def _path(self, relative: Path) -> Path:
        root = self.root.resolve()
        target = root
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise ValueError("unsafe storage segment")
            target = target / part
            if target.is_symlink():
                raise ValueError("symlinks are forbidden in package storage")
        if not target.resolve().is_relative_to(root):
            raise ValueError("path escaped package storage")
        return target

    def _relative(self, context: PackageContext) -> Path:
        return Path(context.user_id.hex, context.package_id.hex, context.version_id.hex)

    def version_root(self, context: PackageContext) -> Path:
        return self._path(self._relative(context))

    def staging_root(self, context: PackageContext) -> Path:
        relative = self._relative(context)
        return self._path(relative.with_name("." + relative.name + ".staging"))

    def package_file(self, context: PackageContext, relative: str) -> Path:
        return self._path(self._relative(context) / archive_path(relative))

    def run_root(self, context: PackageContext, run_id: UUID) -> Path:
        if not isinstance(run_id, UUID):
            raise ValueError("run directory requires a server UUID")
        return self._path(self._relative(context) / "runs" / run_id.hex)

    def run_file(self, context: PackageContext, run_id: UUID, relative: str) -> Path:
        # Reuse portable archive-name rules with a synthetic collection prefix.
        checked = archive_path("repository/" + relative).removeprefix("repository/")
        root = self.run_root(context, run_id)
        return self._path(root.relative_to(self.root.resolve()) / checked)
