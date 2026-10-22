// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";

import { EditorLayout } from "@/components/editor-layout";
import { LoadingState, PageError } from "@/components/feedback";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { providers } from "@/pages/models-page";

export function ModelEditorPage() {
  const { id } = useParams();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api(`/api/ai-models/${id}`).then(setItem).catch(setError); }, [id]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      await api(`/api/ai-models/${id}`, { method: "PUT", body: JSON.stringify(values) });
      setItem((current) => ({ ...current, ...values }));
      toast.success("Saved");
    } catch (requestError) {
      toast.error(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  if (error) return <PageError error={error} />;
  if (!item) return <LoadingState />;

  const providerItems = providers.map((provider) => ({ label: provider, value: provider }));

  return (
    <EditorLayout back="/ai-models" title={item.name} onSubmit={save} saving={saving}>
      <Label>Name<Input name="name" defaultValue={item.name} required /></Label>
      <Label>
        Provider
        <Select name="provider" items={providerItems} defaultValue={item.provider}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {providerItems.map((provider) => <SelectItem key={provider.value} value={provider.value}>{provider.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </Label>
      <Label>Model ID<Input name="model_id" defaultValue={item.model_id} required /></Label>
      <Label>API key<Input value="••••••••••••••••" disabled /><small>Keys cannot be viewed or edited after creation.</small></Label>
      <div className="field-grid">
        <Label>API base URL<Input name="api_base" defaultValue={item.api_base || ""} /></Label>
        <Label>API version<Input name="api_version" defaultValue={item.api_version || ""} /></Label>
      </div>
    </EditorLayout>
  );
}
