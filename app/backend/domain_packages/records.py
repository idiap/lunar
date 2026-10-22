# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Persist validated package content and fresh navigation IDs without source authority."""

import hashlib
import json
import re
from uuid import uuid4

from .format.contract import PackageValidationError, _json


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def content_digest(value):
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def historical_facts(documents):
    """Shared historical identities must describe exactly the same original facts."""
    result = {"runs": {}, "outputs": {}}
    for report in documents["reports"]:
        for kind in result:
            for row in report[kind]:
                prior = result[kind].setdefault(row["id"], row)
                if prior != row:
                    raise PackageValidationError(
                        "conflicting shared historical " + kind + " identity"
                    )
    return result


async def insert_records(connection, context, archive):
    """Insert complete version-owned documents, payload metadata, projections and mappings."""
    owner, version = context.user_id, context.version_id
    manifest, documents, root = archive.manifest, archive.documents, archive.root
    facts = historical_facts(documents)
    resources = {
        (kind, row["id"]): uuid4() for kind, rows in documents.items() for row in rows
    }
    files = {row["path"]: uuid4() for row in manifest["files"]}
    mappings = {kind: {key: uuid4() for key in rows} for kind, rows in facts.items()}
    document_paths = {
        row["document"] for rows in manifest["collections"].values() for row in rows
    }
    provenance_paths = {
        row["file"] for report in documents["reports"] for row in report["provenance"]
    }
    database_paths = document_paths | provenance_paths
    await connection.executemany(
        "INSERT INTO package_resources(id,version_id,user_id,collection,logical_id,document) VALUES($1,$2,$3,$4,$5,$6::jsonb)",
        [
            (resources[kind, row["id"]], version, owner, kind, row["id"], encoded(row))
            for kind, rows in documents.items()
            for row in rows
        ],
    )
    # Files are batched to avoid retaining complete binary datasets in memory.
    for row in manifest["files"]:
        database = row["path"] in database_paths
        await connection.execute(
            """INSERT INTO package_files(id,version_id,user_id,path,size,sha256,media_type,storage_kind,payload)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            files[row["path"]],
            version,
            owner,
            row["path"],
            row["size"],
            row["sha256"],
            row["media_type"],
            "database" if database else "filesystem",
            (root / row["path"]).read_bytes() if database else None,
        )
    file_links, resource_links = [], []
    for kind, rows in manifest["collections"].items():
        for row in rows:
            identity = resources[kind, row["id"]]
            file_links.extend(
                (identity, files[name], version, owner)
                for name in {row["document"], *row["files"]}
            )
            resource_links.extend(
                (identity, resources[ref["collection"], ref["id"]], version, owner)
                for ref in row["references"]
            )
    await connection.executemany(
        "INSERT INTO package_resource_files(resource_id,file_id,version_id,user_id) VALUES($1,$2,$3,$4)",
        file_links,
    )
    await connection.executemany(
        "INSERT INTO package_resource_links(source_id,target_id,version_id,user_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        resource_links,
    )
    navigation = [
        (version, owner, kind, key, identity)
        for (kind, key), identity in resources.items()
    ]
    navigation += [
        (version, owner, kind, key, identity)
        for kind, rows in mappings.items()
        for key, identity in rows.items()
    ]
    await connection.executemany(
        "INSERT INTO package_import_mappings(version_id,user_id,source_collection,source_id,local_id) VALUES($1,$2,$3,$4,$5)",
        navigation,
    )
    from .source_workflows import runtime_manifest

    registrations = {
        row["id"]: row
        for row in runtime_manifest(manifest, root)["runtime"]["workflows"]
    }
    await connection.executemany(
        "INSERT INTO package_workflows(id,version_id,user_id,workflow_id,registration) VALUES($1,$2,$3,$4,$5::jsonb)",
        [
            (uuid4(), version, owner, key, encoded(row))
            for key, row in registrations.items()
        ],
    )
    for row in documents["skills"]:
        descriptor = row["metadata"].get("descriptor", {})
        groups = row["groups"]
        await connection.execute(
            """INSERT INTO skills(id,version_id,user_id,skill_id,display_name,version,description,instructions,
            role,theme,cluster,source_path,catalog_digest,metadata,groups)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb)""",
            resources["skills", row["id"]],
            version,
            owner,
            row["id"],
            row["name"],
            str(descriptor.get("version", "1")),
            str(descriptor.get("description", "")),
            row["instructions"],
            *(groups + [None] * 3)[:3],
            next(
                item["document"]
                for item in manifest["collections"]["skills"]
                if item["id"] == row["id"]
            ),
            content_digest(encoded(row)),
            encoded(row),
            encoded(groups),
        )
    text_fields = (
        "category",
        "scope",
        "canonical_uri",
        "posture",
        "claim_ceiling",
        "owner",
        "refresh_trigger",
        "verified_as_of",
        "schema_version",
    )
    defaults = ("general", "package", "", "descriptor_only", "", "", "", "", "1")
    json_fields = (
        "aliases",
        "modalities",
        "entities",
        "identifiers",
        "access_points",
        "operations",
        "candidate_operations",
        "lineage",
    )
    for row in documents["data-sources"]:
        descriptor = row["descriptor"]
        text_values = [
            str(descriptor.get(key, default))
            for key, default in zip(text_fields, defaults)
        ]
        if text_values[3] not in {
            "descriptor_only",
            "intent_only",
            "fixture_ready",
            "live_ready",
            "blocked",
        }:
            text_values[3] = "descriptor_only"
        values = [
            resources["data-sources", row["id"]],
            version,
            owner,
            row["id"],
            row["name"],
            *text_values,
            content_digest(encoded(row)),
            *(encoded(descriptor.get(key, [])) for key in json_fields),
            encoded(row),
        ]
        await connection.execute(
            """INSERT INTO data_sources(id,version_id,user_id,resource_id,name,category,scope,canonical_uri,posture,
            claim_ceiling,owner,refresh_trigger,verified_as_of,schema_version,catalog_digest,
            aliases,modalities,entities,identifiers,access_points,operations,candidate_operations,lineage,descriptor)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17::jsonb,$18::jsonb,$19::jsonb,$20::jsonb,$21::jsonb,$22::jsonb,$23::jsonb,$24::jsonb)""",
            *values,
        )
    for key, row in facts["runs"].items():
        original = row["facts"]
        workflow = original.get("workflow_id")
        if workflow not in registrations:
            workflow = "historical:" + hashlib.sha256(key.encode()).hexdigest()
            await connection.execute(
                "INSERT INTO package_workflows(id,version_id,user_id,workflow_id,registration) VALUES($1,$2,$3,$4,$5::jsonb)",
                uuid4(),
                version,
                owner,
                workflow,
                encoded(
                    {
                        "historical_only": True,
                        "source_workflow_id": original.get("workflow_id"),
                    }
                ),
            )
        state = original.get("state", "completed")
        # Imported observations are never active jobs, including source snapshots
        # taken while a report-linked source run was still running.
        if state not in {"completed", "failed", "cancelled"}:
            state = "cancelled"
        await connection.execute(
            """INSERT INTO prism_runs(id,version_id,user_id,workflow_id,operation,mode,state,safe_input_manifest,
            accepted_plan_digest,artifact_root,imported,ai_model_snapshot,error_summary)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,'',TRUE,$10::jsonb,$11)""",
            mappings["runs"][key],
            version,
            owner,
            workflow,
            str(original.get("operation", "historical")),
            str(original.get("mode", "historical")),
            state,
            encoded(original.get("safe_input_manifest", {})),
            str(original.get("accepted_plan_digest", content_digest("historical"))),
            encoded(original.get("ai_model_snapshot")),
            original.get("error_summary"),
        )
        from .history import import_run_history

        await import_run_history(
            connection, context, mappings["runs"][key], original, archive, files
        )
    for key, row in facts["outputs"].items():
        metadata = row["metadata"]
        await connection.execute(
            """INSERT INTO prism_run_outputs(id,version_id,user_id,run_id,output_key,component_id,markdown,
            structured_value,media_type,content_digest,provenance_entity_id)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11)""",
            mappings["outputs"][key],
            version,
            owner,
            mappings["runs"][row["run_id"]],
            str(metadata.get("output_key", key)),
            str(metadata.get("component_id", "historical")),
            row["content"],
            encoded(metadata.get("structured_value")),
            str(metadata.get("media_type", "text/markdown")),
            content_digest(row["content"]),
            str(metadata.get("provenance_entity_id", key)),
        )
    for row in documents["reports"]:
        identity = resources["reports", row["id"]]
        await connection.execute(
            """INSERT INTO reports(id,version_id,user_id,logical_id,query,html,name,content,version,provenance_data,imported,generation_type)
            VALUES($1,$2,$3,$4,$5,$6,$5,$6,$7,$8::jsonb,TRUE,$9)""",
            identity,
            version,
            owner,
            row["id"],
            row["name"],
            row["content"],
            row["version"],
            encoded(
                {
                    "original_metadata": row["metadata"],
                    "template_snapshot": row["template_snapshot"],
                }
            ),
            (
                "template"
                if row["metadata"].get("generation_type") == "template"
                else None
            ),
        )
        await connection.executemany(
            "INSERT INTO report_revisions(report_id,version_id,user_id,revision,content,metadata) VALUES($1,$2,$3,$4,$5,$6::jsonb)",
            [
                (
                    identity,
                    version,
                    owner,
                    item["version"],
                    item["content"],
                    encoded(item["metadata"]),
                )
                for item in row["revisions"]
            ],
        )
        for section in row["sections"]:
            output = mappings["outputs"].get(section["output_id"])
            await connection.execute(
                """INSERT INTO report_sections(id,version_id,user_id,report_id,section_id,ordinal,placeholder_name,
                run_output_id,rendered_markdown,content_digest,provenance_entity_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                uuid4(),
                version,
                owner,
                identity,
                section["id"],
                section["ordinal"],
                str(section["metadata"].get("placeholder_name", section["id"])),
                output,
                str(
                    section["metadata"].get(
                        "rendered_markdown",
                        facts["outputs"]
                        .get(section["output_id"], {})
                        .get("content", ""),
                    )
                ),
                "sha256:" + section["content_digest"],
                str(section["metadata"].get("provenance_entity_id", section["id"])),
            )
        # A report may carry several documents of the same format (its own and
        # linked runs). Preserve every original in package_files/resources;
        # normalized single-format projections select the report's first document.
        formats = set()
        for item in row["provenance"]:
            if item["format"] in formats:
                continue
            formats.add(item["format"])
            receipt = next(
                (
                    entry.get("original_wrapper_digest")
                    for entry in row["metadata"].get("provenance_receipts", [])
                    if isinstance(entry, dict) and entry.get("file") == item["file"]
                ),
                None,
            )
            wrapper = (
                receipt
                if isinstance(receipt, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", receipt)
                else "sha256:" + item["sha256"]
            )
            await connection.execute(
                """INSERT INTO report_provenance_exports(id,version_id,user_id,report_id,format,media_type,document,wrapper_digest)
                VALUES($1,$2,$3,$4,$5,'application/json',$6::jsonb,$7)""",
                uuid4(),
                version,
                owner,
                identity,
                {"PROV-JSON": "prov-json", "JSON-LD": "json-ld"}[item["format"]],
                encoded(_json((root / item["file"]).read_bytes())),
                wrapper,
            )
    return database_paths
