// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Select as SelectPrimitive } from "@base-ui/react/select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

export const Select = SelectPrimitive.Root;

export function SelectGroup({ className, ...props }) {
  return <SelectPrimitive.Group className={cn("select-group", className)} {...props} />;
}

export function SelectValue({ className, ...props }) {
  return <SelectPrimitive.Value className={cn("select-value", className)} {...props} />;
}

export function SelectTrigger({ className, children, ...props }) {
  return (
    <SelectPrimitive.Trigger className={cn("select-trigger", className)} {...props}>
      {children}
      <SelectPrimitive.Icon className="select-trigger-icon">
        <ChevronDown aria-hidden="true" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({
  align = "center",
  alignItemWithTrigger = true,
  alignOffset = 0,
  className,
  container,
  children,
  side = "bottom",
  sideOffset = 4,
  ...props
}) {
  return (
    <SelectPrimitive.Portal container={container}>
      <SelectPrimitive.Positioner
        align={align}
        alignItemWithTrigger={alignItemWithTrigger}
        alignOffset={alignOffset}
        className="select-positioner"
        side={side}
        sideOffset={sideOffset}
      >
        <SelectPrimitive.Popup className={cn("select-content", className)} {...props}>
          <SelectScrollUpButton />
          <SelectPrimitive.List>{children}</SelectPrimitive.List>
          <SelectScrollDownButton />
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  );
}

export function SelectLabel({ className, ...props }) {
  return <SelectPrimitive.GroupLabel className={cn("select-label", className)} {...props} />;
}

export function SelectItem({ className, children, ...props }) {
  return (
    <SelectPrimitive.Item className={cn("select-item", className)} {...props}>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="select-item-indicator">
        <Check aria-hidden="true" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}

export function SelectSeparator({ className, ...props }) {
  return <SelectPrimitive.Separator className={cn("select-separator", className)} {...props} />;
}

export function SelectScrollUpButton({ className, ...props }) {
  return (
    <SelectPrimitive.ScrollUpArrow className={cn("select-scroll-button", className)} {...props}>
      <ChevronUp aria-hidden="true" />
    </SelectPrimitive.ScrollUpArrow>
  );
}

export function SelectScrollDownButton({ className, ...props }) {
  return (
    <SelectPrimitive.ScrollDownArrow className={cn("select-scroll-button", className)} {...props}>
      <ChevronDown aria-hidden="true" />
    </SelectPrimitive.ScrollDownArrow>
  );
}
