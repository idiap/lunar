// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { defaultUrlTransform } from "react-markdown";
export function reportUrl(report, value) {
  const attachment = report?.attachments?.find((item) => item.link === value || item.file === value);
  return defaultUrlTransform(attachment?.url || value);
}
