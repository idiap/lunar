// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Play } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";

import { EditorLayout } from "@/components/editor-layout";
import { LoadingState, PageError } from "@/components/feedback";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, streamPrompt } from "@/lib/api";

function VariablesDialog({ variables, open, onOpenChange, onRun, running }) {
  function submit(event) {
    event.preventDefault();
    void onRun(Object.fromEntries(new FormData(event.currentTarget)));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <p className="eyebrow">Test prompt</p>
          <DialogTitle>Prompt variables</DialogTitle>
          <DialogDescription>Supply values for this run.</DialogDescription>
        </DialogHeader>
        <form className="form-stack" onSubmit={submit}>
          {variables.map((name) => <Label key={name}>{name}<Input name={name} required /></Label>)}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={running}>{running ? "Running…" : "Run"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PromptEditorPage() {
  const { id } = useParams();
  const [prompt, setPrompt] = useState(null);
  const [models, setModels] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [modelId, setModelId] = useState("");
  const [content, setContent] = useState("");
  const [output, setOutput] = useState("Model output will appear here.");
  const [variables, setVariables] = useState([]);
  const [variablesOpen, setVariablesOpen] = useState(false);

  useEffect(() => {
    Promise.all([api(`/api/prompts/${id}`), api("/api/ai-models")])
      .then(([promptData, modelData]) => {
        setPrompt(promptData);
        setContent(promptData.content || "");
        setModels(modelData);
      })
      .catch(setError);
  }, [id]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api(`/api/prompts/${id}`, { method: "PUT", body: JSON.stringify({ name: values.name, content }) });
      setPrompt((current) => ({ ...current, name: values.name }));
      toast.success("Saved");
    } catch (requestError) {
      toast.error(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function execute(values = {}) {
    setVariablesOpen(false);
    setRunning(true);
    setOutput("");
    try {
      await streamPrompt({ prompt: content, ai_model_id: modelId, variables: values }, (delta) => setOutput((current) => current + delta));
    } catch (requestError) {
      toast.error(requestError.message);
    } finally {
      setRunning(false);
    }
  }

  function prepareRun() {
    if (!modelId) {
      toast.error("Choose an AI model first");
      return;
    }
    const names = [...new Set([...content.matchAll(/(?<!\{)\{([A-Za-z][A-Za-z0-9_]*)\}(?!\})/g)].map((match) => match[1]))];
    setVariables(names);
    if (names.length) setVariablesOpen(true);
    else void execute();
  }

  if (error) return <PageError error={error} />;
  if (!prompt) return <LoadingState />;

  const modelItems = models.map((model) => ({
    label: `${model.name} · ${model.model_id}`,
    value: model.id,
  }));

  return (
    <>
      <EditorLayout back="/prompts" title={prompt.name} onSubmit={save} saving={saving}>
        <Label>Name<Input name="name" defaultValue={prompt.name} required /></Label>
        <Label>Prompt content<Textarea name="content" rows={20} value={content} onChange={(event) => setContent(event.target.value)} /></Label>
        <section className="runner">
          <div><h2>Test prompt</h2><p>Run this draft with one of your configured AI models.</p></div>
          <Select items={modelItems} value={modelId || null} onValueChange={(value) => setModelId(value || "")}>
            <SelectTrigger aria-label="AI model">
              <SelectValue placeholder="Select a model…" />
            </SelectTrigger>
            <SelectContent>
              {modelItems.map((model) => <SelectItem key={model.value} value={model.value}>{model.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={prepareRun} disabled={running}><Play aria-hidden="true" />{running ? "Running…" : "Run prompt"}</Button>
          <pre className="run-output">{output}</pre>
        </section>
      </EditorLayout>
      <VariablesDialog variables={variables} open={variablesOpen} onOpenChange={setVariablesOpen} onRun={execute} running={running} />
    </>
  );
}
