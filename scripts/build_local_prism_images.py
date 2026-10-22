# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build local Lunar images with the declared PRISM Git dependency available.

For file URLs, Docker receives a local bare repository. Remote URLs are fetched
by uv using uv.lock's exact revision. The normal backend and worker Dockerfiles
supply all other steps.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
from urllib.parse import unquote, urlparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["worker", "backend"], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sources = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["uv"][
        "sources"
    ]
    source = sources["prism-runtime"]
    uri = urlparse(source["git"])
    repository = Path(unquote(uri.path)) if uri.scheme == "file" else None
    worker = root / "app/backend/domain_packages/worker"
    with tempfile.TemporaryDirectory(prefix="lunar-local-prism-") as raw:
        context = Path(raw)
        if repository is not None:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--bare",
                    "--no-hardlinks",
                    str(repository),
                    str(context / "local-prism.git"),
                ],
                check=True,
            )
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copyfile(root / name, context / name)
        dockerfile = (
            worker / "Dockerfile.base"
            if args.target == "worker"
            else root / "app/backend/Dockerfile"
        ).read_text()
        if repository is not None:
            dockerfile = dockerfile.replace(
                "COPY pyproject.toml uv.lock",
                f"COPY local-prism.git {repository}\nCOPY pyproject.toml uv.lock",
                1,
            )
        if args.target == "worker":
            dockerfile += "\nCOPY main.py prism_engine.py /opt/lunar-worker/\n"
            shutil.copyfile(worker / "main.py", context / "main.py")
            shutil.copyfile(worker / "prism.py", context / "prism_engine.py")
            dockerfile += 'LABEL org.lunar.role="worker-runtime"\n'
        else:
            shutil.copytree(
                root / "app/backend",
                context / "app/backend",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        (context / "Dockerfile").write_text(dockerfile)
        subprocess.run(
            ["docker", "build", "--tag", f"lunar-{args.target}:local", str(context)],
            check=True,
        )


if __name__ == "__main__":
    main()
