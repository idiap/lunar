# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Regression checks for the repository's third-party attribution exception."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "idiap_sd", Path(__file__).resolve().parents[1] / ".idiap-sd/idiap_sd.py"
)
assert SPEC is not None and SPEC.loader is not None
sd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sd)


def test_vendored_asset_retains_upstream_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asset = Path("vendor.js")
    asset.write_text("const upstream = true;\n")
    config = {
        "license": "MIT",
        "copyright": "2026 Example Institute",
        "lfs_min_bytes": 1024,
        "contributors": [],
        "file_overrides": {
            "vendor.js": {
                "license": "Apache-2.0",
                "copyright": "2022 Upstream Authors",
                "contributors": [],
                "use_sidecar": True,
            }
        },
    }
    Path("config.json").write_text(json.dumps(config))
    monkeypatch.setattr(sd, "paths", lambda: [asset])
    monkeypatch.setattr(sd, "contributors_for", lambda path, config: [])
    monkeypatch.setattr(
        sd, "git", lambda *a, **kw: type("Result", (), {"returncode": 0})()
    )
    monkeypatch.setattr("sys.argv", ["idiap_sd.py", "apply", "--config", "config.json"])
    assert sd.main() == 0
    sidecar = sd.license_path(asset).read_text()
    assert "Apache-2.0" in sidecar
    assert "2022 Upstream Authors" in sidecar
    assert "Example Institute" not in sidecar
    assert asset.read_text() == "const upstream = true;\n"
    monkeypatch.setattr("sys.argv", ["idiap_sd.py", "check", "--config", "config.json"])
    assert sd.main() == 0
    sd.license_path(asset).write_text(sidecar.replace("Apache-2.0", "MIT"))
    assert sd.main() == 1


def test_empty_frontend_configuration_fails():
    assert sd.run_frontend_tests({"frontend_tests": []}) == 1


@pytest.mark.parametrize(
    "name,preamble,body",
    [
        ("component.jsx", "", "export const Component = () => <div />;\n"),
        ("script.js", "#!/usr/bin/env node\n", "console.log('ok');\n"),
        ("style.css", '@charset "UTF-8";\n', "body { color: red; }\n"),
        ("SKILL.md", "---\nname: example\n---\n", "# Example\n"),
        (
            "icon.svg",
            '<?xml version="1.0"?>\n',
            '<svg xmlns="http://www.w3.org/2000/svg"/>\n',
        ),
        ("Dockerfile.base", "# syntax=docker/dockerfile:1\n", "FROM scratch\n"),
        ("uv.lock", "", "version = 1\n"),
    ],
)
def test_sidecar_migration_preserves_content_and_existing_credit(
    tmp_path, name, preamble, body
):
    asset = tmp_path / name
    asset.write_text(preamble + body)
    config = {
        "license": "MIT",
        "copyright": "2026 Example Institute",
        "contributors": [],
    }
    contributor = {
        "spdx_contributor": "Original Author <author@example.org>",
        "group": "Original Group",
    }
    sidecar = sd.license_path(asset)
    sidecar.write_text(sd.metadata(config, [contributor], ""))
    assert sd.apply_metadata(asset, config, []) == []
    migrated = asset.read_text()
    assert migrated.startswith(preamble)
    assert migrated.endswith(body)
    assert "Original Author <author@example.org>" in migrated
    assert not sidecar.exists()
    assert sd.check_metadata(asset, config, [contributor]) == []
    assert sd.apply_metadata(asset, config, []) == []
    assert asset.read_text() == migrated


def test_conflicting_sidecar_is_preserved(tmp_path):
    asset = tmp_path / "component.jsx"
    asset.write_text("export default null;\n")
    sidecar = sd.license_path(asset)
    config = {
        "license": "MIT",
        "copyright": "2026 Example Institute",
        "contributors": [],
    }
    original = sd.metadata({**config, "license": "Apache-2.0"}, [], "")
    sidecar.write_text(original)
    assert sd.apply_metadata(asset, config, [])
    assert asset.read_text() == "export default null;\n"
    assert sidecar.read_text() == original
