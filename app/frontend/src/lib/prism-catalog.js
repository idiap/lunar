// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { validatePrismBundle } from "./prism-viewer.js";
import { api } from "./api.js";
import { currentSelection, onSelectionChange } from "./package-selection.js";

const cache = new Map();
onSelectionChange(() => cache.clear());
function load(kind, validate, versionId) {
  const context = currentSelection();
  const requestedVersionId = versionId || context.versionId;
  const key = JSON.stringify([context.userId, requestedVersionId, kind]);
  if (!cache.has(key)) {
    const promise = api(`/api/repository/${kind}`, requestedVersionId ? {
      headers: { "X-Lunar-Package-Version": requestedVersionId },
    } : {}).then(validate);
    cache.set(key, promise);
    promise.catch(() => { if (cache.get(key) === promise) cache.delete(key); });
  }
  return cache.get(key);
}
export function loadPrismCatalog(versionId) {
  return load("catalog", (catalog) => {
    if (catalog.schema_version !== 1 || !["public", "reviewed", "package"].includes(catalog.visibility)) {
      throw new Error("The Prism catalog has an unsupported format");
    }
    return catalog;
  }, versionId);
}
export function loadPrismBundle() { return load("bundle", validatePrismBundle); }
