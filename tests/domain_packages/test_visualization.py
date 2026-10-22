# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Source-only package round trips and faithful deterministic PRISM projections."""

import copy
import hashlib
import json
import zipfile

import pytest

from domain_packages.archive import validate_archive
from domain_packages.archive_builder import ArchiveBuilder
from domain_packages.format.contract import (
    PackageValidationError,
    validate_payloads,
    validate_document,
)
from domain_packages.format.source_workflows import derive, SourceProject
from domain_packages.source_workflows import runtime_manifest, upgrade_snapshot
from scripts.validate_imported_prism_packages import validate_package

SOURCE = """type Request:
    value: Int
type Draft = (request: Request) -> Generated[Candidate]
type Execute = (candidate: Generated[Candidate]) -> Receipt
reasoning NativeBackendExecution(request: Request) -> Receipt:
    sequence:
        [candidate: Draft(request)]
        [receipt: Execute(candidate)]
    return receipt
workflow materialize(request: Request) -> Receipt:
    sequence:
        [candidate: Draft(request)]
        [receipt: Execute(candidate)]
    return receipt
def main(request: Request) -> Receipt:
    return solve materialize(request)
"""


def fixture(tmp_path, source=SOURCE, extras=None, execution=None):
    builder = ArchiveBuilder(
        tmp_path / "snapshot", package_key="backend", display_name="Backend"
    )
    paths = []
    if execution:
        source = "# lunar-runtime: " + json.dumps(execution) + "\n" + source
        hook = builder.add_bytes(
            "repository/prepare.py",
            b'raise AssertionError("do not execute package code")',
        )
        builder.manifest["runtime"]["entrypoints"] = [
            dict(id="prepare", operation="prepare", file=hook, callable="prepare")
        ]
        paths.append(hook)
    paths.append(builder.add_bytes("repository/main.prism", source.encode()))
    for path, text in (extras or {}).items():
        paths.append(builder.add_bytes(path, text.encode()))
    builder.add_resource(
        "repository",
        dict(id="backend", name="Backend", kind="project", metadata={}),
        files=paths,
    )
    builder.manifest["files"] = list(builder.files.values())
    payloads = {path: (builder.root / path).read_bytes() for path in builder.files}
    return builder, payloads


def views(builder, payloads):
    return derive(builder.manifest, payloads)[0]["projects"][0]["workflows"]


def test_source_is_the_only_graph_authority_and_types_are_resolved(tmp_path):
    builder, payloads = fixture(tmp_path)
    first = derive(builder.manifest, payloads)
    validate_document(first[0], "viewer")
    assert first == derive(builder.manifest, dict(reversed(list(payloads.items()))))
    (reasoning,) = views(builder, payloads)
    assert reasoning["scope"] == "reasoning"
    graph = reasoning["graph"]
    assert [(n["id"], n["output_type"]) for n in graph["nodes"]] == [
        ("request", "Request"),
        ("candidate", "Generated[Candidate]"),
        ("receipt", "Receipt"),
        ("__result__", "Receipt"),
    ]
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("request", "candidate"),
        ("candidate", "receipt"),
        ("receipt", "__result__"),
    }
    assert all(
        n.get("source_span") for n in graph["nodes"] if n["kind"] == "occurrence"
    )
    changed = {
        **payloads,
        "repository/main.prism": SOURCE.replace(
            "Execute(candidate)", "Execute(request)"
        ).encode(),
    }
    updated = views(builder, changed)[0]
    assert updated["id"] == reasoning["id"]
    assert updated["graph"] != graph
    assert ("request", "receipt", "data") in {
        (e["source"], e["target"], e["kind"]) for e in updated["graph"]["edges"]
    }


def test_import_requires_material_execution_for_every_reasoning_view(tmp_path):
    builder, payloads = fixture(tmp_path)
    with pytest.raises(PackageValidationError, match="Every PRISM reasoning workflow"):
        validate_payloads(builder.manifest, payloads)


