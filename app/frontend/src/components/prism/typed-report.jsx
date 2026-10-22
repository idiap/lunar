// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { GitBranch } from "lucide-react";
import { reportUrl } from "@/lib/report-attachments";
import { sectionProvenancePath } from "@/lib/template-bindings";
import "./typed-report.css";

function Provenance({ report, node }) {
  return <Link className="typed-section-provenance" aria-label={`Show provenance for ${node.id}`}
    to={report.run_id ? `/prism/runs/${encodeURIComponent(report.run_id)}/provenance?section=${encodeURIComponent(node.id)}` : sectionProvenancePath(report.id, node.id)}><GitBranch aria-hidden="true" />Provenance</Link>;
}

function Image({ report, attachment, alt }) {
  const [broken, setBroken] = useState(false);
  const asset = report.attachments?.find((item) => item.link === attachment);
  if (!asset?.url?.startsWith("/api/package-files/") || broken) {
    return <p role="alert" className="report-artifact-error">Image unavailable: {alt || attachment}</p>;
  }
  return <img src={reportUrl(report, attachment)} alt={alt} onError={() => setBroken(true)} />;
}

function contains(node, target) {
  return node.id === target || (node.tabs || node.sections || []).some((child) => contains(child, target));
}

function SectionTabs({ node, report, target }) {
  const [selected, setSelected] = useState(() => node.tabs.find((tab) => contains(tab, target))?.id || node.tabs[0]?.id);
  if (!node.tabs.length) return <p role="alert">Unsupported typed report: empty tabs.</p>;
  return <div className="report-tabs">
    <div role="tablist" aria-label={`Report tabs ${node.id}`}>{node.tabs.map((tab, index) => <button
      key={tab.id} id={`typed-tab-${tab.id}`} role="tab" aria-controls={`typed-panel-${tab.id}`}
      aria-selected={selected === tab.id} tabIndex={selected === tab.id ? 0 : -1}
      onClick={() => setSelected(tab.id)} onKeyDown={(event) => {
        const next = { ArrowRight: (index + 1) % node.tabs.length, ArrowLeft: (index + node.tabs.length - 1) % node.tabs.length,
          Home: 0, End: node.tabs.length - 1 }[event.key];
        if (next !== undefined) {
          event.preventDefault();
          setSelected(node.tabs[next].id);
          document.getElementById(`typed-tab-${node.tabs[next].id}`)?.focus();
        }
      }}>{tab.label}</button>)}</div>
    {node.tabs.map((tab) => <section key={tab.id} id={`typed-panel-${tab.id}`} role="tabpanel"
      aria-labelledby={`typed-tab-${tab.id}`} hidden={selected !== tab.id} data-section-id={tab.id}>
      {selected === tab.id && <><Provenance report={report} node={tab} />
        <Sections nodes={tab.sections} report={report} target={target} /></>}
    </section>)}
  </div>;
}

function Content({ node, report, target }) {
  switch (node.kind) {
    case "markdown": return <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(value) => reportUrl(report, value)}
      components={{ img: ({ src, alt }) => <Image report={report} attachment={report.attachments?.find((item) => item.url === src)?.link || src} alt={alt} /> }}>
      {node.text}</ReactMarkdown>;
    case "html": return <iframe title={`HTML section ${node.id}`} sandbox="" referrerPolicy="no-referrer"
      srcDoc={`<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><body>${node.text}</body>`}
      style={{ width: "100%", minHeight: "240px", border: 0, background: "white" }} />;
    case "image": return <Image key={node.attachment} report={report} attachment={node.attachment} alt={node.alt} />;
    case "tabs": return <SectionTabs node={node} report={report} target={target} />;
    default: return <p role="alert">Unsupported typed section: {String(node.kind)}</p>;
  }
}

function Sections({ nodes, report, target }) {
  return nodes.map((node) => <section key={node.id} id={`typed-${encodeURIComponent(node.id)}`}
    className="typed-section" data-section-id={node.id}>
    <Provenance report={report} node={node} />
    <Content node={node} report={report} target={target} />
  </section>);
}

export function TypedReport({ report }) {
  const { hash } = useLocation();
  const typed = report.typed_report;
  if (typed?.version !== "1" || !Array.isArray(typed.report?.sections)) {
    return <p role="alert" className="report-artifact-error">Unsupported typed report.</p>;
  }
  let target = "";
  try { target = decodeURIComponent(hash.replace(/^#typed-/, "")); } catch { /* No valid section target. */ }
  return <div className="typed-report">
    <p className="generated-report-meta">{typed.report.template ? `Template: ${typed.report.template.title} (${typed.report.template.id})` : "No structural template"}</p>
    <Sections key={target} nodes={typed.report.sections} report={report} target={target} />
  </div>;
}
