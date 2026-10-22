// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ChevronRight, File, Folder } from "lucide-react";
import { getDefaultRegistry } from "@rjsf/core";
import { ariaDescribedByIds, descriptionId, titleId, toFieldPathId } from "@rjsf/utils";
import { Button } from "@/components/ui/button";
import { api, apiText } from "@/lib/api";
import { currentSelection, onSelectionChange } from "@/lib/package-selection";
import { inputHints, inputSuggestions } from "@/lib/input-guidance";

function Suggestions({ schema, hints, registry, onSelect, disabled }) {
  const choices = inputSuggestions(schema, hints.fieldPath, registry.formContext?.previousInputs)
    .filter(({ value }) => registry.schemaUtils.getValidator().isValid(schema.type === "array" ? schema.items : schema, value, registry.rootSchema));
  if (!choices.length) return null;
  return <details className="input-suggestions">
    <summary>Suggested values ({choices.length})</summary>
    <p className="field-description">Examples and previous values are suggestions. Check that they apply to this run.</p>
    <ul>{choices.map((choice) => <li key={choice.value}>
      <Button variant="outline" size="sm" disabled={disabled} onClick={() => onSelect(choice.value)}>
        <span>{choice.value}</span><small>{choice.label}</small>
      </Button>
    </li>)}</ul>
  </details>;
}

function FileTree({ files, search, selected, fileValue, accepts, disabled, onSelect }) {
  const tree = useMemo(() => {
    const root = new Map();
    for (const file of files) {
      let children = root;
      const parts = file.path.split("/");
      parts.forEach((name, index) => {
        const path = parts.slice(0, index + 1).join("/");
        const key = index === parts.length - 1 ? `file:${file.id}` : `folder:${path}`;
        if (!children.has(key)) children.set(key, { name, path, children: new Map() });
        const node = children.get(key);
        if (index === parts.length - 1) node.file = file;
        children = node.children;
      });
    }
    return root;
  }, [files]);

  function branch(children) {
    const nodes = [...children.values()].sort((a, b) => Number(!!a.file) - Number(!!b.file) || a.name.localeCompare(b.name));
    return <ul>{nodes.map((node) => <li key={node.file?.id || node.path}>
      {node.file ? <div className="input-file-row">
        <Button variant="ghost" size="sm" aria-label={node.path} aria-pressed={selected.includes(fileValue(node.file))}
          disabled={disabled || !accepts(fileValue(node.file))}
          title={accepts(fileValue(node.file)) ? node.path : "This value does not match the field constraints or is already selected."}
          onClick={() => onSelect(fileValue(node.file))}>
          <File size={16} aria-hidden="true" /><span>{node.name}</span>
        </Button>
        <a href={node.file.url} target="_blank" rel="noreferrer" aria-label={`View ${node.path}`}>View</a>
      </div> : <details open={search || files.some((file) => file.path.startsWith(`${node.path}/`) && selected.includes(fileValue(file))) || undefined}>
        <summary title={node.path}><ChevronRight className="input-folder-chevron" size={14} aria-hidden="true" />
          <Folder size={16} aria-hidden="true" /><span>{node.name}</span></summary>
        {branch(node.children)}
      </details>}
    </li>)}</ul>;
  }
  return <div className="input-file-tree" aria-label="Package file folders">{branch(tree)}</div>;
}

