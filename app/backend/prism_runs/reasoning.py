# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bounded public decision projection; presentation is never source evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from platform_runtime.reasoning_log import build_reasoning_log

IconId = Literal[
    "DataSource",
    "building_mechanistic_model",
    "decomposing_problem",
    "evaluating_evidence_strength",
    "extracting_criteria",
    "generating_code",
    "generating_counter-arguments",
    "generating_data_visualization",
    "getting_trusted_sources",
    "interpreting_web_sources",
    "parametrizing_model",
    "reasoning_over_facts",
    "verifying_logical_correctness",
]
ICON_IDS = (
    "DataSource",
    "building_mechanistic_model",
    "decomposing_problem",
    "evaluating_evidence_strength",
    "extracting_criteria",
    "generating_code",
    "generating_counter-arguments",
    "generating_data_visualization",
    "getting_trusted_sources",
    "interpreting_web_sources",
    "parametrizing_model",
    "reasoning_over_facts",
    "verifying_logical_correctness",
)
LEGACY_ICONS = {
    "running": "reasoning_over_facts",
    "reasoning": "reasoning_over_facts",
    "data": "DataSource",
    "checking": "verifying_logical_correctness",
    "success": "verifying_logical_correctness",
    "warning": "evaluating_evidence_strength",
    "failure": "generating_counter-arguments",
    "information": "reasoning_over_facts",
}
STATUS_MAP = {
    "queued": "deferred",
    "running": "informational",
    "completed": "accepted",
    "accepted": "accepted",
    "rejected": "rejected",
    "failed": "rejected",
    "interrupted": "blocked",
    "cancelled": "blocked",
}
MISSING_RATIONALE = "No source-provided rationale is available."


def public_text(value: Any) -> str | None:
    # Never stringify containers or traverse arbitrary provider payloads.
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        return None
    if re.search(
        r"<|>|https?://|(?:/Users/|/home/|/private/|[A-Z]:\\)|(?:api[_ -]?key|password|bearer|patient[_ -]?id)\s*[:=]",
        value,
        re.I,
    ):
        return None
    return value.strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelperOutput(StrictModel):
    helper_text: str = Field(min_length=1, max_length=600)
    icon_id: IconId

    @field_validator("helper_text")
    @classmethod
    def plain_text(cls, value):
        if public_text(value) is None or re.search(
            r"javascript:|data:|```", value, re.I
        ):
            raise ValueError("plain public text required")
        return value


class Presentation(StrictModel):
    status: Literal["pending", "ready", "unavailable"] = "pending"
    helper_text: str | None = None
    icon_id: IconId = "reasoning_over_facts"
    model_identity: str | None = Field(
        default=None, max_length=160, pattern=r"^[a-zA-Z0-9._:/-]+$"
    )
    unavailable_reason: (
        Literal[
            "not_configured",
            "invalid_configuration",
            "timeout",
            "provider_error",
            "invalid_output",
            "interrupted",
        ]
        | None
    ) = None

    @field_validator("icon_id", mode="before")
    @classmethod
    def legacy_icon(cls, value):
        # Persisted presentations from the previous catalog remain readable.
        return LEGACY_ICONS.get(value, value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def settled(self):
        if self.status == "ready":
            if self.helper_text is None:
                raise ValueError("ready presentation requires generated text")
            HelperOutput(helper_text=self.helper_text, icon_id=self.icon_id)
            if self.unavailable_reason is not None:
                raise ValueError("ready presentation cannot be unavailable")
        elif self.helper_text is not None:
            raise ValueError("only ready presentations have generated text")
        if (self.status == "unavailable") != (self.unavailable_reason is not None):
            raise ValueError("unavailability requires a safe reason")
        return self


class ModelCall(StrictModel):
    model_id: str
    input_text: str | None = None
    output_text: str | None = None


class ReasoningStep(StrictModel):
    name: str
    component: str
    workflow: str


class PublicSource(StrictModel):
    stage: str = Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9._:/ -]+$")
    status: Literal[
        "queued",
        "running",
        "completed",
        "accepted",
        "rejected",
        "failed",
        "interrupted",
        "cancelled",
    ]
    summary: str = Field(min_length=1, max_length=2000)
    rationale_summary: str = MISSING_RATIONALE
    limitations: list[str] = Field(default_factory=list, max_length=10)
    evidence_references: list[str] = Field(default_factory=list, max_length=10)
    model_call: ModelCall | None = None
    reasoning_step: ReasoningStep | None = None

    @field_validator("summary", "rationale_summary")
    @classmethod
    def safe_text(cls, value):
        if public_text(value) is None:
            raise ValueError("unsafe public source text")
        return value

    @field_validator("limitations")
    @classmethod
    def safe_limitations(cls, values):
        if any(public_text(value) is None for value in values):
            raise ValueError("unsafe limitation")
        return values

    @field_validator("evidence_references")
    @classmethod
    def safe_references(cls, values):
        if any(
            not re.fullmatch(
                r"(?:effect|source|artifact):[a-zA-Z0-9_.:-]{1,160}|sha256:[0-9a-f]{64}",
                value,
            )
            for value in values
        ):
            raise ValueError("reference handles required")
        return values


def project_source(
    *,
    stage: str,
    status: Literal[
        "queued",
        "running",
        "completed",
        "accepted",
        "rejected",
        "failed",
        "interrupted",
        "cancelled",
    ],
    result: Any = None,
    evidence_references=(),
    model_call=None,
    reasoning_step=None,
) -> PublicSource:
    public = result if isinstance(result, dict) else {}
    rationale = public_text(public.get("rationale_summary")) or MISSING_RATIONALE
    limitations = public.get("limitations", [])
    return PublicSource(
        stage=stage,
        status=status,
        summary=public_text(public.get("summary"))
        or f'{stage.replace("_", " ")} {"started" if status == "running" else status}.',
        rationale_summary=rationale,
        limitations=(
            [text for value in limitations[:10] if (text := public_text(value))]
            if isinstance(limitations, list)
            else []
        ),
        evidence_references=list(evidence_references)[:10],
        model_call=model_call,
        reasoning_step=reasoning_step,
    )


def source_digest(source: PublicSource) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                # Preserve the digest of entries recorded before optional details existed.
                source.model_dump(exclude_none=True),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )


class ReasoningEntry(StrictModel):
    id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    source_event_key: str = Field(min_length=1, max_length=200)
    event_kind: Literal["run", "stage", "model"]
    observed_at: datetime
    source: PublicSource
    source_digest: str
    presentation: Presentation = Field(default_factory=Presentation)

    @model_validator(mode="after")
    def verify_digest(self):
        if self.source_digest != source_digest(self.source):
            raise ValueError("source digest mismatch")
        return self


def canonical_snapshot(run_id: str, state: str, entries: list[ReasoningEntry]):
    if not entries:
        return None
    return build_reasoning_log(
        subject_kind="workflow",
        subject_id=run_id,
        summary="Recorded public run decisions.",
        status={"queued": "planned", "cancelled": "blocked"}.get(state, state),
        events=[
            dict(
                entry_id=str(row.id),
                stage=row.source.stage,
                action=row.source.summary,
                rationale_summary=row.source.rationale_summary,
                decision={
                    "status": STATUS_MAP[row.source.status],
                    "outcome": row.source.summary,
                },
                inputs_used=row.source.evidence_references,
            )
            for row in entries
        ],
        limitations=list(
            dict.fromkeys(text for row in entries for text in row.source.limitations)
        ),
    )
