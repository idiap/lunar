# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Selection, real file analysis, and source-bound reporting regression tests."""

import json
import uuid

import pytest

from catalog.integrations.domain_package.runtime import datasets
from catalog.integrations.domain_package.runtime.adapters import validate_run_request
from catalog.integrations.domain_package.runtime.liver_inputs import (
    WORKFLOW_ID,
    prepare,
)
from catalog.integrations.domain_package.runtime.report_packages import (
    build_verified_report_package,
)
from catalog.integrations.domain_package.runtime.runtime import (
    RuntimeContext,
)
from catalog.integrations.domain_package.runtime.schemas import PrismRunRequest


@pytest.fixture
def registered(tmp_path, monkeypatch):
    """Install temporary registered scientific datasets for the liver input oracles."""
    monkeypatch.setenv("BIOAGENTS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("BIOAGENTS_ALLOW_LIVE_NETWORK", raising=False)
    values = [
        (
            "cells",
            "liver_cell_metadata",
            ",patient,sample,tissue,celltype_major\nc1,p1,s1,liver,T\nc2,p1,s1,liver,B\nc3,p2,s2,liver,T\n",
        ),
        (
            "vdj",
            "liver_vdj",
            "Patient_a,TISSUE,clonal_id\np1,liver,c1\np1,liver,c1\np2,liver,c1\n",
        ),
    ]
    registry = []
    for identifier, role, content in values:
        (tmp_path / f"{identifier}.csv").write_text(content)
        registry.append(
            dict(
                dataset_id=identifier,
                name=identifier,
                resource_id="gene-expression-omnibus-geo",
                visibility="public",
                kind="data",
                workflow_ids=[WORKFLOW_ID],
                files=[dict(path=f"{identifier}.csv", analysis_role=role)],
            )
        )
    # This unselected dataset must neither block nor be read.
    registry.append(
        dict(
            dataset_id="missing",
            name="missing",
            resource_id="gene-expression-omnibus-geo",
            visibility="public",
            kind="data",
            workflow_ids=[WORKFLOW_ID],
            files=[dict(path="missing.csv", analysis_role="liver_cell_metadata")],
        )
    )
    monkeypatch.setattr(datasets, "registry", lambda: {"datasets": registry})
    return registry


def run(tmp_path, identifiers):
    """Prepare the selected fixture inputs in a dedicated regression run directory."""
    request = PrismRunRequest(
        ai_model_id=uuid.uuid4(), inputs={"dataset_ids": identifiers}
    )
    adapter, inputs = validate_run_request(WORKFLOW_ID, request)
    context = RuntimeContext(adapter, str(uuid.uuid4()), tmp_path / "run", "live")
    return context, prepare(context, inputs)


def test_selected_files_drive_patient_weighted_results_and_provenance(
    registered, tmp_path, monkeypatch
):
    """Verify selected files drive patient weighted results and provenance."""

    def forbidden(*args, **kwargs):
        """Fail if a data-only or offline operation invokes the prohibited boundary."""
        raise AssertionError("Saved reports and network must not be used")

    monkeypatch.setattr(
        "catalog.integrations.domain_package.runtime.fixture_inputs.load_saved_reporting_inputs",
        forbidden,
    )
    monkeypatch.setattr(
        "catalog.integrations.domain_package.runtime.liver_inputs.download", forbidden
    )
    context, prepared = run(tmp_path, ["cells", "vdj"])
    facts = prepared.analysis_results["derived_facts"]
    assert facts["composition"] == [
        ["cells", "liver", "B", 1, 2, 25.0],
        ["cells", "liver", "T", 2, 2, 75.0],
    ]
    assert facts["receptors"] == [["vdj", "liver", 3, 2, 2]]
    assert {s.source_local_identifier for s in context.consumed_sources} == {
        "cells",
        "vdj",
    }
    assert all(s.access_mode == "local_file" for s in context.consumed_sources)
    assert [b.local_identifier for b in context.adapter.source_bindings] == [
        "cells",
        "vdj",
    ]
    assert "p1" not in json.dumps(facts)
    assert "retained_analysis_fixture" not in [i.kind for i in context.input_entities]
    (tmp_path / "cells.csv").write_text(
        ",patient,sample,tissue,celltype_major\nc1,p1,s1,liver,T\n"
    )
    _, changed = run(tmp_path, ["cells"])
    assert changed.analysis_results["derived_facts"]["composition"] == [
        ["cells", "liver", "T", 1, 1, 100.0]
    ]
    assert changed.request_digest != prepared.request_digest


@pytest.mark.parametrize("ids", [[], ["cells", "cells"], ["unknown"], ["missing"]])
def test_invalid_or_missing_selection_fails_before_execution(registered, ids):
    """Verify invalid or missing selection fails before execution."""
    with pytest.raises(ValueError):
        validate_run_request(
            WORKFLOW_ID,
            PrismRunRequest(ai_model_id=uuid.uuid4(), inputs={"dataset_ids": ids}),
        )


def test_selection_cannot_override_paths_or_select_other_workflows(registered):
    """Verify selection cannot override paths or select other workflows."""
    registered[0]["workflow_ids"] = ["melanoma-resistance"]
    for inputs in (
        {"dataset_ids": ["cells"]},
        {"dataset_ids": ["vdj"], "data_root": "/tmp"},
    ):
        with pytest.raises(ValueError):
            validate_run_request(
                WORKFLOW_ID,
                PrismRunRequest(ai_model_id=uuid.uuid4(), inputs=inputs),
            )


def test_missing_download_requires_both_authorities(registered, monkeypatch):
    """Verify missing download requires both authorities."""
    registered[-1]["files"][0]["url"] = "https://ftp.ncbi.nlm.nih.gov/missing.csv"
    for server, request_authority in (("0", False), ("0", True), ("1", False)):
        monkeypatch.setenv("BIOAGENTS_ALLOW_LIVE_NETWORK", server)
        with pytest.raises(ValueError, match="required input unavailable"):
            validate_run_request(
                WORKFLOW_ID,
                PrismRunRequest(
                    ai_model_id=uuid.uuid4(),
                    network_authority=request_authority,
                    inputs={"dataset_ids": ["missing"]},
                ),
            )
    monkeypatch.setenv("BIOAGENTS_ALLOW_LIVE_NETWORK", "1")
    _, inputs = validate_run_request(
        WORKFLOW_ID,
        PrismRunRequest(
            ai_model_id=uuid.uuid4(),
            network_authority=True,
            inputs={"dataset_ids": ["missing"]},
        ),
    )
    assert inputs["allow_downloads"] is True


@pytest.mark.parametrize(
    "content",
    [
        "wrong,columns\na,b\n",
        ",patient,sample,tissue,celltype_major\n",
        ",patient,sample,tissue,celltype_major\nc1,p1,s1,liver,T\nc1,p1,s1,liver,T\n",
    ],
)
def test_bad_metadata_cannot_generate_a_report(registered, tmp_path, content):
    """Verify bad metadata cannot generate a report."""
    (tmp_path / "cells.csv").write_text(content)
    with pytest.raises(ValueError):
        run(tmp_path, ["cells"])
    assert not (tmp_path / "run/registered-analysis.json").exists()


def section_slots():
    """Provide complete typed narrative slots for the controlled liver report."""
    from catalog.integrations.domain_package.runtime.liver_inputs import report_contract

    return [
        dict(
            slot_id=key,
            prose=(
                f"This is the generated interpretation for {key}. The selected cell metadata support a descriptive account of supplied cell labels and tissue composition. "
                "They do not supply lesion morphology, gene expression, longitudinal outcomes or experimental perturbations. "
                "The next analysis must obtain paired measurements and evaluate patient-level uncertainty before proposing a validated causal mechanism."
            ),
        )
        for key in report_contract()["required_narrative_slots"]
    ]


def package_for(context, prepared, slots=None):
    """Assemble and verify a report from the test's prepared scientific evidence."""
    slots = section_slots() if slots is None else slots
    return build_verified_report_package(
        workflow_id=WORKFLOW_ID,
        context=context,
        analysis_results=prepared.analysis_results,
        compact_prism_input=prepared.value,
        raw_narrative_slots=slots,
        allowed_slot_ids={s["slot_id"] for s in slots},
        provenance={},
    )


def test_live_structure_matches_full_reviewed_reference(registered, tmp_path):
    """Verify live structure matches full reviewed reference."""
    from catalog.workflows.public.dependencies.report_utils import (
        load_report_contract,
        parse_markdown_structure,
    )
    from catalog.integrations.domain_package.runtime.liver_inputs import report_contract
    from PIL import Image

    context, prepared = run(tmp_path, ["cells", "vdj"])
    package = package_for(context, prepared)
    reference = load_report_contract(WORKFLOW_ID)
    current = report_contract()
    assert current["headings"] == reference["headings"]
    for kind in ("tables", "figures"):
        fields = (
            ("key", "placement_after_heading_key", "columns")
            if kind == "tables"
            else ("key", "placement_after_heading_key", "alt_text")
        )
        assert [[x[k] for k in fields] for x in current[kind]] == [
            [x[k] for k in fields] for x in reference[kind]
        ]
    parsed = parse_markdown_structure(package.markdown)
    assert (len(parsed["headings"]), len(parsed["tables"]), len(parsed["figures"])) == (
        73,
        101,
        9,
    )
    assert len(package.narrative_slots) == 72
    assert (
        len([b for b in package.report_layout["blocks"] if b["kind"] == "narrative"])
        == 72
    )
    assert "109 registered figure paths" not in package.markdown
    assert all(
        len(actual["rows"]) >= expected["min_rows"]
        for actual, expected in zip(parsed["tables"], current["tables"], strict=True)
    )
    assert "versioned reviewed priors" in package.markdown
    assert "NOT EVALUATED" not in package.markdown
    assert len(package.figures) == 9
    for figure in parsed["figures"]:
        path = context.run_root / figure["source"]
        with Image.open(path) as image:
            image.verify()
        data = json.loads(path.with_suffix(".png.json").read_text())
        assert data["provenance"]["selected_dataset_ids"] == ["cells", "vdj"]
        assert data["producer"].startswith("plot_")
        assert all(data["data"].values())


@pytest.mark.parametrize(
    "mutation", ["missing", "empty", "short", "duplicate", "heading", "figure", "table"]
)
def test_incomplete_model_sections_cannot_pass(registered, tmp_path, mutation):
    """Verify incomplete model sections cannot pass."""
    from catalog.workflows.public.dependencies.report_utils import (
        ReportVerificationError,
    )

    context, prepared = run(tmp_path, ["cells"])
    slots = section_slots()
    if mutation == "missing":
        slots.pop()
    elif mutation == "empty":
        slots = []
    elif mutation == "short":
        slots[0]["prose"] = "Insufficient."
    elif mutation == "duplicate":
        slots[0]["prose"] = slots[1]["prose"]
    else:
        slots[0]["prose"] = {
            "heading": "## Injected heading",
            "figure": "![Fake](fake.png)",
            "table": "| Fake | table |",
        }[mutation]
    with pytest.raises(ReportVerificationError):
        package_for(context, prepared, slots)
    assert (
        json.loads((context.run_root / "report-verification.json").read_text())[
            "status"
        ]
        == "failed"
    )


@pytest.mark.parametrize(
    "mutation", ["heading", "table", "figure", "corrupt_asset", "missing_asset"]
)
def test_live_structural_regressions_fail_closed(
    registered, tmp_path, mutation, monkeypatch
):
    """Verify live structural regressions fail closed."""
    import catalog.integrations.domain_package.runtime.report_packages as packages
    from catalog.workflows.public.dependencies.report_utils import (
        ReportVerificationError,
    )

    context, prepared = run(tmp_path, ["cells"])
    original = packages.render_contract_markdown

    def changed(**kwargs):
        """Apply the deliberate evidence or report mutation used by this failure oracle."""
        markdown, artifacts, evidence = original(**kwargs)
        blocks = evidence["report_layout"]["blocks"]
        if mutation in {"heading", "table", "figure"}:
            block = next(b for b in blocks if b["kind"] == mutation)
            markdown = markdown[: block["start"]] + markdown[block["end"] :]
        else:
            path = (
                context.run_root
                / prepared.analysis_results["reporting_inputs"]["figures"][0]["path"]
            )
            if mutation == "corrupt_asset":
                path.write_bytes(b"not a figure")
            else:
                path.unlink()
        return markdown, artifacts, evidence

    monkeypatch.setattr(packages, "render_contract_markdown", changed)
    with pytest.raises(ReportVerificationError):
        package_for(context, prepared)


def test_review_figures_are_recomputed_from_scientific_inputs(
    registered, tmp_path, monkeypatch
):
    """Verify review figures are recomputed from scientific inputs."""
    from catalog.workflows.public.liver_metastasis_ecosystem import core

    context, prepared = run(tmp_path, ["cells"])
    figure = (
        context.run_root
        / prepared.analysis_results["reporting_inputs"]["figures"][6]["path"]
    )
    first = figure.read_bytes()
    data = json.loads(figure.with_suffix(".png.json").read_text())
    assert data["producer"] == "plot_claim_rank_sensitivity"
    assert data["data"]["claim_rank_sensitivity_rows"]
    original = core.build_analysis_state

    def changed(**kwargs):
        """Apply the deliberate evidence or report mutation used by this failure oracle."""
        state, manifest = original(**kwargs)
        state["claim_rank_sensitivity_rows"][0]["baseline_rank"] = 6
        return state, manifest

    monkeypatch.setattr(core, "build_analysis_state", changed)
    run(tmp_path, ["cells"])
    assert figure.read_bytes() != first
    assert (
        json.loads(figure.with_suffix(".png.json").read_text())["data"][
            "claim_rank_sensitivity_rows"
        ][0]["baseline_rank"]
        == 6
    )


@pytest.mark.parametrize(
    "mutation",
    ["empty_table", "short_table", "missing_figure_data", "missing_matplotlib"],
)
def test_incomplete_scientific_analysis_cannot_publish(
    registered, tmp_path, monkeypatch, mutation
):
    """Verify incomplete scientific analysis cannot publish."""
    from catalog.workflows.public.liver_metastasis_ecosystem import core
    from catalog.workflows.public.dependencies.report_utils import (
        ReportVerificationError,
        parse_markdown_structure,
    )
    import catalog.integrations.domain_package.runtime.liver_report as report

    if mutation in {"empty_table", "short_table"}:

        def incomplete(markdown):
            """Remove the selected scientific evidence required by the report contract."""
            parsed = parse_markdown_structure(markdown)
            parsed["tables"][0]["rows"] = (
                [] if mutation == "empty_table" else parsed["tables"][0]["rows"][:1]
            )
            return parsed

        monkeypatch.setattr(report, "parse_markdown_structure", incomplete)
    elif mutation == "missing_figure_data":
        original = core.build_analysis_state

        def incomplete(**kwargs):
            """Remove the selected scientific evidence required by the report contract."""
            state, manifest = original(**kwargs)
            state["contextual_causal_coherence_graph"]["edges"] = []
            return state, manifest

        monkeypatch.setattr(core, "build_analysis_state", incomplete)
    else:
        monkeypatch.setattr(core, "import_matplotlib", lambda: None)
    with pytest.raises(ReportVerificationError):
        run(tmp_path, ["cells"])
    assert not (tmp_path / "run/report-verification.json").exists()


def test_consistently_empty_reporting_evidence_cannot_pass(registered, tmp_path):
    """Verify consistently empty reporting evidence cannot pass."""
    from catalog.workflows.public.dependencies.report_utils import (
        ReportVerificationError,
    )

    context, prepared = run(tmp_path, ["cells"])
    prepared.analysis_results["reporting_inputs"]["tables"][0]["rows"] = []
    with pytest.raises(
        ReportVerificationError, match="fewer than required scientific rows"
    ):
        package_for(context, prepared)


@pytest.mark.parametrize(
    "mutation", ["omitted", "extra", "short", "structure", "provider_failure"]
)
def test_model_writer_cannot_silently_fill_missing_or_invalid_sections(
    registered, tmp_path, mutation
):
    """Verify model writer cannot silently fill missing or invalid sections."""
    from types import SimpleNamespace
    from catalog.integrations.domain_package.runtime.liver_report import (
        generate_section_narratives,
    )

    context, prepared = run(tmp_path, ["cells"])
    model = SimpleNamespace(
        provider="openai",
        model_id="stub",
        config={},
        api_key="test-key",
        api_base=None,
        api_version=None,
        safe_snapshot={"model_id": "stub"},
    )
    calls = []

    def completion(**arguments):
        """Return the selected malformed model response for the narrative rejection oracle."""
        calls.append(arguments)
        if mutation == "provider_failure":
            raise RuntimeError("provider unavailable")
        keys = arguments["response_format"]["json_schema"]["schema"]["required"]
        values = {
            s["slot_id"]: s["prose"] for s in section_slots() if s["slot_id"] in keys
        }
        if mutation == "omitted":
            values.pop(keys[0])
        elif mutation == "extra":
            values["unknown"] = "Invented section"
        elif mutation == "short":
            values[keys[0]] = "Too short."
        elif mutation == "structure":
            values[keys[0]] = "## Invented heading"
        return {"choices": [{"message": {"content": json.dumps(values)}}]}

    with pytest.raises((ValueError, RuntimeError)):
        generate_section_narratives(context, prepared, [], model, completion=completion)
    assert len(calls) == 1
    assert context.stages[-1].status == "failed"
    assert not (context.run_root / "report-verification.json").exists()


def test_invalid_image_is_rejected_even_with_matching_hash(registered, tmp_path):
    """Verify invalid image is rejected even with matching hash."""
    import hashlib
    from catalog.workflows.public.dependencies.report_utils import (
        ReportVerificationError,
    )

    context, prepared = run(tmp_path, ["cells"])
    packet = prepared.analysis_results["reporting_inputs"]
    figure = packet["figures"][0]
    invalid = b"an invalid image with a consistent checksum"
    (context.run_root / figure["path"]).write_bytes(invalid)
    figure["sha256"] = hashlib.sha256(invalid).hexdigest()
    packet["files"][figure["path"]]["sha256"] = figure["sha256"]
    with pytest.raises(ReportVerificationError, match="cannot be decoded"):
        package_for(context, prepared)
