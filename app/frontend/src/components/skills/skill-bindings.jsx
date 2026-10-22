// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Card } from "@/components/ui/card";
import "./skill-bindings.css";

function typeLabel(schema = {}) {
  if (schema["x-native-type"]) return schema["x-native-type"];
  if (schema.type === "array") return `${typeLabel(schema.items)}[]`;
  if (schema.anyOf) return schema.anyOf.map(typeLabel).join(" | ");
  return Array.isArray(schema.type) ? schema.type.join(" | ") : schema.type || schema.$ref || "value";
}

export function SkillBindings({ invocation }) {
  const bindings = invocation?.bindings;
  if (invocation?.kind !== "prism" || !Array.isArray(bindings) || !bindings.length) return null;
  return <Card className="skill-bindings">
    <h2>Typed bindings</h2>
    {bindings.map((binding) => <section key={binding.id} aria-label={`Binding ${binding.id}`}>
      <h3>{binding.id}</h3>
      <p>{binding.execution_status === "contract_only" ? "Contract only · execution has not been recorded." : `Execution status: ${binding.execution_status || "not recorded"}`}</p>
      <dl>
        <div><dt>Input type</dt><dd><code>{binding.task_type}</code></dd></div>
        <div><dt>Result type</dt><dd><code>{binding.result_type}</code></dd></div>
      </dl>
      <div className="skill-binding-table"><table>
        <caption>Inputs for {binding.id}</caption>
        <thead><tr><th>Name</th><th>Kind</th><th>Type</th><th>Required</th></tr></thead>
        <tbody>{Object.entries(binding.input_schema?.properties || {}).map(([name, schema]) => {
          const hint = schema["x-input"];
          const source = hint?.kind === "data-source";
          return <tr key={name}>
            <th scope="row">{name}</th>
            <td>{source ? `${hint.multiple ? "Ordered sources" : "Source"} (${hint.content_kind})` : "Configuration"}</td>
            <td><code>{typeLabel(source ? hint.native_schema : schema)}</code></td>
            <td>{binding.input_schema.required?.includes(name) ? "Yes" : "No"}</td>
          </tr>;
        })}</tbody>
      </table></div>
      {!!Object.keys(binding.workflow_uses || {}).length && <p>Workflow uses: {Object.entries(binding.workflow_uses).map(([workflow, hooks]) => `${workflow} (${hooks.join(", ")})`).join("; ")}</p>}
      {!!Object.keys(binding.operation_uses || {}).length && <p>Operation uses: {Object.entries(binding.operation_uses).map(([workflow, operations]) => `${workflow} (${operations.join(", ")})`).join("; ")}</p>}
      <details><summary>Contract details</summary>
        <p><code>{binding.module}:{binding.export}</code></p>
        <p>Callable: <code>{binding.callable_type}</code></p>
        <h4>Input schema</h4><pre>{JSON.stringify(binding.input_schema, null, 2)}</pre>
        <h4>Result schema</h4><pre>{JSON.stringify(binding.result_schema, null, 2)}</pre>
      </details>
    </section>)}
  </Card>;
}
