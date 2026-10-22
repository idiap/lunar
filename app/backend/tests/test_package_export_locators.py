# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Native worker paths and legacy run locators retain the same owned bytes."""

import asyncio
import hashlib
from uuid import uuid4

import pytest

from domain_packages.archive_builder import ArchiveBuilder
from domain_packages.context import PackageContext
from domain_packages.exporter import VersionSnapshot
from domain_packages.storage import VersionStorage


def snapshot(tmp_path, locator):
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    run_id = uuid4()
    storage = VersionStorage(tmp_path / "store")
    path = storage.run_file(context, run_id, "figures/result.svg")
    path.parent.mkdir(parents=True)
    content = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    path.write_bytes(content)
    artifact = {
        "id": uuid4(),
        "safe_locator": locator,
        "media_type": "image/svg+xml",
        "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
    }

    class Connection:
        async def fetch(self, query, *arguments):
            assert arguments[:2] == (context.user_id, context.version_id)
            return [artifact] if "FROM prism_run_artifacts " in query else []

    builder = ArchiveBuilder(
        tmp_path / "snapshot", package_key="test", display_name="Test"
    )
    value = VersionSnapshot(Connection(), context, storage, builder)
    value.runs[str(run_id)] = {
        "id": run_id,
        "artifact_root": str(storage.run_root(context, run_id)),
    }
    return value, run_id, content


@pytest.mark.parametrize("locator", ["figures/result.svg", "run:figures/result.svg"])
def test_export_accepts_current_and_legacy_owned_locators(tmp_path, locator):
    value, run_id, content = snapshot(tmp_path, locator)
    result = asyncio.run(value.run(str(run_id)))
    artifact = result["run"]["facts"]["artifacts"][0]
    assert artifact["relative"] == "figures/result.svg"
    assert (value.builder.root / artifact["file"]).read_bytes() == content
    assert artifact["source_metadata"]["safe_locator"] == locator


@pytest.mark.parametrize(
    "locator",
    [
        "../result.svg",
        "/etc/passwd",
        "https://example.org/x",
        "run:../result.svg",
        "run:/etc/passwd",
    ],
)
def test_export_rejects_unconfined_locators(tmp_path, locator):
    value, run_id, _ = snapshot(tmp_path, locator)
    with pytest.raises(ValueError):
        asyncio.run(value.run(str(run_id)))
    assert value.builder.files == {}
