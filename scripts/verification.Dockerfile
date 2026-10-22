# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
# Test-only image: no domain checkout or scientific base dependencies.
FROM node:22-bookworm-slim AS node
FROM docker:28-cli AS docker-client
FROM python:3.13-slim
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir uv==0.11.14
WORKDIR /workspace
ENV PATH="/workspace/.venv/bin:$PATH" PYTHONPATH="/workspace/app/backend:/workspace" UV_LINK_MODE=copy
COPY --from=docker-client /usr/local/bin/docker /usr/local/bin/docker
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=docker-client /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
COPY pyproject.toml uv.lock conftest.py README.md ./
RUN uv sync --locked --group mcp-backend
COPY app/frontend/package.json app/frontend/package-lock.json ./app/frontend/
RUN npm --prefix app/frontend ci \
    && playwright install --with-deps chromium
COPY planner ./planner
COPY app ./app
COPY tests ./tests
COPY benchmarks ./benchmarks
COPY scripts ./scripts
CMD ["pytest"]
