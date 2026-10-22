// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Navigate, Route, Routes } from "react-router-dom";

import { PackageProvider } from "@/context/package-context";
import { AppShell } from "@/components/app-shell";
import { LoadingState } from "@/components/feedback";
import { Toaster } from "@/components/ui/sonner";
import { useAuth } from "@/context/auth-context";
import { AuthPage } from "@/pages/auth-page";
import { ChatPage } from "@/pages/chat-page";
import { DataSourceDetailPage } from "@/pages/data-source-detail-page";
import { DataSourcesPage } from "@/pages/data-sources-page";
import { HomePage } from "@/pages/home-page";
import { ModelEditorPage } from "@/pages/model-editor-page";
import { ModelsPage } from "@/pages/models-page";
import { PromptEditorPage } from "@/pages/prompt-editor-page";
import { PromptsPage } from "@/pages/prompts-page";
import { ProvenancePage } from "@/pages/provenance-page";
import { ReportEditorPage } from "@/pages/report-editor-page";
import { ReportProvenancePage } from "@/pages/report-provenance-page";
import { ReportsPage } from "@/pages/reports-page";
import { RepositoryPage } from "@/pages/repository-page";
import { PrismPage } from "@/pages/prism-page";
import { PrismRunPage } from "@/pages/prism-run-page";
import { PrismRunReportPage } from "@/pages/prism-run-report-page";
import { SkillDetailPage } from "@/pages/skill-detail-page";
import { SkillsPage } from "@/pages/skills-page";
import { TemplateEditorPage } from "@/pages/template-editor-page";
import { TemplatesPage } from "@/pages/templates-page";

function ProtectedRoutes() {
  const { user } = useAuth();
  return user ? <PackageProvider key={user.id}><AppShell /></PackageProvider> : <Navigate to="/signin" replace />;
}

export default function App() {
  const { loading } = useAuth();
  if (loading) return <LoadingState label="Loading workspace…" />;

  return (
    <>
      <Routes>
        <Route path="/signin" element={<AuthPage mode="signin" />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route element={<ProtectedRoutes />}>
          <Route index element={<HomePage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="chat/:id" element={<ChatPage />} />
          <Route path="data-sources" element={<DataSourcesPage />} />
          <Route path="data-sources/:resourceId" element={<DataSourceDetailPage />} />
          <Route path="prompts" element={<PromptsPage />} />
          <Route path="prompts/:id" element={<PromptEditorPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="reports/:id" element={<ReportEditorPage />} />
          <Route path="reports/:reportId/provenance" element={<ReportProvenancePage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="templates/:id" element={<TemplateEditorPage />} />
          <Route path="ai-models" element={<ModelsPage />} />
          <Route path="ai-models/:id" element={<ModelEditorPage />} />
          <Route path="repository" element={<RepositoryPage />} />
          <Route path="prism" element={<PrismPage />} />
          <Route path="prism/runs/:runId" element={<PrismRunPage />} />
          <Route path="prism/runs/:runId/report" element={<PrismRunReportPage />} />
          <Route path="prism/runs/:runId/provenance" element={<ProvenancePage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="skills/:id" element={<SkillDetailPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </>
  );
}
