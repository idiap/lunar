// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  complexRole,
  layoutComplexGraph,
  parseExample,
  validatePrismBundle,
} from "./prism-viewer.js";

const registry = JSON.parse(readFileSync(new URL("../../tests/fixtures/prism-assets/registry.json", import.meta.url)));
const publicWorkflowIds = registry.workflows
  .filter((workflow) => workflow.visibility === "public")
  .map((workflow) => workflow.workflow_id)
  .sort();

test("ships only deduplicated public Lunar data", () => {
  const catalog = JSON.parse(readFileSync(new URL("../../tests/fixtures/prism-assets/catalog.json", import.meta.url)));
  assert.equal(catalog.visibility, "public");
  assert.deepEqual(catalog.modules.map((module) => module.id).sort(), publicWorkflowIds);
  assert.ok(catalog.skills.length > 0);
  assert.equal(new Set(catalog.skills.map((skill) => skill.id)).size, catalog.skills.length);
  assert.equal(catalog.skills.some((skill) => skill.sources.some((source) => source.includes("/private/"))), false);
  assert.equal(catalog.skills.some((skill) => skill.sources.some((source) => source.startsWith("/") || source.includes("../"))), false);
});

test("ships parsed Prism data without a standalone viewer HTML file", () => {
  const bundleUrl = new URL("../../tests/fixtures/prism-assets/bundle.json", import.meta.url);
  const viewerUrl = new URL("../../tests/fixtures/prism-assets/viewer.html", import.meta.url);
  const bundle = validatePrismBundle(JSON.parse(readFileSync(bundleUrl)));
  assert.equal(bundle.projects[0].id, "bioagents-public");
  assert.deepEqual(bundle.projects[0].workflows.map((workflow) => workflow.id).sort(), publicWorkflowIds);
  assert.equal(existsSync(viewerUrl), false);
  bundle.projects[0].workflows.forEach((workflow) => {
    const nodesById = new Map(workflow.graph.nodes.map((node) => [node.id, node]));
    const outputNodes = workflow.graph.edges
      .filter((edge) => edge.kind === "return")
      .map((edge) => nodesById.get(edge.source));
    assert.ok(workflow.summary.trim(), `${workflow.id} has no workflow summary`);
    const hasSamples = registry.workflows.find((row) => row.workflow_id === workflow.id).has_samples;
    if (hasSamples) {
      assert.equal(
        workflow.graph.nodes.filter((node) => node.kind === "input").every((node) => node.output_example),
        true,
        `${workflow.id} has no concrete workflow input`,
      );
      assert.equal(
        outputNodes.length > 0 && outputNodes.every((node) => node?.output_example),
        true,
        `${workflow.id} has no concrete workflow output`,
      );
    }
    assert.ok(workflow.sources.length > 0);
    assert.equal(workflow.sources.some((source) => source.file_type === "samples"), hasSamples);
    assert.ok(workflow.graph.nodes.length > 0);
    assert.ok(workflow.graph.edges.length > 0);
  });
});

test("implements all five Prism views as modular React components", () => {
  const page = readFileSync(new URL("../pages/prism-page.jsx", import.meta.url), "utf8");
  const graphComponent = readFileSync(new URL("../components/prism/workflow-graph.jsx", import.meta.url), "utf8");
  for (const component of ["ProjectAtlas", "WorkflowGraph", "PrismFiles", "SlidesView", "InputExamples"]) {
    assert.match(page, new RegExp(`<${component}`));
  }
  for (const tab of ["map", "graph", "files", "slides", "examples"]) {
    assert.match(page, new RegExp(`value: "${tab}"`));
  }
  assert.doesNotMatch(page, /iframe|viewer\.html|contentDocument/);
  assert.doesNotMatch(page, /searchParams\.get\("render"\)|onModeChange/);
  assert.doesNotMatch(graphComponent, /renderer-selector|traditional|onModeChange/);
  assert.match(graphComponent, /import\s*\{[^}]*\breasoningKind\b[^}]*\}\s*from\s*"@\/lib\/prism-viewer"/);
  assert.doesNotMatch(readFileSync(new URL("../components/prism/project-atlas.jsx", import.meta.url), "utf8"), /Isolated/);
});

