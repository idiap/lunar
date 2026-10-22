// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { applyReasoningSnapshot } from "./prism-reasoning.js";

export function plannerResult(content) {
  try {
    let result = typeof content === "string" ? JSON.parse(content) : content;
    if (result?.structuredContent) result = result.structuredContent;
    if (result?.result) result = result.result;
    return result && typeof result === "object" ? result : null;
  } catch { return null; }
}

export function applyPlannerSnapshot(messages, event) {
  return messages.map((item) => {
    if (item.id !== event.tool_call_id || item.name !== "planner") return item;
    const snapshot = event.snapshot;
    if (!snapshot?.run_id || (item.reasoning && item.reasoning.run_id !== snapshot.run_id)) return item;
    if (item.reasoning?.state !== "running" && snapshot.state === "running" && item.reasoning) return item;
    const updated = applyReasoningSnapshot({}, snapshot, [snapshot.run_id])[snapshot.run_id];
    return updated ? { ...item, reasoning: updated } : item;
  });
}

export function completePlanner(item, output) {
  const result = plannerResult(output);
  return { ...item, output, result, reasoning: result?.reasoning || item.reasoning,
    status: result?.status === "failed" || result?.error ? "failed" : "complete" };
}

export function failRunningTools(messages, error) {
  return messages.map((item) => item.role === "tool-activity" && item.status === "running"
    ? { ...item, status: "failed", error, reasoning: item.reasoning ? { ...item.reasoning, state: "failed" } : null }
    : item);
}

export function visibleMessages(protocolMessages) {
  const outputs = new Map(protocolMessages.filter((m) => m.role === "tool").map((m) => [m.toolCallId, m.content]));
  const visible = [];
  for (const message of protocolMessages) {
    if (["user", "assistant"].includes(message.role) && message.content) {
      visible.push({ id: message.id, role: message.role, content: message.content });
    }
    for (const call of message.toolCalls || []) {
      const item = { id: call.id, role: "tool-activity", name: call.function.name, input: call.function.arguments };
      visible.push(outputs.has(call.id) ? completePlanner(item, outputs.get(call.id))
        : { ...item, status: "failed", error: "This historical tool call has no saved result." });
    }
  }
  return visible;
}
