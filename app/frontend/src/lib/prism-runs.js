// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export function workflowExecutionOptions(workflowId, registry) {
  return registry.filter((item) => item.id === workflowId || item.metadata?.viewer_workflow_id === workflowId);
}

export function workflowHistoryId(workflowId, runnable) {
  return runnable?.id || workflowId;
}

export const TERMINAL_RUN_STATES = new Set(["completed", "failed", "cancelled"]);

export function prismRunPayload(workflowId, values = {}) {
  return {
    operation: "run",
    ai_model_id: values.aiModelId || null,
    inputs: values.inputs || (values.datasetIds ? { dataset_ids: values.datasetIds } : {}),
    network_authority: values.networkAuthority === true,
  };
}

export function selectedDatasetStatus(runnable, datasetIds) {
  const datasets = (runnable?.datasets || []).filter((dataset) => datasetIds.includes(dataset.dataset_id));
  const unavailable = datasets.filter((dataset) => dataset.status === "unavailable");
  const needsDownloads = datasets.some((dataset) => dataset.status === "download_required");
  return { datasets, unavailable, needsDownloads, ready: datasets.length > 0 && datasets.length === datasetIds.length && !unavailable.length && (!needsDownloads || runnable?.downloads_enabled) };
}

export function canRunWorkflow({ runnable, aiModelId }) {
  return Boolean(runnable && (runnable.metadata?.model_required !== true || aiModelId));
}

export function modelOptionLabel(model) {
  return `${model.name} (${model.provider}/${model.model_id})`;
}

export function emptyModelListLabel(models) {
  return models.length ? "Select a configured model" : "No configured models";
}

export function prismAgentEvents(run) {
  return (run?.events || []).filter((event) => event.detail?.event_kind === "agent-invoked");
}

export function runStatusLabel(state) {
  return String(state || "unknown").replaceAll("_", " ");
}

export function reportRunDescription(item) {
  const id = String(item.run_id || "").slice(0, 8);
  if (item.imported) return `Imported report · Saved snapshot · Run ${id}`;
  return `.prism execution · ${runStatusLabel(item.generation_status)} · Run ${id}`;
}

export function latestOutput(run) {
  return run?.outputs?.[0] || null;
}

export function runReportPath(runId) {
  return `/prism/runs/${encodeURIComponent(runId)}/report`;
}

export function headingAnchor(value) {
  return String(value || "")
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "section";
}

