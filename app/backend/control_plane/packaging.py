# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit completed-artifact packaging within the selected version's run tree."""

from pathlib import Path
from domain_packages.context import CURRENT_VERSION, SelectionRequired
from lunar_planner.delivery_package import build_delivery_package


def package_completed_artifacts_tool(
    planner_result,
    generated_files,
    *,
    storage,
    requested=None,
    package_name=None,
    allow_write=False,
):
    if not allow_write:
        raise ValueError(
            "delivery packaging is disabled without explicit write authorization"
        )
    context = CURRENT_VERSION.get()
    if context is None:
        raise SelectionRequired("Select an imported package version")
    artifact_root = (storage.version_root(context) / "runs").resolve(strict=True)
    confined = []
    for packet in generated_files:
        row = dict(packet)
        if "path" not in row:
            raise ValueError("each generated file requires a path")
        path = Path(str(row["path"]))
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("delivery files must be non-symlink paths")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(artifact_root):
            raise ValueError(
                "delivery packages may include only files under selected version artifacts"
            )
        row["path"] = str(resolved)
        confined.append(row)
    return build_delivery_package(
        planner_result,
        confined,
        output_dir=artifact_root / "planner" / "delivery-packages",
        requested=requested,
        package_name=package_name,
    )
