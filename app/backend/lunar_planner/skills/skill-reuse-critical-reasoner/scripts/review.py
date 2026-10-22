# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys

# Resolve the containing Lunar backend when invoked as an absolute script.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from lunar_planner.navigation import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("review"))
