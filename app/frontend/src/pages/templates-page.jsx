// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { FileText } from "lucide-react";

import { LibraryPage } from "@/pages/library-page";

const config = {
  title: "Templates",
  singular: "Template",
  listEndpoint: "/api/templates",
  createEndpoint: "/api/templates",
  deleteEndpoint: "/api/templates",
  basePath: "/templates",
  icon: FileText,
  fields: [{ name: "name", label: "Template name", required: true }],
  createPayload: ({ name }) => ({ name, content: "# New Template\n\nStart writing your template here…" }),
  itemDescription: (item) => (item.content || "").slice(0, 110),
  itemDate: (item) => item.updated_at,
  emptyTitle: "No templates yet",
  emptyDescription: "Create your first reusable template.",
};

export function TemplatesPage() {
  return <LibraryPage config={config} />;
}
