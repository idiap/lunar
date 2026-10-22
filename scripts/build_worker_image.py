# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build the host-owned worker from Lunar's locked generic dependencies."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", default="lunar-worker:local", help="local worker image tag"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    worker = root / "app/backend/domain_packages/worker"
    base = "lunar-worker-build-base-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="lunar-worker-build-") as raw:
        context = Path(raw)
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copyfile(root / name, context / name)
        shutil.copyfile(worker / "Dockerfile.base", context / "Dockerfile")
        try:
            subprocess.run(["docker", "build", "--tag", base, str(context)], check=True)
            shutil.copyfile(worker / "Dockerfile.runtime", context / "Dockerfile")
            shutil.copyfile(worker / "main.py", context / "main.py")
            shutil.copyfile(worker / "prism.py", context / "prism_engine.py")
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--build-arg",
                    "LUNAR_WORKER_BASE=" + base,
                    "--tag",
                    args.tag,
                    str(context),
                ],
                check=True,
            )
            identity = subprocess.check_output(
                ["docker", "image", "inspect", args.tag, "--format", "{{.Id}}"],
                text=True,
            ).strip()
            print(identity)
        finally:
            subprocess.run(
                ["docker", "image", "rm", base],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
