# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Worker arguments and dependency locks cannot broaden package authority."""

from uuid import uuid4

import pytest

from domain_packages.worker.sandbox import checked_requirements, worker_command


@pytest.mark.parametrize(
    "declaration",
    [
        "--extra-index-url https://private.invalid/simple",
        "package @ https://example.invalid/untrusted.tar.gz --hash=sha256:" + "1" * 64,
        "-r /etc/passwd",
        "package>=1 --hash=sha256:" + "1" * 64,
        "package==1",
        "package==1 --hash=md5:bad",
        "package==1 --hash=sha256:" + "1" * 64 + " --trusted-host host",
        "package==1.* --hash=sha256:" + "1" * 64,
    ],
)
def test_dependency_options_sources_and_unpinned_versions_rejected(declaration):
    with pytest.raises(ValueError):
        checked_requirements(declaration)


def test_pinned_wheels_and_markers_preserve_exact_hashes():
    text = (
        '# comment\nexample==1.2; python_version >= "3.12" \\\n    --hash=sha256:'
        + "a" * 64
        + "\n"
    )
    result = checked_requirements(text)
    assert (
        result
        == 'example==1.2; python_version >= "3.12" --hash=sha256:' + "a" * 64 + "\n"
    )
    assert checked_requirements("# Empty package runtime\n") == ""


def test_worker_sees_only_collection_inputs_and_own_output(tmp_path, monkeypatch):
    version = tmp_path / "version"
    for collection in ("repository", "reports", "skills", "data-sources"):
        (version / collection).mkdir(parents=True)
    output = version / "runs" / uuid4().hex
    output.mkdir(parents=True)
    (version / "planner-state").mkdir()
    monkeypatch.setenv("DATABASE_URL", "must-not-leave-host")
    command = worker_command(
        image="sha256:" + "1" * 64,
        name="lunar-worker-" + uuid4().hex,
        package_root=version,
        run_root=output,
    )
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command and "--cap-drop" in command
    mounts = [
        command[index + 1] for index, value in enumerate(command) if value == "--mount"
    ]
    assert len(mounts) == 5
    assert sum(value.endswith(",readonly") for value in mounts) == 4
    assert not any(
        "planner-state" in value or "docker.sock" in value for value in command
    )
    assert not any(
        "DATABASE_URL" in value or "must-not-leave-host" in value for value in command
    )
    with pytest.raises(ValueError, match="immutable"):
        worker_command(
            image="untrusted:latest",
            name="lunar-worker-" + uuid4().hex,
            package_root=version,
            run_root=output,
        )
    with pytest.raises(ValueError, match="separate"):
        worker_command(
            image="sha256:" + "1" * 64,
            name="lunar-worker-" + uuid4().hex,
            package_root=version,
            run_root=version / "repository",
        )
