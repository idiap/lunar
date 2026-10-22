// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  compactType,
  humanize,
  projectRelations,
  splitCamelCase,
  workflowCommentary,
  workflowInputTypes,
  workflowRelationshipSemantics,
} from "@/lib/prism-viewer";
import { BoundaryValues } from "./prism-values";

function WorkflowContract({ workflow }) {
  const input = [...workflowInputTypes(workflow)].map(compactType).join(" + ") || "No input";
  return (
    <div className="tree-contract">
      <span className="tree-contract-input">{input}</span>
      <span className="tree-contract-arrow">→</span>
      <span className="tree-contract-output">{compactType(workflow.graph.output)}</span>
    </div>
  );
}

function WorkflowCard({ current, index, onOpen, onToggle, open, relations, project, workflow }) {
  const related = relations.filter((relation) => relation.source === index || relation.target === index);
  const description = String(workflow.summary || "").trim()
    || workflowCommentary(workflow.source_text, workflow.graph.reasoning)
    || "No workflow-level description is provided.";
  return (
    <Collapsible
      className={`tree-workflow${current ? " current-workflow" : ""}`}
      open={open}
      onOpenChange={(isOpen) => onToggle(workflow.id, isOpen)}
      role="treeitem"
      aria-level="2"
    >
      <CollapsibleTrigger className="tree-collapsible-trigger tree-workflow-trigger">
        <ChevronRight className="tree-chevron" aria-hidden="true" />
        <strong>{splitCamelCase(workflow.graph.reasoning)}</strong>
        {related.length > 0 && (
          <span className="tree-workflow-status">
            {`${related.length} connection${related.length === 1 ? "" : "s"}`}
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="tree-collapsible-content tree-workflow-panel" role="group">
        <div className="tree-workflow-content">
          <p className="tree-workflow-meta">
            {workflow.graph.topology || "Workflow"} · {workflow.graph.nodes.length} nodes · {workflow.graph.edges.length} typed edges
          </p>
          <Collapsible className="tree-workflow-summary">
            <CollapsibleTrigger className="tree-collapsible-trigger tree-section-trigger">
              <ChevronRight className="tree-chevron" aria-hidden="true" />
              <span>Workflow summary</span>
            </CollapsibleTrigger>
            <CollapsibleContent className="tree-collapsible-content tree-section-panel">
              <p>{description}</p>
            </CollapsibleContent>
          </Collapsible>
          <WorkflowContract workflow={workflow} />
          <Collapsible className="tree-workflow-values">
            <CollapsibleTrigger className="tree-collapsible-trigger tree-section-trigger">
              <ChevronRight className="tree-chevron" aria-hidden="true" />
              <span>Concrete input and output values</span>
            </CollapsibleTrigger>
            <CollapsibleContent className="tree-collapsible-content tree-section-panel">
              <BoundaryValues graph={workflow.graph} compact />
            </CollapsibleContent>
          </Collapsible>
          {related.length > 0 && (
            <>
              <h3 className="tree-relation-heading">How this workflow connects · {related.length}</h3>
              <div className="tree-relations">
                {related.map((relation) => {
                  const relatedIndex = relation.source === index ? relation.target : relation.source;
                  const relatedWorkflow = project.workflows[relatedIndex];
                  const semantics = workflowRelationshipSemantics(relation, index);
                  return (
                    <Button
                      variant="outline"
                      size="sm"
                      className={`tree-relation tree-relation-${relation.kind}`}
                      title={semantics.description}
                      onClick={() => onOpen(relatedWorkflow.id)}
                      key={`${relation.kind}:${relation.source}:${relation.target}`}
                    >
                      <small>{semantics.label}</small>
                      <span>{splitCamelCase(relatedWorkflow.graph.reasoning)}</span>
                    </Button>
                  );
                })}
              </div>
            </>
          )}
          <div className="tree-actions">
            <Button variant="outline" size="sm" className="tree-open-button" onClick={() => onOpen(workflow.id)}>
              Open workflow graph
            </Button>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ProjectAtlas({ project, workflow, onOpenWorkflow }) {
  const [openWorkflow, setOpenWorkflow] = useState(null);
  const relations = projectRelations(project);
  const handoffs = relations.filter((relation) => relation.kind === "handoff").length;
  const sharedContracts = relations.filter((relation) => relation.kind === "contract").length;
  return (
    <section className="map-panel" role="tabpanel" aria-labelledby="map-tab">
      <div className="map-heading">
        <div>
          <h2>{project.label || humanize(project.id)} atlas</h2>
          <p>{project.workflows.length} workflows · {handoffs} directional handoffs · {sharedContracts} structural contract links</p>
        </div>
      </div>
      <div className="map-canvas">
        <div className="project-tree" role="tree" aria-label="Expandable project and workflow catalog">
          <Collapsible className="tree-project current-project" defaultOpen role="treeitem" aria-level="1">
            <CollapsibleTrigger className="tree-collapsible-trigger tree-project-trigger">
              <ChevronRight className="tree-chevron" aria-hidden="true" />
              <strong>{project.label || humanize(project.id)}</strong>
              <span className="tree-project-count">{project.workflows.length} workflows</span>
            </CollapsibleTrigger>
            <CollapsibleContent className="tree-collapsible-content tree-project-panel" role="group">
              <div className="tree-project-body">
                {project.workflows.map((item, index) => (
                  <WorkflowCard
                    current={item.id === workflow.id}
                    index={index}
                    onOpen={onOpenWorkflow}
                    onToggle={(workflowId, isOpen) => setOpenWorkflow((current) => {
                      if (isOpen) return workflowId;
                      return current === workflowId ? null : current;
                    })}
                    open={openWorkflow === item.id}
                    project={project}
                    relations={relations}
                    workflow={item}
                    key={item.id}
                  />
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>
    </section>
  );
}
