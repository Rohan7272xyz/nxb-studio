"""H2 adapter: broker to Codex.

Every rule enforced here is a measured one from nxb-002. The machinery that
enforces them moved to `_process.py` in nxb-027 so a second runtime could reuse
it; this file is now only what is true of Codex specifically.

  F-13  stdin MUST come from /dev/null. With stdin open, `codex exec` produces
        zero bytes, emits no thread.started, and never exits.
  F-14  the `-o` file's PRESENCE is not success; its ABSENCE is failure.
  F-15  no start_signal within start_timeout means kill the child.
  F-16  process liveness is never evidence.
"""

import os

from nxb.adapters._process import (SpawnRefused, _BoundedWriter,  # noqa: F401
                                   _LineReader, ProcessAdapter, find_evidence)


class CodexAdapter(ProcessAdapter):
    runtime_id = "codex"

    def __init__(self, *, binary="codex", model="gpt-5.6-luna",
                 sandbox="read-only", reasoning_effort="low"):
        self.binary = binary
        self.model = model
        self.sandbox = sandbox
        self.reasoning_effort = reasoning_effort

    @staticmethod
    def evidence_for(thread_id, *, sessions_root=None):
        """Locate the rollout file CODEX wrote for this run.

        Delegates to the shared finder, which refuses a blank needle. See C14:
        a blank id used to match the first file the walk reached.
        """
        return find_evidence(sessions_root or "~/.codex/sessions", thread_id)

    def build_command(self, *, work_dir, prompt, out_path, schema_path=None):
        cmd = [
            self.binary, "exec", "--json", "--skip-git-repo-check",
            "-s", self.sandbox,
            "-m", self.model,                       # R-030: pin, never default
            "-C", work_dir,
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "-o", out_path,
        ]
        if schema_path:
            cmd += ["--output-schema", schema_path]
        cmd.append(prompt)
        return cmd

    def _match_start(self, evt):
        return (evt.get("type") == "thread.started"), evt.get("thread_id")

    def _note_terminal(self, evt, terminal, handle):
        t = evt.get("type")
        if t == "turn.completed":
            terminal["turn_completed"] = True
        elif t == "turn.failed":
            terminal["turn_failed"] = True
        elif t == "error":
            terminal["error"] = True