def test_reasoning_adapter_cannot_replace_packaged_material_main(tmp_path):
    builder, payloads = fixture(
        tmp_path,
        extras={
            "repository/material_main.prism": "def main(request: Int) -> Int:\n    return request\n"
        },
        execution={
            "declaration": "materialize",
            "id": "backend-run",
            "prepare_hook": "prepare",
        },
    )
    with pytest.raises(PackageValidationError, match="materialized implementation"):
        validate_payloads(builder.manifest, payloads)
    (builder.root / "manifest.json").write_text(json.dumps(builder.manifest))
    errors = validate_package(builder.root)
    assert any("materialized implementation" in error for error in errors)


def test_imports_nested_topology_guards_and_unused_occurrences_are_preserved(tmp_path):
    source = """import methods as m
reasoning ReviewLoop(request: Int) -> Int:
    sequence:
        [start: m.Step(request)] by Ground
        parallel:
            [left: m.Step(start)]
            [right: m.Step(start)]
        choice [route: m.Step(left)]:
            case Yes:
                [accepted: m.Step(right)]
            case No:
                repeat bounded(3, until = done):
                    [repair: m.Step(right)]
        [last: m.Step(start)]
    on last.done => accept
    on last.failed => stop
    on last.retry => switch @Other
    return last
"""
    builder, payloads = fixture(
        tmp_path,
        source,
        {"repository/methods.prism": "type Step = (value: Int) -> Int\n"},
    )
    validate_document(derive(builder.manifest, payloads)[0], "viewer")
    graph = views(builder, payloads)[0]["graph"]
    assert [n["id"] for n in graph["nodes"] if n["kind"] == "occurrence"] == [
        "start",
        "left",
        "right",
        "route",
        "accepted",
        "repair",
        "last",
    ]
    assert all(
        n["output_type"] == "Int" for n in graph["nodes"] if n["kind"] == "occurrence"
    )
    assert next(n for n in graph["nodes"] if n["id"] == "start")["relation"] == "Ground"
    assert sum(e["kind"] == "repeat" for e in graph["edges"]) == 1
    assert {e["label"] for e in graph["edges"] if e["kind"] == "guard"} == {
        "done → accept",
        "failed → stop",
        "retry → switch",
    }
    assert {"case Yes", "case No"} <= {e["label"] for e in graph["edges"]}
    assert len([n for n in graph["nodes"] if n["label"] == "Parallel"]) == 1
    fork = next(n for n in graph["nodes"] if n.get("topology_role") == "fork")
    assert fork["members"] == ["left", "right"]
    join = next(n for n in graph["nodes"] if n["id"] == fork["join_id"])
    assert join["topology_role"] == "join" and join["parallel_id"] == fork["id"]
    assert (
        graph["composition"]["children"][2]["arms"][1]["children"][0]["until"]["name"]
        == "done"
    )
    # A name containing Loop never creates an unauthored loop.
    simple, simple_payloads = fixture(
        tmp_path / "simple", SOURCE.replace("NativeBackendExecution", "FeedbackLoop")
    )
    assert not any(
        e["kind"] == "repeat"
        for e in views(simple, simple_payloads)[0]["graph"]["edges"]
    )


