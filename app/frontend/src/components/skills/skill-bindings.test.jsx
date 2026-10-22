// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SkillBindings } from "./skill-bindings";
afterEach(cleanup);
it("displays source and configuration contracts without offering contract-only execution", () => {
  render(<SkillBindings invocation={{ kind: "prism", bindings: [{ id: "control", module: "skills.control", export: "check", execution_status: "contract_only",
    task_type: "types.ControlInput", result_type: "types.ControlResult", callable_type: "types.ControlCall",
    input_schema: { required: ["items"], properties: { items: { "x-input": { kind: "data-source", content_kind: "json", multiple: true, native_schema: { type: "object" } } }, budget: { type: "integer" } } }, result_schema: { type: "object" } }] }} />);
  expect(screen.getByText("types.ControlInput")).toBeTruthy();
  expect(screen.getByText("types.ControlResult")).toBeTruthy();
  expect(screen.getByText("Ordered sources (json)")).toBeTruthy();
  expect(screen.getByText("Configuration")).toBeTruthy();
  expect(screen.getByText(/execution has not been recorded/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
it("does not invent typed contracts for legacy skills", () => {
  const { container } = render(<SkillBindings invocation={{ kind: "native" }} />);
  expect(container.textContent).toBe("");
});
