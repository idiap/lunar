# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Request and response schemas for data-source APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DataSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    visibility: str
    name: str
    category: str
    scope: str
    canonical_uri: str
    posture: str
    claim_ceiling: str
    owner: str
    refresh_trigger: str
    verified_as_of: str
    schema_version: str
    catalog_digest: str
    aliases: list[Any]
    modalities: list[Any]
    selection: dict[str, Any] | None = None


class DataSourceDetail(DataSourceSummary):
    workflows: list[dict[str, Any]]
    datasets: list[dict[str, Any]]
    entities: list[Any]
    identifiers: list[Any]
    access_points: list[Any]
    operations: list[Any]
    candidate_operations: list[Any]
    lineage: list[Any]
    descriptor: dict[str, Any]
