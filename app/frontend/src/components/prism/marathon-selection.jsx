// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
/** Select a snapshot-bound research run. Readiness is advisory; execution
 * independently reopens canonical evidence before making model requests. */
export function selectedMarathon(runs, inputs) {
  return runs.find((run) => run.target_id === inputs.target_id && run.run_id === inputs.run_id);
}

export function marathonCanRun(runs, inputs, { networkEnabled, networkAuthority }) {
  const status = selectedMarathon(runs, inputs)?.readiness?.status;
  return status === "requires_validation" ||
    (status === "initialization_available" && networkEnabled && networkAuthority);
}

function targetName(id) {
  return id.replace(/-target$/, "").replaceAll("-", " ");
}

export function MarathonSelection({ runs, value, onChange, disabled }) {
  const targets = [...new Set(runs.map((run) => run.target_id))];
  const available = runs.filter((run) => run.target_id === value.target_id);
  const selected = selectedMarathon(runs, value);
  return <div className="marathon-selection">
    <label className="label">Target
      <select className="form-control" value={value.target_id || ""} disabled={disabled}
        onChange={(event) => onChange({ target_id: event.target.value,
          run_id: runs.some((run) => run.target_id === event.target.value && run.run_id === "new") ? "new" : "" })}>
        <option value="">Choose a target…</option>
        {targets.map((id) => <option key={id} value={id}>{targetName(id)}</option>)}
      </select>
    </label>
    <label className="label">Discovery run
      <select className="form-control" value={value.run_id || ""} disabled={disabled || !available.length}
        onChange={(event) => onChange({ ...value, run_id: event.target.value })}>
        <option value="">Choose a run…</option>
        {available.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id === "new" ? "Start a new run" : `${run.run_id} · ${run.cycle_count} prior cycles`}</option>)}
      </select>
    </label>
    {selected && <p role="status" className={selected.readiness?.status === "blocked" ? "form-error" : "muted"}>
      {selected.readiness?.reason || "Run readiness is unavailable. Re-export this package."}
    </p>}
    {selected?.readiness?.status === "initialization_available" && <p className="muted">New runs use the selected AI model and require public literature reads. Initialization completes before the research cycle starts.</p>}
    <p className="muted">Runs execute one new research cycle and generate the full discovery report. Prior cycles stay in the timeline.</p>
  </div>;
}
