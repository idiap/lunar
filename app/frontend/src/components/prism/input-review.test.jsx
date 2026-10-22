// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { InputReview } from "./input-review";

afterEach(cleanup);
it("validates local configuration without any execution or preparation request", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  function Harness() {
    const [value, change] = useState({});
    return <InputReview schema={{ type: "object", required: ["budget"], properties: { budget: { type: "integer", minimum: 1, default: 3 } } }} value={value} onChange={change} />;
  }
  render(<Harness />); fireEvent.click(screen.getByText("Review inputs"));
  fireEvent.click(screen.getByText("Validate inputs"));
  expect(await screen.findByText("Inputs match the selected contract. No workflow has started.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Budget", { exact: false }), { target: { value: "0" } });
  expect(screen.queryByText("Inputs match the selected contract. No workflow has started.")).toBeNull();
  fireEvent.click(screen.getByText("Validate inputs"));
  expect(screen.queryByText("Inputs match the selected contract. No workflow has started.")).toBeNull();
  expect(fetch).not.toHaveBeenCalled(); fetch.mockRestore();
});
