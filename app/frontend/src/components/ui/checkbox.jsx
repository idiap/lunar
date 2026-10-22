// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { cn } from "@/lib/utils";

export function Checkbox({ className, ...props }) {
  return <input {...props} type="checkbox" className={cn("ui-checkbox", className)} />;
}

export function CheckboxField({ children, ...props }) {
  return <label className="checkbox-label"><Checkbox {...props} /><span>{children}</span></label>;
}
