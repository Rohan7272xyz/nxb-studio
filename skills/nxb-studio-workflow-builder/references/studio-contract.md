# NXB Studio contract

Evidence snapshot: 2026-09-04, local repository `/Users/rohan/dev/nexus-bridge`, baseline commit `954d0df8b5bc` plus an explicitly identified in-progress durable-draft/MCP change.

Use executable code and live capability probes as the authority when they disagree with old prose or JSON contracts. The legacy `/Users/rohan/NEXUS PROTOCOL.md` is not the current Studio contract.

## Product boundary

NXB Studio is a local visual composer for persistent Claude Code and Codex panes in tmux.

```text
Studio draft
  -> validated fleet composition
  -> operator chooses Bring it to life
  -> unsandboxed Claude/Codex processes in tmux
  -> operator talks to orchestrator in tmux
  -> orchestrator uses NXB mint -> send -> collect with fixed workers
```

Studio controls:

- tmux session name;
- default working directory;
- tmux layout;
- one node per agent;
- node name, worker/orchestrator role, runtime, model, effort/mode, optional per-agent directory, and standing instructions;
- canvas position for comprehension only.

Studio does not:

- execute a DAG;
- give edges or positions dependency semantics;
- dispatch or collect work from the browser;
- dynamically add workers to a live rig;
- prove model/account access during structural validation;
- preserve live model context when a rig is rebuilt.

The authoritative implementation areas are:

- `nxb/studio.py`: local server, catalog, state, and launch endpoint;
- `nxb/studio.html`: canvas, Inspector, draft shape, and launch request;
- `nxb/rig.py`: fleet validation, CLI flags, tmux stand-up, and scoped names;
- `nxb/enroll.py`: worker and orchestrator standing rules;
- `nxb/keystroke.py`: rig records and collection states;
- `nxb/usage.py`: heuristic model discovery and usage parsing;
- `docs/OPERATOR-NOTE-nxb.md`: current operator intent, subject to code verification.

## Live environment check

Prefer the connected `nxb_studio_catalog` tool when available. It is read-only and returns the local runtimes, model suggestions, effort suggestions, layouts, and personas.

Fallback from a terminal:

```bash
cd /Users/rohan/dev/nexus-bridge
python3 -m nxb doctor
```

For the baseline model suggestions, configured defaults, and saved personas, use this read-only dump when the MCP catalog tool is absent:

```bash
PYTHONPATH=/Users/rohan/dev/nexus-bridge python3 - <<'PY'
import json
from nxb.studio import Studio
s = Studio("/Users/rohan/.nxb/ledger.db")
print(json.dumps({"runtimes": s.models(), "personas": s.personas()["personas"]}, indent=2))
PY
```

The dump still inherits NXB's heuristic model discovery. It is more complete than doctor output, but it remains a suggestion catalog rather than entitlement proof. Use the layout and role enums below when the older Studio has no structured catalog endpoint.

Do not append `--deep` unless the user explicitly asks. Deep doctor boots throwaway runtimes and may consume a Claude `/usage` turn.

At the snapshot date, the local versions were:

- Claude Code `2.1.260`;
- Codex CLI `0.153.2`;
- tmux `3.7c`.

Configured defaults were Claude `opus[1m]`/`xhigh` and Codex `gpt-5.6-sol`/`xhigh`. These defaults are local facts, not universal recommendations.

## Canonical durable draft

Recent local work adds durable Studio drafts and MCP tools. Capability-detect this surface because it was uncommitted when this snapshot was written. When the tools are present, this is the public model-facing schema:

```json
{
  "session": "atlas",
  "working_directory": "/absolute/project/path",
  "layout": "main-horizontal",
  "view": {"zoom": 1, "x": 0, "y": 0},
  "agents": [
    {
      "name": "Coordinator",
      "role": "orchestrator",
      "runtime": "codex",
      "model": "gpt-5.6-sol",
      "effort": "high",
      "working_directory": "/optional/agent/path",
      "instructions": "Standing role instructions",
      "x": 310,
      "y": 60
    },
    {
      "name": "API Builder",
      "role": "worker",
      "runtime": "claude_code",
      "model": "sonnet",
      "effort": "high",
      "instructions": "Standing role instructions",
      "x": 60,
      "y": 300
    }
  ]
}
```

Required top-level fields for model-authored drafts: `session`, `working_directory`, and nonempty `agents`. `layout` defaults to `main-horizontal`; `view` is optional on create and must be preserved from `get` on update unless the user explicitly changes the viewport.

Required agent fields: `name`, `role`, and `runtime`. All other fields are optional and should be omitted rather than filled with empty strings. On create, omit `node_id`; on update, preserve the positive integer `node_id` returned for every retained node and omit it only for new nodes.

Valid layouts:

- `main-horizontal`
- `main-vertical`
- `tiled`
- `even-horizontal`
- `even-vertical`

Valid roles are `worker` and `orchestrator`. Valid canonical runtimes are `claude_code` and `codex`.

The persistence layer adds server-owned fields such as `schema_version`, `draft_id`, `revision`, and timestamps. It generates view defaults and a stable positive `node_id` for each node. Do not invent identifiers when creating a draft. When updating, read the current record, pass its `draft_id` and `revision` as the tool's `expected_revision`, preserve `view`, `x`, `y`, and retained `node_id` values, and omit the storage-only fields. Losing node IDs changes canvas identity even if human-readable names stay the same.

Draft operations, when exposed:

- `nxb_studio_catalog`: read current design vocabulary; never launches.
- `nxb_studio_draft_list`: list summaries.
- `nxb_studio_draft_get`: read a complete draft and revision.
- `nxb_studio_draft_validate`: strict, read-only validation and directory warnings.
- `nxb_studio_draft_save`: create or compare-and-swap a complete draft; never launches.
- `nxb_studio_draft_delete`: only on explicit discard request; revision checked and moved to recoverable trash.

An open Studio window polls durable drafts. A saved MCP draft should appear on refresh/poll. Concurrent updates are revision-checked so a stale model cannot silently overwrite a newer human edit.

## Launch payload

The browser's `POST /api/rig/up` body uses older short directory keys:

```json
{
  "session": "atlas",
  "dir": "/absolute/project/path",
  "layout": "main-horizontal",
  "agents": [
    {
      "name": "Coordinator",
      "role": "orchestrator",
      "runtime": "codex",
      "model": "gpt-5.6-sol",
      "effort": "high",
      "dir": null,
      "instructions": "Standing role instructions"
    }
  ]
}
```

This launch payload is not the preferred authored-draft format. Generate it only for preview, debugging, or explicit API work. Never POST it merely to validate a workflow.

## Structural invariants

The launcher enforces:

- at least one agent;
- a recognized runtime;
- a nonempty name after whitespace normalization;
- unique names within the fleet;
- no single quote, double quote, or backslash in agent names;
- at most one exact `orchestrator` role.

The Studio server also requires:

- a session name with none of: spaces, tabs, colon, dot, dollar sign, quotes, or backslash;
- an existing rig working directory at launch time.

The durable-draft validator additionally enforces the exact role enum, layout enum, finite positions, and runtime enum. Missing directories are warnings during draft validation because they may be created before launch.

When the workflow builder deliberately authors a missing local rig or per-agent `working_directory` as part of a build, create, save, or update request, that request authorizes creating the exact narrow directory before final validation and save. Resolve it to an absolute path, reject roots, home directories, broad workspace roots, unresolved variables/globs, and ambiguous targets, then verify the result is a directory. This authorization does not extend to remote-host paths, repository initialization, files, installs, permission changes, or launch. Merely reading or reviewing an existing draft does not authorize materializing its paths.

Important launcher gaps in the baseline code:

