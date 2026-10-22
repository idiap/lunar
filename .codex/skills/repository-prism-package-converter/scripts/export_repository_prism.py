#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build one deterministic Lunar PRISM package from an explicit repository map."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib
import json
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

IGNORED_NAMES = {
    ".DS_Store",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".jsonl",
    ".md",
    ".prism",
    ".py",
    ".rflow",
    ".rst",
    ".sh",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,159}$")
RUNTIME_OPERATIONS = {"prepare", "execute", "verify", "plan"}
TOOL_VERSION = "repository-prism-package-converter/v1"


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def normalize_text(content: bytes, source: Path) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"declared text file is not UTF-8: {source}") from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return (text.rstrip("\n") + "\n").encode("utf-8")


def canonical_yaml(content: bytes, source: Path) -> bytes:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to canonicalize YAML data sources"
        ) from exc
    try:
        value = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid YAML: {source}") from exc
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    )
    return normalize_text(rendered.encode("utf-8"), source)


def converted_bytes(source: Path) -> tuple[bytes, str]:
    raw = source.read_bytes()
    suffix = source.suffix.lower()
    if suffix == ".json":
        try:
            return canonical_json(json.loads(raw.decode("utf-8"))), "canonical-json"
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON: {source}") from exc
    if suffix in {".yaml", ".yml"}:
        return canonical_yaml(raw, source), "canonical-yaml"
    if suffix in TEXT_SUFFIXES or source.name in {"SKILL.md", "LICENSE", "ROOT"}:
        return normalize_text(raw, source), "normalized-text"
    return raw, "exact-binary"


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def require_id(value: Any, label: str) -> str:
    identifier = require_string(value, label)
    if not ID_PATTERN.fullmatch(identifier):
        raise ValueError(
            f"{label} is not a stable lowercase identifier: {identifier!r}"
        )
    return identifier


def unique_ids(rows: list[Any], label: str) -> None:
    ids = [
        require_id(require_mapping(row, f"{label} item").get("id"), f"{label}.id")
        for row in rows
    ]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label} ids: {duplicates}")


def read_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read export configuration {path}: {exc}") from exc
    config = require_mapping(config, "configuration")
    if config.get("schema_version") != 1:
        raise ValueError("configuration.schema_version must equal 1")
    package = require_mapping(config.get("package"), "configuration.package")
    require_id(package.get("key"), "configuration.package.key")
    require_string(package.get("display_name"), "configuration.package.display_name")
    for key in ("skills", "data_sources", "workflows"):
        unique_ids(require_list(config.get(key), f"configuration.{key}"), key)
    runtime = require_mapping(config.get("runtime", {}), "configuration.runtime")
    entries = require_list(
        runtime.get("entrypoints", []), "configuration.runtime.entrypoints"
    )
    unique_ids(entries, "runtime entrypoint")
    for entry in entries:
        entry = require_mapping(entry, "runtime entrypoint")
        if entry.get("operation") not in RUNTIME_OPERATIONS:
            raise ValueError(f"invalid runtime operation: {entry.get('operation')!r}")
        require_string(entry.get("source"), "runtime entrypoint.source")
        require_string(entry.get("target"), "runtime entrypoint.target")
        require_string(entry.get("callable"), "runtime entrypoint.callable")
    require_list(config.get("exclusions", []), "configuration.exclusions")
    return config


def repository_path(root: Path, relative: str, *, file: bool | None = None) -> Path:
    pure = PurePosixPath(require_string(relative, "repository path"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"repository path escapes root: {relative!r}")
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"repository path is missing or outside root: {relative!r}"
        ) from exc
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(
                f"symlinks are not deterministic package inputs: {relative!r}"
            )
        cursor = cursor.parent
    if file is True and not resolved.is_file():
        raise ValueError(f"expected file: {relative!r}")
    if file is False and not resolved.is_dir():
        raise ValueError(f"expected directory: {relative!r}")
    return resolved


def excluded(relative: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)


def files_under(root: Path, base: Path, patterns: Iterable[str]) -> list[Path]:
    if base.is_file():
        return [base]
    result: list[Path] = []
    for path in sorted(
        base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()
    ):
        relative = path.relative_to(base).as_posix()
        if any(part in IGNORED_NAMES for part in path.relative_to(base).parts):
            continue
        if excluded(relative, patterns):
            continue
        if path.is_symlink():
            raise ValueError(
                f"symlink in declared package input: {path.relative_to(root)}"
            )
        if path.is_file():
            path.resolve(strict=True).relative_to(root)
            result.append(path)
    return result


