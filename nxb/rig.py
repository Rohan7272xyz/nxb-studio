"""The pane rig: stand up a named, enrolled scenario in tmux.

Rohan runs Ghostty splits, and Ghostty exposes no send-keys surface. tmux does,
and that one difference is what makes a scenario reproducible instead of
hand-assembled.

WHY THIS IS NOT A SPAWN FALLBACK
--------------------------------
`nxb/roster.py` says, deliberately: no fallback to spawning. A broker that
quietly creates a worker to satisfy a request produces exactly the black-box
agent this design exists to prevent, arriving through a convenience.

The rig does not violate that; it is its other half. Spawning here is the
OPERATOR'S EXPLICIT ACT, named in a scenario he chose, in his own tmux session,
in front of him. The broker still never spawns. That distinction is structural
rather than stated: no dispatch path imports this module, and a test asserts it.

MEASURED 2026-08-28, and every one of these changed the design
--------------------------------------------------------------
1. **Codex opens a directory-TRUST prompt** in any directory not already
   trusted, and trust is per exact path -- `/Users/rohan` being trusted does
   NOT cover `/Users/rohan/dev/nexus-bridge`. A rig that slept and then typed
   would have answered a security dialog. So readiness is a MARKER, never a
   sleep, and a trust prompt is a REFUSAL with a remedy: granting trust loads
   project-local config, hooks and exec policies, and that is the operator's
   decision, not the rig's.

2. **`/rename` works through send-keys** and prints the thread UUID, which is
   how a name becomes an address.

3. **A NAME IS NOT AN ADDRESS; THE THREAD ID IS.** `codex queue --thread
   "<name>"` failed with "No active session found" on a pane that had just
   renamed successfully AND whose name already resolved in
   `~/.codex/session_index.jsonl` -- while the same message, sent to that
   pane's UUID, was delivered and answered instantly. So `queue` resolves
   names from some store the index is not, and waiting on the index proved a
   fact that was true and useless.

   That was my own bug in this file, of the exact kind this project keeps
   finding: A READINESS CHECK MUST TEST THE THING YOU WILL ACTUALLY USE. The
   rig now takes the thread id from the rename confirmation the runtime itself
   prints, and dispatch addresses the id. A name is a label for humans; an id
   is where a message goes. This also survives a later rename, which a
   name-addressed dispatch would not.

4. **Claude names at launch (`-n`), Codex names after it (`/rename`).** The
   asymmetry is real and is not papered over: a Claude pane is named and
   enrolled before it renders a frame, a Codex pane is briefly anonymous.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid

from nxb.enroll import (ACK, enroll_command, typed_enrolment_rule,
                        typed_orchestrator_rule)

#: Published refusals. See contract/rig.json.
RIG_NO_TMUX = "rig_no_tmux"
RIG_SESSION_EXISTS = "rig_session_exists"
RIG_UNKNOWN_SCENARIO = "rig_unknown_scenario"
RIG_PANE_NOT_READY = "rig_pane_not_ready"
RIG_TRUST_PROMPT = "rig_trust_prompt"
RIG_HOOKS_REVIEW = "rig_hooks_review"
RIG_NAME_NOT_RESOLVABLE = "rig_name_not_resolvable"
RIG_ENROLMENT_UNCONFIRMED = "rig_enrolment_unconfirmed"
RIG_UPDATE_PROMPT = "rig_update_prompt"
RIG_PEER_INVALID = "rig_peer_invalid"
#: nxb-079. A rig record with no resumable conversation ids; a pane that is
#: visibly mid-turn; a nudge inside the throttle window; a nudge at a pane
#: that holds no task. See docs/CONTEXT-BUDGET-nxb-079.md.
RIG_NOT_RESUMABLE = "rig_not_resumable"
RIG_PANE_BUSY = "rig_pane_busy"
RIG_NUDGE_THROTTLED = "rig_nudge_throttled"
RIG_NOTHING_TO_NUDGE = "rig_nothing_to_nudge"
#: nxb-082. A pane asked for a checkpoint that never confirmed one is NOT
#: reset: an unconfirmed checkpoint plus a reset is the lossy compaction
#: this exists to replace.
RIG_CHECKPOINT_UNCONFIRMED = "rig_checkpoint_unconfirmed"
#: nxb-082.3. A Claude pane's /clear is proven by its session id rotating in
#: the registry; "bypass permissions on" is on screen whether or not the
#: clear ran. No rotation, no reset, and nothing is typed after it. [RIG-39]
RIG_RESET_UNCONFIRMED = "rig_reset_unconfirmed"
#: nxb-082.3. `rig relaunch` restarts one pane's runtime in place, for a new
#: ceiling or a wedged pane; refused when the old runtime will not leave or
#: the new one never reaches READY. [RIG-40]
RIG_RELAUNCH_UNCONFIRMED = "rig_relaunch_unconfirmed"

#: What a READY pane shows. Absence of the marker is failure, never a reason to
#: proceed hopefully: this is F-14's rule applied to a screen instead of a file.
#: MEASURED, not guessed. Each string was read off a real booted pane on
#: 2026-08-28; the first set I wrote from memory matched neither runtime and
#: every Claude pane timed out as "not ready" while sitting at a trust dialog.
READY_MARKERS = {
    # MEASURED 2026-09-12 (ht-android-v2): a client attached at 92 columns
    # squeezed four worker panes to 22 columns, and Codex TRUNCATES its
    # composer placeholder to the width ("Ask Codex to do anyt"), it does
    # not wrap it, so -J could not help and every fresh dispatch was refused
    # rig_pane_not_ready after /clear, 28 times in one evening. The prefix
    # survives any pane wide enough to type in.
    "codex": ("Ask Codex",),
    # `--yolo` is always in the command the rig sends, so the bypass banner is
    # a property of OUR launch rather than of the user's config. The composer
    # placeholder rotates between tips and is not usable as a marker.
    "claude_code": ("bypass permissions on", "for shortcuts"),
}

#: A screen that is NOT ready and never will be without a human. Matched before
#: readiness so the refusal names the actual obstacle rather than timing out.
#: BOTH runtimes prompt, in different words, and trust is per EXACT directory:
#: /Users/rohan being trusted does not cover /Users/rohan/dev/nexus-bridge.
BLOCKING_PROMPTS = {
    "Do you trust the contents of this directory": RIG_TRUST_PROMPT,   # codex
    "Quick safety check": RIG_TRUST_PROMPT,                            # claude
    "Is this a project you created or one you trust": RIG_TRUST_PROMPT,
    # MEASURED 2026-09-04: accepting repository trust can immediately reveal
    # a SECOND gate. Codex reviews configured lifecycle hooks separately
    # because they run outside the sandbox. Treating the old READY marker
    # behind this screen as readiness caused Studio to restart too early.
    "Hooks need review": RIG_HOOKS_REVIEW,
    # MEASURED 2026-09-03, on a real stand-up: a Codex release landed and two
    # of three Codex panes came up on an update chooser reading "Press enter
    # to continue". Unlisted, it is indistinguishable from a slow boot, so the
    # rig burned its full 60s deadline per pane and reported the useless
    # "not ready" instead of "a human must press a key in pane %3". Every
    # entry in this table was added the same way: by a pane sitting on a
    # screen no amount of waiting could clear. [RIG-9]
    "Press enter to continue": RIG_UPDATE_PROMPT,
    "Skip until next version": RIG_UPDATE_PROMPT,
}

SESSION_INDEX = "~/.codex/session_index.jsonl"

#: Codex prints this on a successful rename, and it carries the thread UUID:
#:   Session renamed to X. To resume this session run codex resume, then
#:   select X (01a04b75-424c-7fe2-9e97-4f332768a9f3)
#: Taken from the runtime's own acknowledgement, so there is nothing to race.
#: Matched against a WHITESPACE-STRIPPED copy of the screen. Codex hard-wraps
#: its own output to the pane width, so in the narrow worker panes the UUID is
#: split across a newline (`01a04b77-9591-` / `7ac1-...`). tmux's -J does not
#: rejoin it, because the wrap is the application's, not the terminal's. The id
#: parsed in the wide top pane and failed in every worker pane below it, which
#: presented as flakiness rather than as a layout-dependent bug.
_RENAMED = re.compile(r"Sessionrenamedto(.*?)\.To.*?\(([0-9a-fA-F-]{36})\)")

#: Scenario 2 is Rohan's: one Codex orchestrator on top, four workers below,
#: two of each runtime. `main-horizontal` gives exactly that shape.
#: What an operator may type for a runtime. Short forms because a composition
#: is typed by hand at a prompt, and `cc:2,cx:5` is the shape of the thing.
RUNTIME_ALIASES = {"cc": "claude_code", "claude": "claude_code",
                   "claude_code": "claude_code",
                   "cx": "codex", "codex": "codex"}

#: How a worker of each runtime is named. The runtime is IN THE NAME on
#: purpose: the whole point of a mixed fleet is knowing which vendor answered,
#: and an orchestrator asked to cross-check has to be able to pick two workers
#: that are genuinely different without looking anything up.
WORKER_PREFIX = {"claude_code": "CC", "codex": "CX"}

#: Border colours, one per agent. Spread across the 256-colour cube so no two
#: panes side by side read as the same on a screen or on camera.
ORCHESTRATOR_COLOUR = 141                       # the studio's accent mauve
WORKER_COLOURS = [208, 45, 154, 213, 220, 39, 171, 84, 203, 111,
                  49, 214, 129, 118, 167, 81]


def parse_workers(spec):
    """`cc:2,cx:5` -> [("claude_code", 2), ("codex", 5)]. Raises on nonsense."""
    out = []
    for chunk in str(spec).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        runtime, _, count = chunk.partition(":")
        key = RUNTIME_ALIASES.get(runtime.strip().lower())
        if key is None:
            raise ValueError(
                f"unknown runtime {runtime.strip()!r}. Known: "
                f"{', '.join(sorted(set(RUNTIME_ALIASES)))}")
        try:
            n = int(count) if count else 1
        except ValueError:
            raise ValueError(f"{chunk!r}: the count must be a number") from None
        if n < 1:
            raise ValueError(f"{chunk!r}: a count below 1 builds nothing")
        out.append((key, n))
    if not out:
        raise ValueError("no workers requested")
    return out


#: How each runtime is told which model and how hard to think. MEASURED from
#: each CLI's own --help on 2026-09-03, not assumed: claude takes `--model`
#: and `--effort <low|medium|high|xhigh|max>`; codex takes `-m` and reaches
#: reasoning effort through `-c`, which is the same key its config.toml uses.
#: Nothing here is offered in the UI that a runtime cannot actually be told.
#: CONTEXT CEILINGS, one per runtime, passed on EVERY launch. [RIG-25]
#:
#: MEASURED on the Pact programme, 2026-09-07 to 09-10. Claude panes on the
#: 1M-context models ran to 860K and 930K tokens of context (two screenshot-
#: heavy reviewers) and re-read all of it on every one of their 618 and 1,256
#: requests: 0.95 BILLION cache-read tokens across 20 panes
#: (deduplicated per request; see nxb/usage.py). Codex panes sat
#: at 200K to 244K for most of the run, and every request re-sent it. The
#: model is not the cost; the context each request carries is. Both CLIs take
#: a ceiling at which they compact: `claude --autocompact <tokens>` (100k to
#: 1M, documented in --help) and `codex -c model_auto_compact_token_limit=N`
#: (a ConfigToml key in the binary). Both verified to boot READY with these
#: values on 2026-09-12, claude 2.1.270 and codex 0.154.0.
#:
#: A ceiling is not a model choice: the model, its effort and its window are
#: whatever the operator picked. It decides how much of that window a pane is
#: allowed to fill before it summarises, which is the thing that was never
#: bounded. Per-agent `context_limit` overrides it; 0 disables it.
#: nxb-082 lowered both to 100K: with a CHECKPOINT written to the vault
#: before a reset (rig checkpoint / rig watch), a low ceiling is safe, and
#: MEASURED on Pact 421M of 1,364M input tokens (31 percent) sat above 100K
#: against 117M above 160K.
DEFAULT_CONTEXT_LIMIT = {"claude_code": 100_000, "codex": 100_000}
MIN_CONTEXT_LIMIT = {"claude_code": 60_000, "codex": 32_000}

#: THE CEILING IS OURS; THE RUNTIME'S COMPACTION IS THE BACKSTOP. [nxb-082.1]
#:
#: MEASURED 2026-09-12 on pact-dev Builder 1 (Opus 5, claude 2.1.270): with
#: `--autocompact 100000` the runtime compacted at 67,173 tokens of context,
#: a few file reads into its first task. The flag names a WINDOW, and Claude
#: Code compacts about 33K below it (its output reserve and buffer). The
#: ceiling nxb enforces is `context_limit`, read from the transcript by the
#: gauge and checkpointed at 80 percent; the flag passed to the runtime is
#: set ABOVE the ceiling by this margin so the vendor's opaque compaction
#: fires only if the watcher did not get there first. Codex's
#: model_auto_compact_token_limit is a threshold on tokens used, so its
#: margin is smaller. Both are capped at the model's window.
RUNTIME_BACKSTOP_MARGIN = {"claude_code": 45_000, "codex": 20_000}
RUNTIME_WINDOW_CAP = {"claude_code": 1_000_000, "codex": 250_000}
RUNTIME_FLAG_FLOOR = {"claude_code": 100_000, "codex": 32_000}


#: THE TOOL SCHEMAS ARE HALF THE FLOOR. [nxb-082.2]
#:
#: MEASURED 2026-09-12, four throwaway Haiku panes in ~/dev/pact, one
#: one-word turn each, first-request context read from the transcript:
#: default launch 42,684 tokens; --strict-mcp-config 42,286 (the MCP
#: schemas are deferred and cost about 400); --tools Bash,Read,Edit,Write,
#: Glob,Grep 23,449. The built-in tools a rig pane never uses (Agent,
#: Artifact, Workflow, Skill, the cron and design tools, web fetch and
#: search) are about 19K tokens carried on EVERY request of every pane,
#: and 19K of a 100K ceiling that the work cannot use. A rig pane gets the
#: core set unless its draft says `tools: all`.
CORE_TOOLS = {"claude_code": "Bash,Read,Edit,Write,Glob,Grep"}


def tool_flags(runtime, tools=None):
    """`--tools <set>` for a Claude pane. `all` (or "") keeps everything."""
    if runtime != "claude_code":
        return []                       # no equivalent measured for Codex
    wanted = " ".join(str(tools or "core").split())
    if wanted.lower() == "all":
        return []
    if wanted.lower() == "core":
        wanted = CORE_TOOLS["claude_code"]
    names = [n.strip() for n in wanted.replace(" ", ",").split(",") if n.strip()]
    return ["--tools", shlex.quote(",".join(names))] if names else []


def runtime_backstop(runtime, context_limit):
    """The compaction value the RUNTIME is told, for a ceiling of ours."""
    if not context_limit:
        return None
    value = int(context_limit) + RUNTIME_BACKSTOP_MARGIN.get(runtime, 0)
    value = max(value, RUNTIME_FLAG_FLOOR.get(runtime, 0))
    return min(value, RUNTIME_WINDOW_CAP.get(runtime, value))


def clean_context_limit(value, runtime):
    """An integer token ceiling, 0 for none, None for the runtime default.

    Raises ValueError on nonsense, so a draft cannot carry a ceiling the
    runtime would reject at boot in a pane nobody is watching.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("context_limit must be a number of tokens")
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"context_limit must be a number of tokens, got "
                         f"{value!r}") from None
    if limit < 0:
        raise ValueError("context_limit cannot be negative")
    floor = MIN_CONTEXT_LIMIT.get(runtime, 0)
    if limit and limit < floor:
        raise ValueError(f"context_limit for {runtime} must be at least "
                         f"{floor} tokens (or 0 to disable the ceiling)")
    return limit


def resolved_context_limit(spec):
    """The ceiling a pane will actually be launched with (0 means none)."""
    runtime = RUNTIME_ALIASES.get(str(spec.get("runtime", "")).lower(),
                                  spec.get("runtime"))
    limit = clean_context_limit(spec.get("context_limit"), runtime)
    if limit is None:
        limit = DEFAULT_CONTEXT_LIMIT.get(runtime, 0)
    return limit


