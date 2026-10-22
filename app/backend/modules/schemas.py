# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PromptInput(BaseModel):
    name: str = Field(min_length=1)
    content: str | None = None
    directory_id: UUID | None = None


class PromptUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    directory_id: UUID | None = None


class PromptDirectoryInput(BaseModel):
    name: str = Field(min_length=1)
    parent_id: UUID | None = None


class PromptDirectoryMove(BaseModel):
    parent_id: UUID | None = None


class TemplateInput(BaseModel):
    name: str = Field(min_length=1)
    content: str
    agent: UUID | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    agent: UUID | None = None


class AIModelInput(BaseModel):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    api_base: str | None = None
    api_version: str | None = None
    api_key: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class AIModelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model_id: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    config: dict[str, Any] | None = None


class RunPromptInput(BaseModel):
    prompt: str
    ai_model_id: UUID
    parameters: dict[str, Any] | None = None
    variables: dict[str, str] | None = None


class ReportInput(BaseModel):
    name: str = Field(min_length=1)
    content: str
    content_type_id: int | None = None


class ReportUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    provenance_data: dict[str, Any] | None = None
    content_type_id: int | None = None
