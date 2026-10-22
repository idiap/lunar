# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Execute a PRISM example and package its actual typed report for Lunar upload."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))

from prism.language import check, compile, elaborate, parse_source
from prism.runtime import FakeEffectHandler, run
from prism.sdk.workspace import WorkspaceModuleLoader
from prism_stdlib.report_codec import export_report, inventory
from domain_packages.archive_builder import ArchiveBuilder, json_bytes


def build_package(example: Path, destination: Path, *, with_template=True):
    """Use installed PRISM packages; the supplied directory contains source, not imports of Python code."""
    example = example.resolve()
    entry = example / ("main.prism" if with_template else "no_template.prism")
    loader = WorkspaceModuleLoader(project_root=example)
    checked = check(parse_source(entry.read_text(), str(entry)), module_loader=loader)
    output = run(compile(elaborate(checked)), handler=FakeEffectHandler())
    assets = {"figure": (example / "figure.svg").read_bytes()}
    typed = export_report(output, attachments=assets)
    with tempfile.TemporaryDirectory(prefix="typed-report-") as workspace:
        builder = ArchiveBuilder(
            Path(workspace) / "snapshot",
            package_key="typed-field-report",
            display_name="Typed field report",
        )
        sources = [
            builder.add_file(
                "repository/typed_reports/" + name, example / name, source_root=example
            )
            for name in (
                "main.prism",
                "no_template.prism",
                "content.prism",
                "runtime.json",
                "figure.svg",
                "README.md",
            )
        ]
        builder.add_resource(
            "repository",
            {
                "id": "report-source",
                "name": "Typed report source",
                "kind": "project",
                "metadata": {},
            },
            files=sources,
        )
        image = builder.add_bytes(
            "reports/figure.svg", assets["figure"], media_type="image/svg+xml"
        )
        provenance_bytes = json_bytes(typed["provenance"])
        provenance = builder.add_bytes(
            "reports/provenance.json", provenance_bytes, media_type="application/json"
        )
        exported = builder.add_bytes(
            "reports/typed-report.json",
            json_bytes(typed),
            media_type="application/json",
        )
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
            for i, (node, _) in enumerate(inventory(typed["report"]))
        ]
        document = {
            "id": typed["report"]["id"],
            "name": typed["report"]["title"],
            "content": "",
            "version": 1,
            "revisions": [],
            "sections": sections,
            "runs": [],
            "outputs": [],
            "attachments": [{"link": "figure", "file": image}],
            "provenance": [
                {
                    "format": "PROV-JSON",
                    "file": provenance,
                    "sha256": hashlib.sha256(provenance_bytes).hexdigest(),
                }
            ],
            "template_snapshot": typed["report"]["template"],
            "metadata": {"typed_report": typed},
        }
        builder.add_resource(
            "reports",
            document,
            files=[image, provenance, exported],
            references=[{"collection": "repository", "id": "report-source"}],
        )
        builder.publish(destination)
    return typed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--without-template", action="store_true")
    args = parser.parse_args()
    build_package(args.example, args.output, with_template=not args.without_template)
    print(args.output.resolve())
