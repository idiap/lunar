// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
const KEYWORD_KINDS = new Map([
  ...["reasoning", "type", "relation", "agent", "workflow", "def"].map((word) => [word, "declaration"]),
  ...["from", "import", "as", "return", "by", "if", "else", "match", "case", "for", "in", "fails", "skills"].map((word) => [word, "keyword"]),
  ...["group", "sequence", "parallel", "choice", "repeat"].map((word) => [word, "topology"]),
  ...["true", "false", "null", "none", "None", "Some"].map((word) => [word, "literal"]),
]);

const COMPLEX_RANK_GAP = 500;
const COMPLEX_LANE_GAP = 280;
const COMPLEX_LANE_ORIGIN_Y = 250;

export function validatePrismBundle(payload) {
  if (
    !payload
    || payload.kind !== "prism-viewer-bundle"
    || payload.schema_version !== 1
    || !Array.isArray(payload.projects)
  ) {
    throw new Error("The Prism workflow bundle has an unsupported format");
  }
  for (const project of payload.projects) {
    if (!project.id || !Array.isArray(project.workflows) || !project.workflows.length) {
      throw new Error("The Prism workflow bundle contains an invalid project");
    }
    for (const workflow of project.workflows) {
      const graph = workflow.graph;
      if (workflow.scope === "executable-workflow" || graph?.scope === "executable-workflow") {
        throw new Error("Workflow views must represent PRISM reasoning blocks");
      }
      if (!workflow.id || !graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
        throw new Error("The Prism workflow bundle contains an invalid workflow");
      }
      const nodeIds = new Set(graph.nodes.map((node) => node.id));
      if (nodeIds.size !== graph.nodes.length || nodeIds.has(undefined)) {
        throw new Error("The Prism workflow bundle contains invalid graph nodes");
      }
      if (graph.edges.some((edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target))) {
        throw new Error("The Prism workflow bundle contains an invalid graph edge");
      }
    }
  }
  return payload;
}

export function reasoningOptions(project) {
  const names = new Map();
  project.workflows.forEach((item) => {
    const name = item.label || item.id;
    names.set(name, (names.get(name) || 0) + 1);
  });
  return project.workflows.map((item) => {
    const name = item.label || item.id;
    return { value: item.id, label: names.get(name) > 1 ? `${name} · ${item.source}` : name };
  });
}

export function humanize(value) {
  return String(value || "").replace(/[-_]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function splitCamelCase(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim();
}

export function workflowCommentary(source, reasoning) {
  const lines = String(source || "").split("\n");
  const declaration = lines.findIndex((line) => line.trimStart().startsWith(`reasoning ${reasoning}`));
  const collectAbove = (start) => {
    const comments = [];
    for (let index = start; index >= 0; index -= 1) {
      const line = lines[index].trim();
      if (!line.startsWith("#")) break;
      comments.push(line.slice(1).trimStart());
    }
    return comments.reverse().join("\n");
  };
  const adjacent = declaration > 0 ? collectAbove(declaration - 1) : "";
  if (adjacent) return adjacent;
  const leading = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("#")) break;
    leading.push(trimmed.slice(1).trimStart());
  }
  return leading.join("\n");
}

export function reasoningKind(node) {
  if (node.kind !== "occurrence") return node.kind;
  const prefixes = ["abductive", "analogical", "contrastive", "deductive", "evidential", "inductive", "refutational", "unresolved"];
  const lower = String(node.method || "").toLowerCase();
  return prefixes.find((prefix) => lower.startsWith(prefix))
    || (lower.startsWith("modelbased") ? "model-based" : "reasoning");
}

export function mainLabel(node) {
  if (!node) return "Unknown";
  if (node.kind === "occurrence") return splitCamelCase(node.method || humanize(node.id));
  if (node.kind === "input") return splitCamelCase(node.output_type || humanize(node.id));
  return node.label || (node.kind === "result" ? "Workflow Result" : node.id);
}

export function compactType(value) {
  const text = String(value || "");
  const generated = text.match(/^Generated\[(.+)]$/);
  return splitCamelCase(generated ? generated[1] : text)
    .replace(/\s*\[\s*/g, " · ")
    .replace(/]$/g, "");
}

