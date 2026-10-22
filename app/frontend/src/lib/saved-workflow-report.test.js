// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { workflowHistoryId, nativeHtmlReport, reportRunDescription } from "./prism-runs.js";

test("workflow history follows the material execution registration", () => {
  assert.equal(workflowHistoryId("abducer_work_loop", undefined), "abducer_work_loop");
  assert.equal(workflowHistoryId("viewer", {id: "execution"}), "execution");
});

test("imported report is never described as a fixture or live execution", () => {
  const description = reportRunDescription({imported: true, mode: "historical", generation_status: "completed", run_id: "imported-example"});
  assert.match(description, /Imported report/);
  assert.doesNotMatch(description, /execution|fixtures|datasets/);
  assert.doesNotMatch(reportRunDescription({mode: "fixture", run_id: "test"}), /fixture|live/i);
});

test("imported report remains bound to an owned database artifact", () => {
  const path = "package:example-file";
  const sha256 = "a".repeat(64);
  const output = {structured_value: {html_report: {path, sha256, media_type: "text/html"}}};
  const artifact = {safe_locator: path, content_digest: `sha256:${sha256}`,
    media_type: "text/html", url: "/api/prism/runs/imported/artifacts/owned"};
  assert(nativeHtmlReport({id: "imported", artifacts: [artifact]}, output));
  assert.throws(() => nativeHtmlReport({id: "other", artifacts: [artifact]}, output), /inventory/);
});
