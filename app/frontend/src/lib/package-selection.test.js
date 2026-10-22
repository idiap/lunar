// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";
import { api, streamAgUi } from "./api.js";
import { setSelection } from "./package-selection.js";
import { loadPrismCatalog } from "./prism-catalog.js";
import { validatePrismBundle } from "./prism-viewer.js";
import { validateSkillDetail } from "./skills.js";
import { workflowExecutionOptions, canRunWorkflow } from "./prism-runs.js";

test("discard old responses, separate same-ID catalogs and clear on sign-out", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = (url, options) => new Promise((resolve) => calls.push({ url, options, resolve }));
  try {
    setSelection("owner-a", "version-a");
    const first = loadPrismCatalog();
    assert.equal(loadPrismCatalog(), first);
    assert.equal(calls[0].options.headers["X-Lunar-Package-Version"], "version-a");
    setSelection("owner-a", "version-b");
    const second = loadPrismCatalog();
    const catalog = { schema_version: 1, visibility: "package", modules: [{ id: "same", name: "Version B" }] };
    calls[1].resolve(Response.json(catalog));
    assert.deepEqual(await second, catalog);
    calls[0].resolve(Response.json({ ...catalog, modules: [{ id: "same", name: "Version A" }] }));
    await assert.rejects(first, { name: "AbortError" });
    setSelection(null);
    setSelection("owner-b", "version-b");
    const other = loadPrismCatalog();
    assert.equal(calls.length, 3);
    calls[2].resolve(Response.json({ ...catalog, modules: [] }));
    assert.deepEqual((await other).modules, []);
    const body = new FormData(); body.append("file", new Blob(["zip"]), "package.zip");
    const upload = api("/api/packages/import", { method: "POST", body });
    assert.equal(calls[3].options.headers["Content-Type"], undefined);
    calls[3].resolve(Response.json({ version: {} })); await upload;
  } finally { globalThis.fetch = original; setSelection(null); }
});

test("loads another owned package catalog without changing the workspace selection", async () => {
  const original = globalThis.fetch;
  let call;
  globalThis.fetch = (url, options) => new Promise((resolve) => { call = { url, options, resolve }; });
  try {
    setSelection("owner", "selected-version");
    const pending = loadPrismCatalog("browsed-version");
    assert.equal(call.options.headers["X-Lunar-Package-Version"], "browsed-version");
    const catalog = { schema_version: 1, visibility: "package", modules: [], skills: [], resources: [] };
    call.resolve(Response.json(catalog));
    assert.deepEqual(await pending, catalog);
    assert.equal(loadPrismCatalog("browsed-version"), pending);
  } finally { globalThis.fetch = original; setSelection(null); }
});

test("a switched-away chat keeps consuming its original stream without updating the new view", async () => {
  const original = globalThis.fetch;
  const encoder = new TextEncoder(); let controller;
  globalThis.fetch = async (_, options) => {
    assert.equal(options.headers["X-Lunar-Package-Version"], "version-a");
    return new Response(new ReadableStream({ start(value) { controller = value; } }));
  };
  try {
    setSelection("owner", "version-a");
    const events = [];
    const stream = streamAgUi({}, (event) => events.push(event));
    await Promise.resolve();
    setSelection("owner", "version-b");
    controller.enqueue(encoder.encode('data: {"type":"CUSTOM","name":"chat_saved"}\n\ndata: {"type":"RUN_FINISHED"}\n\n'));
    controller.close(); await stream;
    assert.deepEqual(events, []);
  } finally { globalThis.fetch = original; setSelection(null); }
});

test("neutral packages need neither reviewed graphs, legacy hierarchy nor a model", () => {
  assert.deepEqual(validatePrismBundle({ kind: "prism-viewer-bundle", schema_version: 1, projects: [] }).projects, []);
  const skill = { skill_id: "count", display_name: "Count", version: "1", description: "Count stock", instructions: "Count.", source_path: "skills/count.json", role: null, theme: null, cluster: null };
  assert.equal(validateSkillDetail(skill), skill);
  const workflow = { id: "count", metadata: { viewer_workflow_id: "warehouse" } };
  assert.equal(canRunWorkflow({ runnable: workflow }), true);
  assert.deepEqual(workflowExecutionOptions("warehouse", [workflow]), [workflow]);
});
