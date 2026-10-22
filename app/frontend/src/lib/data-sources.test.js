// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";

import {
  dataSourceListPath,
  dataSourceQuery,
  dataSourceSearchParams,
  isSafeExternalUri,
} from "./data-sources.js";

test("data source query uses stable one-based defaults", () => {
  assert.deepEqual(dataSourceQuery(new URLSearchParams()), { q: "", page: 1 });
  assert.deepEqual(dataSourceQuery(new URLSearchParams("q=geo&page=3")), { q: "geo", page: 3 });
  assert.equal(dataSourceQuery(new URLSearchParams("page=0")).page, 1);
});

test("changed searches reset pagination and preserve URL state", () => {
  assert.equal(dataSourceSearchParams(" GEO ", 1).toString(), "q=GEO");
  assert.equal(dataSourceListPath({ q: "single cell", page: 2 }), "/data-sources?q=single+cell&page=2");
});

test("only HTTP URLs are safe external links", () => {
  assert.equal(isSafeExternalUri("https://example.org/data"), true);
  assert.equal(isSafeExternalUri("javascript:alert(1)"), false);
  assert.equal(isSafeExternalUri("/private/data"), false);
});
