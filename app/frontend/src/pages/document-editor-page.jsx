// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sectionProvenancePath } from "@/lib/template-bindings";
import { reportUrl } from "@/lib/report-attachments";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { EditorLayout } from "@/components/editor-layout";
import { LoadingState, PageError } from "@/components/feedback";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

export function DocumentEditorPage({ config }) {
  const { id } = useParams();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api(`${config.endpoint}/${id}`).then(setItem).catch(setError);
  }, [config.endpoint, id]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      await api(`${config.endpoint}/${id}`, { method: "PUT", body: JSON.stringify(values) });
      setItem(await api(`${config.endpoint}/${id}`));
      setRevision("");
      toast.success("Saved");
    } catch (requestError) {
      toast.error(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  if (error) return <PageError error={error} />;
  if (!item) return <LoadingState />;

  return (
    <EditorLayout
      back={config.back}
      title={item.name}
      onSubmit={save}
      saving={saving}
    >
      {config.endpoint === "/api/report" && <section aria-label="Report preview">
        {item.imported && <Link to={`/reports/${id}/provenance`}>Provenance</Link>}
        {!revision && <ul>{(item.sections || []).map((section) => <li key={section.section_id}><Link to={sectionProvenancePath(id, section.section_id)}>Section provenance: {section.placeholder_name || section.section_id}</Link></li>)}</ul>}
        <label>Report revision <select aria-label="Report revision" value={revision} onChange={(event) => setRevision(event.target.value)}>
          <option value="">Current · v{item.version}</option>
          {(item.revisions || []).map((entry) => <option key={entry.version} value={entry.version}>v{entry.version}</option>)}
        </select></label>
        <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(value) => reportUrl(item, value)}>{revision ? item.revisions.find((entry) => String(entry.version) === revision)?.content || "" : item.content}</ReactMarkdown>
        <ul>{(item.attachments || []).map((entry) => <li key={entry.file_id}><a href={entry.url}>{entry.link || entry.file}</a></li>)}</ul>
      </section>}
      <Label>Name<Input name="name" defaultValue={item.name} required /></Label>
      <Label>{config.contentLabel}<Textarea name="content" rows={config.rows} defaultValue={item.content} /></Label>
    </EditorLayout>
  );
}
