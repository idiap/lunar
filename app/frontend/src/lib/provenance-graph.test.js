// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { catalogResourceId, provenanceGraphModel } from "./provenance-graph.js";

const graph = {
  nodes: [
    { id: "agent:a", kind: "agent" },
    { id: "activity:a", kind: "activity" },
    { id: "entity:a", kind: "entity", attributes: { "lunar:resource_id": "geo" } },
  ],
  edges: [
    { id: "one", source: "agent:a", target: "activity:a", relation: "wasAssociatedWith" },
    { id: "two", source: "activity:a", target: "entity:a", relation: "used" },
  ],
};

test("lays provenance kinds into stable columns and filters relations", () => {
  const all = provenanceGraphModel(graph);
  assert.deepEqual(all.nodes.map((node) => node.x), [70, 400, 730]);
  assert.equal(all.edges.length, 2);
  assert.deepEqual(provenanceGraphModel(graph, "used").edges.map((edge) => edge.id), ["two"]);
});

test("extracts canonical catalog links only from declared attributes", () => {
  assert.equal(catalogResourceId(graph.nodes[2]), "geo");
  assert.equal(catalogResourceId(graph.nodes[1]), null);
});

test("isolates XYFlow internals from legacy provenance SVG styles", () => {
  const page = readFileSync(new URL("../pages/provenance-page.jsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");
  assert.match(page, /<ReactFlowProvider>/);
  assert.match(styles, /\.provenance-flow-canvas \.react-flow/);
  assert.doesNotMatch(styles, /\.provenance-flow-canvas\s+svg/);
});
