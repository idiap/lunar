// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
// Presentation hints never narrow the workflow's JSON Schema contract.
export function inputLabel(name = "") {
  const words = name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function inputHints(schema, name = "") {
  const explicit = schema["x-input"] || {};
  let kind = "text";
  if (/(^|_)(path|paths)$/.test(name)) kind = "file";
  else if (/(^|_)digest$/.test(name)) kind = "digest";
  else if (/(^|_)(anchor|anchors)$/.test(name)) kind = "reference";
  else if (/(^|_)(context|scope|criteria|derivation|description|instructions|prompt|goal)$/.test(name)) kind = "textarea";
  return { kind, ...explicit };
}

export function inputAtPath(value, path) {
  return path.reduce((current, key) => current?.[key], value);
}

export function inputSuggestions(schema, path = [], previousInputs = []) {
  const candidates = [
    ...(schema.examples || []).map((value) => ({ value, label: "Example" })),
    ...(schema.default !== undefined ? [{ value: schema.default, label: "Default" }] : []),
    ...previousInputs.map((inputs) => ({ value: inputAtPath(inputs, path), label: "Previous run" })),
  ];
  const seen = new Set();
  return candidates.flatMap(({ value, label }) => (Array.isArray(value) ? value : [value])
    .filter((item) => typeof item === "string" && item.length && !seen.has(item) && seen.add(item))
    .map((item) => ({ value: item, label }))).slice(0, 30);
}

export function friendlyInputErrors(errors) {
  return errors.map((error) => {
    let message = error.message;
    if (error.name === "required") message = `Enter or select ${inputLabel(error.params.missingProperty).toLowerCase()}.`;
    if (error.name === "enum") message = "Choose one of the available values.";
    if (error.name === "minItems") message = `Add at least ${error.params.limit} item${error.params.limit === 1 ? "" : "s"}.`;
    if (error.name === "minLength") message = `Enter at least ${error.params.limit} character${error.params.limit === 1 ? "" : "s"}.`;
    return { ...error, message };
  });
}
