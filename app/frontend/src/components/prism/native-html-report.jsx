// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { apiText } from "@/lib/api";
import { nativeHtmlReport, verifiedHtmlDocument } from "@/lib/prism-runs";

export function NativeHtmlReport({ run, output }) {
  const [document, setDocument] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    setDocument(null);
    setError(null);
    (async () => {
      const report = nativeHtmlReport(run, output);
      const source = await apiText(report.url, { signal: controller.signal, maxBytes: 64 * 1024 * 1024 });
      const verified = await verifiedHtmlDocument(source, report.sha256);
      if (!controller.signal.aborted) setDocument(verified);
    })().catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [run, output]);
  if (error) return <p role="alert" className="report-artifact-error">{error}</p>;
  if (!document) return <p role="status">Verifying HTML report…</p>;
  return <iframe title="Discovery Marathon report" sandbox="allow-scripts"
    referrerPolicy="no-referrer" srcDoc={document}
    style={{ width: "100%", height: "85vh", border: 0, background: "white" }} />;
}
