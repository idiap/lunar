# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Native package report layouts render without weakening checksum validation."""

import hashlib
import json

from test_report_chat import (
    chat_browser as chat_browser,
    frontend_url as frontend_url,
    playwright,
    RUN_ID,
)


def test_bioagents_report_renders(chat_browser):
    page, state, url = chat_browser
    markdown = "# Completed report\n\nVerified narrative.\n"
    layout = {
        "schema_version": "bioagents.native-report/v1",
        "groups": [],
        "blocks": [
            {
                "id": "body",
                "kind": "prose",
                "start": 0,
                "end": len(markdown),
                "group_keys": [],
            }
        ],
        "content_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
    }
    layout["metadata_sha256"] = hashlib.sha256(
        json.dumps(layout, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output = {"markdown": markdown, "structured_value": {"report_layout": layout}}
    page.route(
        "**/api/prism/runs/" + RUN_ID,
        lambda route: route.fulfill(
            json={"id": RUN_ID, "workflow_id": "example-workflow", "outputs": [output]}
        ),
    )
    page.goto(url + "/prism/runs/" + RUN_ID + "/report")
    playwright.expect(
        page.get_by_role("heading", name="Completed report")
    ).to_be_visible()
    playwright.expect(
        page.get_by_text("Verified narrative.", exact=True)
    ).to_be_visible()
    playwright.expect(
        page.get_by_text("Required report metadata is unavailable.")
    ).to_have_count(0)
