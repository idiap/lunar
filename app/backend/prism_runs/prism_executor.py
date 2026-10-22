# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Host dispatch for validated package registrations; compilation runs in the worker."""


def execute_prism(*, runtime, workflow_id, **arguments):
    return runtime.execute(workflow_id, **arguments)
