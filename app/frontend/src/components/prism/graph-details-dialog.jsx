// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PageTabs } from "@/components/page-tabs";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { TabsContent } from "@/components/ui/tabs";
import {
  compactType,
  edgeValueType,
  humanize,
  mainLabel,
  reasoningKind,
  splitCamelCase,
  workflowSources,
} from "@/lib/prism-viewer";
import { PrismCode } from "./prism-code";
import { ExampleCard, NodeExamples } from "./prism-values";

const DETAIL_TABS = [
  { value: "inspector", label: "Inspector" },
  { value: "source", label: "Prism source" },
];

function Detail({ label, value, className = "" }) {
  if (!value) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{className && value !== "—" ? <code className={className}>{value}</code> : value}</dd>
    </>
  );
}

function stepCommentary(node) {
  if (node.kind !== "occurrence") return "";
  return node.commentary || "No commentary is provided for this step in the Prism source.";
}

function connectedNodes(graph, node) {
  const byId = new Map(graph.nodes.map((item) => [item.id, item]));
  return graph.edges.filter((edge) => edge.target === node.id).map((edge) => byId.get(edge.source)).filter(Boolean);
}

function NodeInspector({ graph, node, workflow }) {
  const producers = connectedNodes(graph, node)
    .map((item) => `${mainLabel(item)} → ${item.output_type || "Unknown"}`)
    .join("\n");
  const skills = node.skills || [];
  return (
    <>
      <p className="hint">Selected · {reasoningKind(node)} · {node.id}</p>
      <h3 className="inspector-label">{mainLabel(node)}</h3>
      <dl>
        <Detail label="Alias" value={node.alias || node.id} className="alias-chip" />
        <Detail label="Input type" value={node.input_type || "—"} className="input-chip" />
        <Detail label="Output type" value={node.output_type || "—"} className="output-chip" />
        <Detail label="Relation" value={node.relation || "—"} className="relation-chip" />
        <Detail label="Source expression" value={node.source_code} className="commentary-block" />
        <Detail label="Certificate" value={node.certificate || "—"} className="certificate-chip" />
        <Detail label="Commentary" value={stepCommentary(node)} className="commentary-block" />
        <Detail label="Incoming" value={producers} />
      </dl>
      <NodeExamples graph={graph} node={node} />
      <h3 className="section-title">Skills · {skills.length}</h3>
      {!skills.length && (
        <p className="skill-empty">
          {workflow.skill_metadata === "unavailable"
            ? "No checked materialization is available for this workflow."
            : "No skill is bound to this reasoning occurrence."}
        </p>
      )}
      {skills.map((skill) => (
        <Link
          className="skill"
          key={`${skill.path}:${skill.binding_occurrence || ""}`}
          to={`/skills/${encodeURIComponent(skill.name)}`}
        >
          <strong>{skill.name || skill.path}</strong>
          <small>{skill.version || ""}</small>
          <span>{skill.role}</span>
          <span className="skill-mapping">
            Mapped to {mainLabel(node)}{skill.binding_agent ? ` via ${compactType(skill.binding_agent)}` : ""}
          </span>
          {skill.contribution && <span className="skill-contribution">{skill.contribution}</span>}
          <code>{skill.path}</code>
        </Link>
      ))}
    </>
  );
}

function flowSemantics(graph, edge, nodesById) {
  const source = nodesById.get(edge.source);
  const target = nodesById.get(edge.target);
  if (!source || !target) return "The checked graph does not expose both endpoints for this flow.";
  const producer = mainLabel(source);
  const consumer = mainLabel(target);
  if (!["data", "dependency", "return"].includes(edge.kind)) {
    return `The source declares ${edge.label || edge.kind} from ${producer} to ${consumer}.`;
  }
  const carried = compactType(edgeValueType(edge, nodesById));
  const producerAction = source.kind === "input"
    ? `The workflow supplies ${carried}.`
    : `The ${producer} function produces ${carried}.`;
  if (edge.kind === "return") {
    const output = compactType(graph.output || target.output_type || carried);
    return `${producerAction} That value becomes the workflow's final ${output} result.`;
  }
  const consumerInput = compactType(target.input_type || carried);
  const consumerOutput = compactType(target.output_type || "declared result");
  const incomingCount = graph.edges.filter((candidate) => candidate.kind !== "return" && candidate.target === target.id).length;
  const contribution = incomingCount > 1 ? `one of ${incomingCount} inputs` : "the input";
  const relation = target.relation
    ? ` The ${splitCamelCase(target.relation)} relation governs this reasoning transition.`
    : "";
  return `${producerAction} The ${consumer} function uses it as ${contribution} to satisfy its ${consumerInput} contract and produce ${consumerOutput}.${relation}`;
}

