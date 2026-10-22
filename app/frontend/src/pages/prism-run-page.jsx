// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Database, FileText, GitBranch, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BackButton } from "@/components/back-button";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import {
  latestOutput,
  prismAgentEvents,
  runReportPath,
  runStatusLabel,
  TERMINAL_RUN_STATES,
} from "@/lib/prism-runs";
import { humanize } from "@/lib/prism-viewer";

function SummaryValue({ value }) {
  if (value === null || value === undefined) return <span className="muted">Not available</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted">None</span>;
    return <ul className="run-summary-list">{value.map((item, index) => <li key={index}><SummaryValue value={item} /></li>)}</ul>;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return <span className="muted">None</span>;
    return <dl className="run-summary-values">{entries.map(([key, item]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><SummaryValue value={item} /></dd></div>)}</dl>;
  }
  return <span>{String(value)}</span>;
}

export function PrismRunPage() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    let timer;
    const load = () => api(`/api/prism/runs/${encodeURIComponent(runId)}`)
      .then((value) => {
        if (!active) return;
        setRun(value);
        setError(null);
        if (!TERMINAL_RUN_STATES.has(value.state)) timer = window.setTimeout(load, 1200);
      })
      .catch((reason) => { if (active) setError(reason); });
    load();
    return () => { active = false; window.clearTimeout(timer); };
  }, [runId]);

  if (error?.status === 404) return <EmptyState icon={GitBranch} title="Run not found" description="This run does not exist or belongs to another user." />;
  if (error) return <PageError error={error} />;
  if (!run) return <LoadingState label="Loading workflow run…" />;
  const output = latestOutput(run);
  const sources = [...new Map((run.consumed_sources || []).map((source) => [source.resource_id, source])).values()];
  const agentEvents = prismAgentEvents(run);

  return (
    <section className="prism-run-page">
      <BackButton to={`/prism?workflow=${encodeURIComponent(run.workflow_id)}&view=run`} />
      <PageHeader title={humanize(run.workflow_id)} />
      <div className="run-detail-summary">
        <span className={`run-state state-${run.state}`}>{runStatusLabel(run.state)}</span>
        {(run.state === "completed" || run.state === "failed") && (
          <Link to={`/prism/runs/${run.id}/provenance`}>View provenance <GitBranch aria-hidden="true" /></Link>
        )}
      </div>
      {run.error_summary && <Card className="run-error"><TriangleAlert aria-hidden="true" /><div><strong>Run failed</strong><p>{run.error_summary}</p></div></Card>}
      <div className="run-receipt-grid">
        <Card><h2><FileText aria-hidden="true" />Report</h2>{output?.markdown ? <Link to={runReportPath(run.id)}>View report</Link> : <p className="muted">No report was emitted.</p>}</Card>
        <Card><h2>Configured model</h2>{run.ai_model_snapshot ? <dl className="run-summary-values"><div><dt>Name</dt><dd>{run.ai_model_snapshot.name}</dd></div><div><dt>Provider model</dt><dd>{run.ai_model_snapshot.provider}/{run.ai_model_snapshot.model_id}</dd></div><div><dt>Configuration ID</dt><dd>{run.ai_model_snapshot.id}</dd></div></dl> : <p className="muted">No AI model is recorded for this run.</p>}</Card>
        <Card><h2><Database aria-hidden="true" />Observed sources</h2><ul>{sources.map((source) => <li key={source.resource_id}><Link to={`/data-sources/${encodeURIComponent(source.resource_id)}`}>{source.name || source.resource_name || humanize(source.resource_id)}</Link></li>)}</ul>{!sources.length && <p className="muted">No source reads were observed.</p>}</Card>
        <Card><h2><GitBranch aria-hidden="true" />Executed agents and skills</h2><ol>{agentEvents.map((event) => <li key={event.id}><strong>{event.detail.agent_name}</strong><small>{(event.detail.activated_skill_ids || []).join(", ")} · {runStatusLabel(event.status)}</small></li>)}</ol>{!agentEvents.length && <p className="muted">No native PRISM agents were recorded.</p>}</Card>
        {run.artifacts?.length > 0 && <Card className="run-artifacts-card"><h2><FileText aria-hidden="true" />Artifacts</h2><ul>{run.artifacts.map((artifact) => <li key={artifact.id}><a href={artifact.url}>{artifact.safe_locator.replace(/^run:/, "")}</a></li>)}</ul></Card>}
      </div>
      {output?.structured_value !== null && output?.structured_value !== undefined && <Card className="run-summary-card"><h2>Summary</h2><SummaryValue value={output.structured_value.typed_report ? { report: output.structured_value.typed_report.report.title, sections: Object.keys(output.structured_value.typed_report.sections), inputs: run.safe_inputs?.inputs } : output.structured_value} /></Card>}
    </section>
  );
}