function FileChoices({ hints, onSelect, disabled, selected = [], accepts = () => true }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const extensions = Array.isArray(hints.extensions) ? hints.extensions.join(",") : "";
  const prefix = typeof hints.pathPrefix === "string" ? hints.pathPrefix : "";
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    if (offset === 0) setResult(null);
    setLoading(true);
    setError(null);
    const timer = setTimeout(() => {
      const parameters = new URLSearchParams({ query, prefix, extensions, offset: String(offset) });
      api(`/api/package-files?${parameters}`, { signal: controller.signal }).then((data) => {
        if (!controller.signal.aborted) {
          setResult((previous) => ({ ...data, items: offset ? [...(previous?.items || []), ...data.items] : data.items }));
          setLoading(false);
        }
      }).catch(() => {
        if (!controller.signal.aborted) {
          setError("Could not load package files. Retry or enter a value manually.");
          setLoading(false);
        }
      });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [open, query, prefix, extensions, retry, offset]);

  const digest = hints.kind === "digest";
  function fileValue(file) {
    const value = digest ? `${hints.digestPrefix ?? "sha256:"}${file.sha256}`
      : hints.relativeToPrefix ? file.path.slice(prefix.length) : file.path;
    return digest && hints.digestPrefix === undefined && !accepts(value) && accepts(file.sha256) ? file.sha256 : value;
  }
  return <div className="input-file-picker">
    <Button variant="outline" size="sm" disabled={disabled} aria-expanded={open} onClick={() => { setOpen(!open); setOffset(0); }}>
      {digest ? "Choose file checksum" : "Browse package files"}
    </Button>
    {open && <div className="input-file-results">
      <input className="form-control" type="search" aria-label="Search package files" placeholder="Search by file name or path…"
        value={query} maxLength={200} disabled={disabled} onChange={(event) => { setQuery(event.target.value); setOffset(0); }} />
      <p className="field-description">{digest ? "Select a file to copy its imported SHA-256 checksum." : "Select an imported file. Check that it matches the input description."}
        {hints.kind === "reference" && " Add a declaration or line reference after selecting the file."}</p>
      <div role="status">{error || (loading ? "Loading files…" : !result?.items.length ? "No matching package files. Change the search or enter a value manually." : "")}</div>
      {error && <Button variant="outline" size="sm" onClick={() => setRetry(retry + 1)} disabled={disabled}>Retry</Button>}
      {result && <FileTree key={query} files={result.items} search={!!query.trim()} selected={selected}
        fileValue={fileValue} accepts={accepts} disabled={disabled} onSelect={onSelect} />}
      {result?.has_more && <div className="input-file-more">
        <span className="field-description">Showing the first {result.items.length} matches. Search by file name or load more to see other folders.</span>
        <Button variant="outline" size="sm" disabled={disabled || loading || !!error}
          onClick={() => setOffset(result.items.length)}>Load more files</Button>
      </div>}
    </div>}
  </div>;
}

// Preview source metadata only; the native runtime derives and validates the
// authoritative value again from the imported bytes at preparation time.
function FileMetadata({ value, hints }) {
  const scope = useSyncExternalStore(onSelectionChange, currentSelection, currentSelection);
  const [result, setResult] = useState(null);
  const [retry, setRetry] = useState(0);
  const metadata = hints.fileMetadata;
  const signature = JSON.stringify([value, hints.pathPrefix, hints.relativeToPrefix, metadata]);
  useEffect(() => {
    const controller = new AbortController();
    if (!value) return () => controller.abort();
    const publish = (data) => {
      if (!controller.signal.aborted) setResult({ ...data, signature, scope });
    };
    const timer = setTimeout(async () => {
      try {
        const path = hints.relativeToPrefix ? `${hints.pathPrefix || ""}${value}` : value;
        const files = await api(`/api/package-files?${new URLSearchParams({ prefix: path })}`, { signal: controller.signal });
        const file = files.items.find((item) => item.path === path);
        if (!file) throw new Error("Selected source is not in this package.");
        const text = await apiText(file.url, { signal: controller.signal });
        const values = text.split(/\r?\n/).flatMap((line) => {
          const trimmed = line.trim();
          if (!trimmed.startsWith(metadata.commentPrefix)) return [];
          const comment = trimmed.slice(metadata.commentPrefix.length).trim();
          const colon = comment.indexOf(":");
          return colon >= 0 && comment.slice(0, colon).trim() === metadata.key
            ? [comment.slice(colon + 1).trim()] : [];
        });
        if (values.length !== 1 || !values[0]) throw new Error(`Source must contain exactly one ${metadata.key} comment with a value.`);
        publish({ value: values[0] });
      } catch (error) {
        publish({ error: error.message || "Could not read source metadata." });
      }
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [signature, scope, retry]);
  const visible = result?.signature === signature && result.scope === scope ? result : null;
  return <div className="field-description" role="status" aria-live="polite">
    <strong>{metadata.label}: </strong>
    {!value ? "Choose a source file." : visible?.error || (visible ? <output>{visible.value}</output> : "Reading source…")}
    {value && visible?.error && <Button variant="outline" size="sm" onClick={() => setRetry(retry + 1)}>Retry detection</Button>}
  </div>;
}

const fileKinds = new Set(["file", "reference", "digest"]);

export function GuidedTextWidget({ id, value, schema, options, label, registry, disabled, readonly, required, autofocus, onChange, onBlur, onFocus, rawErrors, htmlName }) {
  const hints = schema["x-input"] || {};
  const locked = disabled || readonly;
  const nullable = Array.isArray(schema.type) && schema.type.includes("null");
  const change = (text) => onChange(text === "" ? (nullable ? null : options.emptyValue) : text);
  const props = {
    id, name: htmlName, className: "form-control", value: value ?? "", disabled, readOnly: readonly,
    required, autoFocus: autofocus, placeholder: hints.placeholder || "", maxLength: schema.maxLength,
    "aria-describedby": ariaDescribedByIds(id), "aria-invalid": !!rawErrors?.length,
    onChange: (event) => change(event.target.value),
    onBlur: () => onBlur?.(id, value), onFocus: () => onFocus?.(id, value),
  };
  return <div className="guided-input">
    {hints.kind === "textarea" ? <textarea {...props} rows={4} /> : <input {...props} type="text" />}
    {fileKinds.has(hints.kind) && <FileChoices hints={hints} selected={[value]} onSelect={onChange} disabled={locked}
      accepts={(text) => registry.schemaUtils.getValidator().isValid(schema, text, registry.rootSchema)} />}
    {hints.kind === "file" && hints.fileMetadata && <FileMetadata value={value} hints={hints} />}
    <Suggestions schema={schema} hints={hints} registry={registry} onSelect={onChange} disabled={locked} />
    {!fileKinds.has(hints.kind) && /(^|_)(policy|backend|revision)$/.test(hints.fieldPath?.at(-1) || "") &&
      !inputSuggestions(schema, hints.fieldPath, registry.formContext?.previousInputs).length &&
      <p className="field-description">No choices are declared for {label.toLowerCase()}. Enter the value required by your workflow.</p>}
  </div>;
}

export function StringListWidget({ id, value = [], schema, options, registry, label, required, onChange, disabled, readonly, onBlur }) {
  const [bulk, setBulk] = useState("");
  const hints = schema["x-input"] || {};
  const locked = disabled || readonly;
  const items = Array.isArray(value) ? value : [];
  const canAdd = schema.maxItems === undefined || items.length < schema.maxItems;
  function append(values) {
    onChange([...items, ...values]);
  }
  function move(index, delta) {
    const next = [...items];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  }
  const lines = bulk.split(/\r?\n/).filter((line) => line.trim().length);
  const bulkFits = schema.maxItems === undefined || items.length + lines.length <= schema.maxItems;
  const description = options.description ?? schema.description;
  // The outer SchemaField sees a normal array, whose title/description are
  // owned by the array renderer. Our custom widget must render those too.
  return <fieldset id={id} tabIndex={-1} className="string-list" aria-labelledby={titleId(id)} aria-describedby={ariaDescribedByIds(id)}>
    <legend id={titleId(id)}>{label}{required && <span className="required">*</span>}</legend>
    {description && <p id={descriptionId(id)} className="field-description">{description}</p>}
    <p className="field-description">{items.length} selected. Add items individually or paste one per line.</p>
    {items.map((item, index) => {
      const itemId = toFieldPathId(index, registry.globalFormOptions, hints.fieldPath).$id;
      const Control = typeof item === "string" && item.includes("\n") || hints.kind === "textarea" ? "textarea" : "input";
      return <div className="string-list-item" key={index}>
      <div>
        <label className="sr-only" htmlFor={itemId}>{label} {index + 1}</label>
        <Control id={itemId} className="form-control" value={item ?? ""} disabled={disabled} readOnly={readonly}
          aria-invalid={!!options.itemErrors?.[index]?.__errors?.length} aria-describedby={`${itemId}-errors`}
          onBlur={() => onBlur?.(id, items)}
          onChange={(event) => onChange(items.map((current, position) => position === index ? event.target.value : current))} />
        <div id={`${itemId}-errors`} className="error-detail">{options.itemErrors?.[index]?.__errors?.join(" ")}</div>
      </div>
      <div className="string-list-actions">
        <Button variant="ghost" size="sm" aria-label={`Move ${label} ${index + 1} up`} disabled={locked || index === 0} onClick={() => move(index, -1)}>↑</Button>
        <Button variant="ghost" size="sm" aria-label={`Move ${label} ${index + 1} down`} disabled={locked || index === items.length - 1} onClick={() => move(index, 1)}>↓</Button>
        <Button variant="ghost" size="sm" aria-label="Remove item" disabled={locked} onClick={() => onChange(items.filter((_, position) => position !== index))}>Remove</Button>
      </div>
    </div>; })}
    <Button variant="outline" size="sm" disabled={locked || !canAdd} onClick={() => append([""])}>Add item</Button>
    {fileKinds.has(hints.kind) && <FileChoices hints={hints} selected={items} disabled={locked || !canAdd} onSelect={(text) => append([text])}
      accepts={(text) => (!schema.uniqueItems || !items.includes(text)) && registry.schemaUtils.getValidator().isValid(schema.items, text, registry.rootSchema)} />}
    <Suggestions schema={{ ...schema, examples: [...(schema.examples || []), ...(schema.items.examples || [])] }} hints={hints} registry={registry}
      disabled={locked || !canAdd} onSelect={(text) => append([text])} />
    <details className="input-bulk"><summary>Paste multiple items</summary>
      <textarea className="form-control" aria-label={`Paste ${label.toLowerCase()}`} rows={4} value={bulk} disabled={locked}
        placeholder="One item per line" onChange={(event) => setBulk(event.target.value)} />
      {!bulkFits && <p className="form-error">This list allows at most {schema.maxItems} items.</p>}
      <Button variant="outline" size="sm" disabled={locked || !lines.length || !bulkFits} onClick={() => { append(lines); setBulk(""); }}>Add {lines.length || "pasted"} items</Button>
    </details>
  </fieldset>;
}

const defaults = getDefaultRegistry().fields;
export function GuidedStringField(props) {
  const schema = { ...props.schema, "x-input": { ...inputHints(props.schema, props.name), fieldPath: props.fieldPathId.path } };
  return <defaults.StringField {...props} schema={schema} />;
}

export function GuidedArrayField(props) {
  const { schema, registry } = props;
  const item = schema.items && registry.schemaUtils.retrieveSchema(schema.items);
  // Keep specialized controls for formatted values, enums, tuples and unions.
  if (schema.type !== "array" || item?.type !== "string" || item.format || item.const !== undefined || registry.schemaUtils.isSelect(item) || schema.prefixItems || item.anyOf || item.oneOf || item.allOf) {
    return <defaults.ArrayField {...props} />;
  }
  const guided = { ...schema, items: item, "x-input": { ...inputHints(schema, props.name), fieldPath: props.fieldPathId.path } };
  return <defaults.ArrayField {...props} schema={guided} uiSchema={{ ...props.uiSchema, "ui:widget": "StringListWidget",
    "ui:options": { ...props.uiSchema?.["ui:options"], itemErrors: props.errorSchema } }} />;
}
