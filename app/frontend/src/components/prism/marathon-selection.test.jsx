// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { afterEach, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MarathonSelection, selectedMarathon, marathonCanRun } from "./marathon-selection";
import { SchemaForm } from "@/components/ui/schema-form";

afterEach(cleanup);
const runs = [
  { target_id: "yang-mills-target", run_id: "ym-one", cycle_count: 352, readiness: { status: "blocked", reason: "A current canonical cycle is required." } },
  { target_id: "p-vs-np-target", run_id: "pnp-one", cycle_count: 154, readiness: { status: "requires_validation", reason: "The source runner will check current authority." } },
];
function Harness() {
  const [value, setValue] = useState({});
  const schema = { type: "object", required: ["target_id", "run_id"], additionalProperties: false,
    properties: { target_id: { type: "string", enum: runs.map((run) => run.target_id) },
      run_id: { type: "string", enum: runs.map((run) => run.run_id) } },
    allOf: runs.map((run) => ({ if: { properties: { target_id: { const: run.target_id } } },
      then: { properties: { run_id: { enum: [run.run_id] } } } })),
  };
  return <><MarathonSelection runs={runs} value={value} onChange={setValue} />
    <SchemaForm schema={schema} value={value} onChange={setValue} onSubmit={() => {}} managedFields={["target_id", "run_id"]} />
    <button disabled={selectedMarathon(runs, value)?.readiness.status !== "requires_validation"}>Run selected</button></>;
}

test("target selection filters runs, clears stale choices, and exposes blockers", () => {
  render(<Harness />);
  const target = screen.getByLabelText("Target");
  const run = screen.getByLabelText("Discovery run");
  expect(run.disabled).toBe(true);
  fireEvent.change(target, { target: { value: "yang-mills-target" } });
  expect(screen.queryByRole("option", { name: /pnp-one/ })).toBeNull();
  fireEvent.change(run, { target: { value: "ym-one" } });
  expect(screen.getByRole("status").textContent).toContain("current canonical cycle");
  expect(screen.getByRole("button").disabled).toBe(true);
  fireEvent.change(target, { target: { value: "p-vs-np-target" } });
  expect(run.value).toBe("");
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.change(run, { target: { value: "pnp-one" } });
  expect(screen.getByRole("button").disabled).toBe(false);
});

test("cross-target values cannot select a run", () => {
  expect(selectedMarathon(runs, { target_id: "yang-mills-target", run_id: "pnp-one" })).toBeUndefined();
});


test("new runs require explicit public-read authority and stay target-bound", () => {
  const choices = [...runs, { target_id: "p-vs-np-target", run_id: "new", cycle_count: 0,
    readiness: { status: "initialization_available", reason: "Initialize a new run." } }];
  const value = { target_id: "p-vs-np-target", run_id: "new" };
  expect(marathonCanRun(choices, value, { networkEnabled: true, networkAuthority: false })).toBe(false);
  expect(marathonCanRun(choices, value, { networkEnabled: false, networkAuthority: true })).toBe(false);
  expect(marathonCanRun(choices, value, { networkEnabled: true, networkAuthority: true })).toBe(true);
  expect(marathonCanRun(choices, { ...value, target_id: "yang-mills-target" }, { networkEnabled: true, networkAuthority: true })).toBe(false);
  render(<MarathonSelection runs={choices} value={value} onChange={() => {}} />);
  expect(screen.getByRole("option", { name: "Start a new run" })).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("Initialize a new run");
});
