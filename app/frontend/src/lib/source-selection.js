// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
// Match Mathformer's conservative authored-schema compatibility rules. Equal
// contracts and safe union widening are supported; arbitrary subsumption is not.
export function sameValue(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
}

export function schemasCompatible(source, target, depth = 0) {
  if (depth > 100 || !source || !target) return false;
  if (sameValue(source, target)) return true;
  function alternatives(schema) {
    if (Object.keys(schema).length !== 1) return null;
    if (Array.isArray(schema.anyOf)) return schema.anyOf;
    if (Array.isArray(schema.type)) return schema.type.map((type) => ({ type }));
    return null;
  }
  const from = alternatives(source), to = alternatives(target);
  if (from) return from.every((branch) => schemasCompatible(branch, target, depth + 1));
  return !!to?.some((branch) => schemasCompatible(source, branch, depth + 1));
}

export function validReference(reference) {
  return !!reference && typeof reference === "object" && !Array.isArray(reference) &&
    Object.keys(reference).length === 3 && typeof reference.source_id === "string" && !!reference.source_id &&
    typeof reference.package_version === "string" && !!reference.package_version &&
    typeof reference.digest === "string" && /^sha256:[a-f0-9]{64}$/.test(reference.digest);
}

export function compatibleSource(source, hints) {
  const selection = source?.selection;
  return !!selection?.materialized && validReference(selection.reference) &&
    (selection.content_kind === hints.content_kind || hints.content_kind === "path" && ["file", "directory"].includes(selection.content_kind)) &&
    schemasCompatible(selection.native_schema, hints.native_schema);
}

export function referenceMatches(source, reference, hints) {
  return compatibleSource(source, hints) && sameValue(source.selection.reference, reference);
}

export function selectionValues(value, multiple) {
  return value === undefined || value === null ? [] : multiple && Array.isArray(value) ? value : [value];
}

// Walk only actual input fields, resolving local references. Hints' native_schema
// describes payload content and must never be mistaken for another form field.
export function sourceFields(schema, value, root = schema, path = [], depth = 0) {
  if (!schema || typeof schema !== "object" || depth > 100) return [];
  if (schema.$ref?.startsWith("#/")) {
    const resolved = schema.$ref.slice(2).split("/").reduce((node, key) => node?.[key.replaceAll("~1", "/").replaceAll("~0", "~")], root);
    return sourceFields({ ...resolved, ...Object.fromEntries(Object.entries(schema).filter(([key]) => key !== "$ref")) }, value, root, path, depth + 1);
  }
  if (schema["x-input"]?.kind === "data-source") return [{ schema, value, path }];
  const fields = Object.entries(schema.properties || {}).flatMap(([key, child]) => sourceFields(child, value?.[key], root, [...path, key], depth + 1));
  if (Array.isArray(value) && schema.items) fields.push(...value.flatMap((item, index) => sourceFields(schema.items, item, root, [...path, index], depth + 1)));
  for (const key of ["allOf", "anyOf", "oneOf"]) for (const branch of schema[key] || []) fields.push(...sourceFields(branch, value, root, path, depth + 1));
  return fields;
}

// Populate authored defaults only, without synthesizing optional contexts or
// boolean/array values. Native preparation uses the same omission distinction.
export function inputDefaults(schema, value, root = schema, required = false, depth = 0) {
  if (!schema || typeof schema !== "object" || depth > 100) return value;
  if (schema.$ref?.startsWith("#/")) {
    const resolved = schema.$ref.slice(2).split("/").reduce((node, key) => node?.[key.replaceAll("~1", "/").replaceAll("~0", "~")], root);
    return inputDefaults({ ...resolved, ...Object.fromEntries(Object.entries(schema).filter(([key]) => key !== "$ref")) }, value, root, required, depth + 1);
  }
  if (value === undefined && Object.hasOwn(schema, "default")) value = structuredClone(schema.default);
  if (schema["x-input"]?.kind === "data-source" || value === null) return value;
  if (schema.type === "object" || schema.properties) {
    if (value === undefined && !required) return undefined;
    if (value !== undefined && (!value || typeof value !== "object" || Array.isArray(value))) return value;
    const result = { ...value };
    for (const [key, child] of Object.entries(schema.properties || {})) {
      const next = inputDefaults(child, value?.[key], root, schema.required?.includes(key), depth + 1);
      if (next !== undefined) result[key] = next;
    }
    return result;
  }
  if (Array.isArray(value) && schema.items) return value.map((item) => inputDefaults(schema.items, item, root, true, depth + 1));
  return value;
}
