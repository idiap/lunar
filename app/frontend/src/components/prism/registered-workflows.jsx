// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LoadingState, PageError } from "@/components/feedback";
import { RunWorkflow } from "./run-workflow";

export function RegisteredWorkflows() {
  const [items, setItems] = useState(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState(null);
  useEffect(() => { api("/api/prism/workflows").then(setItems).catch(setError); }, []);
  if (error) return <PageError error={error} />;
  if (!items) return <LoadingState />;
  if (!items.length) return <p>No executable workflows in this package.</p>;
  const workflow = items.find((item) => item.id === selected) || items[0];
  return <section>
    <label>Workflow <select aria-label="Registered workflow" value={workflow.id} onChange={(event) => setSelected(event.target.value)}>
      {items.map((item) => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
    </select></label>
    <RunWorkflow key={workflow.id} workflow={{ ...workflow, label: workflow.name }} />
  </section>;
}