test("exports the currently selected workflow visualization and provenance package", () => {
  const page = readFileSync(new URL("../pages/prism-page.jsx", import.meta.url), "utf8");
  assert.match(page, /versions\/\$\{encodeURIComponent\(versionId\)\}\/workflows\/\$\{encodeURIComponent\(current\.workflow\.id\)\}\/export/);
  assert.match(page, /<Download[^>]*\/>Export workflow/);
});

test("keeps the graph details dialog centered in the viewport", () => {
  const styles = readFileSync(new URL("../styles/prism-viewer.css", import.meta.url), "utf8");
  const dialog = readFileSync(new URL("../components/prism/graph-details-dialog.jsx", import.meta.url), "utf8");
  assert.match(
    styles,
    /\.graph-details-dialog\.dialog-content \{[^}]*position: fixed;[^}]*inset: 0;[^}]*margin: auto;[^}]*transform: none;/,
  );
  assert.match(styles, /\.graph-details-dialog \.page-tabs-header \{[^}]*padding: 12px 54px 4px 14px;/);
  assert.doesNotMatch(dialog, /evidence-note|Derived from successful Prism/);
  assert.doesNotMatch(styles, /\.graph-details-dialog \.evidence-note/);
});

test("keeps gradients and colorful left accent stripes out of example cards", () => {
  const styles = readFileSync(new URL("../styles/prism-viewer.css", import.meta.url), "utf8");
  assert.doesNotMatch(styles, /\.graph-details-dialog[^{}]*\{[^}]*border-left:/);
  assert.doesNotMatch(styles, /\.prism-workbench \.example-card[^{}]*\{[^}]*border-left:/);
  assert.doesNotMatch(styles, /\.graph-details-dialog \.source-line\.active \{[^}]*box-shadow:/);
  assert.match(styles, /\.prism-workbench \.example-card,\s*\.graph-details-dialog \.example-card \{[^}]*background: var\(--pv-panel\);/);
});

test("flattens nested value cards in the Prism workbench", () => {
  const styles = readFileSync(new URL("../styles/prism-viewer.css", import.meta.url), "utf8");
  assert.match(
    styles,
    /\.prism-workbench \.actual-value-card \{[^}]*border: 0;[^}]*border-radius: 0;[^}]*background: transparent;[^}]*box-shadow: none;/,
  );
});

test("keeps component values hierarchical without nested card chrome", () => {
  const styles = readFileSync(new URL("../styles/prism-viewer.css", import.meta.url), "utf8");
  assert.match(styles, /\.prism-workbench \.component-value-grid \{[^}]*gap: 0;/);
  assert.match(
    styles,
    /\.prism-workbench \.component-value-card \{[^}]*border: 0;[^}]*border-bottom: 1px solid var\(--pv-line\);[^}]*border-radius: 0;[^}]*background: transparent;/,
  );
  assert.match(styles, /\.prism-workbench \.component-value-body \{[^}]*padding: 16px 14px 16px 53px;/);
});

test("links graph detail skill cards to their catalog pages", () => {
  const dialog = readFileSync(new URL("../components/prism/graph-details-dialog.jsx", import.meta.url), "utf8");
  assert.match(dialog, /<Link[\s\S]*className="skill"[\s\S]*to=\{`\/skills\/\$\{encodeURIComponent\(skill\.name\)\}`\}/);
  assert.doesNotMatch(dialog, /<div className="skill"/);
});

test("reuses the project page tabs in the Prism page and graph details dialog", () => {
  const pageTabs = readFileSync(new URL("../components/page-tabs.jsx", import.meta.url), "utf8");
  const page = readFileSync(new URL("../pages/prism-page.jsx", import.meta.url), "utf8");
  const dialog = readFileSync(new URL("../components/prism/graph-details-dialog.jsx", import.meta.url), "utf8");
  assert.match(pageTabs, /<TabsList variant="line"/);
  assert.match(page, /<PageTabs/);
  assert.match(dialog, /<PageTabs/);
  assert.doesNotMatch(dialog, /graph-details-tab/);
});

