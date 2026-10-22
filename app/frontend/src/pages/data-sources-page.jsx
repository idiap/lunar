// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { ChevronRight, Database, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Searchbar } from "@/components/ui/searchbar";
import { api } from "@/lib/api";
import {
  DATA_SOURCE_PAGE_SIZE,
  dataSourceQuery,
  dataSourceSearchParams,
} from "@/lib/data-sources";

export function DataSourcesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { q, page } = dataSourceQuery(searchParams);
  const [search, setSearch] = useState(q);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => setSearch(q), [q]);
  useEffect(() => {
    let active = true;
    setResult(null);
    setError(null);
    const params = dataSourceSearchParams(q, page);
    params.set("page_size", String(DATA_SOURCE_PAGE_SIZE));
    api(`/api/data-sources?${params}`)
      .then((value) => { if (active) setResult(value); })
      .catch((reason) => { if (active) setError(reason); });
    return () => { active = false; };
  }, [q, page]);

  function submit(event) {
    event.preventDefault();
    setSearchParams(dataSourceSearchParams(search, 1));
  }

  if (error) return <PageError error={error} />;

  return (
    <section className="data-sources-page">
      <PageHeader title="Data Sources" />
      <form className="data-source-search" role="search" onSubmit={submit}>
        <Searchbar
          label="Search data sources"
          placeholder="Search by name, ID, category, alias, or modality"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {search && (
          <Button type="button" variant="ghost" onClick={() => { setSearch(""); setSearchParams({}); }}>
            <X aria-hidden="true" /> Clear
          </Button>
        )}
        <Button type="submit">Search</Button>
      </form>
      {!result ? <LoadingState label="Loading data sources…" /> : (
        <>
          <p className="data-source-result-count">{result.total.toLocaleString()} result{result.total === 1 ? "" : "s"}</p>
          {result.items.length ? (
            <div className="data-source-list" aria-label="Data sources">
              {result.items.map((source) => (
                <Card className="data-source-row" key={source.resource_id}>
                  <Link to={`/data-sources/${encodeURIComponent(source.resource_id)}`}>
                    <span className="asset-icon"><Database aria-hidden="true" /></span>
                    <span className="data-source-copy">
                      <strong>{source.name}</strong>
                      <small>{source.resource_id} · {source.category} · {source.visibility || "package"}</small>
                      <span>{source.scope || "No scope summary supplied."}</span>
                    </span>
                    <span className={`source-posture posture-${source.posture}`}>{(source.posture || "Not specified").replaceAll("_", " ")}</span>
                    <ChevronRight aria-hidden="true" />
                  </Link>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Database}
              title="No data sources found"
              description={q ? `No catalog entry matches “${q}”.` : "The data-source catalog is empty."}
            />
          )}
          <nav className="pagination" aria-label="Data source pages">
            <Button
              variant="outline"
              disabled={page <= 1}
              onClick={() => setSearchParams(dataSourceSearchParams(q, page - 1))}
            >Previous</Button>
            <span>Page {result.page} of {Math.max(result.total_pages, 1)} · {result.total.toLocaleString()} total</span>
            <Button
              variant="outline"
              disabled={page >= result.total_pages}
              onClick={() => setSearchParams(dataSourceSearchParams(q, page + 1))}
            >Next</Button>
          </nav>
        </>
      )}
    </section>
  );
}
