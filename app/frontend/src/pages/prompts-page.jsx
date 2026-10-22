// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { ChevronRight, FileText, Folder, FolderPlus, Home, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { AssetDialog } from "@/components/asset-dialog";
import { AssetRow } from "@/components/asset-row";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function PromptsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const directoryId = searchParams.get("directory");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setData(null);
    setError(null);
    try {
      setData(await api(directoryId ? `/api/prompts/directories/${directoryId}/contents` : "/api/prompts/root/contents"));
    } catch (requestError) {
      setError(requestError);
    }
  }, [directoryId]);

  useEffect(() => { void load(); }, [load]);

  async function createPrompt({ name }) {
    const created = await api("/api/prompts", {
      method: "POST",
      body: JSON.stringify({ name, content: "# New Prompt\n\nStart writing your prompt here…", directory_id: directoryId }),
    });
    navigate(`/prompts/${created.id}`);
  }

  async function createDirectory({ name }) {
    await api("/api/prompts/directories", { method: "POST", body: JSON.stringify({ name, parent_id: directoryId }) });
    toast.success("Directory created");
    await load();
  }

  async function remove(item) {
    const endpoint = item.type === "directory" ? "/api/prompts/directories" : "/api/prompts";
    try {
      await api(`${endpoint}/${item.id}`, { method: "DELETE" });
      toast.success(`${item.type === "directory" ? "Directory" : "Prompt"} deleted`);
      await load();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  }

  if (error) return <PageError error={error} />;
  if (!data) return <LoadingState />;

  const actions = (
    <>
      <AssetDialog
        trigger={<Button variant="outline"><FolderPlus aria-hidden="true" />New directory</Button>}
        title="Create directory"
        fields={[{ name: "name", label: "Directory name", required: true }]}
        onSubmit={createDirectory}
      />
      <AssetDialog
        trigger={<Button><Plus aria-hidden="true" />New prompt</Button>}
        title="Create prompt"
        description="Start with a named Markdown prompt."
        fields={[{ name: "name", label: "Prompt name", required: true }]}
        onSubmit={createPrompt}
      />
    </>
  );

  return (
    <>
      <PageHeader title="AI Prompts" actions={actions} />
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <Link to="/prompts"><Home aria-hidden="true" />Root</Link>
        {data.breadcrumb.map((item) => (
          <span className="breadcrumb-segment" key={item.id}>
            <ChevronRight aria-hidden="true" />
            <Link to={`/prompts?directory=${item.id}`}>{item.name}</Link>
          </span>
        ))}
      </nav>
      <section className="asset-list">
        {data.children.length ? data.children.map((item) => {
          const directory = item.type === "directory";
          return (
            <AssetRow
              key={`${item.type}-${item.id}`}
              href={directory ? `/prompts?directory=${item.id}` : `/prompts/${item.id}`}
              icon={directory ? Folder : FileText}
              title={item.name}
              description={directory ? "Prompt directory" : "AI prompt"}
              date={item.updated_at}
              onDelete={() => remove(item)}
            />
          );
        }) : <EmptyState icon={FileText} title="This directory is empty" description="Create a prompt or a nested directory to get started." />}
      </section>
    </>
  );
}
