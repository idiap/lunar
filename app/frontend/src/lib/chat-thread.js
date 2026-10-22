// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
export function loadedChatThreadId(chat, activeChatId, currentThreadId, newThreadId) {
  return (activeChatId === chat.id ? currentThreadId : newThreadId);
}
