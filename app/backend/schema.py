# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio

import asyncpg

from config import DATABASE_URL

SCHEMA = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token_hash VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id
    ON email_verification_tokens(user_id);

CREATE TABLE IF NOT EXISTS prompt_directories (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_id UUID REFERENCES prompt_directories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_prompt_directories_user_id
    ON prompt_directories(user_id);

CREATE TABLE IF NOT EXISTS prompts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content TEXT,
    directory_id UUID REFERENCES prompt_directories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_prompts_user_id ON prompts(user_id);

CREATE TABLE IF NOT EXISTS templates (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    agent UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_templates_user_id ON templates(user_id);

CREATE TABLE IF NOT EXISTS ai_models (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    api_base TEXT,
    api_version TEXT,
    encrypted_api_key TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ai_models_user_id ON ai_models(user_id);

CREATE TABLE IF NOT EXISTS chats (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_chats_user_updated_at
    ON chats(user_id, updated_at DESC);
ALTER TABLE chats ADD COLUMN IF NOT EXISTS pending_interrupt JSONB;

ALTER TABLE reports ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS provenance_data JSONB;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS content_type_id INTEGER;
UPDATE reports SET name = query WHERE name IS NULL;
UPDATE reports SET content = html WHERE content IS NULL;
"""


async def ensure_schema() -> None:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(SCHEMA)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(ensure_schema())
