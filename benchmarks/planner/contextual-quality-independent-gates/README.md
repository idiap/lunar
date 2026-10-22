<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Independent contextual-quality gates

This benchmark keeps family-level validation material separate from melanoma
development. It exercises the public planner entry point across direct,
composed, ambiguous, blocked, and correction requests. Family is the unit of
inference; paraphrases are never counted as independent observations.

`sealed-rehearsal-cases.jsonl` is intentionally disclosed. It tests the sealed
runner protocol (no repair, no selective rerun, immutable policy), but **is not
a confidential one-time certification corpus**. A release owner must substitute
an access-controlled corpus and rotate it after disclosure before making that
claim.

Build and run:

```bash
python scripts/repository/build_independent_quality_gate_corpus.py
python scripts/evaluation/run_independent_quality_gates.py --partition validation
python scripts/evaluation/run_independent_quality_gates.py --partition sealed_rehearsal --run-sealed-rehearsal
```
