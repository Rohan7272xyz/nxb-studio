# Workflow design method

Use this method to turn a software outcome into an NXB fleet. The objective is useful separation of responsibility, not maximum pane count.

## 1. Decide whether a fleet helps

Use one current agent when all of these hold:

- one coherent artifact or tightly coupled edit;
- little benefit from an independent investigation;
- no meaningful parallel branches;
- verification is quick and objective;
- coordination would cost as much as the task.

Use a fleet when at least one holds:

- two or more independent investigations can run in parallel;
- separate components have clean file ownership;
- a difficult diagnosis benefits from competing hypotheses;
- a maker should be checked by an independent reviewer;
- provider diversity materially increases confidence;
- the work spans discovery, implementation, integration, and verification waves;
- a long-running task needs a coordinator to preserve the global outcome while workers focus locally.

Do not split work merely to assign every small step. Each worker should own a meaningful artifact or decision.

## 2. Write the dependency plan first

For each work unit record:

| Field | Required content |
|---|---|
| ID | Short stable label such as `A1` or `verify-api` |
| Owner | Exactly one Studio node |
| Depends on | IDs whose deliverables must exist first |
| Inputs | Paths, decisions, interfaces, or evidence |
| Action | Bounded work; include edit/read-only authority |
| Deliverable | File, patch, test result, decision memo, or report |
| Acceptance | Observable conditions for done |
| Handoff | Downstream owner and information it needs |

Group independent units into waves. A common coding workflow is:

```text
Wave 0: inspect and establish contract
      |
      +--> Wave 1A: component implementation
      +--> Wave 1B: independent component implementation
      +--> Wave 1C: tests/fixtures or competing diagnosis
                       |
Wave 2: integration and conflict resolution
                       |
Wave 3: independent review and end-to-end verification
```

The graph is written into the orchestrator's standing instructions and summarized in the final brief. Canvas coordinates can mirror it visually, but they do not enforce it.

## 3. Select a topology

### Human-routed independent panel

Use workers and no orchestrator when the operator wants to ask each pane directly or compare independent answers.

Good for:

- architecture opinions;
- two-provider fact checking;
- manual experiments;
- small independent reviews.

Avoid when outputs must feed one another or the operator does not want to coordinate each handoff.

### Orchestrated fan-out/fan-in

Use one orchestrator and two or more workers when independent branches can start together and later converge.

Typical roles:

- coordinator/integrator;
- one worker per component or hypothesis;
- independent verifier on the other runtime.

The orchestrator should dispatch Wave 1 concurrently, collect every result, resolve inconsistencies, then dispatch the verifier after integration.

### Maker/checker

Use one implementer and one independent checker, optionally under an orchestrator.

- Maker owns changes and primary tests.
- Checker is read-only at first, reproduces the issue or validates the diff, and reports precise findings.
- Maker receives a follow-up only for confirmed issues.
- Integration owner makes the final call and reruns acceptance tests.

Prefer different runtimes for the checker when independence matters. Two same-runtime samples can expose stochastic variance, but they are weaker evidence of independent provider agreement.

### Competing hypotheses

Use for ambiguous bugs or architecture decisions:

- give two workers the same facts and separate read-only investigation scopes;
- prohibit them from reading one another's conclusions until both report;
- have the orchestrator compare evidence, not vote counts;
- dispatch one implementation only after a hypothesis wins on reproducible evidence.

### Component owners

Use when components have clean file boundaries:

- one owner per component;
- an explicit interface contract established before parallel edits;
- separate worktrees/directories if branches edit concurrently;
- one integration owner handles shared manifests, lockfiles, generated artifacts, and final merge.

### Pipeline

Use sequential specialist roles only when each transformation produces a durable handoff. If the boundary is fuzzy, one capable worker will usually outperform a chain that repeatedly rehydrates context.

## 4. Prevent write collisions

Shared filesystem access is not isolation. Choose one:

- disjoint file ownership;
- separate git worktrees passed through each node's `working_directory`;
- read-only parallel investigation followed by a single writer;
- explicit serialized turns controlled by the orchestrator.

Name an integration owner for:

- package manifests and lockfiles;
- shared schemas and generated code;
- migrations;
- global formatting;
- cross-component tests;
- conflict resolution.

Workers must not reset, discard, or rewrite changes they do not own. Put that constraint in every editing role.

## 5. Assign models by bottleneck

Do not give every role the strongest model by reflex. Spend capability where errors propagate:

- Orchestrator: decomposition, sequencing, conflict judgment, and synthesis.
- Ambiguous investigator: root-cause reasoning and evidence gathering.
- Integrator: cross-component context and interface decisions.
- Verifier: adversarial reading, reproducibility, and coverage gaps.
- Bounded implementer: execution against a clear spec.
- Mechanical worker: transformations with deterministic checks.

See [model-evidence.md](model-evidence.md) for current facts. Typical inferences, not fixed rules:

- use Astra, Fable 5.1, Opus 5, or Sol for a genuine frontier bottleneck;
- use Terra or Sonnet 5 as strong default implementers;
- use Luna for repetitive, tightly specified work with machine-checkable output;
- use Haiku for fast, scoped work only when its smaller context and absent effort control fit;
- choose the verifier from a different runtime rather than simply duplicating the maker's model;
- start at high/default for hard coding, medium for bounded work, and low for simple subagent tasks; raise effort only where failure cost or local evals justify it.