def test_roundtrip_has_no_workflows_section_or_graph_payload(tmp_path):
    builder, payloads = fixture(
        tmp_path,
        execution={
            "declaration": "materialize",
            "id": "backend-run",
            "prepare_hook": "prepare",
        },
    )
    original = derive(builder.manifest, payloads)
    builder.publish(tmp_path / "package.zip")
    imported = validate_archive(tmp_path / "package.zip", tmp_path / "imported")
    assert "workflows" not in imported.manifest["runtime"]
    assert imported.documents["repository"][0]["metadata"] == {}
    assert not any("viewer" in path for path in builder.files)
    runtime = runtime_manifest(imported.manifest, imported.root)
    assert runtime["runtime"]["workflows"][0]["id"] == "backend-run"
    assert "workflows" not in imported.manifest["runtime"]
    exported = ArchiveBuilder(
        tmp_path / "export", package_key="backend", display_name="Backend"
    )
    exported.manifest = copy.deepcopy(imported.manifest)
    for entry in imported.manifest["files"]:
        exported.add_bytes(
            entry["path"],
            (imported.root / entry["path"]).read_bytes(),
            media_type=entry["media_type"],
        )
    upgrade_snapshot(exported)
    exported.publish(tmp_path / "export.zip")
    with zipfile.ZipFile(tmp_path / "export.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert (
            derive(
                manifest,
                {p["path"]: archive.read(p["path"]) for p in manifest["files"]},
            )
            == original
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "workflows",
        "bundle",
        "invalid-source",
        "invalid-annotation",
        "reasoning-execution",
    ],
)
def test_stale_graphs_and_invalid_source_bindings_are_rejected(tmp_path, mutation):
    builder, payloads = fixture(tmp_path)
    if mutation == "workflows":
        builder.manifest["runtime"]["workflows"] = []
    elif mutation == "bundle":
        path = builder.manifest["collections"]["repository"][0]["document"]
        doc = json.loads(payloads[path])
        doc["metadata"]["bundle"] = "repository/viewer.json"
        payloads[path] = json.dumps(doc).encode()
    else:
        payloads["repository/main.prism"] = {
            "invalid-source": b"reasoning broken\n",
            "invalid-annotation": b"# lunar-runtime: not-json\n" + SOURCE.encode(),
            "reasoning-execution": b'# lunar-runtime: {"declaration":"NativeBackendExecution","prepare_hook":"prepare"}\n'
            + SOURCE.encode(),
        }[mutation]
    for entry in builder.manifest["files"]:
        raw = payloads[entry["path"]]
        entry.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(PackageValidationError):
        validate_payloads(builder.manifest, payloads)


def test_export_upgrades_legacy_stored_registration_without_modifying_original(
    tmp_path,
):
    builder, payloads = fixture(tmp_path)
    builder.manifest["runtime"]["workflows"] = [
        dict(
            id="old-id",
            repository_id="backend",
            name="Backend",
            entry_file="repository/main.prism",
            entry_argument="request",
            prepare_hook="prepare",
            verify_hook=None,
            metadata={},
            input_schema={},
            output_schema={},
        )
    ]
    upgrade_snapshot(builder)
    assert "workflows" not in builder.manifest["runtime"]
    assert payloads["repository/main.prism"] == SOURCE.encode()
    _, registrations = derive(
        builder.manifest, {p: (builder.root / p).read_bytes() for p in builder.files}
    )
    assert registrations[0]["id"] == "old-id"


def test_imported_signature_can_be_linked_by_another_repository_resource(tmp_path):
    builder, payloads = fixture(
        tmp_path,
        "from methods import Step\nreasoning example(x: Int) -> Int:\n    [result: Step(x)]\n    return result\n",
    )
    support = builder.add_bytes(
        "repository/methods.prism", b"type Step = (value: Int) -> Int\n"
    )
    builder.add_resource(
        "repository",
        dict(id="shared", name="Shared", kind="asset", metadata={}),
        files=[support],
    )
    payloads.update({p: (builder.root / p).read_bytes() for p in builder.files})
    graph = views(builder, payloads)[0]["graph"]
    assert (
        next(n for n in graph["nodes"] if n["id"] == "result")["output_type"] == "Int"
    )
    assert [s["path"] for s in views(builder, payloads)[0]["sources"]] == [
        "repository/main.prism",
        support,
    ]


def test_branch_local_aliases_join_without_cross_branch_dependencies(tmp_path):
    source = """type Step = (x: Int) -> Int
reasoning Branches(x: Int) -> Int:
    sequence:
        choice [route: Step(x)]:
            case Yes:
                [value: Step(x)]
            case No:
                [value: Step(x)]
        [final: Step(value)]
    return final
"""
    builder, payloads = fixture(tmp_path, source)
    graph = views(builder, payloads)[0]["graph"]
    branch_ids = [n["id"] for n in graph["nodes"] if n.get("alias") == "value"]
    assert len(set(branch_ids)) == 2
    data = {(e["source"], e["target"]) for e in graph["edges"] if e["kind"] == "data"}
    assert all((branch, "final") in data for branch in branch_ids)
    assert not any(a in branch_ids and b in branch_ids for a, b in data)


