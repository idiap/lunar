<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Blinded calibration protocol

1. Freeze case inputs, output-equivalence contracts, acceptance tests, activity
   taxonomy, policy, and evaluation split before exposing estimates.
2. Recruit at least two experienced reviewers for every promoted domain/risk
   stratum. Record role and experience band without employee-performance data.
3. Produce manual and assisted outputs independently. Both must pass identical
   scientific acceptance, provenance, and review criteria.
4. Record aggregate active effort by work unit, residual review/correction,
   dependency waits, and output acceptance. Do not use automated runtime as a
   manual-effort oracle.
5. Keep calibration and held-out evaluation splits separate. Adjudicate large
   reviewer disagreements without revealing estimator predictions.
6. Report signed bias, absolute error, interval coverage, residual-effort
   underestimation, false-positive savings, inter-reviewer disagreement, and
   quality parity by activity/domain/risk tier.
7. For resource calibration, retain privacy-filtered counts and opaque IDs only;
   report quantile loss, P50/P90 error, retry calibration, overrun rate,
   unpriced share, drift, and invoice discrepancy.
8. Do not promote to advisory unless the policy thresholds pass. Synthetic or
   disclosed fixtures can never substitute for held-out human evidence.
