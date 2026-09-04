"""nxb as an MCP server. MCP is the PLUG SHAPE, not the point.

Every LLM harness already speaks MCP, so speaking it plugs nxb into all of them
without a bridge per vendor. That gives the architecture its shape:

    MCP IN, ADAPTERS OUT.

Any MCP-speaking harness dispatches INTO nxb; any runtime with an adapter gets
dispatched TO. The halves are independent on purpose: a new ORCHESTRATOR
runtime costs zero if it speaks MCP, a new WORKER runtime costs one adapter.

WHY A SERVER AND NOT A LINE IN A MARKDOWN FILE. Measured on the orchestrator
who commissioned this: it spent a whole day dispatching over `SendMessage`
while building the thing meant to replace it, not from forgetfulness but
because the broker was a shell command and `SendMessage` was already in front
of it. `NEXUS PROTOCOL.md` mentions nxb zero times and still describes an
adapter that has not run since June. Writing "orchestrators must use nxb" into
that file would be the exact failure this project exists to fix: the same file
told two months of orchestrators a local adapter was validating their
directives, and that sentence was false the whole time. As an MCP tool,
dispatching costs what SendMessage costs, and nobody has to be persuaded.

The dispatch tools are a THIN WRAPPER over `nxb.run.run`, deliberately.
Dispatch, receipts, the ledger, provenance, and retry/divergence semantics are
all proven there.  Studio draft tools are the other half of the same plug:
they write the durable design model shared with the local page, but never cross
the human launch gate.

Protocol: JSON-RPC 2.0 over stdio, newline-delimited, standard library only,
because the package has no runtime dependencies and adding one to speak a
line-oriented protocol would be a poor trade.
"""

import json
import os
import sys
import traceback

from nxb.h4 import Outbox
from nxb.ledger import Ledger
from nxb.grants import DEFAULT_GRANT, GRANTS, describe
from nxb.run import ADAPTERS, EXIT, run
from nxb.studio_drafts import LAYOUTS, ROLES, RUNTIMES

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "nxb"
SERVER_VERSION = "0.2.0"

#: The ledger every tool call uses. Required, absolute, and taken from the
#: environment because an MCP tool call has no shell to pass a flag through.
#: F3's rule survives the transport: there is NO DEFAULT, because a state
#: location nobody chose is one two callers disagree about.
LEDGER_ENV = "NXB_LEDGER"

_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string",
                 "description": "Human-readable name unique inside the rig."},
        "role": {"type": "string", "enum": list(ROLES),
                 "description": "At most one agent may be orchestrator."},
        "runtime": {"type": "string", "enum": list(RUNTIMES),
                    "description": "Installed worker runtime/provider."},
        "model": {"type": "string",
                  "description": "Optional runtime model; omit for its default."},
        "effort": {"type": "string",
                   "description": "Optional reasoning effort; omit for default."},
        "working_directory": {
            "type": "string",
            "description": "Optional per-agent directory; falls back to the rig."},
        "instructions": {
            "type": "string",
            "description": "Optional standing role/startup instructions."},
        "node_id": {
            "type": "integer", "minimum": 1,
            "description": ("Stable canvas identity. Omit on create; preserve "
                            "the value returned by get when updating.")},
        "x": {"type": "number",
              "description": "Optional canvas x; NXB auto-lays out when omitted."},
        "y": {"type": "number",
              "description": "Optional canvas y; NXB auto-lays out when omitted."},
    },
    "required": ["name", "role", "runtime"],
    "additionalProperties": False,
}

