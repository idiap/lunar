# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Consume exactly one multipart ZIP with finite headers and actual byte limits."""

import asyncio

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header

from .format.contract import PackageValidationError


async def receive_zip(request, path, limits):
    """Stream an authenticated upload into one private regular file, ignoring its filename."""
    content_type, options = parse_options_header(
        request.headers.get("content-type", "")
    )
    boundary = options.get(b"boundary", b"")
    if content_type != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise PackageValidationError("expected multipart/form-data with one file field")
    total, payload, parts, header_bytes = 0, 0, 0, 0
    headers = {}
    field, value = bytearray(), bytearray()
    ready, ended = False, False
    with path.open("xb") as output:

        def part_begin():
            nonlocal parts
            parts += 1
            if parts != 1:
                raise PackageValidationError(
                    "upload accepts exactly one file; owner overrides are forbidden"
                )

        def header_field(data, start, end):
            nonlocal header_bytes
            header_bytes += end - start
            if header_bytes > 8192:
                raise PackageValidationError("multipart headers exceed limit")
            field.extend(data[start:end])

        def header_value(data, start, end):
            nonlocal header_bytes
            header_bytes += end - start
            if header_bytes > 8192:
                raise PackageValidationError("multipart headers exceed limit")
            value.extend(data[start:end])

        def header_end():
            key = bytes(field).lower()
            if key in headers:
                raise PackageValidationError("duplicate multipart header")
            headers[key] = bytes(value)
            field.clear()
            value.clear()

        def headers_finished():
            nonlocal ready
            disposition, parameters = parse_options_header(
                headers.get(b"content-disposition", b"")
            )
            if (
                disposition != b"form-data"
                or parameters.get(b"name") != b"file"
                or b"filename" not in parameters
            ):
                raise PackageValidationError(
                    "upload accepts only the file field; owner overrides are forbidden"
                )
            ready = True

        def part_data(data, start, end):
            nonlocal payload
            if not ready:
                raise PackageValidationError("payload before multipart headers")
            payload += end - start
            if payload > limits.compressed_bytes:
                raise PackageValidationError("compressed upload limit exceeded")
            output.write(data[start:end])

        def finished():
            nonlocal ended
            ended = True

        parser = MultipartParser(
            boundary,
            {
                "on_part_begin": part_begin,
                "on_header_field": header_field,
                "on_header_value": header_value,
                "on_header_end": header_end,
                "on_headers_finished": headers_finished,
                "on_part_data": part_data,
                "on_end": finished,
            },
        )
        try:
            async for chunk in request.stream():
                total += len(chunk)
                if total > limits.compressed_bytes + 65536:
                    raise PackageValidationError("multipart upload limit exceeded")
                await asyncio.to_thread(parser.write, chunk)
            parser.finalize()
        except MultipartParseError as exc:
            raise PackageValidationError("invalid multipart upload") from exc
        if not ended or parts != 1 or not payload:
            raise PackageValidationError("incomplete multipart upload")
    return path
