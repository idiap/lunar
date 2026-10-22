// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TypedReport } from "./typed-report";

afterEach(cleanup);
function report() {
  return { id: "report", attachments: [{ link: "figure", url: "/api/package-files/image?package_version_id=version" }],
    typed_report: { version: "1", report: { template: { id: "layout", title: "Layout" }, sections: [
      { kind: "tabs", id: "outer", tabs: [
        { id: "first", label: "First", sections: [{ id: "one", kind: "markdown", text: "Same text" }] },
        { id: "second", label: "Second", sections: [{ id: "two", kind: "markdown", text: "Same text" },
          { id: "html", kind: "html", text: "<script>window.parent.bad=true</script><p>HTML</p>" },
          { id: "nested", kind: "tabs", tabs: [
            { id: "inner", label: "Inner", sections: [{ id: "image", kind: "image", attachment: "figure", alt: "Figure" }] },
            { id: "other", label: "Other", sections: [{ id: "detail", kind: "markdown", text: "Detail" }] },
          ] },
        ] },
      ] },
    ] } } };
}
function show(value = report(), path = "/reports/report") {
  return render(<MemoryRouter initialEntries={[path]}><TypedReport report={value} /></MemoryRouter>);
}
function provenance(id) {
  expect(screen.getByRole("link", { name: `Show provenance for ${id}` }).getAttribute("href"))
    .toBe(`/reports/report/provenance?section=${id}`);
}
it("renders declared tabs and stable provenance destinations even for duplicate text", () => {
  show();
  expect(screen.getByText("Template: Layout (layout)")).toBeTruthy();
  for (const id of ["outer", "first", "one"]) provenance(id);
  expect(screen.getByText("Same text").closest("[data-section-id]").dataset.sectionId).toBe("one");
  fireEvent.click(screen.getByRole("tab", { name: "Second" }));
  expect(screen.getByText("Same text").closest("[data-section-id]").dataset.sectionId).toBe("two");
  for (const id of ["outer", "second", "two", "html", "nested", "inner", "image"]) provenance(id);
  expect(screen.getByRole("img", { name: "Figure" }).getAttribute("src")).toBe("/api/package-files/image?package_version_id=version");
  fireEvent.keyDown(screen.getByRole("tab", { name: "Inner" }), { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: "Other" }).getAttribute("aria-selected")).toBe("true");
  for (const id of ["other", "detail"]) provenance(id);
  fireEvent.keyDown(screen.getByRole("tab", { name: "Second" }), { key: "Home" });
  expect(screen.getByRole("tab", { name: "First" }).getAttribute("aria-selected")).toBe("true");
});
it("restores nested section visibility when returning from provenance", () => {
  show(report(), "/reports/report#typed-detail");
  expect(screen.getByText("Detail")).toBeTruthy();
  expect(screen.getByRole("tab", { name: "Other" }).getAttribute("aria-selected")).toBe("true");
});
it("isolates HTML without scripts or remote resource loading", () => {
  const { container } = show(report(), "/reports/report#typed-html");
  const frame = screen.getByTitle("HTML section html");
  expect(frame.getAttribute("sandbox")).toBe("");
  expect(frame.getAttribute("srcdoc")).toContain("default-src 'none'");
  expect(container.querySelector("script")).toBeNull();
});
it("shows image failures and unavailable declared attachments", () => {
  show(report(), "/reports/report#typed-image");
  fireEvent.error(screen.getByRole("img"));
  expect(screen.getByRole("alert").textContent).toContain("Image unavailable");
  cleanup();
  const value = report(); value.attachments = [];
  show(value, "/reports/report#typed-image");
  expect(screen.getByRole("alert").textContent).toContain("Image unavailable");
});
it("handles absent templates and refuses unsupported typed data", () => {
  const value = report(); value.typed_report.report.template = null;
  show(value); expect(screen.getByText("No structural template")).toBeTruthy();
  cleanup(); value.typed_report.version = "2";
  show(value); expect(screen.getByRole("alert").textContent).toContain("Unsupported typed report");
  cleanup(); value.typed_report.version = "1"; value.typed_report.report.sections = [{ id: "x", kind: "video" }];
  show(value); expect(screen.getByRole("alert").textContent).toContain("Unsupported typed section");
});