function complexEdgeLabel(value, lineLimit = 24, totalLimit = 54) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= lineLimit) return text;
  const display = text.length <= totalLimit ? text : `${text.slice(0, totalLimit - 1).trimEnd()}…`;
  const words = display.split(" ");
  if (words.length === 1) {
    const middle = Math.ceil(display.length / 2);
    return `${display.slice(0, middle)}\n${display.slice(middle)}`;
  }
  let splitAt = 1;
  let smallestDifference = Infinity;
  for (let index = 1; index < words.length; index += 1) {
    const firstLength = words.slice(0, index).join(" ").length;
    const secondLength = words.slice(index).join(" ").length;
    const difference = Math.abs(firstLength - secondLength);
    if (difference < smallestDifference) {
      smallestDifference = difference;
      splitAt = index;
    }
  }
  return `${words.slice(0, splitAt).join(" ")}\n${words.slice(splitAt).join(" ")}`;
}

export function edgeKey(edge) {
  return `${edge.source}:${edge.kind}:${edge.target}`;
}

export function edgeValueType(edge, nodesById) {
  const source = nodesById.get(edge.source);
  return source?.output_type || edge.label || "Dependency";
}

export function searchable(node) {
  return [
    node.id,
    node.kind,
    node.label,
    node.method,
    node.input_type,
    node.output_type,
    node.relation,
    node.certificate,
    node.commentary,
    ...(node.skills || []).flatMap((skill) => [skill.path, skill.name, skill.role, skill.contribution]),
  ].join(" ").toLowerCase();
}

function topologicalRanks(nodes, edges, spreadCycles = false) {
  const indegree = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, []]));
  for (const edge of edges) {
    if (!indegree.has(edge.source) || !indegree.has(edge.target) || edge.source === edge.target) continue;
    indegree.set(edge.target, indegree.get(edge.target) + 1);
    outgoing.get(edge.source).push(edge.target);
  }
  const queue = nodes.filter((node) => indegree.get(node.id) === 0).map((node) => node.id);
  const ranks = new Map(queue.map((id) => [id, 0]));
  const visited = new Set();
  while (queue.length) {
    const id = queue.shift();
    visited.add(id);
    for (const target of outgoing.get(id)) {
      ranks.set(target, Math.max(ranks.get(target) || 0, (ranks.get(id) || 0) + 1));
      indegree.set(target, indegree.get(target) - 1);
      if (indegree.get(target) === 0) queue.push(target);
    }
  }
  let residualRank = Math.max(0, ...ranks.values()) + 1;
  nodes.filter((node) => !visited.has(node.id)).forEach((node) => {
    ranks.set(node.id, residualRank);
    if (spreadCycles) residualRank += 1;
  });
  return ranks;
}

export function complexRole(node) {
  if (node.kind === "topology" && node.topology_kind === "parallel") {
    if (node.topology_role === "join") return "aggregate";
    if (node.topology_role === "fork") return "parallel-fork";
  }
  if (node.kind === "input" || node.kind === "result") return node.kind;
  return node.kind === "topology" ? "controller" : "process";
}

