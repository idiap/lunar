// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { applyReasoningSnapshot, consumeReasoningStream, reasoningIcon, reasoningSteps, reasoningIconIds } from "./prism-reasoning.js";

const entry = (id, sequence, status = "pending") => ({ id, sequence, run_id: "a", presentation: { status, icon_id: "data" } });
test("snapshots isolate runs, order, deduplicate and enrich in place", () => {
  const b = { entries: [] };
  let current = { b };
  current = applyReasoningSnapshot(current, { type: "snapshot", run_id: "a", entries: [entry("two", 2), entry("one", 1), entry("one", 1)] }, ["a", "b"]);
  assert.deepEqual(current.a.entries.map((e) => e.id), ["one", "two"]);
  current = applyReasoningSnapshot(current, { type: "snapshot", run_id: "a", entries: [entry("two", 2), entry("one", 1, "ready")] }, ["a", "b"]);
  assert.equal(current.a.entries[0].presentation.status, "ready");
  assert.equal(current.b, b);
  assert.equal(applyReasoningSnapshot(current, { type: "deleted", run_id: "c" }, ["a"]), current);
  assert.equal(reasoningIcon("<svg>"), "reasoning_over_facts");
});

test("stream handles split chunks, normal close, interruption and superseded abort", async () => {
  const response = (text) => new Response(new ReadableStream({ start(controller) {
    for (const part of text.match(/.{1,7}/gs)) controller.enqueue(new TextEncoder().encode(part));
    controller.close();
  } }));
  const abort = new AbortController();
  const events = [];
  assert.equal(await consumeReasoningStream(response('data: {"type":"snapshot"}\n\ndata: {"type":"done"}\n\n'), (e) => events.push(e), abort.signal), true);
  assert.equal(events.length, 1);
  assert.equal(await consumeReasoningStream(response(': keepalive\n\n'), () => {}, abort.signal), false);
  abort.abort();
  await consumeReasoningStream(response('data: {"type":"snapshot"}\n\n'), () => assert.fail("stale callback"), abort.signal);
});

test("permanent stream failures retain the HTTP status instead of pretending to reconnect", async () => {
  const abort = new AbortController();
  for (const status of [401, 404]) {
    await assert.rejects(consumeReasoningStream(new Response(null, { status }), () => {}, abort.signal),
      (error) => error.status === status);
  }
});

const observation = (id, sequence, eventKey, status, kind = "stage", run = "a") => ({
  ...entry(id, sequence), run_id: run, event_kind: kind, source_event_key: eventKey,
  source: { stage: "Analysis", status, summary: `${id} summary` },
});

test("steps update in their original row with the final source and presentation", () => {
  const start = observation("start", 1, "stage:1:running", "running");
  const next = observation("next", 2, "stage:2:running", "running");
  for (const status of ["completed", "accepted", "rejected", "failed", "interrupted", "cancelled"]) {
    const final = observation("final", 3, `stage:1:${status}`, status);
    final.presentation = { status: "unavailable", icon_id: "DataSource" };
    const steps = reasoningSteps([final, next, start, start]);
    assert.equal(steps.length, 2);
    assert.equal(steps[0].step_id, reasoningSteps([start])[0].step_id);
    assert.equal(steps[0].id, "final");
    assert.equal(steps[0].source, final.source);
    assert.equal(steps[0].presentation, final.presentation);
    assert.equal(steps[1].id, "next");
  }
});

test("model results replace calls while separate calls and runs remain separate", () => {
  const steps = reasoningSteps([
    observation("call", 1, "model:call-1:running", "running", "model"),
    observation("other-call", 2, "model:call-2:running", "running", "model"),
    observation("result", 3, "model:call-1:result", "accepted", "model"),
    observation("other-run", 1, "model:call-1:running", "running", "model", "b"),
  ]);
  assert.deepEqual(steps.map((step) => step.id), ["result", "other-run", "other-call"]);
  assert.equal(steps[0].step_id, "call");
});

test("run lifecycle replaces queued and started observations, including execution completion", () => {
  const queued = observation("queued", 1, "run:queued", "queued", "run");
  const running = observation("running", 2, "run:running", "running", "run");
  const completed = observation("completed", 3, "run:execution-completed", "completed", "run");
  assert.deepEqual(reasoningSteps([queued, running, completed]).map((step) => [step.step_id, step.id]), [["queued", "completed"]]);
  assert.equal(reasoningSteps([queued, running, completed, observation("failed", 4, "run:failed", "failed", "run")])[0].source.status, "failed");
});

test("pickable icons all resolve to local SVG assets and legacy icons remain readable", async () => {
  const { readdir } = await import("node:fs/promises");
  const files = await readdir(new URL("../../public/icons/reasoning/", import.meta.url));
  // REUSE sidecars accompany the assets without adding selectable icons.
  assert.deepEqual(files.filter((name) => !name.endsWith(".license")).sort(), reasoningIconIds.map((id) => `${id}.svg`).sort());
  assert.equal(reasoningIcon("data"), "DataSource");
  for (const id of reasoningIconIds) assert.equal(reasoningIcon(id), id);
});

const boundary = (id, sequence, step, status, run = "a") => ({
  ...observation(id, sequence, `reasoning-step:${step}:${status}`, status, "stage", run),
  source: { stage: "Reasoning step", status, reasoning_step: { name: step } },
});

test("reasoning boundaries enclose nested model calls and remain in chronological order", () => {
  const events = [
    boundary("outer-start", 1, "outer", "running"),
    boundary("inner-start", 2, "inner", "running"),
    observation("call", 3, "model:1:running", "running", "model"),
    observation("result", 4, "model:1:result", "accepted", "model"),
    boundary("inner-end", 5, "inner", "completed"),
    boundary("outer-end", 6, "outer", "completed"),
  ];
  const live = reasoningSteps(events.slice(0, 3));
  assert.deepEqual(live.map((entry) => entry.depth), [0, 1, 2]);
  assert.equal(live[0].step_finished, undefined);
  const done = reasoningSteps([...events].reverse());
  assert.deepEqual(done.map((entry) => entry.id), ["outer-start", "inner-start", "result", "inner-end", "outer-end"]);
  assert.deepEqual(done.map((entry) => entry.depth), [0, 1, 2, 1, 0]);
  assert.equal(done[0].step_finished, true);
  assert.equal(done[1].step_finished, true);
  assert.deepEqual(reasoningSteps([...events, ...events]), done);
});

test("separate runs, repeated occurrences, and failed steps preserve their own boundaries", () => {
  const done = reasoningSteps([
    boundary("start", 1, "first", "running"),
    boundary("foreign", 2, "foreign", "running", "b"),
    boundary("failed", 3, "first", "rejected"),
    boundary("repeat", 4, "second", "running"),
    observation("call", 5, "model:2:running", "running", "model"),
    boundary("interrupted", 6, "second", "interrupted"),
  ]);
  assert.deepEqual(done.map((entry) => entry.depth), [0, 0, 0, 0, 1, 0]);
  assert.equal(done[0].step_finished, true);
  assert.equal(done[1].step_finished, undefined);
  assert.equal(done[3].step_finished, true);
});

test("completion-only historical entries do not invent a start or model containment", () => {
  const steps = reasoningSteps([
    observation("result", 1, "model:1:result", "accepted", "model"),
    boundary("old-step", 2, "old", "completed"),
  ]);
  assert.deepEqual(steps.map((entry) => [entry.id, entry.depth]), [["result", 0], ["old-step", 0]]);
});
