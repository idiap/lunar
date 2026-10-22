// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export function outputsByVariable(variables, outputs) {
  return Object.fromEntries(variables.map((name) => [
    name,
    outputs.filter((output) => output.output_key === name),
  ]));
}

export function bindingsComplete(variables, bindings, compatible) {
  return variables.length > 0 && variables.every((name) => (
    bindings[name] && compatible[name]?.some((output) => output.id === bindings[name])
  ));
}

export function sectionProvenancePath(reportId, sectionId) {
  return `/reports/${encodeURIComponent(reportId)}/provenance?section=${encodeURIComponent(sectionId)}`;
}

export function reportContentSegments(content, sections = []) {
  const segments = [];
  let cursor = 0;

  for (const section of [...sections].sort((left, right) => left.ordinal - right.ordinal)) {
    if (!section.rendered_markdown) continue;
    const start = content.indexOf(section.rendered_markdown, cursor);
    if (start === -1) continue;
    if (start > cursor) segments.push({ content: content.slice(cursor, start) });
    segments.push({ content: section.rendered_markdown, section });
    cursor = start + section.rendered_markdown.length;
  }

  if (cursor < content.length || segments.length === 0) {
    segments.push({ content: content.slice(cursor) });
  }
  return segments;
}
