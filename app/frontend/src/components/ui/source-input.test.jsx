// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SchemaForm } from "./schema-form";
import { api } from "@/lib/api";
import { setSelection } from "@/lib/package-selection";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));
beforeEach(() => setSelection("user", "version-one"));
afterEach(() => { cleanup(); vi.resetAllMocks(); setSelection(null, null); });
const referenceSchema = { type: "object", required: ["source_id", "package_version", "digest"], additionalProperties: false,
  properties: { source_id: { type: "string" }, package_version: { type: "string" }, digest: { type: "string", pattern: "^sha256:[a-f0-9]{64}$" } } };
const hints = { kind: "data-source", content_kind: "json", native_schema: { type: "integer" }, multiple: false };
const ref = (id, version = "v1") => ({ source_id: id, package_version: version, digest: `sha256:${"a".repeat(64)}` });
const source = (id, overrides = {}) => ({ resource_id: id, name: `Source ${id}`, selection: { reference: ref(id), materialized: true, content_kind: "json", native_schema: { type: "integer" }, ...overrides } });
const field = { ...referenceSchema, "x-input": hints };
const schema = (input = field, required = true) => ({ type: "object", properties: { payload: input, budget: { type: "integer", default: 3 } }, required: required ? ["payload"] : [] });
function Harness({ contract = schema(), initial = {}, submit = vi.fn(), disabled = false }) {
  const [value, change] = useState(initial);
  return <SchemaForm schema={contract} value={value} onChange={change} onSubmit={submit} disabled={disabled}><button type="submit">Run</button></SchemaForm>;
}
function catalog(items = [source("one")]) {
  api.mockImplementation(async (url) => url.startsWith("/api/data-sources?") ? { items, total_pages: 1 } : items.find((item) => url.endsWith(`/${item.resource_id}`)));
}

it("selects only compatible registered sources and submits exact references with configuration", async () => {
  catalog([source("one"), source("wrong-type", { native_schema: { type: "string" } }), source("remote", { materialized: false })]);
  const submit = vi.fn(); render(<Harness submit={submit} />);
  fireEvent.click(screen.getByText("Run")); expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Choose source"));
  fireEvent.click(await screen.findByRole("button", { name: "Source one" }));
  expect(screen.queryByRole("button", { name: "Source wrong-type" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Source remote" })).toBeNull();
  await screen.findByText("Selected sources verified.");
  fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenCalledWith({ payload: ref("one"), budget: 3 }));
  expect(api.mock.calls.every(([url, options]) => url.startsWith("/api/data-sources") && !options.method)).toBe(true);
});

it("preserves optional null and workspace defaults without manufacturing a source", async () => {
  catalog(); const submit = vi.fn();
  render(<Harness submit={submit} contract={schema({ anyOf: [referenceSchema, { type: "null" }], "x-input": { ...hints, default_from: { kind: "prepared-workspace", path: "history.json" } } }, false)} />);
  expect(screen.getByText("Using the workflow default.")).toBeTruthy();
  fireEvent.click(screen.getByText("No source")); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ payload: null, budget: 3 }));
  fireEvent.click(screen.getByText("Use default")); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit.mock.lastCall[0].payload).toBeUndefined());
  expect(api).not.toHaveBeenCalled();
});

it("enforces array bounds and uniqueness, and preserves chosen order", async () => {
  catalog([source("one"), source("two")]); const submit = vi.fn();
  render(<Harness submit={submit} contract={schema({ type: "array", minItems: 2, maxItems: 2, uniqueItems: true, items: referenceSchema, "x-input": { ...hints, multiple: true } })} />);
  fireEvent.click(screen.getByText("Add source")); fireEvent.click(await screen.findByRole("button", { name: "Source one" }));
  await screen.findByText("Selected sources verified.");
  fireEvent.click(screen.getByText("Run")); expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Source one" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Source two" }));
  expect(screen.getByText("Add source").disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("Move Payload 2 up"));
  await screen.findByText("Selected sources verified.");
  fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ payload: [ref("two"), ref("one")], budget: 3 }));
});

it("blocks stale identities, pending checks and late responses after a version switch", async () => {
  let resolve; api.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const submit = vi.fn(); render(<Harness initial={{ payload: ref("one") }} submit={submit} />);
  fireEvent.click(screen.getByText("Run")); expect(submit).not.toHaveBeenCalled();
  api.mockResolvedValue(source("one", { reference: ref("one", "v2") }));
  act(() => setSelection("user", "version-two"));
  await screen.findByText(/unavailable, incompatible/);
  await act(async () => resolve(source("one")));
  fireEvent.click(screen.getByText("Run")); expect(submit).not.toHaveBeenCalled();
  expect(api.mock.calls[0][1].signal.aborted).toBe(true);
});

