// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";

import { loadPrismBundle } from "@/lib/prism-catalog";

export function usePrismBundle() {
  const [bundle, setBundle] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    loadPrismBundle()
      .then((value) => { if (active) setBundle(value); })
      .catch((requestError) => { if (active) setError(requestError); });
    return () => { active = false; };
  }, []);

  return { bundle, error };
}
