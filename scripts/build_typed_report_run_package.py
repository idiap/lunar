# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build a runnable package: the report is produced only when Run is clicked."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))
from domain_packages.archive_builder import ArchiveBuilder

PREPARE = b"""import hashlib,json
from pathlib import Path

def prepare(**values):
    request=values["inputs"]
    source=Path(__file__).with_name("main.prism")
    (values["run_root"]/"main.prism").write_bytes(source.read_bytes())
    return {"prepared_input":{"entry_argument_name":"request","value":request,
        "request_digest":hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest(),
        "analysis_results":{}},"state":None}
"""


def build_package(example, destination):
    with tempfile.TemporaryDirectory(prefix="typed-report-run-") as raw:
        builder = ArchiveBuilder(
            Path(raw) / "snapshot",
            package_key="field-survey-run",
            display_name="Field survey · runnable PRISM report",
        )
        source = builder.add_file(
            "repository/field-survey/main.prism",
            example / "main.prism",
            source_root=example,
        )
        prepare = builder.add_bytes(
            "repository/field-survey/prepare.py", PREPARE, media_type="text/x-python"
        )
        readme = builder.add_file(
            "repository/field-survey/README.md",
            example / "README.md",
            source_root=example,
        )
        builder.add_resource(
            "repository",
            {
                "id": "field-survey",
                "name": "Field survey",
                "kind": "workflow",
                "metadata": {
                    "description": "Enter a field observation, run PRISM, then inspect the typed report and its recorded provenance."
                },
            },
            files=[source, prepare, readme],
        )
        builder.manifest["runtime"]["entrypoints"] = [
            {
                "id": "prepare",
                "operation": "prepare",
                "file": prepare,
                "callable": "prepare",
            }
        ]
        execution = {
            "declaration": "field_survey",
            "id": "field-survey",
            "entry_argument": "request",
            "prepare_hook": "prepare",
            "verify_hook": None,
            "metadata": {"output_format": "prism-typed-report/v1"},
            "input_schema": {
                "type": "object",
                "required": ["observation"],
                "additionalProperties": False,
                "properties": {
                    "observation": {
                        "type": "string",
                        "minLength": 1,
                        "title": "Field observation",
                        "default": "The morning survey recorded twelve birds beside the lake.",
                    }
                },
            },
            "output_schema": {
                "type": "object",
                "required": ["structured_value"],
                "properties": {
                    "structured_value": {"type": "object", "required": ["typed_report"]}
                },
            },
        }
        raw = (
            "# lunar-runtime: " + json.dumps(execution, sort_keys=True) + "\n"
        ).encode() + (builder.root / source).read_bytes()
        (builder.root / source).write_bytes(raw)
        builder.files[source].update(
            size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )
        builder.publish(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_package(args.example.resolve(), args.output.resolve()))
