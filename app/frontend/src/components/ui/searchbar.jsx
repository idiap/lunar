// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function Searchbar({ className, label = "Search", ...props }) {
  return (
    <label className={cn("searchbar", className)}>
      <Search aria-hidden="true" />
      <span className="sr-only">{label}</span>
      <Input type="search" {...props} />
    </label>
  );
}
