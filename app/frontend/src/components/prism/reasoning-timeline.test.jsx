// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReasoningTimeline } from "./reasoning-timeline";

afterEach(cleanup);
const event = (id, sequence, status, extra = {}) => ({
  id, run_id: "run", sequence, event_kind: "model", source_event_key: `model:call:1:${status}`,
  source: { stage: "Model call", status, summary: "Recorded call.", ...extra },
  presentation: { status: "unavailable", icon_id: "reasoning_over_facts" },
});

it("shows the model, input and output together when a live call completes", () => {
  const detail = { model_id: "openai/gpt-5.6-sol", input_text: "user:\nQuestion <script>hello</script>" };
  const start = event("start", 1, "running", { model_call: detail });
  const { rerender, container } = render(<ReasoningTimeline entries={[start]} runState="running" />);
  expect(screen.getByText("openai/gpt-5.6-sol")).toBeTruthy();
  expect(screen.getByText("Waiting for model output…")).toBeTruthy();
  const result = event("end", 2, "accepted", { model_call: { ...detail, output_text: "42\nSecond line" } });
  rerender(<ReasoningTimeline entries={[start, result]} runState="completed" />);
  expect(container.querySelectorAll(".prism-reasoning-entry")).toHaveLength(1);
  expect(container.querySelectorAll("pre")[0].textContent).toBe(detail.input_text);
  expect(container.querySelectorAll("pre")[1].textContent).toBe("42\nSecond line");
  expect(container.querySelector("script")).toBeNull();
});

it("shows recorded reasoning.prism step names and distinguishes missing historical text", () => {
  const step = { ...event("step", 2, "completed", { stage: "Reasoning step", reasoning_step: {
    name: "trajectory_assessment", component: "steps.AssessWorkflowTrajectory", workflow: "RefineMathformerWorkflow",
  } }), event_kind: "stage", source_event_key: "reasoning-step:1:completed" };
  render(<ReasoningTimeline entries={[event("old", 1, "accepted"), step]} runState="completed" />);
  expect(screen.getByText("Input text was not recorded.")).toBeTruthy();
  expect(screen.getByText("Output text was not recorded.")).toBeTruthy();
  expect(screen.getByText("trajectory_assessment")).toBeTruthy();
  expect(screen.queryByText("steps.AssessWorkflowTrajectory")).toBeNull();
  expect(screen.queryByText("Workflow: RefineMathformerWorkflow")).toBeNull();
});

it("keeps reasoning boundaries around the model call after completion", () => {
  const start = { ...event("start-step", 1, "running", { stage: "Reasoning step", reasoning_step: {
    name: "trajectory_assessment", component: "steps.AssessWorkflowTrajectory", workflow: "RefineMathformerWorkflow",
  } }), event_kind: "stage", source_event_key: "reasoning-step:execution:1:running" };
  const { rerender, container } = render(<ReasoningTimeline entries={[start]} runState="running" />);
  expect(screen.getByRole("heading", { name: "Reasoning step - Started" })).toBeTruthy();
  const row = container.querySelector(".prism-reasoning-entry");
  const completed = { ...start, id: "completed-step", sequence: 4,
    source_event_key: "reasoning-step:execution:1:completed", source: { ...start.source, status: "completed" } };
  const call = event("call", 2, "running");
  const result = event("result", 3, "accepted");
  rerender(<ReasoningTimeline entries={[start, call, result, completed]} runState="running" />);
  expect(screen.getByRole("heading", { name: "Reasoning step - Completed" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Reasoning step - Started" })).toBeTruthy();
  expect(screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent)).toEqual([
    "Reasoning step - Started", "Model call · Completed", "Reasoning step - Completed",
  ]);
  expect([...container.querySelectorAll(".prism-reasoning-entry")].map((node) => node.dataset.depth)).toEqual(["0", "1", "0"]);
  expect(container.querySelector(".prism-reasoning-icon-active")).toBeNull();
  expect(container.querySelectorAll(".prism-reasoning-entry")).toHaveLength(3);
  expect(container.querySelector(".prism-reasoning-entry")).toBe(row);
});
