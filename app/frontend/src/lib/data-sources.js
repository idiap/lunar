// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export const DATA_SOURCE_PAGE_SIZE = 20;

export function dataSourceQuery(searchParams) {
  const rawPage = Number.parseInt(searchParams.get("page") || "1", 10);
  return {
    q: (searchParams.get("q") || "").trim(),
    page: Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1,
  };
}

export function dataSourceSearchParams(q, page = 1) {
  const params = new URLSearchParams();
  const query = q.trim();
  if (query) params.set("q", query);
  if (page > 1) params.set("page", String(page));
  return params;
}

export function dataSourceListPath({ q, page }) {
  const query = dataSourceSearchParams(q, page).toString();
  return query ? `/data-sources?${query}` : "/data-sources";
}

export function isSafeExternalUri(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}
