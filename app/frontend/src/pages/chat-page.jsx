// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useParams } from "react-router-dom";

import { ChatConversation } from "@/components/chat-conversation";

export function ChatPage() {
  const { id } = useParams();
  return <ChatConversation id={id} />;
}
