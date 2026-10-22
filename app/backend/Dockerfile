# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
FROM docker:28-cli AS docker-client
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir uv==0.11.14
COPY --from=docker-client /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /workspace
ENV PATH="/workspace/.venv/bin:$PATH" \
    PYTHONPATH="/workspace/app/backend:/workspace" \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --group mcp-backend
COPY app/backend ./app/backend

WORKDIR /workspace/app/backend
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = development ]; then cd /workspace/live/backend && export PYTHONPATH=/workspace/live/backend:/workspace/live; fi; python wait_for_database.py && alembic upgrade head && python schema.py && if [ \"$ENVIRONMENT\" = development ]; then exec uvicorn server:app --host 0.0.0.0 --port 8000 --reload --reload-dir /workspace/live/backend; else exec uvicorn server:app --host 0.0.0.0 --port 8000; fi"]
