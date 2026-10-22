// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export const PROVENANCE_RELATIONS = [
  "used", "wasGeneratedBy", "wasAssociatedWith", "wasDerivedFrom", "specializationOf",
];

export function provenanceGraphModel(graph, relation = "all") {
  const columns = { agent: 0, activity: 1, entity: 2 };
  const seen = { agent: 0, activity: 0, entity: 0 };
  const nodes = (graph?.nodes || []).map((node) => {
    const kind = columns[node.kind] === undefined ? "entity" : node.kind;
    const index = seen[kind]++;
    return { ...node, x: 70 + columns[kind] * 330, y: 65 + index * 105 };
  });
  const allowed = new Set(nodes.map((node) => node.id));
  const edges = (graph?.edges || []).filter((edge) => (
    allowed.has(edge.source)
    && allowed.has(edge.target)
    && (relation === "all" || edge.relation === relation)
  ));
  return {
    nodes,
    edges,
    width: 860,
    height: Math.max(380, 130 + Math.max(...Object.values(seen)) * 105),
  };
}

export function catalogResourceId(node) {
  return node?.attributes?.["lunar:resource_id"] || null;
}
