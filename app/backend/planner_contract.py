# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Transport-independent public contract for the automatic planner."""

from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from prism_runs.reasoning import ReasoningEntry, StrictModel


class PlannerInput(StrictModel):
    ai_model_id: UUID | None = Field(
        default=None,
        description="An owned AI model configuration for workflow execution.",
    )
    command_text: str = Field(
        min_length=1, description="The user's natural-language request for this turn."
    )
    references: list[str] | None = None
    desired_inputs: list[str] | None = None
    desired_outputs: list[str] | None = None
    supplied_inputs: dict[str, Any] | None = Field(
        default=None,
        description="Known facts; use the returned questions' missing_fields keys when answering questions.",
    )
    continuation_id: str | None = Field(
        default=None,
        description="The opaque continuation_id returned for required clarification.",
    )

    @field_validator("command_text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("request must not be blank")
        return value

    @field_validator("supplied_inputs")
    @classmethod
    def no_internal_inputs(cls, value):
        reserved = {
            "quality_review_id",
            "principal",
            "accepted_plan_digest",
            "prepared_execution_id",
            "approval",
            "approval_mechanism",
            "allow_network",
            "allow_write",
            "approved_permissions",
            "frozen_outcome_quality_contract",
            "outcome_quality_review",
            "authorized_outcome_quality_review",
            "frozen_delivery_quality_plan",
            "delivery_quality_review",
            "authorized_delivery_quality_review",
        }
        if reserved.intersection(value or {}):
            raise ValueError("internal execution and quality inputs are server-owned")
        return value


class PlannerReasoning(StrictModel):
    type: Literal["snapshot"] = "snapshot"
    run_id: UUID
    state: Literal["running", "completed", "failed", "blocked"]
    entries: list[ReasoningEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def invocation(self):
        if any(entry.run_id != self.run_id for entry in self.entries):
            raise ValueError("reasoning belongs to another invocation")
        if [entry.sequence for entry in self.entries] != list(
            range(1, len(self.entries) + 1)
        ):
            raise ValueError("reasoning sequence must be unique and ordered")
        if len({entry.source_event_key for entry in self.entries}) != len(self.entries):
            raise ValueError("duplicate reasoning event key")
        if self.state != "running" and any(
            entry.source.status == "running" for entry in self.entries
        ):
            raise ValueError("terminal reasoning cannot contain running entries")
        return self


class PlannerResult(StrictModel):
    status: Literal[
        "completed", "planning_only", "clarification_required", "blocked", "failed"
    ]
    execution_status: Literal[
        "not_started", "completed", "handoff", "blocked", "failed"
    ] = "not_started"
    questions: list[Any] = Field(default_factory=list)
    continuation_id: str | None = None
    blockers: list[str] = Field(default_factory=list, max_length=10)
    released_artifact: Any = None
    report: dict[str, str] | None = None
    publication: Literal["not_attempted", "published", "unavailable", "failed"] = (
        "not_attempted"
    )
    publication_error: str | None = None
    plan: dict[str, Any] | None = None
    reasoning: PlannerReasoning

    @model_validator(mode="after")
    def delivery(self):
        if self.status == "completed" and (
            self.execution_status != "completed" or self.released_artifact is None
        ):
            raise ValueError("completion requires execution and a released artifact")
        if (self.report is not None) != (self.publication == "published"):
            raise ValueError("report requires successful publication")
        return self