function complexTopologyLayout(graph) {
  const nodeOrder = new Map(graph.nodes.map((node, index) => [node.id, index]));
  const rankMap = topologicalRanks(graph.nodes, graph.edges.filter((edge) => edge.kind !== "repeat"), true);
  const incoming = new Map(graph.nodes.map((node) => [node.id, []]));
  const outgoing = new Map(graph.nodes.map((node) => [node.id, []]));
  graph.edges.forEach((edge) => {
    if (edge.source === edge.target) return;
    incoming.get(edge.target)?.push(edge.source);
    outgoing.get(edge.source)?.push(edge.target);
  });
  const columns = new Map();
  graph.nodes.forEach((node) => {
    const rank = rankMap.get(node.id) || 0;
    if (!columns.has(rank)) columns.set(rank, []);
    columns.get(rank).push(node);
  });
  const orderedColumns = [...columns.entries()].sort((left, right) => left[0] - right[0]);
  const laneCount = Math.max(orderedColumns.length >= 12 ? 3 : 2, ...orderedColumns.map(([, column]) => column.length));
  const laneByNode = new Map();
  const positions = new Map();
  const alternatingLanes = [];
  for (let inset = 0; alternatingLanes.length < laneCount; inset += 1) {
    const upper = inset;
    const lower = laneCount - inset - 1;
    if (upper <= lower) alternatingLanes.push(upper);
    if (lower !== upper && alternatingLanes.length < laneCount) alternatingLanes.push(lower);
  }
  const predecessorCenter = (node) => {
    const lanes = (incoming.get(node.id) || []).map((id) => laneByNode.get(id)).filter(Number.isFinite);
    return lanes.length ? lanes.reduce((sum, lane) => sum + lane, 0) / lanes.length : undefined;
  };
  orderedColumns.forEach(([, column], stageIndex) => {
    if (column.length > 1) {
      column.sort((left, right) => {
        const leftCenter = predecessorCenter(left);
        const rightCenter = predecessorCenter(right);
        return (leftCenter ?? laneCount / 2) - (rightCenter ?? laneCount / 2)
          || nodeOrder.get(left.id) - nodeOrder.get(right.id);
      });
      column.forEach((node, index) => laneByNode.set(node.id, Math.round(index * (laneCount - 1) / (column.length - 1))));
    } else {
      const node = column[0];
      const predecessors = incoming.get(node.id) || [];
      const center = predecessorCenter(node);
      let lane;
      if (predecessors.length > 1 && Number.isFinite(center)) lane = center;
      else if (predecessors.length === 1) {
        const predecessor = predecessors[0];
        const predecessorColumn = columns.get(rankMap.get(predecessor)) || [];
        if (predecessorColumn.length > 1 || (outgoing.get(predecessor) || []).length > 1) {
          lane = laneByNode.get(predecessor);
        } else {
          lane = alternatingLanes[stageIndex % alternatingLanes.length];
          if (lane === laneByNode.get(predecessor)) lane = alternatingLanes[(stageIndex + 1) % alternatingLanes.length];
        }
      } else lane = alternatingLanes[stageIndex % alternatingLanes.length];
      laneByNode.set(node.id, Math.max(0, Math.min(laneCount - 1, lane ?? 0)));
    }
    column.forEach((node) => positions.set(node.id, {
      x: 160 + stageIndex * COMPLEX_RANK_GAP,
      y: COMPLEX_LANE_ORIGIN_Y + laneByNode.get(node.id) * COMPLEX_LANE_GAP,
    }));
  });
  return { positions, rankMap, laneByNode, laneCount, laneOriginY: COMPLEX_LANE_ORIGIN_Y, incoming, outgoing };
}

function systemNodeSize(role) {
  if (role === "parallel-fork") return { width: 1, height: 1 };
  if (role === "aggregate") return { width: 54, height: 54 };
  if (role === "criterion-note") return { width: 150, height: 86 };
  if (role === "iteration") return { width: 210, height: 66 };
  if (role === "evaluation") return { width: 230, height: 104 };
  return { width: 205, height: 76 };
}

