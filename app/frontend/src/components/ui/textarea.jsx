// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { cn } from "@/lib/utils";

export function Textarea({ className, ...props }) {
  return <textarea className={cn("textarea", className)} {...props} />;
}
