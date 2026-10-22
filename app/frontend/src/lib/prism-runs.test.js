// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";

import {
  canRunWorkflow,
  workflowExecutionOptions,
  selectedDatasetStatus,
  emptyModelListLabel,
  latestOutput,
  headingAnchor,
  modelOptionLabel,
  prismAgentEvents,
  prismRunPayload,
  reportHeadings,
  reportTarget,
  runReportPath,
  runStatusLabel,
  TERMINAL_RUN_STATES,
  nativeReportTree,
  verifyReportLayout,
} from "./prism-runs.js";

test("builds one execution request without credentials or modes", () => {
  assert.deepEqual(prismRunPayload("melanoma-resistance", { aiModelId: "model-uuid" }), {
    operation: "run", ai_model_id: "model-uuid", inputs: {}, network_authority: false,
  });
  assert.deepEqual(prismRunPayload("pharmaceutical-process-capture").inputs, {});
  assert.equal(JSON.stringify(prismRunPayload("melanoma-resistance", { aiModelId: "model-uuid" })).includes("api_key"), false);
});

test("requires explicit model selection for every fixed workflow card", () => {
  const base = { runnable: { id: "melanoma-resistance", metadata: { model_required: true } } };
  assert.equal(canRunWorkflow({ ...base, aiModelId: "" }), false);
  assert.equal(canRunWorkflow({ ...base, aiModelId: "model-uuid" }), true);
  assert.equal(canRunWorkflow({ ...base, runnable: null, aiModelId: "model-uuid" }), false);
});

test("labels configured and empty model lists without secret fields", () => {
  const model = { id: "model-uuid", name: "Reviewed", provider: "openai", model_id: "gpt-test", api_key: "must-not-render" };
  assert.equal(modelOptionLabel(model), "Reviewed (openai/gpt-test)");
  assert.equal(modelOptionLabel(model).includes(model.api_key), false);
  assert.equal(emptyModelListLabel([]), "No configured models");
  assert.equal(emptyModelListLabel([model]), "Select a configured model");
  assert.deepEqual(prismAgentEvents({ events: [{ id: 1, detail: { event_kind: "workflow-node" } }, { id: 2, detail: { event_kind: "agent-invoked" } }] }).map((event) => event.id), [2]);
});

test("projects run status and output consistently", () => {
  assert.equal(TERMINAL_RUN_STATES.has("failed"), true);
  assert.equal(TERMINAL_RUN_STATES.has("running"), false);
  assert.equal(runStatusLabel("worker_interrupted"), "worker interrupted");
  assert.equal(latestOutput({ outputs: [{ output_key: "report" }] }).output_key, "report");
  assert.equal(latestOutput({}), null);
});

test("builds the run report path", () => {
  assert.equal(runReportPath("run/id"), "/prism/runs/run%2Fid/report");
});

test("maps only recorded relative report artifacts to authenticated URLs", () => {
  const run = { artifacts: [{ safe_locator: "run:figures/plot.svg", url: "/api/artifact-id" }] };
  assert.equal(reportTarget(run, "figures/plot.svg"), "/api/artifact-id");
  assert.equal(reportTarget(run, "https://doi.org/example"), "https://doi.org/example");
  assert.equal(reportTarget(run, "#references"), "#references");
  assert.equal(reportTarget(run, "../secret"), null);
  assert.equal(reportTarget(run, "%2e%2e/secret"), null);
  assert.equal(reportTarget(run, "file:///tmp/secret"), null);
  assert.equal(reportTarget(run, "figures/missing.svg"), null);
});

test("derives stable safe heading anchors and contents outside code fences", () => {
  assert.equal(headingAnchor("Claim ceiling & release"), "claim-ceiling-release");
  assert.deepEqual(reportHeadings("# Report\n\n## Results\n## Results\n```\n## not a heading\n```\n"), [
    { level: 1, text: "Report", id: "report" },
    { level: 2, text: "Results", id: "results" },
    { level: 2, text: "Results", id: "results-2" },
  ]);
});

test("network authority is an explicit run permission", () => {
  const payload = prismRunPayload("her2-arm-proteogenomics", { aiModelId: "model-uuid", networkAuthority: true });
  assert.equal("mode" in payload, false);
  assert.equal(payload.network_authority, true);
  const offline = prismRunPayload("her2-arm-proteogenomics", { aiModelId: "model-uuid" });
  assert.equal(offline.network_authority, false);
  assert.deepEqual(payload.inputs, {});
});