function placeComplexEdgeLabels(nodes, edges) {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const boxes = nodes.filter((node) => node.data.role !== "module").map((node) => {
    const width = node.style?.width || node.width;
    const height = node.style?.height || node.height;
    return { left: node.position.x, top: node.position.y, right: node.position.x + width, bottom: node.position.y + height };
  });
  const placed = [];
  const overlaps = (left, right, padding = 5) => left.left < right.right + padding
    && left.right > right.left - padding
    && left.top < right.bottom + padding
    && left.bottom > right.top - padding;
  const labelBox = (label, x, y, angle) => {
    const lines = String(label || "").split("\n");
    const width = Math.min(180, Math.max(...lines.map((line) => line.length)) * 7 + 10);
    const height = lines.length * 15 + 6;
    const radians = angle * (Math.PI / 180);
    const rotatedWidth = Math.abs(width * Math.cos(radians)) + Math.abs(height * Math.sin(radians));
    const rotatedHeight = Math.abs(width * Math.sin(radians)) + Math.abs(height * Math.cos(radians));
    return { left: x - rotatedWidth / 2, right: x + rotatedWidth / 2, top: y - rotatedHeight / 2, bottom: y + rotatedHeight / 2 };
  };

  return edges.map((edge) => {
    if (!edge.data.label) return edge;
    const source = nodesById.get(edge.source);
    const target = nodesById.get(edge.target);
    if (!source || !target) return edge;
    const sourceWidth = source.style?.width || source.width;
    const sourceHeight = source.style?.height || source.height;
    const targetWidth = target.style?.width || target.width;
    const targetHeight = target.style?.height || target.height;
    const vertical = edge.data.role === "criterion";
    const sourceInset = source.data.role === "synthesis" ? sourceWidth * 0.14 : 0;
    const targetInset = target.data.role === "synthesis" ? targetWidth * 0.14 : 0;
    const sourceX = vertical ? source.position.x + sourceWidth / 2 : source.position.x + sourceWidth - sourceInset;
    const sourceY = vertical ? source.position.y : source.position.y + sourceHeight / 2;
    const targetX = vertical ? target.position.x + targetWidth / 2 : target.position.x + targetInset;
    const targetY = vertical ? target.position.y + targetHeight : target.position.y + targetHeight / 2;
    let x;
    let y;
    let pathAngle;
    if (edge.source === edge.target) {
      x = sourceX;
      y = sourceY - 92;
      pathAngle = 0;
    } else if (edge.data.routeOffset) {
      const deltaX = targetX - sourceX;
      const deltaY = targetY - sourceY;
      const control1 = { x: sourceX + deltaX * 0.3, y: sourceY + deltaY * 0.18 + edge.data.routeOffset };
      const control2 = { x: sourceX + deltaX * 0.7, y: sourceY + deltaY * 0.82 + edge.data.routeOffset };
      x = (sourceX + 3 * control1.x + 3 * control2.x + targetX) / 8;
      y = (sourceY + 3 * control1.y + 3 * control2.y + targetY) / 8;
      pathAngle = Math.atan2(control2.y - control1.y, control2.x - control1.x) * (180 / Math.PI);
    } else {
      const progress = edge.data.labelProgress || 0.5;
      x = sourceX + (targetX - sourceX) * progress;
      y = sourceY + (targetY - sourceY) * progress;
      pathAngle = Math.atan2(targetY - sourceY, targetX - sourceX) * (180 / Math.PI);
    }
    const pathRadians = pathAngle * (Math.PI / 180);
    const baseOffset = edge.data.labelOffset || 0;
    x -= Math.sin(pathRadians) * baseOffset;
    y += Math.cos(pathRadians) * baseOffset;
    const readableAngle = pathAngle > 90 ? pathAngle - 180 : pathAngle < -90 ? pathAngle + 180 : pathAngle;
    const angle = vertical ? readableAngle : Math.max(-42, Math.min(42, readableAngle));
    const tangent = { x: Math.cos(pathRadians), y: Math.sin(pathRadians) };
    const normal = { x: -tangent.y, y: tangent.x };
    const shifts = [[0, 0], [-58, 0], [58, 0]];
    for (const away of [-42, 42, -84, 84, -126, 126, -168, 168]) {
      shifts.push([0, away], [-58, away], [58, away], [-116, away], [116, away]);
    }
    let position = { x, y, angle };
    let shift = { along: 0, away: 0 };
    let box = labelBox(edge.data.label, x, y, angle);
    for (const [along, away] of shifts) {
      const candidate = {
        x: x + tangent.x * along + normal.x * away,
        y: y + tangent.y * along + normal.y * away,
        angle,
      };
      const candidateBox = labelBox(edge.data.label, candidate.x, candidate.y, angle);
      if (!boxes.some((nodeBox) => overlaps(candidateBox, nodeBox)) && !placed.some((label) => overlaps(candidateBox, label))) {
        position = candidate;
        shift = { along, away };
        box = candidateBox;
        break;
      }
    }
    placed.push(box);
    return { ...edge, data: { ...edge.data, labelPosition: position, labelShift: shift } };
  });
}

