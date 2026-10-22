// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { SchemaForm } from "@/components/ui/schema-form";

/** Local contract validation is available before runtime preparation. */
export function InputReview({ schema, value, onChange }) {
  const [checked, setChecked] = useState(false);
  return <Dialog onOpenChange={() => setChecked(false)}>
    <DialogTrigger asChild><Button variant="outline">Review inputs</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Review inputs</DialogTitle>
        <DialogDescription>Choose sources and check parameters before preparing the runtime. This does not execute the workflow.</DialogDescription>
      </DialogHeader>
      <SchemaForm schema={schema} value={value} onChange={(next) => { setChecked(false); onChange(next); }} onSubmit={() => setChecked(true)}>
        <Button type="submit">Validate inputs</Button>
      </SchemaForm>
      {checked && <p role="status">Inputs match the selected contract. No workflow has started.</p>}
    </DialogContent>
  </Dialog>;
}