function EdgeInspector({ edge, graph }) {
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const source = nodesById.get(edge.source);
  const target = nodesById.get(edge.target);
  const skills = (source.skills || []).map((skill) => {
    const name = skill.name || skill.path;
    return skill.binding_agent ? `${name} via ${compactType(skill.binding_agent)}` : name;
  }).join("\n");
  return (
    <>
      <p className="hint">Selected · {edge.kind === "return" ? "Workflow return" : edge.kind === "data" ? "Data dependency" : edge.kind}</p>
      <h3 className="inspector-label edge-inspector-label">{mainLabel(source)} → {mainLabel(target)}</h3>
      <dl>
        <Detail label={["data", "dependency", "return"].includes(edge.kind) ? "Value carried" : "Source transition"} value={["data", "dependency", "return"].includes(edge.kind) ? edgeValueType(edge, nodesById) : edge.label || edge.kind} className="flow-chip" />
        <Detail label="Producer" value={`${mainLabel(source)} · ${source.id}`} />
        <Detail label="Consumer" value={`${mainLabel(target)} · ${target.id}`} />
        <Detail label="Consumer contract" value={target.input_type || "Workflow result"} className="input-chip" />
        <Detail label="Flow semantics" value={flowSemantics(graph, edge, nodesById)} className="commentary-block" />
        <Detail label="Producer function" value={stepCommentary(source)} className="commentary-block" />
        {edge.kind !== "return" && <Detail label="Consumer function" value={stepCommentary(target)} className="commentary-block" />}
        <Detail label="Producer skills" value={skills} />
      </dl>
      {source.output_example && (
        <>
          <h3 className="section-title example-title">Concrete value carried</h3>
          <ExampleCard example={{ label: mainLabel(source), code: source.output_example }} direction="output" />
        </>
      )}
    </>
  );
}

function SystemInspector({ data }) {
  return (
    <>
      <p className="hint">Selected · Complex systems annotation</p>
      <h3 className="inspector-label">{data.label || humanize(data.role)}</h3>
      <dl>
        <Detail label="System role" value={humanize(data.role || "annotation")} className="relation-chip" />
        <Detail label="Evidence" value={data.explanation || "Derived from the checked dependency structure."} className="commentary-block" />
        {data.role === "iteration" && (
          <Detail
            label="Trust boundary"
            value="Visual recurrence cue only; no cycle exists in the authored dependency graph."
            className="certificate-chip"
          />
        )}
      </dl>
    </>
  );
}

export function GraphDetailsDialog({ selection, workflow, onOpenChange }) {
  const [tab, setTab] = useState("inspector");
  const sources = useMemo(() => workflowSources(workflow), [workflow]);
  const source = sources.find((item) => item.path === workflow.source) || sources[0];
  const selectedNode = selection?.type === "node"
    ? selection.node
    : selection?.type === "edge"
      ? workflow.graph.nodes.find((node) => node.id === selection.edge.source)
      : selection?.data?.originalNode || null;

  useEffect(() => setTab("inspector"), [selection]);
  if (!selection || !source) return null;
  const activeSpan = selectedNode?.source_span ? {
    ...selectedNode.source_span,
    symbols: [selectedNode.id, selectedNode.method, selectedNode.relation].filter(Boolean),
  } : null;
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="graph-details-dialog">
        <DialogTitle className="sr-only">Graph element details</DialogTitle>
        <PageTabs
          tabs={DETAIL_TABS}
          label="Graph element details"
          value={tab}
          onValueChange={setTab}
          className="graph-details-frame"
        >
          <div className="graph-details-content">
            <TabsContent value="inspector" className="contract-panel graph-details-panel">
              <h2>Inspector</h2>
              {selection.type === "node" && <NodeInspector graph={workflow.graph} node={selection.node} workflow={workflow} />}
              {selection.type === "edge" && <EdgeInspector graph={workflow.graph} edge={selection.edge} />}
              {selection.type === "system" && <SystemInspector data={selection.data} />}
            </TabsContent>
            <TabsContent value="source" className="source-panel graph-details-panel">
              <div className="source-heading">
                <h2>Prism source</h2>
                <code>{workflow.source}</code>
              </div>
              <pre className="source-view" tabIndex="0" aria-label="Highlighted Prism source">
                <code>
                  <PrismCode
                    activeSpan={activeSpan}
                    onNavigate={() => {}}
                    source={source}
                    sources={sources}
                    workflow={workflow}
                  />
                </code>
              </pre>
            </TabsContent>
          </div>
        </PageTabs>
      </DialogContent>
    </Dialog>
  );
}
