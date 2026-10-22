// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createHash, webcrypto } from "node:crypto";
import { NativeReport } from "./native-report";

vi.stubGlobal("crypto", webcrypto);
vi.mock("./report-math", () => ({ ReportInlineCode: ({ children }) => <code>{children}</code> }));
afterEach(() => { cleanup(); window.location.hash = ""; });
const hash = (text) => createHash("sha256").update(text).digest("hex");
const canonical = (value) => Array.isArray(value) ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object" ? `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}` : JSON.stringify(value);
function output() {
  const parts = ["## Summary\n\n", "Visible narrative.\n\n", "## Timeline\n\n", "Detailed equation evidence.\n\n"];
  let offset = 0;
  const blocks = parts.map((text, index) => {
    const block = { id: `b${index}`, kind: index % 2 === 0 ? "heading" : "prose", start: offset,
      end: offset + Array.from(text).length, group_keys: index < 2 ? ["summary"] : index === 2 ? ["timeline"] : ["timeline", "evidence"] };
    offset = block.end;
    return block;
  });
  const markdown = parts.join("");
  const layout = { schema_version: "lunar.native-report/v1", blocks,
    groups: [{ key: "summary", kind: "tab", label: "Summary" }, { key: "timeline", kind: "tab", label: "Timeline" },
      { key: "evidence", kind: "disclosure", label: "Open evidence" }], content_sha256: hash(markdown) };
  layout.metadata_sha256 = hash(canonical(layout));
  return { markdown, structured_value: { report_layout: layout } };
}

it("renders platform tabs and loads evidence on demand without an iframe", async () => {
  const { container } = render(<NativeReport run={{ id: "run" }} output={output()} />);
  await screen.findByRole("tab", { name: "Summary" });
  expect(container.querySelector("iframe")).toBeNull();
  expect(screen.getByText("Visible narrative.")).toBeTruthy();
  expect(screen.queryByText("Detailed equation evidence.")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
  expect(screen.queryByText("Visible narrative.")).toBeNull();
  const disclosure = screen.getByText("Open evidence").closest("details");
  disclosure.open = true;
  fireEvent(disclosure, new Event("toggle"));
  expect(await screen.findByText("Detailed equation evidence.")).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("tab", { name: "Timeline" }), { key: "Home" });
  expect(screen.getByRole("tab", { name: "Summary" }).getAttribute("aria-selected")).toBe("true");
});

it("retains the native report digest gate", async () => {
  const changed = output();
  changed.markdown += "tampered";
  render(<NativeReport run={{ id: "run" }} output={changed} />);
  expect((await screen.findByRole("alert")).textContent).toMatch(/integrity|missing/);
});
