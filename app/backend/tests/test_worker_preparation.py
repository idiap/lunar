# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Reject worker interpreter mismatches before installing dependencies."""

import asyncio
import asyncpg
import pytest

from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker import preparation
from domain_packages.worker.sandbox import WorkerUnavailable
from test_package_importer import user, staged


def test_mismatched_worker_python_persists_failed_state(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(preparation, "_image_id", lambda image: "sha256:" + "1" * 64)
    monkeypatch.setattr(preparation, "_python_version", lambda image: "3.11.0")

    def forbidden(**arguments):
        raise AssertionError("incompatible runtime reached dependency installation")

    monkeypatch.setattr(preparation, "build_runtime", forbidden)

    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            storage = VersionStorage(tmp_path / "store")
            context = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "mismatch")
            )
            with pytest.raises(WorkerUnavailable, match="Python requirement"):
                await preparation.prepare_runtime(
                    connection, context, storage, base_image="test-base"
                )
            row = await connection.fetchrow(
                "SELECT runtime_state,runtime_image FROM package_versions WHERE id=$1",
                context.version_id,
            )
            assert row["runtime_state"] == "failed" and row["runtime_image"] is None
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_refresh_worker_code_updates_only_host_files(monkeypatch):
    from pathlib import Path

    old, new = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    monkeypatch.setattr(
        preparation, "_image_id", lambda value: new if value == "refreshed" else old
    )
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *a, **k: "")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1] == "build":
            root = Path(args[-1])
            assert set(p.name for p in root.iterdir()) == {
                "Dockerfile",
                "main.py",
                "prism_engine.py",
            }
            text = (root / "Dockerfile").read_text()
            assert "pip install" not in text and "RUN " not in text
            assert "model_calls" in (root / "prism_engine.py").read_text()
            assert "--network=none" in args

    monkeypatch.setattr(preparation.subprocess, "run", run)
    assert preparation.refresh_worker_code(old, tag="refreshed") == new
    assert calls[0][1:3] == ["tag", old]
    assert calls[-1][1:3] == ["image", "rm"]


def test_refresh_worker_code_reuses_matching_image(monkeypatch):
    import hashlib
    from pathlib import Path

    worker = Path(preparation.__file__).parent
    digest = hashlib.sha256(
        b"\0".join((worker / name).read_bytes() for name in ("main.py", "prism.py"))
    ).hexdigest()
    monkeypatch.setattr(preparation, "_image_id", lambda value: value)
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *a, **k: digest)

    def forbidden(*a, **k):
        raise AssertionError("matching worker code must not rebuild")

    monkeypatch.setattr(preparation.subprocess, "run", forbidden)
    assert (
        preparation.refresh_worker_code("sha256:" + "1" * 64, tag="unused")
        == "sha256:" + "1" * 64
    )


def test_ready_runtime_refreshes_and_persists_new_image(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    old, new = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    writes = []

    class Connection:
        async def fetchval(self, *args):
            return True

        async def fetchrow(self, *args):
            return {"runtime_state": "ready", "runtime_image": old}

        async def execute(self, *args):
            writes.append(args)

    async def owned(*args):
        return context

    def refresh(image, *, tag):
        assert image == old and tag == "lunar-runtime-" + context.version_id.hex
        return new

    monkeypatch.setattr(preparation, "owned_context", owned)
    monkeypatch.setattr(preparation, "_image_id", lambda value: value)
    monkeypatch.setattr(preparation, "refresh_worker_code", refresh)
    result = asyncio.run(
        preparation.prepare_runtime(Connection(), context, None, base_image="unused")
    )
    assert result == new
    assert writes[0][1:] == (context.version_id, context.user_id, new)
    assert "runtime_image=$3" in writes[0][0]
    assert "pg_advisory_unlock" in writes[-1][0]


def test_fresh_runtime_overlays_current_worker_after_dependency_build(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from uuid import uuid4

    from domain_packages import source_workflows

    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    dependency_image = "sha256:" + "2" * 64
    current_image = "sha256:" + "3" * 64
    refreshed = []
    writes = []

    class Connection:
        async def fetchval(self, *args):
            return True

        async def fetchrow(self, *args):
            return {
                "manifest": {
                    "runtime": {
                        "python": ">=3.13",
                        "requirements_lock": None,
                        "workflows": [],
                    },
                    "files": [],
                },
                "runtime_state": "unprepared",
                "runtime_image": None,
            }

        async def execute(self, *args):
            writes.append(args)

    async def owned(*args):
        return context

    monkeypatch.setattr(preparation, "owned_context", owned)
    monkeypatch.setattr(
        source_workflows, "runtime_manifest", lambda manifest, root: manifest
    )
    monkeypatch.setattr(preparation, "_image_id", lambda image: "sha256:" + "1" * 64)
    monkeypatch.setattr(preparation, "_python_version", lambda image: "3.13.0")
    monkeypatch.setattr(preparation, "check_capabilities", lambda *args: None)
    monkeypatch.setattr(
        preparation, "build_runtime", lambda **arguments: dependency_image
    )

    def refresh(image, *, tag):
        refreshed.append((image, tag))
        return current_image

    monkeypatch.setattr(preparation, "refresh_worker_code", refresh)

    image = asyncio.run(
        preparation.prepare_runtime(
            Connection(),
            context,
            SimpleNamespace(version_root=lambda _: tmp_path),
            base_image="test-base",
        )
    )
    assert image == current_image
    ready_write = next(args for args in writes if "runtime_state='ready'" in args[0])
    assert ready_write[1:] == (context.version_id, context.user_id, current_image)
    assert refreshed == [(dependency_image, "lunar-runtime-" + context.version_id.hex)]


def test_execution_guard_refreshes_stale_ready_runtime(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    context = SimpleNamespace(user_id=uuid4(), version_id=uuid4())
    old, new = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    writes = []

    class Connection:
        async def fetchrow(self, *args):
            return {"runtime_state": "ready", "runtime_image": old}

        async def execute(self, *args):
            writes.append(args)

    monkeypatch.setattr(
        preparation,
        "refresh_worker_code",
        lambda image, *, tag: new,
    )
    result = asyncio.run(preparation.ensure_current_worker_code(Connection(), context))
    assert result == new
    assert "pg_advisory_lock" in writes[0][0]
    assert "runtime_image=$3" in writes[1][0]
    assert writes[1][1:] == (context.version_id, context.user_id, new)
    assert "pg_advisory_unlock" in writes[-1][0]