test("includes fourth-level headings and redirects report self-links", () => {
  assert.deepEqual(reportHeadings("#### Panel\n#### Panel"), [
    { level: 4, text: "Panel", id: "panel" }, { level: 4, text: "Panel", id: "panel-2" },
  ]);
  const run = { id: "saved-run", artifacts: [{ safe_locator: "run:figures/plot.svg", url: "/api/plot" }] };
  assert.equal(reportTarget(run, "report.md#results"), "/prism/runs/saved-run/report#results");
  assert.equal(reportTarget(run, "figures/plot.svg#panel"), "/api/plot#panel");
  run.artifacts[0].safe_locator = "figures/plot.svg";
  assert.equal(reportTarget(run, "figures/plot.svg#panel"), "/api/plot#panel");
  assert.equal(reportTarget(run, "figures/unrecorded.svg"), null);
});

for (const schemaVersion of ["lunar.native-report/v1", "bioagents.native-report/v1"]) {
test(`groups ${schemaVersion} Unicode content without losing legacy Markdown`, () => {
  assert.equal(nativeReportTree({ markdown: "# Historical report" }), null);
  const output = {
    markdown: "# Results\n\nEvidence 🧬.\n\n",
    structured_value: { report_layout: {
      schema_version: schemaVersion,
      groups: [{ key: "results-tab", kind: "tab", label: "Results" }],
      anchors: [{ id: "source-anchor", content_key: "prose" }],
      blocks: [
        { id: "heading", kind: "heading", heading_key: "controlled-heading", start: 0, end: 11, group_keys: ["results-tab"] },
        { id: "prose", kind: "prose", start: 11, end: 24, group_keys: ["results-tab"] },
      ],
    } },
  };
  output.structured_value.report_layout.blocks[1].end = Array.from(output.markdown).length;
  const [group] = nativeReportTree(output);
  assert.equal(group.kind, "tab");
  assert.equal(group.children[0].headingId, "controlled-heading");
  assert.deepEqual(group.children[0].anchors, []);
  assert.equal(group.children[1].markdown, "Evidence 🧬.\n\n");
  assert.deepEqual(group.children[1].anchors, ["source-anchor"]);
  output.structured_value.report_layout.blocks.pop();
  assert.throws(() => nativeReportTree(output), /content is missing/);
});
}

test("rejects broken metadata and mismatched report content", async () => {
  assert.throws(() => nativeReportTree({ markdown: "text", structured_value: { report_layout: {} } }), /metadata is unavailable/);
  await assert.rejects(verifyReportLayout({ markdown: "changed", structured_value: { report_layout: { content_sha256: "stale" } } }), /integrity check/);
});


test("registered selections are sent explicitly and only selected availability blocks runs", () => {
  const payload = prismRunPayload("liver-metastasis-ecosystem", { aiModelId: "model-id", datasetIds: ["cohort"], networkAuthority: true });
  assert.deepEqual(payload.inputs, { dataset_ids: ["cohort"] });
  assert.equal(payload.network_authority, true);
  const runnable = { downloads_enabled: false, datasets: [
    { dataset_id: "cohort", status: "available" },
    { dataset_id: "review", status: "unavailable" },
    { dataset_id: "remote", status: "download_required" },
  ] };
  assert.equal(selectedDatasetStatus(runnable, ["cohort"]).ready, true);
  for (const ids of [[], ["review"], ["remote"], ["unknown"], ["cohort", "cohort"]]) {
    assert.equal(selectedDatasetStatus(runnable, ids).ready, false);
  }
  assert.equal(selectedDatasetStatus({ ...runnable, downloads_enabled: true }, ["remote"]).ready, true);
});


test("maps viewable workflows only to registered execution adapters", () => {
  const registry = ["melanoma-resistance", "pharmaceutical-process-clone", "pharmaceutical-process-capture", "private-workflow"]
    .map((id) => ({ id, metadata: { viewer_workflow_id: id.startsWith("pharmaceutical-process-") ? "pharmaceutical-process" : id } }));
  assert.deepEqual(workflowExecutionOptions("biomedical-research-ethics", registry), []);
  assert.deepEqual(workflowExecutionOptions("melanoma-resistance", []), []);
  assert.deepEqual(workflowExecutionOptions("melanoma-resistance", registry).map((item) => item.id), ["melanoma-resistance"]);
  assert.deepEqual(workflowExecutionOptions("pharmaceutical-process", registry).map((item) => item.id),
    ["pharmaceutical-process-clone", "pharmaceutical-process-capture"]);
});
