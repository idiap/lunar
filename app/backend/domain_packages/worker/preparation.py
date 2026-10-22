# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit, version-specific container runtime preparation with PostgreSQL state."""

import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import UUID, uuid4
from packaging.specifiers import SpecifierSet

from ..context import VersionNotFound, owned_context
from .sandbox import WorkerUnavailable, checked_requirements


def runtime_lock_key(version_id):
    if not isinstance(version_id, UUID):
        raise ValueError("runtime lock requires a package version UUID")
    return int.from_bytes(
        hashlib.sha256(("runtime:" + str(version_id)).encode()).digest()[:8],
        signed=True,
    )


def remove_runtime_image(version_id):
    """Remove only the deterministic tag owned by one deleted package version."""
    if not isinstance(version_id, UUID):
        raise ValueError("runtime image removal requires a package version UUID")
    subprocess.run(
        ["docker", "image", "rm", "lunar-runtime-" + version_id.hex],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def _image_id(reference):
    value = subprocess.check_output(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        text=True,
        timeout=15,
    ).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise WorkerUnavailable("container engine returned an invalid image identity")
    return value


def worker_code_digest():
    """Return the identity of the host-owned worker sources in this backend."""
    worker = Path(__file__).parent
    return hashlib.sha256(
        b"\0".join((worker / name).read_bytes() for name in ("main.py", "prism.py"))
    ).hexdigest()


def refresh_worker_code(image, *, tag):
    """Refresh host-owned worker code without replacing prepared dependencies."""
    identity = _image_id(image)
    worker = Path(__file__).parent
    files = {
        "main.py": (worker / "main.py").read_bytes(),
        "prism_engine.py": (worker / "prism.py").read_bytes(),
    }
    digest = worker_code_digest()
    label = subprocess.check_output(
        [
            "docker",
            "image",
            "inspect",
            identity,
            "--format",
            '{{index .Config.Labels "org.lunar.worker-code"}}',
        ],
        text=True,
        timeout=15,
    ).strip()
    if label == digest:
        return identity
    base_tag = "lunar-worker-refresh-base-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="lunar-worker-refresh-") as raw:
        root = Path(raw)
        for name, content in files.items():
            (root / name).write_bytes(content)
        (root / "Dockerfile").write_text(
            f"FROM {base_tag}\n"
            "COPY main.py prism_engine.py /opt/lunar-worker/\n"
            f'LABEL org.lunar.worker-code="{digest}"\n'
        )
        subprocess.run(["docker", "tag", identity, base_tag], check=True, timeout=15)
        try:
            subprocess.run(
                ["docker", "build", "--network=none", "--tag", tag, str(root)],
                check=True,
                timeout=120,
                stdout=subprocess.DEVNULL,
            )
        finally:
            subprocess.run(
                ["docker", "image", "rm", base_tag],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
    return _image_id(tag)


async def ensure_current_worker_code(connection, context):
    """Refresh a ready runtime lazily before it can execute host-owned code."""
    lock_key = runtime_lock_key(context.version_id)
    await connection.execute("SELECT pg_advisory_lock($1)", lock_key)
    try:
        row = await connection.fetchrow(
            "SELECT runtime_state,runtime_image FROM package_versions WHERE id=$1 AND user_id=$2",
            context.version_id,
            context.user_id,
        )
        if row is None or row["runtime_state"] != "ready" or not row["runtime_image"]:
            raise WorkerUnavailable(
                "Prepare the selected package runtime before execution or policy evaluation"
            )
        current = await asyncio.to_thread(
            refresh_worker_code,
            row["runtime_image"],
            tag="lunar-runtime-" + context.version_id.hex,
        )
        if current != row["runtime_image"]:
            await connection.execute(
                "UPDATE package_versions SET runtime_image=$3,error=NULL WHERE id=$1 AND user_id=$2",
                context.version_id,
                context.user_id,
                current,
            )
        return current
    finally:
        await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)


def check_capabilities(manifest, image):
    """Only the host-owned image can advertise execution capabilities."""
    required = set()
    for workflow in manifest["runtime"]["workflows"]:
        values = workflow.get("metadata", {}).get("required_capabilities", [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise WorkerUnavailable("invalid runtime capability declaration")
        required.update(values)
    if required:
        label = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                image,
                "--format",
                '{{index .Config.Labels "org.lunar.capabilities"}}',
            ],
            text=True,
            timeout=15,
        ).strip()
        missing = required - set(label.split(","))
        if missing:
            raise WorkerUnavailable(
                "worker image lacks required capabilities: "
                + ", ".join(sorted(missing))
            )


def _python_version(image):
    return subprocess.check_output(
        [
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
            "128m",
            "--pids-limit",
            "32",
            "--entrypoint",
            "python",
            image,
            "-I",
            "-c",
            "import platform; print(platform.python_version())",
        ],
        text=True,
        timeout=30,
    ).strip()


def build_runtime(*, version_id, base_image, requirements, timeout=1200):
    """Install hash-verified binary wheels without running package build scripts."""
    base_identity = _image_id(base_image)
    tag = "lunar-runtime-" + version_id.hex
    with tempfile.TemporaryDirectory(prefix="lunar-runtime-build-") as raw:
        root = Path(raw)
        (root / "requirements.lock").write_text(checked_requirements(requirements))
        (root / ".dockerignore").write_text("build.log\n")
        # A temporary host-generated tag is verified against the immutable base ID.
        base_tag = "lunar-preparation-base-" + version_id.hex
        subprocess.run(
            ["docker", "tag", base_identity, base_tag], check=True, timeout=15
        )
        dockerfile = (
            "FROM " + base_tag + "\nCOPY requirements.lock /tmp/requirements.lock\n"
            "RUN uv pip install --python /opt/bootstrap/.venv/bin/python --only-binary :all: "
            "--require-hashes --no-cache -r /tmp/requirements.lock && rm /tmp/requirements.lock\n"
            'LABEL org.lunar.role="package-runtime" org.lunar.version="'
            + str(version_id)
            + '"\n'
        )
        if not requirements.strip():
            dockerfile = (
                "FROM "
                + base_tag
                + '\nLABEL org.lunar.role="package-runtime" org.lunar.version="'
                + str(version_id)
                + '"\n'
            )
        (root / "Dockerfile").write_text(dockerfile)
        try:
            with (root / "build.log").open("w+b") as log:
                completed = subprocess.run(
                    ["docker", "build", "--tag", tag, str(root)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
                if completed.returncode:
                    log.seek(max(0, log.tell() - 8192))
                    detail = log.read().decode(errors="replace")
                    raise WorkerUnavailable("dependency preparation failed: " + detail)
            return _image_id(tag)
        except subprocess.TimeoutExpired as exc:
            raise WorkerUnavailable("dependency preparation timed out") from exc
        finally:
            subprocess.run(
                ["docker", "image", "rm", base_tag],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )


async def prepare_runtime(
    connection, context, storage, *, base_image, max_lock_bytes=4 * 1024 * 1024
):
    """Prepare only an explicitly selected ready version; planning never calls this."""
    if await owned_context(connection, context.user_id, context.version_id) != context:
        raise VersionNotFound("Package context does not match the owned version")
    lock_key = runtime_lock_key(context.version_id)
    acquired = await connection.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
    if not acquired:
        raise WorkerUnavailable("this package runtime is already being prepared")
    try:
        row = await connection.fetchrow(
            "SELECT manifest,runtime_state,runtime_image FROM package_versions WHERE id=$1 AND user_id=$2",
            context.version_id,
            context.user_id,
        )
        if row["runtime_state"] == "ready":
            try:
                await asyncio.to_thread(_image_id, row["runtime_image"])
            except subprocess.CalledProcessError:
                pass
            else:
                image = await asyncio.to_thread(
                    refresh_worker_code,
                    row["runtime_image"],
                    tag="lunar-runtime-" + context.version_id.hex,
                )
                await connection.execute(
                    "UPDATE package_versions SET runtime_image=$3 WHERE id=$1 AND user_id=$2",
                    context.version_id,
                    context.user_id,
                    image,
                )
                return image
        manifest = (
            json.loads(row["manifest"])
            if isinstance(row["manifest"], str)
            else row["manifest"]
        )
        from ..source_workflows import runtime_manifest

        manifest = runtime_manifest(manifest, storage.version_root(context))
        await connection.execute(
            "UPDATE package_versions SET runtime_state='preparing',runtime_image=NULL,error=NULL WHERE id=$1 AND user_id=$2",
            context.version_id,
            context.user_id,
        )
        try:
            base_identity = await asyncio.to_thread(_image_id, base_image)
            await asyncio.to_thread(check_capabilities, manifest, base_identity)
            python_version = await asyncio.to_thread(_python_version, base_identity)
            if python_version not in SpecifierSet(manifest["runtime"]["python"]):
                raise WorkerUnavailable(
                    "declared Python requirement does not match the worker base"
                )
            declaration = manifest["runtime"]["requirements_lock"]
            requirements = ""
            if declaration:
                path = storage.package_file(context, declaration)
                entry = next(
                    item for item in manifest["files"] if item["path"] == declaration
                )
                if (
                    entry["size"] > max_lock_bytes
                    or path.stat().st_size > max_lock_bytes
                ):
                    raise WorkerUnavailable(
                        "dependency lock exceeds the preparation limit"
                    )
                payload = path.read_bytes()
                if (
                    len(payload) != entry["size"]
                    or hashlib.sha256(payload).hexdigest() != entry["sha256"]
                ):
                    raise WorkerUnavailable(
                        "dependency lock content differs from the imported version"
                    )
                requirements = checked_requirements(payload.decode("utf-8"))
            image = await asyncio.to_thread(
                build_runtime,
                version_id=context.version_id,
                base_image=base_identity,
                requirements=requirements,
            )
            # The dependency layer may have come from a stale mutable base tag.
            # Always overlay and label the worker files owned by this backend.
            image = await asyncio.to_thread(
                refresh_worker_code,
                image,
                tag="lunar-runtime-" + context.version_id.hex,
            )
        except Exception as exc:
            await connection.execute(
                "UPDATE package_versions SET runtime_state='failed',error=$3 WHERE id=$1 AND user_id=$2",
                context.version_id,
                context.user_id,
                str(exc)[-8192:],
            )
            raise
        await connection.execute(
            "UPDATE package_versions SET runtime_state='ready',runtime_image=$3,error=NULL WHERE id=$1 AND user_id=$2",
            context.version_id,
            context.user_id,
            image,
        )
        return image
    finally:
        await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)


async def recover_runtime_preparations(connection):
    """Fail abandoned preparations while retaining ones locked by live processes."""
    recovered = []
    for row in await connection.fetch(
        "SELECT id FROM package_versions WHERE runtime_state='preparing'"
    ):
        lock_key = runtime_lock_key(row["id"])
        if not await connection.fetchval("SELECT pg_try_advisory_lock($1)", lock_key):
            continue
        try:
            result = await connection.execute(
                "UPDATE package_versions SET runtime_state='failed',runtime_image=NULL,error='Runtime preparation was interrupted' WHERE id=$1 AND runtime_state='preparing'",
                row["id"],
            )
            if result == "UPDATE 1":
                recovered.append(row["id"])
        finally:
            await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)
    return recovered
