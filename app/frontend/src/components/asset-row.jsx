// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Calendar, ChevronRight, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";

export function AssetRow({ href, icon: Icon, title, description, date, onDelete }) {
  return (
    <article className="asset-row">
      <Link to={href} className="asset-link">
        <span className="asset-icon"><Icon aria-hidden="true" /></span>
        <span className="asset-copy"><strong>{title}</strong><small>{description}</small></span>
        <time><Calendar aria-hidden="true" />{formatDate(date)}</time>
        <span className="row-chevron"><ChevronRight aria-hidden="true" /></span>
      </Link>
      {onDelete && <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="ghost" size="icon" className="danger" title="Delete" aria-label={`Delete ${title}`}>
            <Trash2 aria-hidden="true" />
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <p className="eyebrow">Delete asset</p>
            <AlertDialogTitle>Delete “{title}”?</AlertDialogTitle>
            <AlertDialogDescription>This action cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>}
    </article>
  );
}
