// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Database, FileText, Play, Square, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CheckboxField } from "@/components/ui/checkbox";
import { sourceFields } from "@/lib/source-selection";
import { InputReview } from "./input-review";
import { SchemaForm } from "@/components/ui/schema-form";
import { reusableInputRuns, workflowInputSchema } from "@/lib/schema-form";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ReasoningTimeline } from "./reasoning-timeline";
import { NativeHtmlReport } from "./native-html-report";
import { TypedReport } from "./typed-report";
import { NativeReport } from "./native-report";
import { MarathonSelection, marathonCanRun } from "./marathon-selection";
import { applyReasoningSnapshot } from "@/lib/prism-reasoning";
import { usePackage } from "@/context/package-context";
import { api, streamReasoning } from "@/lib/api";
import {
  canRunWorkflow,
  workflowExecutionOptions,
  selectedDatasetStatus,
  emptyModelListLabel,
  modelOptionLabel,
  prismRunPayload,
  runStatusLabel,
  workflowHistoryId,
  runReportPath,
} from "@/lib/prism-runs";

// Saved reports remain readable even when a workflow has no execution adapter.
function SavedRunReport({ run }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    api(`/api/prism/runs/${encodeURIComponent(run.id)}`)
      .then((value) => { if (active) setDetail(value); })
      .catch((reason) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [run.id, run.version_id, run.state]);
  if (error) return <p role="alert" className="form-error">{error}</p>;
  const output = detail?.outputs?.find((item) => item.structured_value?.typed_report || item.structured_value?.html_report || item.structured_value?.report_layout);
  if (!output) return null;
  return <section className="run-report" aria-label="Run report" style={{ width: "100%", minWidth: 0, padding: "0 16px 16px" }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, margin: "16px 0" }}>
      <div><h3>{run.safe_inputs?.report_title || "Report"}</h3>
        {run.imported && <p className="muted">Imported example · {run.safe_inputs?.report_summary || "Saved report and source evidence"}</p>}
      </div>
      <Button variant="outline" asChild><Link to={runReportPath(run.id)} style={{ flex: "0 0 auto", padding: "8px 12px" }}><FileText aria-hidden="true" />Open report</Link></Button>
    </div>
    {output.structured_value?.typed_report ? <TypedReport report={{ id: output.id, run_id: run.id, typed_report: output.structured_value.typed_report }} /> : output.structured_value?.report_layout ? <NativeReport run={detail} output={output} /> : <NativeHtmlReport run={detail} output={output} />}
  </section>;
}

