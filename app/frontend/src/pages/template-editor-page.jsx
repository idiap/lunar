// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { EditorLayout } from "@/components/editor-layout";
import { LoadingState, PageError } from "@/components/feedback";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { bindingsComplete, outputsByVariable } from "@/lib/template-bindings";

function outputLabel(output) {
  return `${output.workflow_id} · ${new Date(output.created_at).toLocaleString()} · ${output.run_id.slice(0, 8)} · ${output.content_digest.slice(0, 15)}…`;
}

export function TemplateEditorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState([]);
  const [bindings, setBindings] = useState({});
  const [reportName, setReportName] = useState("");
  const [runError, setRunError] = useState(null);

  useEffect(() => { api(`/api/templates/${id}`).then(setItem).catch(setError); }, [id]);
  const variables = item?.placeholder_inventory?.variables || [];
  const compatible = useMemo(() => outputsByVariable(variables, choices), [variables, choices]);
  const canRun = reportName.trim() && bindingsComplete(variables, bindings, compatible);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setRunError(null);
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      const updated = await api(`/api/templates/${id}`, { method: "PUT", body: JSON.stringify(values) });
      setItem(updated);
      toast.success("Saved");
    } catch (requestError) {
      setRunError(requestError);
      toast.error(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function showRunner() {
    setRunError(null);
    try {
      const result = await api(`/api/templates/${id}/outputs`);
      setChoices(result.items);
      setBindings({});
      setReportName(`${item.name} report`);
      setOpen(true);
    } catch (requestError) {
      toast.error(requestError.message);
    }
  }

  async function runTemplate() {
    try {
      const result = await api(`/api/templates/${id}/runs`, {
        method: "POST", body: JSON.stringify({ report_name: reportName, bindings }),
      });
      navigate(`/reports/${result.report_id}`);
    } catch (requestError) {
      setRunError(requestError);
    }
  }

  if (error) return <PageError error={error} />;
  if (!item) return <LoadingState />;
  return (
    <>
      <EditorLayout
        back="/templates" title={item.name} onSubmit={save} saving={saving}
        actions={<Button type="button" variant="outline" disabled={!variables.length || item.template_errors?.length} onClick={showRunner}><Play aria-hidden="true" />Run template</Button>}
      >
        <Label>Name<Input name="name" value={item.name} required onChange={(event) => setItem({ ...item, name: event.target.value })} /></Label>
        <Label>Template content<Textarea name="content" rows={24} value={item.content} onChange={(event) => setItem({ ...item, content: event.target.value })} /></Label>
        <section className="template-inventory"><h2>Required variables</h2>{variables.length ? <div>{variables.map((name) => <code key={name}>{name}{item.placeholder_inventory.duplicates[name] ? ` × ${item.placeholder_inventory.duplicates[name]}` : ""}</code>)}</div> : <p className="muted">Add a standalone placeholder such as <code>{"{{workflow_output_key}}"}</code>.</p>}</section>
        {(item.template_errors || runError?.details)?.map?.((detail, index) => <p className="form-error" key={`${detail.line}-${index}`}>Line {detail.line}: {detail.message}</p>)}
      </EditorLayout>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="template-run-dialog">
          <DialogHeader><DialogTitle>Run template</DialogTitle><DialogDescription>Bind each variable to one completed, provenance-backed workflow output.</DialogDescription></DialogHeader>
          <Label>Report name<Input value={reportName} onChange={(event) => setReportName(event.target.value)} /></Label>
          {variables.map((name) => <div className="label" key={name}>
            <Label htmlFor={`binding-${name}`}>{name}</Label>
            <select
              className="select-trigger"
              id={`binding-${name}`}
              value={bindings[name] || ""}
              onChange={(event) => setBindings((current) => ({ ...current, [name]: event.target.value }))}
            >
              <option value="" disabled>Choose a completed output</option>
              {compatible[name].map((output) => <option key={output.id} value={output.id}>{outputLabel(output)}</option>)}
            </select>
            {!compatible[name].length && <small>No completed compatible outputs are available.</small>}
          </div>)}
          {runError && <p className="form-error">{runError.message}</p>}
          <DialogFooter><Button disabled={!canRun} onClick={runTemplate}><Play aria-hidden="true" />Generate report</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
