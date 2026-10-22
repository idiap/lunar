// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { mainLabel, workflowSources } from "@/lib/prism-viewer";
import { PrismCode } from "./prism-code";
import { NodeValues } from "./prism-values";

export function PrismFiles({ workflow }) {
  const sources = useMemo(() => workflowSources(workflow), [workflow]);
  const [selectedPath, setSelectedPath] = useState(sources[0]?.path || "");
  const [focusLine, setFocusLine] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const source = sources.find((item) => item.path === selectedPath) || sources[0];
  const items = sources.map((item) => ({ value: item.path, label: item.path }));

  useEffect(() => {
    setSelectedPath(sources[0]?.path || "");
    setFocusLine(null);
    setTooltip(null);
  }, [sources]);

  if (!source) {
    return <section className="files-panel"><span className="source-unavailable">Source text is unavailable in this bundle.</span></section>;
  }

  const navigate = (target) => {
    setSelectedPath(target.source.path);
    setFocusLine(target.line);
  };
  const showTooltip = (node, event) => {
    if (!node) {
      setTooltip(null);
      return;
    }
    const width = 620;
    setTooltip({
      node,
      left: Math.max(12, Math.min(event.clientX + 18, window.innerWidth - width - 12)),
      top: Math.max(12, Math.min(event.clientY + 18, window.innerHeight - 300)),
    });
  };

  return (
    <section className="files-panel" role="tabpanel" aria-labelledby="files-tab">
      <div className="file-toolbar">
        <label htmlFor="prism-file-select">File</label>
        <Select items={items} value={source.path} onValueChange={(value) => {
          setSelectedPath(value);
          setFocusLine(null);
          setTooltip(null);
        }}>
          <SelectTrigger id="prism-file-select" className="prism-file-select"><SelectValue /></SelectTrigger>
          <SelectContent>{items.map((item) => <SelectItem value={item.value} key={item.value}>{item.label}</SelectItem>)}</SelectContent>
        </Select>
        <code>{source.path}</code>
      </div>
      <pre className="file-view" tabIndex="0" aria-label="Syntax-colored Prism file">
        <code>
          <PrismCode
            focusLine={focusLine}
            onNavigate={navigate}
            onOccurrenceHover={showTooltip}
            source={source}
            sources={sources}
            workflow={workflow}
          />
        </code>
      </pre>
      {tooltip && (
        <div className="file-example-tooltip" role="tooltip" style={{ left: tooltip.left, top: tooltip.top }}>
          <strong>{mainLabel(tooltip.node)}</strong>
          <NodeValues graph={workflow.graph} node={tooltip.node} />
        </div>
      )}
    </section>
  );
}
