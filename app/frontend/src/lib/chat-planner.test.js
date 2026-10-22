// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";
import { applyPlannerSnapshot, completePlanner, failRunningTools, visibleMessages } from "./chat-planner.js";

const entry = { id: "e", run_id: "r", sequence: 1, source_event_key: "planning:1", event_kind: "stage", source: { status: "running" }, presentation: { status: "pending" } };
const snapshot = { type: "snapshot", run_id: "r", state: "running", entries: [entry] };
const item = { id: "call", name: "planner", role: "tool-activity", status: "running" };

test("live and history reasoning agree and terminal result is exact", () => {
  const live = applyPlannerSnapshot([item], { tool_call_id: "call", snapshot })[0];
  const result = { status: "completed", released_artifact: { value: [1,2] }, reasoning: { ...snapshot, state: "completed", entries: [{ ...entry, source: { status: "completed" } }] } };
  const output = JSON.stringify(result);
  const completed = completePlanner(live, output);
  const history = visibleMessages([{ role: "assistant", toolCalls: [{ id: "call", function: { name: "planner", arguments: "{}" } }] }, { role: "tool", toolCallId: "call", content: output }]);
  assert.deepEqual(completed.reasoning, history[0].reasoning);
  assert.deepEqual(completed.result.released_artifact, result.released_artifact);
});

test("snapshots isolate invocations and replace duplicate and late presentation entries", () => {
  let state = applyPlannerSnapshot([item], { tool_call_id: "other", snapshot });
  assert.deepEqual(state, [item]);
  state = applyPlannerSnapshot(state, { tool_call_id: "call", snapshot });
  assert.deepEqual(applyPlannerSnapshot(state, { tool_call_id: "call", snapshot: { ...snapshot, run_id: "other" } }), state);
  state = applyPlannerSnapshot(state, { tool_call_id: "call", snapshot: { ...snapshot, entries: [entry, entry] } });
  assert.equal(state[0].reasoning.entries.length, 1);
  const update = { ...entry, presentation: { status: "ready", helper_text: "Recorded decision", icon_id: "DataSource" } };
  state = applyPlannerSnapshot(state, { tool_call_id: "call", snapshot: { ...snapshot, entries: [update] } });
  assert.equal(state[0].reasoning.entries[0].id, entry.id);
  assert.equal(state[0].reasoning.entries[0].presentation.helper_text, "Recorded decision");
});

test("failures stop running indicators and historical pending calls never resume", () => {
  const state = failRunningTools([{ ...item, reasoning: snapshot }], "Disconnected");
  assert.equal(state[0].reasoning.state, "failed");
  assert.equal(state[0].status, "failed");
  assert.equal(applyPlannerSnapshot(state, { tool_call_id: "call", snapshot })[0].status, "failed");
  assert.equal(visibleMessages([{ toolCalls: [{ id: "old", function: { name: "execute_plan" } }] }])[0].status, "failed");
});
