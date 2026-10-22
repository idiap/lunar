// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { GitBranch, Lock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { TypedReport } from "@/components/prism/typed-report";
import { BackButton } from "@/components/back-button";
import { LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { reportUrl } from "@/lib/report-attachments";
import { api } from "@/lib/api";
import { reportContentSegments, sectionProvenancePath } from "@/lib/template-bindings";
import { DocumentEditorPage } from "@/pages/document-editor-page";

const config = {
  endpoint: "/api/report",
  back: "/reports",
  contentLabel: "Report content",
  rows: 26,
};

export function ReportEditorPage() {
  const { id } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [selectedSection, setSelectedSection] = useState(null);
  useEffect(() => { api(`/api/report/${id}`).then(setReport).catch(setError); }, [id]);
  const segments = useMemo(
    () => report?.typed_report ? [] : reportContentSegments(report?.content || "", report?.sections),
    [report],
  );
  if (error) return <PageError error={error} />;
  if (!report) return <LoadingState label="Loading report…" />;
  if (!report.typed_report && report.generation_type !== "template" && !report.read_only) return <DocumentEditorPage config={config} />;
  return (
    <section className="generated-report-page">
      <BackButton to="/reports" />
      <PageHeader
        title={report.name}
        actions={<Link className={buttonVariants({ variant: "outline" })} to={`/reports/${id}/provenance`}><GitBranch aria-hidden="true" />Provenance</Link>}
      />
      <div className="generated-report-meta"><Lock aria-hidden="true" />{report.template_id ? <span>Template <Link to={`/templates/${encodeURIComponent(report.template_id)}`}><strong>{report.template_name || "Open template"}</strong></Link></span> : <span>{report.generation_type === "template" ? "Template unavailable" : "Imported workflow report"}</span>}<span>{report.sections?.length || 0} traceable sections</span></div>
      <Card className="generated-report-markdown">
        {report.typed_report ? <TypedReport report={report} /> : segments.map((segment, index) => segment.section ? (
          <section className="generated-report-section" key={segment.section.section_id}>
            <Button
              className="generated-section-provenance"
              variant="ghost"
              size="icon"
              aria-label={`Show provenance for ${segment.section.placeholder_name}`}
              title="Show section provenance"
              onClick={() => setSelectedSection(segment.section)}
            >
              <GitBranch aria-hidden="true" />
            </Button>
            <ReactMarkdown urlTransform={(value) => reportUrl(report, value)} remarkPlugins={[remarkGfm]}>{segment.content}</ReactMarkdown>
          </section>
        ) : (
          <ReactMarkdown key={`markdown-${index}`} urlTransform={(value) => reportUrl(report, value)} remarkPlugins={[remarkGfm]}>{segment.content}</ReactMarkdown>
        ))}
      </Card>
      <Dialog open={Boolean(selectedSection)} onOpenChange={(open) => { if (!open) setSelectedSection(null); }}>
        {selectedSection && <DialogContent className="section-provenance-dialog">
          <DialogHeader>
            <DialogTitle>Section provenance</DialogTitle>
            <DialogDescription>Traceability details for this generated report section.</DialogDescription>
          </DialogHeader>
          <div className="section-provenance-card">
            <strong>{selectedSection.placeholder_name}</strong>
            <code>{selectedSection.content_digest}</code>
          </div>
          <Link className={buttonVariants({ variant: "outline" })} to={sectionProvenancePath(id, selectedSection.section_id)}>
            <GitBranch aria-hidden="true" />View section provenance
          </Link>
        </DialogContent>}
      </Dialog>
    </section>
  );
}
