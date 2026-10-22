// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";

import {
  bindingsComplete,
  outputsByVariable,
  reportContentSegments,
  sectionProvenancePath,
} from "./template-bindings.js";

test("derives only compatible output choices and complete binding state", () => {
  const compatible = outputsByVariable(["a", "b"], [
    { id: "1", output_key: "a" }, { id: "2", output_key: "b" }, { id: "3", output_key: "other" },
  ]);
  assert.deepEqual(compatible.a.map((item) => item.id), ["1"]);
  assert.equal(bindingsComplete(["a", "b"], { a: "1" }, compatible), false);
  assert.equal(bindingsComplete(["a", "b"], { a: "1", b: "2" }, compatible), true);
  assert.equal(bindingsComplete(["a", "b"], { a: "3", b: "2" }, compatible), false);
});

test("constructs an encoded section provenance route", () => {
  assert.equal(sectionProvenancePath("report id", "section/one"), "/reports/report%20id/provenance?section=section%2Fone");
});

test("splits report markdown around provenance-backed sections in ordinal order", () => {
  const sections = [
    { section_id: "second", ordinal: 1, rendered_markdown: "## Result B\n\nB body" },
    { section_id: "first", ordinal: 0, rendered_markdown: "## Result A\n\nA body" },
  ];
  const segments = reportContentSegments(
    "# Report\n\n## Result A\n\nA body\n\nContext\n\n## Result B\n\nB body\n",
    sections,
  );

  assert.deepEqual(segments.map((segment) => segment.section?.section_id || null), [null, "first", null, "second", null]);
  assert.equal(segments.map((segment) => segment.content).join(""), "# Report\n\n## Result A\n\nA body\n\nContext\n\n## Result B\n\nB body\n");
});

test("keeps unmatched report content visible", () => {
  assert.deepEqual(reportContentSegments("# Report", [{ ordinal: 0, rendered_markdown: "missing" }]), [
    { content: "# Report" },
  ]);
});
