// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { BackButton } from "@/components/back-button";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { TypedReport } from "@/components/prism/typed-report";
import { NativeReport } from "@/components/prism/native-report";
import { NativeHtmlReport } from "@/components/prism/native-html-report";
import { ReportChat } from "@/components/prism/report-chat";
import { ReportSourceFiles } from "@/components/prism/report-source-files";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { latestOutput } from "@/lib/prism-runs";
import { humanize } from "@/lib/prism-viewer";

export function PrismRunReportPage() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    api(`/api/prism/runs/${encodeURIComponent(runId)}`)
      .then((value) => { if (active) setRun(value); })
      .catch((reason) => { if (active) setError(reason); });
    return () => { active = false; };
  }, [runId]);

  if (error?.status === 404) return <EmptyState icon={FileText} title="Report not found" description="This run does not exist or belongs to another user." />;
  if (error) return <PageError error={error} />;
  if (!run) return <LoadingState label="Loading report…" />;
  const output = latestOutput(run);
  if (!output?.markdown) return <EmptyState icon={FileText} title="No report available" description="This run did not emit a report-compatible output." />;


  return (
    <section className="prism-run-page">
      <BackButton to={`/prism/runs/${encodeURIComponent(run.id)}`} />
      <PageHeader title={output.structured_value?.typed_report?.report.title || humanize(run.workflow_id)} />
      <Card className="run-report">{output.structured_value?.typed_report ? <TypedReport report={{ id: output.id, run_id: run.id, typed_report: output.structured_value.typed_report }} /> : output.structured_value?.html_report ? <NativeHtmlReport run={run} output={output} /> : <NativeReport run={run} output={output} />}<ReportSourceFiles run={run} /></Card>
      <ReportChat key={run.id} run={run} output={output} />
    </section>
  );
}
