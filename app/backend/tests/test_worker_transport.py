# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Provider waits cannot prevent worker cancellation."""

import threading
import pytest
from domain_packages.worker.transport import _channel_result
from domain_packages.worker.sandbox import WorkerUnavailable


def test_interruption_during_provider_request_does_not_wait_for_provider():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def provider(arguments):
        entered.set()
        release.wait(5)
        finished.set()
        return {"late": True}

    def check():
        if entered.is_set():
            raise WorkerUnavailable("worker interrupted")

    try:
        with pytest.raises(WorkerUnavailable, match="interrupted"):
            _channel_result(provider, {}, check)
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)


def test_provider_result_and_failure_are_forwarded():
    assert _channel_result(
        lambda args: {"value": args["value"]}, {"value": 42}, lambda: None
    ) == {"value": 42}

    def failed(args):
        raise ValueError("provider failure")

    with pytest.raises(ValueError, match="provider failure"):
        _channel_result(failed, {}, lambda: None)
