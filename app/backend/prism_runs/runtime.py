# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Confined recording loaders and runtime receipts for Prism adapters."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol


class SourceBinding(Protocol):
    """Structural type for the retired adapter runtime boundary."""

    resource_id: str
    source_local_identifier: str
    access_point_id: str | None
    operation_id: str | None
    access_mode: str
    version_or_snapshot: str
    safe_locator: str
    metadata: dict[str, Any]


class WorkflowAdapter(Protocol):
    """Structural type for the legacy receipt recorder."""

    allowed_data_roots: list[Path]
    stages: list[Any]


SECRET_KEY = re.compile(
    r"(?:secret|password|token|credential|api[_-]?key|prompt)", re.I
)


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def text_digest(value: str) -> str:
    return bytes_digest(value.encode("utf-8"))


def _artifact_key(relative_path: str) -> str:
    path = Path(relative_path)
    if path.parent == Path("."):
        return path.stem.replace("-", "_")
    return re.sub(r"[^a-zA-Z0-9_]+", "_", path.as_posix()).strip("_")


def safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): "[redacted]" if SECRET_KEY.search(str(key)) else item
        for key, item in (value or {}).items()
        if not isinstance(item, (bytes, bytearray))
    }


@dataclass
class ConsumedSourceReceipt:
    resource_id: str
    source_local_identifier: str
    access_point_id: str | None
    operation_id: str | None
    access_mode: str
    version_or_snapshot: str
    safe_locator: str
    content_digest: str
    observed_at: datetime
    metadata: dict[str, Any]


@dataclass
class InputEntityReceipt:
    input_key: str
    kind: str
    safe_locator: str
    content_digest: str
    observed_at: datetime
    metadata: dict[str, Any]


@dataclass
class StageReceipt:
    stage_id: str
    component_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    safe_summary: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactReceipt:
    artifact_key: str
    safe_locator: str
    media_type: str
    content_digest: str
    provenance_entity_id: str


@dataclass
class WorkflowExecutionResult:
    markdown: str
    structured_value: dict[str, Any] | None = None
    artifacts: list[ArtifactReceipt] = field(default_factory=list)
    analysis_results: dict[str, Any] = field(default_factory=dict)
    compact_prism_input: dict[str, Any] = field(default_factory=dict)
    narrative_slots: list[dict[str, str]] = field(default_factory=list)
    report_verification: dict[str, Any] | None = None


