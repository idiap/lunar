# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Complete, owned package exports from a repeatable PostgreSQL snapshot."""

import asyncio
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from .archive_builder import ArchiveBuilder, ExportError, json_bytes
from .context import owned_context
from .files import verified_payload

RUN_FIELDS = (
    "workflow_id",
    "operation",
    "mode",
    "state",
    "safe_input_manifest",
    "accepted_plan_digest",
    "error_summary",
    "created_at",
    "started_at",
    "finished_at",
    "terminal_result_digest",
    "ai_model_snapshot",
    "prism_source_digest",
)
CHILDREN = (
    "prism_run_planned_sources",
    "prism_run_consumed_sources",
    "prism_run_input_entities",
    "prism_run_events",
    "prism_reasoning_entries",
)
LINK = re.compile(r'!?\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+["\'][^)]*)?\)')
HTML_LINK = re.compile(r'<(?:img|a)\b[^>]*(?:src|href)=["\']([^"\']+)["\']', re.I)
ARTIFACT = re.compile(
    r"/api/prism/runs/([0-9a-fA-F-]{36})/artifacts/([0-9a-fA-F-]{36})"
)
PACKAGE_FILE = re.compile(r"/api/package-files/([0-9a-fA-F-]{36})")


def plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def links(content):
    return set((*LINK.findall(content), *HTML_LINK.findall(content)))


