// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { reasoningIcon, reasoningSteps } from "@/lib/prism-reasoning";

const labels = { queued: "Queued", running: "Started", completed: "Completed", accepted: "Accepted",
  rejected: "Rejected", failed: "Failed", interrupted: "Interrupted", cancelled: "Cancelled" };
export function ReasoningTimeline({ entries, reconnecting, error, runState }) {
  const steps = reasoningSteps(entries);
  const runFinished = ["completed", "failed", "cancelled", "blocked"].includes(runState);
  return <div className="prism-reasoning-timeline" aria-live="polite" aria-relevant="additions text" aria-label="Run reasoning timeline">
    {error && <p className="prism-reasoning-connection" role="status">{error}</p>}
    {reconnecting && <p className="prism-reasoning-connection" role="status">Reconnecting to live updates…</p>}
    {!entries?.length && <p className="muted">{["completed", "failed", "cancelled", "blocked"].includes(runState) ? "No reasoning entries were recorded for this run." : "No reasoning entries recorded yet."}</p>}
    <ol>{steps.map((entry) => {
      const { source, presentation } = entry;
      const ready = presentation.status === "ready";
      const helperText = ready ? presentation.helper_text : source.summary;
      const icon = reasoningIcon(presentation.icon_id);
      const active = source.status === "running" && !entry.step_finished && !runFinished;
      const heading = source.reasoning_step || source.stage === "Reasoning step"
        ? `Reasoning step - ${labels[source.status] || source.status}`
        : entry.event_kind === "model" && source.status === "accepted"
          ? "Model call · Completed"
          : `${source.stage} · ${labels[source.status] || source.status}`;
      return <li key={entry.step_id} style={{ "--reasoning-depth": Math.min(entry.depth || 0, 4) }} data-depth={entry.depth || 0} data-entry-id={entry.id} data-sequence={entry.sequence} data-source-digest={entry.source_digest} data-presentation={presentation.status} className={`prism-reasoning-entry reasoning-${source.status}`}>
        <img src={`/icons/reasoning/${icon}.svg`} alt="" aria-hidden="true" className={`prism-reasoning-icon${active ? " prism-reasoning-icon-active" : ""}`} />
        <div>
          <h3>{heading}</h3>
          {source.reasoning_step && <div className="prism-reasoning-step">
            <p><strong>{source.reasoning_step.name}</strong></p>
          </div>}
          {helperText && !["Model result accepted.", "Reasoning step completed."].includes(helperText) && <p className="prism-reasoning-helper">{helperText}</p>}
          {presentation.status === "pending" && <small>Preparing description</small>}
          <details>
            <summary>Recorded detail</summary>
            {entry.event_kind === "model" && <div className="prism-model-call">
              <p><strong>Model:</strong> {source.model_call?.model_id || "Not recorded"}</p>
              <h4>Input text</h4>
              {source.model_call?.input_text != null ? <pre>{source.model_call.input_text}</pre> : <p className="muted">Input text was not recorded.</p>}
              <h4>Output text</h4>
              {source.model_call?.output_text != null ? <pre>{source.model_call.output_text}</pre> : <p className="muted">{active ? "Waiting for model output…" : "Output text was not recorded."}</p>}
            </div>}
            <p>{source.rationale_summary}</p>
            {!!source.limitations?.length && <ul>{source.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>}
            {!!source.evidence_references?.length && <p>Evidence: {source.evidence_references.join(", ")}</p>}
          </details>
        </div>
      </li>;
    })}</ol>
  </div>;
}
