// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Download, GitBranch } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { BackButton } from "@/components/back-button";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { catalogResourceId, PROVENANCE_RELATIONS, provenanceGraphModel } from "@/lib/provenance-graph";

function ProvenanceNode({ data, selected }) {
  const { node } = data;
  return (
    <div className={`provenance-flow-node kind-${node.kind}${selected ? " selected" : ""}`}>
      <Handle id="left-target" type="target" position={Position.Left} />
      <Handle id="right-target" type="target" position={Position.Right} />
      <Handle id="top-target" type="target" position={Position.Top} />
      <Handle id="bottom-target" type="target" position={Position.Bottom} />
      <strong>{String(node.label || node.id).slice(0, 24)}</strong>
      <span>{String(node.type || node.kind).slice(0, 28)}</span>
      <Handle id="left-source" type="source" position={Position.Left} />
      <Handle id="right-source" type="source" position={Position.Right} />
      <Handle id="top-source" type="source" position={Position.Top} />
      <Handle id="bottom-source" type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { provenanceNode: ProvenanceNode };

function edgeHandles(edge, byId) {
  const source = byId.get(edge.source);
  const target = byId.get(edge.target);
  if (!source || !target) return {};
  if (source.x < target.x) return { sourceHandle: "right-source", targetHandle: "left-target" };
  if (source.x > target.x) return { sourceHandle: "left-source", targetHandle: "right-target" };
  if (source.y < target.y) return { sourceHandle: "bottom-source", targetHandle: "top-target" };
  return { sourceHandle: "top-source", targetHandle: "bottom-target" };
}

function NodeDetailsDialog({ node, onOpenChange }) {
  if (!node) return null;
  const catalogId = catalogResourceId(node);
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="provenance-node-dialog">
        <DialogHeader>
          <DialogTitle>{String(node.label || node.id)}</DialogTitle>
          <DialogDescription>{String(node.type || node.kind)} · {node.id}</DialogDescription>
        </DialogHeader>
        {catalogId && <Link to={`/data-sources/${encodeURIComponent(catalogId)}`}>Open catalog source</Link>}
        <dl>{Object.entries(node.attributes || {}).map(([key, item]) => <div key={key}><dt>{key}</dt><dd>{typeof item === "object" ? JSON.stringify(item) : String(item)}</dd></div>)}</dl>
      </DialogContent>
    </Dialog>
  );
}

function ProvenanceFlow({ edges, nodes, onSelect }) {
  const nodesInitialized = useNodesInitialized();
  const { fitView } = useReactFlow();

  useEffect(() => {
    if (!nodesInitialized) return undefined;
    const frame = requestAnimationFrame(() => fitView({ padding: 0.18, duration: 150 }));
    return () => cancelAnimationFrame(frame);
  }, [fitView, nodes, nodesInitialized]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_event, node) => onSelect(node.data.node)}
      nodesDraggable={false}
      nodesConnectable={false}
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} size={0.7} color="var(--border)" />
      <Panel position="bottom-left"><div className="provenance-flow-legend"><span className="entity">Entity</span><span className="activity">Activity</span><span className="agent">Agent</span></div></Panel>
      <Controls position="bottom-right" showInteractive={false} />
    </ReactFlow>
  );
}

export function ProvenanceExplorer({ resourceId, endpoint, downloadEndpoint = endpoint, back, title = "Execution lineage" }) {
  const [value, setValue] = useState(null);
  const [error, setError] = useState(null);
  const [relation, setRelation] = useState("all");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    api(endpoint)
      .then(setValue).catch(setError);
  }, [endpoint]);
  const model = useMemo(() => provenanceGraphModel(value?.graph, relation), [value, relation]);
  const byId = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model.nodes]);
  const flowNodes = useMemo(() => model.nodes.map((node) => ({
    id: node.id,
    type: "provenanceNode",
    position: { x: node.x, y: node.y },
    data: { node },
    ariaLabel: `${node.kind}: ${node.label || node.id}`,
  })), [model.nodes]);
  const flowEdges = useMemo(() => model.edges.map((edge) => ({
    ...edge,
    ...edgeHandles(edge, byId),
    label: edge.relation,
    markerEnd: { type: MarkerType.ArrowClosed },
  })), [byId, model.edges]);

  async function download(format) {
    const separator = downloadEndpoint.includes("?") ? "&" : "?";
    const receipt = await api(`${downloadEndpoint}${separator}format=${format}`);
    const blob = new Blob([`${JSON.stringify(receipt.document, null, 2)}\n`], { type: receipt.media_type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${resourceId}.${format}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (error?.status === 404) return <EmptyState icon={GitBranch} title="Provenance unavailable" description="No observed provenance export exists for this run." />;
  if (error) return <PageError error={error} />;
  if (!value) return <LoadingState label="Loading observed provenance…" />;

  return (
    <section className="provenance-page">
      <BackButton to={back} />
      <PageHeader title={title} />
      {value.native_reference && <p>Recorded execution: <code>{value.recorded_execution}</code> · Native value: <code>{value.native_reference}</code></p>}
      {value.report && <div className="provenance-report-meta">
        {value.report.template_name && <span>Template <Link to={`/templates/${encodeURIComponent(value.report.template_id)}`}><strong>{value.report.template_name}</strong></Link></span>}
        {value.section?.run_id && <span>Output <Link to={`/prism/runs/${encodeURIComponent(value.section.run_id)}`}><strong>{value.section.workflow_id} · {value.section.output_key}</strong></Link></span>}
        {value.source_summary && <span>{value.source_summary.length} scoped source/input entities</span>}
      </div>}
      <div className="provenance-toolbar">
        <label className="label">Relation filter
          <Select value={relation} onValueChange={setRelation} items={[{ value: "all", label: "All relations" }, ...PROVENANCE_RELATIONS.map((item) => ({ value: item, label: item }))]}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All relations</SelectItem>{PROVENANCE_RELATIONS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
          </Select>
        </label>
        <span>{model.nodes.length} nodes · {model.edges.length} visible relations</span>
        <Button variant="outline" onClick={() => download("prov-json")}><Download aria-hidden="true" />PROV-JSON</Button>
        <Button variant="outline" onClick={() => download("json-ld")}><Download aria-hidden="true" />JSON-LD</Button>
      </div>
      <Card className="provenance-flow-canvas" aria-label="Observed provenance graph">
        <ReactFlowProvider>
          <ProvenanceFlow edges={flowEdges} nodes={flowNodes} onSelect={setSelected} />
        </ReactFlowProvider>
      </Card>
      <NodeDetailsDialog node={selected} onOpenChange={(open) => { if (!open) setSelected(null); }} />
    </section>
  );
}

export function ProvenancePage() {
  const { runId } = useParams();
  const [params] = useSearchParams();
  const section = params.get("section");
  const base = `/api/prism/runs/${encodeURIComponent(runId)}/provenance`;
  return <ProvenanceExplorer
    resourceId={runId}
    endpoint={section ? `${base}?section=${encodeURIComponent(section)}` : base}
    downloadEndpoint={base}
    title={section ? `Section lineage · ${section}` : "Execution lineage"}
    back={section ? `/prism/runs/${runId}/report#typed-${encodeURIComponent(section)}` : `/prism/runs/${runId}`}
  />;
}