it("supports search, pagination and retry after lookup or verification failure", async () => {
  api.mockRejectedValueOnce(new Error("offline")); const submit = vi.fn(); render(<Harness submit={submit} />);
  fireEvent.click(screen.getByText("Choose source")); await screen.findByText("Could not load sources. Retry.");
  api.mockResolvedValue({ items: [], total_pages: 2 }); fireEvent.click(screen.getByText("Retry sources"));
  await screen.findByText("Page 1 of 2"); fireEvent.click(screen.getByText("Next sources"));
  await waitFor(() => expect(api.mock.lastCall[0]).toContain("page=2"));
  api.mockResolvedValue({ items: [source("one")], total_pages: 1 });
  fireEvent.change(screen.getByLabelText("Search sources for Payload"), { target: { value: "one" } });
  await screen.findByRole("button", { name: "Source one" }); expect(api.mock.lastCall[0]).toContain("q=one&page=1");
  api.mockRejectedValue(new Error("offline")); fireEvent.click(screen.getByRole("button", { name: "Source one" }));
  await screen.findByText("Could not verify selected sources. Retry before submitting.");
  fireEvent.click(screen.getByText("Run")); expect(submit).not.toHaveBeenCalled();
  api.mockImplementation(async (url) => url.includes("?") ? { items: [source("one")], total_pages: 1 } : source("one"));
  fireEvent.click(screen.getByText("Retry verification")); await screen.findByText("Selected sources verified.");
  fireEvent.click(screen.getByText("Run")); await waitFor(() => expect(submit).toHaveBeenCalled());
});

it.each(["disabled", "readOnly"])("honors %s for typed source fields", async (mode) => {
  catalog(); render(<Harness disabled={mode === "disabled"} contract={schema({ ...field, readOnly: mode === "readOnly" })} initial={{ payload: ref("one") }} />);
  await screen.findByText("Selected sources verified.");
  expect(screen.getByText("Choose source").disabled).toBe(true);
  expect(screen.getByLabelText("Remove Payload 1").disabled).toBe(true);
});

it("keeps omitted object references as defaults and validates explicit reference defaults", async () => {
  catalog(); const submit = vi.fn();
  const { unmount } = render(<Harness submit={submit} contract={schema({ ...field, "x-input": { ...hints, default_source_id: "one" } }, false)} />);
  fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit.mock.lastCall[0].payload).toBeUndefined());
  expect(api).not.toHaveBeenCalled(); unmount();
  render(<Harness submit={submit} contract={schema({ ...field, default: ref("one") }, false)} />);
  await screen.findByText("Selected sources verified."); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ payload: ref("one"), budget: 3 }));
});

it("supports a nullable ordered source collection", async () => {
  catalog(); const submit = vi.fn();
  render(<Harness submit={submit} contract={schema({ anyOf: [{ type: "array", items: referenceSchema, maxItems: 1 }, { type: "null" }], default: null, "x-input": { ...hints, multiple: true } })} />);
  fireEvent.click(screen.getByText("Add source")); fireEvent.click(await screen.findByRole("button", { name: "Source one" }));
  await screen.findByText("Selected sources verified."); expect(screen.getByText("Add source").disabled).toBe(true);
  fireEvent.click(screen.getByText("Run")); await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ payload: [ref("one")], budget: 3 }));
});

it("checks source references inside a nested local schema reference", async () => {
  catalog(); const submit = vi.fn();
  render(<Harness submit={submit} initial={{ context: { payload: ref("one") } }} contract={{ type: "object", $defs: { Context: schema() }, properties: { context: { $ref: "#/$defs/Context" } }, required: ["context"] }} />);
  await screen.findByText("Selected sources verified."); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenCalledWith({ context: { payload: ref("one"), budget: 3 } }));
});

it("does not enable optional contexts through their configuration defaults", async () => {
  catalog(); const submit = vi.fn();
  render(<Harness submit={submit} contract={{ type: "object", properties: { context: schema(), other: { type: "object", required: ["config"], properties: { config: { type: "object", required: ["flag"], properties: { flag: { type: "boolean" } } } } } } }} />);
  expect(screen.queryByText("Choose source")).toBeNull();
  fireEvent.click(screen.getByText("Run")); await waitFor(() => expect(submit).toHaveBeenLastCalledWith({}));
  fireEvent.click(screen.getByRole("button", { name: "Include Context" }));
  fireEvent.click(screen.getByText("Choose source")); fireEvent.click(await screen.findByRole("button", { name: "Source one" }));
  await screen.findByText("Selected sources verified."); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ context: { payload: ref("one"), budget: 3 } }));
});

it("retains an explicitly included empty context and opens nested optional groups", async () => {
  const submit = vi.fn(); render(<Harness submit={submit} contract={{ type: "object", properties: {
    skills: { type: "object", properties: { empty: { type: "object", properties: {} }, context: schema() } },
  } }} />);
  fireEvent.click(screen.getByText("Include Skills"));
  fireEvent.click(screen.getByText("Include Empty"));
  fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({ skills: { empty: {} } }));
  fireEvent.click(screen.getByText("Remove Skills")); fireEvent.click(screen.getByText("Run"));
  await waitFor(() => expect(submit).toHaveBeenLastCalledWith({}));
});
