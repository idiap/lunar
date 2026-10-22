# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Validated public and internal Prism run schemas."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PrismRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["run"] = "run"
    ai_model_id: UUID | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    network_authority: bool = False


class RunListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ReasoningSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=160)
    run_ids: list[UUID] = Field(min_length=1, max_length=8)
