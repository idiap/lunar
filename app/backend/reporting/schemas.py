# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Template binding and generated-report schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TemplateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_name: str = Field(min_length=1, max_length=200)
    bindings: dict[str, UUID]
