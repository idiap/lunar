// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";

import { loadSkill, loadSkills } from "@/lib/skills";

function useRequest(loader, dependency) {
  const [value, setValue] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setValue(null);
    setError(null);
    loader(dependency)
      .then((result) => { if (active) setValue(result); })
      .catch((requestError) => { if (active) setError(requestError); });
    return () => { active = false; };
  }, [loader, dependency]);

  return { value, error };
}

export function useSkills(query) {
  const { value, error } = useRequest(loadSkills, query);
  return { hierarchy: value, error };
}

export function useSkill(skillId) {
  const { value, error } = useRequest(loadSkill, skillId);
  return { skill: value, error };
}
