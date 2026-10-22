// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReactMarkdown from "react-markdown";
import { ReportCodeBlock, ReportSourceFiles } from "./report-source-files";
import { apiText } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiText: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const source = '/-- Source: C1 <script>alert(1)</script> -/\ntheorem identity (x : ℝ) : x = x := by\n  rfl\n';
const file = (id, name, digest = "a".repeat(64)) => ({ id, safe_locator: name,
  content_digest: `sha256:${digest}`, url: `/api/prism/runs/run-1/artifacts/${id}?package_version_id=v1` });
const run = { id: "run-1", artifacts: [file("final", "Identity.lean"), file("attempt", "attempts/Identity.lean")] };

it("renders actual attached Lean source with highlighting, safe text, copy and download", async () => {
  apiText.mockResolvedValue(source);
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  const { container } = render(<ReportSourceFiles run={run} />);
  const code = await screen.findByLabelText("Identity.lean", { selector: "pre" });
  await waitFor(() => expect(code.querySelector('span[style*="color"]')).not.toBeNull());
  expect(code.textContent).toBe(source);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelectorAll("details")).toHaveLength(1);
  expect(apiText).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe(run.artifacts[0].url);
  fireEvent.click(screen.getByRole("button", { name: "Copy Identity.lean" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(source));
  expect(screen.getByText("Copied")).toBeTruthy();
});

it("loads additional files only when expanded and preserves downloads on errors", async () => {
  apiText.mockResolvedValueOnce(source).mockRejectedValueOnce(new Error("Source file unavailable (HTTP 410)."));
  const { container } = render(<ReportSourceFiles run={{ ...run, artifacts: [...run.artifacts, file("second", "Second.lean", "b".repeat(64))] }} />);
  await screen.findByLabelText("Identity.lean", { selector: "pre" });
  expect(apiText).toHaveBeenCalledTimes(1);
  const details = container.querySelectorAll("details")[1];
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect((await screen.findByRole("alert")).textContent).toContain("410");
  expect(screen.getAllByRole("link", { name: "Download" })).toHaveLength(2);
});

it("highlights Lean markdown fences while preserving inline and other code", async () => {
  const markdown = '`lean inline`\n\n```lean\ntheorem identity : True := by trivial\n```\n\n```text\nplain text\n```';
  const { container } = render(<ReactMarkdown components={{ pre: ReportCodeBlock }}>{markdown}</ReactMarkdown>);
  const code = screen.getByLabelText("Lean code");
  await waitFor(() => expect(code.querySelector('span[style*="color"]')).not.toBeNull());
  expect(container.querySelectorAll("pre")).toHaveLength(2);
  expect(screen.getByText("lean inline").tagName).toBe("CODE");
  expect(screen.getByText("plain text").closest("pre").className).toBe("");
});

it("does not render a source section for reports without Lean artifacts", () => {
  const { container } = render(<ReportSourceFiles run={{ id: "other", artifacts: [] }} />);
  expect(container.textContent).toBe("");
});
