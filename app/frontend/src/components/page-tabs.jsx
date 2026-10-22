// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export function PageTabs({ tabs, label, className, children, ...props }) {
  return (
    <Tabs className={cn("page-tabs", className)} {...props}>
      <div className="page-tabs-header">
        <TabsList variant="line" aria-label={label} className="page-tabs-list">
          {tabs.map((tab) => (
            <TabsTrigger id={tab.id} key={tab.value} value={tab.value} className="page-tab">
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {children}
    </Tabs>
  );
}
