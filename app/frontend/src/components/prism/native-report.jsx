// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Children, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ReportCodeBlock } from "./report-source-files";
import { ReportInlineCode } from "./report-math";
import "./native-report.css";
import { headingAnchor, nativeReportTree, reportHeadings, reportTarget, verifyReportLayout } from "@/lib/prism-runs";

function nodeText(children) {
  return Children.toArray(children).map((child) => (
    typeof child === "string" || typeof child === "number" ? String(child) : ""
  )).join("");
}

function ReportImage({ run, src, alt }) {
  const [broken, setBroken] = useState(false);
  const resolved = reportTarget(run, src);
  if (!resolved || broken) {
    return <span className="report-artifact-error" role="alert">Artifact unavailable: {alt || src}</span>;
  }
  return <a href={resolved} aria-label={`Open full-size figure: ${alt || "Scientific figure"}`}><img src={resolved} alt={alt || ""} onError={() => setBroken(true)} /></a>;
}

function containsAnchor(node, id) {
  return Boolean(id && (node.headingId === id || node.anchors?.includes(id) || node.children?.some((child) => containsAnchor(child, id))));
}

function hashTarget() {
  try { return decodeURIComponent(window.location.hash.slice(1)); } catch { return ""; }
}

function ReportDisclosure({ node, components }) {
  const [open, setOpen] = useState(() => containsAnchor(node, hashTarget()));
  useEffect(() => {
    const reveal = () => { if (containsAnchor(node, hashTarget())) setOpen(true); };
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, [node]);
  return <details className="report-disclosure" data-report-group={node.key} open={open}
    onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{node.label || "Supporting evidence"}</summary>
    {open && <ReportChildren nodes={node.children} components={components} />}
  </details>;
}

function ReportTabs({ groups, components }) {
  const [selected, setSelected] = useState(groups[0].key);
  useEffect(() => {
    const reveal = () => {
      const id = hashTarget();
      const group = groups.find((item) => containsAnchor(item, id));
      if (group) setSelected(group.key);
    };
    window.addEventListener("hashchange", reveal);
    reveal();
    return () => window.removeEventListener("hashchange", reveal);
  }, [groups]);
  return <div className="report-tabs">
    <div role="tablist" aria-label="Report views">{groups.map((group, index) => <button
      key={group.key} id={`tab-${group.key}`} role="tab" aria-controls={`panel-${group.key}`}
      aria-selected={selected === group.key} tabIndex={selected === group.key ? 0 : -1}
      onClick={() => setSelected(group.key)}
      onKeyDown={(event) => {
        const directions = { ArrowRight: (index + 1) % groups.length, ArrowLeft: (index + groups.length - 1) % groups.length, Home: 0, End: groups.length - 1 };
        if (event.key in directions) {
          event.preventDefault();
          const next = groups[directions[event.key]].key;
          setSelected(next);
          document.getElementById(`tab-${next}`)?.focus();
        }
      }}
    >{group.label}</button>)}</div>
    {groups.map((group) => <section key={group.key} id={`panel-${group.key}`} role="tabpanel"
      aria-labelledby={`tab-${group.key}`} hidden={selected !== group.key} data-report-group={group.key}>
      {selected === group.key && <ReportChildren nodes={group.children} components={components} />}
    </section>)}
  </div>;
}

function ReportChildren({ nodes, components }) {
  const children = [];
  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (node.presentation === "metric") {
      const metrics = [node];
      while (nodes[index + 1]?.presentation === "metric") metrics.push(nodes[++index]);
      children.push(<div key={node.key} className="report-metrics">{metrics.map((metric) => <div key={metric.key} className="report-metric"><ReportChildren nodes={metric.children} components={components} /></div>)}</div>);
    } else if (node.kind === "tab") {
      const tabs = [node];
      while (nodes[index + 1]?.kind === "tab") tabs.push(nodes[++index]);
      children.push(<ReportTabs key={node.key} groups={tabs} components={components} />);
    } else if (node.children) {
      const content = <ReportChildren nodes={node.children} components={components} />;
      if (node.kind === "disclosure") {
        children.push(<ReportDisclosure key={node.key} node={node} components={components} />);
      } else {
        const className = node.kind === "figure_group" ? (node.visual_count > 1 ? "report-figure-grid" : "report-figure") : "report-card";
        children.push(<div key={node.key} className={className} data-report-group={node.key}>{content}</div>);
      }
    } else {
      const overrides = node.headingId ? Object.fromEntries(["h1", "h2", "h3", "h4"].map((Tag) => [Tag, ({ children }) => <Tag id={node.headingId}>{children}</Tag>])) : {};
      children.push(<div key={node.id} className="report-block" data-report-block={node.id} data-kind={node.kind}>
        {node.anchors.map((id) => <span key={id} id={id} className="report-anchor" />)}
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ ...components, ...overrides }}>{node.markdown}</ReactMarkdown>
      </div>);
    }
  }
  return children;
}