test("lays out nodes and edges dynamically for branches and cycles", () => {
  const graph = {
    nodes: [
      { id: "input", kind: "input", output_type: "Request" },
      { id: "left", kind: "occurrence", method: "DeductiveLeft", output_type: "Generated[Left]" },
      { id: "right", kind: "occurrence", method: "EvidentialRight", output_type: "Generated[Right]" },
      { id: "join", kind: "occurrence", method: "ValidateJoin", output_type: "Generated[Answer]", certificate: "Accepted[Answer]" },
      { id: "result", kind: "result" },
    ],
    edges: [
      { source: "input", target: "left", kind: "dependency" },
      { source: "input", target: "right", kind: "dependency" },
      { source: "left", target: "join", kind: "dependency" },
      { source: "right", target: "join", kind: "dependency" },
      { source: "join", target: "result", kind: "return" },
    ],
    input: [{ name: "input", type: "Request" }],
    output: "Answer",
    reasoning: "ArbitraryReasoning",
    topology: "parallel",
  };
  const workflow = { id: "arbitrary", graph, source_text: "reasoning ArbitraryReasoning:\n" };
  const complex = layoutComplexGraph(workflow);
  assert.equal(complex.nodes.length, graph.nodes.length);
  assert.deepEqual(complex.edges.map(({ source, target }) => [source, target]), graph.edges.map(({ source, target }) => [source, target]));
  assert.equal(graph.nodes.every((node) => complex.nodes.some((item) => item.id === node.id)), true);
  assert.notEqual(complex.nodes.find((node) => node.id === "left").position.y, complex.nodes.find((node) => node.id === "right").position.y);

  const cyclic = {
    ...graph,
    nodes: graph.nodes.slice(0, 3),
    edges: [
      { source: "input", target: "left", kind: "dependency" },
      { source: "left", target: "right", kind: "dependency" },
      { source: "right", target: "left", kind: "dependency" },
    ],
  };
  assert.equal(layoutComplexGraph({ ...workflow, graph: cyclic }).nodes.every((node) => Number.isFinite(node.position.x) && Number.isFinite(node.position.y)), true);
});

test("every generated module produces a complete React Flow model", () => {
  const bundle = validatePrismBundle(JSON.parse(readFileSync(new URL("../../tests/fixtures/prism-assets/bundle.json", import.meta.url))));
  bundle.projects.flatMap((project) => project.workflows).forEach((workflow) => {
    const complex = layoutComplexGraph(workflow);
    assert.equal(workflow.graph.nodes.every((node) => complex.nodes.some((item) => item.id === node.id)), true);
    assert.ok(complex.edges.length >= workflow.graph.edges.length);
    const visibleNodes = complex.nodes.filter((node) => node.data.role !== "module");
    const nodeBounds = [];
    for (let leftIndex = 0; leftIndex < visibleNodes.length; leftIndex += 1) {
      const left = visibleNodes[leftIndex];
      const leftWidth = left.style?.width || left.width;
      const leftHeight = left.style?.height || left.height;
      nodeBounds.push({
        id: left.id,
        left: left.position.x,
        right: left.position.x + leftWidth,
        top: left.position.y,
        bottom: left.position.y + leftHeight,
      });
      for (let rightIndex = leftIndex + 1; rightIndex < visibleNodes.length; rightIndex += 1) {
        const right = visibleNodes[rightIndex];
        const rightWidth = right.style?.width || right.width;
        const rightHeight = right.style?.height || right.height;
        const overlapX = left.position.x < right.position.x + rightWidth && left.position.x + leftWidth > right.position.x;
        const overlapY = left.position.y < right.position.y + rightHeight && left.position.y + leftHeight > right.position.y;
        assert.equal(overlapX && overlapY, false, `${workflow.id}: ${left.id} overlaps ${right.id}`);
      }
    }
    const labelBounds = [];
    complex.edges.forEach((edge) => {
      const position = edge.data.labelPosition;
      assert.ok(position, `${workflow.id}: ${edge.id} has no label placement`);
      const lines = String(edge.data.label).split("\n");
      const width = Math.min(180, Math.max(...lines.map((line) => line.length)) * 7 + 10);
      const height = lines.length * 15 + 6;
      const radians = position.angle * (Math.PI / 180);
      const rotatedWidth = Math.abs(width * Math.cos(radians)) + Math.abs(height * Math.sin(radians));
      const rotatedHeight = Math.abs(width * Math.sin(radians)) + Math.abs(height * Math.cos(radians));
      const bounds = {
        id: edge.id,
        left: position.x - rotatedWidth / 2,
        right: position.x + rotatedWidth / 2,
        top: position.y - rotatedHeight / 2,
        bottom: position.y + rotatedHeight / 2,
      };
      const overlaps = (other) => bounds.left < other.right + 4 && bounds.right > other.left - 4
        && bounds.top < other.bottom + 4 && bounds.bottom > other.top - 4;
      assert.equal(nodeBounds.some(overlaps), false, `${workflow.id}: label ${edge.id} overlaps a node`);
      assert.equal(labelBounds.some(overlaps), false, `${workflow.id}: label ${edge.id} overlaps another label`);
      labelBounds.push(bounds);
    });
  });
});

