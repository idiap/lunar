// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import { usePackage } from "@/context/package-context";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function PackageSwitcher() {
  const { versions, selected, versionId, switchVersion, refresh } = usePackage();
  const availableVersions = versions.filter((item) => !item.deletion_started_at);
  const [busy, setBusy] = useState(false);
  async function prepare() {
    setBusy(true);
    try {
      await api(`/api/packages/versions/${versionId}/prepare`, { method: "POST" });
    } catch (error) {
      toast.error(error.message);
    } finally {
      try { await refresh(); }
      catch (error) { toast.error(error.message); }
      setBusy(false);
    }
  }
  const preparing = busy || selected?.runtime_state === "preparing";
  return <section className="package-switcher" aria-label="Package workspace">
    <div className="package-switcher-controls">
      <select id="package-version" aria-label="Package version" value={versionId || ""} onChange={(event) => switchVersion(event.target.value)} disabled={busy}>
        <option value="">No package selected</option>
        {availableVersions.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.display_name}</option>)}
      </select>
    </div>
    {selected && (selected.runtime_state !== "ready" || busy) && (
      <Button variant="outline" disabled={preparing} aria-busy={preparing} onClick={prepare}>
        {preparing && <span className="runtime-spinner" role="status" aria-label="Preparing runtime"><LoaderCircle className="spin" aria-hidden="true" /></span>}
        Prepare runtime
      </Button>
    )}
  </section>;
}
