# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real authenticated HTTP uploads preserve owner boundaries and reject overrides."""

import asyncio

import asyncpg
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import modules.common as common
from domain_packages.routes import import_package, import_result, package_versions
from test_package_archive import write_zip
from test_package_importer import user


def test_authenticated_upload_listing_and_owner_isolation(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(auth, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(common, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "storage"))

    async def identities():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            return owners, [await auth.create_session(owner) for owner in owners]
        finally:
            await connection.close()

    owners, tokens = asyncio.run(identities())
    app = Starlette(
        routes=[
            Route("/api/packages/import", import_package, methods=["POST"]),
            Route("/api/packages/versions", package_versions),
            Route("/api/packages/imports/{version_id}", import_result),
        ]
    )
    archive = tmp_path / "neutral.zip"
    write_zip(archive)
    with TestClient(app) as client:
        assert (
            client.post("/api/packages/import", content=b"unauthenticated").status_code
            == 401
        )
        assert not (tmp_path / "storage").exists()
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        assert client.get("/api/packages/versions").json() == {"versions": []}
        response = client.post(
            "/api/packages/import",
            files={
                "file": ("untrusted-name.zip", archive.read_bytes(), "application/zip")
            },
        )
        assert response.status_code == 201, response.text
        version = response.json()["version"]
        assert version["status"] == "ready" and version["runtime_state"] == "unprepared"
        assert client.get("/api/packages/imports/" + version["id"]).status_code == 200
        assert len(client.get("/api/packages/versions").json()["versions"]) == 1
        for parameters in (
            {"params": {"owner": str(owners[1])}},
            {"data": {"owner": str(owners[1])}},
        ):
            response = client.post(
                "/api/packages/import",
                files={"file": ("package.zip", archive.read_bytes())},
                **parameters,
            )
            assert response.status_code == 400, response.text
        assert (
            client.post(
                "/api/packages/import", files={"file": ("bad.zip", b"not a ZIP")}
            ).status_code
            == 400
        )
        assert len(client.get("/api/packages/versions").json()["versions"]) == 1
        client.cookies.set(auth.SESSION_COOKIE, tokens[1])
        assert client.get("/api/packages/imports/" + version["id"]).status_code == 404
        assert client.get("/api/packages/versions").json() == {"versions": []}
        response = client.post(
            "/api/packages/import", files={"file": ("same.zip", archive.read_bytes())}
        )
        assert response.status_code == 201, response.text
        assert response.json()["version"]["version"] == 1
        assert response.json()["version"]["package_id"] != version["package_id"]
        assert not list((tmp_path / "storage" / ".uploads").glob("upload-*"))


def test_multipart_limits_and_duplicate_fields_cleanup(tmp_path):
    from domain_packages.archive import ArchiveLimits
    from domain_packages.format.contract import PackageValidationError
    from domain_packages.upload import receive_zip
    from starlette.requests import Request
    import pytest

    async def attempt(body, limit):
        chunks = [body[index : index + 3] for index in range(0, len(body), 3)]

        async def receive():
            chunk = chunks.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [
                    (b"content-type", b"multipart/form-data; boundary=boundary")
                ],
            },
            receive,
        )
        target = tmp_path / "upload.zip"
        try:
            return await receive_zip(
                request, target, ArchiveLimits(compressed_bytes=limit)
            )
        finally:
            target.unlink(missing_ok=True)

    part = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.zip"\r\n\r\n1234567890\r\n'
    with pytest.raises(PackageValidationError, match="limit"):
        asyncio.run(attempt(part + b"--boundary--\r\n", 5))
    with pytest.raises(PackageValidationError, match="exactly one"):
        asyncio.run(attempt(part + part + b"--boundary--\r\n", 100))
    with pytest.raises(PackageValidationError, match="incomplete"):
        asyncio.run(attempt(part, 100))
    asyncio.run(attempt(part + b"--boundary--\r\n", 100))
