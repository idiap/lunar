# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Actual process-death cleanup of upload staging before database allocation."""

from pathlib import Path
import subprocess
import sys

from domain_packages.storage import VersionStorage
from domain_packages.workspace import recover_uploads, upload_workspace


def test_recovery_keeps_an_active_upload_and_cleans_ordinary_exit(
    tmp_path, postgres_url
):
    storage = VersionStorage(tmp_path / "storage")
    with upload_workspace(storage, database_url=postgres_url) as work:
        (work / "upload.zip").write_bytes(b"partial upload")
        assert recover_uploads(storage, database_url=postgres_url) == []
        assert (work / "upload.zip").exists()
    assert not work.exists()


def test_process_death_before_version_allocation_is_recoverable(tmp_path, postgres_url):
    storage = VersionStorage(tmp_path / "storage")
    backend = Path(__file__).resolve().parents[1]
    program = """
import os,pathlib,sys
sys.path.insert(0,sys.argv[1])
from domain_packages.storage import VersionStorage
from domain_packages.workspace import upload_workspace
with upload_workspace(VersionStorage(pathlib.Path(sys.argv[2])),database_url=sys.argv[3]) as root:
    (root/'upload.zip').write_bytes(b'partial upload before process death')
    os._exit(7)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(backend),
            str(storage.root),
            postgres_url,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 7, result.stderr
    assert len(recover_uploads(storage, database_url=postgres_url)) == 1
    assert recover_uploads(storage, database_url=postgres_url) == []
    assert not list((storage.root / ".uploads").glob("upload-*"))


def test_recovery_keeps_another_process_active_upload(tmp_path, postgres_url):
    storage = VersionStorage(tmp_path / "storage")
    backend = Path(__file__).resolve().parents[1]
    program = """
import pathlib,sys
sys.path.insert(0,sys.argv[1])
from domain_packages.storage import VersionStorage
from domain_packages.workspace import upload_workspace
with upload_workspace(VersionStorage(pathlib.Path(sys.argv[2])),database_url=sys.argv[3]) as root:
    (root/'upload.zip').write_bytes(b'active upload in another process')
    print(str(root),flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(backend),
            str(storage.root),
            postgres_url,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        line = process.stdout.readline().strip()
        assert line, "Upload process failed before acquiring its lease"
        work = Path(line)
        assert recover_uploads(storage, database_url=postgres_url) == []
        assert (work / "upload.zip").read_bytes() == b"active upload in another process"
    finally:
        _, error = process.communicate("release\n", timeout=10)
    assert process.returncode == 0, error
    assert not work.exists()
