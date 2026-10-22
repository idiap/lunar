# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import asyncpg
import resend
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from config import (
    AUTH_SECRET,
    BYPASS_VERIFICATION,
    DATABASE_URL,
    FRONTEND_ORIGIN,
    PUBLIC_BASE_URL,
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    SESSION_COOKIE,
    SESSION_COOKIE_SAMESITE,
    SESSION_SECONDS,
)

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
logger = logging.getLogger(__name__)


def mcp_token_for_user(user_id: str) -> str:
    signature = hmac.new(
        AUTH_SECRET.encode(),
        user_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"rpt_{user_id}.{signature}"


class ReportTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("rpt_"):
            return None
        try:
            user_id, signature = token[4:].split(".", 1)
            parsed_user_id = uuid.UUID(user_id)
        except (ValueError, AttributeError):
            return None

        expected = mcp_token_for_user(user_id).rsplit(".", 1)[1]
        if not hmac.compare_digest(signature, expected):
            return None

        connection = await asyncpg.connect(DATABASE_URL)
        try:
            exists = await connection.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM users
                    WHERE id = $1 AND email_verified_at IS NOT NULL
                )
                """,
                parsed_user_id,
            )
        finally:
            await connection.close()
        if not exists:
            return None

        return AccessToken(
            token=token,
            client_id="reports-mcp",
            scopes=["reports:create"],
            subject=user_id,
        )


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, expected_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual_hex = hash_password(password, bytes.fromhex(salt_hex)).rsplit("$", 1)[1]
        return hmac.compare_digest(actual_hex, expected_hex)
    except ValueError:
        return False


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verification_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def send_verification_email(email: str, token: str) -> None:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not configured")

    verification_url = (
        f"{PUBLIC_BASE_URL}/api/auth/verify-email?" f"{urlencode({'token': token})}"
    )
    resend.api_key = RESEND_API_KEY
    params: resend.Emails.SendParams = {
        "from": RESEND_FROM_EMAIL,
        "to": [email],
        "subject": "Verify your Lunar email",
        "html": (
            "<p>Welcome to Lunar.</p>"
            f'<p><a href="{verification_url}">Verify your email address</a></p>'
            "<p>This link expires in 24 hours.</p>"
        ),
    }
    resend.Emails.send(params)


async def create_session(user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
            session_hash(token),
            user_id,
            datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS),
        )
    finally:
        await connection.close()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=PUBLIC_BASE_URL.startswith("https://"),
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )


async def current_user(request: Request) -> asyncpg.Record | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.fetchrow(
            """
            SELECT users.id, users.email, users.created_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = $1
              AND sessions.expires_at > NOW()
              AND users.email_verified_at IS NOT NULL
            """,
            session_hash(token),
        )
    finally:
        await connection.close()


def user_json(user: asyncpg.Record) -> dict[str, str]:
    user_id = str(user["id"])
    return {
        "id": user_id,
        "email": user["email"],
        "mcp_url": f"{PUBLIC_BASE_URL}/mcp",
        "mcp_token": mcp_token_for_user(user_id),
    }


async def signup(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    if "@" not in email:
        return JSONResponse({"error": "Enter a valid email"}, status_code=400)
    if len(password) < 8:
        return JSONResponse(
            {"error": "Password must have at least 8 characters"}, status_code=400
        )

    user_id = uuid.uuid4()
    verification_token = secrets.token_urlsafe(32)
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        try:
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO users (id, email, password_hash) VALUES ($1, $2, $3)",
                    user_id,
                    email,
                    hash_password(password),
                )
                if BYPASS_VERIFICATION:
                    await connection.execute(
                        "UPDATE users SET email_verified_at = NOW() WHERE id = $1",
                        user_id,
                    )
                    return JSONResponse(
                        {"message": "Account created. You can now sign in."},
                        status_code=201,
                    )
                await connection.execute(
                    """
                    INSERT INTO email_verification_tokens
                        (token_hash, user_id, expires_at)
                    VALUES ($1, $2, $3)
                    """,
                    verification_token_hash(verification_token),
                    user_id,
                    datetime.now(timezone.utc) + EMAIL_VERIFICATION_TTL,
                )
        except asyncpg.UniqueViolationError:
            return JSONResponse(
                {"error": "An account with this email already exists"},
                status_code=409,
            )
    finally:
        await connection.close()

    try:
        await asyncio.to_thread(send_verification_email, email, verification_token)
    except Exception:
        logger.exception("Failed to send verification email")
        connection = await asyncpg.connect(DATABASE_URL)
        try:
            await connection.execute(
                "DELETE FROM users WHERE id = $1 AND email_verified_at IS NULL",
                user_id,
            )
        finally:
            await connection.close()
        return JSONResponse(
            {"error": "Could not send the verification email. Please try again."},
            status_code=502,
        )

    return JSONResponse(
        {"message": "Check your email to verify your account."},
        status_code=201,
    )


async def verify_email(request: Request) -> Response:
    token = request.query_params.get("token", "")
    if not token:
        return JSONResponse(
            {"error": "Verification token is required"}, status_code=400
        )

    connection = await asyncpg.connect(DATABASE_URL)
    try:
        async with connection.transaction():
            verification = await connection.fetchrow(
                """
                SELECT user_id, expires_at
                FROM email_verification_tokens
                WHERE token_hash = $1
                FOR UPDATE
                """,
                verification_token_hash(token),
            )
            if verification is None:
                return JSONResponse(
                    {"error": "Verification link is invalid or has already been used"},
                    status_code=400,
                )
            if verification["expires_at"] <= datetime.now(timezone.utc):
                await connection.execute(
                    "DELETE FROM email_verification_tokens WHERE token_hash = $1",
                    verification_token_hash(token),
                )
                return JSONResponse(
                    {"error": "Verification link has expired"}, status_code=400
                )

            await connection.execute(
                "UPDATE users SET email_verified_at = NOW() WHERE id = $1",
                verification["user_id"],
            )
            await connection.execute(
                "DELETE FROM email_verification_tokens WHERE user_id = $1",
                verification["user_id"],
            )
    finally:
        await connection.close()

    session_token = await create_session(verification["user_id"])
    response = RedirectResponse(f"{FRONTEND_ORIGIN}/", status_code=303)
    set_session_cookie(response, session_token)
    return response


async def signin(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    connection = await asyncpg.connect(DATABASE_URL)
    try:
        user = await connection.fetchrow(
            """
            SELECT id, email, password_hash, email_verified_at
            FROM users
            WHERE email = $1
            """,
            email,
        )
    finally:
        await connection.close()
    if user is None or not password_matches(password, user["password_hash"]):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)
    if user["email_verified_at"] is None:
        return JSONResponse(
            {"error": "Verify your email before signing in"}, status_code=403
        )

    token = await create_session(user["id"])
    response = JSONResponse({"user": {"id": str(user["id"]), "email": user["email"]}})
    set_session_cookie(response, token)
    return response


async def signout(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        connection = await asyncpg.connect(DATABASE_URL)
        try:
            await connection.execute(
                "DELETE FROM sessions WHERE token_hash = $1",
                session_hash(token),
            )
        finally:
            await connection.close()
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=PUBLIC_BASE_URL.startswith("https://"),
        samesite=SESSION_COOKIE_SAMESITE,
    )
    return response


async def me(request: Request) -> JSONResponse:
    user = await current_user(request)
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse({"user": user_json(user)})


def register_auth_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/auth/signup", methods=["POST"])(signup)
    mcp.custom_route("/api/auth/verify-email", methods=["GET"])(verify_email)
    mcp.custom_route("/api/auth/signin", methods=["POST"])(signin)
    mcp.custom_route("/api/auth/signout", methods=["POST"])(signout)
    mcp.custom_route("/api/auth/me", methods=["GET"])(me)
