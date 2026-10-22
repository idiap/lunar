// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { formSchema, schemaFormValidator, workflowInputSchema } from "./schema-form.js";

test("the workflow has one input schema", () => {
  const base = { type: "object" };
  assert.equal(workflowInputSchema({ input_schema: base }), base);
  assert.equal(workflowInputSchema({ input_schema: base, metadata: { mode_input_schemas: { live: { type: "string" } } } }), base);
});

test("nullable field normalization preserves validation and does not mutate schemas or defaults", () => {
  const schema = { type: "object", properties: {
    goal: { anyOf: [{ type: "string", minLength: 2 }, { type: "null" }], default: null },
    choice: { anyOf: [{ type: "string", enum: ["a"] }, { type: "null" }] },
  } };
  const original = structuredClone(schema);
  const normalized = formSchema(schema);
  assert.deepEqual(schema, original);
  for (const value of [{}, { goal: null }, { goal: "ok" }, { goal: "x" }, { goal: 2 }, { choice: null }, { choice: "b" }]) {
    assert.equal(schemaFormValidator.isValid(normalized, value, normalized), schemaFormValidator.isValid(schema, value, schema));
  }
});

test("validation supports Draft 2020-12 constraints", () => {
  const schema = { $schema: "https://json-schema.org/draft/2020-12/schema", type: "object", properties: {
    pair: { type: "array", prefixItems: [{ type: "string" }, { type: "integer" }], items: false },
  } };
  assert.equal(schemaFormValidator.isValid(schema, { pair: ["a", 1] }, schema), true);
  assert.equal(schemaFormValidator.isValid(schema, { pair: [1, "a"] }, schema), false);
});
