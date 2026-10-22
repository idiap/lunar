// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export const reasoningIconIds = ["DataSource", "building_mechanistic_model", "decomposing_problem", "evaluating_evidence_strength", "extracting_criteria", "generating_code", "generating_counter-arguments", "generating_data_visualization", "getting_trusted_sources", "interpreting_web_sources", "parametrizing_model", "reasoning_over_facts", "verifying_logical_correctness"];

const legacyIcons = { running: "reasoning_over_facts", reasoning: "reasoning_over_facts", data: "DataSource",
  checking: "verifying_logical_correctness", success: "verifying_logical_correctness",
  warning: "evaluating_evidence_strength", failure: "generating_counter-arguments", information: "reasoning_over_facts" };

export function reasoningIcon(id) {
  return reasoningIconIds.includes(id) ? id : (Object.hasOwn(legacyIcons, id) ? legacyIcons[id] : "reasoning_over_facts");
}

export function reasoningSteps(entries = []) {
  const steps = new Map();
  const openSteps = new Map();
  const ordered = [...new Map(entries.map((entry) => [entry.id, entry])).values()]
    .sort((a, b) => a.sequence - b.sequence);
  for (const entry of ordered) {
    const eventKey = entry.source_event_key;
    const stepKey = entry.event_kind === "run" ? "run"
      : eventKey?.replace(/:(queued|running|completed|accepted|rejected|failed|interrupted|cancelled|result)$/, "");
    const boundary = !!entry.source?.reasoning_step || entry.source?.stage === "Reasoning step";
    // Keep reasoning boundaries in event order; only model calls and other
    // lifecycle observations settle into their original row.
    const key = JSON.stringify([entry.run_id, entry.event_kind, boundary ? eventKey || entry.id : stepKey || entry.id]);
    const previous = steps.get(key);
    const stack = openSteps.get(entry.run_id) || [];
    openSteps.set(entry.run_id, stack);
    let depth = previous?.depth ?? (entry.event_kind === "run" ? 0 : stack.length);
    const row = { ...entry, step_id: previous?.step_id || entry.id, depth };
    if (boundary) {
      if (entry.source.status === "running") {
        stack.push({ key: stepKey || entry.id, row });
      } else {
        const index = stack.findIndex((step) => step.key === stepKey);
        if (index >= 0) {
          depth = index;
          for (const step of stack.splice(index)) step.row.step_finished = true;
        } else {
          // Historical completion-only entries do not establish containment.
          depth = 0;
        }
        row.depth = depth;
      }
    }
    steps.set(key, row);
  }
  return [...steps.values()];
}

export function applyReasoningSnapshot(current, event, runIds) {
  if (!runIds.includes(event.run_id)) return current;
  if (event.type === "deleted") {
    const next = { ...current };
    delete next[event.run_id];
    return next;
  }
  if (event.type !== "snapshot" || !Array.isArray(event.entries)) return current;
  const entries = [...new Map(event.entries
    .filter((entry) => entry.run_id === event.run_id && Number.isInteger(entry.sequence) && entry.sequence > 0)
    .map((entry) => [entry.id, { ...entry, presentation: { ...entry.presentation, icon_id: reasoningIcon(entry.presentation?.icon_id) } }])).values()]
    .sort((a, b) => a.sequence - b.sequence);
  return { ...current, [event.run_id]: { ...event, entries } };
}

export async function consumeReasoningStream(response, onEvent, signal) {
  if (!response.ok) {
    const error = new Error("Reasoning connection unavailable");
    error.status = response.status;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) return false;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const raw = chunk.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!raw || signal.aborted) continue;
        const event = JSON.parse(raw);
        if (event.type === "done") return true;
        onEvent(event);
      }
    }
    return false;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
