// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useRef } from "react";

import { authoredValues, mainLabel, prismFileNavigationIndex, tokenizePrismLine } from "@/lib/prism-viewer";

function tokenDestination(token, source, lineNumber, index) {
  const symbol = token.text;
  const moduleName = symbol.includes(".") ? symbol.split(".").at(-1) : "";
  const declarationTargets = index.declarations.get(symbol) || [];
  const moduleTarget = moduleName && index.modules.get(moduleName);
  const targets = moduleTarget ? [{ source: moduleTarget, line: 1 }] : declarationTargets;
  return targets.find((item) => item.source.path !== source.path || item.line !== lineNumber) || null;
}

function occurrenceLines(workflow, source) {
  if (source.file_type !== "reasoning" || source.content !== workflow.source_text) return new Map();
  const graph = workflow.graph;
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const lines = new Map();
  graph.nodes.filter((node) => node.kind === "occurrence").forEach((node) => {
    const incoming = graph.edges.filter((edge) => edge.target === node.id).map((edge) => byId.get(edge.source));
    if (!authoredValues(incoming).length && !authoredValues([node]).length) return;
    const span = node.source_span;
    if (!span || !Number.isInteger(span.line) || !Number.isInteger(span.end_line)) return;
    for (let line = span.line; line <= span.end_line; line += 1) {
      if (!lines.has(line)) lines.set(line, []);
      lines.get(line).push(node);
    }
  });
  return new Map([...lines].filter(([, nodes]) => nodes.length === 1).map(([line, nodes]) => [line, nodes[0]]));
}

export function PrismCode({
  activeSpan,
  focusLine,
  onNavigate,
  onOccurrenceHover,
  source,
  sources,
  workflow,
}) {
  const lineRefs = useRef(new Map());
  const navigation = useMemo(() => prismFileNavigationIndex(sources), [sources]);
  const interactiveLines = useMemo(() => occurrenceLines(workflow, source), [source, workflow]);
  const lines = source.content ? source.content.split("\n") : [];

  useEffect(() => {
    const targetLine = focusLine || activeSpan?.line;
    if (targetLine) lineRefs.current.get(targetLine)?.scrollIntoView({ block: "center", behavior: "auto" });
  }, [activeSpan, focusLine, source.path]);

  if (!source.content) return <span className="source-unavailable">Source text is unavailable in this bundle.</span>;
  return lines.map((line, lineIndex) => {
    const lineNumber = lineIndex + 1;
    const node = interactiveLines.get(lineNumber);
    const active = activeSpan && lineNumber >= activeSpan.line && lineNumber <= activeSpan.end_line;
    const focused = focusLine === lineNumber;
    return (
      <span key={lineNumber}>
        <span
          ref={(element) => {
            if (element) lineRefs.current.set(lineNumber, element);
            else lineRefs.current.delete(lineNumber);
          }}
          className={`source-line${active ? " active" : ""}${focused ? " file-navigation-target" : ""}${node ? " reasoning-step-source" : ""}`}
          data-line={lineNumber}
          data-node-id={node?.id}
          tabIndex={node ? 0 : undefined}
          aria-label={node ? `${mainLabel(node)}. Show concrete input and output values.` : undefined}
          onMouseEnter={node ? (event) => onOccurrenceHover?.(node, event) : undefined}
          onMouseMove={node ? (event) => onOccurrenceHover?.(node, event) : undefined}
          onMouseLeave={node ? () => onOccurrenceHover?.(null) : undefined}
          onFocus={node ? (event) => onOccurrenceHover?.(node, event) : undefined}
          onBlur={node ? () => onOccurrenceHover?.(null) : undefined}
        >
          <span className="line-number" aria-hidden="true">{lineNumber}</span>
          <span className="line-content">
            {tokenizePrismLine(line).map((token, tokenIndex) => {
              const target = tokenDestination(token, source, lineNumber, navigation);
              const semantic = activeSpan?.symbols?.includes(token.text)
                || activeSpan?.symbols?.includes(token.text.split(".").at(-1));
              const className = [
                "source-token",
                token.kind && `tok-${token.kind}`,
                target && "source-navigation-link",
                semantic && "semantic-active",
              ].filter(Boolean).join(" ");
              if (!target) return <span className={className} key={tokenIndex}>{token.text}</span>;
              return (
                <span
                  className={className}
                  role="link"
                  tabIndex={0}
                  title={`Open ${target.source.file_type} · ${target.source.path}:${target.line}`}
                  onClick={(event) => { event.stopPropagation(); onNavigate(target); }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    event.stopPropagation();
                    onNavigate(target);
                  }}
                  key={tokenIndex}
                >
                  {token.text}
                </span>
              );
            })}
          </span>
        </span>
        {lineIndex < lines.length - 1 ? "\n" : null}
      </span>
    );
  });
}
