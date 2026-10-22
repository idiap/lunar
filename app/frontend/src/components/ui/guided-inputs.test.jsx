// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SchemaForm } from "./schema-form";
import { api, apiText } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(), apiText: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

function Harness({ schema, previousInputs, onSubmit = vi.fn(), initial = {} }) {
  const [value, setValue] = useState(initial);
  return <SchemaForm schema={schema} previousInputs={previousInputs} value={value} onChange={setValue} onSubmit={onSubmit}><button type="submit">Run</button></SchemaForm>;
}

const file = { id: "file-1", path: "repository/sources/chapter.tex", sha256: "a".repeat(64), url: "/api/package-files/file-1" };

async function expandFileFolders(path = file.path) {
  for (const folder of path.split("/").slice(0, -1)) {
    const summary = await screen.findByText(folder, { selector: "summary span" });
    if (!summary.closest("details").open) fireEvent.click(summary);
  }
}

describe("domain-generic guided inputs", () => {
  it("visibly labels and describes adjacent nested lists, including empty required lists", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", properties: {
      workflow_source: { type: "object", required: ["equations", "symbol_assumptions"], properties: {
        equations: { type: "array", description: "Equations to assess.", items: { type: "string" } },
        target_identity: { type: "string" },
        symbol_assumptions: { type: "array", description: "Assumptions about the symbols.", items: { type: "string" } },
      } },
    } }} />);
    for (const [label, description] of [["Equations", "Equations to assess."], ["Symbol assumptions", "Assumptions about the symbols."]]) {
      const list = screen.getByRole("group", { name: `${label}*` });
      const heading = within(list).getByText(label, { selector: "legend", exact: false });
      expect(heading.classList.contains("sr-only")).toBe(false);
      expect(heading.hidden).toBe(false);
      expect(list.getAttribute("aria-labelledby")).toBe(heading.id);
      const help = within(list).getByText(description);
      expect(list.getAttribute("aria-describedby").split(" ")).toContain(help.id);
      fireEvent.click(within(list).getByRole("button", { name: "Add item" }));
      fireEvent.change(within(list).getByLabelText(`${label} 1`), { target: { value: label === "Equations" ? "x = x" : "x is real" } });
      expect(within(list).getAllByText(label, { selector: "legend", exact: false })).toHaveLength(1);
    }
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ workflow_source: { equations: ["x = x"], symbol_assumptions: ["x is real"] } }));
  });

  it("browses and adds package paths while preserving an editable ordered list", async () => {
    api.mockResolvedValue({ items: [file], has_more: false });
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", properties: {
      source_paths: { type: "array", minItems: 1, items: { type: "string" } },
    } }} />);
    fireEvent.click(screen.getByText("Browse package files"));
    await expandFileFolders();
    fireEvent.click(await screen.findByRole("button", { name: file.path }));
    expect(screen.getByLabelText("Source paths 1").value).toBe(file.path);
    fireEvent.change(screen.getByLabelText("Paste source paths"), { target: { value: "second\nthird" } });
    fireEvent.click(screen.getByText("Add 2 items"));
    fireEvent.click(screen.getByLabelText("Move Source paths 3 up"));
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ source_paths: [file.path, "third", "second"] }));
  });

  it("copies declared file digests and permits manual source anchors", async () => {
    api.mockResolvedValue({ items: [file], has_more: false });
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", properties: {
      baseline_digest: { type: "string", pattern: "^[a-f0-9]{64}$" },
      source_anchor: { type: "string" },
    } }} />);
    fireEvent.click(screen.getByText("Choose file checksum"));
    await expandFileFolders();
    fireEvent.click(await screen.findByRole("button", { name: file.path }));
    fireEvent.change(screen.getByLabelText("Source anchor"), { target: { value: `${file.path}:10-15` } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ baseline_digest: file.sha256, source_anchor: `${file.path}:10-15` }));
  });

  it("honors explicit file hints on arbitrary field names and recovers from lookup failure", async () => {
    api.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ items: [file], has_more: true });
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} schema={{ type: "object", properties: {
      attachment: { type: "string", "x-input": { kind: "file", extensions: [".tex"], pathPrefix: "repository/", relativeToPrefix: true } },
    } }} />);
    fireEvent.click(screen.getByText("Browse package files"));
    expect(await screen.findByText(/Could not load package files/)).toBeTruthy();
    fireEvent.click(screen.getByText("Retry"));
    await expandFileFolders();
    fireEvent.click(await screen.findByRole("button", { name: file.path }));
    expect(screen.getByRole("button", { name: "Load more files" })).toBeTruthy();
    expect(api.mock.calls[1][0]).toContain("extensions=.tex");
    expect(api.mock.calls[1][0]).toContain("prefix=repository%2F");
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ attachment: "sources/chapter.tex" }));
  });

  it("browses nested folders and searches with matching ancestors expanded", async () => {
    api.mockResolvedValue({ items: [file, { ...file, id: "second", path: "tests/physics/derivation.tex" }], has_more: false });
    render(<Harness schema={{ type: "object", properties: { source_path: { type: "string" } } }} />);
    fireEvent.click(screen.getByText("Browse package files"));
    const repository = await screen.findByText("repository", { selector: "summary span" });
    expect(repository.closest("details").open).toBe(false);
    await expandFileFolders();
    expect(screen.getByRole("button", { name: file.path }).textContent).toBe("chapter.tex");
    fireEvent.click(repository);
    expect(repository.closest("details").open).toBe(false);
    api.mockResolvedValue({ items: [{ ...file, id: "second", path: "tests/physics/derivation.tex" }], has_more: false });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "derivation" } });
    const match = await screen.findByRole("button", { name: "tests/physics/derivation.tex" });
    expect(screen.getByText("physics", { selector: "summary span" }).closest("details").open).toBe(true);
    expect(screen.queryByText("repository", { selector: "summary span" })).toBeNull();
    expect(api.mock.calls.at(-1)[0]).toContain("query=derivation");
    fireEvent.click(match);
    expect(screen.getByLabelText("Source path").value).toBe("tests/physics/derivation.tex");
  });

  it("loads additional files into the hierarchy and resets pagination for search", async () => {
    api.mockResolvedValueOnce({ items: [file], has_more: true })
      .mockResolvedValueOnce({ items: [{ ...file, id: "second", path: "repository/sources/later.tex" }], has_more: false })
      .mockResolvedValue({ items: [], has_more: false });
    render(<Harness schema={{ type: "object", properties: { source_path: { type: "string" } } }} />);
    fireEvent.click(screen.getByText("Browse package files"));
    await expandFileFolders();
    fireEvent.click(screen.getByRole("button", { name: "Load more files" }));
    expect(await screen.findByRole("button", { name: "repository/sources/later.tex" })).toBeTruthy();
    expect(screen.getByRole("button", { name: file.path })).toBeTruthy();
    expect(api.mock.calls[1][0]).toContain("offset=1");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "missing" } });
    expect(await screen.findByText(/No matching package files/)).toBeTruthy();
    expect(api.mock.calls[2][0]).toContain("offset=0");
  });

  it("uses previous values at the correct nested reference path without inventing an enum", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} previousInputs={[{ config: { review_policy: "existing-policy" } }]}
      schema={{ type: "object", $defs: { config: { type: "object", properties: { review_policy: { type: "string" } } } },
        properties: { config: { $ref: "#/$defs/config" } } }} />);
    fireEvent.click(screen.getByText(/Suggested values/));
    fireEvent.click(screen.getByRole("button", { name: /existing-policy/ }));
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ config: { review_policy: "existing-policy" } }));
    fireEvent.change(screen.getByLabelText("Review policy"), { target: { value: "custom-policy" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenLastCalledWith({ config: { review_policy: "custom-policy" } }));
  });

  it("retains strict enums and validates list items, uniqueness, and bounds", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} initial={{ entries: ["bad", "bad"] }} schema={{ type: "object", properties: {
      entries: { type: "array", uniqueItems: true, maxItems: 2, items: { type: "string", pattern: "^ok" } },
      method: { type: "string", enum: ["fast", "full"] },
    } }} />);
    expect(screen.getByLabelText("Method").tagName).toBe("SELECT");
    fireEvent.click(screen.getByText("Run"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByText(/must match pattern/).length).toBeGreaterThan(0);
    expect(screen.getByText("Add item").disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Entries 1"), { target: { value: "ok-one" } });
    fireEvent.change(screen.getByLabelText("Entries 2"), { target: { value: "ok-two" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });

  it("uses multiline context fields and shows a single actionable required error", () => {
    render(<Harness schema={{ type: "object", required: ["review_policy"], properties: {
      study_context: { type: "string" }, review_policy: { type: "string" },
    } }} />);
    expect(screen.getByLabelText("Study context").tagName).toBe("TEXTAREA");
    expect(screen.queryByText("Enter or select review policy.")).toBeNull();
    fireEvent.click(screen.getByText("Run"));
    expect(screen.getAllByText("Enter or select review policy.")).toHaveLength(1);
  });
});


describe("source metadata preview", () => {
  const schema = { type: "object", required: ["source_path"], properties: {
    source_path: { type: "string", "x-input": { kind: "file", pathPrefix: "repository/", relativeToPrefix: true,
      fileMetadata: { label: "Detected physics case", commentPrefix: "%", key: "physics-case-id" } } },
  } };
  it("reads the case from file contents, displays it read-only, and submits only the source", async () => {
    api.mockResolvedValue({ items: [file] });
    apiText.mockResolvedValue("% physics-case-id: formalphysics_0042\nDerivation");
    const onSubmit = vi.fn();
    render(<Harness schema={schema} initial={{ source_path: "sources/chapter.tex" }} onSubmit={onSubmit} />);
    expect(await screen.findByText("formalphysics_0042")).toBeTruthy();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(apiText).toHaveBeenCalledWith(file.url, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ source_path: "sources/chapter.tex" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "missing.tex" } });
    expect(screen.queryByText("formalphysics_0042")).toBeNull();
    expect(await screen.findByText(/Selected source is not in this package/)).toBeTruthy();
  });
  it("reports missing or ambiguous declarations and retries detection", async () => {
    api.mockResolvedValue({ items: [file] });
    apiText.mockResolvedValueOnce("No metadata").mockResolvedValueOnce("% physics-case-id: formalphysics_0000\n% physics-case-id: formalphysics_0001")
      .mockResolvedValueOnce("% physics-case-id: formalphysics_0001");
    render(<Harness schema={schema} initial={{ source_path: "sources/chapter.tex" }} />);
    expect(await screen.findByText(/Source must contain exactly one/)).toBeTruthy();
    fireEvent.click(screen.getByText("Retry detection"));
    await waitFor(() => expect(apiText).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/Source must contain exactly one/)).toBeTruthy();
    fireEvent.click(screen.getByText("Retry detection"));
    expect(await screen.findByText("formalphysics_0001")).toBeTruthy();
  });
});
