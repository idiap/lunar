# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Retained slow/expensive domain oracles run inside an imported package container."""

import asyncio
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import asyncpg
import pytest
from domain_packages.archive import validate_archive
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker.preparation import prepare_runtime

pytestmark = pytest.mark.e2e


def test_73_retained_domain_oracles_in_imported_runtime(
    e2e_database_url, tmp_path, worker_image
):
    package = os.getenv("LUNAR_E2E_BIOAGENTS_ZIP")
    assert package, "Provide the actual BioAgents export as a ZIP input"

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            owner = uuid4()
            await connection.execute(
                "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
                owner,
                str(owner) + "@example.invalid",
            )
            archive = validate_archive(Path(package), tmp_path / "validated")
            storage = VersionStorage(tmp_path / "store")
            context = await import_validated(
                connection, storage, user_id=owner, archive=archive
            )
            image = await prepare_runtime(
                connection, context, storage, base_image=worker_image
            )
            return storage.version_root(context), image
        finally:
            await connection.close()

    version, image = asyncio.run(setup())
    # Add only pure-Python testing modules, not the API, planner or a domain checkout.
    vendor = tmp_path / "test-libs"
    vendor.mkdir()
    for name in ("pytest", "_pytest", "pluggy", "iniconfig", "pygments"):
        spec = importlib.util.find_spec(name)
        shutil.copytree(
            Path(spec.origin).parent,
            vendor / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    shutil.copyfile(importlib.util.find_spec("py").origin, vendor / "py.py")
    cases = tmp_path / "cases"
    cases.mkdir()
    for path in (Path(__file__).parents[1] / "fixtures/domain_cases").glob(
        "cases_*.py"
    ):
        shutil.copyfile(path, cases / path.name.replace("cases_", "test_"))
    output = tmp_path / "oracle-output"
    output.mkdir()
    program = """
import importlib.abc, pathlib, sys
sys.path[:0] = ['/test-libs', '/package/repository/runtime']
class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'app', 'prism_runs', 'data_sources', 'bioagents_planner', 'lunar_planner'} or fullname.startswith(('catalog.planner', 'catalog.integrations.planner', 'catalog.workflows.public.dependencies.planner')):
            raise AssertionError('forbidden host import: ' + fullname)
sys.meta_path.insert(0, NoHost())
from catalog.integrations.domain_package.runtime.config import configure
configure(pathlib.Path('/package/repository/runtime'), data_root=pathlib.Path('/package/data-sources/local'), run_root=pathlib.Path('/output/runs'))
import pytest
raise SystemExit(pytest.main(['/cases', '-q', '--import-mode=importlib', '--basetemp=/output/tmp', '-p', 'no:cacheprovider']))
"""
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "4g",
        "--pids-limit",
        "128",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
        "--entrypoint",
        "python",
    ]
    for name in ("repository", "skills", "data-sources", "reports"):
        argv += [
            "--mount",
            f"type=bind,src={version/name},dst=/package/{name},readonly",
        ]
    for source, target in ((vendor, "/test-libs"), (cases, "/cases")):
        argv += ["--mount", f"type=bind,src={source},dst={target},readonly"]
    argv += [
        "--mount",
        f"type=bind,src={output},dst=/output",
        image,
        "-I",
        "-c",
        program,
    ]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "73 passed" in result.stdout
    (tmp_path / "domain-oracles.log").write_text(result.stdout)