def test_repeat_rebinding_and_implicit_arguments_keep_their_producers(tmp_path):
    source = """type Step = (x: Int) -> Int
reasoning Loop(request: Int) -> Int:
    sequence:
        [value: Step(request)]
        repeat bounded(3):
            [value: Step(value)]
        [last: Step(value)]
    return last
"""
    builder, payloads = fixture(tmp_path, source)
    graph = views(builder, payloads)[0]["graph"]
    loop_value = next(
        n["id"]
        for n in graph["nodes"]
        if n.get("alias") == "value" and n["id"] != "value"
    )
    data = {(e["source"], e["target"]) for e in graph["edges"] if e["kind"] == "data"}
    assert ("value", loop_value) in data
    assert (loop_value, "last") in data
    assert ("value", "last") not in data
    other, values = fixture(
        tmp_path / "implicit",
        "def increment(request: Int) -> Int:\n    return request + 1\nreasoning implicit(request: Int) -> Int:\n    [increment]\n    return increment\n",
    )
    graph = views(other, values)[0]["graph"]
    assert ("request", "increment") in {
        (e["source"], e["target"]) for e in graph["edges"]
    }


def test_executable_results_propagate_failure_and_expose_success_type(tmp_path):
    source = """def action(request: Int) -> Result[String, Error]:
    return Ok("done")
workflow execution(request: Int) -> String fails Error:
    [result: action(request)]
    return result
"""
    builder, payloads = fixture(tmp_path, source)
    assert derive(builder.manifest, payloads)[0]["projects"] == []
    project = SourceProject({"repository/main.prism": source})
    graph = project.graph(
        "repository/main.prism",
        project.programs["repository/main.prism"].declarations[-1],
    )
    node = next(n for n in graph["nodes"] if n["id"] == "result")
    assert (node["output_type"], node["failure_type"]) == ("String", "Error")
    assert graph["failure"] == "Error"
    assert ("result", "__failure__", "failure") in {
        (e["source"], e["target"], e["kind"]) for e in graph["edges"]
    }


def test_every_reasoning_block_is_exposed_independently_of_executable_registrations(
    tmp_path,
):
    second = SOURCE[SOURCE.index("reasoning ") : SOURCE.index("workflow ")].replace(
        "NativeBackendExecution", "SecondReasoning"
    )
    builder, payloads = fixture(
        tmp_path,
        SOURCE + second,
        extras={
            "repository/helper.prism": SOURCE[: SOURCE.index("workflow ")],
            "repository/executable.prism": SOURCE[: SOURCE.index("reasoning ")]
            + SOURCE[SOURCE.index("workflow ") :],
        },
        execution={
            "declaration": "materialize",
            "id": "run-backend",
            "prepare_hook": "prepare",
        },
    )
    bundle, registrations = derive(builder.manifest, payloads)
    workflows = bundle["projects"][0]["workflows"]
    assert [(w["source"], w["graph"]["reasoning"]) for w in workflows] == [
        ("repository/helper.prism", "NativeBackendExecution"),
        ("repository/main.prism", "NativeBackendExecution"),
        ("repository/main.prism", "SecondReasoning"),
    ]
    assert len({w["id"] for w in workflows}) == 3
    assert all(
        w["scope"] == "reasoning" and w["graph"]["scope"] == "reasoning"
        for w in workflows
    )
    assert registrations[0]["id"] == "run-backend"
    assert (
        "viewer_workflow_id" not in registrations[0]["metadata"]
    )  # No ambiguous association.
    assert all(w["id"] != "run-backend" for w in workflows)


def test_single_reasoning_execution_association_preserves_source_identity(tmp_path):
    builder, payloads = fixture(
        tmp_path,
        execution={
            "declaration": "materialize",
            "id": "run-backend",
            "prepare_hook": "prepare",
        },
    )
    bundle, registrations = derive(builder.manifest, payloads)
    (reasoning,) = bundle["projects"][0]["workflows"]
    assert registrations[0]["metadata"]["viewer_workflow_id"] == reasoning["id"]
    assert registrations[0]["metadata"]["reasoning_contract"] == {
        "workflow": "NativeBackendExecution",
        "steps": ["candidate", "receipt"],
    }
    assert reasoning["graph"]["reasoning"] == "NativeBackendExecution"
    assert reasoning["id"] != "run-backend"
