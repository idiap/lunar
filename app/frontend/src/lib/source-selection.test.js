// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { schemasCompatible, compatibleSource, referenceMatches, sourceFields, inputDefaults } from "./source-selection.js";

const hints = { kind: "data-source", content_kind: "json", native_schema: { type: "integer" } };
const reference = { source_id: "count", package_version: "v1", digest: `sha256:${"a".repeat(64)}` };
const source = { selection: { reference, materialized: true, content_kind: "json", native_schema: { type: "integer" } } };

test("compatibility supports exact contracts and safe unions without dropping constraints", () => {
  assert.equal(schemasCompatible({ type: "string", enum: ["a"] }, { enum: ["a"], type: "string" }), true);
  assert.equal(schemasCompatible({ type: "integer" }, { anyOf: [{ type: "integer" }, { type: "null" }] }), true);
  assert.equal(schemasCompatible({ type: ["string", "null"] }, { type: ["string", "integer", "null"] }), true);
  assert.equal(schemasCompatible({ type: ["string", "null"] }, { type: "string" }), false);
  assert.equal(schemasCompatible({ type: "string" }, { type: "string", minLength: 1 }), false);
  assert.equal(schemasCompatible({ type: "integer" }, { anyOf: [{ type: "integer" }], minimum: 1 }), false);
});

test("references require materialized compatible content and exact version and digest", () => {
  assert.equal(compatibleSource(source, hints), true);
  assert.equal(compatibleSource({ selection: { ...source.selection, materialized: false } }, hints), false);
  assert.equal(compatibleSource(source, { ...hints, content_kind: "file" }), false);
  assert.equal(referenceMatches(source, { ...reference, package_version: "v2" }, hints), false);
  assert.equal(referenceMatches(source, { ...reference, digest: `sha256:${"b".repeat(64)}` }, hints), false);
  assert.equal(referenceMatches(source, { ...reference, extra: true }, hints), false);
  assert.equal(compatibleSource({ selection: { ...source.selection, content_kind: "directory" } }, { ...hints, content_kind: "path" }), true);
});

test("source discovery follows nested refs and array paths without reading payload schemas", () => {
  const schema = { $defs: { source: { "x-input": hints } }, properties: { entries: { type: "array", items: { properties: { payload: { $ref: "#/$defs/source" } } } } } };
  assert.deepEqual(sourceFields(schema, { entries: [{ payload: reference }] }).map(({ path, value }) => ({ path, value })), [{ path: ["entries", 0, "payload"], value: reference }]);
});


test("authored defaults preserve omitted contexts and required boolean omission", () => {
  const schema = { type: "object", properties: {
    budget: { type: "integer", default: 3 },
    context: { type: "object", required: ["nested"], properties: { nested: { type: "object", required: ["flag"], properties: { flag: { type: "boolean" } } }, setting: { type: "integer", default: 2 } } },
    source: { type: "object", default: reference, "x-input": hints },
  } };
  assert.deepEqual(inputDefaults(schema, {}), { budget: 3, source: reference });
  assert.deepEqual(inputDefaults(schema, { context: {} }), { budget: 3, source: reference, context: { nested: {}, setting: 2 } });
  assert.equal(schema.properties.context.properties.nested.properties.flag.default, undefined);
});
