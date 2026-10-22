# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Low-level verification for deployment-authenticated quality receipts.

The signing key is owned by the Lunar deployment.  Planner continuation
code imports this module without importing assessment orchestration, avoiding a
cycle with :mod:`quality_authorization`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from .contracts import canonical_digest


def verify_signed_quality_receipt(
    value: Mapping[str, Any], trusted_key: bytes, label: str
) -> None:
    """Verify the canonical digest and HMAC of one quality receipt."""

    if len(trusted_key) < 32:
        raise ValueError("quality attestation key must contain at least 32 bytes")
    if value.get("digest") != canonical_digest(value):
        raise ValueError(f"{label} digest is invalid")
    payload = {
        key: item for key, item in value.items() if key not in {"digest", "signature"}
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    expected = (
        "hmac-sha256:" + hmac.new(trusted_key, encoded, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(str(value.get("signature", "")), expected):
        raise ValueError(f"{label} signature is invalid")