export function reportHeadings(markdown) {
  let fenced = false;
  const counts = new Map();
  return String(markdown || "").split("\n").flatMap((line) => {
    if (line.trimStart().startsWith("```")) {
      fenced = !fenced;
      return [];
    }
    if (fenced) return [];
    const match = /^(#{1,4})\s+(.+?)\s*#*$/.exec(line);
    if (!match) return [];
    const text = match[2].replace(/[`*~]/g, "").trim();
    const base = headingAnchor(text);
    const ordinal = (counts.get(base) || 0) + 1;
    counts.set(base, ordinal);
    return [{ level: match[1].length, text, id: ordinal === 1 ? base : `${base}-${ordinal}` }];
  });
}

export function reportTarget(run, target) {
  const value = String(target || "").trim();
  if (!value) return null;
  if (value.startsWith("#")) return value;
  if (/^(?:https?:|mailto:)/i.test(value)) return value;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|\\)/i.test(value) || value.includes("\\")) return null;
  let decoded;
  try {
    decoded = decodeURIComponent(value.split(/[?#]/, 1)[0]);
  } catch {
    return null;
  }
  const parts = decoded.split("/");
  if (!decoded || parts.some((part) => !part || part === "." || part === "..")) return null;
  const fragment = value.includes("#") ? value.slice(value.indexOf("#")) : "";
  if (["report.md", "report.html"].includes(decoded) && run?.id) return `${runReportPath(run.id)}${fragment}`;
  const artifact = (run?.artifacts || []).find(
    (item) => [decoded, `run:${decoded}`].includes(item.safe_locator) && typeof item.url === "string",
  );
  return artifact?.url ? `${artifact.url}${fragment}` : null;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function verifyReportLayout(output) {
  const layout = output?.structured_value?.report_layout;
  if (!layout) return;
  const hash = async (value) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const { metadata_sha256: expected, ...metadata } = layout;
  if (await hash(output.markdown) !== layout.content_sha256 || await hash(canonicalJson(metadata)) !== expected) {
    throw new Error("Report content or metadata failed its integrity check.");
  }
}

export function nativeReportTree(output) {
  const layout = output?.structured_value?.report_layout;
  if (!layout) return null;
  if (!["lunar.native-report/v1", "bioagents.native-report/v1"].includes(layout.schema_version) || !Array.isArray(layout.blocks) || !Array.isArray(layout.groups)) {
    throw new Error("Required report metadata is unavailable.");
  }
  const characters = Array.from(output.markdown);
  const headings = reportHeadings(output.markdown);
  const groups = new Map(layout.groups.map((group) => [group.key, group]));
  const containers = new Map();
  const aliases = new Map();
  const aliasIds = new Set();
  for (const anchor of layout.anchors || []) {
    if (aliasIds.has(anchor.id)) continue;
    aliasIds.add(anchor.id);
    aliases.set(anchor.content_key, [...(aliases.get(anchor.content_key) || []), anchor.id]);
  }
  const root = { children: [] };
  const ids = new Set();
  let position = 0;
  let headingIndex = 0;
  for (const block of layout.blocks) {
    if (ids.has(block.id) || block.start !== position || !Number.isInteger(block.end) || block.end <= block.start || block.end > characters.length) {
      throw new Error(`Report content is missing or out of order: ${block.id}`);
    }
    ids.add(block.id);
    position = block.end;
    let parent = root;
    for (const key of block.group_keys || []) {
      const definition = groups.get(key);
      if (!definition || !["card", "tab", "disclosure", "figure_group"].includes(definition.kind)) {
        throw new Error(`Required report group is unavailable: ${key}`);
      }
      let group = containers.get(key);
      if (!group) {
        group = { ...definition, children: [], parent };
        containers.set(key, group);
        parent.children.push(group);
      } else if (group.parent !== parent) {
        throw new Error(`Report group nesting is inconsistent: ${key}`);
      }
      parent = group;
    }
    const heading = block.kind === "heading" ? headings[headingIndex++] : null;
    const headingId = heading ? block.heading_key || heading.id : null;
    const anchors = new Set(aliases.get(block.id) || []);
    anchors.delete(headingId);
    parent.children.push({ ...block, markdown: characters.slice(block.start, block.end).join(""), headingId, anchors: [...anchors] });
  }
  if (position !== characters.length) throw new Error("Required report content is missing.");
  return root.children;
}


// Native HTML is admitted only through this run's digest-bound artifact inventory.
export function nativeHtmlReport(run, output) {
  const report = output?.structured_value?.html_report;
  if (!report) return null;
  if (report.media_type !== "text/html" || !/^[a-f0-9]{64}$/.test(report.sha256 || "")) {
    throw new Error("Invalid HTML report descriptor");
  }
  const artifact = (run.artifacts || []).find((item) =>
    [report.path, `run:${report.path}`].includes(item.safe_locator));
  if (!artifact || artifact.media_type !== "text/html" ||
      artifact.content_digest !== `sha256:${report.sha256}` ||
      !artifact.url?.startsWith(`/api/prism/runs/${encodeURIComponent(run.id)}/artifacts/`)) {
    throw new Error("HTML report is not bound to this run's artifact inventory");
  }
  return { ...report, url: artifact.url };
}

export async function verifiedHtmlDocument(document, sha256) {
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(document))))
    .map((value) => value.toString(16).padStart(2, "0")).join("");
  if (digest !== sha256) throw new Error("HTML report integrity check failed");
  // The opaque iframe origin and this policy allow local scripts/MathJax while
  // denying application access, external requests, forms, frames and base URLs.
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">`;
  // The policy must precede even malformed source markup or early scripts.
  return '<!doctype html>' + policy + document.replace(/^\s*<!doctype[^>]*>/i, '');
}