export function layoutComplexGraph(workflow) {
  const graph = workflow.graph;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const topology = complexTopologyLayout(graph);
  const { positions, rankMap, laneByNode, laneCount } = topology;
  const resultNodes = graph.nodes.map((node) => {
    const role = complexRole(node);
    const size = systemNodeSize(role);
    const center = positions.get(node.id);
    return {
      id: node.id,
      type: "systemNode",
      position: { x: center.x - size.width / 2, y: center.y - size.height / 2 },
      width: size.width,
      height: size.height,
      style: size,
      data: { label: role === "aggregate" ? "Σ" : role === "parallel-fork" ? "" : mainLabel(node), role, node, family: reasoningKind(node) },
    };
  });
  // Frames are presentation for explicit source blocks, never inferred from
  // reachability or names. The source fork/join IDs and all edges stay intact.
  const renderedById = new Map(resultNodes.map((node) => [node.id, node]));
  const frames = new Map();
  const parallels = graph.nodes.filter((node) => node.topology_kind === "parallel"
    && node.topology_role === "fork" && Array.isArray(node.members));
  const bounds = (node) => ({
    left: node.position.x, top: node.position.y,
    right: node.position.x + node.style.width, bottom: node.position.y + node.style.height,
  });
  [...parallels].sort((a, b) => a.members.length - b.members.length).forEach((parallel) => {
    const boxes = parallel.members.flatMap((id) => {
      const member = renderedById.get(id);
      return member ? [bounds(member), ...(frames.has(id) ? [bounds(frames.get(id))] : [])] : [];
    });
    if (!boxes.length) return;
    const left = Math.min(...boxes.map((box) => box.left)) - 32;
    const top = Math.min(...boxes.map((box) => box.top)) - 52;
    const right = Math.max(...boxes.map((box) => box.right)) + 32;
    const bottom = Math.max(...boxes.map((box) => box.bottom)) + 32;
    frames.set(parallel.id, {
      id: `module:${parallel.id}`,
      type: "systemNode",
      position: { x: left, y: top },
      style: { width: right - left, height: bottom - top },
      data: {
        label: `Convergent module ${parallels.indexOf(parallel) + 1}`,
        role: "module", node: parallel, members: parallel.members,
      },
      draggable: false, selectable: false, connectable: false,
      zIndex: -1,
    });
  });
  resultNodes.unshift(...parallels.map((node) => frames.get(node.id)).filter(Boolean));
  const resultEdges = [];
  const edgeBands = new Map();
  graph.edges.forEach((edge) => {
    const band = `${rankMap.get(edge.source) || 0}:${rankMap.get(edge.target) || 0}`;
    if (!edgeBands.has(band)) edgeBands.set(band, []);
    edgeBands.get(band).push(edge);
  });
  graph.edges.forEach((edge, index) => {
    const sourceRole = complexRole(nodesById.get(edge.source));
    const targetRole = complexRole(nodesById.get(edge.target));
    const joining = targetRole === "aggregate" && edge.kind === "control";
    const integrated = sourceRole === "aggregate" && edge.kind === "control";
    const parallelFlow = sourceRole === "parallel-fork" || targetRole === "parallel-fork";
    const band = `${rankMap.get(edge.source) || 0}:${rankMap.get(edge.target) || 0}`;
    const peers = edgeBands.get(band) || [edge];
    const peerIndex = peers.indexOf(edge);
    const labelOffset = (peerIndex - (peers.length - 1) / 2) * 46 - 14;
    const rankSpan = Math.abs((rankMap.get(edge.target) || 0) - (rankMap.get(edge.source) || 0));
    const sourceLane = laneByNode.get(edge.source) || 0;
    const targetLane = laneByNode.get(edge.target) || 0;
    const routeDirection = (sourceLane + targetLane) / 2 <= (laneCount - 1) / 2 ? -1 : 1;
    const routeOffset = rankSpan > 1
      ? routeDirection * (170 + Math.min(135, Math.max(0, rankSpan - 2) * 45) + (peerIndex % 3) * 42)
      : 0;
    const labelProgress = rankSpan <= 1 && peers.length > 1
      ? 0.28 + peerIndex * (0.44 / (peers.length - 1))
      : undefined;
    resultEdges.push({
      id: `flow:${index}:${edgeKey(edge)}`,
      source: edge.source,
      target: edge.target,
      sourceHandle: "right-source",
      targetHandle: "left-target",
      type: "prismEdge",
      data: {
        edge,
        label: complexEdgeLabel(integrated ? "integrated signal" : joining
          ? compactType(nodesById.get(edge.source)?.output_type) || "branch complete"
          : parallelFlow ? "" : edge.kind === "data" || edge.kind === "return"
            ? compactType(edgeValueType(edge, nodesById)) : edge.label || edge.kind),
        labelOffset,
        labelProgress,
        routeOffset,
        role: integrated ? "aggregate" : joining || parallelFlow ? "converging"
          : edge.kind === "return" ? "return" : edge.kind === "repeat" ? "iteration" : "flow",
      },
    });
  });

  return { nodes: resultNodes, edges: placeComplexEdgeLabels(resultNodes, resultEdges), rankMap };
}

