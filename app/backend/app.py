# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""CLI and ASGI entrypoint for the Lunar application backend."""

from server import app, build_parser, main, mcp

__all__ = ["app", "build_parser", "main", "mcp"]


if __name__ == "__main__":
    main()