test("styles source node kinds without inferring semantics from names", () => {
  assert.equal(complexRole({ kind: "occurrence", method: "FormDrugTargetHypothesis", output_type: "Generated[DrugRepurposingCoherenceHypothesis]" }), "process");
  assert.equal(complexRole({ kind: "occurrence", method: "CalibrateClaimStatus", output_type: "Generated[ClaimStatus]" }), "process");
});

test("parses authored Prism constructor values", () => {
  assert.deepEqual(parseExample('request: Request = Request(name = "sample", flags = [Ready, 2])'), {
    binding: "request",
    type: "Request",
    value: {
      kind: "constructor",
      name: "Request",
      fields: [
        { name: "name", value: { kind: "string", value: "sample" } },
        {
          name: "flags",
          value: {
            kind: "list",
            items: [{ kind: "symbol", value: "Ready" }, { kind: "number", value: "2" }],
          },
        },
      ],
      items: [],
    },
  });
});

test("keeps the Prism tabs content-sized and the graph controls positioned", () => {
  const styles = readFileSync(new URL("../styles/prism-viewer.css", import.meta.url), "utf8");
  const graph = readFileSync(new URL("../components/prism/workflow-graph.jsx", import.meta.url), "utf8");
  assert.match(styles, /\.page-tabs-list \{[^}]*display: inline-flex;[^}]*width: fit-content;[^}]*justify-content: flex-start;/);
  assert.match(styles, /\.page-tab \{[^}]*min-width: 0;[^}]*flex: 0 0 auto;/);
  assert.match(styles, /\.graph-shell \{[^}]*height: clamp\(560px, 26vw, 820px\);/);
  assert.match(styles, /\.graph-search \{[^}]*position: absolute;[^}]*top: 14px;[^}]*left: 14px;/);
  assert.match(styles, /\.graph-search \.input \{[^}]*padding: 8px 11px 8px 38px;/);
  assert.match(graph, /<Searchbar[\s\S]*className="graph-search"[\s\S]*label="Search graph"/);
  assert.doesNotMatch(styles, /renderer-selector|graph-renderer-control|workflow-graph-node/);
  assert.match(styles, /\.complex-legend \{[^}]*bottom: 14px;[^}]*left: 14px;/);
  assert.match(styles, /\.system-node-shape \{[^}]*position: absolute;/);
  assert.match(styles, /--pv-input: #087f75;/);
  assert.match(styles, /--pv-result: #b35c00;/);
  assert.match(styles, /\.tree-workflow-values \.actual-value-card \{[^}]*box-shadow: none;/);
});