def lunar_modules(lunar_root: Path):
    backend = lunar_root.resolve(strict=True) / "app" / "backend"
    if not (backend / "domain_packages" / "archive_builder.py").is_file():
        raise ValueError(f"Lunar backend not found below {lunar_root}")
    sys.path.insert(0, str(backend))
    try:
        builder = importlib.import_module("domain_packages.archive_builder")
        archive = importlib.import_module("domain_packages.archive")
    finally:
        sys.path.pop(0)
    return builder.ArchiveBuilder, archive.validate_archive


class Export:
    def __init__(
        self, builder: Any, root: Path, config_path: Path, config: dict[str, Any]
    ):
        self.builder = builder
        self.root = root
        self.config_path = config_path
        self.config = config
        self.archive_paths: set[str] = set()
        self.lock_rows: list[dict[str, Any]] = []

    def add(self, source: Path, target: str) -> str:
        target = PurePosixPath(target).as_posix()
        if target.startswith("/") or ".." in PurePosixPath(target).parts:
            raise ValueError(f"invalid archive path: {target}")
        if target in self.archive_paths:
            raise ValueError(f"duplicate archive path: {target}")
        content, conversion = converted_bytes(source)
        self.archive_paths.add(target)
        archived = self.builder.add_bytes(target, content)
        self.lock_rows.append(
            {
                "archive_path": archived,
                "archive_sha256": digest_bytes(content),
                "conversion": conversion,
                "source_path": source.relative_to(self.root).as_posix(),
                "source_sha256": digest_file(source),
            }
        )
        return archived

    def add_tree(
        self, source_root: Path, archive_root: str, patterns: Iterable[str]
    ) -> list[str]:
        files: list[str] = []
        for source in files_under(self.root, source_root, patterns):
            relative = (
                source.name
                if source_root.is_file()
                else source.relative_to(source_root).as_posix()
            )
            files.append(self.add(source, f"{archive_root}/{relative}"))
        if not files:
            raise ValueError(
                f"declared resource has no files: {source_root.relative_to(self.root)}"
            )
        return files

    def skills(self) -> set[str]:
        ids: set[str] = set()
        for row in sorted(self.config["skills"], key=lambda item: item["id"]):
            row = require_mapping(row, "skill")
            identifier = require_id(row.get("id"), "skill.id")
            source_root = repository_path(self.root, row["root"], file=False)
            skill_file = source_root / "SKILL.md"
            if not skill_file.is_file():
                raise ValueError(f"{identifier}: skill root has no SKILL.md")
            files = self.add_tree(
                source_root,
                f"skills/source/{identifier}",
                require_list(row.get("exclude", []), f"{identifier}.exclude"),
            )
            instructions = converted_bytes(skill_file)[0].decode("utf-8")
            description = require_string(
                row.get("description"), f"{identifier}.description"
            )
            document = {
                "id": identifier,
                "name": require_string(
                    row.get("name", identifier), f"{identifier}.name"
                ),
                "instructions": instructions,
                "groups": sorted(
                    set(require_list(row.get("groups", []), f"{identifier}.groups"))
                ),
                "capabilities": sorted(
                    set(
                        require_list(
                            row.get("capabilities", []), f"{identifier}.capabilities"
                        )
                    )
                ),
                "invocation": {
                    "kind": "codex-skill",
                    "entrypoint": f"skills/source/{identifier}/SKILL.md",
                },
                "metadata": {
                    **require_mapping(
                        row.get("metadata", {}), f"{identifier}.metadata"
                    ),
                    "description": description,
                    "source_path": skill_file.relative_to(self.root).as_posix(),
                    "source_sha256": digest_file(skill_file),
                },
            }
            self.builder.add_resource("skills", document, files=files)
            ids.add(identifier)
        return ids

    def data_sources(self) -> None:
        for row in sorted(self.config["data_sources"], key=lambda item: item["id"]):
            row = require_mapping(row, "data source")
            identifier = require_id(row.get("id"), "data source.id")
            prefix = PurePosixPath(
                require_string(row.get("prefix"), f"{identifier}.prefix")
            ).as_posix()
            if prefix.startswith("/") or ".." in PurePosixPath(prefix).parts:
                raise ValueError(f"{identifier}: invalid data-source prefix")
            patterns = require_list(row.get("exclude", []), f"{identifier}.exclude")
            local_files: list[dict[str, str]] = []
            files: list[str] = []
            for supplied in sorted(
                require_list(row.get("paths"), f"{identifier}.paths")
            ):
                source = repository_path(self.root, supplied)
                if source.is_file():
                    candidates = [source]
                    source_base = source.parent
                else:
                    candidates = files_under(self.root, source, patterns)
                    source_base = source
                for candidate in candidates:
                    relative = candidate.relative_to(source_base).as_posix()
                    archive_path = self.add(
                        candidate, f"data-sources/{prefix}/{relative}"
                    )
                    files.append(archive_path)
            files = sorted(set(files))
            if not files and not row.get("remote_references"):
                raise ValueError(f"{identifier}: data source is empty")
            for index, path in enumerate(files, start=1):
                local_files.append({"id": f"file-{index:04d}", "file": path})
            remote = require_list(
                row.get("remote_references", []), f"{identifier}.remote_references"
            )
            document = {
                "id": identifier,
                "name": require_string(row.get("name"), f"{identifier}.name"),
                "descriptor": require_mapping(
                    row.get("descriptor"), f"{identifier}.descriptor"
                ),
                "local_files": local_files,
                "remote_references": sorted(
                    remote, key=lambda item: (item["id"], item["uri"])
                ),
            }
            self.builder.add_resource("data-sources", document, files=files)

    def workflows(self, skill_ids: set[str]) -> None:
        for row in sorted(self.config["workflows"], key=lambda item: item["id"]):
            row = require_mapping(row, "workflow")
            identifier = require_id(row.get("id"), "workflow.id")
            source_root = repository_path(self.root, row["root"], file=False)
            entry = PurePosixPath(
                require_string(row.get("entrypoint"), f"{identifier}.entrypoint")
            )
            reasoning = PurePosixPath(
                require_string(
                    row.get("reasoning_entrypoint"),
                    f"{identifier}.reasoning_entrypoint",
                )
            )
            for label, relative in (
                ("entrypoint", entry),
                ("reasoning entrypoint", reasoning),
            ):
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not (source_root / relative).is_file()
                ):
                    raise ValueError(
                        f"{identifier}: invalid or missing {label}: {relative}"
                    )
            references = sorted(
                set(require_list(row.get("skill_ids", []), f"{identifier}.skill_ids"))
            )
            missing = sorted(set(references) - skill_ids)
            if missing:
                raise ValueError(
                    f"{identifier}: references unexported skills: {missing}"
                )
            archive_root = f"repository/projects/{identifier}"
            files = self.add_tree(
                source_root,
                archive_root,
                require_list(row.get("exclude", []), f"{identifier}.exclude"),
            )
            metadata = {
                **require_mapping(row.get("metadata", {}), f"{identifier}.metadata"),
                "description": require_string(
                    row.get("description"), f"{identifier}.description"
                ),
                "entrypoint": f"{archive_root}/{entry.as_posix()}",
                "reasoning_entrypoint": f"{archive_root}/{reasoning.as_posix()}",
                "public_output_type": require_string(
                    row.get("public_output_type"), f"{identifier}.public_output_type"
                ),
                "semantic_mode": require_string(
                    row.get("semantic_mode"), f"{identifier}.semantic_mode"
                ),
            }
            self.builder.add_resource(
                "repository",
                {
                    "id": identifier,
                    "name": require_string(
                        row.get("name", identifier), f"{identifier}.name"
                    ),
                    "kind": "project",
                    "metadata": metadata,
                },
                files=files,
                references=[
                    {"collection": "skills", "id": item} for item in references
                ],
            )

    def runtime(self) -> None:
        runtime = require_mapping(self.config.get("runtime", {}), "runtime")
        entries: list[dict[str, str]] = []
        files: list[str] = []
        targets: dict[str, tuple[Path, str]] = {}
        for row in sorted(runtime.get("entrypoints", []), key=lambda item: item["id"]):
            source = repository_path(self.root, row["source"], file=True)
            target = PurePosixPath(require_string(row["target"], "runtime target"))
            if target.is_absolute() or ".." in target.parts:
                raise ValueError(f"invalid runtime target: {target}")
            target_name = target.as_posix()
            if target_name in targets:
                previous, archive_path = targets[target_name]
                if previous != source:
                    raise ValueError(
                        f"runtime target {target_name!r} is supplied by multiple source files"
                    )
            else:
                archive_path = self.add(source, f"repository/runtime/{target_name}")
                targets[target_name] = (source, archive_path)
                files.append(archive_path)
            if source.suffix == ".py":
                compile(converted_bytes(source)[0], str(source), "exec")
            entries.append(
                {
                    "id": require_id(row["id"], "runtime entrypoint.id"),
                    "operation": row["operation"],
                    "file": archive_path,
                    "callable": row["callable"],
                }
            )
        self.builder.manifest["runtime"].update(
            {
                "python": self.config.get("python", ">=3.12,<3.15"),
                "requirements_lock": runtime.get("requirements_lock"),
                "planning_hooks": sorted(
                    runtime.get("planning_hooks", []),
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
                "entrypoints": entries,
            }
        )
        if files:
            self.builder.add_resource(
                "repository",
                {
                    "id": "repository-prism-runtime",
                    "name": "Repository PRISM runtime",
                    "kind": "runtime",
                    "metadata": {"entrypoint_count": len(entries)},
                },
                files=files,
            )

    def lock(self) -> None:
        lock = {
            "schema_version": 1,
            "tool": TOOL_VERSION,
            "package_key": self.config["package"]["key"],
            "configuration_path": self.config_path.relative_to(self.root).as_posix(),
            "configuration_sha256": digest_bytes(canonical_json(self.config)),
            "exclusions": sorted(
                self.config.get("exclusions", []),
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
            "files": sorted(self.lock_rows, key=lambda item: item["archive_path"]),
        }
        path = self.builder.add_bytes(
            "repository/conversion-lock.json",
            canonical_json(lock),
            media_type="application/json",
        )
        self.builder.add_resource(
            "repository",
            {
                "id": "repository-prism-conversion-lock",
                "name": "Repository PRISM deterministic conversion lock",
                "kind": "asset",
                "metadata": {
                    "schema_version": 1,
                    "tool": TOOL_VERSION,
                    "source_file_count": len(self.lock_rows),
                },
            },
            files=[path],
        )


def build(
    root: Path, config_path: Path, output: Path, lunar_root: Path
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = config_path if config_path.is_absolute() else root / config_path
    config_path = config_path.resolve(strict=True)
    config_path.relative_to(root)
    config = read_config(config_path)
    ArchiveBuilder, validate_archive = lunar_modules(lunar_root)
    with tempfile.TemporaryDirectory(prefix="repository-prism-export-") as temporary:
        builder = ArchiveBuilder(
            Path(temporary) / "snapshot",
            package_key=config["package"]["key"],
            display_name=config["package"]["display_name"],
        )
        export = Export(builder, root, config_path, config)
        skill_ids = export.skills()
        export.data_sources()
        export.workflows(skill_ids)
        export.runtime()
        export.lock()
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = builder.publish(output)
        validated = validate_archive(output, Path(temporary) / "validated")
        if validated.manifest != manifest:
            raise ValueError("Lunar archive validation changed the generated manifest")
    return {
        "archive": str(output.resolve()),
        "archive_sha256": digest_file(output),
        "file_count": len(manifest["files"]),
        "format_version": manifest["format_version"],
        "package": manifest["package"],
        "skill_count": len(config["skills"]),
        "data_source_count": len(config["data_sources"]),
        "workflow_count": len(config["workflows"]),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="source repository root"
    )
    parser.add_argument(
        "--config", type=Path, required=True, help="repository-relative export JSON"
    )
    parser.add_argument(
        "--lunar-root", type=Path, required=True, help="Lunar checkout root"
    )
    parser.add_argument("--output", type=Path, required=True, help="destination ZIP")
    parser.add_argument(
        "--verify-reproducible",
        action="store_true",
        help="build independently twice and require byte-identical archives",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build(args.root, args.config, args.output, args.lunar_root)
    if args.verify_reproducible:
        with tempfile.TemporaryDirectory(prefix="repository-prism-repro-") as temporary:
            comparison = Path(temporary) / args.output.name
            second = build(args.root, args.config, comparison, args.lunar_root)
            if report["archive_sha256"] != second["archive_sha256"]:
                raise ValueError("independent exports were not byte-identical")
        report["reproducible"] = True
    print(canonical_json(report).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
