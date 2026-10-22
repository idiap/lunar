# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build the distributable frontend once for browser regression tests."""

from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope="session")
def frontend_build() -> Path:
    frontend_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["npm", "run", "build"],
        cwd=frontend_root,
        check=True,
        timeout=120,
        capture_output=True,
        text=True,
    )
    return frontend_root
