// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { AssetDialog } from "@/components/asset-dialog";
import { AssetRow } from "@/components/asset-row";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function LibraryPage({ config }) {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await api(config.listEndpoint));
    } catch (requestError) {
      setError(requestError);
    }
  }, [config.listEndpoint]);

  useEffect(() => { void load(); }, [load]);

  async function create(values) {
    const created = await api(config.createEndpoint, { method: "POST", body: JSON.stringify(config.createPayload(values)) });
    navigate(`${config.basePath}/${created.id}`);
  }

  async function remove(item) {
    try {
      await api(`${config.deleteEndpoint}/${item.id}`, { method: "DELETE" });
      toast.success(`${config.singular} deleted`);
      await load();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  }

  if (error) return <PageError error={error} />;
  if (!items) return <LoadingState />;

  const Icon = config.icon;
  const action = (
    <AssetDialog
      trigger={<Button><Plus aria-hidden="true" />New {config.singular.toLowerCase()}</Button>}
      title={`Create ${config.singular.toLowerCase()}`}
      description={config.dialogDescription}
      fields={config.fields}
      onSubmit={create}
    />
  );

  return (
    <>
      <PageHeader title={config.title} actions={action} />
      <section className="asset-list">
        {items.length ? items.map((item) => (
          <AssetRow
            key={item.id}
            href={config.itemPath ? config.itemPath(item) : `${config.basePath}/${item.id}`}
            icon={Icon}
            title={config.itemTitle?.(item) ?? item.name}
            description={config.itemDescription(item)}
            date={config.itemDate(item)}
            onDelete={config.canDelete && !config.canDelete(item) ? undefined : () => remove(item)}
          />
        )) : <EmptyState icon={Icon} title={config.emptyTitle} description={config.emptyDescription} />}
      </section>
    </>
  );
}
