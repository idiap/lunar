<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Codex skill-creator context control

## Boundary

The planner is not a skill author, skill initializer, or alternative skill-
creation framework. It never writes or revises canonical `SKILL.md` bodies,
chooses their final internal layout, recreates `init_skill.py`, copies the
system skill-creator instructions, or substitutes its own validator for
`quick_validate.py`.

Codex `skill-creator` remains the sole authoring owner for a new or materially
revised skill. The planner owns the work immediately around that authoring
step: deciding whether a skill change is necessary, enriching and bounding the
context, obtaining acceptance, invoking the platform-owned creator, validating
the returned repository change, and routing observed failures back for a
focused creator revision.

If the system `skill-creator` is unavailable or its contract cannot be
validated, a skill-change TODO blocks. The planner must not fall back to
writing a skill itself.

## Division of responsibility

| Planner owns | Codex `skill-creator` owns |
| --- | --- |
| Verbatim user intent, use cases, desired outcome, and non-goals | Final skill name and discriminating frontmatter, within accepted naming constraints |
| Actual-body reuse, sufficiency, novelty, and monotonic-extension evidence | Creating or updating the skill folder and `SKILL.md` |
| Target repository, candidate canonical location, allowed change set, authority, and protected unrelated files | Choosing the smallest useful skill structure |
| Existing contract and consumers for an update | Preserving supported metadata and invocation policy |
| Trigger/non-trigger evidence, input/output handoffs, domain constraints, source policy, and claim boundaries | Writing concise, decision-changing instructions with progressive disclosure |
| Candidate scripts, references, or assets and why each may be useful | Deciding which justified resources to create, reuse, update, or omit |
| Acceptance criteria, realistic requests, negative routes, regression obligations, and observable tests | Running the bundled initializer when appropriate, validating the skill, and testing added scripts |
| Post-authoring catalog registration, hooks, workflow integration, derived surfaces, consumer canaries, and closure | Returning changed files, validation evidence, assumptions, and unresolved issues |

Planner context is advisory where authoring judgment belongs to
`skill-creator`. A proposed name, file split, or resource is not a mandatory
template unless the accepted plan identifies a real compatibility or safety
invariant requiring it.

## Skill-creator context packet

`skill-creator-context-packet.json` is an immutable, versioned handoff. It
contains only information that should materially change authoring decisions:

- `request_text`, user facts, desired observable outcome, representative
  requests, counterexamples, non-goals, explicit user choices, and separate
  hard invariants versus optional preferences;
- accepted user-need, problem-frame, outcome-contract, selected-alternative,
  and problem-to-plan-trace IDs/digests so the creator receives the need without
  inheriting unsupported architectural conjectures;
- accepted skill-reuse-design assessment and its declared reuse-scope tier,
  invariant responsibility, variation axes, prospective consumers, exclusions,
  portability constraints, and transfer fixtures;
- `change_mode`: `create`, `update`, or `no_skill_change`;
- target environment, repository, candidate canonical directory, invocation
  policy requested by the user, authority envelope, and allowed/protected
  paths;
- candidate skill identity and one-responsibility/one-primary-output boundary;
- exact local skill bodies and workflows reviewed, reuse classes,
  insufficiency/novelty evidence, and why a monotonic update or new skill is
  justified;
- current skill body, resources, callers, metadata, invocation policy, and
  preserved contracts when the mode is `update`;
- domain terminology, schemas, source and representation contracts, evidence
  and claim ceilings, dependency/platform facts, and security/privacy rules;
- candidate scripts, references, assets, and UI metadata with a concrete need
  for each, plus items explicitly rejected as generic, duplicate, or
  speculative;
- acceptance criteria, realistic forward-test prompts, negative routing
  fixtures, deterministic checks, relevant consumer canaries, required
  generated-surface updates, and a risk/authority decision on whether an
  independent forward-test agent is warranted;
- a versioned Codex exec generative-test manifest with paired baseline/candidate
  cases, structured output schemas, deterministic assertions, blind semantic
  rubrics when needed, isolation/authority limits, and bounded cost/timeout;
- packet/schema version, source snapshot and skill-creator contract digests,
  provenance anchors, assumptions, missing inputs, and blockers.

The packet does not contain a prewritten `SKILL.md`, a mandated heading list,
generic Codex advice, copied upstream manuals, or permission beyond the accepted
authority envelope. Large domain references are passed as exact paths or
sanitized handles and are read only when relevant.

