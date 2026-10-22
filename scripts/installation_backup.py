# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Matched offline PostgreSQL/package checkpoint for a local Compose Docker host.

Run with the filesystem permissions of the installation operator (root on Linux).
Restore accepts only an empty package directory and an empty public DB schema.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Backup refuses symbolic links: {path}")
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
        elif not path.is_dir():
            raise ValueError(f"Backup refuses special files: {path}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--env-file", default=str(ROOT / "app/.env"))
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--compose-file", action="append", default=[])
    args = parser.parse_args()
    compose = [
        "docker",
        "compose",
        "--env-file",
        args.env_file,
        "-p",
        args.project_name,
        "-f",
        str(ROOT / "app/docker-compose.yml"),
    ]
    for filename in args.compose_file:
        compose += ["-f", filename]
    config = json.loads(
        run(compose + ["config", "--format", "json"], capture_output=True).stdout
    )
    environment = config["services"]["backend"]["environment"]
    storage = Path(environment["LUNAR_PACKAGE_STORAGE_ROOT"])
    if not storage.is_absolute() or storage.is_symlink() or storage == Path("/"):
        raise ValueError(
            "Package storage must be an absolute, non-symlink directory below root"
        )
    checkpoint = args.checkpoint.resolve()
    if checkpoint.is_relative_to(storage.resolve()) or storage.resolve().is_relative_to(
        checkpoint
    ):
        raise ValueError("Checkpoint and live storage must be separate directories")
    pg_env = config["services"]["db"]["environment"]
    pg = compose + ["exec", "-T", "db"]
    identity = ["-U", pg_env["POSTGRES_USER"], "-d", pg_env["POSTGRES_DB"]]
    if args.operation == "backup":
        if (
            checkpoint.exists()
            or checkpoint.with_name(checkpoint.name + ".partial").exists()
        ):
            raise ValueError("Choose a new checkpoint directory")
        if not storage.is_dir():
            raise ValueError("Live package storage is missing")
    else:
        expected = json.loads((checkpoint / "checkpoint.json").read_text())
        if inventory(checkpoint / "payload") != expected["sha256"]:
            raise ValueError(
                "Checkpoint bytes do not match the recorded digest inventory"
            )
        if storage.exists() and any(storage.iterdir()):
            raise ValueError("Restore requires empty package storage")
    # Stop the sole API before either checkpoint operation; restore failures leave it stopped.
    run(compose + ["stop", "backend"])
    # Workers have no database access. Quiesce only workers mounting this installation.
    ids = run(
        ["docker", "ps", "-q", "--filter", "name=lunar-worker-"],
        capture_output=True,
        text=True,
    ).stdout.split()
    if ids:
        containers = json.loads(
            run(["docker", "inspect", *ids], capture_output=True).stdout
        )
        for container in containers:
            if any(
                Path(mount["Source"]).is_relative_to(storage)
                for mount in container.get("Mounts", [])
                if mount.get("Type") == "bind"
            ):
                run(["docker", "stop", "--time", "10", container["Id"]])
    if args.operation == "backup":
        partial = checkpoint.with_name(checkpoint.name + ".partial")
        try:
            partial.mkdir(mode=0o700, parents=True)
            payload = partial / "payload"
            payload.mkdir()
            with (payload / "database.dump").open("wb") as dump:
                run(
                    pg
                    + [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        *identity,
                    ],
                    stdout=dump,
                )
            inventory(
                storage
            )  # Refuse links/special files before copying, never dereference them.
            shutil.copytree(storage, payload / "packages", symlinks=True)
            receipt = {
                "format": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sha256": inventory(payload),
            }
            (partial / "checkpoint.json").write_text(
                json.dumps(receipt, indent=2) + "\n"
            )
            partial.rename(checkpoint)
        finally:
            run(compose + ["start", "backend"])
    else:
        tables = run(
            pg
            + [
                "psql",
                *identity,
                "-Atc",
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tables != "0":
            raise ValueError(
                "Restore requires an empty public database schema; API remains stopped"
            )
        storage.mkdir(parents=True, exist_ok=True)
        shutil.copytree(checkpoint / "payload/packages", storage, dirs_exist_ok=True)
        with (checkpoint / "payload/database.dump").open("rb") as dump:
            run(
                pg
                + [
                    "pg_restore",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    *identity,
                ],
                stdin=dump,
            )
        run(compose + ["up", "-d", "backend", "frontend"])
    print(f"{args.operation} complete: {checkpoint}")


if __name__ == "__main__":
    main()
