// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { mainLabel } from "@/lib/prism-viewer";
import { BoundaryValues, NodeValues, SectionHeading } from "./prism-values";

export function InputExamples({ workflow }) {
  const graph = workflow.graph;
  const steps = graph.nodes.filter((node) => node.kind === "occurrence");
  return (
    <section className="examples-panel" role="tabpanel" aria-labelledby="examples-tab">
      <div className="examples-heading">
        <p className="eyebrow">CONCRETE VALUES</p>
        <h2>{workflow.label} values</h2>
        <p>Follow the authored values from the workflow boundary through every component.</p>
      </div>
      <div className="examples-content">
        <details className="workflow-values">
          <SectionHeading as="summary" kicker="Workflow level" title="Boundary values" />
          <BoundaryValues graph={graph} />
        </details>
        <section className="component-values">
          <SectionHeading kicker="Component level" title="Values at every reasoning step" />
          <div className="component-value-grid">
            {steps.map((node, index) => (
              <details className="component-value-card" key={node.id}>
                <summary>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <h3>{mainLabel(node)}</h3>
                </summary>
                <div className="component-value-body"><NodeValues graph={graph} node={node} /></div>
              </details>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
