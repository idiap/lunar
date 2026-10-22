# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Returned worker receipts are checked against real confined output files."""

import hashlib
import os

import pytest

from domain_packages.worker.results import validate_worker_result
from domain_packages.worker.sandbox import WorkerUnavailable


def packet():
    request = {"request_id": "test", "operation": "plan"}
    result = {
        "contract_version": 1,
        "request_id": "test",
        "status": "succeeded",
        "prepared_input": None,
        "result": {
            "markdown": "",
            "structured_value": {},
            "analysis_results": {},
            "compact_prism_input": {},
            "narrative_slots": [],
            "report_verification": None,
        },
        "events": [],
        "artifacts": [],
        "error": None,
    }
    return request, result


def test_exact_artifact_inventory_and_bytes_are_required(tmp_path):
    request, result = packet()
    data = b"inventory count: 42"
    (tmp_path / "count.txt").write_bytes(data)
    with pytest.raises(WorkerUnavailable, match="omitted"):
        validate_worker_result(result, request, tmp_path)
    result["artifacts"] = [
        {
            "path": "count.txt",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "text/plain",
        }
    ]
    assert validate_worker_result(result, request, tmp_path) == result
    (tmp_path / "count.txt").write_bytes(b"forged value")
    with pytest.raises(WorkerUnavailable, match="differ"):
        validate_worker_result(result, request, tmp_path)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_special_output_files_are_rejected_even_when_omitted(tmp_path, kind):
    request, result = packet()
    if kind == "symlink":
        (tmp_path / "escape").symlink_to("/etc/passwd")
    else:
        os.mkfifo(tmp_path / "pipe")
    with pytest.raises(WorkerUnavailable, match="special"):
        validate_worker_result(result, request, tmp_path)


def test_foreign_and_failed_results_never_release_content(tmp_path):
    request, result = packet()
    result["request_id"] = "other"
    with pytest.raises(WorkerUnavailable, match="another"):
        validate_worker_result(result, request, tmp_path)
    result["request_id"] = "test"
    result["status"] = "failed"
    with pytest.raises(WorkerUnavailable, match="failed worker"):
        validate_worker_result(result, request, tmp_path)
