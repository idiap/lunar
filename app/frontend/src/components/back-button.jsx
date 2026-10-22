// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

export function BackButton({ to }) {
  return <Link to={to} className="back-link"><ArrowLeft aria-hidden="true" />Back</Link>;
}
