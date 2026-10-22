// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Brain } from "lucide-react";

import { LibraryPage } from "@/pages/library-page";

const providers = ["openai", "azure", "anthropic", "google", "cohere", "mistral", "huggingface", "ollama", "other"];

const config = {
  title: "AI Models",
  singular: "AI model",
  dialogDescription: "The API key is encrypted before storage.",
  listEndpoint: "/api/ai-models",
  createEndpoint: "/api/ai-models",
  deleteEndpoint: "/api/ai-models",
  basePath: "/ai-models",
  icon: Brain,
  fields: [
    { name: "provider", label: "Provider", type: "select", options: providers, required: true },
    { name: "model_id", label: "Model ID", required: true },
    { name: "api_key", label: "API key", type: "password", required: true },
    { name: "api_base", label: "API base URL" },
    { name: "api_version", label: "API version" },
  ],
  createPayload: (values) => ({
    ...values,
    name: `${values.provider.trim()}/${values.model_id.trim()}`,
  }),
  itemDescription: (item) => `${item.provider} · ${item.model_id}`,
  itemDate: (item) => item.updated_at,
  emptyTitle: "No AI models configured",
  emptyDescription: "Add a provider connection to run prompts.",
};

export { providers };

export function ModelsPage() {
  return <LibraryPage config={config} />;
}
