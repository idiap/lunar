# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Deterministic projections of PRISM syntax; never execute package code.

The portable archive contains source, not a second graph. Optional
``# lunar-runtime: {"declaration": "name", ...}`` comments bind a source
workflow to host worker hooks without describing its topology.
"""

from dataclasses import fields, is_dataclass, asdict
import hashlib
from pathlib import PurePosixPath
from typing import Any

from prism.language import parse_source
from prism.language.developer import parse_type
from prism.language.developer.syntax import ast

from .contract import PackageValidationError


def identity(repository, path, name):
    return (
        "source:"
        + hashlib.sha256((repository + "\0" + path + "\0" + name).encode()).hexdigest()[
            :24
        ]
        + ":"
        + name[:100]
    )


def _type(value):
    if value is None:
        return ""
    if hasattr(value, "text"):
        return value.text
    return value.name + (
        "[" + ", ".join(_type(arg) for arg in value.arguments) + "]"
        if value.arguments
        else ""
    )


def _name(value):
    if isinstance(value, ast.NameExpr):
        return value.name
    if isinstance(value, ast.FieldExpr):
        return _name(value.value) + "." + value.field
    if isinstance(value, ast.CallExpr):
        return _name(value.callee)
    return ""


def _references(value):
    if isinstance(value, ast.NameExpr):
        yield value.name
    elif isinstance(value, ast.LambdaExpr):
        yield from (name for name in _references(value.body) if name != value.parameter)
    elif is_dataclass(value):
        for field in fields(value):
            if field.name not in {"span", "type_arguments"}:
                yield from _references(getattr(value, field.name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _references(item)


def _annotations(text):
    result = {}
    for line in text.splitlines():
        if line.startswith("# lunar-runtime:"):
            try:
                from .contract import _json

                value = _json(line.partition(":")[2].encode())
                name = value.pop("declaration")
                if not isinstance(name, str) or name in result:
                    raise ValueError("duplicate declaration")
                result[name] = value
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise PackageValidationError(
                    "Invalid lunar-runtime source annotation"
                ) from exc
    return result


class SourceProject:
    def __init__(self, sources):
        self.sources = sources
        self.programs = {}
        for path, text in sorted(sources.items()):
            try:
                self.programs[path] = parse_source(text, path=path)
            except Exception as exc:
                raise PackageValidationError(
                    f"Invalid PRISM source {path}: {exc}"
                ) from exc

    def module_path(self, path, module):
        for parent in PurePosixPath(path).parents:
            candidate = str(parent / (module.replace(".", "/") + ".prism"))
            if candidate in self.programs:
                return candidate
        return None

    def source_closure(self, path):
        seen, pending = set(), [path]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            for declaration in self.programs[current].declarations:
                if isinstance(declaration, (ast.ImportDecl, ast.ModuleImportDecl)):
                    target = self.module_path(current, declaration.module)
                    if target:
                        pending.append(target)
        return [path, *sorted(seen - {path})]

    def resolve(self, path, name, seen=()):
        key = (path, name)
        if key in seen:
            return None
        declarations = self.programs[path].declarations
        local = next(
            (d for d in declarations if getattr(d, "name", None) == name), None
        )
        if local is not None:
            return local
        head, _, tail = name.partition(".")
        for declaration in declarations:
            module = target = None
            if isinstance(declaration, ast.ImportDecl):
                for original, alias in declaration.names:
                    if (alias or original) == name:
                        module, target = declaration.module, original
            elif (
                isinstance(declaration, ast.ModuleImportDecl)
                and declaration.alias == head
                and tail
            ):
                module, target = declaration.module, tail
            if module:
                # Resolve within the owning source tree, never the host filesystem.
                candidate = self.module_path(path, module)
                if candidate:
                    return self.resolve(candidate, target, (*seen, key))
        return None

    def contract(self, path, component):
        declaration = self.resolve(path, _name(component))
        if isinstance(
            declaration,
            (ast.FunctionDecl, ast.WorkflowDecl, ast.ReasoningDecl, ast.AgentDecl),
        ):
            return (
                ", ".join(p.type.text for p in declaration.parameters),
                declaration.result.text,
            )
        annotation = (
            getattr(declaration, "alias", None)
            or getattr(declaration, "annotation", None)
            or getattr(declaration, "type", None)
        )
        if annotation:
            value = parse_type(annotation.text)
            if value.name == "Function":
                return ", ".join(_type(t) for _, t in value.parameters), _type(
                    value.result
                )
            if value.name == "Occurrence" and len(value.arguments) >= 2:
                return _type(value.arguments[0]), _type(value.arguments[1])
        return "", ""

    def graph(self, path, declaration):
        nodes, edges, aliases, failures = [], [], set(), []

        def add(node_id, kind, label, span=None, **values):
            if node_id in aliases:
                node_id += f"@{span.line}:{span.column}" if span else "@boundary"
            if node_id in aliases:
                raise PackageValidationError(
                    f"Duplicate PRISM node {node_id} in {path}"
                )
            aliases.add(node_id)
            node: dict[str, Any] = dict(
                id=node_id,
                kind=kind,
                label=label,
                method=label,
                input_type="",
                output_type="",
                relation="",
                certificate="",
                skills=[],
            )
            node.update(values)
            if span:
                node["source_span"] = asdict(span)
                lines = self.sources[path].splitlines()
                node["source_code"] = "\n".join(lines[span.line - 1 : span.end_line])
                comments = []
                for line in reversed(lines[: span.line - 1]):
                    if not line.strip().startswith("#"):
                        break
                    comments.append(line.strip()[1:].strip())
                node["commentary"] = "\n".join(reversed(comments))
            nodes.append(node)
            return node_id

        def edge(source, target, kind="control", label=""):
            item = dict(source=source, target=target, kind=kind, label=label)
            if item not in edges:
                edges.append(item)

        environment = {}
        for parameter in declaration.parameters:
            environment[parameter.name] = [
                add(
                    parameter.name,
                    "input",
                    parameter.name,
                    parameter.span,
                    output_type=parameter.type.text,
                )
            ]

        def sequence(children, incoming, env, label="sequence"):
            current = incoming
            for index, child in enumerate(children):
                current, env = visit(
                    child, current, env, label if index == 0 else "sequence"
                )
            return current, env

        def visit(composition, incoming, env, label="sequence"):
            env = dict(env)
            kind = type(composition).__name__.removesuffix("Composition")
            if isinstance(composition, ast.NodeOccurrence):
                method = _name(composition.component)
                alias = (
                    composition.alias
                    or method.rsplit(".", 1)[-1]
                    or f"occurrence_{composition.span.line}"
                )
                input_type, output_type = self.contract(path, composition.component)
                failure_type = ""
                if isinstance(declaration, ast.WorkflowDecl) and output_type:
                    result_type = parse_type(output_type)
                    # Executable occurrences propagate the outer Result failure.
                    if result_type.name == "Result" and len(result_type.arguments) == 2:
                        output_type, failure_type = map(_type, result_type.arguments)
                node_id = add(
                    alias,
                    "occurrence",
                    method or alias,
                    composition.span,
                    alias=alias,
                    input_type=input_type,
                    output_type=output_type,
                    failure_type=failure_type,
                    relation=composition.relation or "",
                    constraints=[asdict(c) for c in composition.constraints],
                )
                for parent in incoming:
                    edge(parent, node_id, label=label)
                references = (
                    set(_references(composition.component))
                    if isinstance(composition.component, ast.CallExpr)
                    else set()
                )
                if not isinstance(composition.component, ast.CallExpr):
                    target = self.resolve(path, method)
                    references.update(p.name for p in getattr(target, "parameters", ()))
                    annotation = getattr(target, "alias", None) or getattr(
                        target, "annotation", None
                    )
                    if annotation:
                        references.update(
                            name
                            for name, _ in parse_type(annotation.text).parameters
                            if name
                        )
                for reference in sorted(references & env.keys()):
                    for source in env[reference]:
                        existing = next(
                            (
                                e
                                for e in edges
                                if e["source"] == source
                                and e["target"] == node_id
                                and e["kind"] == "control"
                                and e["label"] == "sequence"
                            ),
                            None,
                        )
                        if existing:
                            existing.update(kind="data", label="")
                        else:
                            edge(source, node_id, "data")
                env[alias] = [node_id]
                if failure_type and failure_type != "Never":
                    failures.append((node_id, failure_type))
                return [node_id], env
            if isinstance(composition, ast.SequenceComposition):
                if composition.relation:
                    group = add(
                        f"__sequence_{composition.span.line}_{composition.span.column}",
                        "topology",
                        "Sequence",
                        composition.span,
                        relation=composition.relation,
                    )
                    for parent in incoming:
                        edge(parent, group, label=label)
                    incoming = [group]
                return sequence(
                    composition.children, incoming, env, composition.relation or label
                )
            node_id = (
                f"__{kind.lower()}_{composition.span.line}_{composition.span.column}"
            )
            if isinstance(composition, ast.ChoiceComposition):
                routed, routed_env = visit(composition.router, incoming, env, label)
                ends, branches = [], []
                for arm in composition.arms:
                    branch_ends, branch = sequence(
                        arm.children, routed, routed_env, "case " + arm.pattern
                    )
                    ends.extend(branch_ends)
                    branches.append(branch)
                # Only aliases present in every branch are available after choice.
                merged = {
                    name: list(
                        dict.fromkeys(
                            node for branch in branches for node in branch[name]
                        )
                    )
                    for name in sorted(set.intersection(*(set(b) for b in branches)))
                }
                return ends, merged
            node_id = add(
                node_id,
                "topology",
                kind,
                composition.span,
                relation=composition.relation or "",
            )
            for parent in incoming:
                edge(parent, node_id, label=label)
            if isinstance(composition, ast.ParallelComposition):
                fork = nodes[-1]
                fork.update(topology_kind="parallel", topology_role="fork")
                member_start = len(nodes)
                ends, merged = [], dict(env)
                for child in composition.children:
                    branch_ends, branch = visit(child, [node_id], env, "parallel")
                    ends.extend(branch_ends)
                    for name, values in branch.items():
                        if name not in env or values != env[name]:
                            merged[name] = values
                fork["members"] = [node["id"] for node in nodes[member_start:]]
                join = add(
                    node_id + "_join",
                    "topology",
                    "Parallel join",
                    composition.span,
                    topology_kind="parallel",
                    topology_role="join",
                    parallel_id=node_id,
                )
                fork["join_id"] = join
                for end in ends:
                    edge(end, join, label="join")
                return [join], merged
            if isinstance(composition, ast.RepeatComposition):
                nodes[-1]["policy"] = asdict(composition.policy)
                nodes[-1]["until"] = (
                    asdict(composition.until) if composition.until else None
                )
                ends, repeated_env = sequence(composition.children, [node_id], env)
                completed = add(
                    node_id + "_complete",
                    "topology",
                    "Repeat complete",
                    composition.span,
                )
                for end in ends:
                    edge(end, node_id, "repeat", "repeat per policy")
                    edge(
                        end,
                        completed,
                        label=(
                            "until / policy complete"
                            if composition.until
                            else "policy complete"
                        ),
                    )
                return [completed], repeated_env
            raise PackageValidationError(f"Unsupported PRISM composition: {kind}")

        ends, environment = visit(declaration.composition, [], environment)
        result = add(
            "__result__",
            "result",
            declaration.result.text,
            output_type=declaration.result.text,
        )
        if declaration.result_alias and declaration.result_alias not in environment:
            raise PackageValidationError(
                f"Unknown PRISM return alias {declaration.result_alias} in {path}"
            )
        returned = (
            environment[declaration.result_alias] if declaration.result_alias else ends
        )
        for end in returned:
            edge(end, result, "return", declaration.result.text)
        for end in ends:
            if end not in returned:
                edge(end, result, label="complete")
        for index, exit_ in enumerate(getattr(declaration, "exits", ())):
            if exit_.occurrence not in environment:
                raise PackageValidationError(
                    f"Unknown guarded exit occurrence in {path}"
                )
            target = (
                result
                if exit_.action == "accept"
                else add(
                    f"__exit_{index}",
                    "exit",
                    exit_.action + (" @" + exit_.target if exit_.target else ""),
                    exit_.span,
                )
            )
            for origin in environment[exit_.occurrence]:
                edge(origin, target, "guard", exit_.selector + " → " + exit_.action)
        failure = getattr(declaration, "failure", None)
        if failure and failure.text != "Never":
            target = add(
                "__failure__",
                "exit",
                "fails " + failure.text,
                declaration.span,
                output_type=failure.text,
            )
            for origin, failure_type in failures:
                edge(origin, target, "failure", failure_type)
        scope = (
            "reasoning"
            if isinstance(declaration, ast.ReasoningDecl)
            else "executable-workflow"
        )
        return dict(
            schema_version=1,
            scope=scope,
            reasoning=declaration.name,
            source=path,
            topology=type(declaration.composition).__name__.removesuffix("Composition"),
            composition=asdict(declaration.composition),
            input=[dict(name=p.name, type=p.type.text) for p in declaration.parameters],
            output=declaration.result.text,
            failure=failure.text if failure else None,
            effects=list(getattr(declaration, "effects", ())),
            nodes=nodes,
            edges=edges,
        )


def derive(manifest, payloads, repositories=None):
    """Return the viewer and executable registrations from linked source bytes."""
    projects, registrations = [], []
    names = {r["id"]: r.get("name", r["id"]) for r in repositories or []}
    resources = sorted(manifest["collections"]["repository"], key=lambda r: r["id"])
    sources = {}
    for path in sorted(
        {p for r in resources for p in r["files"] if p.endswith(".prism")}
    ):
        try:
            sources[path] = payloads[path].decode("utf-8")
        except UnicodeError as exc:
            raise PackageValidationError(f"Invalid UTF-8 PRISM source {path}") from exc
    project = SourceProject(sources)
    for resource in resources:
        views = []
        for path in sorted(p for p in resource["files"] if p.endswith(".prism")):
            program = project.programs[path]
            annotations = _annotations(sources[path])
            declarations = [
                d
                for d in program.declarations
                if isinstance(d, (ast.ReasoningDecl, ast.WorkflowDecl))
            ]
            if set(annotations) - {
                d.name for d in declarations if isinstance(d, ast.WorkflowDecl)
            }:
                raise PackageValidationError(
                    f"Runtime annotation must name an executable workflow in {path}"
                )
            for declaration in declarations:
                options = annotations.get(declaration.name)
                workflow_id = identity(resource["id"], path, declaration.name)
                if options is not None:
                    options = dict(options)
                    entrypoint = next(
                        (
                            d
                            for d in program.declarations
                            if isinstance(d, ast.FunctionDecl) and d.name == "main"
                        ),
                        None,
                    )
                    if entrypoint is None:
                        raise PackageValidationError(
                            f"Executable PRISM source {path} has no main function"
                        )
                    # Optional stable public identity belongs to this declaration.
                    workflow_id = options.pop("id", workflow_id)
                    if not isinstance(workflow_id, str) or not workflow_id:
                        raise PackageValidationError("Invalid source workflow identity")
                    registration = dict(
                        id=workflow_id,
                        repository_id=resource["id"],
                        name=declaration.name,
                        entry_file=path,
                        entry_argument=(
                            declaration.parameters[0].name
                            if declaration.parameters
                            else ""
                        ),
                        input_schema={},
                        output_schema={},
                        verify_hook=None,
                        metadata={},
                    )
                    forbidden = {"repository_id", "entry_file", "name"} & options.keys()
                    if forbidden:
                        raise PackageValidationError(
                            "Runtime annotation cannot override source identity"
                        )
                    registration.update(options)
                    if not registration["entry_argument"] or registration[
                        "entry_argument"
                    ] not in {parameter.name for parameter in entrypoint.parameters}:
                        raise PackageValidationError(
                            f"Registered entry argument is not accepted by main in {path}"
                        )
                    registrations.append(registration)
                if not isinstance(declaration, ast.ReasoningDecl):
                    continue
                graph = project.graph(path, declaration)
                views.append(
                    dict(
                        id=workflow_id,
                        label=declaration.name,
                        source=path,
                        source_text=sources[path],
                        scope=graph["scope"],
                        summary="",
                        graph=graph,
                        sources=[
                            dict(
                                path=p,
                                file_type="reasoning" if p == path else "module",
                                content=sources[p],
                            )
                            for p in project.source_closure(path)
                        ],
                    )
                )
        resource_registrations = [
            row for row in registrations if row["repository_id"] == resource["id"]
        ]
        if len(views) == 1:
            for registration in resource_registrations:
                registration["metadata"] = {
                    **registration.get("metadata", {}),
                    "viewer_workflow_id": views[0]["id"],
                }
        elif views:
            view_ids = {view["id"] for view in views}
            for registration in resource_registrations:
                viewer_id = registration.get("metadata", {}).get("viewer_workflow_id")
                if viewer_id is not None and viewer_id not in view_ids:
                    raise PackageValidationError(
                        "Runtime annotation references an unknown reasoning workflow"
                    )
        views_by_id = {view["id"]: view for view in views}
        for registration in resource_registrations:
            metadata = registration.setdefault("metadata", {})
            view = views_by_id.get(metadata.get("viewer_workflow_id"))
            if view is None:
                continue
            # This is a host-derived execution invariant, not package-authored
            # topology. The worker may emit additional nested/model events, but
            # every declared occurrence below must be durably completed.
            metadata["reasoning_contract"] = {
                "workflow": view["graph"]["reasoning"],
                "steps": [
                    node["id"]
                    for node in view["graph"]["nodes"]
                    if node["kind"] == "occurrence"
                ],
            }
        if views:
            projects.append(
                dict(
                    id=resource["id"],
                    label=names.get(resource["id"], resource["id"]),
                    workflows=views,
                )
            )
    ids = [v["id"] for p in projects for v in p["workflows"]]
    if len(ids) != len(set(ids)):
        raise PackageValidationError("Duplicate source workflow identity")
    return (
        dict(kind="prism-viewer-bundle", schema_version=1, projects=projects),
        registrations,
    )
