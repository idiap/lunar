// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import {
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Searchbar } from "@/components/ui/searchbar";
import {
  edgeValueType,
  layoutComplexGraph,
  mainLabel,
  reasoningKind,
  searchable,
} from "@/lib/prism-viewer";
import { GraphDetailsDialog } from "./graph-details-dialog";

function SystemNode({ data, selected }) {
  if (data.role === "module") {
    return (
      <div className={`system-module${data.dim ? " dim" : ""}`}>
        <span>{data.label}</span>
      </div>
    );
  }

  if (data.role === "parallel-fork") {
    return <div className="system-parallel-fork" aria-label="Parallel fork">
      <Handle id="left-target" type="target" position={Position.Left} />
      <Handle id="right-source" type="source" position={Position.Right} />
    </div>;
  }

  const shape = (() => {
    if (data.role === "evaluation") return <polygon points="28,2 202,2 228,52 202,102 28,102 2,52" />;
    if (data.role === "synthesis") return <polygon points="2,14 38,2 167,2 203,14 176,38 203,62 167,74 38,74 2,62 29,38" />;
    if (data.role === "criterion") return <polygon points="50,2 155,2 203,22 203,54 155,74 50,74 2,54 2,22" />;
    if (data.role === "controller") return <polygon points="2,2 172,2 203,38 172,74 2,74" />;
    if (data.role === "criterion-note") return <polygon points="75,2 148,43 75,84 2,43" />;
    if (data.role === "aggregate") return <circle cx="27" cy="27" r="24" />;
    if (data.role === "result") {
      return (
        <>
          <path d="M18 3 C7 3 3 12 3 38 C3 64 7 73 18 73 H187 C198 73 202 64 202 38 C202 12 198 3 187 3 Z" />
          <path className="system-node-shape-inner" d="M20 8 C12 8 9 16 9 38 C9 60 12 68 20 68 H185 C193 68 196 60 196 38 C196 16 193 8 185 8 Z" />
        </>
      );
    }
    return <rect x="2" y="2" width="201" height="72" rx={data.role === "iteration" ? 24 : 11} />;
  })();
  const viewBox = data.role === "evaluation" ? "0 0 230 104"
    : data.role === "criterion-note" ? "0 0 150 86"
      : data.role === "aggregate" ? "0 0 54 54"
        : "0 0 205 76";
  return (
    <div
      className={`system-graph-node system-${data.role} family-${data.family || "reasoning"}${data.dim ? " dim" : ""}${data.related ? " related" : ""}${selected ? " selected" : ""}`}
    >
      <Handle id="left-target" type="target" position={Position.Left} />
      <Handle id="bottom-target" type="target" position={Position.Bottom} />
      <svg className="system-node-shape" viewBox={viewBox} preserveAspectRatio="none" aria-hidden="true">
        {shape}
      </svg>
      <span className="system-node-label">{data.label}</span>
      <Handle id="right-source" type="source" position={Position.Right} />
      <Handle id="top-source" type="source" position={Position.Top} />
    </div>
  );
}

