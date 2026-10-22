// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { FileText } from "lucide-react";

import { LibraryPage } from "@/pages/library-page";
import { runReportPath, reportHeadings, reportRunDescription } from "@/lib/prism-runs";

const config = {
  title: "Reports",
  singular: "Report",
  listEndpoint: "/api/report?limit=none",
  createEndpoint: "/api/report",
  deleteEndpoint: "/api/report",
  basePath: "/reports",
  icon: FileText,
  fields: [
    { name: "name", label: "Report name", required: true },
    { name: "content", label: "Initial content", type: "textarea", value: "# New Report\n\n", required: true },
  ],
  createPayload: (values) => values,
  itemPath: (item) => item.generation_type === "prism" ? runReportPath(item.run_id) : `/reports/${item.id}`,
  canDelete: (item) => item.generation_type !== "prism",
  itemTitle: (item) => item.generation_type === "prism" && item.imported
    ? reportHeadings(item.content)[0]?.text || item.name : item.name,
  itemDescription: (item) => item.generation_type === "prism"
    ? reportRunDescription(item)
    : `Version ${item.version} · ${(item.content || "").replace(/[#*_]/g, "").slice(0, 90)}`,
  itemDate: (item) => item.created_at,
  emptyTitle: "No reports yet",
  emptyDescription: "Run a .prism workflow, create a report here, or publish a quality-released artifact through MCP.",
};

export function ReportsPage() {
  return <LibraryPage config={config} />;
}
