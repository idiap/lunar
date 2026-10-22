// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Database, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BackButton } from "@/components/back-button";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { isSafeExternalUri } from "@/lib/data-sources";

function Value({ value }) {
  if (value === null || value === undefined || value === "") return <span className="muted">Not specified</span>;
  if (typeof value === "string" && isSafeExternalUri(value)) {
    return <a className="external-link" href={value} target="_blank" rel="noreferrer">{value}<ExternalLink aria-hidden="true" /></a>;
  }
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted">None declared</span>;
    return <ul>{value.map((item, index) => <li key={typeof item === "string" ? item : index}><Value value={item} /></li>)}</ul>;
  }
  return (
    <dl className="source-object">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><Value value={item} /></dd></div>
      ))}
    </dl>
  );
}

function DetailSection({ title, value }) {
  return <Card className="source-detail-section"><h2>{title}</h2><Value value={value} /></Card>;
}

export function DataSourceDetailPage() {
  const { resourceId } = useParams();
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setSource(null);
    setError(null);
    api(`/api/data-sources/${encodeURIComponent(resourceId)}`)
      .then((value) => { if (active) setSource(value); })
      .catch((reason) => { if (active) setError(reason); });
    return () => { active = false; };
  }, [resourceId]);

  if (error?.status === 404) return <EmptyState icon={Database} title="Data source not found" description="This catalog resource does not exist." />;
  if (error) return <PageError error={error} />;
  if (!source) return <LoadingState label="Loading data source…" />;

  return (
    <section className="data-source-detail-page">
      <BackButton to="/data-sources" />
      <PageHeader title={source.name} />
      <div className="source-summary">
        <code>{source.resource_id}</code>
        <span>{source.visibility || "Package"}</span>
        <span className={`source-posture posture-${source.posture}`}>{(source.posture || "Not specified").replaceAll("_", " ")}</span>
        <span>Claim ceiling: <strong>{source.claim_ceiling}</strong></span>
      </div>
      {!!source.datasets?.length && <Card className="source-detail-section">
        <h2>Registered datasets</h2>
        
        <ul className="workflow-datasets">{source.datasets.map((dataset) => <li key={dataset.dataset_id}>
          <strong>{dataset.name}</strong>
          <span>{(dataset.status || "Packaged").replaceAll("_", " ")} · {dataset.available_file_count ?? dataset.files?.length ?? 0}/{dataset.file_count ?? dataset.files?.length ?? 0} files available{dataset.kind === "fixture" ? " · Representative test example" : ""}</span>
          {dataset.download_urls?.length > 0 && <details><summary>Public download locations</summary><Value value={dataset.download_urls} /></details>}
        </li>)}</ul>
      </Card>}
      {!!source.workflows?.length && <Card className="source-detail-section"><h2>Used by workflows</h2>
        <ul>{source.workflows.map((workflow) => <li key={workflow.id}><Link to={`/prism?workflow=${encodeURIComponent(workflow.id)}&view=run`}>{workflow.name}</Link></li>)}</ul>
      </Card>}
      <section aria-label="Local source files"><h2>Local files</h2><ul>{(source.local_files || []).map((file) => <li key={file.id}><a href={file.url}>{file.id}</a></li>)}</ul></section>
      <div className="source-detail-grid">
        <DetailSection title="Overview" value={{ canonical_uri: source.canonical_uri, owner: source.owner, aliases: source.aliases }} />
        <DetailSection title="Scope" value={source.scope} />
        <DetailSection title="Modalities" value={source.modalities} />
        <DetailSection title="Entities" value={source.entities} />
        <DetailSection title="Identifiers" value={source.identifiers} />
        <DetailSection title="Access points" value={source.access_points} />
        <DetailSection title="Admitted operations" value={source.operations} />
        <DetailSection title="Candidate operations" value={source.candidate_operations} />
        <DetailSection title="Lineage" value={source.lineage} />
        <DetailSection title="Verification status" value={{ verified_as_of: source.verified_as_of, refresh_trigger: source.refresh_trigger, schema_version: source.schema_version, catalog_digest: source.catalog_digest }} />
      </div>
    </section>
  );
}
