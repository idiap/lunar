// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";
import { apiText } from "./api.js";
import { setSelection } from "./package-selection.js";

test("source fetches retain authentication, selection and complete Unicode text", async (t) => {
  setSelection("user", "version");
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/source");
    assert.equal(options.credentials, "include");
    assert.equal(options.headers["X-Lunar-Package-Version"], "version");
    return new Response("theorem test (x : ℝ) : x = x := by rfl\n");
  });
  assert.equal(await apiText("/source"), "theorem test (x : ℝ) : x = x := by rfl\n");
});

test("source fetches reject HTTP failures, oversized streams and stale workspaces", async (t) => {
  const mock = t.mock.method(globalThis, "fetch", async () => new Response("missing", { status: 410 }));
  await assert.rejects(apiText("/source"), /HTTP 410/);
  mock.mock.mockImplementation(async () => new Response("123456789"));
  await assert.rejects(apiText("/source", { maxBytes: 4 }), /too large/);
  mock.mock.mockImplementation(async () => { setSelection("user", "changed"); return new Response("source"); });
  await assert.rejects(apiText("/source"), /Workspace selection changed/);
});