_DRAFT_PROPERTIES = {
    "session": {
        "type": "string",
        "description": ("Future tmux session and Studio tab name. No spaces, "
                        "colons, dots, dollar signs, quotes or backslashes."),
    },
    "working_directory": {
        "type": "string",
        "description": "Default working directory for the whole rig.",
    },
    "layout": {
        "type": "string", "enum": list(LAYOUTS),
        "default": "main-horizontal",
        "description": "The tmux pane layout; canvas coordinates are visual only.",
    },
    "agents": {
        "type": "array", "minItems": 1, "items": _AGENT_SCHEMA,
        "description": "The complete fleet. Each entry becomes one Studio node.",
    },
    "view": {
        "type": "object",
        "properties": {
            "zoom": {"type": "number"}, "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "additionalProperties": False,
        "description": "Optional persisted canvas viewport returned by get.",
    },
}


_TOOLS = [
    {
        "name": "nxb_dispatch",
        "description": (
            "Dispatch a self-contained directive to a worker runtime and "
            "return its report. The worker CANNOT see your conversation, so "
            "every path, precondition and acceptance criterion must be inside "
            "the directive. Returns the worker's own report plus provenance "
            "naming which model actually ran."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "directive": {"type": "string",
                              "description": "The self-contained instruction."},
                "runtime": {"type": "string", "enum": sorted(ADAPTERS),
                            "description": "Which worker runtime to dispatch to."},
                "dispatch_key": {"type": "string",
                                 "description": "Optional. Reuse to retry safely "
                                 "after an unknown outcome; reusing one with a "
                                 "CHANGED directive is refused."},
                "model": {"type": "string",
                          "description": "Optional. Pin the worker's model."},
                "grant": {"type": "string", "enum": sorted(GRANTS),
                          "default": DEFAULT_GRANT,
                          "description": "What the worker may hold. Default "
                          "'default' has NO SHELL, no network fetch, no cron, "
                          "and none of your connected MCP servers. Ask for "
                          "'shell' only when the task must run commands."},
            },
            "required": ["directive", "runtime"],
        },
    },
    {
        "name": "nxb_collect",
        "description": ("Take delivery of a previously dispatched outcome by "
                        "its dispatch_key. Safe to call repeatedly; nothing is "
                        "consumed by being read."),
        "inputSchema": {
            "type": "object",
            "properties": {"dispatch_key": {"type": "string"}},
            "required": ["dispatch_key"],
        },
    },
    {
        "name": "nxb_pending",
        "description": ("Outcomes nobody has collected. THE ALARM. An empty "
                        "list and a firing alarm must not look alike, so the "
                        "count is reported explicitly."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "nxb_studio_catalog",
        "description": (
            "Read the local Studio design vocabulary before composing a fleet: "
            "installed runtimes, models, reasoning efforts, layouts and saved "
            "personas. Read-only and never launches agents."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
    {
        "name": "nxb_studio_draft_list",
        "description": (
            "List durable NXB Studio drafts with ids, revisions and fleet "
            "summaries. Read-only; use nxb_studio_draft_get for the full graph."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
    {
        "name": "nxb_studio_draft_get",
        "description": (
            "Read one complete Studio draft, including every agent and its "
            "revision. Read before updating so newer human/model edits cannot "
            "be overwritten."),
        "inputSchema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"], "additionalProperties": False,
        },
    },
    {
        "name": "nxb_studio_draft_validate",
        "description": (
            "Validate a complete fleet idea without saving or launching it. "
            "Checks the same structural invariants used at launch and reports "
            "missing local directories as warnings."),
        "inputSchema": {
            "type": "object", "properties": _DRAFT_PROPERTIES,
            "required": ["session", "working_directory", "agents"],
            "additionalProperties": False,
        },
    },
    {
        "name": "nxb_studio_draft_save",
        "description": (
            "Create or replace a COMPLETE durable Studio workflow in one call. "
            "It appears in an open Studio window on refresh and DOES NOT launch "
            "agents. Omit draft_id to create. To replace, first read the draft "
            "and pass both draft_id and expected_revision; stale edits are "
            "refused."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_DRAFT_PROPERTIES, **{
                "draft_id": {
                    "type": "string",
                    "description": "Omit to create; provide to replace."},
                "expected_revision": {
                    "type": "integer", "minimum": 1,
                    "description": "Required with draft_id; use the revision read."},
            }),
            "required": ["session", "working_directory", "agents"],
            "additionalProperties": False,
        },
    },
    {
        "name": "nxb_studio_draft_delete",
        "description": (
            "Remove a Studio draft only when the user asked to discard it. "
            "Requires the revision just read, never touches a running rig, and "
            "moves the JSON file to recoverable local trash rather than erasing "
            "it."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "expected_revision": {"type": "integer", "minimum": 1},
            },
            "required": ["draft_id", "expected_revision"],
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    """A tool failed in a way the caller should see as text, not a crash."""


def _ledger_path():
    path = os.environ.get(LEDGER_ENV)
    if not path:
        raise ToolError(
            f"{LEDGER_ENV} is not set. nxb needs an ABSOLUTE path to its state "
            f"database, and there is deliberately no default: state relative to "
            f"a working directory means two callers disagree about whether work "
            f"already happened.")
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        raise ToolError(f"{LEDGER_ENV} must be absolute, got {path!r}.")
    return path


def _text(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    return {"content": [{"type": "text", "text": body}]}


def _public_draft(record):
    """MCP shape, excluding Studio-owned liveness stamps."""
    out = dict(record)
    out["agents"] = []
    for raw in record.get("agents", []):
        agent = dict(raw)
        agent.pop("deployed_name", None)
        out["agents"].append(agent)
    return out


def call_tool(name, args):
    """Dispatch one tool call. Returns an MCP result dict."""
    ledger_path = _ledger_path()

    if name == "nxb_dispatch":
        directive = args.get("directive")
        runtime = args.get("runtime")
        if not directive or not isinstance(directive, str):
            raise ToolError("`directive` must be a non-empty string.")
        if runtime not in ADAPTERS:
            raise ToolError(f"unknown runtime {runtime!r}; have {sorted(ADAPTERS)}")
        # NOTE: the directive arrives as a STRING. `read_directive`'s @file and
        # `-` forms are shell affordances and are deliberately NOT reachable
        # here, rather than silently accepted and misread: over MCP a literal
        # "@notes.md" is a directive that starts with an at-sign, and treating
        # it as a path would read a file the caller never named.
        code, outcome = run(directive=directive, runtime_id=runtime,
                            ledger_path=ledger_path,
                            dispatch_key=args.get("dispatch_key"),
                            model=args.get("model"),
                            grant=args.get("grant") or DEFAULT_GRANT,
                            out=open(os.devnull, "w"), err=sys.stderr)
        result = {"exit_state": _state_for(code),
                  "grant_applied": args.get("grant") or DEFAULT_GRANT,
                  "grant_means": describe(args.get("grant") or DEFAULT_GRANT),
                  "outcome": outcome}
        return _text(result)

    if name == "nxb_collect":
        key = args.get("dispatch_key")
        if not key:
            raise ToolError("`dispatch_key` is required.")
        led = Ledger(ledger_path)
        try:
            return _text(Outbox(led._conn).collect(key))
        finally:
            led.close()

    if name == "nxb_pending":
        led = Ledger(ledger_path)
        try:
            rows = Outbox(led._conn).pending()
            return _text({"uncollected": len(rows), "outcomes": rows})
        finally:
            led.close()

    if name == "nxb_studio_catalog":
        from nxb.studio import Studio
        from nxb.studio_drafts import SCHEMA_VERSION

        studio = Studio(ledger_path)
        return _text({
            "schema_version": SCHEMA_VERSION,
            "runtimes": studio.models(),
            "roles": list(ROLES),
            "layouts": list(LAYOUTS),
            "personas": studio.personas()["personas"],
            "launch": ("Draft tools design Studio workflows only. Launch remains "
                       "behind the operator's Bring it to life action in Studio."),
        })

    if name == "nxb_studio_draft_list":
        from nxb.studio_drafts import list_drafts

        drafts = list_drafts(ledger_path)
        return _text({"count": len(drafts), "drafts": [
            {"draft_id": d["draft_id"], "revision": d["revision"],
             "session": d["session"], "working_directory":
             d["working_directory"], "layout": d["layout"],
             "agents": len(d["agents"]), "updated_at": d["updated_at"],
             "updated_by": d["updated_by"]}
            for d in drafts
        ]})

    if name == "nxb_studio_draft_get":
        from nxb.studio_drafts import DraftError, get_draft

        try:
            return _text(_public_draft(
                get_draft(ledger_path, args.get("draft_id"))))
        except DraftError as exc:
            raise ToolError(str(exc)) from exc

    if name in ("nxb_studio_draft_validate", "nxb_studio_draft_save"):
        from nxb.studio_drafts import (DraftError, save_draft,
                                       validate as validate_draft)

        spec = {key: args.get(key) for key in
                ("session", "working_directory", "layout", "agents", "view")
                if args.get(key) is not None}
        try:
            if name == "nxb_studio_draft_validate":
                return _text(validate_draft(spec))
            record = save_draft(
                ledger_path, spec, draft_id=args.get("draft_id"),
                expected_revision=args.get("expected_revision"), source="mcp",
                strict=True)
            return _text({"state": "SAVED", "launched": False,
                          "draft": _public_draft(record),
                          "next": "Review it in Studio; launch remains a human action."})
        except DraftError as exc:
            raise ToolError(str(exc)) from exc

    if name == "nxb_studio_draft_delete":
        from nxb.studio_drafts import DraftError, delete_draft

        try:
            return _text(delete_draft(
                ledger_path, args.get("draft_id"),
                expected_revision=args.get("expected_revision")))
        except DraftError as exc:
            raise ToolError(str(exc)) from exc

    raise ToolError(f"unknown tool {name!r}")


def _state_for(code):
    for label, value in EXIT.items():
        if value == code:
            return label
    return "UNKNOWN"


def handle(request):
    """Return a JSON-RPC response dict, or None for a notification."""
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return _ok(req_id, {"tools": _TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        try:
            return _ok(req_id, call_tool(params.get("name"),
                                         params.get("arguments") or {}))
        except ToolError as exc:
            # A tool failure is CONTENT, not a protocol error: the caller is a
            # model and needs to read what went wrong.
            return _ok(req_id, {"content": [{"type": "text", "text": str(exc)}],
                                "isError": True})
        except Exception:                                      # noqa: BLE001
            return _ok(req_id, {"content": [{"type": "text",
                                             "text": traceback.format_exc()}],
                                "isError": True})
    if req_id is None:
        return None
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
