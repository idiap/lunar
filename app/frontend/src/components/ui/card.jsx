// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { cn } from "@/lib/utils";

export function Card({ className, ...props }) {
  return <div className={cn("card", className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <div className={cn("card-header", className)} {...props} />;
}

export function CardTitle({ className, ...props }) {
  return <h2 className={cn("card-title", className)} {...props} />;
}

export function CardDescription({ className, ...props }) {
  return <p className={cn("card-description", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("card-content", className)} {...props} />;
}