An expensive orchestrator with cheap workers is sensible when coordination is the bottleneck. Cheap orchestration with one frontier specialist is sensible when the task graph is obvious but one branch is unusually hard.

## 6. Treat nested orchestration explicitly

NXB itself is a persistent multi-agent layer. Current clients also expose provider-native orchestration:

- Claude Code `ultracode`: `xhigh` model effort plus dynamic workflows.
- Codex `ultra`: maximum reasoning with automatic task delegation.

Do not enable these silently inside NXB nodes. Nested delegation can:

- multiply effective agents beyond the visible Studio roster;
- increase quota/cost unpredictably;
- create simultaneous writes that NXB's visible plan did not allocate;
- weaken worker-level attribution;
- duplicate the orchestrator's job.

Consider nesting only for a single isolated node whose internal work is safely parallel, whose files are isolated, and whose client capability was confirmed. Record the inner concurrency assumption and budget. Otherwise model parallelism directly as visible NXB workers.

## 7. Write roles that survive dispatch

### Worker instruction template

```text
MISSION
Own <bounded result> for the overall <project outcome>.

SCOPE AND OWNERSHIP
You may read <paths>. You may edit only <paths>, or you are read-only.
Preserve all unrelated and pre-existing changes. Do not reset or discard them.

INPUTS
Inspect <paths/contracts/tests>. Treat <decision> as fixed. State any blocking
contradiction before editing.

DELIVERABLE
Produce <artifact/report> at <location or in final response>. Include a concise
change/evidence summary and exact verification results.

ACCEPTANCE AND VERIFICATION
- <observable criterion>
- <command/check>
- <edge case>
Report failures and uncertainty; do not claim a check you did not run.

HANDOFF
Tell <integration owner> what changed, interfaces affected, remaining risks,
and any follow-up needed.

NON-GOALS
No unrelated refactors, dependency upgrades, global formatting, or speculative
features.
```

### Orchestrator instruction template

```text
MISSION
Coordinate the fixed NXB roster to deliver <outcome>. Do not substitute for a
missing worker; escalate to the operator.

EXECUTION PLAN
Wave 0: <contract/discovery work>.
Wave 1 in parallel: <worker -> unit/deliverable>.
Wave 2 after required inputs: <integration owner -> integration>.
Wave 3: <independent verifier -> acceptance suite/review>.

ASSIGNMENT POLICY
Dispatch only to the named role that owns the work. Every directive must include
all paths, preconditions, edit authority, deliverables, acceptance criteria, and
handoff requirements. Preserve file ownership and serialize shared files.

CONVERGENCE
Collect every required report. Treat WAITING as incomplete. Reconcile conflicts
using reproduced evidence. Attribute each claim to its worker. When verification
is requested, use different runtimes and report agreement or disagreement.

DONE GATE
Do not declare completion until <tests/artifacts/review> pass and the integration
owner has accounted for every worker's changes. State skipped checks and risks.

OPERATOR ESCALATION
Ask before expanding scope, adding a worker, destructive actions, launching an
external deployment, spending materially more quota, or resolving <named product
decision> without guidance.
```

NXB already injects the authoritative task-ID and dispatch commands. Avoid pasting a second protocol that could drift.

## 8. Pick names and canvas layout

Use names that identify responsibility, not provider alone:

- `Coordinator`
- `API Builder`
- `UI Builder`
- `Migration Owner`
- `Regression Reviewer`
- `Integration Tester`

Names must be unique and contain no quotes or backslashes. The live name will be `<session> <name>`.

Suggested visual positions:

- orchestrator centered near `y=60`;
- Wave 1 workers across `y=300`;
- late-stage verifier to the right or at `y=540` if the canvas is large.

Choose tmux layout independently:

- `main-horizontal`: one large top/bottom emphasis; useful for an orchestrator plus workers.
- `main-vertical`: one large side pane; useful when the main pane needs width.
- `tiled`: equal visibility for a peer panel.
- `even-horizontal` / `even-vertical`: equal strips for a small homogeneous set.

These are tmux display choices, not workflow semantics.

## 9. Review a proposed workflow

Score it against these questions:

1. Is a fleet genuinely better than one agent?
2. Does every worker own a distinct deliverable?
3. Are all dependencies and waves explicit in text?
4. Can any two workers edit the same file at the same time?
5. Is there exactly one integration owner?
6. Is expensive capability placed on the real bottleneck?
7. Is verification independent enough for the failure cost?
8. Are model/effort claims supported and current?
9. Can the orchestrator execute the plan using only its fixed roster?
10. Is the canonical draft structurally valid and explicitly unlaunched?

If the answer to 1 or 2 is no, reduce the fleet. If 3–5 are no, repair the execution plan before changing models. If 6–8 are no, revise routing. If 9–10 are no, do not save.

## 10. Operator handoff

After saving, give the operator a short first prompt for the orchestrator. It should name the final outcome and tell the orchestrator to follow its standing execution plan, for example:

```text
Run the planned workflow for <outcome>. First inspect the current repository
state, then dispatch Wave 0. Preserve existing changes, enforce the stated file
ownership, and stop for me only on the escalation conditions in your role.
```

Do not include task IDs; the orchestrator mints them. Do not say agents are working until the operator has actually brought the rig to life and sent this prompt.