function PrismEdge({ id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }) {
  let path;
  let labelX;
  let labelY;
  let labelAngle;
  if (source === target) {
    path = `M ${sourceX} ${sourceY} C ${sourceX + 90} ${sourceY - 110}, ${sourceX - 90} ${sourceY - 110}, ${targetX} ${targetY}`;
    labelX = sourceX;
    labelY = sourceY - 92;
    labelAngle = 0;
  } else if (data.routeOffset) {
    const deltaX = targetX - sourceX;
    const deltaY = targetY - sourceY;
    const control1 = { x: sourceX + deltaX * 0.3, y: sourceY + deltaY * 0.18 + data.routeOffset };
    const control2 = { x: sourceX + deltaX * 0.7, y: sourceY + deltaY * 0.82 + data.routeOffset };
    path = `M ${sourceX} ${sourceY} C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${targetX} ${targetY}`;
    labelX = (sourceX + 3 * control1.x + 3 * control2.x + targetX) / 8;
    labelY = (sourceY + 3 * control1.y + 3 * control2.y + targetY) / 8;
    labelAngle = Math.atan2(control2.y - control1.y, control2.x - control1.x) * (180 / Math.PI);
  } else {
    [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.42 });
    labelAngle = Math.atan2(targetY - sourceY, targetX - sourceX) * (180 / Math.PI);
    if (data.labelProgress) {
      labelX = sourceX + (targetX - sourceX) * data.labelProgress;
      labelY = sourceY + (targetY - sourceY) * data.labelProgress;
    }
  }
  const label = data.label || "";
  const offset = data.labelOffset || 0;
  const shift = data.labelShift || { along: 0, away: 0 };
  const radians = labelAngle * (Math.PI / 180);
  const offsetX = source === target
    ? shift.along
    : Math.cos(radians) * shift.along - Math.sin(radians) * (offset + shift.away);
  const offsetY = source === target
    ? offset + shift.away
    : Math.sin(radians) * shift.along + Math.cos(radians) * (offset + shift.away);
  const readableAngle = labelAngle > 90 ? labelAngle - 180 : labelAngle < -90 ? labelAngle + 180 : labelAngle;
  const angle = data.role === "criterion" ? readableAngle : Math.max(-42, Math.min(42, readableAngle));
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={`prism-flow-edge role-${data.role || data.edge?.kind || "flow"}${data.dim ? " dim" : ""}${data.related ? " related" : ""}`}
        interactionWidth={18}
      />
      {label && (
        <EdgeLabelRenderer>
          <span
            className={`prism-flow-edge-label role-${data.role || data.edge?.kind || "flow"}${data.dim ? " dim" : ""}${data.related ? " related" : ""}`}
            style={{ transform: `translate(-50%, -50%) translate(${labelX + offsetX}px,${labelY + offsetY}px) rotate(${angle}deg)` }}
          >
            {label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { systemNode: SystemNode };
const edgeTypes = { prismEdge: PrismEdge };

function GraphTooltip({ tooltip, graph }) {
  if (!tooltip) return null;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  if (tooltip.type === "node") {
    const node = tooltip.node;
    return (
      <div className="node-tooltip" role="tooltip" style={{ left: tooltip.left, top: tooltip.top }}>
        <strong>{mainLabel(node)}</strong>
        <span>{reasoningKind(node)} · {node.id}</span>
        <p><span>In</span><code className="input-chip">{node.input_type || (node.kind === "input" ? "Workflow parameter" : "Unknown")}</code></p>
        <p><span>Out</span><code className="output-chip">{node.output_type || "Unknown"}</code></p>
        {node.relation && <p><span>By</span><code className="relation-chip">{node.relation}</code></p>}
      </div>
    );
  }
  if (tooltip.type === "edge") {
    const edge = tooltip.edge;
    return (
      <div className="node-tooltip" role="tooltip" style={{ left: tooltip.left, top: tooltip.top }}>
        <strong>{mainLabel(nodesById.get(edge.source))} → {mainLabel(nodesById.get(edge.target))}</strong>
        <span>{edge.kind === "return" ? "Workflow return" : edge.kind === "data" ? "Data dependency" : edge.kind}</span>
        <p><span>{["data", "dependency", "return"].includes(edge.kind) ? "Carries" : "Transition"}</span><code className="flow-chip">{["data", "dependency", "return"].includes(edge.kind) ? edgeValueType(edge, nodesById) : edge.label || edge.kind}</code></p>
      </div>
    );
  }
  return (
    <div className="node-tooltip" role="tooltip" style={{ left: tooltip.left, top: tooltip.top }}>
      <strong>{tooltip.data.label}</strong>
      <span>{tooltip.data.role} · derived systems view</span>
      <p><span>Detail</span><code className="commentary-block">{tooltip.data.explanation || "Derived from checked dependency structure."}</code></p>
    </div>
  );
}

function GraphControls({ onReset }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className="graph-view-controls" aria-label="Graph view controls">
      <Button variant="outline" size="icon" onClick={() => zoomOut({ duration: 150 })} aria-label="Zoom out" title="Zoom out"><Minus aria-hidden="true" /></Button>
      <Button variant="outline" size="icon" onClick={() => zoomIn({ duration: 150 })} aria-label="Zoom in" title="Zoom in"><Plus aria-hidden="true" /></Button>
      <Button
        variant="outline"
        size="icon"
        onClick={() => { onReset(); requestAnimationFrame(() => fitView({ padding: 0.1, duration: 180 })); }}
        aria-label="Reset view"
        title="Reset view"
      >
        <RotateCcw aria-hidden="true" />
      </Button>
    </div>
  );
}

function GraphCanvas({ graph, onSelection, query, workflow }) {
  const { fitView } = useReactFlow();
  const baseModel = useMemo(() => {
    const model = layoutComplexGraph(workflow);
    const roles = new Map(model.nodes.map((node) => [node.id, node.data.role]));
    return {
      ...model,
      edges: model.edges.map((edge) => {
        const role = edge.data.role || edge.data.edge?.kind;
        const color = role === "return" ? "var(--pv-result)"
          : ["aggregate", "converging"].includes(role) ? "var(--pv-system-aggregate)"
            : role === "criterion" ? "var(--pv-system-control)"
              : role === "iteration" ? "var(--pv-system-feedback)"
                : "var(--pv-edge)";
        return { ...edge, markerEnd: roles.get(edge.target) === "parallel-fork"
          ? undefined : { type: MarkerType.ArrowClosed, color } };
      }),
    };
  }, [workflow]);
  const [nodes, setNodes, onNodesChange] = useNodesState(baseModel.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(baseModel.edges);
  const [hovered, setHovered] = useState(null);
  const [tooltip, setTooltip] = useState(null);

  const reset = useCallback(() => {
    setNodes(baseModel.nodes);
    setEdges(baseModel.edges);
  }, [baseModel, setEdges, setNodes]);

  useEffect(() => {
    reset();
    const frame = requestAnimationFrame(() => fitView({ padding: 0.12, duration: 180 }));
    return () => cancelAnimationFrame(frame);
  }, [fitView, reset]);

  useEffect(() => {
    const normalized = query.trim().toLowerCase();
    const matches = new Set(graph.nodes.filter((node) => !normalized || searchable(node).includes(normalized)).map((node) => node.id));
    setNodes((current) => current.map((node) => {
      const original = node.data.node || node.data.originalNode;
      const match = node.data.synthetic
        ? !normalized || String(node.data.label || "").toLowerCase().includes(normalized)
        : matches.has(original?.id);
      const related = hovered?.type === "node" && (node.id === hovered.id
        || graph.edges.some((edge) => (edge.source === hovered.id && edge.target === node.id) || (edge.target === hovered.id && edge.source === node.id)));
      return { ...node, data: { ...node.data, dim: !match, related } };
    }));
    setEdges((current) => current.map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        dim: Boolean(normalized) && !matches.has(edge.data.edge?.source) && !matches.has(edge.data.edge?.target),
        related: hovered?.type === "node" && (edge.data.edge?.source === hovered.id || edge.data.edge?.target === hovered.id),
      },
    })));
  }, [graph.edges, graph.nodes, hovered, query, setEdges, setNodes]);

  const positionTooltip = (event) => {
    const bounds = event.currentTarget.closest(".graph-canvas")?.getBoundingClientRect();
    if (!bounds) return { left: 10, top: 10 };
    return {
      left: Math.max(10, Math.min(bounds.width - 370, event.clientX - bounds.left + 16)),
      top: Math.max(10, Math.min(bounds.height - 190, event.clientY - bounds.top + 16)),
    };
  };
  const hoverNode = (event, node) => {
    const original = node.data.node;
    setHovered({ type: "node", id: original?.id || node.id });
    setTooltip(original
      ? { type: "node", node: original, ...positionTooltip(event) }
      : { type: "system", data: node.data, ...positionTooltip(event) });
  };
  const hoverEdge = (event, edge) => {
    setHovered({ type: "edge", id: edge.id });
    setTooltip(edge.data.edge
      ? { type: "edge", edge: edge.data.edge, ...positionTooltip(event) }
      : { type: "system", data: edge.data, ...positionTooltip(event) });
  };
  const clearHover = () => { setHovered(null); setTooltip(null); };

  return (
    <div className="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeMouseEnter={hoverNode}
        onNodeMouseMove={hoverNode}
        onNodeMouseLeave={clearHover}
        onEdgeMouseEnter={hoverEdge}
        onEdgeMouseMove={hoverEdge}
        onEdgeMouseLeave={clearHover}
        onNodeClick={(_event, node) => onSelection(node.data.node
          ? { type: "node", node: node.data.node }
          : { type: "system", data: node.data })}
        onEdgeClick={(_event, edge) => onSelection(edge.data.edge
          ? { type: "edge", edge: edge.data.edge }
          : { type: "system", data: edge.data })}
        nodesConnectable={false}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.05}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={0.8} color="var(--pv-line)" />
        <GraphControls onReset={reset} />
      </ReactFlow>
      <GraphTooltip tooltip={tooltip} graph={graph} />
      <div className="complex-legend" aria-label="Complex systems symbol legend">
        <span className="legend-process">Process</span>
        <span className="legend-module">Parallel group</span>
        <span className="legend-aggregate">Σ Join</span>
        <span className="legend-criterion">Source topology</span>
        <span className="legend-feedback">Declared repeat</span>
      </div>
    </div>
  );
}

export function WorkflowGraph({ workflow }) {
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState(null);

  useEffect(() => {
    setQuery("");
    setSelection(null);
  }, [workflow]);

  return (
    <section className="graph-panel" role="tabpanel" aria-labelledby="graph-tab">
      <div className="graph-shell">
        <Searchbar
          className="graph-search"
          label="Search graph"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter nodes, methods, types…"
        />
        <ReactFlowProvider>
          <GraphCanvas graph={workflow.graph} onSelection={setSelection} query={query} workflow={workflow} />
        </ReactFlowProvider>
      </div>
      <GraphDetailsDialog selection={selection} workflow={workflow} onOpenChange={(open) => { if (!open) setSelection(null); }} />
    </section>
  );
}
