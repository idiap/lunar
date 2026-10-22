// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { authoredValues, humanize, mainLabel, parseExample } from "@/lib/prism-viewer";

export function ExampleValue({ value }) {
  if (!value) return null;
  if (value.kind === "string") return <div className="value value-string">{value.value}</div>;
  if (value.kind === "number" || value.kind === "symbol") {
    return <div className={`value value-${value.kind}`}>{value.value}</div>;
  }
  if (value.kind === "list") {
    return (
      <div className="value value-list">
        {value.items.map((item, index) => (
          <div className="value-list-item" key={index}>
            <span className="value-list-number">{String(index + 1).padStart(2, "0")}</span>
            <ExampleValue value={item} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className={`value value-constructor${!value.fields.length && !value.items.length ? " value-enum" : ""}`}>
      <strong className="value-constructor-name">{value.name}</strong>
      {value.fields.map((field) => (
        <div className="value-field" key={field.name}>
          <span className="value-field-label">{humanize(field.name)}</span>
          <ExampleValue value={field.value} />
        </div>
      ))}
      {value.items.map((item, index) => <ExampleValue value={item} key={index} />)}
    </div>
  );
}

export function ExampleCard({ example, direction }) {
  const parsed = parseExample(example.code);
  return (
    <article className={`example-card example-card-${direction}`}>
      <div>
        <strong>{example.label}</strong>
        {parsed && <code>{parsed.type}</code>}
      </div>
      {parsed
        ? <ExampleValue value={parsed.value} />
        : <p className="example-fallback">{String(example.code || "").replace(/\s+/g, " ").trim()}</p>}
    </article>
  );
}

export function ActualValueCard({ example, direction }) {
  return (
    <article className={`example-card example-card-${direction} actual-value-card`}>
      <ExampleValue value={example.value} />
    </article>
  );
}

export function ValueGroup({ title, examples, direction }) {
  return (
    <section className={`actual-value-group actual-value-group-${direction}`}>
      <h4>{title}</h4>
      {examples.length
        ? examples.map((example, index) => <ActualValueCard example={example} direction={direction} key={index} />)
        : <p className="actual-value-empty">No concrete value authored.</p>}
    </section>
  );
}

export function SectionHeading({ kicker, title, as: Element = "div" }) {
  return (
    <Element className="examples-section-heading">
      <span>{kicker}</span>
      <strong>{title}</strong>
    </Element>
  );
}

export function BoundaryValues({ graph, compact = false }) {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const incoming = (node) => graph.edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => byId.get(edge.source))
    .filter(Boolean);
  const inputs = authoredValues(graph.nodes.filter((node) => node.kind === "input"));
  const outputs = authoredValues(graph.nodes.filter((node) => node.kind === "result").flatMap(incoming));
  return (
    <div className={compact ? "tree-workflow-value-flow" : "workflow-value-flow"}>
      <ValueGroup title="Input" examples={inputs} direction="input" />
      <span className={compact ? "tree-workflow-value-arrow" : "workflow-value-arrow"}>→</span>
      <ValueGroup title="Output" examples={outputs} direction="output" />
    </div>
  );
}

export function NodeValues({ graph, node }) {
  const byId = new Map(graph.nodes.map((item) => [item.id, item]));
  const incoming = graph.edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => byId.get(edge.source))
    .filter(Boolean);
  return (
    <div className="file-example-values">
      <ValueGroup title="Input" examples={authoredValues(incoming)} direction="input" />
      <ValueGroup title="Output" examples={authoredValues([node])} direction="output" />
    </div>
  );
}

export function NodeExamples({ graph, node }) {
  const byId = new Map(graph.nodes.map((item) => [item.id, item]));
  const incoming = graph.edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => byId.get(edge.source))
    .filter(Boolean);
  const inputExamples = node.kind === "input" && node.output_example
    ? [{ label: mainLabel(node), code: node.output_example }]
    : incoming.filter((item) => item.output_example).map((item) => ({
      label: mainLabel(item), code: item.output_example,
    }));
  const outputExamples = node.kind === "result"
    ? incoming.filter((item) => item.output_example).map((item) => ({
      label: mainLabel(node), code: item.output_example,
    }))
    : node.output_example ? [{ label: mainLabel(node), code: node.output_example }] : [];
  const section = (label, examples, direction) => (
    <>
      <h4 className={`example-${direction}-label`}>{label}</h4>
      {examples.length
        ? examples.map((example, index) => <ExampleCard example={example} direction={direction} key={index} />)
        : <p className="example-missing">No authored concrete example is provided in sample_outputs.prism.</p>}
    </>
  );
  return (
    <>
      <h3 className="section-title example-title">Concrete examples</h3>
      {section("Input", inputExamples, "input")}
      {section("Output", outputExamples, "output")}
    </>
  );
}
