# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Runtime projections and migration for source-derived workflow packages."""

import hashlib
import json
from prism.language import parse_source
from prism.language.developer.syntax import ast
from .format.contract import PackageValidationError
from .format.source_workflows import derive, _annotations, identity


def _single_contract(registration):
    """Normalize stored pre-single-contract registrations without exposing modes."""
    registration.pop("modes", None)
    metadata = registration.setdefault("metadata", {})
    metadata.pop("mode_input_schemas", None)
    metadata.pop("planner_mode_bindings", None)
    metadata.pop("unavailable_modes", None)
    return registration


def runtime_manifest(manifest, root):
    """Build a private worker projection; never serialize this as an archive."""
    from copy import deepcopy
    from .archive_builder import SnapshotPayloads

    projected = deepcopy(manifest)
    if "workflows" in manifest["runtime"]:  # Existing stored versions remain runnable.
        for registration in projected["runtime"]["workflows"]:
            _single_contract(registration)
            path = registration["entry_file"]
            source = root / path
            if source.is_file():
                declarations = [
                    d
                    for d in parse_source(source.read_text(), path=path).declarations
                    if isinstance(d, ast.ReasoningDecl)
                ]
                if len(declarations) == 1:
                    registration.setdefault("metadata", {})["viewer_workflow_id"] = (
                        identity(
                            registration["repository_id"], path, declarations[0].name
                        )
                    )
        return projected
    _, registrations = derive(
        manifest, SnapshotPayloads(root, {r["path"]: r for r in manifest["files"]})
    )
    projected["runtime"]["workflows"] = registrations
    for registration in projected["runtime"]["workflows"]:
        _single_contract(registration)
    return projected


def upgrade_snapshot(builder):
    """Export older stored versions as source-only packages in the private snapshot.

    Keep execution settings as annotations on an actual executable declaration.
    Ambiguous bindings require correction instead of guessing at a workflow.
    """
    from .archive_builder import json_bytes

    legacy = builder.manifest["runtime"].pop("workflows", [])

    def replace(path, raw):
        (builder.root / path).write_bytes(raw)
        builder.files[path].update(
            size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )

    for registration in legacy:
        path = registration["entry_file"]
        text = (builder.root / path).read_text()
        declarations = [
            d
            for d in parse_source(text, path=path).declarations
            if isinstance(d, ast.WorkflowDecl)
        ]
        if len(declarations) != 1:
            raise PackageValidationError(
                f"Cannot migrate runtime binding for {path}: expected one executable workflow"
            )
        name = declarations[0].name
        annotation = _annotations(text).get(name)
        if annotation is not None and annotation.get("id") != registration["id"]:
            raise PackageValidationError(
                f"Cannot migrate multiple runtime bindings for {path}:{name}"
            )
        if annotation is None:
            options = {
                k: v
                for k, v in registration.items()
                if k not in {"repository_id", "name", "entry_file", "modes"}
            }
            metadata = options.get("metadata")
            if isinstance(metadata, dict):
                for key in (
                    "mode_input_schemas",
                    "planner_mode_bindings",
                    "unavailable_modes",
                ):
                    metadata.pop(key, None)
            options["declaration"] = name
            replace(
                path,
                (
                    "# lunar-runtime: "
                    + json.dumps(options, sort_keys=True)
                    + "\n"
                    + text
                ).encode(),
            )
    obsolete = set()
    for resource in builder.manifest["collections"]["repository"]:
        path = resource["document"]
        doc = json.loads((builder.root / path).read_bytes())
        bundle = doc["metadata"].pop("bundle", None)
        if bundle:
            obsolete.add(bundle)
            replace(path, json_bytes(doc))
    for resources in builder.manifest["collections"].values():
        for resource in resources:
            resource["files"] = [p for p in resource["files"] if p not in obsolete]
    for path in obsolete:
        builder.files.pop(path, None)
        (builder.root / path).unlink(missing_ok=True)
