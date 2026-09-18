---
name: nxb-studio-workflow-builder
description: Architect, validate, and optionally save evidence-based NXB Studio coding workflows for Claude Code and Codex. Use when the user asks to design, build, revise, compare, or optimize an NXB/Nexus/XB/NXP Studio fleet, choose agents, models, or efforts for that fleet, write its node instructions, or turn a software goal into a Studio draft.
---

# NXB Studio Workflow Builder

Build the smallest NXB Studio fleet that can complete and verify the user's goal. Base model claims on current primary evidence, make the orchestration executable in NXB, and never pretend that a benchmark guarantees a result.

Normalize “Nexus Studio,” “XB Studio,” and “NXP Studio” to **NXB Studio** unless the user explicitly distinguishes another product.

## Required references

Read these before producing a workflow:

1. [studio-contract.md](references/studio-contract.md) for the exact product and draft contract.
2. [workflow-design.md](references/workflow-design.md) for decomposition, topology, roles, prompts, and output requirements.
3. [model-evidence.md](references/model-evidence.md) whenever selecting, comparing, or explaining models or effort levels.

The references are a dated evidence snapshot, not timeless truth. Follow their refresh policy when model choice matters.

## Non-negotiable rules

- Studio architects and stands up a tmux fleet. It is not a DAG executor. Canvas positions and visual connections do not schedule work.
- The orchestrator and its NXB `mint -> send -> collect` protocol perform runtime sequencing. `WAITING` is not an answer.
- Prefer the smallest useful fleet. A model with internal subagents nested inside an NXB fleet can multiply cost, contention, and attribution ambiguity.
- Treat local CLI recognition, account entitlement, and public model availability as three different facts.
- Attach model ID, effort/mode, benchmark version, harness, tools, date, and source to every numerical benchmark claim. An absent number is “not published,” never zero.
- Do not compare different benchmark versions as if they are one scale. In particular, keep Terminal-Bench 2.0, 2.1, 4.0, and Terminal-Bench-Science separate.
- Separate facts from recommendations. Label any recommendation derived from benchmark evidence as an inference.
- Never launch, rebuild, tear down, or delete a rig unless the user explicitly asks for that state change. Stand-up launches unsandboxed agents, consumes quota, and rebuild destroys live context.
- A request to “build/create the workflow” authorizes saving a non-running Studio draft when the draft tools exist. It does not authorize “Bring it to life.” A request to advise, review, or plan is read-only.
- A request to build, create, or save a workflow also authorizes creating the exact, narrowly scoped **local** `working_directory` paths that the workflow builder deliberately authors into that draft when they are missing. Resolve the path before creation and report what was created. This does not authorize creating remote-host directories, cloning or initializing a repository, adding files, installing software, changing permissions, or launching the rig. Never auto-create a filesystem root, home directory, workspace root, unresolved variable/glob, or ambiguous path; choose a safe project directory or ask the user instead.
- Never run `python3 -m nxb doctor --deep` without an explicit ask; it boots runtimes and can consume a Claude turn. The ordinary doctor is read-only enough for this workflow.
- Preserve user changes. When editing a durable draft, read the latest revision and use compare-and-swap; do not overwrite a revision you did not read.

## Operating procedure

### 1. Establish the design context

Capture, or infer conservatively:

- desired outcome and definition of done;
- repository/root directory and relevant artifacts;
- task shape: implementation, debugging, migration, review, research, testing, or mixed;
- the project's **quality priority score** from 1–5 and the evidence behind it;
- constraints: time, provider-specific quota/headroom and reset horizon, provider diversity, security, file ownership, and whether agents may edit;
- desired operator involvement: manual dispatch, orchestrated fleet, or independent opinions;
- whether the user wants a proposal only or a saved Studio draft.

Inspect the target repository and its agent instructions when available. Never silently assume a balanced quality/cost preference. If the score is missing and model or effort routing would materially change, ask one concise question before saving; for a proposal, state a provisional score and its basis. Ask another question only if a missing choice would materially change topology or permission. Otherwise state assumptions and proceed.

### 2. Read the live NXB vocabulary

If the connected NXB MCP exposes Studio tools:

1. Call `nxb_studio_catalog` before composing. Treat its model list as suggestions, not entitlement proof.
2. When revising a draft, call `nxb_studio_draft_list`, identify the target, then call `nxb_studio_draft_get`. Retain `draft_id`, `revision`, the canvas `view`, and each retained agent's stable `node_id`, `x`, and `y` unless the user asked to move it.
3. Prefer `nxb_studio_draft_validate` for a non-mutating contract check.

Reuse a returned saved persona when its standing role genuinely matches a node; do not edit or delete persona files as part of workflow design.

If those tools are absent, use the local fallback checks in [studio-contract.md](references/studio-contract.md). Do not confuse the one-shot `nxb_dispatch` MCP tool with Studio's persistent tmux fleet.

### 3. Turn the goal into an execution graph

Write the work as waves and dependencies before choosing models:

- give every unit one owner, concrete inputs, a deliverable, acceptance criteria, and a handoff target;
- parallelize only independent work;
- serialize shared-file edits or give agents separate worktrees/directories;
- name one integration owner for multi-writer work;
- add an independent verification step for high-impact or uncertain changes;
- use a different runtime for strong cross-vendor verification when possible.

The execution graph belongs in orchestrator instructions and the workflow brief. Do not encode it only as canvas geometry.

### 4. Choose the topology

Use [workflow-design.md](references/workflow-design.md). Default to:

- no fleet for an atomic task a single current session can do well;
- workers without an orchestrator for a human-driven comparison or a fixed set of independent tasks;
- one orchestrator plus workers for dependencies, retries, integration, or multi-wave work;
- a maker/checker pair for correctness-sensitive changes;
- cross-runtime duplicate analysis only when disagreement is valuable enough to justify the extra run.

Every added pane must have a distinct responsibility. Never add agents merely because capacity exists.

### 5. Select models and effort

Use the routing method and dated evidence in [model-evidence.md](references/model-evidence.md):

1. Identify the job's dominant need: frontier reasoning, long-horizon coding, routine implementation, mechanical transformation, review, or orchestration.
2. Establish and report the quality priority score below.
3. Filter by current local capability and likely entitlement.
4. Spend capability according to the score and provider-specific headroom. Do not average asymmetric provider quotas into uniformly weaker choices.
5. Prefer an effort sweep on representative local tasks over a universal claim. Effort labels are not calibrated equivalently across model families, and the highest label is not automatically the highest-quality choice for every task.
6. State the evidence, quota assumptions, routing consequences, and uncertainty behind each choice.

#### Quality priority score

Every workflow that selects models or efforts must carry one explicit project-level score:

| Score | Controlling preference | Default routing consequence |
| --- | --- | --- |
| **1/5** | Cost and quota conservation dominate; lowest acceptable quality | Use the least expensive capable models and the lowest effort proven adequate by checks. Reserve premium capability for an unavoidable blocker. |
| **2/5** | Cost-sensitive | Use efficient models by default and premium models only for a small number of high-risk bottlenecks. |
| **3/5** | Balanced | Use provider defaults or balanced efforts, raising capability for orchestration, ambiguity, integration, and verification. |
| **4/5** | Quality-first, constrained by a real quota or availability bottleneck | Use the strongest appropriate models and higher efforts on critical roles. Exploit the provider with ample headroom and reserve a constrained provider for work where its model or cross-vendor perspective adds distinct value. |
| **5/5** | Maximum quality; cost optimization is subordinate to capability | Use frontier models and the highest appropriate validated single-agent efforts on all critical roles. Do not downgrade primarily for price or speed. Nested delegation still requires explicit justification. |

Treat **5/5 as the user's standing desired ceiling** unless they explicitly say otherwise; do not economize below it merely because they did not volunteer a budget. Current usage, reset timing, entitlement, or availability can inhibit that ceiling. The effective score is the user's desired quality after those real constraints are applied. Record:

- the score and a one-sentence interpretation;
- the user's quality intent and consequence of failure;
- available headroom for each provider, expressed using fresh user- or Studio-supplied facts when available;
- reset timing or other time sensitivity;
- which provider is the bottleneck and how that changes individual node assignments.

Canonical operator example: when quality is strongly preferred, Codex has **60% remaining on a 20× Max allowance that resets in two days**, and Claude is **80% used**, rate the project **4/5** because Claude is the bottleneck. That does not justify lowering every node to a balanced tier: spend Codex capability aggressively and allocate Claude only where it contributes unique implementation or independent-verification value.

If the user supplies the score, treat it as controlling. If the user supplies the factors but not the number, state the inferred score and derivation rather than hiding the judgment. Never downgrade models or effort for quota savings without identifying the downgrade and connecting it to the recorded score. If quota conditions materially change during a long-running project, re-rate transparently instead of silently changing the fleet.

The score controls quality-versus-cost routing; it never relaxes safety, authorization, verification, or completion gates. “Highest appropriate effort” means the provider-recommended setting most likely to improve this workload, not blindly selecting `max` when current evidence shows diminishing returns, overthinking, or a nested orchestration mode.

If plan headroom is a constraint, use a fresh value the operator or Studio already provides. Do not translate API list prices into subscription usage, and do not trigger Claude's quota probe without an explicit ask because that probe costs a turn.

Special handling:

- Claude Code `ultracode` is a CLI orchestration mode that sends `xhigh` to the model; it is not a sixth Anthropic API effort.
- Codex `ultra` is multi-agent orchestration, not an API reasoning-effort value. `max` is the deepest single-agent setting.
- Because NXB is already an orchestration layer, default to ordinary model efforts. Use nested `ultracode`/`ultra` only when the user explicitly wants nested delegation, the installed client supports it, and the benefit outweighs attribution and quota costs.
- Haiku 4.5 has no effort control. Omit `effort`; never relabel a fixed thinking-token benchmark as low/high/max.
- If an effort/model combination is not exposed by the current catalog, validate capability before saving it. Do not trust a stale hardcoded picker.

