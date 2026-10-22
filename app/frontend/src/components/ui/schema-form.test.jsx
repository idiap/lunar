// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { SchemaForm } from "./schema-form";

afterEach(cleanup);

function Harness({ schema, onSubmit, initial = {}, managedFields }) {
  const [value, setValue] = useState(initial);
  return <SchemaForm id="parameters" schema={schema} value={value} onChange={setValue} onSubmit={onSubmit} managedFields={managedFields}><button type="submit">Run</button></SchemaForm>;
}

describe("SchemaForm", () => {
  it("renders nullable packaged inputs as labeled text fields and submits edits", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", properties: {
      analysis_goal: { title: "Analysis goal", anyOf: [{ type: "string", minLength: 1 }, { type: "null" }], default: null },
    } }} />);
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.change(screen.getByLabelText("Analysis goal"), { target: { value: "Compare treatments" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ analysis_goal: "Compare treatments" }));
  });

  it("validates required fields and numeric bounds before submitting typed values", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", required: ["count"], properties: {
      count: { title: "Count", type: "integer", minimum: 1, maximum: 10 },
      enabled: { title: "Enabled", type: "boolean", default: false },
      method: { title: "Method", type: "string", enum: ["fast", "full"], default: "fast" },
    } }} />);
    fireEvent.click(screen.getByText("Run"));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "11" } });
    fireEvent.click(screen.getByText("Run"));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ count: 3, enabled: true, method: "fast" }));
  });

  it("allows clearing required nullable text back to null", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} initial={{ goal: "Initial goal" }} schema={{ type: "object", required: ["goal"], properties: {
      goal: { title: "Goal", anyOf: [{ type: "string", minLength: 1 }, { type: "null" }] },
    } }} />);
    fireEvent.change(screen.getByLabelText(/Goal/), { target: { value: "" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ goal: null }));
  });

  it("supports the Run dialog's external submit button and schema defaults", async () => {
    const onSubmit = vi.fn();
    render(<><SchemaForm id="external-form" schema={{ type: "object", properties: { count: { type: "integer", default: 4 } } }} value={{}} onChange={() => {}} onSubmit={onSubmit} /><button type="submit" form="external-form">Run</button></>);
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ count: 4 }));
  });

  it("edits referenced nested objects and arrays without JSON", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", $defs: {
      settings: { type: "object", properties: { name: { type: "string", title: "Name" } } },
    }, properties: {
      settings: { $ref: "#/$defs/settings" },
      tags: { title: "Tags", type: "array", items: { type: "string" } },
    } }} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Study" } });
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[1], { target: { value: "trial" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ settings: { name: "Study" }, tags: ["trial"] }));
    fireEvent.click(screen.getByRole("button", { name: "Remove item" }));
    expect(screen.queryByLabelText("Tags 1")).toBeNull();
    expect(screen.getByLabelText("Name").value).toBe("Study");
  });

  it("validates and submits externally managed dataset IDs without duplicate controls", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} initial={{ dataset_ids: ["study-1"] }} managedFields={["dataset_ids"]} schema={{
      type: "object", required: ["dataset_ids"], additionalProperties: false,
      properties: { dataset_ids: { type: "array", minItems: 1, items: { type: "string" } } },
    }} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add item" })).toBeNull();
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ dataset_ids: ["study-1"] }));
  });
});
