// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useParams, useSearchParams } from "react-router-dom";

import { ProvenanceExplorer } from "@/pages/provenance-page";

export function ReportProvenancePage() {
  const { reportId } = useParams();
  const [searchParams] = useSearchParams();
  const sectionId = searchParams.get("section");
  const base = `/api/report/${encodeURIComponent(reportId)}/provenance`;
  const endpoint = sectionId
    ? `/api/report/${encodeURIComponent(reportId)}/sections/${encodeURIComponent(sectionId)}/provenance`
    : base;
  return <ProvenanceExplorer
    resourceId={sectionId || reportId}
    endpoint={endpoint}
    downloadEndpoint={base}
    back={`/reports/${reportId}${sectionId ? `#typed-${encodeURIComponent(sectionId)}` : ""}`}
    title={sectionId ? `Section lineage · ${sectionId}` : "Report lineage"}
  />;
}
