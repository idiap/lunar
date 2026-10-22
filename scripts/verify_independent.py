# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Run the offline L0-L5/E0 matrix inside Lunar's standalone verification image.

Database URLs must be reachable from Docker. Only two ZIPs, a fresh output directory
and the Docker socket are mounted. This command never runs the genuine-provider E1
suite and does not receive model credential environment variables.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

GATES = {
    "L0": ["uv", "run", "--group", "mcp-backend", "pytest", "-q"],
    "L1-test": ["npm", "--prefix", "app/frontend", "test"],
    "L1-build": ["npm", "--prefix", "app/frontend", "run", "build"],
    "L2": ["uv", "run", "--group", "mcp-backend", "pytest", "app/backend/tests", "-q"],
    "L3": [
        "uv",
        "run",
        "--group",
        "mcp-backend",
        "pytest",
        "--run-expensive",
        "tests/planner",
        "tests/mcp_backend",
        "-q",
    ],
    "L4": [
        "uv",
        "run",
        "--group",
        "mcp-backend",
        "python",
        "planner/testing/verify_module.py",
    ],
    "L5": ["uv", "run", "--group", "mcp-backend", "pytest", "app/frontend/tests", "-q"],
    "E0": [
        "uv",
        "run",
        "--group",
        "mcp-backend",
        "pytest",
        "--run-e2e",
        "tests/e2e",
        "-q",
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="lunar-verification:local")
    parser.add_argument("--gate", choices=GATES, action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        args.output.resolve()
        if args.output
        else Path(tempfile.mkdtemp(prefix="lunar-independent-")).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)
    shared = output / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "tmp").mkdir(exist_ok=True)
    inputs = shared / "inputs"
    inputs.mkdir(exist_ok=True)
    environment = {
        "TMPDIR": "/tmp",
        "LUNAR_E2E_DOCKER_HOST_ADDRESS": "host.docker.internal",
    }
    for name in (
        "LUNAR_TEST_DATABASE_URL",
        "LUNAR_E2E_DATABASE_URL",
        "LUNAR_WORKER_IMAGE",
    ):
        environment[name] = os.environ[name]
    for name, filename in (
        ("LUNAR_E2E_BIOAGENTS_ZIP", "domain.zip"),
        ("LUNAR_E2E_BIOAGENTS_REPORT_ZIP", "reports.zip"),
    ):
        source = Path(os.environ[name]).resolve(strict=True)
        target = inputs / filename
        shutil.copyfile(source, target)
        environment[name] = str(target)
    image = subprocess.check_output(
        ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True
    ).strip()
    receipt = {"image": image, "inputs": {}}
    for path in inputs.iterdir():
        with path.open("rb") as stream:
            receipt["inputs"][path.name] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    (output / "inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")
    base = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--workdir",
        "/workspace",
        "--network",
        os.getenv("LUNAR_VERIFICATION_NETWORK", "bridge"),
        "--add-host",
        "host.docker.internal:host-gateway",
        "--mount",
        f"type=bind,src={shared},dst={shared}",
        "--mount",
        "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock",
    ]
    for name, value in environment.items():
        base += ["--env", name + "=" + value]
    # No checkout mount, no catalog installation, no provider secrets in this container.
    subprocess.run(
        base
        + [
            image,
            "python",
            "-c",
            "import importlib.util; from pathlib import Path; assert importlib.util.find_spec('catalog') is None; assert not Path('/workspace/catalog').exists()",
        ],
        check=True,
    )
    failed = []
    for gate in args.gate or GATES:
        with (output / (gate + ".log")).open("w") as log:
            command = list(GATES[gate])
            if "pytest" in command:
                command += ["--basetemp", str(shared / "tmp" / gate)]
            result = subprocess.run(
                base + [image, *command], stdout=log, stderr=subprocess.STDOUT
            )
        print(
            gate + ": " + ("passed" if result.returncode == 0 else "FAILED"), flush=True
        )
        if result.returncode:
            failed.append(gate)
    (output / "result.json").write_text(
        json.dumps({"failed": failed, "gates": args.gate or list(GATES)}, indent=2)
        + "\n"
    )
    print("Evidence: " + str(output), flush=True)
    raise SystemExit(bool(failed))


if __name__ == "__main__":
    main()