- an orchestrator-only fleet is structurally accepted even though it cannot dispatch to a worker;
- unknown roles historically fell back to worker unless the durable validator was used;
- model and effort values pass through without model-specific validation;
- per-agent directories are not fully prevalidated by baseline composition;
- the baseline backend trusts the supplied layout more than the UI does.

Design above these gaps: use exact enums, include at least one worker for an orchestrated fleet, check directories, and capability-check model/effort combinations.

## Runtime launch and role binding

Every node launches as an unsandboxed/yolo runtime by the operator's design. Stand-up starts runtimes concurrently, waits for readiness markers, names and enrolls panes, applies custom instructions, then writes a rig record. `READY` confirms pane startup/enrollment; it is not proof that the selected model accepted a request. A model can still return an account or HTTP error after `READY`.

Role binding differs:

- Claude receives name and NXB standing rules at launch through `-n` and `--append-system-prompt`; custom role instructions are launch-bound too.
- Codex launches first, is renamed with `/rename`, then receives standing rules and custom instructions as operator messages because Codex has no equivalent append-system-prompt flag.

Therefore repeat safety-critical boundaries and acceptance criteria in each Codex task directive. Do not rely solely on its startup role through a long session.

Per-agent directories fall back to the rig directory. Use separate directories or worktrees for concurrent writers. Canvas placement does not isolate files.

The tmux pane is scoped as `<session> <node name>`, for example `atlas API Builder`. The orchestrator must use exact scoped names from its live worker listing.

## Orchestrator protocol

NXB injects the protocol automatically. Custom instructions should specify the work, not duplicate these mechanics.

The orchestrator:

1. lists its fixed roster;
2. mints a fresh task ID for one exact worker;
3. sends one self-contained marked directive;
4. collects the correlated report;
5. treats `WAITING` as incomplete and collects again;
6. attributes reports to the worker that produced them;
7. dispatches verification to different runtimes when cross-vendor assurance was requested;
8. asks the operator if the required worker does not exist rather than silently substituting or doing the task itself.

A worker cannot see the operator's conversation. Each directive needs all paths, preconditions, required artifacts, non-goals, and acceptance criteria.

Do not prescribe `nxb_dispatch` for controlling Studio panes. That MCP tool creates a fresh one-shot child and uses a different receipt/outbox path.

## Baseline browser-draft fallback

Before durable drafts, browser designs lived only in `localStorage["nxb.studio.v2"]` using short keys (`name`, `dir`, `nodes`). A browser-local draft was not externally writable or reliably recoverable by another LLM session.

If durable draft tools are absent:

- return the canonical JSON and a Studio entry table;
- optionally write it to a user-approved file and validate with this skill's script;
- tell the user it has not been imported or launched;
- do not attempt to mutate Safari localStorage from a shell.

Do not treat a reopened live rig as a lossless source in the baseline implementation. Rig records omit layout, directories, instructions, and positions, and the baseline state API can omit model/effort. Preserve the authored draft separately.

## Destructive and quota-bearing actions

- `Bring it to life` launches broad-access model processes and consumes quota.
- `Rebuild` first tears down a standing session; every pane loses its conversation context.
- Closing/deleting a durable draft should happen only on explicit request; the new implementation moves it to trash, but it is still a user-visible removal.
- `rig down`, `rig forget`, task revocation, and token rotation are outside ordinary workflow design.

Saving or validating a non-running draft is not a launch.

## Catalog truth hierarchy

Use this order:

1. Current runtime's structured selector/catalog and official provider documentation.
2. A successful request or local transcript as evidence that this account used a model at that time.
3. Current NXB catalog suggestions and configured defaults.
4. Binary strings as CLI-recognition evidence only.

Never infer entitlement from a launch post, binary string, or dropdown. At this snapshot, NXB's regex could omit `gpt-6-astra`, include historical GPT-5 strings, and offer a generic effort list that did not express Max/Ultra semantics correctly.
