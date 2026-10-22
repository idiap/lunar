# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import auth
import pytest


@pytest.fixture(autouse=True)
def verification_enabled_by_default(monkeypatch):
    monkeypatch.setattr(auth, "BYPASS_VERIFICATION", False)


class FakeRequest:
    def __init__(self, body=None, *, query_params=None):
        self._body = body or {}
        self.query_params = query_params or {}
        self.cookies = {}

    async def json(self):
        return self._body


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeConnection:
    def __init__(self, *, row=None):
        self.row = row
        self.executions = []
        self.closed = False

    def transaction(self):
        return FakeTransaction()

    async def execute(self, query, *arguments):
        self.executions.append((query, arguments))

    async def fetchrow(self, query, *arguments):
        return self.row

    async def close(self):
        self.closed = True


def response_json(response):
    return json.loads(response.body)


def test_verification_email_uses_resend_api_key(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(auth, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(auth, "RESEND_FROM_EMAIL", "Lunar <verify@example.com>")
    monkeypatch.setattr(auth, "PUBLIC_BASE_URL", "https://api.example.com")
    monkeypatch.setattr(auth.resend.Emails, "send", sent.append)

    auth.send_verification_email("person@example.com", "secret token")

    assert auth.resend.api_key == "re_test"
    assert sent == [
        {
            "from": "Lunar <verify@example.com>",
            "to": ["person@example.com"],
            "subject": "Verify your Lunar email",
            "html": (
                "<p>Welcome to Lunar.</p>"
                '<p><a href="https://api.example.com/api/auth/verify-email?token=secret+token">'
                "Verify your email address</a></p>"
                "<p>This link expires in 24 hours.</p>"
            ),
        }
    ]


def test_signup_sends_verification_without_creating_session(monkeypatch) -> None:
    connection = FakeConnection()
    sent = []

    async def connect(_database_url):
        return connection

    monkeypatch.setattr(auth.asyncpg, "connect", connect)
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda _length: "verify-token")
    monkeypatch.setattr(
        auth,
        "send_verification_email",
        lambda email, token: sent.append((email, token)),
    )

    response = asyncio.run(
        auth.signup(
            cast(
                Any,
                FakeRequest({"email": "Person@Example.com", "password": "password1"}),
            )
        )
    )

    assert response.status_code == 201
    assert response_json(response) == {
        "message": "Check your email to verify your account."
    }
    assert "set-cookie" not in response.headers
    assert sent == [("person@example.com", "verify-token")]
    token_insert = connection.executions[1][1]
    assert token_insert[0] == auth.verification_token_hash("verify-token")
    assert "verify-token" not in token_insert
    assert connection.closed is True


def test_verify_email_consumes_token_and_starts_session(monkeypatch) -> None:
    user_id = uuid.uuid4()
    connection = FakeConnection(
        row={
            "user_id": user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
    )

    async def connect(_database_url):
        return connection

    async def create_session(received_user_id):
        assert received_user_id == user_id
        return "session-token"

    monkeypatch.setattr(auth.asyncpg, "connect", connect)
    monkeypatch.setattr(auth, "create_session", create_session)
    monkeypatch.setattr(auth, "FRONTEND_ORIGIN", "https://app.example.com")
    monkeypatch.setattr(auth, "PUBLIC_BASE_URL", "https://api.example.com")

    response = asyncio.run(
        auth.verify_email(
            cast(Any, FakeRequest(query_params={"token": "verify-token"}))
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://app.example.com/"
    assert "session-token" in response.headers["set-cookie"]
    assert any(
        "UPDATE users SET email_verified_at" in query
        for query, _ in connection.executions
    )
    assert any(
        "DELETE FROM email_verification_tokens" in query
        for query, _ in connection.executions
    )


def test_bypassed_signup_skips_email_and_allows_signin(monkeypatch) -> None:
    connection = FakeConnection()

    async def connect(_database_url):
        return connection

    def unexpected_email(*args):
        pytest.fail("Bypassed signup must not send email")

    monkeypatch.setattr(auth, "BYPASS_VERIFICATION", True)
    monkeypatch.setattr(auth.asyncpg, "connect", connect)
    monkeypatch.setattr(auth, "send_verification_email", unexpected_email)
    request = FakeRequest({"email": "person@example.com", "password": "password1"})
    response = asyncio.run(auth.signup(cast(Any, request)))
    assert response.status_code == 201
    assert response_json(response) == {
        "message": "Account created. You can now sign in."
    }
    assert not any("email_verification_tokens" in q for q, _ in connection.executions)
    user_id, email, password_hash = connection.executions[0][1]
    assert connection.executions[1] == (
        "UPDATE users SET email_verified_at = NOW() WHERE id = $1",
        (user_id,),
    )
    assert connection.closed
    connection.row = dict(
        id=user_id,
        email=email,
        password_hash=password_hash,
        email_verified_at=datetime.now(timezone.utc),
    )
    response = asyncio.run(auth.signin(cast(Any, request)))
    assert response.status_code == 200
    assert "set-cookie" in response.headers


def test_unverified_user_cannot_sign_in(monkeypatch) -> None:
    connection = FakeConnection(
        row={
            "id": uuid.uuid4(),
            "email": "person@example.com",
            "password_hash": auth.hash_password("password1"),
            "email_verified_at": None,
        }
    )

    async def connect(_database_url):
        return connection

    monkeypatch.setattr(auth.asyncpg, "connect", connect)

    response = asyncio.run(
        auth.signin(
            cast(
                Any,
                FakeRequest({"email": "person@example.com", "password": "password1"}),
            )
        )
    )

    assert response.status_code == 403
    assert response_json(response) == {"error": "Verify your email before signing in"}
