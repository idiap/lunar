// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";
import { codeLanguage, highlightSource, reportSourceFiles } from "./source-highlighter.js";

test("Lean grammar preserves Unicode, whitespace and nested comments while coloring declarations", async () => {
  const source = '/- outer /- inner -/ end -/\ntheorem identity (x : ℝ) : x = x := by\n  rfl\n';
  const lines = await highlightSource(source, "lean4");
  assert.equal(lines.map((line) => line.map((token) => token.content).join("")).join("\n"), source);
  assert.ok(lines[1].some((token) => token.content === "theorem" && token.color !== "#24292E"));
  assert.equal(codeLanguage("Lean"), "lean4");
  assert.equal(await highlightSource(source, "unknown"), null);
});

test("source previews are workflow-independent and group duplicate registered files", () => {
  const artifact = (id, name, digest = "a".repeat(64)) => ({ id, safe_locator: name,
    content_digest: `sha256:${digest}`, url: `/api/prism/runs/run-1/artifacts/${id}?package_version_id=v1` });
  const files = reportSourceFiles({ id: "run-1", workflow_id: "any-workflow", artifacts: [
    artifact("final", "proofs/Identity.lean"), artifact("attempt", "run:attempts/Identity.lean"),
    artifact("log", "compiler.log"), { ...artifact("external", "Remote.lean"), url: "https://example.org/Remote.lean" },
    artifact("other", "Other.lean", "b".repeat(64)),
  ] });
  assert.equal(files.length, 2);
  assert.equal(files[0].name, "proofs/Identity.lean");
  assert.equal(files[0].aliases[0].name, "attempts/Identity.lean");
});