def model_flags(runtime, model=None, effort=None, context_limit=None):
    """Return shell-ready runtime flags with every dynamic value quoted.

    Both launch paths join these fragments into a command that is typed into
    an interactive shell. Model aliases are therefore shell data: Claude's
    official ``opus[1m]`` form must not become a zsh glob, and a value restored
    from an older Studio draft must never become shell syntax.

    `context_limit` is nxb's ceiling in tokens (checkpointed by the watcher
    at 80 percent); the runtime receives it plus a margin as its own
    compaction backstop, see runtime_backstop. None or 0 passes no flag and
    leaves the runtime's own default in place.
    """
    out = []
    backstop = runtime_backstop(runtime, context_limit)
    if runtime == "claude_code":
        if model:
            out += ["--model", shlex.quote(str(model))]
        if effort:
            out += ["--effort", shlex.quote(str(effort))]
        if backstop:
            out += ["--autocompact", str(backstop)]
    elif runtime == "codex":
        if model:
            out += ["-m", shlex.quote(str(model))]
        if effort:
            setting = f'model_reasoning_effort="{effort}"'
            out += ["-c", shlex.quote(setting)]
        if backstop:
            out += ["-c", shlex.quote(
                f"model_auto_compact_token_limit={backstop}")]
    return out


#: Characters a peer rig name cannot carry: the same set a session name
#: refuses, because a peer IS a session name. [RIG-21]
_BAD_PEER_CHARS = " \t:.$'\"\\"


def _clean_peers(peers):
    """Peer rig names as a deduplicated list, or ValueError. [RIG-21]

    Accepts a list or a comma-separated string: the CLI flag and the browser
    bar both speak the latter, the draft speaks the former.
    """
    if peers is None:
        return []
    if isinstance(peers, str):
        peers = peers.split(",")
    if not isinstance(peers, (list, tuple)):
        raise ValueError("peers must be a list of rig session names")
    out = []
    for raw in peers:
        name = str(raw or "").strip()
        if not name:
            continue
        if any(c in name for c in _BAD_PEER_CHARS):
            raise ValueError(f"peer rig {name!r}: a rig name carries no "
                             f"spaces, colons, dots, dollar signs, quotes or "
                             f"backslashes")
        if name not in out:
            out.append(name)
    return out


def compose_agents(agents, *, layout="main-horizontal", peers=None):
    """A scenario from EXPLICIT agents, each with its own name and settings.

    `compose` builds a fleet from counts, which is the right shape for a
    command line. A composed diagram is a different thing: every node is an
    individual with a name the operator chose ("API Worker", not "CX Worker
    2"), and possibly its own model, reasoning effort and directory. Rather
    than overload the count form, this takes the list as given and validates
    it. [STUDIO-2]
    """
    if not agents:
        raise ValueError("a fleet with no agents is not a fleet")
    panes, seen = [], set()
    orchestrators = 0
    for a in agents:
        runtime = RUNTIME_ALIASES.get(str(a.get("runtime", "")).lower())
        if runtime is None:
            raise ValueError(
                f"unknown runtime {a.get('runtime')!r}. Known: "
                f"{', '.join(sorted(set(RUNTIME_ALIASES)))}")
        role = "orchestrator" if a.get("role") == "orchestrator" else "worker"
        orchestrators += role == "orchestrator"
        name = " ".join(str(a.get("name") or "").split())
        if not name:
            raise ValueError("every agent needs a name")
        if any(c in name for c in "'\\\""):
            raise ValueError(f"{name!r}: quotes and backslashes cannot go in a "
                             f"name that is typed into a shell and a runtime")
        if name in seen:
            # Two panes with one name means a minted id addresses both, and
            # the worker-side check cannot tell them apart.
            raise ValueError(f"two agents are both called {name!r}")
        seen.add(name)
        pane = {"name": name, "runtime": runtime, "role": role}
        for key in ("model", "effort", "dir", "instructions", "tools"):
            if a.get(key):
                pane[key] = a[key]
        # A ceiling is validated HERE, at composition, so a draft that names
        # one the runtime would refuse never reaches a pane. [RIG-25]
        limit = clean_context_limit(a.get("context_limit"), runtime)
        if limit is not None:
            pane["context_limit"] = limit
        panes.append(pane)
    if orchestrators > 1:
        raise ValueError("a rig has at most one orchestrator")
    plan = {"description": f"{len(panes)} agents, composed",
            "layout": layout, "panes": panes}
    peers = _clean_peers(peers)
    if peers:
        plan["peers"] = peers
    return plan


def scoped_name(session, name):
    """`nxb CX Worker 1`. A worker's name CARRIES ITS RIG. [RIG-20]

    Rohan's call, and it is the right one: RIG-18 refused an ambiguous name,
    which is a guard standing where an invariant belongs. Fleets are built
    from a shape, so two rigs both held a "CX Worker 1" AND both held an
    "Orchestrator" -- and a ticket names a worker, not a rig, so a ticket
    minted for one fleet would type into the other and be validated there.

    Scoping the name deletes the ambiguity instead of detecting it. Names are
    now globally unique across every standing rig, which also means `--session`
    stops being required to disambiguate: there is nothing to disambiguate.

    Applied at STAND-UP rather than baked into the scenarios, so a scenario
    stays a SHAPE and naming stays one rule in one place.
    """
    prefix = f"{session} "
    return name if str(name).startswith(prefix) else prefix + str(name)


def compose(workers, *, orchestrator=None, layout="main-horizontal"):
    """Build a scenario from a composition, instead of a hardcoded table.

    THE TABLE WAS THE LIMIT, not the machinery. Everything below this already
    handled any mix of runtimes and roles; the only thing stopping an operator
    from running one Claude orchestrator over five Codex workers was that
    SCENARIOS held exactly one entry and it lived in Python. Composition is
    the operator's, which is the same principle as the roster: the population
    is declared by the person who will watch it. [RIG-17]
    """
    panes = []
    if orchestrator:
        key = RUNTIME_ALIASES.get(str(orchestrator).lower())
        if key is None:
            raise ValueError(f"unknown orchestrator runtime {orchestrator!r}")
        panes.append({"name": "Orchestrator", "runtime": key,
                      "role": "orchestrator"})
    # VALIDATED HERE, not in the caller. This checked the orchestrator's
    # runtime and trusted the workers' because its only caller ran them
    # through parse_workers first. The studio is a second caller and does not,
    # so an unknown runtime reached WORKER_PREFIX and raised KeyError -- which
    # in an HTTP handler is a dropped connection rather than a refusal.
    # A validation that lives in the caller is a validation one new caller
    # away from being absent. [STUDIO-1]
    given = list(workers)
    workers = [(RUNTIME_ALIASES.get(str(r).lower()), int(n)) for r, n in given]
    for (runtime, count), (raw, _) in zip(workers, given):
        # NAME THE OFFENDING VALUE. A refusal the operator cannot act on is
        # the same as no message: they still have to go and look.
        if runtime is None or runtime not in WORKER_PREFIX:
            raise ValueError(
                f"unknown worker runtime {raw!r}. Known: "
                f"{', '.join(sorted(set(RUNTIME_ALIASES)))}")
        if count < 1:
            raise ValueError(f"{raw!r}: a worker count below 1 builds nothing")
    for runtime, count in workers:
        for i in range(1, count + 1):
            panes.append({"name": f"{WORKER_PREFIX[runtime]} Worker {i}",
                          "runtime": runtime, "role": "worker"})
    kinds = ", ".join(f"{n} {WORKER_PREFIX[r]}" for r, n in workers)
    return {"description": (f"{orchestrator or 'no'} orchestrator; "
                            f"workers: {kinds}"),
            "layout": layout, "panes": panes}


SCENARIOS = {
    "scenario2": {
        "description": "1 Codex orchestrator on top; 4 workers below "
                       "(2 Claude Code, 2 Codex)",
        "layout": "main-horizontal",
        "panes": [
            {"name": "Orchestrator", "runtime": "codex", "role": "orchestrator"},
            {"name": "CC Worker 1", "runtime": "claude_code", "role": "worker"},
            {"name": "CC Worker 2", "runtime": "claude_code", "role": "worker"},
            {"name": "CX Worker 1", "runtime": "codex", "role": "worker"},
            {"name": "CX Worker 2", "runtime": "codex", "role": "worker"},
        ],
    },
}


#: tmux MATCHES A SESSION TARGET BY PREFIX. Measured 2026-09-03: `-t zztest`
#: resolved to a session actually named `zztest-abc`, and `rig down` with the
#: default name `nxb` killed the operator's `nxb-s2` rig while reporting
#: `"session": "nxb"` -- a session that never existed. Right outcome, wrong
#: reason, misleading report, and with two rigs standing it is a coin flip
#: over which one dies. `=name` is tmux's own exact-match form. [RIG-8]
def _exact(session):
    return session if str(session).startswith("=") else f"={session}"


def _exact_window(session):
    """Exact-match form for a WINDOW or PANE target, which is not the same.

    MEASURED 2026-09-03, immediately after the exact-match fix broke `rig up`
    outright with "can't find pane: =nxb". A session target takes `=name`; a
    pane or window target takes `=name:` and REJECTS the bare form. One idea,
    two syntaxes, and applying the session form to every call site looked like
    a tidy sweep. Every other test in this file mocks tmux, so the mocks
    agreed with what the author believed tmux's syntax was -- a measurement of
    the author, not of tmux. The only thing that caught it was standing a rig
    up, and the guard that now covers it drives the real binary.
    """
    return session if str(session).startswith("=") else f"={session}:"


