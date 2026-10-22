// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Download } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { PageError, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { PageTabs } from "@/components/page-tabs";
import { InputExamples } from "@/components/prism/input-examples";
import { PrismFiles } from "@/components/prism/prism-files";
import { ProjectAtlas } from "@/components/prism/project-atlas";
import { RunWorkflow } from "@/components/prism/run-workflow";
import { SlidesView } from "@/components/prism/slides-view";
import { WorkflowGraph } from "@/components/prism/workflow-graph";
import { buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePrismBundle } from "@/lib/use-prism-bundle";
import { reasoningOptions } from "@/lib/prism-viewer";
import { usePackage } from "@/context/package-context";
import "@/styles/prism-viewer.css";

const VIEW_TABS = [
  { value: "map", label: "Project atlas", id: "map-tab" },
  { value: "graph", label: "Workflow graph", id: "graph-tab" },
  { value: "files", label: "Prism files", id: "files-tab" },
  { value: "slides", label: "Slide View", id: "slides-tab" },
  { value: "examples", label: "Input examples", id: "examples-tab" },
  { value: "run", label: "Run", id: "run-tab" },
];

function selection(bundle, searchParams) {
  const requestedProject = searchParams.get("project");
  const requestedWorkflow = searchParams.get("workflow");
  const project = bundle.projects.find((item) => item.id === requestedProject)
    || bundle.projects.find((item) => item.workflows.some((workflow) => workflow.id === requestedWorkflow))
    || bundle.projects[0];
  if (!project) return null;
  const workflow = project.workflows.find((item) => item.id === requestedWorkflow) || project.workflows[0];
  const requestedView = searchParams.get("view");
  const view = VIEW_TABS.some((tab) => tab.value === requestedView) ? requestedView : "map";
  return { project, workflow, view };
}

function PrismControls({ bundle, project, workflow, onProjectChange, onWorkflowChange }) {
  const projectItems = bundle.projects.map((item) => ({ value: item.id, label: item.label || item.id }));
  const workflowItems = reasoningOptions(project);
  return (
    <nav className="prism-controls" aria-label="Graph controls">
      <div className="prism-selector-group">
        <label htmlFor="prism-project-select">Project</label>
        <Select items={projectItems} value={project.id} onValueChange={onProjectChange}>
          <SelectTrigger id="prism-project-select" className="prism-project-select"><SelectValue /></SelectTrigger>
          <SelectContent>{projectItems.map((item) => <SelectItem value={item.value} key={item.value}>{item.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="prism-selector-group workflow-selector">
        <label htmlFor="prism-workflow-select">Workflow</label>
        <Select items={workflowItems} value={workflow.id} onValueChange={onWorkflowChange}>
          <SelectTrigger id="prism-workflow-select" className="prism-workflow-select"><SelectValue /></SelectTrigger>
          <SelectContent>{workflowItems.map((item) => <SelectItem value={item.value} key={item.value}>{item.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
    </nav>
  );
}

export function PrismPage() {
  const { bundle, error } = usePrismBundle();
  const { versionId } = usePackage();
  const [searchParams, setSearchParams] = useSearchParams();
  const current = useMemo(() => bundle ? selection(bundle, searchParams) : null, [bundle, searchParams]);

  useEffect(() => {
    if (!current) return;
    const canonical = new URLSearchParams(searchParams);
    canonical.set("project", current.project.id);
    canonical.set("workflow", current.workflow.id);
    if (current.view === "map") canonical.delete("view");
    else canonical.set("view", current.view);
    canonical.delete("render");
    if (canonical.toString() !== searchParams.toString()) setSearchParams(canonical, { replace: true });
  }, [current, searchParams, setSearchParams]);

  if (error) return <PageError error={error} />;
  if (bundle && !bundle.projects.length) return <section><PageHeader title="Prism" /><p>No PRISM reasoning blocks found.</p></section>;
  if (!current) return <LoadingState label="Loading Prism workflows…" />;

  const updateParams = (changes) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(changes).forEach(([key, value]) => {
      if (!value || (key === "view" && value === "map")) next.delete(key);
      else next.set(key, value);
    });
    setSearchParams(next, { replace: true });
  };
  const selectProject = (projectId) => {
    const project = bundle.projects.find((item) => item.id === projectId);
    if (project) updateParams({ project: project.id, workflow: project.workflows[0].id });
  };
  const openWorkflow = (workflowId) => updateParams({ workflow: workflowId, view: "graph" });
  const exportUrl = `/api/packages/versions/${encodeURIComponent(versionId)}/workflows/${encodeURIComponent(current.workflow.id)}/export`;

  return (
    <section className="prism-page">
      <PageHeader
        title="Prism"
        actions={
          <a
            className={buttonVariants({ variant: "outline" })}
            href={exportUrl}
            download
            aria-label={`Export ${current.workflow.label || current.workflow.id} workflow package`}
          >
            <Download aria-hidden="true" />Export workflow
          </a>
        }
      />
      <div className="prism-workbench">
        <PrismControls
          bundle={bundle}
          project={current.project}
          workflow={current.workflow}
          onProjectChange={selectProject}
          onWorkflowChange={(workflowId) => updateParams({ workflow: workflowId })}
        />
        <PageTabs
          tabs={VIEW_TABS}
          label="Viewer mode"
          value={current.view}
          onValueChange={(view) => updateParams({ view })}
          className="prism-view-tabs"
        />
        <main className="prism-view-content">
          {current.view === "map" && (
            <ProjectAtlas project={current.project} workflow={current.workflow} onOpenWorkflow={openWorkflow} />
          )}
          {current.view === "graph" && (
            <WorkflowGraph workflow={current.workflow} />
          )}
          {current.view === "files" && <PrismFiles workflow={current.workflow} />}
          {current.view === "slides" && <SlidesView project={current.project} />}
          {current.view === "examples" && <InputExamples workflow={current.workflow} />}
          {current.view === "run" && <RunWorkflow workflow={current.workflow} />}
        </main>
      </div>
    </section>
  );
}
