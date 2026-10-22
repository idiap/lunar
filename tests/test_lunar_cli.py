# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Tests for the package iteration CLI."""

import json
from email.message import Message
from typing import Any

import pytest

from scripts import lunar_cli


class FakeResponse:
    def __init__(self, status, value, *, headers=None):
        self.status = status
        self.reason = "test response"
        self._body = json.dumps(value).encode()
        self.headers = Message()
        for key, item in (headers or {}).items():
            self.headers[key] = item

    def read(self):
        return self._body


class FakeConnection:
    def __init__(self, requests):
        self.requests = requests
        self.method = None
        self.path = None
        self.headers = {}
        self.body = bytearray()

    def request(self, method, path, body=None, headers=None):
        self.method = method
        self.path = path
        self.headers = headers or {}
        self.body.extend(body or b"")

    def putrequest(self, method, path):
        self.method, self.path = method, path

    def putheader(self, key, value):
        self.headers[key] = value

    def endheaders(self):
        pass

    def send(self, body):
        self.body.extend(body)

    def close(self):
        pass

    def getresponse(self):
        body = bytes(self.body)
        self.requests.append((self.method, self.path, self.headers, body))
        if self.path == "/api/auth/signin":
            assert json.loads(body) == {
                "email": "user@example.test",
                "password": "secret",
            }
            return FakeResponse(
                200,
                {"user": {"id": "owner"}},
                headers={
                    "Set-Cookie": "report_session=session-value; HttpOnly; Path=/"
                },
            )
        if self.path == "/api/packages/import":
            assert self.headers["Cookie"] == "report_session=session-value"
            assert b'name="file"; filename="package.zip"' in body
            assert b"package-bytes" in body
            return FakeResponse(
                201,
                {"version": {"id": "version-1", "runtime_state": "unprepared"}},
            )
        if self.path == "/api/packages/versions/version-1/prepare":
            assert self.headers["Cookie"] == "report_session=session-value"
            return FakeResponse(200, {"runtime_state": "ready"})
        if self.path == "/api/prism/workflows":
            assert self.headers["X-Lunar-Package-Version"] == "version-1"
            return FakeResponse(
                200,
                [{"id": "inventory", "input_schema": {"required": ["count"]}}],
            )
        if self.path == "/api/prism/workflows/inventory/runs":
            assert self.headers["X-Lunar-Package-Version"] == "version-1"
            assert json.loads(body)["inputs"] == {"count": 41}
            return FakeResponse(202, {"run_id": "run-1", "state": "queued"})
        if self.path == "/api/prism/runs/run-1":
            assert self.headers["X-Lunar-Package-Version"] == "version-1"
            return FakeResponse(
                200, {"id": "run-1", "state": "completed", "outputs": []}
            )
        return FakeResponse(404, {"error": "not found"})


def fake_client():
    requests = []
    client = lunar_cli.LunarClient("http://lunar.example.test")
    client_any: Any = client
    client_any._connection = lambda: FakeConnection(requests)
    return client, requests


def test_http_client_supports_full_iteration_cycle(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package-bytes")
    client, requests = fake_client()

    client.sign_in("user@example.test", "secret")
    version = client.upload(package)
    assert version["id"] == "version-1"
    assert client.prepare(version["id"]) == {"runtime_state": "ready"}
    assert client.workflows(version["id"])[0]["input_schema"]["required"] == ["count"]
    accepted = client.start_run(
        version["id"],
        "inventory",
        inputs={"count": 41},
        ai_model_id=None,
        network_authority=False,
    )
    assert client.run_detail(version["id"], accepted["run_id"])["state"] == "completed"
    assert len(requests) == 6


def test_parse_inputs_accepts_inline_file_and_stdin(tmp_path, monkeypatch):
    path = tmp_path / "inputs.json"
    path.write_text('{"count": 41}', encoding="utf-8")
    assert lunar_cli.parse_inputs('{"count": 40}') == {"count": 40}
    assert lunar_cli.parse_inputs("@" + str(path)) == {"count": 41}
    monkeypatch.setattr(
        "sys.stdin", type("Input", (), {"read": lambda self: '{"count": 42}'})()
    )
    assert lunar_cli.parse_inputs("-") == {"count": 42}


def test_parse_inputs_requires_a_json_object():
    with pytest.raises(lunar_cli.CliError, match="JSON object"):
        lunar_cli.parse_inputs("[1, 2]")


def test_api_errors_include_server_message():
    client, _ = fake_client()
    client.session_token = "session-value"
    with pytest.raises(lunar_cli.CliError, match="not found"):
        client.prepare("missing")


def test_cycle_command_composes_upload_prepare_run_and_wait(
    tmp_path, monkeypatch, capsys
):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")

    class CycleClient:
        def __init__(self, *args, session_token=None, **kwargs):
            self.session_token = session_token

        def upload(self, path):
            assert path == package
            return {"id": "version-1"}

        def prepare(self, version_id):
            assert version_id == "version-1"
            return {"runtime_state": "ready"}

        def start_run(self, version_id, workflow_id, **values):
            assert (version_id, workflow_id) == ("version-1", "inventory")
            assert values["inputs"] == {"count": 41}
            return {"run_id": "run-1", "state": "queued"}

        def run_detail(self, version_id, run_id):
            assert (version_id, run_id) == ("version-1", "run-1")
            return {"id": "run-1", "state": "completed", "outputs": []}

    monkeypatch.setattr(lunar_cli, "LunarClient", CycleClient)
    status = lunar_cli.main(
        [
            "--session-token",
            "token",
            "cycle",
            str(package),
            "inventory",
            "--inputs",
            '{"count": 41}',
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["version"]["id"] == "version-1"
    assert output["preparation"]["runtime_state"] == "ready"
    assert output["run"]["state"] == "completed"