### 6. Write self-contained node instructions

For every node, use this compact contract:

```text
MISSION
The outcome this role owns.

SCOPE AND OWNERSHIP
Files, systems, decisions, and whether this role may edit.

INPUTS
Paths, upstream artifacts, constraints, and assumptions it must inspect.

DELIVERABLE
The exact artifact or report and where it goes.

ACCEPTANCE AND VERIFICATION
Tests, checks, evidence, and failure reporting required before done.

HANDOFF
What the orchestrator or named downstream role needs.

NON-GOALS
Work explicitly outside scope; forbid unrelated refactors when appropriate.
```

Startup instructions establish a standing role; the orchestrator's dispatched directive must still include all task-specific paths, preconditions, and acceptance criteria because workers cannot see the operator conversation.

For orchestrators, include the waves, assignment policy, integration owner, verification gates, and what requires operator escalation. Do not copy the low-level NXB protocol commands into the custom instructions; NXB injects its authoritative protocol brief.

Also include the project quality priority score, the dated provider-headroom snapshot used for routing, and the rule for escalating when a constrained provider would force a material quality downgrade. Do not let workers reinterpret the score independently.

For Codex nodes, repeat critical constraints in each dispatched task because custom startup instructions are typed conversationally after launch. Claude's role is launch-bound via `--append-system-prompt`, but task directives must still be self-contained.

### 7. Validate and, when requested, save

Build a complete canonical draft using the schema in [studio-contract.md](references/studio-contract.md).

Before validation or save, materialize every missing local rig or per-agent `working_directory` that you deliberately selected for the workflow:

- Resolve it to an absolute, narrow path with no unresolved variables or globs, and confirm it is not a filesystem root, the user's home directory, or a broad workspace root.
- If it does not exist, create that exact directory, including necessary parent directories, then verify it is a directory. A build/create/save request supplies the authorization for this local directory creation.
- Do not create a directory merely because it appears in an existing draft being reviewed. Create it when you author or retain it as part of a requested build, create, save, or update operation.
- Do not treat an SSH destination, Windows path on another host, URI, or intended mount as a local path. Remote directory creation needs separate explicit authorization.
- If safe creation fails, do not save a knowingly unlaunchable draft; report the failure and the exact path.

- With NXB Studio MCP: call `nxb_studio_draft_validate`. If the user asked to create/build/save the workflow, call `nxb_studio_draft_save` only after validation. For an update, pass the latest `draft_id`, pass its `revision` as `expected_revision`, preserve `view`, and preserve each retained agent's `node_id` and position. Omit `node_id` only for a genuinely new node; omit storage fields such as timestamps and `schema_version`.
- Without the draft tools: write the JSON to a user-approved location if requested, then run `python3 scripts/validate_draft.py <path>` from this skill directory. Otherwise validate via stdin and return the canonical JSON.
- Surface directory warnings and model/account uncertainty. Say **structurally valid; model compatibility and account access not live-verified** unless a separate, non-destructive current probe established them.
- Resolve every known-incompatible or unknown model/effort warning before saving, either by choosing a supported value or by recording fresh live capability evidence. Nested Ultra/Ultracode warnings require explicit user intent. A missing-local-directory warning must not remain for a path the workflow builder authored: create it safely and revalidate before saving.
- Never call a launch endpoint as a validation technique.

## Final response contract

Lead with the recommended fleet and why. Include:

1. **Workflow summary** — outcome, assumptions, topology, and total panes.
2. **Execution plan** — waves/dependencies and integration/verification owner.
3. **Studio nodes** — name, role, runtime, exact model or alias, effort/mode, directory, and concise responsibility.
4. **Quality priority and model rationale** — the explicit 1–5 score, provider-headroom/reset snapshot, bottleneck, routing consequences, factual evidence, inference, limitations, and source links near numerical claims.
5. **Validation/save state** — valid or not, warnings, draft ID/revision if saved, and the explicit statement `launched: false` unless a separately authorized launch actually occurred.
6. **Operator handoff** — what to review in Studio and the first prompt to give the orchestrator in tmux.

When useful, include the canonical draft JSON. Do not swamp the answer with the entire benchmark catalog; quote only the rows that changed the design and point to the dated evidence reference for the rest.

## Quality gate

Before finishing, confirm:

- every worker has unique, non-overlapping value;
- dependencies exist in text, not just geometry;
- file-write collisions are prevented;
- every model/effort is currently plausible and any access gap is disclosed;
- an explicit quality priority score and provider-specific headroom explain every material cost/capability tradeoff;
- no model or effort was silently downgraded for cost, latency, or quota;
- every deliberately authored local working directory exists and is a directory;
- numerical claims retain benchmark versions and sources;
- the draft passes NXB validation;
- saved does not mean launched;
- the user knows the next concrete action.
