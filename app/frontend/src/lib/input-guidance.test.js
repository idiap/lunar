// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { inputHints, inputSuggestions } from "./input-guidance.js";
import { reusableInputRuns } from "./schema-form.js";

test("explicit presentation overrides field conventions without inventing values", () => {
  assert.equal(inputHints({}, "document_paths").kind, "file");
  assert.equal(inputHints({}, "baseline_digest").kind, "digest");
  assert.equal(inputHints({}, "review_policy").kind, "text");
  assert.equal(inputHints({ "x-input": { kind: "textarea" } }, "document_paths").kind, "textarea");
  assert.deepEqual(inputSuggestions({}, ["policy"], []), []);
  assert.deepEqual(inputSuggestions({ examples: ["a", "a"] }, ["settings", "policy"], [
    { settings: { policy: "b" } }, { settings: { policy: "a" } },
  ]), [{ value: "a", label: "Example" }, { value: "b", label: "Previous run" }]);
});

test("input reuse excludes foreign versions, workflows, failed, imported, and invalid runs", () => {
  const valid = { workflow_id: "review", version_id: "version-1", state: "completed", safe_inputs: { inputs: { count: 2 } } };
  const invalid = [
    { version_id: "version-2" }, { workflow_id: "other" },
    { state: "failed" }, { imported: true }, { safe_inputs: {} }, { safe_inputs: { inputs: { count: 0 } } },
  ].map((change) => ({ ...valid, ...change }));
  assert.deepEqual(reusableInputRuns([valid, ...invalid], {
    workflowId: "review", versionId: "version-1",
    schema: { type: "object", required: ["count"], properties: { count: { type: "integer", minimum: 1 } } },
  }), [valid]);
});
