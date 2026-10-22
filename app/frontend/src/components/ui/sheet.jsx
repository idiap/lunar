// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Dialog as SheetPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

export function Sheet(props) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />;
}

export function SheetTrigger(props) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

export function SheetClose(props) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />;
}

function SheetPortal(props) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />;
}

function SheetOverlay({ className, ...props }) {
  return <SheetPrimitive.Backdrop className={cn("sheet-overlay", className)} {...props} />;
}

export function SheetContent({ className, children, side = "right", showCloseButton = true, ...props }) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Popup
        data-slot="sheet-content"
        data-side={side}
        className={cn("sheet-content", className)}
        {...props}
      >
        {children}
        {showCloseButton && (
          <SheetPrimitive.Close className="sheet-close" aria-label="Close">
            <X aria-hidden="true" />
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Popup>
    </SheetPortal>
  );
}

export function SheetHeader({ className, ...props }) {
  return <div className={cn("sheet-header", className)} {...props} />;
}

export function SheetFooter({ className, ...props }) {
  return <div className={cn("sheet-footer", className)} {...props} />;
}

export function SheetTitle({ className, ...props }) {
  return <SheetPrimitive.Title className={cn("sheet-title", className)} {...props} />;
}

export function SheetDescription({ className, ...props }) {
  return <SheetPrimitive.Description className={cn("sheet-description", className)} {...props} />;
}
