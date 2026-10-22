// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { AlertCircle } from "lucide-react";

export function LoadingState({ label = "Loading…" }) {
  return <div className="loading" role="status">{label}</div>;
}

export function EmptyState({ icon: Icon = AlertCircle, title, description }) {
  return (
    <div className="empty-state">
      <span><Icon aria-hidden="true" /></span>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}

export function PageError({ error }) {
  return <EmptyState title="Could not load this page" description={error.message} />;
}
