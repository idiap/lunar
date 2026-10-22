// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
let leanHighlighter;

export function sourceLanguage(path) {
  return /\.prism$/i.test(String(path)) ? "prism" : /\.lean$/i.test(String(path)) ? "lean4" : null;
}

export function codeLanguage(language) {
  return ["lean", "lean4"].includes(String(language).toLowerCase()) ? "lean4" : null;
}

export async function highlightSource(source, language) {
  if (!codeLanguage(language)) return null;
  leanHighlighter ||= Promise.all([
    import("shiki/core"), import("shiki/engine/javascript"),
    import("shiki/langs/lean4.mjs"), import("shiki/themes/github-light.mjs"),
  ]).then(([{ createHighlighterCore }, { createJavaScriptRegexEngine }, grammar, theme]) => createHighlighterCore({
    langs: [grammar.default], themes: [theme.default], engine: createJavaScriptRegexEngine(),
  })).catch((error) => { leanHighlighter = undefined; throw error; });
  const highlighter = await leanHighlighter;
  return highlighter.codeToTokens(source, { lang: "lean4", theme: "github-light" }).tokens;
}

export function reportSourceFiles(run) {
  const groups = new Map();
  for (const artifact of run?.artifacts || []) {
    const path = String(artifact.safe_locator || "").replace(/^run:/, "");
    const name = sourceLanguage(path) ? path : artifact.artifact_key;
    const language = sourceLanguage(name);
    // Render only registered run artifacts, never arbitrary external links.
    if (!language || !artifact.id || !artifact.url?.startsWith(`/api/prism/runs/${encodeURIComponent(run.id)}/artifacts/`)) continue;
    const key = /^sha256:[a-f0-9]{64}$/.test(artifact.content_digest) ? artifact.content_digest : artifact.id;
    const item = { ...artifact, name, language };
    if (groups.has(key)) groups.get(key).aliases.push(item);
    else groups.set(key, { ...item, aliases: [] });
  }
  return [...groups.values()];
}
