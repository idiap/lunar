// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { nativeHtmlReport, verifiedHtmlDocument } from "./prism-runs.js";
globalThis.crypto ??= webcrypto;
test("HTML policy precedes early scripts and preserves source", async () => {
  const source = '<script>window.test=true</script><head></head><p>result</p>';
  const hash = createHash('sha256').update(source).digest('hex');
  const framed = await verifiedHtmlDocument(source, hash);
  assert(framed.indexOf('Content-Security-Policy') < framed.indexOf('<script>'));
  assert(framed.includes(source));
  await assert.rejects(verifiedHtmlDocument(source+'changed',hash), /integrity/);
});
test("HTML artifact must belong to the current run and digest", () => {
  const descriptor = {path:'full_timeline.html',sha256:'a'.repeat(64),media_type:'text/html'};
  const output = {structured_value:{html_report:descriptor}};
  const artifact = {safe_locator:descriptor.path,content_digest:'sha256:'+descriptor.sha256,
    media_type:'text/html',url:'/api/prism/runs/owned/artifacts/result'};
  assert(nativeHtmlReport({id:'owned',artifacts:[artifact]},output));
  assert.throws(()=>nativeHtmlReport({id:'foreign',artifacts:[artifact]},output), /inventory/);
  assert.throws(()=>nativeHtmlReport({id:'owned',artifacts:[{...artifact,content_digest:'bad'}]},output), /inventory/);
  assert.equal(nativeHtmlReport({id:'owned'},{}),null);
});
