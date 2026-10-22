// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { createContext, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import { setSelection } from "@/lib/package-selection";
import { LoadingState, PageError } from "@/components/feedback";

const PackageContext = createContext(null);
export function usePackage() { return useContext(PackageContext); }

export function PackageProvider({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [versions, setVersions] = useState(null);
  const [versionId, setVersionId] = useState(null);
  const [error, setError] = useState(null);
  const [restoredKey, setRestoredKey] = useState(null);
  const storageKey = `lunar-package:${user.id}`;
  function select(id) {
    setSelection(user.id, id);
    setVersionId(id);
    if (id) localStorage.setItem(storageKey, id);
    else localStorage.removeItem(storageKey);
  }
  async function refresh() {
    const data = await api("/api/packages/versions");
    setVersions(data.versions);
    return data.versions;
  }
  useEffect(() => {
    let active = true;
    api("/api/packages/versions").then((data) => {
      if (!active) return;
      const requested = new URLSearchParams(window.location.search).get("package_version_id") || localStorage.getItem(storageKey);
      setVersions(data.versions);
      select(data.versions.some((item) => item.id === requested && !item.deletion_started_at) ? requested : null);
    }).catch((failure) => { if (active) setError(failure); });
    return () => { active = false; };
  }, []);
  // Resolve only ownership/binding before fetching a saved conversation's content.
  const chatId = /^\/chat\/([^/]+)$/.exec(location.pathname)?.[1];
  const contextKey = `${chatId || ""}:${new URLSearchParams(location.search).get("package_version_id") || ""}`;
  const restoring = restoredKey !== contextKey;
  useEffect(() => {
    if (!versions) return;
    let active = true;

    const restore = async () => {
      const queryId = new URLSearchParams(location.search).get("package_version_id");
      if (chatId) {
        const context = await api(`/api/chats/${encodeURIComponent(chatId)}/context`);
        if (active) select(context.version_id);
      } else if (queryId && queryId !== versionId) {
        if (!versions.some((item) => item.id === queryId && !item.deletion_started_at)) throw new Error("Package version not found");
        if (active) select(queryId);
      }
    };
    restore().catch((failure) => { if (active) setError(failure); })
      .finally(() => { if (active) setRestoredKey(contextKey); });
    return () => { active = false; };
  }, [chatId, location.search, Boolean(versions)]);
  function switchVersion(id) {
    select(id || null);
    setError(null);
    const root = location.pathname.split("/")[1];
    navigate(["chat", "reports", "skills", "data-sources", "prism", "repository"].includes(root) ? `/${root}` : location.pathname, { replace: true });
  }
  useEffect(() => {
    if (versionId && versions && !versions.some((item) => item.id === versionId && !item.deletion_started_at)) {
      select(null);
    }
  }, [versions, versionId]);
  const selected = versions?.find((item) => item.id === versionId && !item.deletion_started_at) || null;
  const value = { versions: versions || [], selected, versionId, switchVersion, refresh, restoring, error };
  if (!versions) return error ? <PageError error={error} /> : <LoadingState label="Loading packages…" />;
  return <PackageContext.Provider value={value}>{children}</PackageContext.Provider>;
}
