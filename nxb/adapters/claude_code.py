"""H2 adapter: broker to a Claude Code child the broker owns.

This is the runtime the broker runs inside, and until nxb-027 it was the half
of the project that did not exist. It is a SPAWN adapter: the broker starts
`claude -p` and owns its stdout, so it has custody of the report rather than an
assertion about it. That is a different path from peer-messaging an existing
session, which has no content reply channel at all; the two declarations in
`contract/runtimes/claude_code.json` describe that other path and neither is
registrable for this one.

Three divergences from Codex, all measured in nxb-027 rather than assumed:

  1. `--json-schema` takes the schema INLINE, not a path. Codex's
     `--output-schema` takes a path. An adapter written by analogy passes a
     path and the child exits 1 with
     `--json-schema is not valid JSON: JSON Parse error`.
  2. There is no `-o`. The answer arrives in the `result` frame on stdout, so
     this adapter produces `out_path` itself in `_finalize`.
  3. The start signal is the `system`/`init` frame, which carries `session_id`.
"""

import json
import os

from nxb.adapters._process import ProcessAdapter, find_evidence


class ClaudeCodeAdapter(ProcessAdapter):
    runtime_id = "claude_code"

    def __init__(self, *, binary="claude", model="haiku", restricted=False,
                 strict_mcp_config=False, banned_tools=None):
        self.binary = binary
        #: R-030: pinned explicitly, never left to the runtime's default.
        #: `haiku` is a COST choice for canaries and probes, not a claim that it
        #: is the right model for real work. A caller dispatching work that
        #: matters should pass its own.
        self.model = model
        #: `--restricted` removes shell, REPL, WebFetch, Workflow and cron as a
        #: CATEGORY. Off by default at the adapter, because the broker does not
        #: decide a worker's powers; that is the permission boundary. The MCP
        #: path turns it ON, because that path is about to be registered in a
        #: human's own runtimes and a permissive default would decide an
        #: undecided question by accident.
        self.restricted = restricted
        #: `--strict-mcp-config` drops the operator's connected MCP servers,
        #: which have no business in a dispatched worker.
        self.strict_mcp_config = strict_mcp_config
        #: Tools this child must NOT hold. Passed as --disallowedTools AND
        #: re-checked against the child's own init frame, because passing a
        #: flag is not the same as the flag taking effect.
        self.banned_tools = list(banned_tools or [])

    @staticmethod
    def evidence_for(thread_id, *, sessions_root=None):
        """Locate the transcript CLAUDE CODE wrote for this run.

        Delegates to the shared finder, which refuses a blank needle. See C14:
        a blank id used to match the first file the walk reached.
        """
        return find_evidence(sessions_root or "~/.claude/projects", thread_id)

    def build_command(self, *, work_dir, prompt, out_path, schema_path=None):
        cmd = [
            self.binary, "-p", prompt,
            "--model", self.model,
            "--output-format", "stream-json",
            "--verbose",
        ]
        if self.restricted:
            cmd.append("--restricted")
        if self.strict_mcp_config:
            cmd.append("--strict-mcp-config")
        if self.banned_tools:
            # Measured nxb-029: `--disallowedTools Bash` REMOVES the tool,
            # where a scoped form like `Bash(echo *)` leaves it advertised and
            # denies the call. Bare names, so the tool is gone rather than
            # present and refused.
            cmd += ["--disallowedTools"] + list(self.banned_tools)
        if schema_path:
            # INLINE, not a path. Measured nxb-027: passing the path makes the
            # child exit 1 parsing the filename as JSON. The interface hands us
            # a path because Codex needs one, so we read it here.
            with open(schema_path, encoding="utf-8") as handle:
                cmd += ["--json-schema", json.dumps(json.load(handle))]
        return cmd

    def _match_start(self, evt):
        """`system`/`init`, which nxb-022 measured as LOCAL at 0.857s.

        Like Codex's `thread.started` it proves a binary launched on this
        machine and nothing about whether the runtime can reach its model. The
        first post-round-trip frame is `assistant`.
        """
        matched = evt.get("type") == "system" and evt.get("subtype") == "init"
        return matched, (evt.get("session_id") if matched else None)

    def _reject_start(self, evt):
        """GRANT-2. Refuse a child that came back holding a banned tool.

        The init frame is the runtime's OWN report of what it holds, so this is
        read-back rather than trust. If a future release renames a tool, adds a
        fleet-reaching one, or ignores the flag, the dispatch FAILS HERE with
        the offending names instead of quietly widening what a worker can do.
        """
        if not self.banned_tools:
            return None
        held = set(evt.get("tools") or [])
        survived = sorted(held.intersection(self.banned_tools))
        if survived:
            return "grant_violation: banned tools survived: " + ",".join(survived)
        return None

    def _note_terminal(self, evt, terminal, handle):
        if evt.get("type") != "result":
            return
        # Stash the whole frame: _finalize needs its payload, and the handle is
        # the correctly scoped place for per-spawn state.
        handle["result_frame"] = evt
        if evt.get("subtype") == "success" and not evt.get("is_error"):
            terminal["turn_completed"] = True
        else:
            terminal["turn_failed"] = True

    def _finalize(self, handle, terminal):
        """Produce `out_path` from the result frame, preserving F-14.

        THE DELIBERATE CHOICE, because this is where Claude Code diverges
        structurally from Codex and where the defect would live:

        The file is written ONLY for a `result` frame whose subtype is
        `success` and whose `is_error` is not true. An errored result does NOT
        write it.

        F-14 has two halves and they are not equally load-bearing. "Presence is
        not success" survives either way, because the content can still be a
        schema-valid lie and `h3.collect_report` validates it separately.
        "ABSENCE IS A RELIABLE FAILURE SIGNAL" is the half that does work, and
        writing an error payload into the success channel would destroy exactly
        that half: absence would then mean only "no result frame at all", and a
        runtime that failed loudly would look identical on disk to one that
        succeeded. So the error path is left to the terminal flags, which
        `collect_report` already reads as RUNTIME_FAILED.
        """
        frame = handle.get("result_frame")
        if not frame or frame.get("subtype") != "success" or frame.get("is_error"):
            return
        payload = frame.get("result")
        if payload is None:
            return
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        try:
            with open(handle["out_path"], "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError:
            # Absence then means failure, which is exactly what it should mean.
            pass
