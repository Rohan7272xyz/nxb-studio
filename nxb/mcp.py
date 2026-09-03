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

This is a THIN WRAPPER over `nxb.run.run`, deliberately. Dispatch, receipts,
the ledger, provenance, and the retry and divergence semantics are all proven
there. Nothing here re-implements any of it.

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

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "nxb"
SERVER_VERSION = "0.1.0"

#: The ledger every tool call uses. Required, absolute, and taken from the
#: environment because an MCP tool call has no shell to pass a flag through.
#: F3's rule survives the transport: there is NO DEFAULT, because a state
#: location nobody chose is one two callers disagree about.
LEDGER_ENV = "NXB_LEDGER"

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
