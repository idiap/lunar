// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import test from "node:test";

import { loadedChatThreadId } from "./chat-thread.js";

test("preserves the live thread when a newly saved chat route loads", () => {
  assert.equal(
    loadedChatThreadId({ id: "chat-1" }, "chat-1", "live-thread", "new-thread"),
    "live-thread",
  );
});

test("does not resume historical execution approvals", () => {
  assert.equal(
    loadedChatThreadId(
      { id: "chat-1", pending_interrupt: { thread_id: "approval-thread" } },
      null,
      "page-thread",
      "new-thread",
    ),
    "new-thread",
  );
});

test("starts a distinct thread when navigating to another chat", () => {
  assert.equal(
    loadedChatThreadId({ id: "chat-2" }, "chat-1", "old-thread", "new-thread"),
    "new-thread",
  );
});
