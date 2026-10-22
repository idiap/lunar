// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { customizeValidator } from "@rjsf/validator-ajv8";
import Ajv2020 from "ajv/dist/2020.js";
import { inputLabel } from "./input-guidance.js";

// Match the package runtime's JSON Schema dialect. Format is annotation-only
// there, so avoid rejecting inputs here that the server would accept.
export const schemaFormValidator = customizeValidator({
  AjvClass: Ajv2020,
  ajvOptionsOverrides: { strict: false, validateFormats: false },
});

export function workflowInputSchema(workflow) {
  return workflow?.input_schema ?? { type: "object", properties: {} };
}

export function reusableInputRuns(runs, { workflowId, versionId, schema }) {
  return runs.filter((run) => run.workflow_id === workflowId && run.version_id === versionId &&
    run.state === "completed" && !run.imported && run.safe_inputs?.inputs &&
    schemaFormValidator.isValid(schema, run.safe_inputs.inputs, schema));
}

// Pydantic represents optional values with anyOf. The equivalent type union
// lets the renderer show a single field instead of a string/null chooser.
export function formSchema(schema, name = "") {
  if (typeof schema !== "object" || schema === null) return schema;
  const result = { ...schema };
  if (name && result.title === undefined) result.title = inputLabel(name);
  for (const key of ["properties", "$defs", "definitions", "patternProperties", "dependentSchemas"]) {
    if (result[key]) result[key] = Object.fromEntries(Object.entries(result[key]).map(([childName, child]) => [childName, formSchema(child, key === "properties" ? childName : "")]));
  }
  for (const key of ["items", "additionalProperties", "contains", "not", "if", "then", "else", "propertyNames", "unevaluatedProperties", "unevaluatedItems"]) {
    if (result[key] !== undefined) result[key] = formSchema(result[key]);
  }
  for (const key of ["anyOf", "oneOf", "allOf", "prefixItems"]) {
    if (Array.isArray(result[key])) result[key] = result[key].map((child) => formSchema(child));
  }
  const branches = result.anyOf;
  if (branches?.length === 2) {
    const nullBranch = branches.find((branch) => branch.type === "null" && Object.keys(branch).length === 1);
    const valueBranch = branches.find((branch) => ["string", "number", "integer", "boolean"].includes(branch.type));
    if (nullBranch && valueBranch && !valueBranch.enum && valueBranch.const === undefined && !result.type && !result.$ref) {
      // Preserve outer constraints rather than overriding them with branch keys.
      const overlaps = Object.keys(valueBranch).some((key) => key !== "type" && key in result);
      if (!overlaps) {
        delete result.anyOf;
        return { ...result, ...valueBranch, type: [valueBranch.type, "null"] };
      }
    }
  }
  return result;
}
