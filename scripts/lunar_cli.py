#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Upload, prepare, and execute Lunar packages through the public HTTP API."""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import secrets
import ssl
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote, urlsplit

TERMINAL_STATES = {"completed", "failed", "cancelled"}


class CliError(RuntimeError):
    """A user-facing CLI failure."""


class LunarClient:
    def __init__(
        self,
        base_url: str,
        *,
        session_token: str | None = None,
        session_cookie_name: str = "report_session",
        timeout: float = 60.0,
    ) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CliError("Lunar URL must start with http:// or https://")
        if parsed.query or parsed.fragment:
            raise CliError("Lunar URL cannot contain a query string or fragment")
        self.scheme = parsed.scheme
        self.host = parsed.hostname or ""
        self.port = parsed.port
        self.base_path = parsed.path.rstrip("/")
        self.timeout = timeout
        self.session_token = session_token
        self.session_cookie_name = session_cookie_name

    def _connection(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(
                self.host,
                self.port,
                timeout=self.timeout,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _path(self, path: str) -> str:
        return f"{self.base_path}/{path.lstrip('/')}"

    def _headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        result = {"Accept": "application/json", **(headers or {})}
        if self.session_token:
            result["Cookie"] = f"{self.session_cookie_name}={self.session_token}"
        return result

    @staticmethod
    def _decode_response(response: http.client.HTTPResponse) -> Any:
        content = response.read()
        if not content:
            return None
        try:
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CliError(
                f"Lunar returned a non-JSON response (HTTP {response.status})"
            ) from exc

    @staticmethod
    def _check_response(response: http.client.HTTPResponse, value: Any) -> Any:
        if 200 <= response.status < 300:
            return value
        message = value.get("error") if isinstance(value, dict) else None
        if not message:
            message = response.reason or "request failed"
        details = value.get("details") if isinstance(value, dict) else None
        suffix = f": {json.dumps(details, ensure_ascii=False)}" if details else ""
        raise CliError(f"Lunar API error (HTTP {response.status}): {message}{suffix}")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        encoded = None
        request_headers = self._headers(headers)
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        connection = self._connection()
        try:
            connection.request(
                method, self._path(path), body=encoded, headers=request_headers
            )
            response = connection.getresponse()
            value = self._decode_response(response)
            return self._check_response(response, value)
        except (OSError, http.client.HTTPException) as exc:
            raise CliError(
                f"Could not reach Lunar at {self.scheme}://{self.host}: {exc}"
            ) from exc
        finally:
            connection.close()

    def sign_in(self, email: str, password: str) -> None:
        connection = self._connection()
        encoded = json.dumps({"email": email, "password": password}).encode()
        try:
            connection.request(
                "POST",
                self._path("/api/auth/signin"),
                body=encoded,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            value = self._decode_response(response)
            self._check_response(response, value)
            cookie = SimpleCookie()
            for header in response.headers.get_all("Set-Cookie", []):
                cookie.load(header)
            morsel = cookie.get(self.session_cookie_name)
            if morsel is None:
                raise CliError(
                    "Sign-in succeeded but Lunar did not return a session cookie"
                )
            self.session_token = morsel.value
        except (OSError, http.client.HTTPException) as exc:
            raise CliError(
                f"Could not reach Lunar at {self.scheme}://{self.host}: {exc}"
            ) from exc
        finally:
            connection.close()

    def upload(self, package: Path) -> dict[str, Any]:
        boundary = "----lunar-cli-" + secrets.token_hex(16)
        prefix = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="package.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        try:
            package_size = package.stat().st_size
        except OSError as exc:
            raise CliError(f"Cannot read package {package}: {exc}") from exc
        if not package.is_file():
            raise CliError(f"Package is not a file: {package}")

        connection = self._connection()
        headers = self._headers(
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(prefix) + package_size + len(suffix)),
            }
        )
        try:
            connection.putrequest("POST", self._path("/api/packages/import"))
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            connection.send(prefix)
            with package.open("rb") as stream:
                self._send_file(connection, stream)
            connection.send(suffix)
            response = connection.getresponse()
            value = self._decode_response(response)
            result = self._check_response(response, value)
            if not isinstance(result, dict) or not isinstance(
                result.get("version"), dict
            ):
                raise CliError("Lunar returned an invalid package import response")
            return result["version"]
        except (OSError, http.client.HTTPException) as exc:
            raise CliError(f"Package upload failed: {exc}") from exc
        finally:
            connection.close()

    @staticmethod
    def _send_file(connection: http.client.HTTPConnection, stream: BinaryIO) -> None:
        while chunk := stream.read(1024 * 1024):
            connection.send(chunk)

    def prepare(self, version_id: str) -> dict[str, Any]:
        return self.request_json(
            "POST", f"/api/packages/versions/{quote(version_id, safe='')}/prepare"
        )

    def workflows(self, version_id: str) -> list[dict[str, Any]]:
        result = self.request_json(
            "GET",
            "/api/prism/workflows",
            headers={"X-Lunar-Package-Version": version_id},
        )
        if not isinstance(result, list):
            raise CliError("Lunar returned an invalid workflow list")
        return result

    def start_run(
        self,
        version_id: str,
        workflow_id: str,
        *,
        inputs: dict[str, Any],
        ai_model_id: str | None,
        network_authority: bool,
    ) -> dict[str, Any]:
        return self.request_json(
            "POST",
            f"/api/prism/workflows/{quote(workflow_id, safe='')}/runs",
            headers={"X-Lunar-Package-Version": version_id},
            body={
                "operation": "run",
                "ai_model_id": ai_model_id,
                "inputs": inputs,
                "network_authority": network_authority,
            },
        )

    def run_detail(self, version_id: str, run_id: str) -> dict[str, Any]:
        result = self.request_json(
            "GET",
            f"/api/prism/runs/{quote(run_id, safe='')}",
            headers={"X-Lunar-Package-Version": version_id},
        )
        if not isinstance(result, dict):
            raise CliError("Lunar returned an invalid run response")
        return result


def parse_inputs(value: str) -> dict[str, Any]:
    if value == "-":
        source = sys.stdin.read()
        label = "standard input"
    elif value.startswith("@"):
        path = Path(value[1:]).expanduser()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CliError(f"Cannot read workflow inputs from {path}: {exc}") from exc
        label = str(path)
    else:
        source = value
        label = "--inputs"
    try:
        result = json.loads(source)
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON in {label}: {exc}") from exc
    if not isinstance(result, dict):
        raise CliError("Workflow inputs must be a JSON object")
    return result


def wait_for_run(
    client: LunarClient,
    version_id: str,
    run_id: str,
    *,
    poll_interval: float,
    run_timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + run_timeout
    last_state = None
    while True:
        run = client.run_detail(version_id, run_id)
        state = run.get("state")
        if state != last_state:
            print(f"Run {run_id}: {state}", file=sys.stderr)
            last_state = state
        if state in TERMINAL_STATES:
            return run
        if time.monotonic() >= deadline:
            raise CliError(
                f"Timed out after {run_timeout:g}s waiting for run {run_id}; the run was not stopped"
            )
        time.sleep(poll_interval)


def execute_run(
    client: LunarClient, args: argparse.Namespace, version_id: str
) -> dict[str, Any]:
    inputs = parse_inputs(args.inputs)
    accepted = client.start_run(
        version_id,
        args.workflow,
        inputs=inputs,
        ai_model_id=args.ai_model_id,
        network_authority=args.network_authority,
    )
    if not args.wait:
        return accepted
    return wait_for_run(
        client,
        version_id,
        accepted["run_id"],
        poll_interval=args.poll_interval,
        run_timeout=args.run_timeout,
    )


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def add_run_arguments(parser: argparse.ArgumentParser, *, version: bool) -> None:
    if version:
        parser.add_argument("version", help="uploaded package version UUID")
    parser.add_argument("workflow", help="workflow execution ID")
    parser.add_argument(
        "--inputs",
        required=True,
        metavar="JSON|@FILE|-",
        help="required workflow inputs as JSON, @path, or - for stdin",
    )
    parser.add_argument("--ai-model-id", help="configured Lunar AI model UUID")
    parser.add_argument(
        "--network-authority",
        action="store_true",
        help="allow the workflow's declared public network reads",
    )
    waiting = parser.add_mutually_exclusive_group()
    waiting.add_argument("--wait", action="store_true", default=True)
    waiting.add_argument("--no-wait", action="store_false", dest="wait")
    parser.add_argument("--poll-interval", type=float, default=1.0, metavar="SECONDS")
    parser.add_argument("--run-timeout", type=float, default=3600.0, metavar="SECONDS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("LUNAR_URL", "http://localhost:8080"),
        help="Lunar base URL (default: LUNAR_URL or http://localhost:8080)",
    )
    parser.add_argument("--email", default=os.getenv("LUNAR_EMAIL"))
    parser.add_argument("--password", default=os.getenv("LUNAR_PASSWORD"))
    parser.add_argument(
        "--session-token",
        default=os.getenv("LUNAR_SESSION_TOKEN"),
        help="existing session token (default: LUNAR_SESSION_TOKEN)",
    )
    parser.add_argument(
        "--session-cookie-name",
        default=os.getenv("LUNAR_SESSION_COOKIE_NAME", "report_session"),
    )
    parser.add_argument("--http-timeout", type=float, default=60.0, metavar="SECONDS")
    commands = parser.add_subparsers(dest="command", required=True)

    upload = commands.add_parser("upload", help="upload a package ZIP")
    upload.add_argument("package", type=Path)

    prepare = commands.add_parser("prepare", help="prepare an uploaded runtime")
    prepare.add_argument("version")

    workflows = commands.add_parser(
        "workflows", help="list workflows and their expected input schemas"
    )
    workflows.add_argument("version")
    workflows.add_argument("workflow", nargs="?", help="show only this workflow")

    run = commands.add_parser("run", help="run a workflow from an uploaded package")
    add_run_arguments(run, version=True)

    cycle = commands.add_parser(
        "cycle", help="upload, prepare, run, and wait in one command"
    )
    cycle.add_argument("package", type=Path)
    add_run_arguments(cycle, version=False)
    return parser


def authenticate(client: LunarClient, args: argparse.Namespace) -> None:
    if client.session_token:
        return
    if not args.email:
        raise CliError(
            "Provide --email/LUNAR_EMAIL or --session-token/LUNAR_SESSION_TOKEN"
        )
    password = args.password
    if password is None:
        if not sys.stdin.isatty():
            raise CliError("Set LUNAR_PASSWORD when standard input is not interactive")
        password = getpass.getpass("Lunar password: ")
    client.sign_in(args.email, password)


def dispatch(client: LunarClient, args: argparse.Namespace) -> tuple[Any, int]:
    if args.command == "upload":
        print(f"Uploading {args.package}...", file=sys.stderr)
        return client.upload(args.package), 0
    if args.command == "prepare":
        print(f"Preparing runtime for {args.version}...", file=sys.stderr)
        return client.prepare(args.version), 0
    if args.command == "workflows":
        workflows = client.workflows(args.version)
        if args.workflow:
            workflow = next(
                (item for item in workflows if item.get("id") == args.workflow), None
            )
            if workflow is None:
                raise CliError(f"Workflow not found: {args.workflow}")
            return workflow, 0
        return workflows, 0
    if args.command == "run":
        result = execute_run(client, args, args.version)
        return result, 1 if result.get("state") in {"failed", "cancelled"} else 0
    if args.command == "cycle":
        print(f"Uploading {args.package}...", file=sys.stderr)
        version = client.upload(args.package)
        version_id = version["id"]
        print(f"Preparing runtime for {version_id}...", file=sys.stderr)
        preparation = client.prepare(version_id)
        run = execute_run(client, args, version_id)
        result = {"version": version, "preparation": preparation, "run": run}
        return result, 1 if run.get("state") in {"failed", "cancelled"} else 0
    raise CliError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.http_timeout <= 0:
        parser.error("--http-timeout must be greater than zero")
    if hasattr(args, "poll_interval") and args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")
    if hasattr(args, "run_timeout") and args.run_timeout <= 0:
        parser.error("--run-timeout must be greater than zero")
    try:
        client = LunarClient(
            args.url,
            session_token=args.session_token,
            session_cookie_name=args.session_cookie_name,
            timeout=args.http_timeout,
        )
        authenticate(client, args)
        result, status = dispatch(client, args)
        print_json(result)
        return status
    except (CliError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
