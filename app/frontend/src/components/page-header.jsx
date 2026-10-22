// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export function PageHeader({ title, actions }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
      </div>
      {actions && <div className="header-actions">{actions}</div>}
    </header>
  );
}
