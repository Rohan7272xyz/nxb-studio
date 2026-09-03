"""What a dispatched worker is allowed to hold, named rather than implied.

An undecided question gets answered by whoever writes the first line of code
that depends on it. The MCP path is about to be registered in an operator's own
runtimes, so a permissive default there would decide the permission boundary by
accident, on their behalf, without them ruling.

So grants are NAMED, the default is the narrow one, widening is deliberate and
appears in the call, and the grant that was actually applied is recorded in the
outcome's provenance. An operator can answer "what can the thing I installed
do" without reading Python.

`--restricted` is chosen over a denylist on purpose. It removes shell, REPL,
WebFetch, Workflow and cron as a CATEGORY, so it stays correct when new tools
ship. A denylist rots on the next release: measured in nxb-031, an ALLOWLIST
(`--allowedTools Read`) removed nothing at all, and only an exhaustive denylist
removed tools, which fails OPEN on anything added later.

What `--restricted` does NOT remove, measured: Write, Edit, Task, SendMessage
and WebSearch. Write and Edit are acceptable because the worker runs in an
isolated work dir. Task and SendMessage are NOT, and are handled by
FLEET_REACHING_TOOLS below.

THE HONEST LIMIT, stated because a silent gap is worse than a known one: under
the `shell` grant the worker has Bash, and a shell can invoke the `claude` or
`codex` binaries directly. NO DENYLIST CONTAINS A WORKER WITH A SHELL. The ban
still applies there because it removes the easy path, but `shell` should be
understood as trusting the worker, not as containing it.
"""

#: Tools that reach OUTSIDE the isolated work dir, to other agents, other
#: sessions, other machines, or the operator. Banned under EVERY grant.
#:
#: GRANT-2 measured that `--restricted` does not touch these: a child under the
#: narrow grant called ListAgents and enumerated eleven live sessions by name,
#: then EXECUTED SendMessage with zero permission_denied frames. Since the
#: operator runs his fleet in bypass mode, any session so messaged acts on it
#: without prompting, which is a confused-deputy path from an isolated worker
#: into the whole fleet.
#:
#: `--restricted` is a CATEGORY filter and these are not in the category, so
#: only an exhaustive denylist removes them. A denylist FAILS OPEN on anything
#: added in a future release, which is the rot this file already warned about,
#: so it is paired with a read-back assertion at spawn: the child's own init
#: frame is checked and the dispatch is REFUSED if a banned tool survived.
#: That converts a list that rots silently into one that fails loudly.
FLEET_REACHING_TOOLS = [
    # enumerate and message the operator's other live sessions
    "ListAgents", "SendMessage",
    # spawn or steer other agents and background work
    "Task", "Workflow", "Monitor",
    "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate",
    # schedule execution the operator did not ask for, or see and delete his
    "CronCreate", "CronDelete", "CronList", "ScheduleWakeup",
    # reach the operator or another machine out of band
    "PushNotification", "RemoteTrigger", "DesignSync",
    # leave the isolated working directory
    "EnterWorktree", "ExitWorktree",
    # ESCALATION VECTOR: surfaces and makes callable tools that were deferred,
    # which is a route back to everything above.
    "ToolSearch",
]

#: name -> per-runtime adapter kwargs. Keep this SMALL; every grant is a
#: decision someone has to understand.
GRANTS = {
    "default": {
        "_doc": "No shell, no network fetch, no cron, no workflows, and none of "
                "the operator's connected MCP servers. Can still read and write "
                "files inside its isolated work dir.",
        "claude_code": {"restricted": True, "strict_mcp_config": True,
                        "banned_tools": FLEET_REACHING_TOOLS},
        "codex": {"sandbox": "read-only"},
    },
    "shell": {
        "_doc": "DELIBERATELY WIDER. Restores the shell and the runtime's own "
                "tooling. Ask for this only when the task genuinely needs to run "
                "commands, and know that a worker with a shell in an isolated "
                "dir still has network access.",
        # The fleet ban applies HERE TOO: a worker with a shell is not
        # entitled to the operator's other sessions either. See the honest
        # limit in the module docstring.
        "claude_code": {"restricted": False, "strict_mcp_config": True,
                        "banned_tools": FLEET_REACHING_TOOLS},
        "codex": {"sandbox": "workspace-write"},
    },
}

DEFAULT_GRANT = "default"


def adapter_kwargs(grant, runtime_id):
    """Kwargs for this runtime under this grant. Raises on an unknown grant."""
    if grant not in GRANTS:
        raise KeyError(f"unknown grant {grant!r}; have {sorted(g for g in GRANTS)}")
    return dict(GRANTS[grant].get(runtime_id) or {})


def describe(grant):
    return GRANTS.get(grant, {}).get("_doc", "")