class RuntimeContext:
    def __init__(
        self,
        adapter: WorkflowAdapter,
        run_id: str,
        run_root: Path,
        mode: str,
        on_reasoning=None,
    ):
        self.on_reasoning = on_reasoning
        self.adapter = adapter
        self.run_id = run_id
        self.run_root = run_root.resolve()
        self.mode = mode
        self.consumed_sources: list[ConsumedSourceReceipt] = []
        self.input_entities: list[InputEntityReceipt] = []
        self.stages: list[StageReceipt] = []
        self.artifacts: list[ArtifactReceipt] = []

    def _source_path(self, path: Path) -> tuple[Path, str]:
        resolved = path.resolve()
        for root in self.adapter.allowed_data_roots:
            root = root.resolve()
            if resolved == root or root in resolved.parents:
                return resolved, f"data:{resolved.relative_to(root).as_posix()}"
        raise ValueError("source path is outside configured data roots")

    @contextmanager
    def stage(self, stage_id: str) -> Iterator[StageReceipt]:
        binding = next(
            (item for item in self.adapter.stages if item.stage_id == stage_id), None
        )
        if binding is None:
            raise ValueError(f"undeclared runtime stage: {stage_id}")
        receipt = StageReceipt(
            stage_id=stage_id,
            component_id=binding.component_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.stages.append(receipt)
        event_key = f"stage:{len(self.stages)}"

        def observe(status, observed_at):
            if self.on_reasoning:
                self.on_reasoning(
                    source_event_key=f"{event_key}:{status}",
                    event_kind="stage",
                    observed_at=observed_at,
                    stage=stage_id,
                    status=status,
                )

        observe("running", receipt.started_at)
        try:
            yield receipt
        except Exception as exc:
            receipt.status = "failed"
            receipt.safe_summary = str(exc)[:500]
            receipt.finished_at = datetime.now(timezone.utc)
            observe("failed", receipt.finished_at)
            raise
        receipt.status = "completed"
        receipt.finished_at = datetime.now(timezone.utc)
        observe("completed", receipt.finished_at)

    def read_input(
        self,
        path: Path,
        *,
        input_key: str,
        kind: str = "local_file",
        metadata: dict[str, Any] | None = None,
    ) -> bytes:
        resolved, locator = self._source_path(path)
        content = resolved.read_bytes()
        self.input_entities.append(
            InputEntityReceipt(
                input_key=input_key,
                kind=kind,
                safe_locator=locator,
                content_digest=bytes_digest(content),
                observed_at=datetime.now(timezone.utc),
                metadata=safe_metadata(metadata),
            )
        )
        return content

    def read_json_input(self, path: Path, **kwargs: Any) -> Any:
        return json.loads(self.read_input(path, **kwargs).decode("utf-8"))

    def observe_input_value(
        self,
        value: bytes,
        *,
        input_key: str,
        kind: str,
        safe_locator: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.input_entities.append(
            InputEntityReceipt(
                input_key=input_key,
                kind=kind,
                safe_locator=safe_locator,
                content_digest=bytes_digest(value),
                observed_at=datetime.now(timezone.utc),
                metadata=safe_metadata(metadata),
            )
        )

    def observe_source_record(
        self,
        *,
        binding: SourceBinding,
        content: bytes,
        safe_locator: str,
        local_identifier: str,
        access_mode: str,
        version_or_snapshot: str,
        access_point_id: str | None = None,
        operation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.consumed_sources.append(
            ConsumedSourceReceipt(
                resource_id=binding.resource_id,
                source_local_identifier=local_identifier,
                access_point_id=access_point_id,
                operation_id=operation_id,
                access_mode=access_mode,
                version_or_snapshot=version_or_snapshot,
                safe_locator=safe_locator,
                content_digest=bytes_digest(content),
                observed_at=datetime.now(timezone.utc),
                metadata=safe_metadata({**dict(binding.metadata), **(metadata or {})}),
            )
        )

    def read_source_file(
        self,
        path: Path,
        *,
        binding: SourceBinding,
        local_identifier: str,
        access_mode: str,
        version_or_snapshot: str,
        access_point_id: str | None = None,
        operation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bytes:
        resolved, locator = self._source_path(path)
        content = resolved.read_bytes()
        self.observe_source_record(
            binding=binding,
            content=content,
            safe_locator=locator,
            local_identifier=local_identifier,
            access_mode=access_mode,
            version_or_snapshot=version_or_snapshot,
            access_point_id=access_point_id,
            operation_id=operation_id,
            metadata=metadata,
        )
        return content

    def write_artifact(
        self, relative_path: str, content: bytes, media_type: str
    ) -> ArtifactReceipt:
        path = (self.run_root / relative_path).resolve()
        if self.run_root not in path.parents:
            raise ValueError("artifact path escapes the confined run root")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        key = _artifact_key(relative_path)
        receipt = ArtifactReceipt(
            artifact_key=key,
            safe_locator=f"run:{Path(relative_path).as_posix()}",
            media_type=media_type,
            content_digest=bytes_digest(content),
            provenance_entity_id=f"entity:run:{self.run_id}:artifact:{key}",
        )
        self.artifacts.append(receipt)
        return receipt

    def capture_artifact(self, relative_path: str, media_type: str) -> ArtifactReceipt:
        path = (self.run_root / relative_path).resolve()
        if self.run_root not in path.parents or not path.is_file():
            raise ValueError(
                "required generated artifact is unavailable or outside the run root"
            )
        content = path.read_bytes()
        key = _artifact_key(relative_path)
        receipt = ArtifactReceipt(
            artifact_key=key,
            safe_locator=f"run:{Path(relative_path).as_posix()}",
            media_type=media_type,
            content_digest=bytes_digest(content),
            provenance_entity_id=f"entity:run:{self.run_id}:artifact:{key}",
        )
        self.artifacts.append(receipt)
        return receipt