class VersionSnapshot:
    def __init__(self, connection, context, storage, builder):
        self.connection, self.context, self.storage, self.builder = (
            connection,
            context,
            storage,
            builder,
        )
        self.files = {}
        self.file_ids = {}
        self.originals = {}
        self.original_runs = {}
        self.original_outputs = {}
        self.mappings = {}
        self.runs = {}
        self.outputs = {}
        self.run_cache = {}

    async def rows(self, table, extra="", *args):
        return [
            dict(row)
            for row in await self.connection.fetch(
                f"SELECT * FROM {table} WHERE user_id=$1 AND version_id=$2 " + extra,
                self.context.user_id,
                self.context.version_id,
                *args,
            )
        ]

    def identity(self, kind, identity):
        return self.mappings.get((kind, str(identity)), str(identity))

    def copy_file(self, name):
        if name in self.builder.files:
            return name
        row = self.files.get(name)
        if row is None:
            raise ExportError("Referenced package file is missing")
        payload = verified_payload(row, self.storage, self.context)
        if isinstance(payload, bytes):
            self.builder.add_bytes(name, payload, media_type=row["media_type"])
        else:
            self.builder.add_file(
                name,
                payload,
                source_root=self.storage.version_root(self.context),
                expected_digest=row["sha256"],
            )
            self.builder.files[name]["media_type"] = row["media_type"]
        return name

    async def provenance(self, table, column, identity):
        result = []
        for row in await self.rows(
            table, f"AND {column}=$3 ORDER BY format,id", identity
        ):
            raw = json_bytes(row["document"])
            path = f'reports/provenance/{row["id"]}-{row["format"]}.json'
            self.builder.add_bytes(path, raw, media_type=row["media_type"])
            result.append(
                {
                    "format": {"prov-json": "PROV-JSON", "json-ld": "JSON-LD"}[
                        row["format"]
                    ],
                    "file": path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "receipt": {
                        "file": path,
                        "original_wrapper_digest": row["wrapper_digest"],
                        "generated_at": plain(row["generated_at"]),
                    },
                }
            )
        return result

    def original_provenance(self, run_id):
        names = {
            item["file"]
            for item in self.original_runs[run_id]["facts"].get(
                "provenance_receipts", []
            )
        }
        return [
            deepcopy(item)
            for document in self.originals.values()
            for item in document["provenance"]
            if item["file"] in names
        ]

    async def run(self, identity):
        key = self.identity("runs", identity)
        if key in self.run_cache:
            return self.run_cache[key]
        if key in self.original_runs:
            result = {
                "run": deepcopy(self.original_runs[key]),
                "provenance": self.original_provenance(key),
            }
            for item in result["run"]["facts"].get("artifacts", []):
                self.copy_file(item["file"])
            for item in result["provenance"]:
                self.copy_file(item["file"])
        else:
            row = self.runs.get(str(identity))
            if row is None:
                raise ExportError("Report refers to a missing or foreign run")
            facts = {key: plain(row.get(key)) for key in RUN_FIELDS}
            facts["import_posture"] = "historical_only"
            for table in CHILDREN:
                records = await self.rows(table, "AND run_id=$3 ORDER BY id", row["id"])
                facts[table.removeprefix("prism_run_")] = [
                    plain(
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"run_id", "user_id", "version_id"}
                        }
                    )
                    for item in records
                ]
            artifacts = []
            for item in await self.rows(
                "prism_run_artifacts", "AND run_id=$3 ORDER BY id", row["id"]
            ):
                locator = item["safe_locator"]
                relative = locator.removeprefix("run:")
                expected = self.storage.run_root(self.context, row["id"])
                if Path(row["artifact_root"]) != expected:
                    raise ExportError("Run artifact root is not owned")
                path = self.builder.add_file(
                    f'reports/artifacts/{row["id"]}/{relative}',
                    self.storage.run_file(self.context, row["id"], relative),
                    source_root=expected,
                    expected_digest=item["content_digest"],
                )
                self.builder.files[path]["media_type"] = item["media_type"]
                artifacts.append(
                    {
                        "id": str(item["id"]),
                        "file": path,
                        "relative": relative,
                        "link": f'/api/prism/runs/{row["id"]}/artifacts/{item["id"]}',
                        "source_metadata": plain(
                            {
                                key: value
                                for key, value in item.items()
                                if key not in {"user_id", "version_id"}
                            }
                        ),
                    }
                )
            provenance = await self.provenance(
                "prism_run_provenance_exports", "run_id", row["id"]
            )
            facts["artifacts"] = artifacts
            facts["provenance_receipts"] = [item["receipt"] for item in provenance]
            result = {"run": {"id": key, "facts": facts}, "provenance": provenance}
        self.run_cache[key] = result
        return result

    def output(self, identity):
        key = self.identity("outputs", identity)
        if key in self.original_outputs:
            return deepcopy(self.original_outputs[key])
        row = self.outputs.get(str(identity))
        if row is None:
            raise ExportError("Report refers to a missing or foreign output")
        content = row["markdown"] or ""
        if digest(content) != row["content_digest"].removeprefix("sha256:"):
            raise ExportError("Run output content digest mismatch")
        return {
            "id": key,
            "run_id": self.identity("runs", row["run_id"]),
            "content": content,
            "metadata": plain(
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"id", "run_id", "markdown", "user_id", "version_id"}
                }
            ),
        }

    async def complete(self, document, run_ids, resource_files=(), references=()):
        files = set(resource_files)
        for name in files:
            self.copy_file(name)
        attachments = {item["link"]: item["file"] for item in document["attachments"]}
        wanted = links(document["content"])
        for revision in document["revisions"]:
            wanted.update(links(revision["content"]))
        for section in document["sections"]:
            wanted.update(links(section["metadata"].get("rendered_markdown", "")))
        for link in wanted:
            match = ARTIFACT.fullmatch(urlsplit(link).path)
            if match:
                run_ids.add(str(UUID(match[1])))
        details = [await self.run(identity) for identity in sorted(run_ids)]
        known = {row["id"]: row for row in document["runs"]}
        for detail in details:
            known[detail["run"]["id"]] = detail["run"]
        document["runs"] = list(known.values())
        outputs = {row["id"]: row for row in document["outputs"]}
        for identity, row in self.outputs.items():
            if self.identity("runs", row["run_id"]) in known:
                value = self.output(identity)
                outputs[value["id"]] = value
        document["outputs"] = list(outputs.values())
        for output in outputs.values():
            wanted.update(links(output["content"]))
        artifacts = [
            item for run in known.values() for item in run["facts"].get("artifacts", [])
        ]
        for item in artifacts:
            files.add(item["file"])
            if item.get("link"):
                attachments.setdefault(item["link"], item["file"])
        for link in sorted(wanted):
            if link in attachments:
                continue
            parsed = urlsplit(link)
            artifact_match = ARTIFACT.fullmatch(parsed.path)
            file_match = PACKAGE_FILE.fullmatch(parsed.path)
            if file_match:
                selected = parse_qs(parsed.query).get("package_version_id", [])
                if selected and selected != [str(self.context.version_id)]:
                    raise ExportError("Attachment belongs to a different selection")
                row = self.file_ids.get(str(UUID(file_match[1])))
                if row is None:
                    raise ExportError("Report attachment is missing or foreign")
                target = self.copy_file(row["path"])
            elif artifact_match:
                target = next(
                    (
                        item["file"]
                        for item in artifacts
                        if item["id"] == str(UUID(artifact_match[2]))
                        and urlsplit(item.get("link", "")).path == parsed.path
                    ),
                    None,
                )
                if target is None:
                    raise ExportError("Report artifact is missing or foreign")
            elif link.startswith("#") or parsed.scheme in {
                "http",
                "https",
                "mailto",
                "doi",
                "data",
            }:
                continue
            else:
                relative = unquote(parsed.path).removeprefix("./")
                candidates = {
                    item["file"]
                    for item in artifacts
                    if item.get("relative") == relative
                    or item.get("source_metadata", {}).get("safe_locator")
                    == "run:" + relative
                }
                if relative in self.files:
                    candidates.add(self.copy_file(relative))
                if len(candidates) != 1:
                    raise ExportError("Report contains an unresolved local attachment")
                target = candidates.pop()
            attachments[link] = target
        document["attachments"] = [
            {"link": link, "file": path} for link, path in sorted(attachments.items())
        ]
        files.update(attachments.values())
        provenance = {
            (item["format"], item["file"]): item for item in document["provenance"]
        }
        receipts = {
            item["file"]: item
            for item in document["metadata"].get("provenance_receipts", [])
            if isinstance(item, dict) and "file" in item
        }
        for detail in details:
            for item in detail["provenance"]:
                provenance[item["format"], item["file"]] = {
                    key: value for key, value in item.items() if key != "receipt"
                }
                if "receipt" in item:
                    receipts[item["file"]] = item["receipt"]
        document["provenance"] = list(provenance.values())
        if receipts:
            document["metadata"]["provenance_receipts"] = list(receipts.values())
        files.update(item["file"] for item in document["provenance"])
        for name in files:
            if name not in self.builder.files:
                self.copy_file(name)
        self.builder.add_resource(
            "reports", plain(document), files=sorted(files), references=list(references)
        )

    async def collect(self, manifest):
        self.files = {row["path"]: row for row in await self.rows("package_files")}
        self.file_ids = {str(row["id"]): row for row in self.files.values()}
        self.mappings = {
            (row["source_collection"], str(row["local_id"])): row["source_id"]
            for row in await self.rows("package_import_mappings")
        }
        self.originals = {
            str(row["id"]): row["document"]
            for row in await self.rows("package_resources", "AND collection='reports'")
        }
        for document in self.originals.values():
            self.original_runs.update({row["id"]: row for row in document["runs"]})
            self.original_outputs.update(
                {row["id"]: row for row in document["outputs"]}
            )
        self.runs = {str(row["id"]): row for row in await self.rows("prism_runs")}
        self.outputs = {
            str(row["id"]): row for row in await self.rows("prism_run_outputs")
        }
        # Every immutable non-report payload keeps its path, bytes and media type.
        for name in self.files:
            if not name.startswith("reports/"):
                await asyncio.to_thread(self.copy_file, name)
        for kind, entries in manifest["collections"].items():
            if kind == "reports":
                continue
            self.builder.manifest["collections"][kind] = deepcopy(entries)
            for entry in entries:
                for name in (entry["document"], *entry["files"]):
                    await asyncio.to_thread(self.copy_file, name)
        entries = {row["id"]: row for row in manifest["collections"]["reports"]}
        for row in await self.rows("reports", "ORDER BY id"):
            original = self.originals.get(str(row["id"]))
            document = (
                deepcopy(original)
                if original
                else {
                    "id": "report:" + str(row["id"]),
                    "revisions": [],
                    "attachments": [],
                    "sections": [],
                    "runs": [],
                    "outputs": [],
                    "provenance": [],
                    "template_snapshot": None,
                    "metadata": {},
                }
            )
            document.update(
                name=row["name"] or row["query"],
                content=row["content"] if row["content"] is not None else row["html"],
                version=row["version"],
            )
            document["revisions"] = [
                {
                    "version": item["revision"],
                    "content": item["content"],
                    "metadata": item["metadata"],
                }
                for item in await self.rows(
                    "report_revisions", "AND report_id=$3 ORDER BY revision", row["id"]
                )
            ]
            run_ids = set()
            if not original:
                for section in await self.rows(
                    "report_sections", "AND report_id=$3 ORDER BY ordinal,id", row["id"]
                ):
                    if digest(section["rendered_markdown"]) != section[
                        "content_digest"
                    ].removeprefix("sha256:"):
                        raise ExportError("Report section content digest mismatch")
                    output_id = section["run_output_id"]
                    if output_id is not None:
                        output = self.output(output_id)
                        document["outputs"].append(output)
                        run_ids.add(str(self.outputs[str(output_id)]["run_id"]))
                    document["sections"].append(
                        {
                            "id": section["section_id"],
                            "ordinal": section["ordinal"],
                            "output_id": (
                                self.identity("outputs", output_id)
                                if output_id
                                else None
                            ),
                            "content_digest": section["content_digest"].removeprefix(
                                "sha256:"
                            ),
                            "metadata": plain(
                                {
                                    key: value
                                    for key, value in section.items()
                                    if key
                                    not in {
                                        "id",
                                        "report_id",
                                        "section_id",
                                        "ordinal",
                                        "run_output_id",
                                        "content_digest",
                                        "user_id",
                                        "version_id",
                                    }
                                }
                            ),
                        }
                    )
                if row["template_content_digest"]:
                    document["template_snapshot"] = {
                        "content_digest": row["template_content_digest"],
                        "sections": deepcopy(document["sections"]),
                    }
                    template = await self.connection.fetchrow(
                        "SELECT name,content FROM templates WHERE id=$1 AND user_id=$2",
                        row["template_id"],
                        self.context.user_id,
                    )
                    if (
                        template
                        and "sha256:" + digest(template["content"])
                        == row["template_content_digest"]
                    ):
                        document["template_snapshot"].update(
                            name=template["name"], content=template["content"]
                        )
                own = await self.provenance(
                    "report_provenance_exports", "report_id", row["id"]
                )
                document["provenance"] = [
                    {k: v for k, v in item.items() if k != "receipt"} for item in own
                ]
                document["metadata"]["provenance_receipts"] = [
                    item["receipt"] for item in own
                ]
                document["metadata"].update(
                    {
                        key: plain(row.get(key))
                        for key in (
                            "generation_type",
                            "generation_status",
                            "generated_at",
                            "artifact_digest",
                            "release_receipt",
                            "created_at",
                        )
                    }
                )
            changes = {
                key: value
                for key, value in (row["provenance_data"] or {}).items()
                if key not in {"original_metadata", "template_snapshot"}
            }
            if changes:
                document["metadata"]["lunar_report_metadata"] = changes
            document["metadata"]["lunar_export_snapshot"] = {
                "import_archive_digest": manifest["_archive_digest"],
                "exported_at": manifest["_exported_at"],
            }
            entry = entries.get(document["id"], {})
            await self.complete(
                document, run_ids, entry.get("files", ()), entry.get("references", ())
            )
        for identity, row in self.outputs.items():
            run = self.runs[str(row["run_id"])]
            if (
                run["imported"]
                or run["state"] != "completed"
                or not (row["markdown"] or "").strip()
            ):
                continue
            document = {
                "id": "output:" + identity,
                "name": run["workflow_id"] + " report",
                "content": row["markdown"],
                "version": 1,
                "revisions": [],
                "attachments": [],
                "sections": [],
                "runs": [],
                "outputs": [self.output(identity)],
                "provenance": [],
                "template_snapshot": None,
                "metadata": {
                    "native_output_id": identity,
                    "generation_type": "prism",
                    "lunar_export_snapshot": {
                        "import_archive_digest": manifest["_archive_digest"],
                        "exported_at": manifest["_exported_at"],
                    },
                },
            }
            await self.complete(document, {str(row["run_id"])})