export function RunWorkflow({ workflow }) {
  const { selected } = usePackage();
  const [inputs, setInputs] = useState({});
  const inputFormId = useId();
  const [networkAuthority, setNetworkAuthority] = useState(false);
  const [registry, setRegistry] = useState([]);
  const [registryLoaded, setRegistryLoaded] = useState(false);
  const [selectedExecutionId, setSelectedExecutionId] = useState(null);
  const executionOptions = workflowExecutionOptions(workflow.id, registry);
  const runnable = executionOptions.find((item) => item.id === selectedExecutionId) || executionOptions[0];
  const executionId = workflowHistoryId(workflow.id, runnable);
  const networkEnabled = runnable?.downloads_enabled === true;
  const [models, setModels] = useState([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [reasoning, setReasoning] = useState({});
  const [reconnecting, setReconnecting] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const workflowRef = useRef(executionId);
  workflowRef.current = executionId;
  const workflowRuns = runs.filter((run) => run.workflow_id === executionId)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const activeRun = workflowRuns.find((run) => ["queued", "running"].includes(run.state) && !run.imported);
  const selectedRun = workflowRuns.find((run) => run.id === selectedRunId) || workflowRuns[0];
  const visibleRuns = selectedRun ? [selectedRun] : [];
  const runOptions = workflowRuns.map((run, index) => ({
    value: run.id,
    label: `${index === 0 ? "Latest · " : ""}${new Date(run.created_at).toLocaleString()} · ${run.imported ? "Imported report" : runStatusLabel(run.state)} · ${run.id.slice(0, 8)}`,
  }));
  const subscriptionKey = visibleRuns.filter((run) => !run.imported).map((run) => run.id).sort().join(",");

  useEffect(() => {
    setReasoning({});
    setSelectedRunId(null);
    setDatasetIds([]);
    setInputs({});
    setNetworkAuthority(false);
    setRunDialogOpen(false);
    setRuns([]);
  }, [selected?.id, workflow.id, executionId]);

  useEffect(() => {
    if (!subscriptionKey) return;
    const runIds = subscriptionKey.split(",");
    const controller = new AbortController();
    let timer;
    async function subscribe() {
      try {
        const complete = await streamReasoning(executionId, runIds, (event) => {
          if (controller.signal.aborted) return;
          setReconnecting(false);
          setReasoning((current) => applyReasoningSnapshot(current, event, runIds));
        }, controller.signal);
        if (complete || controller.signal.aborted) return;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error.status >= 400 && error.status < 500) {
          setReconnecting(false);
          setStreamError("Live reasoning is unavailable on this server.");
          return;
        }
      }
      setReconnecting(true);
      timer = window.setTimeout(subscribe, 1500);
    }
    setReconnecting(false);
    setStreamError(null);
    subscribe();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [executionId, subscriptionKey]);
  const [datasetIds, setDatasetIds] = useState([]);
  const [aiModelId, setAiModelId] = useState("");
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [stoppingRunId, setStoppingRunId] = useState(null);
  const [deletingRunId, setDeletingRunId] = useState(null);
  const runDialogContentRef = useRef(null);

  useEffect(() => {
    if (stoppingRunId && !runs.some((run) => run.id === stoppingRunId && ["queued", "running"].includes(run.state))) {
      setStoppingRunId(null);
    }
  }, [runs, stoppingRunId]);

  function refresh() {
    if (!executionId) return;
    api(`/api/prism/runs?workflow_id=${encodeURIComponent(executionId)}&page_size=8`)
      .then((value) => { if (workflowRef.current === executionId) setRuns(value.items); })
      .catch((error) => { if (workflowRef.current === executionId) toast.error(error.message); });
  }

  useEffect(() => {
    api("/api/prism/workflows").then((value) => { setRegistry(value); setRegistryLoaded(true); }).catch((error) => toast.error(error.message));
    api("/api/ai-models")
      .then(setModels)
      .catch((error) => toast.error(error.message))
      .finally(() => setModelsLoaded(true));
  }, []);
  useEffect(() => {
    if (!executionId) return;
    refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => window.clearInterval(timer);
  }, [executionId]);
  const inputSchema = workflowInputSchema(runnable);
  const previousInputs = reusableInputRuns(workflowRuns, { workflowId: executionId, versionId: selected?.id, schema: inputSchema });
  const datasetInput = Boolean(inputSchema.properties?.dataset_ids);
  const marathonRuns = runnable?.metadata?.marathon_runs || [];
  const marathonInput = marathonRuns.length > 0;
  const marathonReady = !marathonInput || marathonCanRun(marathonRuns, inputs, { networkEnabled, networkAuthority });
  const { unavailable, needsDownloads, ready: datasetsReady } = selectedDatasetStatus(runnable, datasetIds);
  const canRun = selected?.runtime_state === "ready" && canRunWorkflow({ runnable, aiModelId }) && (!datasetInput || datasetsReady) && marathonReady;
  async function startRun(formInputs) {
    if (!canRun) return;
    setSubmitting(true);
    try {
      const accepted = await api(`/api/prism/workflows/${encodeURIComponent(executionId)}/runs`, {
        method: "POST",
        body: JSON.stringify(prismRunPayload(executionId, { aiModelId, datasetIds, inputs: datasetInput ? { ...formInputs, dataset_ids: datasetIds } : formInputs, networkAuthority: networkEnabled && networkAuthority })),
      });
      if (workflowRef.current !== executionId) return;
      toast.success("Workflow run accepted");
      setRunDialogOpen(false);
      setRuns((current) => [{ id: accepted.run_id, workflow_id: executionId, state: "queued", created_at: new Date().toISOString(), safe_inputs: { inputs: formInputs } }, ...current]);
      setSelectedRunId(accepted.run_id);
      refresh();
      window.location.hash = `run-${accepted.run_id}`;
    } catch (error) {
      toast.error(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function stopRun(run) {
    setStoppingRunId(run.id);
    try {
      await api(`/api/prism/runs/${encodeURIComponent(run.id)}/stop`, { method: "POST" });
      toast.success("Stopping workflow run");
      refresh();
    } catch (error) {
      toast.error(error.message);
      refresh();
      setStoppingRunId(null);
    }
  }

  async function deleteRun(run) {
    setDeletingRunId(run.id);
    try {
      await api(`/api/prism/runs/${encodeURIComponent(run.id)}`, { method: "DELETE" });
      setRuns((current) => current.filter((item) => item.id !== run.id));
      toast.success("Run deleted");
    } catch (error) {
      toast.error(error.message);
    } finally {
      setDeletingRunId(null);
    }
  }

  return (
    <section className="prism-run-panel">
      <Card className="prism-run-card">
        <div>
          <h2>Run {workflow.label || workflow.id}</h2>
          <p>Runtime source reads, stages, artifacts, and outputs are recorded for provenance.</p>
        </div>
        {executionOptions.length > 1 && <label className="label">Operation
          <Select items={executionOptions.map((item) => ({ value: item.id, label: item.name }))} value={executionId} onValueChange={setSelectedExecutionId} disabled={submitting}>
            <SelectTrigger aria-label="Select operation"><SelectValue /></SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              {executionOptions.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </label>}
        <div className="prism-run-actions">
          {runnable && sourceFields(inputSchema, inputs).length > 0 && <InputReview key={`${selected?.id}:${executionId}`} schema={inputSchema} value={inputs} onChange={setInputs} />}
          {!!runnable?.sources?.length && <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline"><Database aria-hidden="true" />Data Sources</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Data Sources</DialogTitle>
                <DialogDescription>Data sources for this workflow. Select a source to view its details.</DialogDescription>
              </DialogHeader>
              <ul className="workflow-datasets">
                {runnable.sources.map((source) => (
                  <li key={source}>
                    <DialogClose asChild>
                      <Link to={`/data-sources/${encodeURIComponent(source)}`}>{source.replaceAll("-", " ")}</Link>
                    </DialogClose>
                  </li>
                ))}
              </ul>
            </DialogContent>
          </Dialog>}
          {activeRun ? <Button
            className="prism-run-button"
            variant="destructive"
            disabled={stoppingRunId === activeRun.id}
            onClick={() => stopRun(activeRun)}
          >
            <Square aria-hidden="true" />{stoppingRunId === activeRun.id ? "Stopping…" : "Stop"}
          </Button> : <Dialog open={runDialogOpen} onOpenChange={(open) => { if (!submitting) { setRunDialogOpen(open); if (open) api("/api/prism/workflows").then(setRegistry).catch((error) => toast.error(error.message)); } }}>
            <DialogTrigger asChild>
              <Button
                className="prism-run-button"
                disabled={!runnable || submitting || selected?.runtime_state !== "ready"}
              >
                <Play aria-hidden="true" />Run
              </Button>
            </DialogTrigger>
            <DialogContent className="prism-run-dialog" ref={runDialogContentRef} aria-describedby={undefined}>
              <DialogHeader>
                <DialogTitle>Run {runnable?.name || workflow.label || workflow.id}</DialogTitle>
              </DialogHeader>
              {!!previousInputs.length && <label className="label">Start from a previous run
                <select className="form-control" value="" disabled={submitting} onChange={(event) => {
                  const previous = previousInputs.find((run) => run.id === event.target.value);
                  if (previous) {
                    setInputs(structuredClone(previous.safe_inputs.inputs));
                    if (datasetInput) setDatasetIds(previous.safe_inputs.inputs.dataset_ids || []);
                  }
                }}>
                  <option value="">Choose inputs to reuse…</option>
                  {previousInputs.map((run) => <option key={run.id} value={run.id}>{new Date(run.created_at).toLocaleString()} · {run.id.slice(0, 8)}</option>)}
                </select>
                <small className="muted">Review reused values and references before running.</small>
              </label>}
              {marathonInput && <MarathonSelection runs={marathonRuns} value={inputs} onChange={setInputs} disabled={submitting} />}
              <SchemaForm
                key={`${selected?.id || ""}:${workflow.id}:${executionId}`}
                id={inputFormId}
                schema={inputSchema}
                value={datasetInput ? { ...inputs, dataset_ids: datasetIds } : inputs}
                managedFields={marathonInput ? ["target_id", "run_id"] : datasetInput ? ["dataset_ids"] : []}
                previousInputs={previousInputs.map((run) => run.safe_inputs.inputs)}
                onChange={setInputs}
                onSubmit={startRun}
                disabled={submitting}
              />
              <CheckboxField disabled={!networkEnabled} checked={networkEnabled && networkAuthority} onChange={(event) => setNetworkAuthority(event.target.checked)}>Allow declared public network reads for this run</CheckboxField>
              {!networkEnabled && <p className="muted">Public network reads are disabled on this server. Runs can use packaged data and configured AI models.</p>}
              {datasetInput && <>
                <div className="label" id="run-dataset-label">Datasets</div>
                <ul className="workflow-datasets" aria-labelledby="run-dataset-label">{(runnable?.datasets || []).filter((dataset) => dataset.kind !== "fixture").map((dataset) => (
                  <li key={dataset.dataset_id}>
                    <CheckboxField checked={datasetIds.includes(dataset.dataset_id)} onChange={(event) => setDatasetIds((current) => event.target.checked ? [...current, dataset.dataset_id] : current.filter((id) => id !== dataset.dataset_id))}>
                      {dataset.name}
                    </CheckboxField>
                    <Link to={`/data-sources/${encodeURIComponent(dataset.resource_id)}`}>View data source</Link>
                    <small>{dataset.visibility} · {dataset.status.replaceAll("_", " ")}</small>
                  </li>
                ))}</ul>
                {!datasetIds.length && <p className="muted">Select at least one dataset from Data Sources.</p>}
                {!!unavailable.length && <p className="form-error">Required local inputs are unavailable: {unavailable.map((dataset) => dataset.name).join(", ")}. Configure these existing datasets on the server.</p>}
                {needsDownloads && runnable && !runnable.downloads_enabled && <p className="form-error">Public dataset downloads are disabled on this server.</p>}
              </>}
              <label className="label">AI model
                <Select items={models.map((model) => ({ value: model.id, label: modelOptionLabel(model) }))} value={aiModelId} onValueChange={setAiModelId}>
                  <SelectTrigger aria-label="Run AI model"><SelectValue placeholder={emptyModelListLabel(models)} /></SelectTrigger>
                  <SelectContent container={runDialogContentRef} alignItemWithTrigger={false}>{models.map((model) => <SelectItem key={model.id} value={model.id}>{modelOptionLabel(model)}</SelectItem>)}</SelectContent>
                </Select>
              </label>
              {runnable?.metadata?.model_required === true && modelsLoaded && !models.length && <p className="form-error">No configured model is available. <Link to="/ai-models">Configure an AI model</Link>.</p>}
              <DialogFooter>
                <DialogClose asChild><Button variant="outline" disabled={submitting}>Cancel</Button></DialogClose>
                <Button type="submit" form={inputFormId} disabled={!canRun || submitting}>
                  <Play aria-hidden="true" />{submitting ? "Accepting…" : "Run"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>}
        </div>
        {selected?.runtime_state !== "ready" && <p>Prepare the selected package runtime to execute workflows.</p>}
        {!runnable && registryLoaded && <p role="alert" className="form-error">This imported workflow is invalid because it has no materialized execution registration.</p>}
      </Card>
      <Select items={runOptions} value={selectedRun?.id || null} onValueChange={setSelectedRunId} disabled={!workflowRuns.length}>
        <SelectTrigger aria-label="Select run"><SelectValue placeholder="No runs available" /></SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          {runOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
        </SelectContent>
      </Select>
      <div className="prism-run-list">
        {visibleRuns.map((run) => (
          <Card className="prism-run-row" id={`run-${run.id}`} key={run.id} style={{ display: "block" }}>
            <div className="prism-run-row-header">
            <Link to={`/prism/runs/${run.id}`}>
              <span><strong>{run.safe_inputs?.report_title || workflow.label || run.workflow_id}</strong><small>{new Date(run.created_at).toLocaleString()}</small></span>
              <span className={`run-state state-${run.state}`}>{run.imported ? "Imported report" : runStatusLabel(run.state)}</span>
            </Link>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="danger prism-run-delete"
                  disabled={["queued", "running"].includes(run.state) || deletingRunId === run.id}
                  title={["queued", "running"].includes(run.state) ? "This run is still active" : "Delete run"}
                  aria-label={`Delete ${run.workflow_id} run`}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <p className="eyebrow">Delete run</p>
                  <AlertDialogTitle>Delete this run?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This deletes the run and its recorded artifacts. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => deleteRun(run)}>Delete</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            </div>
            {run.state === "failed" && run.error_summary && <p role="alert" className="form-error">{run.error_summary}</p>}
            {!run.imported && <ReasoningTimeline entries={reasoning[run.id]?.entries} reconnecting={reconnecting} error={streamError} runState={run.state} />}
            {["completed", "failed", "cancelled"].includes(run.state) && <SavedRunReport run={run} />}
          </Card>
        ))}
        {!visibleRuns.length && <p className="muted">No runs for this workflow yet.</p>}
      </div>
    </section>
  );
}
