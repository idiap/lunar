# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real PRISM execution and package fixtures for typed-report integration tests."""

from pathlib import Path
import asyncio
import pytest
import hashlib

from prism.language import check, compile, elaborate, parse_source
from prism.runtime import run, FakeEffectHandler
from prism.sdk.workspace import WorkspaceModuleLoader
from prism_stdlib.report_codec import export_report, inventory
from domain_packages.archive_builder import ArchiveBuilder, json_bytes
from domain_packages.archive import validate_archive

SOURCE = 'import prism.reporting.report as r\n\ndef main() -> r.Report:\n    leaf: r.Section = r.Markdown(id="markdown", text="same text")\n    html: r.Section = r.Html(id="html", text="<p>HTML</p>")\n    image: r.Section = r.Image(id="image", attachment="figure", alt="A figure")\n    nested: r.Section = r.Tabs(id="nested", tabs=[r.Tab(id="inner", label="Inner", sections=[image])])\n    sections: List[r.Section] = [r.Tabs(id="outer", tabs=[r.Tab(id="first", label="First", sections=[leaf]), r.Tab(id="second", label="Second", sections=[html, nested])])]\n    html_slot: r.TemplateSection = r.HtmlSlot(id="html")\n    nested_slot: r.TemplateSection = r.TabsSlot(id="nested", tabs=[r.TemplateTab(id="inner", sections=[r.ImageSlot(id="image")])])\n    slots: List[r.TemplateSection] = [r.TabsSlot(id="outer", tabs=[r.TemplateTab(id="first", sections=[r.MarkdownSlot(id="markdown")]), r.TemplateTab(id="second", sections=[html_slot, nested_slot])])]\n    template = r.WithTemplate(snapshot=r.Template(id="layout", title="Layout", sections=slots))\n    return r.Report(id="sample", title="Sample", sections=sections, template=template)\n'
IMAGE = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect width="120" height="40" fill="teal"/></svg>'


def exported(*, template=True, source=SOURCE):
    if not template:
        source = source.replace("template=template", "template=r.NoTemplate()")
    checked = check(
        parse_source(source),
        module_loader=WorkspaceModuleLoader(project_root=Path("/tmp")),
    )
    output = run(compile(elaborate(checked)), handler=FakeEffectHandler())
    assert output.status == "accepted", output.diagnostics
    return export_report(output, attachments={"figure": IMAGE})


def package(tmp_path, label="typed", *, template=True, typed=None):
    typed = typed if typed is not None else exported(template=template)
    builder = ArchiveBuilder(
        tmp_path / (label + "-snapshot"),
        package_key="typed-report",
        display_name="Typed report",
    )
    image = builder.add_bytes("reports/figure.svg", IMAGE, media_type="image/svg+xml")
    raw = json_bytes(typed["provenance"])
    provenance = builder.add_bytes(
        "reports/provenance.json", raw, media_type="application/json"
    )
    report = typed["report"]
    sections = [
        {
            "id": node["id"],
            "ordinal": i,
            "output_id": None,
            "content_digest": typed["sections"][node["id"]]["digest"].removeprefix(
                "sha256:"
            ),
            "metadata": {
                "provenance_entity_id": typed["sections"][node["id"]]["entity"],
                "native_reference": typed["sections"][node["id"]]["reference"],
            },
        }
        for i, (node, _) in enumerate(inventory(report))
    ]
    document = {
        "id": report["id"],
        "name": report["title"],
        "content": "",
        "version": 1,
        "revisions": [],
        "attachments": [{"link": "figure", "file": image}],
        "sections": sections,
        "runs": [],
        "outputs": [],
        "provenance": [
            {
                "format": "PROV-JSON",
                "file": provenance,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
        "template_snapshot": report["template"],
        "metadata": {"typed_report": typed},
    }
    builder.add_resource("reports", document, files=[image, provenance])
    path = tmp_path / (label + ".zip")
    builder.publish(path)
    return path


def staged(tmp_path, label="typed", **kwargs):
    return validate_archive(
        package(tmp_path, label, **kwargs), tmp_path / (label + "-validated")
    )


@pytest.fixture
def typed_client(postgres_url, tmp_path, monkeypatch):
    import asyncpg
    import auth
    import modules.common as common
    from domain_packages.importer import import_validated
    from domain_packages.storage import VersionStorage
    from domain_packages.middleware import PackageSelectionMiddleware
    from domain_packages.export_routes import export_package
    from domain_packages.files import package_file
    from modules.reports import get_report, update_report
    from reporting.routes import report_section_provenance
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient
    from test_package_importer import user

    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            contexts = []
            identities = []
            documents = []
            for i, owner in enumerate([owners[0], owners[0], owners[1]]):
                archive = staged(tmp_path, str(i), template=i != 1)
                context = await import_validated(
                    connection, storage, user_id=owner, archive=archive
                )
                contexts.append(context)
                documents.append(archive.documents["reports"][0])
                identities.append(
                    str(
                        await connection.fetchval(
                            "SELECT id FROM reports WHERE version_id=$1",
                            context.version_id,
                        )
                    )
                )
            return contexts, identities, documents, await auth.create_session(owners[0])
        finally:
            await connection.close()

    contexts, identities, documents, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/report/{report_id}", get_report),
            Route("/api/report/{report_id}", update_report, methods=["PUT"]),
            Route(
                "/api/report/{report_id}/sections/{section_id}/provenance",
                report_section_provenance,
            ),
            Route("/api/packages/versions/{version_id}/export", export_package),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        yield client, contexts, identities, documents, storage