function ReportBody({ output, components }) {
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState(null);
  const tree = useMemo(() => {
    try { return { nodes: nativeReportTree(output) }; } catch (reason) { return { error: reason.message }; }
  }, [output]);
  useEffect(() => {
    let active = true;
    setVerified(false);
    setError(null);
    verifyReportLayout(output).then(() => { if (active) setVerified(true); }).catch((reason) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [output]);
  useEffect(() => {
    if (!verified) return;
    const reveal = () => {
      let id;
      try { id = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
      const target = document.getElementById(id);
      if (!target) return;
      for (let parent = target.parentElement; parent; parent = parent.parentElement) {
        if (parent.tagName === "DETAILS") parent.open = true;
      }
      requestAnimationFrame(() => requestAnimationFrame(() => target.scrollIntoView({ block: "start" })));
    };
    window.addEventListener("hashchange", reveal);
    reveal();
    return () => window.removeEventListener("hashchange", reveal);
  }, [verified]);
  if (error || tree.error) return <p className="report-artifact-error" role="alert">{error || tree.error}</p>;
  if (!verified) return <p role="status">Verifying report content…</p>;
  return tree.nodes ? <ReportChildren nodes={tree.nodes} components={components} /> : <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{output.markdown}</ReactMarkdown>;
}

export function NativeReport({ run, output }) {
  const nativeHeadings = output.structured_value?.report_layout?.blocks?.filter((block) => block.kind === "heading");
  const headings = reportHeadings(output.markdown).map((heading, index) => ({ ...heading, id: nativeHeadings?.[index]?.heading_key || heading.id }));
  const headingIds = new Map();
  headings.forEach((item) => {
    const values = headingIds.get(item.text) || [];
    values.push(item.id);
    headingIds.set(item.text, values);
  });
  const renderedHeadings = new Map();
  const heading = (Tag, children) => {
    const text = nodeText(children);
    const ordinal = renderedHeadings.get(text) || 0;
    renderedHeadings.set(text, ordinal + 1);
    return <Tag id={headingIds.get(text)?.[ordinal] || headingAnchor(text)}>{children}</Tag>;
  };
  const components = {
    pre: ReportCodeBlock,
    code: ReportInlineCode,
    h1: ({ children }) => heading("h1", children),
    h2: ({ children }) => heading("h2", children),
    h3: ({ children }) => heading("h3", children),
    h4: ({ children }) => heading("h4", children),
    img: (props) => <ReportImage run={run} {...props} />,
    table: ({ children }) => <div className="report-table-scroll" tabIndex={0} aria-label="Scrollable report table"><table>{children}</table></div>,
    a: ({ href, children }) => {
      const resolved = reportTarget(run, href);
      if (!resolved) return <span className="report-artifact-error">{children}</span>;
      const external = /^https?:/i.test(resolved);
      return <a href={resolved} rel={external ? "noreferrer noopener" : undefined}>{children}</a>;
    },
  };
  return <ReportBody output={output} components={components} />;
}