def _tmux(*args, check=True):
    return subprocess.run(["tmux", *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=20,
                          check=False if not check else False)


def _refuse(reason, detail, **extra):
    out = {"state": "REFUSED", "reason": reason, "detail": detail}
    out.update(extra)
    return out


#: Above this many bytes, text goes in as a PASTE rather than as keystrokes.
#:
#: MEASURED 2026-09-07 on live Claude Code 2.1.263 panes: a ~1.3 KB operator
#: message typed with send-keys arrived in two of five panes with only its
#: last two dozen characters ("Acknowledge in one line."), and a running
#: orchestrator independently observed the same on a worker pane. Keystroke
#: delivery of a long burst is lossy at the TUI; a bracketed paste through
#: tmux's buffer is atomic and is what both runtimes' composers expect for
#: large input. [RIG-23]
PASTE_THRESHOLD = 600


def send_line(pane, text, *, settle=0.5):
    """Deliver text, then submit it as a SEPARATE keystroke.

    MEASURED: sending the text and Enter in one `send-keys` call leaves the
    text sitting un-submitted in Codex's composer. Its slash-command popup
    opens as `/rename` is typed and eats the Enter that arrives in the same
    burst. My hand-run worked only because I happened to pause between the two.
    So the pause is the mechanism, not a politeness, and it is why the rig
    verifies submission rather than assuming it.

    Long text is pasted (bracketed, via a tmux buffer) rather than typed, and
    the settle grows with its size so Enter arrives after the paste has been
    consumed. [RIG-23]
    """
    data = str(text).encode("utf-8")
    if len(data) > PASTE_THRESHOLD:
        # Through a FILE and `_tmux`, so tmux stays the only process this
        # module can start (F-15b) and no stdin plumbing is needed.
        import tempfile
        buf = f"nxb-{os.getpid()}-{int(time.time() * 1000)}"
        with tempfile.NamedTemporaryFile("wb", prefix="nxb-paste-",
                                         suffix=".txt", delete=False) as handle:
            handle.write(data)
            path = handle.name
        try:
            loaded = _tmux("load-buffer", "-b", buf, path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if loaded.returncode == 0:
            _tmux("paste-buffer", "-p", "-d", "-b", buf, "-t", pane)
            time.sleep(max(settle, 1.0) + len(data) / 4000.0)
            _tmux("send-keys", "-t", pane, "Enter")
            return
        # A buffer that will not load falls back to typing; better late than
        # silent, and the old path is the one every earlier rig used.
    _tmux("send-keys", "-t", pane, text)
    time.sleep(settle)
    _tmux("send-keys", "-t", pane, "Enter")


def await_screen(pane, needle, *, deadline=20.0, poll=0.5):
    """Wait for `needle` to appear on a pane. True, or False on timeout."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if needle in capture(pane):
            return True
        time.sleep(poll)
    return False


def capture(pane):
    """What is on a pane's screen right now."""
    # -J JOINS WRAPPED LINES. Without it the rename confirmation wraps in a
    # narrow pane and splits the UUID across a newline, so the id regex
    # matched in the wide top pane and failed in every worker pane below it.
    # A layout-dependent bug that looked like flakiness.
    result = _tmux("capture-pane", "-t", pane, "-p", "-J")
    return result.stdout if result.returncode == 0 else ""


def capture_history(pane, lines=3000):
    """A pane's scrollback as well as its screen.

    `capture` reads the visible screen only, which is right for a readiness
    marker and wrong for an ANSWER: a long reply scrolls off, and reading the
    visible screen would silently return a truncated one. [RIG-5]
    """
    result = _tmux("capture-pane", "-t", pane, "-p", "-J", "-S", f"-{lines}")
    return result.stdout if result.returncode == 0 else ""


def pane_state(pane, runtime):
    """READY, a blocking-prompt refusal reason, or None for 'not yet'.

    Blocking prompts are checked FIRST. A trust dialog would otherwise simply
    time out, and 'not ready after 40s' is a far worse answer than 'it is
    waiting for you to make a trust decision, here is how'.
    """
    screen = capture(pane)
    for needle, reason in BLOCKING_PROMPTS.items():
        if needle in screen:
            return reason
    for marker in READY_MARKERS.get(runtime, ()):
        if marker in screen:
            return "READY"
    return None


def trust_scope(screen):
    """The directory a runtime is asking the operator to trust, if shown.

    Codex can wrap ``repository root`` in the middle of the word in a narrow
    pane, so this is parsed from a whitespace-normalised screen rather than a
    single terminal line.  It is display evidence only: recovery still
    re-checks the actual trust prompt before pressing anything.
    """
    flat = re.sub(r"\s+", " ", str(screen or "")).strip()
    boundaries = (r"(?=\s+(?:Do you trust|Trusting the directory|"
                  r"Quick safety check|Is this a project|(?:›\s*)?1\.))")
    match = re.search(
        r"repository\s+r\s*o\s*o\s*t\s*:\s*(.+?)" + boundaries,
        flat, re.IGNORECASE)
    if match is None:
        match = re.search(r"You are in\s+(.+?)"
                          r"(?=\s+(?:Note:|Do you trust|Quick safety check|"
                          r"Is this a project))", flat, re.IGNORECASE)
    return match.group(1).strip() if match else None


def await_ready(pane, runtime, *, deadline=60.0, poll=0.5):
    """Wait for a READY marker. Returns (True, None) or (False, reason)."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        state = pane_state(pane, runtime)
        if state == "READY":
            return True, None
        if state is not None:
            return False, state
        time.sleep(poll)
    return False, RIG_PANE_NOT_READY


def codex_thread_named(name, *, index_path=None):
    """Thread id currently bound to `name`, or None.

    The index is an APPEND LOG: a thread appears once per rename, so the LAST
    row for a name is the live binding and earlier rows are history. Reading
    the first match would resolve a name to a thread that has since been
    renamed away from it.
    """
    path = os.path.expanduser(index_path or SESSION_INDEX)
    found = None
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("thread_name") == name:
                    found = row.get("id")
    except OSError:
        return None
    return found


def await_rename(pane, name, *, deadline=30.0, poll=0.5):
    """Wait for Codex to CONFIRM the rename, and return the thread id it prints.

    The id comes from the runtime's own acknowledgement on screen, which is
    both immediate and authoritative. An earlier version waited for the name to
    appear in session_index.jsonl instead; that check passed while
    `codex queue --thread "<name>"` still answered "No active session found",
    so it proved a true and useless fact. Measured both ways on 2026-08-28.
    """
    wanted = re.sub(r"\s+", "", name)
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        match = _RENAMED.search(re.sub(r"\s+", "", capture(pane)))
        # The confirmation names the pane it belongs to, so a stale one from an
        # earlier rename cannot be mistaken for this one's.
        if match and match.group(1) == wanted:
            return match.group(2)
        time.sleep(poll)
    return None


#: Codex's undocumented alias for --dangerously-bypass-approvals-and-sandbox,
#: verified accepted on codex-cli 0.153.0. It is the counterpart of the
#: `claude --yolo` the Claude half has always used.
#:
#: WHY BOTH RUNTIMES RUN UNSANDBOXED, stated plainly rather than left implicit.
#: Rohan's fleet runs in bypass mode by his own decision: these are his panes,
#: on his machine, doing his work, and a pane that stops to ask permission is a
#: pane he has to babysit. The Claude half honoured that from the start and the
#: Codex half quietly did not -- it was launched --sandbox workspace-write, so
#: two runtimes in one fleet had different powers and nobody had decided that.
#:
#: MEASURED CONSEQUENCE, and it is why this is a defect rather than a
#: preference: the sandboxed Codex orchestrator could not reach the tmux
#: socket in /private/tmp, so `rig workers` reported an EMPTY FLEET to the one
#: agent whose entire job is knowing the fleet. An unchosen asymmetry became a
#: false answer at the top of the system. [RIG-12]
CODEX_YOLO = "--yolo"


def launch_command(spec, *, ledger, repo, sandbox=None, session="nxb",
                   peers=None):
    """The shell line for one pane. Returns (command, enrolment_kind, refusal).

    `enrolment_kind` is "launch", "typed" or None -- never a boolean. A
    launch-bound rule and a typed one are different KINDS of barrier and a
    boolean would erase exactly the difference that matters.
    """
    limit = resolved_context_limit(spec)
    if spec["runtime"] == "claude_code":
        # Named AND enrolled before it renders a frame: -n sets the display
        # name at launch and the rule is bound at the same moment, so there is
        # no window in which the pane is anonymous or unenrolled. The session
        # id is chosen HERE too (--session-id), so the record knows the
        # address a later resume needs before the pane has said a word.
        cmd, refusal = enroll_command(
            spec["name"], ledger=ledger, repo=repo,
            role=spec.get("role", "worker"), session=session,
            model=spec.get("model"), effort=spec.get("effort"),
            instructions=spec.get("instructions"), peers=peers,
            session_id=spec.get("session_id"),
            resume_session_id=spec.get("resume_session_id"),
            context_limit=limit, tools=spec.get("tools"))
        return cmd, "launch", refusal
    if spec["runtime"] == "codex":
        # No --append-system-prompt and no --name: named by /rename after
        # launch, and enrolled by TYPING the rule in once it is named.
        # `sandbox` remains an explicit opt-in: passing one is a deliberate
        # choice to give a Codex pane LESS than the fleet's declared posture,
        # and it is recorded in the command the operator can read on screen.
        flag = f"--sandbox {sandbox}" if sandbox else CODEX_YOLO
        extra = model_flags("codex", spec.get("model"), spec.get("effort"),
                            context_limit=limit)
        line = ["codex", flag, *extra]
        if spec.get("resume_thread_id"):
            # `codex [OPTIONS] resume <id>`: global flags first, verified to
            # boot READY with the pane's original name in its footer.
            line += ["resume", shlex.quote(str(spec["resume_thread_id"]))]
        return " ".join(line), "typed", None
    return None, None, _refuse(
        RIG_UNKNOWN_SCENARIO, f"no launcher for runtime {spec['runtime']!r}")


def await_ack(pane, name, *, deadline=90.0, poll=1.0):
    """Wait for a typed-enrolled pane to echo its acknowledgement.

    Matched whitespace-stripped, for the same reason the rename id is: Codex
    hard-wraps to the pane width and the echo straddles a newline in the
    narrow worker panes.
    """
    wanted = re.sub(r"\s+", "", f"{ACK}{name}")
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if wanted in re.sub(r"\s+", "", capture(pane)):
            return True
        time.sleep(poll)
    return False


def stand_up(scenario="scenario2", *, session="nxb", work_dir=None, ledger,
             repo=None, width=240, height=60, ready_deadline=60.0,
             name_deadline=30.0, enrol_deadline=90.0, peers=None):
    """Create the scenario. Returns a report; never raises.

    Refuses rather than clobbering an existing session: those panes may be
    running the operator's work, and killing them to make room is not a
    convenience anyone asked for.
    """
    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.",
                       remedy=["brew install tmux"])
    if isinstance(scenario, dict):
        plan, scenario = scenario, scenario.get("name", "custom")
    elif scenario in SCENARIOS:
        plan = SCENARIOS[scenario]
    else:
        return _refuse(RIG_UNKNOWN_SCENARIO,
                       f"No scenario {scenario!r}. Known: "
                       f"{', '.join(sorted(SCENARIOS))}. Or compose one with "
                       f"--orchestrator and --workers.")
    # PEER RIGS are validated before any tmux state changes. [RIG-21]
    try:
        peers = _clean_peers(peers if peers is not None
                             else plan.get("peers"))
    except ValueError as exc:
        return _refuse(RIG_PEER_INVALID, str(exc))
    if session in peers:
        return _refuse(RIG_PEER_INVALID,
                       f"rig {session!r} cannot be its own peer.",
                       remedy=["name only OTHER rigs as peers"])
    work_dir = work_dir or os.getcwd()
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if _tmux("has-session", "-t", _exact(session)).returncode == 0:
        return _refuse(
            RIG_SESSION_EXISTS,
            f"tmux session {session!r} already exists. Refusing to replace it: "
            f"its panes may be running your work.",
            remedy=[f"tmux attach -t {session}",
                    f"tmux kill-session -t {session}"])

    # A pane may name its OWN directory; the rig's --dir is the default for
    # any that does not. tmux takes it per pane at creation, so this costs
    # nothing beyond passing it through.
    pane_dirs = [os.path.expanduser(str(p.get("dir") or work_dir))
                 for p in plan["panes"]]
    pane_ids, refusal = _build_window(session, pane_dirs, plan["layout"],
                                      width=width, height=height)
    if refusal is not None:
        return refusal

    panes, problems = [], []
    for spec, pane, pane_dir in zip(plan["panes"], pane_ids, pane_dirs):
        spec = dict(spec, name=scoped_name(session, spec["name"]))
        if spec["runtime"] == "claude_code":
            # THE ADDRESS IS CHOSEN BEFORE LAUNCH. A Claude session id is
            # otherwise learned only by asking the registry later, and a
            # rig that goes down with the machine before anyone asked has no
            # address to resume. [RIG-26]
            spec["session_id"] = str(uuid.uuid4())
            # The tool set is recorded as launched, so the record says what
            # the pane has and a resume reapplies it. [RIG-34]
            spec.setdefault("tools", "core")
        cmd, enrolment, refusal = launch_command(
            spec, ledger=ledger, repo=repo, session=session, peers=peers)
        entry = {"name": spec["name"], "runtime": spec["runtime"],
                 "role": spec["role"], "pane": pane, "dir": pane_dir,
                 "context_limit": resolved_context_limit(spec),
                 "launched_at": _utc_now(),
                 **{k: spec[k] for k in ("model", "effort", "instructions",
                                         "session_id", "tools")
                    if spec.get(k)},
                 # Set only once CONFIRMED. A typed rule is not enrolment until
                 # the pane echoes it back.
                 "enrolment": enrolment if enrolment == "launch" else None,
                 "enrolment_intended": enrolment}
        if refusal is not None:
            entry.update(state="REFUSED", reason=refusal["reason"])
            problems.append(entry)
            panes.append(entry)
            continue
        send_line(pane, cmd)
        panes.append(entry)

    # Readiness is awaited AFTER every pane has been launched, so five runtimes
    # boot concurrently instead of serially.
    for entry in panes:
        if entry.get("state") == "REFUSED":
            continue
        ok, reason = await_ready(entry["pane"], entry["runtime"],
                                 deadline=ready_deadline)
        if not ok:
            screen = capture(entry["pane"])
            entry.update(state="REFUSED", reason=reason,
                         screen_tail=screen.strip()[-300:])
            if reason == RIG_TRUST_PROMPT:
                scope = trust_scope(screen)
                if scope:
                    entry["trust_scope"] = scope
            if reason in (RIG_TRUST_PROMPT, RIG_UPDATE_PROMPT):
                what = ("trust prompt" if reason == RIG_TRUST_PROMPT
                        else "update prompt")
                # "then re-run" WAS WRONG AND IT IS ALSO RUNTIME-DEPENDENT.
                # Re-running refuses: the session now exists. And a Claude
                # pane needs no re-run at all, because -n and
                # --append-system-prompt were bound in the launch command, so
                # answering the dialog lets it finish booting already named
                # and already enrolled. A Codex pane DOES need one, because
                # its name and its rule are typed AFTER readiness and the rig
                # has already given up. Measured on a real stand-up. [RIG-10]
                if entry["runtime"] == "claude_code":
                    entry["remedy"] = [
                        f"tmux attach -t {session}, answer the {what} in pane "
                        f"{entry['pane']}. NO RE-RUN NEEDED: this pane was "
                        f"launched already named and enrolled, so answering "
                        f"the dialog completes it.",
                        f"then confirm with: python3 -m nxb rig workers "
                        f"--session {session}"]
                else:
                    entry["remedy"] = [
                        f"tmux attach -t {session}, answer the {what} in pane "
                        f"{entry['pane']}. This pane is NOT yet named or "
                        f"enrolled (Codex is named after it boots), so it "
                        f"needs the rig to finish it:",
                        f"python3 -m nxb rig down --session {session} && "
                        f"python3 -m nxb rig up --session {session}",
                        "or stand the rig up in a directory both runtimes "
                        "already trust"]
            elif reason == RIG_HOOKS_REVIEW:
                entry["remedy"] = [
                    f"tmux attach -t {session}, review the hooks in pane "
                    f"{entry['pane']}. Hooks execute outside the sandbox, so "
                    "this is a separate operator decision from repository "
                    "trust.",
                    "After the choice, rebuild this partial rig so Codex can "
                    "finish naming and enrolment."]
            problems.append(entry)
            continue
        entry["state"] = "READY"

    # Codex panes are named only now: /rename needs a composer to type into.
    for entry in panes:
        if entry["state"] != "READY" or entry["runtime"] != "codex":
            continue
        send_line(entry["pane"], f"/rename {entry['name']}")
        thread_id = await_rename(entry["pane"], entry["name"],
                                 deadline=name_deadline)
        if thread_id is None:
            entry.update(
                state="REFUSED", reason=RIG_NAME_NOT_RESOLVABLE,
                detail="the rename was never acknowledged, so the keystroke "
                       "did not land and this pane has no dispatch address",
                screen_tail=capture(entry["pane"]).strip()[-300:])
            problems.append(entry)
            continue
        # The ADDRESS. Dispatch uses this, never entry["name"].
        entry["thread_id"] = thread_id

        # nxb-051: now that it has a name, type the rule in. This is the
        # typing layer doing what it exists for -- normalising what differs
        # between runtimes -- and it is confirmed, not assumed.
        if entry["enrolment_intended"] == "typed":
            # THE SEAT DESIGNED TO DRIVE THE FLEET WAS BEING TOLD ONLY HOW TO
            # RECEIVE WORK. Until 2026-09-03 every pane, orchestrator included,
            # got the worker rule, so nothing anywhere told an orchestrator
            # that mint/send/collect exist. The plumbing was complete and
            # unreachable. [RIG-7]
            rule = _typed_rule(entry, ledger=ledger, repo=repo,
                               session=session, peers=peers)
            send_line(entry["pane"], rule)
            if not await_ack(entry["pane"], entry["name"],
                             deadline=enrol_deadline):
                entry.update(
                    state="REFUSED", reason=RIG_ENROLMENT_UNCONFIRMED,
                    detail="the rule was typed but never acknowledged, so this "
                           "pane is named and NOT enrolled; treat it as "
                           "unprotected",
                    screen_tail=capture(entry["pane"]).strip()[-300:])
                problems.append(entry)
                continue
            entry["enrolment"] = "typed"

    # A ROLE RIDES WITH THE RULE. Claude carries it in the system prompt at
    # launch, the stronger form [STUDIO-11]. Codex has it typed, and since
    # nxb-079 it is typed INSIDE the enrolment message rather than as a
    # second message: one turn per pane instead of two, one acknowledgement
    # to verify instead of one plus a free-text reply, and the RIG-22
    # preamble (a typed role is not a task) is part of the same text. See
    # enroll.typed_role. Recorded per pane so a reset can re-type it.
    for entry in panes:
        if entry.get("state") != "READY" or not entry.get("instructions"):
            continue
        entry["role_binding"] = ("launch" if entry["runtime"] == "claude_code"
                                 else "typed")

    _decorate(session, panes)

    report = {"state": "REFUSED" if problems else "READY",
              "scenario": scenario, "session": session, "peers": peers,
              "attach": f"tmux attach -t {session}",
              "panes": panes,
              # What a RESUME needs to rebuild the window the same way.
              "work_dir": work_dir, "layout": plan["layout"],
              "width": width, "height": height, "repo": repo,
              "launched_at": _utc_now(),
              **({"problems": [p["name"] for p in problems]} if problems else {})}
    # Which pane holds which worker, so a later dispatch can find it. Written
    # even on a partial stand-up: the panes that DID come up are still usable.
    from nxb.keystroke import save_rig
    report["rig_state"] = save_rig(ledger, session, report)
    return report


#: `/clear` is the same word in both runtimes, which is luck rather than
#: design; it is a per-runtime fact and lives in a table so it stays one.
CLEAR_COMMAND = {"codex": "/clear", "claude_code": "/clear"}


def clear(session="nxb", *, only=None, ledger=None, repo=None,
          enrol_deadline=90.0):
    """Clear every pane in the rig. THE STANDING MANUAL STEP, ENDED.

    A pane cannot clear itself, so all day this has been a rule in HANDOFF.md
    that Rohan executes by hand, once per pane. Typing is the mechanism that
    makes it a command instead of a habit.

    MEASURED: `/clear` does NOT change a Codex thread id, so a cleared worker
    keeps its dispatch address. A clear that silently re-addressed the pane
    would be worse than not having one.
    """
    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.")
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return _refuse(RIG_SESSION_EXISTS,
                       f"no tmux session {session!r} to clear.",
                       remedy=[f"python3 -m nxb rig up --session {session}"])

    from nxb.keystroke import load_rig, save_rig

    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state = load_rig(ledger, session) if ledger else None
    peers = list((state or {}).get("peers") or [])
    listed = _tmux("list-panes", "-t", _exact(session),
                   "-F", "#{pane_id}")
    panes = listed.stdout.split() if listed.returncode == 0 else []
    known = {p["pane"]: p for p in (state or {}).get("panes", [])}

    cleared, re_enrolled, unprotected = [], [], []
    for pane in panes:
        if only is not None and pane not in only:
            continue
        send_line(pane, "/clear")
        cleared.append(pane)

        # A LAUNCH-BOUND RULE SURVIVES /clear. A TYPED ONE CANNOT: it IS a
        # conversation message, and /clear exists precisely to discard those.
        # Before this, clear left a Codex pane named, addressable, recorded as
        # enrolled, and no longer enforcing anything -- silently, because
        # `enrolment: "typed"` records how a rule was DELIVERED, never whether
        # it still HOLDS. So the rule is re-typed and re-confirmed, and a pane
        # that will not confirm is DOWNGRADED in the state file rather than
        # left wearing a claim it cannot back. [RIG-6]
        entry = known.get(pane)
        if not entry or entry.get("enrolment") != "typed":
            continue
        if not ledger:
            unprotected.append(entry["name"])
            continue
        rule = _typed_rule(entry, ledger=ledger, repo=repo, session=session,
                           peers=peers)
        send_line(pane, rule)
        if await_ack(pane, entry["name"], deadline=enrol_deadline):
            re_enrolled.append(entry["name"])
        else:
            entry["enrolment"] = None
            unprotected.append(entry["name"])

    if state is not None and ledger:
        # /clear ROTATES a Claude session id (measured, RUNTIME-CLAUDE-CODE),
        # so the resume address recorded at launch is stale from here. Ask
        # the registry for the new one by name.
        refresh_session_ids(known.values())
        save_rig(ledger, session, dict(state, session=session, peers=peers,
                                       panes=list(known.values())))
    out = {"state": "CLEARED", "session": session, "panes": cleared,
           "re_enrolled": re_enrolled}
    if unprotected:
        # Named loudly: these panes are named and NOT enforcing.
        out["unprotected"] = unprotected
        out["detail"] = (f"{len(unprotected)} pane(s) could not be re-enrolled "
                         f"after the clear and are recorded UNENROLLED: "
                         f"{', '.join(unprotected)}. rig send will refuse them.")
    return out


class RigTmuxError(RuntimeError):
    """tmux could not be ASKED. Distinct from tmux answering 'nothing'.

    MEASURED 2026-09-03, and it is this project's own founding defect wearing
    a new hat. `rig_roster` filtered its recorded panes against the live pane
    ids tmux reports, and on a failed tmux call that list is EMPTY -- so a
    roster of five live workers and a tmux that cannot be reached produced the
    same answer: `"workers": []`. The freshly briefed orchestrator ran the
    command, was told it had no fleet, and had no way to know it had been lied
    to. An empty answer and an unaskable question must never look alike.
    """

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def _pane_widths(session):
    """{pane id: width in columns} for a standing rig; {} if tmux refuses."""
    listed = _tmux("list-panes", "-t", _exact(session), "-F",
                   "#{pane_id} #{pane_width}")
    out = {}
    if listed.returncode == 0:
        for line in listed.stdout.split("\n"):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                out[parts[0]] = int(parts[1])
    return out


#: Narrower than this and the runtimes truncate the lines nxb reads: Codex's
#: composer placeholder, Claude Code's footer. Health names it. [RIG-38]
NARROW_PANE_COLS = 60


def _live_panes(session):
    """Live pane ids, or raise. NEVER an empty set standing in for failure.

    THREE OUTCOMES, and nxb-055 collapsed two of them. A rig that has been
    TORN DOWN legitimately has no panes: that is an answer, not a failure, and
    treating it as one made a stale state file from this morning refuse every
    mint in the afternoon. Only a session that EXISTS and cannot be queried is
    unaskable. Asked first, so the distinction is made by tmux rather than by
    reading an error string. [RIG-14]
    """
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return set()                    # that rig is down; it has no workers
    listed = _tmux("list-panes", "-t", _exact(session), "-F", "#{pane_id}")
    if listed.returncode != 0:
        raise RigTmuxError(
            f"tmux could not be asked about session {session!r}: "
            f"{(listed.stderr or '').strip() or 'no error text'}. This is NOT "
            f"the same as the session having no panes, and nxb will not "
            f"report an empty fleet on the strength of a failed question.")
    return set(listed.stdout.split())


def live_rig_sessions(ledger):
    """Rig sessions recorded next to `ledger` whose tmux session still stands.

    A state file outlives its session (tear_down does not delete it), so the
    file alone is a record, not a live rig. Existence plus a tmux answer is
    the same discipline the roster applies to sockets: never existence alone.
    """
    from nxb.keystroke import rig_sessions
    return [s for s in rig_sessions(ledger)
            if _tmux("has-session", "-t", _exact(s)).returncode == 0]


def accept_trust_prompts(session, *, ledger, deadline=60.0, poll=0.5):
    """Accept only currently visible directory-trust prompts in one rig.

    This is intentionally narrower than a generic "continue" button.  The
    operator has made the trust decision in Studio, but a stale browser must
    never press Enter into a composer, an update chooser, or an unrelated
    pane.  Every recorded pane is checked before any key is sent, then each
    target is checked once more immediately before the literal Enter key.
    """
    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.")
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"tmux session {session!r} is no longer standing; there is no "
            "trust prompt to accept.")

    from nxb.keystroke import load_rig
    record = load_rig(ledger, session)
    entries = list((record or {}).get("panes") or [])
    if not entries:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"no recorded panes belong to {session!r}; refusing to send a "
            "key to an unverified tmux target.")
    try:
        live = _live_panes(session)
    except RigTmuxError as exc:
        return _refuse(RIG_PANE_NOT_READY, exc.detail)

    targets, blockers, observed = [], [], []
    for entry in entries:
        pane = entry.get("pane")
        runtime = entry.get("runtime")
        if not pane or pane not in live or runtime not in READY_MARKERS:
            current = "missing"
        else:
            current = pane_state(pane, runtime)
        item = {"name": entry.get("name"), "pane": pane,
                "runtime": runtime, "state": current}
        if current == RIG_TRUST_PROMPT:
            scope = trust_scope(capture(pane))
            if scope:
                item["trust_scope"] = scope
            targets.append(item)
        elif current != "READY":
            blockers.append(item)
        observed.append(item)

    if blockers:
        names = ", ".join(str(p.get("name") or p.get("pane"))
                          for p in blockers)
        return _refuse(
            RIG_PANE_NOT_READY,
            "Trust recovery is available only when every incomplete pane is "
            f"still at a directory-trust prompt. Check: {names}.",
            panes=observed)
    if not targets:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"no pane in {session!r} is currently showing a directory-trust "
            "prompt, so Studio did not send any keys.", panes=observed)

    # A second all-target check keeps a stale click from partially acting if
    # a prompt changed while the first screen inventory was being captured.
    changed = [p for p in targets
               if pane_state(p["pane"], p["runtime"]) != RIG_TRUST_PROMPT]
    if changed:
        return _refuse(
            RIG_PANE_NOT_READY,
            "A trust prompt changed before Studio could accept it. No keys "
            "were sent; inspect the rig and try again.", panes=observed)

    accepted = []
    for item in targets:
        sent = _tmux("send-keys", "-t", item["pane"], "Enter")
        if sent.returncode != 0:
            return _refuse(
                RIG_PANE_NOT_READY,
                f"tmux could not accept the trust prompt in {item['pane']}: "
                f"{(sent.stderr or '').strip() or 'no error text'}.",
                accepted=accepted, panes=observed)
        accepted.append(item["pane"])

    # Do not tear the partial rig down until each runtime has consumed and
    # persisted the choice.  An immediate restart can race that persistence
    # and present the same prompt again.
    pending = {p["pane"]: p for p in targets}
    ready_seen = {pane: 0 for pane in pending}
    end = time.monotonic() + deadline
    last = {}
    while pending and time.monotonic() < end:
        for pane, item in list(pending.items()):
            current = pane_state(pane, item["runtime"])
            last[pane] = current
            if current == "READY":
                ready_seen[pane] += 1
                if ready_seen[pane] >= 3:
                    del pending[pane]
            elif current in BLOCKING_PROMPTS.values() and current != RIG_TRUST_PROMPT:
                return _refuse(
                    RIG_PANE_NOT_READY,
                    f"{item.get('name') or pane} moved from repository trust "
                    f"to another prompt ({current}); Studio will not answer "
                    "that prompt automatically.", accepted=accepted)
            else:
                ready_seen[pane] = 0
        if pending:
            time.sleep(poll)
    if pending:
        names = ", ".join(str(p.get("name") or pane)
                          for pane, p in pending.items())
        return _refuse(
            RIG_PANE_NOT_READY,
            f"Trust was accepted, but these panes did not finish booting "
            f"before the deadline: {names}.", accepted=accepted, last=last)

    return {"state": "TRUST_ACCEPTED", "session": session,
            "panes": targets, "accepted": accepted}


def _selected_hook_option(screen):
    match = re.search(r"(?:›|>)\s*([123])\.\s*", str(screen or ""))
    return int(match.group(1)) if match else None


def accept_hook_prompts(session, *, ledger, deadline=60.0, poll=0.5):
    """Choose "Trust all" only on verified Codex hook-review screens.

    Hook approval is separate from repository trust because hooks execute
    outside the sandbox.  This function is reached only after the operator
    explicitly says they reviewed them in Studio. It moves the selector to
    option 2, verifies that exact label on every target, and only then submits.
    """
    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.")
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"tmux session {session!r} is no longer standing; there is no "
            "hook review to approve.")

    from nxb.keystroke import load_rig
    record = load_rig(ledger, session)
    entries = list((record or {}).get("panes") or [])
    if not entries:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"no recorded panes belong to {session!r}; refusing to send keys "
            "to unverified tmux targets.")
    try:
        live = _live_panes(session)
    except RigTmuxError as exc:
        return _refuse(RIG_PANE_NOT_READY, exc.detail)

    targets, blockers, observed = [], [], []
    for entry in entries:
        pane = entry.get("pane")
        runtime = entry.get("runtime")
        current = (pane_state(pane, runtime)
                   if pane and pane in live and runtime in READY_MARKERS
                   else "missing")
        item = {"name": entry.get("name"), "pane": pane,
                "runtime": runtime, "state": current}
        if current == RIG_HOOKS_REVIEW:
            item["selected"] = _selected_hook_option(capture(pane))
            targets.append(item)
        elif current != "READY":
            blockers.append(item)
        observed.append(item)
    if blockers:
        names = ", ".join(str(p.get("name") or p.get("pane"))
                          for p in blockers)
        return _refuse(
            RIG_PANE_NOT_READY,
            "Hook recovery is available only when every incomplete pane is "
            f"still at the hook-review screen. Check: {names}.",
            panes=observed)
    if not targets:
        return _refuse(
            RIG_PANE_NOT_READY,
            f"no pane in {session!r} is currently showing hook review, so "
            "Studio did not send any keys.", panes=observed)

    changed = [p for p in targets
               if pane_state(p["pane"], p["runtime"]) != RIG_HOOKS_REVIEW]
    if changed:
        return _refuse(
            RIG_PANE_NOT_READY,
            "A hook-review screen changed before Studio could act. No keys "
            "were sent; inspect the rig and try again.", panes=observed)

    # Move every selector first; do not approve a subset if one pane refuses
    # to land on the exact "Trust all and continue" choice.
    for item in targets:
        selected = _selected_hook_option(capture(item["pane"]))
        if selected not in (1, 2, 3):
            return _refuse(
                RIG_PANE_NOT_READY,
                f"Studio could not identify the selected hook option in "
                f"{item['pane']}; no approval was submitted.", panes=observed)
        if selected != 2:
            key = "Down" if selected == 1 else "Up"
            moved = _tmux("send-keys", "-t", item["pane"], key)
            if moved.returncode != 0:
                return _refuse(
                    RIG_PANE_NOT_READY,
                    f"tmux could not select hook approval in {item['pane']}: "
                    f"{(moved.stderr or '').strip() or 'no error text'}.",
                    panes=observed)

    select_end = time.monotonic() + 3.0
    unselected = list(targets)
    while unselected and time.monotonic() < select_end:
        unselected = [p for p in targets
                      if (pane_state(p["pane"], p["runtime"]) !=
                          RIG_HOOKS_REVIEW or
                          _selected_hook_option(capture(p["pane"])) != 2)]
        if unselected:
            time.sleep(.1)
    if unselected:
        return _refuse(
            RIG_PANE_NOT_READY,
            "Studio could not verify 'Trust all and continue' on every pane, "
            "so it submitted none of them.", panes=observed)

    approved = []
    for item in targets:
        sent = _tmux("send-keys", "-t", item["pane"], "Enter")
        if sent.returncode != 0:
            return _refuse(
                RIG_PANE_NOT_READY,
                f"tmux could not submit hook approval in {item['pane']}: "
                f"{(sent.stderr or '').strip() or 'no error text'}.",
                approved=approved, panes=observed)
        approved.append(item["pane"])

    pending = {p["pane"]: p for p in targets}
    ready_seen = {pane: 0 for pane in pending}
    end = time.monotonic() + deadline
    last = {}
    while pending and time.monotonic() < end:
        for pane, item in list(pending.items()):
            current = pane_state(pane, item["runtime"])
            last[pane] = current
            if current == "READY":
                ready_seen[pane] += 1
                if ready_seen[pane] >= 3:
                    del pending[pane]
            elif (current in BLOCKING_PROMPTS.values() and
                  current != RIG_HOOKS_REVIEW):
                return _refuse(
                    RIG_PANE_NOT_READY,
                    f"{item.get('name') or pane} moved to another prompt "
                    f"({current}); Studio will not answer it automatically.",
                    approved=approved)
            else:
                ready_seen[pane] = 0
        if pending:
            time.sleep(poll)
    if pending:
        names = ", ".join(str(p.get("name") or pane)
                          for pane, p in pending.items())
        return _refuse(
            RIG_PANE_NOT_READY,
            f"Hooks were approved, but these panes did not finish booting "
            f"before the deadline: {names}.", approved=approved, last=last)
    return {"state": "HOOKS_APPROVED", "session": session,
            "panes": targets, "approved": approved}


def rig_roster(ledger, session="nxb"):
    """The workers this rig declared, as a Roster.

    The Claude session registry cannot see a Codex pane, so without this a
    Codex worker could never be minted for and the uniform rule would be
    uniform in wording only. The rig's own state IS a declaration -- the
    operator named this population when he stood the scenario up -- which is
    the same property the registry's `nameSource: user` provides.

    Liveness is still not taken on trust: a recorded pane counts only if tmux
    still lists it, for the same reason a socket file is not a live worker.
    """
    from nxb.keystroke import load_rig
    from nxb.roster import Roster, RosterEntry

    state = load_rig(ledger, session)
    if not state:
        return Roster([])
    live = _live_panes(session)
    return Roster([
        RosterEntry(entry["pane"], name=entry["name"], alive=True,
                    source="rig")
        for entry in state["panes"]
        if entry.get("name") and entry["pane"] in live])


def tear_down(session="nxb"):
    """Kill the rig's session BY NAME.

    F-15b: only ever a direct handle, never a command-line pattern. A
    `pkill -f codex` here would kill the operator's unrelated work, which is
    not hypothetical -- it happened in nxb-009 and cost another worker's run.
    """
    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.")
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return {"state": "ABSENT", "session": session}
    _tmux("kill-session", "-t", _exact(session))
    return {"state": "GONE", "session": session}


# =============================================================================
# nxb-079: the context budget. Reset, resume, nudge, health.
#
# MEASURED on the Pact programme (docs/CONTEXT-BUDGET-nxb-079.md): the fleet's
# cost was request count times context size, and three things drove both --
# orchestrators polling, panes carrying every previous task's context, and two
# host restarts that rebuilt 25 panes from nothing and re-dispatched work
# whose ids were still open. Everything below exists to remove one of those.
# =============================================================================

def _utc_now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _build_window(session, pane_dirs, layout, *, width=240, height=60):
    """Create the tmux session with one pane per directory. (ids, refusal).

    Shared by `stand_up` and `resume`, so a resumed rig has the window a
    fresh one has.
    """
    created = _tmux("new-session", "-d", "-s", session, "-c", pane_dirs[0],
                    "-x", str(width), "-y", str(height))
    if created.returncode != 0:
        return None, _refuse(
            RIG_NO_TMUX, f"tmux new-session failed: {created.stderr.strip()}")
    # THE WINDOW KEEPS ITS DECLARED SIZE WHATEVER CLIENT ATTACHES. MEASURED
    # 2026-09-12/13: a client attached at 92 columns shrank ht-android-v2's
    # four worker panes to 22 columns (Codex truncated its placeholder, 28
    # dispatch refusals) and pact-dev's builders to 53 (the footer lost its
    # busy marker, a working builder read idle). With window-size manual the
    # client gets a viewport and the panes stay as drafted. [RIG-38]
    _tmux("set-option", "-w", "-t", _exact_window(session),
          "window-size", "manual")
    _tmux("resize-window", "-t", _exact_window(session),
          "-x", str(width), "-y", str(height))
    # Panes run a SHELL and are then typed into, rather than having the runtime
    # as the pane process. A runtime that dies then leaves its error on screen
    # instead of taking the pane with it, which is the difference between a
    # debuggable rig and a vanishing one.
    pane_ids = [_tmux("list-panes", "-t", _exact(session),
                      "-F", "#{pane_id}").stdout.split()[0]]
    for index in range(1, len(pane_dirs)):
        made = _tmux("split-window", "-t", _exact_window(session),
                     "-c", pane_dirs[index], "-P", "-F", "#{pane_id}")
        if made.returncode != 0:
            return None, _refuse(
                RIG_NO_TMUX,
                f"split-window failed at pane {index + 1} of "
                f"{len(pane_dirs)}: {made.stderr.strip()}",
                remedy=["a smaller fleet, or a larger --width/--height"])
        pane_ids.append(made.stdout.strip())
        # REDISTRIBUTE AFTER EVERY SPLIT, not once at the end.
        #
        # Each split halves the pane it lands in, so without this the window
        # runs out of room and tmux refuses with "no space for a new pane".
        # MEASURED with plain tmux on a 240x60 window, no runtimes involved:
        # 5 panes without this line, 15 with it. The rig therefore had an
        # undocumented ceiling of about six agents, and it failed as a bare
        # tmux error message rather than as anything an operator could act
        # on -- found by asking for eleven.
        _tmux("select-layout", "-t", _exact_window(session), layout)
    _tmux("select-layout", "-t", _exact_window(session), layout)
    return pane_ids, None


def _decorate(session, panes):
    """Names on the borders, one colour per agent.

    ONE COLOUR PER AGENT. Colouring by RUNTIME was the obvious move and it
    is the wrong one: a mixed fleet then has two colours, and eleven panes
    in two colours read as one undifferentiated block. The orchestrator
    keeps the accent so the eye lands on it first.

    EVERY PANE WEARS ITS AGENT'S NAME, whatever runtime is inside it.
    Claude titles its pane with the worker name and Codex titles it with the
    cwd, so half a mixed fleet's borders read "rohan" and the operator has
    to count panes to know who is who. The rig already knows every name, so
    it is stored as a tmux USER OPTION -- which a runtime cannot overwrite,
    unlike the pane title it is competing with.
    """
    worker_n = 0
    for entry in panes:
        if not entry.get("pane"):
            continue
        if entry.get("name"):
            _tmux("set-option", "-p", "-t", entry["pane"],
                  "@nxb_name", entry["name"])
        if entry.get("role") == "orchestrator":
            colour = ORCHESTRATOR_COLOUR
        else:
            colour = WORKER_COLOURS[worker_n % len(WORKER_COLOURS)]
            worker_n += 1
        _tmux("set-option", "-p", "-t", entry["pane"],
              "pane-border-style", f"fg=colour{colour}")
        _tmux("set-option", "-p", "-t", entry["pane"],
              "pane-active-border-style", f"fg=colour{colour},bold")
        entry["colour"] = colour
    _tmux("set-option", "-t", _exact(session), "pane-border-format",
          " #[bold]#{?@nxb_name,#{@nxb_name},#{pane_title}} ")
    _tmux("set-option", "-t", _exact(session), "pane-border-status", "top")
    _tmux("set-option", "-t", _exact(session), "pane-border-lines", "heavy")


def _typed_rule(entry, *, ledger, repo, session, peers):
    """The rule a typed-enrolment pane is given, role included. [RIG-22]"""
    if entry.get("role") == "orchestrator":
        return typed_orchestrator_rule(
            entry["name"], ledger=ledger, repo=repo, session=session,
            peers=peers, instructions=entry.get("instructions"))
    return typed_enrolment_rule(entry["name"], ledger=ledger, repo=repo,
                                instructions=entry.get("instructions"))


def claude_session_ids():
    """{display name: sessionId} for Claude sessions, from the registry files.

    Read on demand and never cached: a session id ROTATES on /clear
    (measured, docs/RUNTIME-CLAUDE-CODE.md), so any copy is stale from the
    next clear. Read from `~/.claude/sessions/<pid>.json` rather than by
    running `claude agents --json`, because this module is proven to start
    no process but tmux (F-15b) and the records carry the same fields.
    """
    from nxb.roster import session_registry_ids
    return session_registry_ids()


def refresh_session_ids(entries):
    """Re-read live Claude session ids by name into pane entries. {name: id}"""
    claude = [e for e in entries
              if e.get("runtime") == "claude_code" and e.get("name")]
    if not claude:
        return {}
    live = claude_session_ids()
    changed = {}
    for entry in claude:
        sid = live.get(entry["name"])
        if sid and sid != entry.get("session_id"):
            entry["session_id"] = sid
            changed[entry["name"]] = sid
    return changed


def _is_busy(screen):
    from nxb.keystroke import busy_screen
    return busy_screen(screen)


def reset_pane(entry, *, session, ledger, repo=None, enrol_deadline=90.0,
               ready_deadline=60.0):
    """Clear ONE pane and put its rule and role back. [RIG-25]

    The per-task context reset behind `rig send --fresh` (the default). A
    Claude pane's rule and role are launch-bound and survive /clear; a Codex
    pane's are typed, so they are re-typed in one message and the
    acknowledgement is verified, exactly as at stand-up. A pane that is
    visibly mid-turn is refused rather than cleared: the reset exists to save
    tokens, not to destroy work.
    """
    from nxb.keystroke import load_rig, save_rig

    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pane, runtime, name = entry["pane"], entry["runtime"], entry["name"]
    if _tmux("has-session", "-t", _exact(session)).returncode != 0:
        return _refuse(RIG_PANE_NOT_READY,
                       f"rig {session!r} is not standing; nothing to reset.")
    if _is_busy(capture(pane)):
        return _refuse(RIG_PANE_BUSY,
                       f"{name} is mid-turn; a reset now would discard work "
                       f"in flight.",
                       remedy=["collect its outstanding task with --wait",
                               "or send with --keep-context to queue behind "
                               "it"])
    if runtime == "claude_code":
        # A DRAFT IN THE COMPOSER TURNS /clear INTO A MESSAGE. MEASURED
        # 2026-09-12 (pact-dev): the operator had typed "continue from the
        # checkpoint" into an idle pane without sending it; /clear typed
        # after it would have submitted "continue from the checkpoint/clear"
        # as a prompt and cleared nothing. Ctrl-U empties the line first.
        # Claude only: measured there, not on Codex. [RIG-36]
        _tmux("send-keys", "-t", pane, "C-u")
        time.sleep(0.3)
    send_line(pane, CLEAR_COMMAND.get(runtime, "/clear"))
    time.sleep(1.5)
    ok, reason = await_ready(pane, runtime, deadline=ready_deadline)
    if not ok:
        return _refuse(reason or RIG_PANE_NOT_READY,
                       f"{name} did not come back to a prompt after /clear.",
                       screen_tail=capture(pane).strip()[-300:])
    out = {"state": "RESET", "worker": name, "pane": pane,
           "runtime": runtime, "session": session}

    state = load_rig(ledger, session)
    peers = list((state or {}).get("peers") or [])
    record = next((p for p in (state or {}).get("panes", [])
                   if p.get("name") == name), None)
    target = record if record is not None else entry
    if not target.get("instructions") and entry.get("instructions"):
        target["instructions"] = entry["instructions"]

    # A LAUNCH-BOUND RULE SURVIVES /clear. A TYPED ONE CANNOT. [RIG-6]
    if "typed" in (target.get("enrolment"), entry.get("enrolment")):
        send_line(pane, _typed_rule(target, ledger=ledger, repo=repo,
                                    session=session, peers=peers))
        if await_ack(pane, name, deadline=enrol_deadline):
            target["enrolment"] = "typed"
            out["re_enrolled"] = True
        else:
            target["enrolment"] = None
            if state is not None:
                save_rig(ledger, session, state)
            entry["enrolment"] = None
            return _refuse(RIG_ENROLMENT_UNCONFIRMED,
                           f"{name} was cleared and its rule was typed but "
                           f"never acknowledged; it is recorded UNENROLLED.",
                           screen_tail=capture(pane).strip()[-300:])
    if runtime == "claude_code":
        # /clear rotates the session id; the resume address must follow it.
        # The registry is rewritten a moment AFTER the clear (measured: a
        # single read right after it kept the old id and blinded the
        # watcher for 21 minutes), so poll it briefly for a changed id.
        before_id = target.get("session_id")
        changed = {}
        for _ in range(40):
            changed = refresh_session_ids([target])
            if changed or not before_id:
                break
            time.sleep(0.5)
        if changed:
            out["session_id"] = changed[name]
        elif before_id:
            # MEASURED 2026-09-13 12:55 AM (pact-dev Builder 2): /clear was
            # typed into a pane that had just begun a turn, queued behind
            # it, and the READY marker matched anyway. The continuation then
            # queued too, and the pane ran its old context to the vendor's
            # compaction. The registry is the only proof a clear ran.
            return _refuse(RIG_RESET_UNCONFIRMED,
                           f"{name}'s session id did not rotate within 20 s "
                           f"of /clear, so the clear did not run (it is "
                           f"probably queued behind a turn); nothing was "
                           f"typed after it.",
                           worker=name, session_id=before_id,
                           screen_tail=capture(pane).strip()[-300:])
    if state is not None and record is not None:
        save_rig(ledger, session, state)
    for key in ("enrolment", "session_id"):
        if key in target:
            entry[key] = target[key]
    return out


def _resume_id(entry):
    """The conversation id a pane can be resumed on, or None.

    MEASURED 2026-09-12 (pact-dev): a Claude pane that was launched with a
    pinned session id but never received a prompt has NO transcript, and
    `claude --resume <id>` refuses it, so the pane came back REFUSED while
    its two siblings resumed. A session id with nothing recorded under it
    is not an address; such a pane is relaunched fresh instead.
    """
    if entry.get("runtime") == "codex":
        return entry.get("thread_id") or None
    if entry.get("runtime") == "claude_code":
        sid = entry.get("session_id") or None
        if not sid:
            return None
        from nxb.gauge import _claude_transcript
        return sid if _claude_transcript(sid) else None
    return None


def _name_and_enrol(entry, *, ledger, repo, session, peers, name_deadline,
                    enrol_deadline):
    """Rename and enrol ONE fresh Codex pane. The stand-up steps, for resume."""
    send_line(entry["pane"], f"/rename {entry['name']}")
    thread_id = await_rename(entry["pane"], entry["name"],
                             deadline=name_deadline)
    if thread_id is None:
        entry.update(state="REFUSED", reason=RIG_NAME_NOT_RESOLVABLE,
                     detail="the rename was never acknowledged, so this pane "
                            "has no dispatch address",
                     screen_tail=capture(entry["pane"]).strip()[-300:])
        return False
    entry["thread_id"] = thread_id
    send_line(entry["pane"], _typed_rule(entry, ledger=ledger, repo=repo,
                                         session=session, peers=peers))
    if not await_ack(entry["pane"], entry["name"], deadline=enrol_deadline):
        entry.update(state="REFUSED", reason=RIG_ENROLMENT_UNCONFIRMED,
                     detail="the rule was typed but never acknowledged; this "
                            "pane is named and NOT enrolled",
                     screen_tail=capture(entry["pane"]).strip()[-300:])
        return False
    entry["enrolment"] = "typed"
    if entry.get("instructions"):
        entry["role_binding"] = "typed"
    return True


SHELLS = ("zsh", "bash", "sh", "fish", "-zsh", "-bash", "login")


def _pane_command(pane):
    out = _tmux("display", "-p", "-t", pane, "#{pane_current_command}")
    return out.stdout.strip() if out.returncode == 0 else ""


def relaunch_pane(worker, *, session, ledger, repo=None, context_limit=None,
                  effort=None, ready_deadline=180.0, name_deadline=30.0,
                  enrol_deadline=90.0, exit_deadline=20.0):
    """Restart ONE pane's runtime in place and set it going again. [RIG-40]

    MEASURED 2026-09-13 (pact-dev): a 100K Opus builder on a Swift page
    spent its evening in checkpoint cycles, five resets on one task, and a
    wedged API retry cost it fifteen minutes. Changing a pane's ceiling or
    unwedging it meant `rig resume` for the whole rig, which disturbs the
    panes that were fine. This leaves the runtime (Ctrl-C twice), relaunches
    with the record's flags (a new `context_limit` or `effort` first
    written to the record), waits READY, re-enrols a Codex pane, and types
    a continuation for the task the pane holds: from its checkpoint note
    when one exists, plainly otherwise. Never resets the lead's siblings.
    """
    from nxb.context import orientation_line
    from nxb.keystroke import (_resolve, load_rig, marked_directive,
                               outstanding_tasks, save_rig)
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state = load_rig(ledger, session)
    if not state:
        return _refuse(KEYSTROKE_NO_RIG_REASON, f"no rig record for {session!r}.")
    entry = next((p for p in state.get("panes", []) if p.get("name") == worker),
                 None)
    if entry is None:
        return _refuse(RIG_NAME_NOT_RESOLVABLE,
                       f"{worker!r} is not a pane of rig {session!r}.")
    try:
        live = _live_panes(session)
    except RigTmuxError as exc:
        return _refuse("rig_tmux_unavailable", exc.detail)
    pane = entry.get("pane")
    if pane not in live:
        return _refuse(RIG_PANE_NOT_READY, f"{worker}'s pane {pane} is not alive.")
    name, runtime = entry["name"], entry["runtime"]
    if context_limit is not None:
        entry["context_limit"] = clean_context_limit(context_limit, runtime)
    if effort:
        entry["effort"] = effort
    # 1. Replace the pane's process with a fresh shell. MEASURED 2026-09-13
    # 1:12 to 1:14 AM on a busy Claude pane: two Ctrl-C only interrupted
    # the turn and dropped its queued messages, and /exit queued behind the
    # turn. tmux's respawn-pane -k kills whatever runs in the pane and
    # starts the shell again in the SAME pane id, so every record and every
    # peer's address still holds. The transcript is on disk; nothing else
    # in the old process matters.
    if _pane_command(pane) not in SHELLS:
        _tmux("respawn-pane", "-k", "-t", pane, "-c",
              entry.get("dir") or state.get("work_dir") or os.getcwd())
        end = time.monotonic() + exit_deadline
        while time.monotonic() < end and _pane_command(pane) not in SHELLS:
            time.sleep(0.5)
        if _pane_command(pane) not in SHELLS:
            return _refuse(RIG_RELAUNCH_UNCONFIRMED,
                           f"{name}'s pane did not come back to a shell "
                           f"within {int(exit_deadline)} s of respawn-pane; "
                           f"nothing relaunched.", worker=name,
                           screen_tail=capture(pane).strip()[-300:])
    # THE SHELL MUST BE AT ITS PROMPT BEFORE THE LAUNCH IS TYPED. MEASURED
    # 2026-09-13 1:43 AM under load 40: the fresh zsh sat in its mise
    # prompt hook for two minutes, the typed launch waited in its input
    # buffer, and READY timed out. A probe echo proves the prompt.
    probe = f"NXB-SHELL-READY-{int(time.time() * 1000)}"
    send_line(pane, f"echo {probe}")
    end = time.monotonic() + max(exit_deadline, 60.0)
    while time.monotonic() < end and probe not in capture(pane):
        time.sleep(1.0)
    if probe not in capture(pane):
        return _refuse(RIG_RELAUNCH_UNCONFIRMED,
                       f"{name}'s shell never reached its prompt; nothing "
                       f"relaunched. (A slow shell hook under load looks "
                       f"like this.)", worker=name,
                       screen_tail=capture(pane).strip()[-300:])
    # 2. Launch fresh with the record's flags.
    spec = dict(entry)
    for key in ("resume_session_id", "resume_thread_id", "reason",
                "trust_scope"):
        spec.pop(key, None)
    if runtime == "claude_code":
        spec["session_id"] = str(uuid.uuid4())
        entry["session_id"] = spec["session_id"]
        if not spec.get("tools"):
            spec["tools"] = entry["tools"] = "core"
    entry["enrolment"] = None
    peers = list(state.get("peers") or [])
    cmd, enrolment, refusal = launch_command(spec, ledger=ledger, repo=repo,
                                             session=session, peers=peers)
    if refusal is not None:
        return refusal
    send_line(pane, cmd)
    ok, reason = await_ready(pane, runtime, deadline=ready_deadline)
    if not ok:
        entry.update(state="REFUSED", reason=reason)
        save_rig(ledger, session, state)
        return _refuse(reason or RIG_RELAUNCH_UNCONFIRMED,
                       f"{name} was relaunched but never reached READY.",
                       worker=name, screen_tail=capture(pane).strip()[-300:])
    entry.update(state="READY", launched_at=_utc_now(),
                 checkpoint_requested_at=None)
    if runtime == "claude_code":
        entry["enrolment"] = "launch"
        if entry.get("instructions"):
            entry["role_binding"] = "launch"
        refresh_session_ids([entry])
    elif not _name_and_enrol(entry, ledger=ledger, repo=repo, session=session,
                             peers=peers, name_deadline=name_deadline,
                             enrol_deadline=enrol_deadline):
        save_rig(ledger, session, state)
        return _refuse(entry.get("reason") or RIG_ENROLMENT_UNCONFIRMED,
                       f"{name} relaunched but was not enrolled.",
                       worker=name, screen_tail=capture(pane).strip()[-300:])
    save_rig(ledger, session, state)
    # 3. Continue what it holds.
    held = [t["task_id"] for t in outstanding_tasks(ledger, name)]
    _, note_path, mtime = _note_stat(ledger, session, name)
    note = note_path if mtime is not None else None
    orient = orientation_line(ledger, session,
                              entry.get("dir") or state.get("work_dir"))
    continued = None
    if held:
        body = (f"CONTINUATION of task {held[0]} after a relaunch of your "
                f"pane. Your previous context is gone. "
                + (f"Read your checkpoint note at {note} FIRST and continue "
                   f"from its exact next step; do not redo anything it lists "
                   f"as done. " if note else
                   f"Everything you wrote to disk stands: read the working "
                   f"tree's diff first and continue from there. ")
                + (f"You also hold {', '.join(held[1:])}. " if held[1:] else ""))
        send_line(pane, marked_directive(held[0], name, body, ledger=ledger,
                                         repo=repo, orientation=orient))
        continued = held[0]
    elif entry.get("role") == "orchestrator":
        send_line(pane, f"Operator note (nxb relaunch): your pane was "
                        f"relaunched with a fresh context. Read "
                        f"{note or 'your rig state note'} first, then the "
                        f"state note, and continue your plan.")
        continued = "plan"
    return {"state": "RELAUNCHED", "worker": name, "pane": pane,
            "session": session, "context_limit": entry.get("context_limit"),
            "effort": entry.get("effort"), "session_id": entry.get("session_id"),
            "thread_id": entry.get("thread_id"), "continued": continued,
            "note": note}


#: What a resumed pane with unfinished work is told, UNMARKED, when the
#: operator asks for it (`rig resume --continue`). One turn per such pane,
#: against re-dispatching a whole task to a fresh worker that then redoes it.
_CONTINUE_NOTE = (
    "Operator note (nxb resume, {when}): the host restarted and this session "
    "was resumed with its full context. Your task {ids} is still "
    "outstanding: continue it from exactly where you were. Everything you "
    "already wrote to disk stands; do not start over and do not redo "
    "finished steps. File with rig reply as the directive instructed, then "
    "print the done marker."
)


def resume(session, *, ledger, repo=None, work_dir=None, width=None,
           height=None, ready_deadline=60.0, name_deadline=30.0,
           enrol_deadline=90.0, reaffirm=False, continue_notes=False):
    """Bring a rig that went down back up ON ITS ORIGINAL CONVERSATIONS. [RIG-26]

    MEASURED on the Pact programme: two host restarts, and each time every
    pane was REBUILT from its draft -- 25 new threads with no memory of the
    work -- and the orchestrator was told to re-dispatch everything that had
    been in flight. Fresh workers then redid finished work from the start,
    which is the single most expensive thing a fleet can do. Both runtimes
    can resume a conversation by id (`codex resume <thread>`, `claude
    --resume <session>`; both verified to boot READY with the pane's name on
    2026-09-12), and the rig record holds those ids. So a rig is resumed,
    and the panes that held unfinished tasks are told so, rather than asked
    to start again.

    A pane with no recorded id (a record older than nxb-079, or one refused
    at launch) is relaunched fresh and reported as such. Nothing here is
    automatic at login: a resume is the operator's act, like a stand-up.
    """
    from nxb.keystroke import load_rig, outstanding_tasks, save_rig

    if shutil.which("tmux") is None:
        return _refuse(RIG_NO_TMUX, "tmux is not installed.")
    state = load_rig(ledger, session)
    if not state:
        return _refuse(RIG_NOT_RESUMABLE, f"no rig record for {session!r}.",
                       remedy=["python3 -m nxb rig up --session "
                               f"{session} --dir <work dir>"])
    if _tmux("has-session", "-t", _exact(session)).returncode == 0:
        return _refuse(RIG_SESSION_EXISTS,
                       f"{session!r} is standing; there is nothing to resume.",
                       remedy=[f"tmux attach -t {session}"])
    panes = [dict(p) for p in state.get("panes", []) if p.get("name")]
    if not any(_resume_id(p) for p in panes):
        return _refuse(RIG_NOT_RESUMABLE,
                       "the record holds no conversation ids to resume: it "
                       "predates nxb-079, or every pane was refused at launch.",
                       remedy=["rebuild it: python3 -m nxb rig up, or "
                               "Studio's Bring it to life"])
    repo = repo or state.get("repo") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    work_dir = os.path.expanduser(work_dir or state.get("work_dir") or "")
    pane_dirs = [os.path.expanduser(p.get("dir") or work_dir or "")
                 for p in panes]
    if any(not d for d in pane_dirs):
        return _refuse(RIG_NOT_RESUMABLE,
                       "the record does not say where the panes worked.",
                       remedy=["pass --dir <work dir>"])
    layout = state.get("layout") or "main-horizontal"
    pane_ids, refusal = _build_window(
        session, pane_dirs, layout,
        width=int(width or state.get("width") or 240),
        height=int(height or state.get("height") or 60))
    if refusal is not None:
        return refusal
    peers = list(state.get("peers") or [])

    problems = []
    for entry, pane, pane_dir in zip(panes, pane_ids, pane_dirs):
        entry.update(pane=pane, dir=pane_dir)
        entry.pop("reason", None)
        entry.pop("trust_scope", None)
        spec = dict(entry)
        if entry["runtime"] == "claude_code" and not entry.get("tools"):
            entry["tools"] = spec["tools"] = "core"
        rid = _resume_id(entry)
        if rid:
            spec["resume_thread_id" if entry["runtime"] == "codex"
                 else "resume_session_id"] = rid
            entry["mode"] = "resumed"
        else:
            if entry["runtime"] == "claude_code":
                spec["session_id"] = str(uuid.uuid4())
                entry["session_id"] = spec["session_id"]
            entry["enrolment"] = None
            entry["mode"] = "relaunched"
        cmd, enrolment, refusal = launch_command(
            spec, ledger=ledger, repo=repo, session=session, peers=peers)
        if refusal is not None:
            entry.update(state="REFUSED", reason=refusal["reason"])
            problems.append(entry)
            continue
        entry["enrolment_intended"] = enrolment
        send_line(pane, cmd)

    for entry in panes:
        if entry.get("state") == "REFUSED":
            continue
        ok, reason = await_ready(entry["pane"], entry["runtime"],
                                 deadline=ready_deadline)
        if not ok:
            entry.update(state="REFUSED", reason=reason,
                         screen_tail=capture(entry["pane"]).strip()[-300:])
            problems.append(entry)
            continue
        entry["state"] = "READY"
        if entry["mode"] == "resumed":
            if entry["runtime"] == "codex":
                # The resumed TUI prints the thread's name in its footer;
                # matched whitespace-stripped because narrow panes wrap it.
                entry["name_seen"] = (
                    re.sub(r"\s+", "", entry["name"]) in
                    re.sub(r"\s+", "", capture(entry["pane"])))
            entry["resumed_at"] = _utc_now()
            continue
        # A fresh pane: named and enrolled as at stand-up.
        entry["launched_at"] = _utc_now()
        if entry["runtime"] == "claude_code":
            entry["enrolment"] = "launch"
            if entry.get("instructions"):
                entry["role_binding"] = "launch"
        elif not _name_and_enrol(entry, ledger=ledger, repo=repo,
                                 session=session, peers=peers,
                                 name_deadline=name_deadline,
                                 enrol_deadline=enrol_deadline):
            problems.append(entry)

    if reaffirm:
        # The typed rule is in the resumed transcript, possibly 200K tokens
        # back. Re-typing it costs one turn per pane; the operator chooses.
        for entry in panes:
            if (entry.get("state") == "READY" and entry.get("mode") == "resumed"
                    and entry.get("enrolment") == "typed"):
                send_line(entry["pane"], _typed_rule(
                    entry, ledger=ledger, repo=repo, session=session,
                    peers=peers))
                entry["reaffirmed"] = await_ack(entry["pane"], entry["name"],
                                                deadline=enrol_deadline)
                if not entry["reaffirmed"]:
                    entry["enrolment"] = None

    _decorate(session, panes)
    state.update(panes=panes, peers=peers, layout=layout, repo=repo,
                 resumed_at=_utc_now())
    if work_dir:
        state["work_dir"] = work_dir
    save_rig(ledger, session, state)

    by_worker = {}
    for task in outstanding_tasks(ledger):
        by_worker.setdefault(task["worker"], []).append(task["task_id"])
    for entry in panes:
        entry["outstanding"] = by_worker.get(entry["name"], [])
    if continue_notes:
        import datetime
        when = datetime.datetime.now().strftime("%-I:%M %p")
        for entry in panes:
            if (entry.get("state") == "READY" and entry.get("mode") == "resumed"
                    and entry["outstanding"]):
                send_line(entry["pane"], _CONTINUE_NOTE.format(
                    when=when, ids=", ".join(entry["outstanding"])))
                entry["continued"] = True

    return {"state": "REFUSED" if problems else "RESUMED",
            "session": session, "peers": peers,
            "attach": f"tmux attach -t {session}",
            "resumed": [p["name"] for p in panes if p.get("mode") == "resumed"
                        and p.get("state") == "READY"],
            "relaunched": [p["name"] for p in panes
                           if p.get("mode") == "relaunched"
                           and p.get("state") == "READY"],
            "outstanding": {p["name"]: p["outstanding"] for p in panes
                            if p["outstanding"]},
            "panes": panes,
            **({"problems": [p["name"] for p in problems]} if problems else {}),
            "next": ("panes with outstanding tasks were told to continue"
                     if continue_notes else
                     "type, unmarked, into each pane that holds an "
                     "outstanding task: continue it from where you were; or "
                     "re-run with --continue to have nxb do that")}


def nudge(worker, message, *, ledger, session=None, min_interval_s=3600,
          force=False):
    """Type an UNMARKED operator note into a pane, with the guards a
    watcher script never had. [RIG-28]

    MEASURED on the Pact programme: a stall watcher typed thirteen "you have
    been silent" notes overnight, four of them into one pane inside thirty
    minutes, each a full-context turn, several into panes that were waiting
    correctly. So: never into a pane that is mid-turn, never twice inside
    the interval, and never into a pane that holds no task unless forced.
    """
    from nxb.keystroke import _resolve, load_rig, outstanding_tasks, save_rig
    import datetime

    pane, session, refusal = _resolve(worker, ledger, session)
    if refusal is not None:
        return refusal
    if _is_busy(capture(pane["pane"])):
        return _refuse(RIG_PANE_BUSY,
                       f"{worker} is mid-turn; a nudge would only queue "
                       f"behind the work it is asking about.")
    last = pane.get("last_nudge_at")
    if last and not force:
        try:
            then = datetime.datetime.fromisoformat(last)
            age = (datetime.datetime.now(datetime.timezone.utc) - then
                   ).total_seconds()
        except ValueError:
            age = None
        if age is not None and age < min_interval_s:
            return _refuse(RIG_NUDGE_THROTTLED,
                           f"{worker} was nudged {int(age // 60)} minutes "
                           f"ago; the interval is {min_interval_s // 60} "
                           f"minutes.",
                           remedy=["--force to override"])
    held = outstanding_tasks(ledger, worker)
    if not held and not force:
        return _refuse(RIG_NOTHING_TO_NUDGE,
                       f"{worker} holds no outstanding task; there is "
                       f"nothing to nudge it about.",
                       remedy=["--force to type it anyway"])
    when = datetime.datetime.now().strftime("%-I:%M %p")
    text = f"Operator note (nxb nudge, {when}): {' '.join(str(message).split())}"
    send_line(pane["pane"], text)
    state = load_rig(ledger, session)
    if state:
        for entry in state.get("panes", []):
            if entry.get("name") == worker:
                entry["last_nudge_at"] = _utc_now()
        save_rig(ledger, session, state)
    return {"state": "TYPED", "worker": worker, "pane": pane["pane"],
            "session": session, "outstanding": [t["task_id"] for t in held],
            "chars": len(text)}


def health(session, *, ledger):
    """One read-only look at a rig: who is alive, busy, blocked, or holding
    an unfiled task, and for how long. Types nothing, spends nothing.

    This is what a watcher should read before it decides to type anything.
    """
    from nxb.keystroke import load_rig, outstanding_tasks
    import datetime

    state = load_rig(ledger, session)
    if not state:
        return _refuse(KEYSTROKE_NO_RIG_REASON, f"no rig record for {session!r}.")
    standing = _tmux("has-session", "-t", _exact(session)).returncode == 0
    try:
        live = _live_panes(session) if standing else set()
    except RigTmuxError as exc:
        return _refuse("rig_tmux_unavailable", exc.detail)
    now = datetime.datetime.now(datetime.timezone.utc)
    held, healed = {}, False
    for task in outstanding_tasks(ledger):
        try:
            age = int((now - datetime.datetime.fromisoformat(
                task["issued_at"].replace("Z", "+00:00"))).total_seconds()
                // 60)
        except (ValueError, TypeError):
            age = None
        held.setdefault(task["worker"], []).append(
            {"task_id": task["task_id"], "age_min": age})
    widths = _pane_widths(session) if standing else {}
    panes = []
    for entry in state.get("panes", []):
        pane = entry.get("pane")
        alive = bool(pane and pane in live)
        screen = capture(pane) if alive else ""
        from nxb.gauge import fullness, pane_context
        before_id = entry.get("session_id")
        tokens, limit, fraction = fullness(entry)
        if entry.get("session_id") != before_id:
            # The gauge corrected a stale id from the registry; keep the
            # record honest so resume and usage follow it.
            healed = True
        item = {"name": entry.get("name"), "runtime": entry.get("runtime"),
                "role": entry.get("role", "worker"), "pane": pane,
                "alive": alive, "enrolled": bool(entry.get("enrolment")),
                "busy": _is_busy(screen) if alive else None,
                "width": widths.get(pane),
                "narrow": (widths.get(pane) is not None
                           and widths[pane] < NARROW_PANE_COLS),
                "blocked_on": next((r for n, r in BLOCKING_PROMPTS.items()
                                    if n in screen), None) if alive else None,
                "outstanding": held.get(entry.get("name"), []),
                "resumable": bool(_resume_id(entry)),
                "context_tokens": tokens, "context_limit": limit,
                "context_fraction": (round(fraction, 2)
                                     if fraction is not None else None),
                "context_reason": (None if fraction is not None else
                                   pane_context(entry).get("reason")),
                "last_nudge_at": entry.get("last_nudge_at"),
                "last_checkpoint_at": entry.get("last_checkpoint_at")}
        panes.append(item)
    if healed:
        from nxb.keystroke import save_rig
        save_rig(ledger, session, state)
    from nxb import machine
    return {"session": session, "standing": standing,
            "outstanding_total": sum(len(p["outstanding"]) for p in panes),
            "panes": panes,
            # THE MACHINE IS PART OF THE RIG'S HEALTH. A worker that is
            # alive, idle and not moving is either finished or swapping,
            # and only one of those is the rig's problem. [RIG-42]
            "machine": machine.snapshot(session) if standing else None}


#: `health` on an unknown rig uses the keystroke vocabulary's "no rig" term.
KEYSTROKE_NO_RIG_REASON = "keystroke_no_rig"


# =============================================================================
# nxb-082: checkpoint, then reset. Compaction you can read.
# =============================================================================

#: When a pane's context passes this fraction of its ceiling, `rig watch`
#: checkpoints it. Below the runtime's own compaction point on purpose: the
#: checkpoint must land before the vendor's summary does.
CHECKPOINT_THRESHOLD = 0.8
CHECKPOINT_MARKER = "[NXB-CHECKPOINT {name}]"
#: How long a pane may stay mid-turn AFTER confirming its note before the
#: pass gives up on resetting it this pass. The note is kept, and the next
#: pass finishes the reset without asking again. MEASURED 2026-09-12
#: (pact-dev): the lead confirmed a note in six passes running and was
#: refused rig_pane_busy six times, because the reset was tried two seconds
#: after the marker while the turn was still ending; each pass cost a full
#: 140K-context request and the lead reached 101 percent. [RIG-36]
CHECKPOINT_IDLE_DEADLINE_S = 120.0
#: A request typed this recently and not yet answered is PENDING: the pass
#: waits for it instead of typing another. MEASURED 2026-09-13 12:41 and
#: 12:47 AM: two passes each typed a request into Builder 2 while its turn
#: ran; both queued, then sat unsent in its composer behind an API error.
#: A second request never speeds up the first. [RIG-39]
CHECKPOINT_PENDING_S = 900.0
#: A confirmed note younger than this, with its marker still on screen, is
#: OWED a reset whatever the gauge says: the pane printed the marker and
#: stopped, as asked. MEASURED the same evening: Builder 2 printed its
#: marker a minute after the deadline, the next pass read it under the
#: threshold and skipped it, and it sat idle for twenty minutes. [RIG-36]
CHECKPOINT_NOTE_FRESH_S = 1800.0
#: How far ahead a pass projects a pane's context when deciding whether to
#: ask now: ONE watch interval. What the checkpoint itself then costs is
#: already reserved by `_effective_threshold`, and projecting past that as
#: well asked for the same headroom twice. MEASURED 2026-09-13: at four
#: minutes this rule checkpointed Builder 2 six times below its own
#: ask-line in eighty minutes. [RIG-46]
CHECKPOINT_HORIZON_S = 60.0
#: Below this fraction the rate rule is not applied. A pane with more than
#: half its ceiling free has room for one more pass whatever it is doing,
#: and an early checkpoint costs a full-context request to preserve a
#: context nobody needed preserved. MEASURED the same morning: Builder 1
#: rose from 0 to 43 percent in its first three minutes of a task, which
#: is a normal start, not an emergency.
CHECKPOINT_RATE_FLOOR = 0.5
#: How much context a pane spends BETWEEN being asked for a checkpoint and
#: being reset. Asking is not free and it is not instant: the pane finishes
#: whatever turn it was in, writes a note of up to 12,000 characters, files
#: it and prints its marker, and every one of those is a full-context
#: request. MEASURED twice on pact-dev 2026-09-13 from Builder 1's own
#: transcripts, on a 140K ceiling: asked at 100,503 it peaked at 143,970
#: before the reset, and asked at 114,055 it peaked at 146,631. A rise of
#: 43K and of 33K. A flat 80 percent threshold therefore lands a 140K pane
#: at about 145K and a 100K pane at about 115K, which is past the vendor's
#: own compaction point and is why 100K Opus panes were compacted four
#: times in one night (RIG-40).
CHECKPOINT_REQUEST_COST = 35_000
#: How long a pane must have been sitting cleared, holding a task, with a
#: note newer than its last reset, before a pass will continue it from that
#: note. Long enough that it cannot race a dispatch the operator or the
#: orchestrator has just typed and the model has not answered yet, and
#: short enough that a stranded worker is picked up on the next pass but
#: one. [RIG-45]
CONTINUATION_OWED_AFTER_S = 120.0


def _effective_threshold(limit, threshold):
    """The fraction at which a pane must be ASKED so that it is still under
    its ceiling when it is RESET. Never above the configured threshold, and
    never below CHECKPOINT_RATE_FLOOR, which would checkpoint a small-ceiling
    pane on every pass and preserve a context nobody needed. [RIG-44]"""
    if not limit:
        return threshold
    headroom = (limit - CHECKPOINT_REQUEST_COST) / float(limit)
    return min(threshold, max(CHECKPOINT_RATE_FLOOR, headroom))


def _checkpoint_request(entry, *, ledger, repo, key, outstanding):
    """The UNMARKED note that asks a pane to write its checkpoint."""
    import datetime
    from nxb.context import CHECKPOINT_CAP_CHARS, CHECKPOINT_HARD_CAP_CHARS
    when = datetime.datetime.now().strftime("%-I:%M %p")
    ids = ", ".join(outstanding) if outstanding else "none outstanding"
    return (f"Operator note (nxb checkpoint, {when}): your context is near "
            f"its ceiling. Before anything else, write a CHECKPOINT NOTE of "
            f"about {CHECKPOINT_CAP_CHARS} characters, never more than "
            f"{CHECKPOINT_HARD_CAP_CHARS} (if it runs long, cut whole "
            f"sections; never count characters), to a file and file it by "
            f"running exactly:\n"
            f"PYTHONPATH={repo} python3 -m nxb context put --key {key} "
            f"--file <path to the note> --ledger {ledger}\n"
            f"The note holds: the task id(s) you hold ({ids}); the goal in "
            f"one paragraph; decisions made and why; what is DONE, with exact "
            f"file paths and commit shas; what remains, as a numbered list; "
            f"and the exact next step. Then print on its own line exactly: "
            f"{CHECKPOINT_MARKER.format(name=entry['name'])} and stop. Your "
            f"pane will be reset onto that note and told to continue; "
            f"nothing on disk is lost.")


def _marker_on_screen(pane, name):
    wanted = re.sub(r"\s+", "", CHECKPOINT_MARKER.format(name=name))
    return wanted in re.sub(r"\s+", "", capture(pane))


def _note_stat(ledger, session, name):
    """(key, path, mtime_ns or None) of a pane's checkpoint note."""
    from nxb.context import Vault, checkpoint_key
    key = checkpoint_key(session, name)
    vault = Vault(ledger)
    try:
        path = vault.path_for(key)
    finally:
        vault.close()
    try:
        return key, path, os.stat(path).st_mtime_ns
    except OSError:
        return key, path, None


def _owed_reset(entry, *, ledger, session):
    """True when the pane has printed its marker and its note is newer than
    its last reset: it stopped as asked and is waiting for us."""
    import datetime
    name = entry["name"]
    _, _, mtime = _note_stat(ledger, session, name)
    if mtime is None:
        return False
    written = mtime / 1e9
    if time.time() - written > CHECKPOINT_NOTE_FRESH_S:
        return False
    last = entry.get("last_checkpoint_at")
    if last:
        try:
            stamp = datetime.datetime.fromisoformat(
                str(last).replace("Z", "+00:00")).timestamp()
        except ValueError:
            stamp = None
        if stamp is not None and written <= stamp:
            return False
    return _marker_on_screen(entry["pane"], name)


def _continuation_owed(entry, held, *, ledger, session):
    """True when this pane's clear landed but its continuation never did.

    DERIVED FROM STATE, NOT FROM A FLAG, on purpose: the pane that produced
    this finding was already stranded before there was a flag to set, and a
    recovery that only knows about faults recorded since it shipped is not
    a recovery. Every clause is something the rig can see now.

      - it holds a task, so there is something to continue;
      - it is not busy, so nothing is already running in it;
      - its gauge reads FRESH and NOTHING HAS BEEN ASKED of that session,
        which is what a cleared and abandoned pane looks like and is
        exactly what a pane mid-dispatch does not look like;
      - its checkpoint note is newer than its last recorded reset, so the
        note is the one written for this clear and not an older one;
      - and the note is at least CONTINUATION_OWED_AFTER_S old, so a
        dispatch typed seconds ago has time to land first.

    MEASURED 2026-09-13 1:37:56 PM: Builder 2 met all five for six minutes
    and every pass read it as PENDING and did nothing. [RIG-45]
    """
    if not held:
        return False
    pane = entry.get("pane")
    if not pane or _is_busy(capture(pane)):
        return False
    from nxb.gauge import pane_context
    reading = pane_context(entry)
    if not reading.get("fresh") or reading.get("asked"):
        return False
    _, _, mtime = _note_stat(ledger, session, entry["name"])
    if mtime is None:
        return False
    written, now = mtime / 1e9, time.time()
    if not (CONTINUATION_OWED_AFTER_S <= now - written
            <= CHECKPOINT_NOTE_FRESH_S):
        return False
    last = entry.get("last_checkpoint_at")
    if last:
        import datetime
        try:
            stamp = datetime.datetime.fromisoformat(
                str(last).replace("Z", "+00:00")).timestamp()
        except ValueError:
            stamp = None
        if stamp is not None and written <= stamp:
            return False
    return True


def _stamp_age_s(stamp):
    """Seconds since an ISO stamp on the record, or None."""
    import datetime
    if not stamp:
        return None
    try:
        then = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds()


def _mark_requested(entry, *, ledger, session, clear=False):
    """Record (or clear) the time a checkpoint request was typed."""
    from nxb.keystroke import load_rig, save_rig
    stamp = None if clear else _utc_now()
    state = load_rig(ledger, session) or {}
    for rec in state.get("panes", []):
        if rec.get("name") == entry.get("name"):
            rec["checkpoint_requested_at"] = stamp
    if state:
        save_rig(ledger, session, state)
    entry["checkpoint_requested_at"] = stamp


def _await_idle(pane, *, deadline=CHECKPOINT_IDLE_DEADLINE_S, poll=2.0,
                settled=2):
    """True once the pane has read idle `settled` polls in a row."""
    end = time.monotonic() + deadline
    quiet = 0
    while time.monotonic() < end:
        if _is_busy(capture(pane)):
            quiet = 0
        else:
            quiet += 1
            if quiet >= settled:
                return True
        time.sleep(poll)
    return False


def _rising_past_the_line(name, tokens, line, fraction, history,
                          horizon=CHECKPOINT_HORIZON_S):
    """Would waiting one more pass put this pane past the line anyway?

    THE THRESHOLD IS A LEVEL AND THE DANGER IS A RATE. MEASURED 2026-09-13
    on pact-dev: Builder 1 read 43 percent at 11:50:47, 72 percent at
    11:51:47 and 102 percent at 11:54:18. It crossed the 80 percent line
    entirely between two passes, so the level rule never saw it, and it was
    reset at 103 percent of a 140K ceiling, about 8K short of the vendor's
    own compaction point. A pane rising 40K a minute needs asking before it
    is over the line, not after.

    THE LINE IS THE ASK-LINE, NOT THE CEILING, and the horizon is ONE PASS.
    The first version of this rule projected to the ceiling over four
    minutes, which double-counted: `_effective_threshold` has already
    reserved 35K below the ceiling for what the ask itself costs, so
    demanding the pane also stay under the ceiling four minutes out asked
    for that headroom twice. MEASURED the same afternoon: it checkpointed
    Builder 2 six times below its own ask-line between 2:39 and 3:58 PM, at
    61, 68, 71, 70, 59 and 59 percent, each costing about 35K and several
    minutes. The question it asks now is the honest one: if I leave this
    pane for one more pass, will it be past the line I would ask at anyway?
    [RIG-43, corrected by RIG-46]

    Records this reading in `history`. Only above CHECKPOINT_RATE_FLOOR:
    below that the pane has room for another pass whatever it is doing.
    """
    now = time.monotonic()
    before = history.get(name) if history is not None else None
    if history is not None and tokens is not None:
        history[name] = (tokens, now)
    if (before is None or tokens is None or not line
            or fraction is None or fraction < CHECKPOINT_RATE_FLOOR):
        return False
    was, at = before
    elapsed = now - at
    if elapsed <= 0 or tokens <= was:
        return False
    rate = (tokens - was) / elapsed
    return tokens + rate * horizon >= line


def _plan_checkpoint(entry, *, session, ledger, threshold, force,
                     history=None):
    """What one pane needs this pass: 'finish' (owed a reset), 'request'
    (over the line or rising past it), or 'skip' (with the result)."""
    from nxb.gauge import fullness
    from nxb.keystroke import outstanding_tasks
    name = entry["name"]
    tokens, limit, fraction = fullness(entry)
    held = [t["task_id"] for t in outstanding_tasks(ledger, name)]
    key, note_path, before = _note_stat(ledger, session, name)
    threshold = _effective_threshold(limit, threshold)
    rising = _rising_past_the_line(name, tokens, (limit or 0) * threshold,
                                   fraction, history)
    base = {"worker": name, "context_tokens": tokens, "context_limit": limit,
            "context_fraction": fraction, "threshold": round(threshold, 3)}
    if rising:
        base["rising"] = True
    if _owed_reset(entry, ledger=ledger, session=session):
        return {"action": "finish", "held": held, "note_path": note_path,
                "reused": True, **base}
    # Checked BEFORE the pending stamp: a pane stranded by an unproven
    # clear still carries the stamp of the request that cleared it, and
    # waiting fifteen minutes for that to age out is the bug. [RIG-45]
    if _continuation_owed(entry, held, ledger=ledger, session=session):
        return {"action": "continue", "held": held, "note_path": note_path,
                "stranded": True, **base}
    asked = _stamp_age_s(entry.get("checkpoint_requested_at"))
    if asked is not None and asked < CHECKPOINT_PENDING_S and not force:
        return {"action": "skip", "result": {
            "state": "PENDING", **base,
            "detail": (f"a checkpoint request typed {asked // 60} min ago "
                       f"is not answered yet; waiting, not asking again")}}
    if not force and not rising and (fraction is None or fraction < threshold):
        if fraction is None:
            # WHY it is unknown is the whole value of the reading. MEASURED
            # 2026-09-13: two watch lines read "Builder 2=?" and there was
            # no way afterwards to tell which branch of the gauge produced
            # them, so the same "?" had to be diagnosed from scratch. The
            # gauge already knows; carry it. [RIG-41]
            from nxb.gauge import pane_context
            base["context_reason"] = pane_context(entry).get("reason")
        return {"action": "skip", "result": {
            "state": "SKIPPED", **base,
            "detail": ("below the threshold" if fraction is not None
                       else f"context unknown: {base.get('context_reason')}")}}
    if not held and entry.get("role") != "orchestrator" and not force:
        # A worker with nothing outstanding has just filed, or never
        # started: its next dispatch resets it for free. Checkpointing it
        # would spend a full-context turn to preserve a context nobody
        # will continue. MEASURED 2026-09-12: Builder 2 crossed 88 percent
        # in the same minute it filed.
        return {"action": "skip", "result": {
            "state": "SKIPPED", **base,
            "detail": "no outstanding task; the next dispatch resets "
                      "this pane"}}
    return {"action": "request", "held": held, "key": key,
            "note_path": note_path, "before": before, "reused": False,
            **base}


def _confirmed(entry, plan):
    path, before = plan["note_path"], plan.get("before")
    written = (os.path.exists(path) and
               os.stat(path).st_mtime_ns != before)
    return written and _marker_on_screen(entry["pane"], entry["name"])


def _finish_checkpoint(entry, plan, *, session, ledger, repo):
    """The pane has a confirmed note: wait for it to go idle, clear it, and
    set it going again on the same task id."""
    from nxb.context import orientation_line
    from nxb.keystroke import load_rig, marked_directive, save_rig
    name, pane = entry["name"], entry["pane"]
    held, note_path = plan["held"], plan["note_path"]
    if not _await_idle(pane):
        return _refuse(RIG_PANE_BUSY,
                       f"{name} confirmed its checkpoint but stayed mid-turn "
                       f"for {int(CHECKPOINT_IDLE_DEADLINE_S)} s; the note is "
                       f"kept and the next pass finishes the reset without "
                       f"asking again.",
                       worker=name, checkpoint=note_path, confirmed=True)
    reset = reset_pane(entry, session=session, ledger=ledger, repo=repo)
    if reset.get("state") != "RESET":
        # AN UNPROVEN CLEAR IS NOT AN UNSENT ONE. MEASURED 2026-09-13
        # 1:37:56 PM on pact-dev: the clear was typed, the session id did
        # not rotate inside the 20 s proof window under 11 GB of swap, this
        # refused as designed and typed nothing more, and the clear landed a
        # moment later. Builder 2 was left empty, idle and holding a task
        # nothing would ever continue. Record that the reset is owed and
        # drop the pending stamp, so the next pass is free to check whether
        # the clear landed and finish the job. [RIG-45]
        if reset.get("reason") == RIG_RESET_UNCONFIRMED:
            _mark_requested(entry, ledger=ledger, session=session, clear=True)
            _note_unproven_reset(entry, ledger=ledger, session=session)
        reset.update(checkpoint=note_path, worker=name, confirmed=True)
        return reset
    return _continue_from_note(entry, held, note_path, session=session,
                               ledger=ledger, repo=repo,
                               reset=reset.get("state"),
                               reused=bool(plan.get("reused")),
                               gauge=plan)


def _note_unproven_reset(entry, *, ledger, session):
    """Stamp the record: a clear was typed into this pane and not proven."""
    from nxb.keystroke import load_rig, save_rig
    stamp = _utc_now()
    state = load_rig(ledger, session) or {}
    for rec in state.get("panes", []):
        if rec.get("name") == entry["name"]:
            rec["reset_unproven_at"] = stamp
    if state:
        save_rig(ledger, session, state)
    entry["reset_unproven_at"] = stamp


def _continue_from_note(entry, held, note_path, *, session, ledger, repo,
                        reset=None, reused=False, gauge=None):
    """Set a freshly cleared pane going again on its own checkpoint note.

    The second half of a reset, split out because it is owed in two
    different situations: straight after a proven clear, and to a pane
    whose clear landed after the proof window closed. [RIG-45]
    """
    from nxb.context import orientation_line
    from nxb.keystroke import load_rig, marked_directive, save_rig
    name, pane = entry["name"], entry["pane"]
    gauge = gauge or {}
    state = load_rig(ledger, session) or {}
    work_dir = entry.get("dir") or state.get("work_dir")
    orient = orientation_line(ledger, session, work_dir)
    continued = None
    if held:
        body = (f"CONTINUATION of task {held[0]} after a context checkpoint. "
                f"Your previous context was reset. Read your checkpoint note "
                f"at {note_path} FIRST and continue from its exact next step; "
                f"do not redo anything it lists as done. "
                + (f"You also hold {', '.join(held[1:])}. " if held[1:] else ""))
        send_line(pane, marked_directive(held[0], name, body, ledger=ledger,
                                         repo=repo, orientation=orient))
        continued = held[0]
    elif entry.get("role") == "orchestrator":
        send_line(pane, f"Operator note (nxb checkpoint): your context was "
                        f"reset after a checkpoint. Read {note_path} first, "
                        f"then your rig's state note, and continue your plan "
                        f"from the checkpoint's next step.")
        continued = "plan"
    # THE STAMP IS WRITTEN ON A FRESH LOAD AND MIRRORED INTO THE CALLER'S
    # ENTRY. MEASURED 2026-09-12: three real checkpoints and `rig health`
    # showed last_checkpoint_at null for every pane, because the pass saved
    # its own stale copy of the record afterwards. [RIG-36]
    stamp = _utc_now()
    for rec in state.get("panes", []):
        if rec.get("name") == name:
            rec["last_checkpoint_at"] = stamp
            rec["checkpoint_requested_at"] = None
            rec["reset_unproven_at"] = None
            entry["checkpoint_requested_at"] = None
            entry["reset_unproven_at"] = None
            # How many checkpoints THIS task has cost; collect logs it.
            if held and rec.get("checkpoint_task") == held[0]:
                rec["checkpoints"] = int(rec.get("checkpoints") or 0) + 1
            elif held:
                rec["checkpoint_task"], rec["checkpoints"] = held[0], 1
            entry["checkpoint_task"] = rec.get("checkpoint_task")
            entry["checkpoints"] = rec.get("checkpoints")
    if state:
        save_rig(ledger, session, state)
    entry["last_checkpoint_at"] = stamp
    return {"state": "CHECKPOINTED", "worker": name, "note": note_path,
            "context_tokens": gauge.get("context_tokens"),
            "context_limit": gauge.get("context_limit"),
            "context_fraction": gauge.get("context_fraction"),
            "reset": reset, "continued": continued, "reused_note": reused}


def checkpoint_pane(entry, *, session, ledger, repo=None,
                    threshold=CHECKPOINT_THRESHOLD, force=False,
                    deadline=300.0):
    """Checkpoint ONE pane to the vault, reset it, and set it going again.

    The pane writes the note itself (it is the only party that knows what
    matters), nxb verifies the note exists and the marker printed, and only
    then clears the pane and types the continuation: a MARKED directive
    carrying the SAME task id for a worker mid-task (its rule validates the
    id, which is still issued and unrevoked), or an unmarked note for an
    orchestrator. Nothing is reset on an unconfirmed checkpoint. [RIG-31]

    A pane whose marker is on screen over a fresh note is owed the reset and
    is never asked again; a pane still mid-turn after confirming keeps its
    note for the next pass. [RIG-36]
    """
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plan = _plan_checkpoint(entry, session=session, ledger=ledger,
                            threshold=threshold, force=force)
    if plan["action"] == "skip":
        return plan["result"]
    if plan["action"] == "request":
        send_line(entry["pane"],
                  _checkpoint_request(entry, ledger=ledger, repo=repo,
                                      key=plan["key"], outstanding=plan["held"]),
                  settle=3.5)
        _mark_requested(entry, ledger=ledger, session=session)
        end = time.monotonic() + deadline
        while not _confirmed(entry, plan):
            if time.monotonic() >= end:
                return _refuse(RIG_CHECKPOINT_UNCONFIRMED,
                               f"{entry['name']} did not confirm a checkpoint "
                               f"within {int(deadline)} s; the pane was NOT "
                               f"reset.",
                               worker=entry["name"], note=plan["note_path"],
                               context_fraction=plan.get("context_fraction"),
                               screen_tail=capture(entry["pane"]).strip()[-300:])
            time.sleep(3.0)
        time.sleep(2.0)
    return _finish_checkpoint(entry, plan, session=session, ledger=ledger,
                              repo=repo)


def checkpoint_rig(session, *, ledger, worker=None,
                   threshold=CHECKPOINT_THRESHOLD, force=False,
                   deadline=300.0, history=None):
    """One pass over a rig: checkpoint every pane over the threshold.

    Requests go to EVERY full pane before any waiting, and one deadline
    covers them all. MEASURED 2026-09-12: with one 300 s wait per pane in
    turn, a pass sat five minutes on Builder 1 and five on Builder 2 while
    the rig went unwatched; Builder 1 reached 104 percent and Builder 2
    reached 108 and was compacted by the vendor. [RIG-36]
    """
    from nxb.keystroke import load_rig, save_rig
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state = load_rig(ledger, session)
    if not state:
        return _refuse("keystroke_no_rig", f"no rig record for {session!r}.")
    try:
        live = _live_panes(session)
    except RigTmuxError as exc:
        return _refuse("rig_tmux_unavailable", exc.detail)
    results, plans, ids_before = {}, [], {}
    for entry in state.get("panes", []):
        name = entry.get("name")
        if worker and name != worker:
            continue
        if entry.get("pane") not in live:
            results[name] = {"state": "SKIPPED", "worker": name,
                             "detail": "pane not alive"}
            continue
        ids_before[name] = entry.get("session_id")
        try:
            plan = _plan_checkpoint(entry, session=session, ledger=ledger,
                                    threshold=threshold, force=force,
                                    history=history)
        except Exception as exc:                               # noqa: BLE001
            results[name] = _refuse("rig_checkpoint_error",
                                    f"{name}: {type(exc).__name__}: {exc}",
                                    worker=name)
            continue
        if plan["action"] == "skip":
            results[name] = plan["result"]
            continue
        if plan["action"] == "continue":
            try:
                results[name] = _continue_from_note(
                    entry, plan["held"], plan["note_path"], session=session,
                    ledger=ledger, repo=repo, reset="STRANDED", gauge=plan)
                results[name]["stranded"] = True
            except Exception as exc:                           # noqa: BLE001
                results[name] = _refuse("rig_checkpoint_error",
                                        f"{name}: {type(exc).__name__}: {exc}",
                                        worker=name)
            continue
        if plan["action"] == "request":
            send_line(entry["pane"],
                      _checkpoint_request(entry, ledger=ledger, repo=repo,
                                          key=plan["key"],
                                          outstanding=plan["held"]),
                      settle=3.5)
            _mark_requested(entry, ledger=ledger, session=session)
        plans.append((entry, plan))
    # Phase two: one clock for every request.
    end = time.monotonic() + deadline
    waiting = [(e, p) for e, p in plans if p["action"] == "request"]
    while waiting and time.monotonic() < end:
        waiting = [(e, p) for e, p in waiting if not _confirmed(e, p)]
        if waiting:
            time.sleep(3.0)
    unconfirmed = {e["name"] for e, _ in waiting}
    if plans and not waiting:
        time.sleep(2.0)
    # Phase three: reset what confirmed, in order.
    for entry, plan in plans:
        name = entry["name"]
        if name in unconfirmed:
            results[name] = _refuse(
                RIG_CHECKPOINT_UNCONFIRMED,
                f"{name} did not confirm a checkpoint within {int(deadline)} "
                f"s; the pane was NOT reset. If it prints its marker later, "
                f"the next pass finishes the reset without asking again.",
                worker=name, note=plan["note_path"],
                context_fraction=plan.get("context_fraction"),
                screen_tail=capture(entry["pane"]).strip()[-300:])
            continue
        try:
            results[name] = _finish_checkpoint(entry, plan, session=session,
                                               ledger=ledger, repo=repo)
        except Exception as exc:                               # noqa: BLE001
            results[name] = _refuse("rig_checkpoint_error",
                                    f"{name}: {type(exc).__name__}: {exc}",
                                    worker=name)
    # A HEALED SESSION ID IS MERGED INTO A FRESH LOAD, never saved from the
    # copy this pass started with: resets and stamps wrote the record in
    # the meantime, and the stale copy erased them. [RIG-36]
    healed = {e.get("name"): e.get("session_id") for e in state.get("panes", [])
              if e.get("name") in ids_before
              and e.get("session_id") != ids_before[e.get("name")]}
    if healed:
        fresh = load_rig(ledger, session) or state
        for rec in fresh.get("panes", []):
            if rec.get("name") in healed:
                rec["session_id"] = healed[rec["name"]]
        save_rig(ledger, session, fresh)
    ordered = [results[e.get("name")] for e in state.get("panes", [])
               if e.get("name") in results]
    return {"state": "PASS", "session": session, "panes": ordered,
            "checkpointed": [p["worker"] for p in ordered
                             if p.get("state") == "CHECKPOINTED"]}


#: A worker holding a task whose transcript has been still this long, with
#: no turn on screen, is named in the watcher's line. [RIG-38]
STALL_AFTER_S = 600


def _stalls(session, *, ledger):
    """['Builder 2 (11 min, nxbt-…)', ...]: workers holding a task, idle."""
    from nxb.keystroke import last_activity_s, load_rig, outstanding_tasks
    state = load_rig(ledger, session) or {}
    try:
        live = _live_panes(session)
    except RigTmuxError:
        return []
    found = []
    for entry in state.get("panes", []):
        if entry.get("pane") not in live:
            continue
        held = outstanding_tasks(ledger, entry.get("name"))
        if not held or _is_busy(capture(entry["pane"])):
            continue
        age = last_activity_s(entry)
        if age is not None and age >= STALL_AFTER_S:
            short = str(entry.get("name")).split(" ", 1)[-1]
            found.append(f"{short} ({age // 60} min, {held[0]['task_id']})")
    return found


def watch(session, *, ledger, interval=60, threshold=CHECKPOINT_THRESHOLD,
          once=False, out=None):
    """The watcher a fleet should have had: read the gauge, checkpoint what
    is over the line, type nothing else. `once` makes it a single pass."""
    import datetime
    from nxb import machine
    out = out or (lambda line: print(line, flush=True))
    # A CONSTANT COMPLAINT IS NOT A REPORT. Narrow panes persist for as long
    # as the operator's terminal is attached, so the watcher names them when
    # the set CHANGES and then stops, instead of printing the same grievance
    # sixty times an hour. [RIG-42]
    narrow_before = None
    # The gauge history lives with the LOOP, not in the ledger: it is only
    # meaningful between consecutive passes at a known interval, and three
    # database writes a minute to hold two numbers is a worse trade than
    # losing them when the watcher restarts. [RIG-43]
    history = {}
    while True:
        stamp = datetime.datetime.now().strftime("%-I:%M:%S %p")
        # A WATCHER THAT DIES IS WORSE THAN NO WATCHER: the operator believes
        # it is standing guard. MEASURED 2026-09-12: the first watcher on
        # pact-dev died on a KeyError while summarising a refused
        # checkpoint, and the pane it was guarding sailed to 106K. Every
        # pass is now contained, and a refusal is reported, not raised.
        try:
            report = checkpoint_rig(session, ledger=ledger,
                                    threshold=threshold, history=history)
        except Exception as exc:                               # noqa: BLE001
            out(f"{stamp} {session}: pass failed: {type(exc).__name__}: {exc}")
            report = {"state": "ERROR", "detail": str(exc)}
        if report.get("state") != "PASS":
            out(f"{stamp} {session}: {report.get('reason', report.get('state'))} "
                f"{report.get('detail')}")
        else:
            gauges, refused = [], []
            for p in report["panes"]:
                name = str(p.get("worker") or "?").split(" ", 1)[-1]
                frac = p.get("context_fraction")
                if frac is None:
                    why = p.get("context_reason")
                    gauges.append(f"{name}=?" + (f" ({why})" if why else ""))
                else:
                    gauges.append(f"{name}={frac:.0%}"
                                  + ("(rising)" if p.get("rising") else ""))
                if p.get("state") == "REFUSED":
                    refused.append(f"{name}: {p.get('reason')}")
                elif p.get("state") == "PENDING":
                    refused.append(f"{name}: request pending")
            done = [p["worker"]
                    + (" [stranded, continued from its note]"
                       if p.get("stranded") else
                       " (from its note)" if p.get("reused_note") else "")
                    for p in report["panes"] if p.get("state") == "CHECKPOINTED"]
            try:
                stalled = _stalls(session, ledger=ledger)
            except Exception as exc:                           # noqa: BLE001
                stalled = [f"stall check failed: {type(exc).__name__}"]
            try:
                snap = machine.snapshot(session)
                widths = _pane_widths(session)
            except Exception as exc:                           # noqa: BLE001
                snap, widths = {}, {}
                out(f"{stamp} {session}: machine read failed: "
                    f"{type(exc).__name__}")
            narrow_now = {pane: cols for pane, cols in widths.items()
                          if cols is not None and cols < NARROW_PANE_COLS}
            # The FIRST pass reports narrow panes too: a watcher restarted
            # into an already squeezed rig would otherwise adopt the fault
            # as its baseline and never mention it.
            if narrow_now != (narrow_before or {}) and (narrow_now
                                                        or narrow_before):
                where = ", ".join(f"{pane} {cols} cols" for pane, cols
                                  in sorted(narrow_now.items())) or "none"
                seen = ", ".join(f"{c['width']}x{c['height']}"
                                 for c in snap.get("clients") or []) or "none"
                out(f"{stamp} {session}: narrow panes: {where} "
                    f"(clients attached: {seen})")
            narrow_before = narrow_now
            body = machine.line(snap) if snap else ""
            out(f"{stamp} {session}: " + " ".join(gauges)
                + (f" | checkpointed: {', '.join(done)}" if done else "")
                + (f" | refused: {'; '.join(refused)}" if refused else "")
                + (f" | stalled: {'; '.join(stalled)}" if stalled else "")
                + (f" | {body}" if body else ""))
        if once:
            return report
        time.sleep(max(10, int(interval)))


def usage(session, *, ledger):
    """What each pane of a rig has spent, from the runtimes' own transcripts.

    The monitoring readout for a running workflow: requests, uncached input,
    cache reads, output and the largest context seen, per pane, read from
    the same files the gauge reads. Costs no tokens. Compare against the
    measured Pact numbers in docs/CONTEXT-BUDGET-nxb-079.md (about 43
    requests at 125K context per task, orchestrators at the 244K window).
    """
    import json
    from nxb.gauge import _claude_transcript, _codex_rollout
    from nxb.keystroke import load_rig
    state = load_rig(ledger, session)
    if not state:
        return _refuse("keystroke_no_rig", f"no rig record for {session!r}.")
    panes, total = [], {"requests": 0, "uncached": 0, "cache_read": 0,
                        "output": 0}
    for entry in state.get("panes", []):
        row = {"name": entry.get("name"), "runtime": entry.get("runtime"),
               "requests": 0, "uncached": 0, "cache_read": 0, "output": 0,
               "max_context": 0, "transcript": None}
        if entry.get("runtime") == "claude_code":
            path = _claude_transcript(entry.get("session_id") or "")
            if path:
                row["transcript"] = path
                # ONE RECORD PER REQUEST. MEASURED 2026-09-12: a Claude
                # transcript writes one assistant record per content block
                # (thinking, text, each tool_use), every one carrying the
                # same usage; summing them overcounted a pane's cache reads
                # about three times over. Dedupe on requestId.
                seen = set()
                with open(path, errors="replace") as handle:
                    for line in handle:
                        if '"usage"' not in line:
                            continue
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        usage_ = (record.get("message") or {}).get("usage")
                        if not isinstance(usage_, dict):
                            continue
                        key = (record.get("requestId")
                               or (record.get("message") or {}).get("id"))
                        if key is not None:
                            if key in seen:
                                continue
                            seen.add(key)
                        i = usage_.get("input_tokens") or 0
                        cr = usage_.get("cache_read_input_tokens") or 0
                        cw = usage_.get("cache_creation_input_tokens") or 0
                        if i + cr + cw == 0:
                            continue
                        row["requests"] += 1
                        row["uncached"] += i + cw
                        row["cache_read"] += cr
                        row["output"] += usage_.get("output_tokens") or 0
                        row["max_context"] = max(row["max_context"], i + cr + cw)
        elif entry.get("runtime") == "codex":
            path = _codex_rollout(entry.get("thread_id") or "")
            if path:
                row["transcript"] = path
                with open(path, errors="replace") as handle:
                    for line in handle:
                        if "token_count" not in line:
                            continue
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        payload = record.get("payload") or {}
                        if payload.get("type") != "token_count":
                            continue
                        last = (payload.get("info") or {}).get(
                            "last_token_usage") or {}
                        i = last.get("input_tokens") or 0
                        if not i:
                            continue
                        c = last.get("cached_input_tokens") or 0
                        row["requests"] += 1
                        row["uncached"] += i - c
                        row["cache_read"] += c
                        row["output"] += last.get("output_tokens") or 0
                        row["max_context"] = max(row["max_context"], i)
        for key in total:
            total[key] += row[key]
        panes.append(row)
    return {"state": "USAGE", "session": session, "panes": panes,
            "total": total,
            "note": ("a /clear rotates a Claude session id; a pane's earlier "
                     "sessions are not summed here, the current one is")}
