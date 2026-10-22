// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";

import { loadPrismCatalog } from "@/lib/prism-catalog";

export function usePrismCatalog(versionId, enabled = true) {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    setError(null);
    loadPrismCatalog(versionId)
      .then((value) => { if (active) setCatalog(value); })
      .catch((requestError) => { if (active) setError(requestError); });
    return () => { active = false; };
  }, [versionId, enabled]);

  return { catalog, error };
}
