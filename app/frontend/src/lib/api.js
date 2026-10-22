// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { currentSelection, selectionHeaders, assertCurrent } from "./package-selection.js";

const apiBaseUrl = (import.meta.env?.VITE_API_BASE_URL || "").replace(/\/$/, "");

export async function apiText(path, { signal, maxBytes = 256 * 1024 } = {}) {
  const context = currentSelection();
  const response = await fetch(`${apiBaseUrl}${path}`, {
    credentials: "include", headers: selectionHeaders(context), signal,
  });
  if (!response.ok) throw new Error(`Source file unavailable (HTTP ${response.status}).`);
  const tooLarge = () => new Error("This file is too large to preview. Download it to view the complete source.");
  if (Number(response.headers.get("content-length")) > maxBytes) {
    await response.body?.cancel();
    throw tooLarge();
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw tooLarge();
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    assertCurrent(context);
    return text;
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

export async function api(path, options = {}) {
  const context = currentSelection();
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...selectionHeaders(context),
      ...(typeof options.body === "string" ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  assertCurrent(context);
  if (!response.ok) {
    const error = new Error(data.error || data.detail || "Request failed");
    error.status = response.status;
    error.details = data.details;
    throw error;
  }
  return data;
}

export async function streamPrompt(payload, onText) {
  const response = await fetch(`${apiBaseUrl}/api/prompts/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Could not start prompt run");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop();
    for (const event of events) {
      const raw = event.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
      if (!raw || raw === "[DONE]") continue;
      const data = JSON.parse(raw);
      if (data.type === "text-delta") onText(data.delta);
      if (data.type === "error") throw new Error(data.error);
    }
  }
}

export async function streamAgUi(payload, onEvent) {
  const context = currentSelection();
  const response = await fetch(`${apiBaseUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...selectionHeaders(context) },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Could not start chat run");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop();
    for (const event of events) {
      const raw = event.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
      if (!raw) continue;
      const data = JSON.parse(raw);
      if (currentSelection() === context) onEvent(data);
      if (data.type === "RUN_FINISHED") finished = true;
      if (data.type === "RUN_ERROR") throw new Error(data.message || "Chat run failed");
    }
  }
  if (!finished) throw new Error("Chat stream ended before completion");
}

export async function streamReasoning(workflowId, runIds, onEvent, signal) {
  const context = currentSelection();
  const { consumeReasoningStream } = await import("./prism-reasoning.js");
  const query = new URLSearchParams({ workflow_id: workflowId, run_ids: runIds.join(",") });
  const response = await fetch(`${apiBaseUrl}/api/prism/runs/reasoning?${query}`, {
    credentials: "include", headers: { Accept: "text/event-stream", ...selectionHeaders(context) }, signal,
  });
  return consumeReasoningStream(response, (event) => { if (currentSelection() === context) onEvent(event); }, signal);
}
