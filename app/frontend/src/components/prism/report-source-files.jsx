// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { Check, Copy, Download, FileCode2 } from "lucide-react";

import { apiText } from "@/lib/api";
import { codeLanguage, highlightSource, reportSourceFiles } from "@/lib/source-highlighter";

export function HighlightedCode({ source, language, label = "Source code" }) {
  const [highlighted, setHighlighted] = useState(null);
  useEffect(() => {
    let active = true;
    highlightSource(source, language).then((tokens) => {
      if (active) setHighlighted({ source, language, tokens });
    }).catch(() => { if (active) setHighlighted(null); });
    return () => { active = false; };
  }, [source, language]);
  const tokens = highlighted?.source === source && highlighted?.language === language ? highlighted.tokens : null;
  return <pre className="report-source-code" tabIndex={0} aria-label={label}><code className={`language-${language}`}>
    {tokens ? tokens.map((line, index) => <span className="source-line" key={index}>
      {line.map((token, i) => <span key={i} style={{ color: token.color,
        fontStyle: token.fontStyle & 1 ? "italic" : undefined,
        fontWeight: token.fontStyle & 2 ? 600 : undefined,
        textDecoration: token.fontStyle & 4 ? "underline" : undefined,
      }}>{token.content}</span>)}{index < tokens.length - 1 ? "\n" : ""}
    </span>) : source}
  </code></pre>;
}

export function ReportCodeBlock({ children }) {
  const child = Array.isArray(children) ? children[0] : children;
  const language = codeLanguage(/\blanguage-([^\s]+)/.exec(child?.props?.className || "")?.[1]);
  if (!language || typeof child?.props?.children !== "string") return <pre>{children}</pre>;
  return <HighlightedCode source={child.props.children} language={language} label="Lean code" />;
}

function SourcePreview({ file }) {
  const [state, setState] = useState({});
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setState({});
    apiText(file.url, { signal: controller.signal })
      .then((source) => { if (!controller.signal.aborted) setState({ source }); })
      .catch((error) => { if (!controller.signal.aborted) setState({ error: error.message }); });
    return () => controller.abort();
  }, [file.url]);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(state.source);
      setCopied(true); setCopyError(false);
    } catch { setCopyError(true); }
  }
  return <>
    <div className="report-source-toolbar">
      <span>{file.language === "prism" ? "PRISM" : "Lean 4"}</span>
      <div>
        {typeof state.source === "string" && <button type="button" onClick={copy} aria-label={`Copy ${file.name}`}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}{copied ? "Copied" : "Copy"}
        </button>}
        <a href={file.url} download={file.name.split("/").pop()}><Download aria-hidden="true" />Download</a>
      </div>
    </div>
    {state.error ? <p role="alert" className="report-artifact-error">{state.error}</p>
      : typeof state.source === "string" ? <HighlightedCode source={state.source} language={file.language} label={file.name} />
        : <p role="status">Loading source…</p>}
    {copyError && <p role="status">Could not copy. Select the source text or use Download.</p>}
    {file.aliases.length > 0 && <p className="report-source-aliases">Identical source: {file.aliases.map((alias, index) => <span key={alias.id}>
      {index > 0 ? ", " : ""}<a href={alias.url} download>{alias.name}</a>
    </span>)}</p>}
  </>;
}

function SourceFile({ file, initiallyOpen }) {
  const [expanded, setExpanded] = useState(initiallyOpen);
  return <details className="report-source-file" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary><FileCode2 aria-hidden="true" /><span>{file.name}</span></summary>
    {expanded && <SourcePreview file={file} />}
  </details>;
}

export function ReportSourceFiles({ run }) {
  const files = reportSourceFiles(run);
  if (!files.length) return null;
  return <section className="report-source-files" aria-label="Source files">
    <h2>Source files</h2>
    {files.map((file, index) => <SourceFile key={`${run.id}:${file.id}`} file={file} initiallyOpen={index === 0} />)}
  </section>;
}
