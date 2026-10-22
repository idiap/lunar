// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

function Field({ field, dialogContentRef }) {
  const common = { name: field.name, required: field.required, defaultValue: field.value || "" };
  const options = field.options?.map((option) => ({ label: option, value: option })) || [];
  return (
    <Label>
      {field.label}
      {field.type === "select" ? (
        <Select
          name={field.name}
          required={field.required}
          defaultValue={field.value || null}
          items={options}
        >
          <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
          <SelectContent container={dialogContentRef} alignItemWithTrigger={false}>
            {options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
          </SelectContent>
        </Select>
      ) : field.type === "textarea" ? (
        <Textarea rows={7} {...common} />
      ) : (
        <Input type={field.type || "text"} {...common} />
      )}
    </Label>
  );
}

export function AssetDialog({ trigger, title, description, fields, submitLabel = "Create", onSubmit }) {
  // Keep select popups within Radix's modal focus and interaction boundary.
  const dialogContentRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(Object.fromEntries(new FormData(event.currentTarget)));
      setOpen(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent ref={dialogContentRef}>
        <DialogHeader>
          <p className="eyebrow">New asset</p>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <form className="form-stack" onSubmit={handleSubmit}>
          {fields.map((field) => <Field key={field.name} field={field} dialogContentRef={dialogContentRef} />)}
          {error && <p className="form-error">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? "Working…" : submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