## Controlled authoring handoff

1. Reuse, sufficiency, novelty, and gap stages classify the requested change.
   `no_skill_change` continues through ordinary workflow implementation.
2. A deterministic `SkillCreatorContextAssembler` joins accepted planning
   artifacts without adding new semantic decisions. `artifact-contract-
   validator` rejects missing, stale, contradictory, over-prescriptive, or
   authority-expanding packets.
3. The operator accepts the plan digest, skill-change mode, target paths,
   context packet digest, tests, and rollback scope.
4. `CodexSkillCreatorAdapter` invokes the installed `skill-creator` with the
   context packet and exact target location. The adapter supplies no hidden
   authoring instructions and never interprets a failed invocation as
   permission to edit the skill itself.
5. `skill-creator` creates or updates the skill and returns
   `skill-creator-result.json`: changed files, resource decisions, validation
   commands/results, test results, assumptions, deviations, and unresolved
   issues.
6. A deterministic `CodexExecSkillGenerativeTestRunner` validates the returned
   digest with the accepted manifest in a temporary isolated workspace. It
   cannot repair the skill or broaden prompts, tools, data, network, paths, or
   budget.
7. The planner validates path scope, frontmatter/name rules, requested versus
   delivered behavior, preserved contracts, consumer canaries, routes, hooks,
   generated catalog parity, and realistic forward tests. Creator success is
   necessary but not sufficient for repository promotion.
   Complex or risky skills receive an isolated independent forward test only
   when delegation is available and authorized; ordinary changes do not gain an
   automatic subagent requirement.
8. A failed review or required generative case produces a bounded
   `skill-creator-revision-packet.json`
   containing observed behavior and evidence. Revision is handed back to
   `skill-creator`; the planner does not patch the skill. Repeated failure uses
   the normal bounded-refinement stop rule.

## Update versus creation

For an existing skill, the context packet includes the complete current skill
and relevant resources, supported callers, baseline route fixtures, output
contract, and monotonicity findings. `skill-creator` chooses the narrowest
authoring change consistent with those preserved contracts. Breaking changes
require an explicit migration or a separate skill decision before invocation.

For a new skill, the packet must prove that direct reuse, composed reuse, and a
coherent monotonic extension were rejected. Keyword or catalog search failure
is insufficient. The creator receives realistic tasks and discriminating
boundaries, not a fully authored substitute skill.

The planner also identifies the broadest evidence-supported reuse boundary
before authoring. Codex `skill-creator` retains authoring judgment, but the
packet distinguishes intrinsic constraints from details incidental to the
originating workflow. It supplies near-transfer, farther-transfer when claimed,
negative-routing, and specialization fixtures. “Universal” is not accepted as
a property without transfer evidence, and generalization must not merge
independently triggered responsibilities into one skill.

## Platform contract and availability

The planner records the resolved `skill-creator/SKILL.md` path, content digest,
supported initializer and validator paths, and target environment. This is a
platform dependency record, not a copied catalog entry. A contract change
invalidates unexecuted handoffs for review; it does not cause the planner to
vendor the system skill.

Default automatic invocation policy is preserved. An explicit-only policy is
requested only when the user explicitly asks for it. The planner never infers
explicit-only invocation from sensitivity or approval requirements.

## Closure gates

A skill-changing iteration cannot close unless:

- the accepted context packet and creator result digests match the invocation;
- all changed skill files were authored through `skill-creator` and remain
  inside the accepted path scope;
- bundled validation and any added scripts pass, or failures are explicit
  blockers;
- the current skill digest has a passing Codex exec generative report covering
  required positive, non-trigger, ambiguity, transfer, contract, paired
  baseline/candidate, and consumer-regression cases;
- descriptions are discriminating, instructions preserve user intent,
  references are selectively discoverable, and no unjustified scaffolding or
  duplicated guidance was added;
- positive, negative, ambiguity, and consumer-regression fixtures pass;
- the declared reuse scope, variation axes, exclusions, prospective consumers,
  transfer fixtures, and catalog metadata agree with observed behavior;
- monotonicity, catalog registration, workflow hooks, help, documentation, and
  visibility-parity gates pass; and
- residual risks, deferred work, or creator deviations are recorded.
