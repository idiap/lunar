// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Save } from "lucide-react";

import { BackButton } from "@/components/back-button";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export function EditorLayout({ back, title, children, onSubmit, saving, actions }) {
  return (
    <>
      <BackButton to={back} />
      <PageHeader
        title={title}
        actions={
          <>{actions}<Button type="submit" form="editor-form" disabled={saving}>
              <Save aria-hidden="true" />{saving ? "Saving…" : "Save changes"}
            </Button></>
        }
      />
      <Card className="editor-card">
        <form id="editor-form" className="editor-form" onSubmit={onSubmit}>{children}</form>
      </Card>
    </>
  );
}
