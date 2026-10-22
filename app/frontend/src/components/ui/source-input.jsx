// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import "./source-input.css";
import { useEffect, useState, useSyncExternalStore } from "react";
import { getDefaultRegistry } from "@rjsf/core";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { currentSelection, onSelectionChange } from "@/lib/package-selection";
import { compatibleSource, referenceMatches, sameValue, selectionValues, validReference } from "@/lib/source-selection";
import { inputLabel } from "@/lib/input-guidance";

export function SourceInput({ schema, formData, name, fieldPathId, onChange, registry, required, disabled, readonly, errorSchema }) {
  const scope = useSyncExternalStore(onSelectionChange, currentSelection, currentSelection);
  const hints = schema["x-input"];
  const multiple = hints.multiple === true;
  const arraySchema = schema.type === "array" ? schema : schema.anyOf?.find((branch) => branch.type === "array");
  const values = selectionValues(formData, multiple);
  const signature = JSON.stringify(formData);
  const hintSignature = JSON.stringify(hints);
  const [checked, setChecked] = useState(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [retry, setRetry] = useState(0);
  const locked = disabled || readonly || schema.readOnly;
  const label = schema.title || inputLabel(name);
  const report = registry.formContext?.reportSourceCheck;
  const pathKey = JSON.stringify(fieldPathId.path);
  const validation = registry.schemaUtils.getValidator();
  const nullable = validation.isValid(schema, null, registry.rootSchema);
  const change = (value) => onChange(value, fieldPathId.path, undefined, fieldPathId.$id);

  useEffect(() => {
    const controller = new AbortController();
    const publish = (message, names = []) => {
      if (controller.signal.aborted) return;
      setChecked({ scope, signature, message, names });
      report?.(pathKey, signature, scope, message);
    };
    if (!values.length) { publish(null); return () => controller.abort(); }
    publish("Checking selected sources…");
    if (!scope.versionId) publish("Select a package version to verify these sources.");
    else if (!values.every(validReference)) publish("Choose a registered source to replace this invalid reference.");
    else Promise.all(values.map((reference) => api(`/api/data-sources/${encodeURIComponent(reference.source_id)}`, { signal: controller.signal })))
      .then((sources) => publish(sources.every((source, index) => referenceMatches(source, values[index], hints))
        ? null : "A selected source is unavailable, incompatible, or belongs to a different version. Choose it again.", sources.map((source) => source.name)))
      .catch(() => publish("Could not verify selected sources. Retry before submitting."));
    return () => controller.abort();
  }, [scope, signature, hintSignature, retry, pathKey, report]);

  useEffect(() => {
    if (!open || !scope.versionId) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: query, page: String(page), page_size: "40" });
      api(`/api/data-sources?${params}`, { signal: controller.signal })
        .then((data) => { if (!controller.signal.aborted) setResult({ data, scope, query, page }); })
        .catch(() => { if (!controller.signal.aborted) setResult({ error: "Could not load sources. Retry.", scope, query, page }); });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [open, scope, query, page, retry]);

  const visible = result?.scope === scope && result.query === query && result.page === page ? result : null;
  const choices = visible?.data?.items?.filter((source) => compatibleSource(source, hints)) || [];
  const status = checked?.scope === scope && checked.signature === signature ? checked : null;
  const canAdd = !multiple || arraySchema?.maxItems === undefined || values.length < arraySchema.maxItems;
  function canChoose(source) {
    const reference = source.selection.reference;
    const itemSchema = multiple ? arraySchema?.items : schema;
    return canAdd && validation.isValid(itemSchema, reference, registry.rootSchema) &&
      (!multiple || !arraySchema?.uniqueItems || !values.some((value) => sameValue(value, reference)));
  }
  return <fieldset className="source-input" id={fieldPathId.$id} tabIndex={-1} aria-labelledby={`${fieldPathId.$id}-label`}>
    <legend id={`${fieldPathId.$id}-label`}>{label}{required ? " *" : ""}</legend>
    {schema.description && <p>{schema.description}</p>}
    <ol>{values.map((value, index) => <li key={index}>
      <span>{status?.names[index] || value?.source_id || "Invalid selection"}</span>
      {multiple && <>
        <Button variant="ghost" size="sm" disabled={locked || index === 0} aria-label={`Move ${label} ${index + 1} up`} onClick={() => {
          const next = [...values]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; change(next);
        }}>↑</Button>
        <Button variant="ghost" size="sm" disabled={locked || index === values.length - 1} aria-label={`Move ${label} ${index + 1} down`} onClick={() => {
          const next = [...values]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; change(next);
        }}>↓</Button>
      </>}
      <Button variant="ghost" size="sm" disabled={locked} aria-label={`Remove ${label} ${index + 1}`} onClick={() => change(multiple ? values.filter((_, i) => i !== index) : undefined)}>Remove</Button>
    </li>)}</ol>
    <div role="status">{values.length ? status?.message || (status ? "Selected sources verified." : "Checking selected sources…") :
      formData === null ? "No source selected." : (hints.default_from || hints.default_source_id) ? "Using the workflow default." : "Choose a source from this package version."}</div>
    {status?.message && <Button variant="outline" size="sm" disabled={locked} onClick={() => setRetry(retry + 1)}>Retry verification</Button>}
    <div className="source-input-actions">
      <Button variant="outline" size="sm" disabled={locked || !scope.versionId || !canAdd} aria-expanded={open} onClick={() => setOpen(!open)}>{multiple ? "Add source" : "Choose source"}</Button>
      {nullable && <Button variant="ghost" size="sm" disabled={locked} onClick={() => change(null)}>No source</Button>}
      {!required && <Button variant="ghost" size="sm" disabled={locked} onClick={() => change(undefined)}>{hints.default_from || hints.default_source_id || schema.default !== undefined ? "Use default" : "Clear selection"}</Button>}
    </div>
    {open && <div className="source-input-options">
      <input className="form-control" aria-label={`Search sources for ${label}`} type="search" value={query} maxLength={200} disabled={locked}
        onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
      {!visible ? <p role="status">Loading sources…</p> : visible.error ? <>
        <p role="alert">{visible.error}</p><Button variant="outline" size="sm" disabled={locked} onClick={() => setRetry(retry + 1)}>Retry sources</Button>
      </> : <>
        {!choices.length && <p>No compatible sources on this page.</p>}
        <ul>{choices.map((source) => <li key={source.resource_id}>
          <Button variant="outline" size="sm" disabled={locked || !canChoose(source)} onClick={() => change(multiple ? [...values, source.selection.reference] : source.selection.reference)}>{source.name}</Button>
        </li>)}</ul>
        <div className="source-input-actions">
          <Button variant="ghost" size="sm" disabled={locked || page === 1} onClick={() => setPage(page - 1)}>Previous sources</Button>
          <span>Page {page} of {Math.max(1, visible.data.total_pages)}</span>
          <Button variant="ghost" size="sm" disabled={locked || page >= visible.data.total_pages} onClick={() => setPage(page + 1)}>Next sources</Button>
        </div>
      </>}
    </div>}
    {!!errorSchema?.__errors?.length && <div role="alert">{errorSchema.__errors.join(" ")}</div>}
  </fieldset>;
}

const DefaultSchemaField = getDefaultRegistry().fields.SchemaField;
function OptionalContext(props) {
  const { schema, formData, fieldPathId, onChange, disabled, readonly } = props;
  const label = schema.title || inputLabel(props.name);
  const present = formData !== undefined;
  const change = (value) => onChange(value, fieldPathId.path, undefined, fieldPathId.$id);
  return <div className="optional-input-context">
    {present && <DefaultSchemaField {...props} />}
    <Button variant="outline" size="sm" disabled={disabled || readonly || schema.readOnly} onClick={() => change(present ? undefined : {})}>
      {present ? "Remove" : "Include"} {label}
    </Button>
  </div>;
}

export function GuidedSchemaField(props) {
  const schema = props.schema.$ref ? props.registry.schemaUtils.retrieveSchema(props.schema, props.formData) : props.schema;
  if (schema["x-input"]?.kind === "data-source" && !props.uiSchema?.["ui:field"]) return <SourceInput {...props} schema={schema} />;
  if (props.registry.formContext?.optionalContexts && props.fieldPathId.path.length > 0 && !props.required && schema.type === "object" && !props.uiSchema?.["ui:field"]) return <OptionalContext {...props} schema={schema} />;
  return <DefaultSchemaField {...props} />;
}
