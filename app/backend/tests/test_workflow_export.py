# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""One workflow export contains only its source, view, runs, and provenance."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4
import zipfile
import xml.etree.ElementTree as ET

import asyncpg
import auth
import modules.common as common
from domain_packages import workflow_exporter
from domain_packages.archive import validate_archive
from domain_packages.export_routes import export_workflow_package
from domain_packages.format.source_workflows import identity
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from provenance.service import persist_run_provenance
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_archive import write_zip
from test_package_importer import user

PRISM = b"""type InventoryRequest:
    count: Int

type InventoryResult:
    count: Int

def count_items(request: InventoryRequest) -> InventoryResult:
    return InventoryResult(count = request.count + 1)

type CountItems = (request: InventoryRequest) -> InventoryResult

reasoning InventoryReasoning(request: InventoryRequest) -> InventoryResult:
    [counted: CountItems(request)]
    return counted

workflow inventory(request: InventoryRequest) -> InventoryResult:
    [counted: count_items(request)]
    return counted

def main(request: InventoryRequest) -> InventoryResult:
    return solve inventory(request)
"""


def test_workflow_export_archive_without_database(tmp_path, monkeypatch):
    run_id = uuid4()
    context = SimpleNamespace(version_id=uuid4(), version=3)
    view = {
        "id": "view",
        "label": "Review",
        "sources": [
            {
                "path": "repository/main.prism",
                "content": "reasoning Review(request: Int) -> Int:\n    return request\n",
            }
        ],
        "graph": {
            "reasoning": "Review",
            "nodes": [
                {"id": "request", "kind": "input", "output_type": "Int"},
                {"id": "result", "kind": "result", "output_type": "Int"},
            ],
            "edges": [{"source": "request", "target": "result", "kind": "return"}],
        },
    }
    projection = (
        {
            "kind": "prism-viewer-bundle",
            "schema_version": 1,
            "projects": [{"id": "project", "label": "Project", "workflows": [view]}],
        },
        [
            {
                "id": "execute",
                "metadata": {"viewer_workflow_id": "view"},
            }
        ],
    )

    class Connection:
        async def set_type_codec(self, *args, **kwargs):
            pass

        async def reset_type_codec(self, *args, **kwargs):
            pass

        @asynccontextmanager
        async def transaction(self, **kwargs):
            yield

        async def fetchrow(self, query, *args):
            return {
                "archive_digest": "a" * 64,
                "snapshot_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "package_key": "example",
                "display_name": "Example",
            }

        async def fetch(self, query, *args):
            if "FROM prism_runs" in query:
                return [
                    {
                        "id": run_id,
                        "workflow_id": "execute",
                        "operation": "run",
                        "mode": "default",
                        "state": "completed",
                        "safe_input_manifest": {},
                        "accepted_plan_digest": "sha256:" + "1" * 64,
                        "imported": False,
                    }
                ]
            return [
                {
                    "format": "prov-json",
                    "media_type": "application/provenance+json",
                    "document": {"entity": {}},
                    "wrapper_digest": "sha256:" + "2" * 64,
                    "generated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                }
            ]

    async def selected(*args, **kwargs):
        return context

    async def source_projection(*args, **kwargs):
        return projection

    monkeypatch.setattr(workflow_exporter, "owned_context", selected)
    monkeypatch.setattr(workflow_exporter, "_source_projection", source_projection)
    archive, receipt = asyncio.run(
        workflow_exporter.export_workflow(
            Connection(),
            None,
            user_id=uuid4(),
            version_id=context.version_id,
            workflow_id="execute",
            workspace=tmp_path,
        )
    )
    assert receipt["workflow_name"] == "Review"
    with zipfile.ZipFile(archive) as exported:
        manifest = json.loads(exported.read("manifest.json"))
        assert manifest["workflow"]["id"] == "view"
        assert manifest["workflow"]["requested_id"] == "execute"
        assert manifest["workflow"]["execution_ids"] == ["execute"]
        assert manifest["workflow"]["visualization_svg"] == "visualization.svg"
        assert manifest["runs"][0]["provenance"][0]["format"] == "prov-json"
        svg = exported.read("visualization.svg")
        assert svg.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
        assert ET.fromstring(svg).tag == "{http://www.w3.org/2000/svg}svg"
        assert b"Review" in svg and b"node-request" in svg and b"node-result" in svg
        assert exported.read("sources/repository/main.prism").startswith(
            b"reasoning Review"
        )
        for row in manifest["files"]:
            payload = exported.read(row["path"])
            assert len(payload) == row["size"]
            assert hashlib.sha256(payload).hexdigest() == row["sha256"]


def source_archive(tmp_path):
    def mutate(manifest, payloads):
        values = dict(payloads)
        annotation = {
            "declaration": "inventory",
            "id": "inventory",
            "entry_argument": "request",
            "prepare_hook": "prepare",
            "input_schema": {"type": "object"},
        }
        additions = {
            "repository/main.prism": (
                "# lunar-runtime: " + json.dumps(annotation) + "\n"
            ).encode()
            + PRISM,
            "repository/prepare.py": b"def prepare(**values): return values\n",
        }
        values.update(additions)
        manifest["runtime"]["entrypoints"] = [
            {
                "id": "prepare",
                "operation": "prepare",
                "file": "repository/prepare.py",
                "callable": "prepare",
            }
        ]
        manifest["collections"]["repository"][0]["files"].extend(additions)
        for path, content in additions.items():
            manifest["files"].append(
                {
                    "path": path,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "media_type": "text/plain",
                }
            )
        return manifest, list(values.items())

    path = tmp_path / "workflow-source.zip"
    write_zip(path, mutate=mutate)
    return validate_archive(path, tmp_path / "workflow-source")


def test_workflow_export_is_scoped_and_digest_inventoried(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))
    view_id = identity("warehouse", "repository/main.prism", "InventoryReasoning")

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection,
                storage,
                user_id=owner,
                archive=source_archive(tmp_path),
            )
            run_id = uuid4()
            await connection.execute(
                """INSERT INTO prism_runs
                   (id,user_id,version_id,workflow_id,operation,mode,state,
                    safe_input_manifest,accepted_plan_digest,artifact_root)
                   VALUES($1,$2,$3,'inventory','run','default','completed',
                          '{}'::jsonb,$4,'')""",
                run_id,
                owner,
                context.version_id,
                "sha256:" + "1" * 64,
            )
            await persist_run_provenance(
                connection,
                context,
                run_id,
                {"id": "inventory", "name": "Inventory"},
                failed=False,
            )
            return context, run_id, await auth.create_session(owner)
        finally:
            await connection.close()

    context, run_id, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route(
                "/api/packages/versions/{version_id}/workflows/{workflow_id}/export",
                export_workflow_package,
            )
        ]
    )
    endpoint = f"/api/packages/versions/{context.version_id}/workflows/{view_id}/export"
    with TestClient(app) as client:
        assert client.get(endpoint).status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, token)
        assert client.get(endpoint + "?user_id=someone-else").status_code == 400
        assert client.get(endpoint.replace(view_id, "unknown")).status_code == 404
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["x-lunar-workflow-id"] == view_id
        assert response.headers["etag"] == (
            '"' + hashlib.sha256(response.content).hexdigest() + '"'
        )

    archive = tmp_path / "workflow-export.zip"
    archive.write_bytes(response.content)
    with zipfile.ZipFile(archive) as exported:
        names = set(exported.namelist())
        manifest = json.loads(exported.read("manifest.json"))
        visualization = json.loads(exported.read("visualization.json"))
        bindings = json.loads(exported.read("execution-bindings.json"))
        assert manifest["schema_version"] == "lunar.workflow-export/v1"
        assert manifest["workflow"]["id"] == view_id
        assert manifest["workflow"]["execution_ids"] == ["inventory"]
        assert [row["id"] for row in manifest["runs"]] == [str(run_id)]
        assert {row["format"] for row in manifest["runs"][0]["provenance"]} == {
            "json-ld",
            "prov-json",
        }
        assert visualization["projects"][0]["workflows"][0]["id"] == view_id
        svg = exported.read("visualization.svg")
        assert ET.fromstring(svg).tag == "{http://www.w3.org/2000/svg}svg"
        assert b"InventoryReasoning" in svg
        assert b"node-counted" in svg
        assert [row["id"] for row in bindings["bindings"]] == ["inventory"]
        assert b"reasoning InventoryReasoning" in exported.read(
            "sources/repository/main.prism"
        )
        assert not any(name.startswith("reports/") for name in names)
        assert all(
            len(exported.read(row["path"])) == row["size"]
            and hashlib.sha256(exported.read(row["path"])).hexdigest() == row["sha256"]
            for row in manifest["files"]
        )

    async def receipts():
        connection = await asyncpg.connect(postgres_url)
        try:
            return await connection.fetchval(
                "SELECT COUNT(*) FROM package_exports WHERE version_id=$1",
                context.version_id,
            )
        finally:
            await connection.close()

    assert asyncio.run(receipts()) == 1
