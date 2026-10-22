<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Codex exec generative testing for skills

## Purpose

Deterministic validation proves that a skill is structurally valid; it does not
prove that Codex selects it correctly or that its instructions improve realistic
behavior. Every new skill, and every material skill update, therefore receives
a skill-specific generative validation pass before workflow execution and
catalog promotion.

The runner is deterministic infrastructure, not another skill. It invokes the
locally installed `codex exec` and emits a versioned
`skill-generative-validation-report.json`.

## Test manifest

`skill-generative-test-manifest.json` pins:

- creator-context, creator-result, skill-body, resource, and reuse-design
  digests;
- Codex CLI version, model, reasoning configuration, test-runner version, and
  effective non-secret configuration;
- prompt, fixture, rubric, output-schema, consumer-contract, and baseline
  digests;
- execution directory, sandbox, allowed paths, source/network policy, timeout,
  token/cost budget, concurrency, and stop rules;
- each case's intent: explicit positive, implicit-routing positive,
  non-trigger, ambiguity, near transfer, farther transfer when claimed,
  adversarial boundary, output-contract, or consumer regression; and
- number of trials justified by risk. Retries caused by infrastructure failure
  are recorded separately and never erase a behavioral failure.

Secrets and raw private data are referenced only through approved handles and
never written into prompts, manifests, JSONL, or final reports.

## Execution contract

The planned `CodexExecSkillGenerativeTestRunner`:

1. Creates a fresh temporary Git workspace containing only the target skill,
   permitted resources, sanitized fixtures, and test instructions.
2. Runs deterministic skill validation and any script tests first.
3. Executes paired cases with the same model/configuration: no-skill versus new
   skill for creation, or accepted baseline skill versus candidate for update.
4. Invokes `codex exec` non-interactively with `--ephemeral`, `--json`,
   `--output-schema`, an explicit model, `-C` set to the isolated workspace, and
   the narrowest viable sandbox (`read-only` by default).
5. Never uses `--dangerously-bypass-approvals-and-sandbox` or
   `--dangerously-bypass-hook-trust`. Network, workspace writes, external tools,
   or additional directories require explicit case-level authority.
6. Captures the command contract, exit status, JSONL event stream, final
   structured output, file-system delta, duration, and available usage/cost
   fields without persisting secrets or chain-of-thought.
7. Applies deterministic assertions first. When semantic judgment is necessary,
   a separate blind evaluator receives only the request, sanitized output,
   rubric, and allowed evidence—not the intended answer, suspected defect,
   creator rationale, or candidate/baseline identity.
8. Aggregates results without cherry-picking. Nonzero exits, timeouts, malformed
   output, unauthorized writes, missing evidence, routing collisions, contract
   failures, or required-case failures block the skill.

The harness must terminate subprocess groups on timeout, retain bounded logs,
clean temporary workspaces, and produce a diagnostic blocker rather than
silently weakening the test when Codex, a model, or authentication is
unavailable.

## Minimum behavioral matrix

Every new skill includes:

- representative explicit-use tasks that exercise its primary output;
- natural-language positive routing cases without copying the description;
- adjacent non-trigger and ambiguity cases;
- malformed, sparse, and conflicting inputs relevant to its contract;
- source, authority, and side-effect boundary cases when applicable;
- at least one real prospective consumer workflow and its typed handoff;
- near-transfer and farther-transfer cases required by the accepted reuse scope;
- a regression or coexistence case for the nearest catalog neighbors; and
- a paired baseline/candidate comparison demonstrating material benefit without
  losing valid baseline behavior.

Material updates use the same matrix against the accepted previous skill body.
Narrow editorial updates may emit a risk-justified no-op only when the change
cannot affect routing, instructions, resources, tools, outputs, or consumers.

## Acceptance and revision

The report records per-case and aggregate pass/fail/inconclusive status,
deterministic assertions, blind-evaluator rubric results, baseline/candidate
deltas, routing evidence, contract evidence, transfer-scope evidence,
unauthorized effects, infrastructure failures, residual risk, and immutable
artifact references.

A failed required case produces evidence for a bounded Codex `skill-creator`
revision. The planner never edits the skill body. After revision, affected cases
and all required regression/transfer cases rerun against the new digest. Catalog
promotion and planner closure require a passing current report or an explicit
blocked state; `inconclusive` is not treated as success.
