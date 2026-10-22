// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useId, useMemo, useState, useSyncExternalStore } from "react";
import Form, { getDefaultRegistry } from "@rjsf/core";
import { ArrowDown, ArrowUp, Copy, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CheckboxField } from "@/components/ui/checkbox";
import { ariaDescribedByIds, descriptionId, schemaRequiresTrueValue } from "@rjsf/utils";

import { formSchema, schemaFormValidator } from "@/lib/schema-form";
import { friendlyInputErrors } from "@/lib/input-guidance";
import { GuidedArrayField, GuidedStringField, GuidedTextWidget, StringListWidget } from "./guided-inputs";

import { GuidedSchemaField } from "./source-input";
import { sourceFields, selectionValues, inputDefaults } from "@/lib/source-selection";
import { currentSelection, onSelectionChange } from "@/lib/package-selection";

// RJSF's custom-validation adapter repopulates omitted objects with empty
// defaults. Validate source identities against the actual submitted values.
const sourceFormValidator = Object.create(schemaFormValidator);
sourceFormValidator.validateFormData = (data, schema, customValidate, ...options) =>
  schemaFormValidator.validateFormData(data, schema,
    customValidate && ((_defaults, errors, ...rest) => customValidate(data, errors, ...rest)), ...options);

function ManagedField() { return null; }

function CheckboxWidget({ id, htmlName, value, disabled, readonly, autofocus, required, label, schema, options, onChange, onBlur, onFocus }) {
  const description = options.description ?? schema.description;
  return <div>
    {description && <p id={descriptionId(id)} className="field-description">{description}</p>}
    <CheckboxField
      id={id}
      name={htmlName || id}
      checked={value === true}
      disabled={disabled || readonly}
      autoFocus={autofocus}
      required={required && schemaRequiresTrueValue(schema)}
      aria-describedby={ariaDescribedByIds(id)}
      onChange={(event) => onChange(event.target.checked)}
      onBlur={(event) => onBlur(id, event.target.checked)}
      onFocus={(event) => onFocus(id, event.target.checked)}
    >{label}</CheckboxField>
  </div>;
}

const DefaultTextWidget = getDefaultRegistry().widgets.TextWidget;
function TextWidget(props) {
  const string = props.schema.type === "string" || (Array.isArray(props.schema.type) && props.schema.type.includes("string"));
  return string ? <GuidedTextWidget {...props} /> : <DefaultTextWidget {...props} />;
}
const widgets = { CheckboxWidget, TextWidget, StringListWidget };
const fields = { SchemaField: GuidedSchemaField, StringField: GuidedStringField, ArrayField: GuidedArrayField };

const DefaultInput = getDefaultRegistry().templates.BaseInputTemplate;
function BaseInputTemplate(props) {
  const nullable = Array.isArray(props.schema.type) && props.schema.type.includes("null");
  return <DefaultInput {...props} options={nullable ? { ...props.options, emptyValue: null } : props.options} />;
}

function actionButton(label, Icon) {
  return function FormAction({ id, onClick, disabled }) {
    return <Button id={id} variant="outline" size="sm" onClick={onClick} disabled={disabled} aria-label={label} title={label}><Icon aria-hidden="true" />{label === "Add item" && label}</Button>;
  };
}

const templates = {
  BaseInputTemplate,
  ButtonTemplates: {
    AddButton: actionButton("Add item", Plus),
    RemoveButton: actionButton("Remove item", X),
    MoveUpButton: actionButton("Move up", ArrowUp),
    MoveDownButton: actionButton("Move down", ArrowDown),
    CopyButton: actionButton("Copy item", Copy),
    ClearButton: actionButton("Clear", X),
  },
};

/** Reusable JSON Schema form. Managed fields are supplied by external pickers,
 * remain in the data, and are still validated against the complete schema. */
export function SchemaForm({ id, schema, value, onChange, onSubmit, managedFields = [], previousInputs = [], disabled = false, children }) {
  const prefix = useId();
  const hasSources = useMemo(() => sourceFields(schema, value).length > 0, [schema, value]);
  const renderedSchema = useMemo(() => formSchema(schema), [schema]);
  const inputValue = useMemo(() => hasSources ? inputDefaults(schema, value, schema, true) : value, [schema, value, hasSources]);
  const scope = useSyncExternalStore(onSelectionChange, currentSelection, currentSelection);
  const [sourceChecks, setSourceChecks] = useState({});
  const reportSourceCheck = useCallback((path, signature, checkedScope, message) => {
    setSourceChecks((previous) => {
      const old = previous[path];
      if (old && old.signature === signature && old.scope === checkedScope && old.message === message) return previous;
      return { ...previous, [path]: { signature, scope: checkedScope, message } };
    });
  }, []);
  const validateSources = useCallback((data, errors) => {
    for (const field of sourceFields(renderedSchema, data)) {
      if (!selectionValues(field.value, field.schema["x-input"].multiple).length) continue;
      const check = sourceChecks[JSON.stringify(field.path)];
      const message = check?.scope === scope && check.signature === JSON.stringify(field.value)
        ? check.message : "Checking selected sources…";
      if (message) {
        const target = field.path.reduce((node, key) => node?.[key], errors) || errors;
        target.addError(message);
      }
    }
    return errors;
  }, [renderedSchema, scope, sourceChecks]);
  const uiSchema = {
    "ui:title": "Run parameters",
    ...Object.fromEntries(managedFields.map((name) => [name, { "ui:field": ManagedField }])),
  };
  return (
    <Form
      id={id}
      idPrefix={prefix}
      className="schema-form"
      schema={renderedSchema}
      validator={sourceFormValidator}
      templates={templates}
      widgets={widgets}
      fields={fields}
      formContext={{ previousInputs, reportSourceCheck, optionalContexts: hasSources }}
      customValidate={validateSources}
      uiSchema={uiSchema}
      formData={inputValue}
      onChange={({ formData }) => onChange(formData)}
      onSubmit={({ formData }) => onSubmit(formData)}
      disabled={disabled}
      noHtml5Validate
      focusOnFirstError
      experimental_defaultFormStateBehavior={{ arrayMinItems: { populate: "never" },
        ...(hasSources ? { emptyObjectFields: "skipDefaults" } : {}) }}
      liveValidate="onBlur"
      transformErrors={friendlyInputErrors}
      showErrorList={false}
    >
      {children ?? <span />}
    </Form>
  );
}