async def export_version(connection, storage, *, user_id, version_id, workspace):
    await connection.set_type_codec(
        "jsonb", schema="pg_catalog", encoder=json.dumps, decoder=json.loads
    )
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            context = await owned_context(connection, user_id, version_id)
            row = await connection.fetchrow(
                "SELECT manifest,archive_digest,transaction_timestamp() AS snapshot_at FROM package_versions WHERE id=$1 AND user_id=$2",
                version_id,
                user_id,
            )
            manifest = deepcopy(row["manifest"])
            builder = ArchiveBuilder(
                workspace / "snapshot",
                package_key=manifest["package"]["key"],
                display_name=manifest["package"]["display_name"],
            )
            builder.manifest["runtime"] = deepcopy(manifest["runtime"])
            manifest.update(
                _archive_digest=row["archive_digest"],
                _exported_at=plain(row["snapshot_at"]),
            )
            await VersionSnapshot(connection, context, storage, builder).collect(
                manifest
            )
            from .source_workflows import upgrade_snapshot

            upgrade_snapshot(builder)
            destination = workspace / "package.zip"
            await asyncio.to_thread(builder.publish, destination)
            return destination, {
                "source_archive_digest": row["archive_digest"],
                "snapshot_at": plain(row["snapshot_at"]),
                "version": context.version,
                "package_key": manifest["package"]["key"],
            }
    finally:
        await connection.reset_type_codec("jsonb", schema="pg_catalog")