export function parseExample(source) {
  const text = String(source || "");
  const split = text.match(/^\s*([A-Za-z_]\w*)\s*:\s*([^=]+?)\s*=\s*([\s\S]+?)\s*$/);
  if (!split) return null;
  const tokens = [];
  const expression = split[3];
  const tokenPattern = /\s*(?:((?:"(?:\\.|[^"\\])*")|(?:'(?:\\.|[^'\\])*'))|(-?\d+(?:\.\d+)?)|([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)|([\[\](),=]))/gy;
  let end = 0;
  while (end < expression.length) {
    tokenPattern.lastIndex = end;
    const match = tokenPattern.exec(expression);
    if (!match) return null;
    tokens.push(match[1] ? { kind: "string", value: match[1] }
      : match[2] ? { kind: "number", value: match[2] }
        : match[3] ? { kind: "identifier", value: match[3] }
          : { kind: match[4], value: match[4] });
    end = tokenPattern.lastIndex;
  }
  let cursor = 0;
  const peek = (offset = 0) => tokens[cursor + offset];
  const take = (kind) => {
    const token = peek();
    if (!token || (kind && token.kind !== kind)) throw new Error("unexpected example token");
    cursor += 1;
    return token;
  };
  const value = () => {
    const token = take();
    if (token.kind === "string") {
      return { kind: "string", value: token.value.slice(1, -1).replace(/\\n/g, "\n").replace(/\\([\\"'])/g, "$1") };
    }
    if (token.kind === "number") return { kind: "number", value: token.value };
    if (token.kind === "[") {
      const items = [];
      while (peek() && peek().kind !== "]") {
        items.push(value());
        if (peek()?.kind === ",") take(",");
        else break;
      }
      take("]");
      return { kind: "list", items };
    }
    if (token.kind !== "identifier") throw new Error("unsupported example value");
    if (!peek() || peek().kind !== "(") return { kind: "symbol", value: token.value };
    take("(");
    const fields = [];
    const items = [];
    while (peek() && peek().kind !== ")") {
      if (peek().kind === "identifier" && peek(1)?.kind === "=") {
        const name = take("identifier").value;
        take("=");
        fields.push({ name, value: value() });
      } else items.push(value());
      if (peek()?.kind === ",") take(",");
      else break;
    }
    take(")");
    return { kind: "constructor", name: token.value, fields, items };
  };
  try {
    const result = value();
    if (cursor !== tokens.length) return null;
    return { binding: split[1], type: split[2].trim(), value: result };
  } catch (_error) {
    return null;
  }
}

export function authoredValues(nodes) {
  const seen = new Set();
  return nodes.filter(Boolean).flatMap((node) => {
    const code = String(node.output_example || "").trim();
    if (!code || seen.has(code)) return [];
    const parsed = parseExample(code);
    if (!parsed) return [];
    seen.add(code);
    return [{ value: parsed.value }];
  });
}

export function workflowSources(workflow) {
  if (Array.isArray(workflow.sources) && workflow.sources.length) return workflow.sources;
  return workflow.source_text
    ? [{ path: workflow.source, file_type: "reasoning", content: workflow.source_text }]
    : [];
}

function plainType(value) {
  const match = String(value || "").match(/^Generated\[(.+)]$/);
  return match ? match[1] : String(value || "");
}

export function workflowInputTypes(workflow) {
  return new Set((workflow.graph.input || []).map((input) => input.type).filter(Boolean));
}

function workflowProducedTypes(workflow) {
  return new Set(workflow.graph.nodes
    .filter((node) => node.kind === "occurrence" && node.output_type)
    .map((node) => plainType(node.output_type)));
}

function workflowConcepts(workflow) {
  const ignored = new Set(["Generated", "Occurrence", "Object", "Assessment", "Disposition", "Result", "Evidence", "Context", "Specification", "Request", "Response", "State", "Input", "Output"]);
  const contracts = [
    ...workflowInputTypes(workflow),
    workflow.graph.output,
    ...workflow.graph.nodes.flatMap((node) => [node.input_type, node.output_type]),
  ].filter(Boolean);
  return new Set(contracts.flatMap((contract) => String(contract).match(/[A-Z][A-Za-z0-9]+/g) || [])
    .filter((concept) => concept.length > 4 && !ignored.has(concept)));
}

function intersection(left, right) {
  return [...left].filter((item) => right.has(item)).sort();
}

export function projectRelations(project) {
  const workflows = project.workflows;
  const inputs = workflows.map(workflowInputTypes);
  const produced = workflows.map(workflowProducedTypes);
  const concepts = workflows.map(workflowConcepts);
  const relations = [];
  for (let source = 0; source < workflows.length; source += 1) {
    for (let target = source + 1; target < workflows.length; target += 1) {
      const forward = intersection(produced[source], inputs[target]);
      const reverse = intersection(produced[target], inputs[source]);
      if (forward.length || reverse.length) {
        if (forward.length) relations.push({ source, target, kind: "handoff", labels: forward });
        if (reverse.length) relations.push({ source: target, target: source, kind: "handoff", labels: reverse });
        continue;
      }
      const sharedConcepts = intersection(concepts[source], concepts[target]);
      if (sharedConcepts.length) relations.push({ source, target, kind: "contract", labels: sharedConcepts });
    }
  }
  return relations;
}

export function workflowRelationshipSemantics(relation, workflowIndex) {
  const names = relation.labels.slice(0, 2).map(compactType).join(" + ");
  const more = relation.labels.length > 2 ? ` +${relation.labels.length - 2}` : "";
  const contracts = `${names}${more}`;
  const outgoing = relation.source === workflowIndex;
  if (relation.kind === "handoff") {
    return outgoing
      ? { label: `Feeds ${contracts} into`, description: `This workflow produces ${contracts}, which matches the other workflow's declared input.` }
      : { label: `Receives ${contracts} from`, description: `The other workflow produces ${contracts}, which matches this workflow's declared input.` };
  }
  return {
    label: `Shares ${contracts} contract with`,
    description: `Both workflows reference the ${contracts} contract. This is a structural connection, not an invocation or a value handoff.`,
  };
}

export function tokenizePrismLine(line) {
  const tokens = [];
  let index = 0;
  while (index < line.length) {
    const character = line[index];
    if (/\s/.test(character)) {
      let end = index + 1;
      while (end < line.length && /\s/.test(line[end])) end += 1;
      tokens.push({ text: line.slice(index, end), kind: "" });
      index = end;
    } else if (character === "#") {
      tokens.push({ text: line.slice(index), kind: "comment" });
      break;
    } else if (character === '"' || character === "'") {
      const quote = character;
      let end = index + 1;
      let escaped = false;
      while (end < line.length) {
        const current = line[end];
        end += 1;
        if (escaped) escaped = false;
        else if (current === "\\") escaped = true;
        else if (current === quote) break;
      }
      tokens.push({ text: line.slice(index, end), kind: "string" });
      index = end;
    } else if (/[A-Za-z_]/.test(character)) {
      let end = index + 1;
      while (end < line.length && /[A-Za-z0-9_.]/.test(line[end])) end += 1;
      const word = line.slice(index, end);
      tokens.push({ text: word, kind: KEYWORD_KINDS.get(word) || (/^[A-Z]/.test(word) ? "type" : "identifier") });
      index = end;
    } else if (/\d/.test(character)) {
      let end = index + 1;
      while (end < line.length && /[\d.]/.test(line[end])) end += 1;
      tokens.push({ text: line.slice(index, end), kind: "number" });
      index = end;
    } else {
      const pair = line.slice(index, index + 2);
      const length = ["->", "==", "!=", "<=", ">="].includes(pair) ? 2 : 1;
      tokens.push({ text: line.slice(index, index + length), kind: "operator" });
      index += length;
    }
  }
  return tokens;
}

export function prismFileNavigationIndex(sources) {
  const declarations = new Map();
  const modules = new Map();
  const declarationPattern = /^\s*(?:type|relation|reasoning|agent|def)\s+([A-Za-z_][A-Za-z0-9_]*)/;
  const assignmentPattern = /^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=/;
  sources.forEach((source) => {
    const moduleName = source.path.split("/").at(-1).replace(/\.prism$/, "");
    modules.set(moduleName, source);
    source.content.split("\n").forEach((line, index) => {
      const match = line.match(declarationPattern) || line.match(assignmentPattern);
      if (!match) return;
      if (!declarations.has(match[1])) declarations.set(match[1], []);
      declarations.get(match[1]).push({ source, line: index + 1 });
    });
  });
  return { declarations, modules };
}
