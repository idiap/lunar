// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
let selection = Object.freeze({ userId: null, versionId: null });
const listeners = new Set();

export function currentSelection() { return selection; }
export function setSelection(userId, versionId = null) {
  if (selection.userId === userId && selection.versionId === versionId) return selection;
  selection = Object.freeze({ userId, versionId });
  listeners.forEach((listener) => listener());
  return selection;
}
export function onSelectionChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function selectionHeaders(context = selection) {
  return context.versionId ? { "X-Lunar-Package-Version": context.versionId } : {};
}
export function assertCurrent(context) {
  if (selection !== context) throw new DOMException("Workspace selection changed", "AbortError");
}
