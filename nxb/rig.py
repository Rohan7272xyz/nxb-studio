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
import shutil
import subprocess
import time

from nxb.enroll import (ACK, enroll_command, typed_enrolment_rule,
                        typed_orchestrator_rule)

#: Published refusals. See contract/rig.json.
RIG_NO_TMUX = "rig_no_tmux"
RIG_SESSION_EXISTS = "rig_session_exists"
RIG_UNKNOWN_SCENARIO = "rig_unknown_scenario"
RIG_PANE_NOT_READY = "rig_pane_not_ready"
RIG_TRUST_PROMPT = "rig_trust_prompt"
RIG_NAME_NOT_RESOLVABLE = "rig_name_not_resolvable"
RIG_ENROLMENT_UNCONFIRMED = "rig_enrolment_unconfirmed"
RIG_UPDATE_PROMPT = "rig_update_prompt"

#: What a READY pane shows. Absence of the marker is failure, never a reason to
#: proceed hopefully: this is F-14's rule applied to a screen instead of a file.
#: MEASURED, not guessed. Each string was read off a real booted pane on
#: 2026-08-28; the first set I wrote from memory matched neither runtime and
#: every Claude pane timed out as "not ready" while sitting at a trust dialog.
READY_MARKERS = {
    "codex": ("Ask Codex to do anything",),
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
def model_flags(runtime, model=None, effort=None):
    out = []
    if runtime == "claude_code":
        if model:
            out += ["--model", str(model)]
        if effort:
            out += ["--effort", str(effort)]
    elif runtime == "codex":
        if model:
            out += ["-m", str(model)]
        if effort:
            out += ["-c", f'model_reasoning_effort="{effort}"']
    return out


def compose_agents(agents, *, layout="main-horizontal"):
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
        for key in ("model", "effort", "dir", "instructions"):
            if a.get(key):
                pane[key] = a[key]
        panes.append(pane)
    if orchestrators > 1:
        raise ValueError("a rig has at most one orchestrator")
    return {"description": f"{len(panes)} agents, composed",
            "layout": layout, "panes": panes}


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


def send_line(pane, text, *, settle=0.5):
    """Type a line, then submit it as a SEPARATE keystroke.

    MEASURED: sending the text and Enter in one `send-keys` call leaves the
    text sitting un-submitted in Codex's composer. Its slash-command popup
    opens as `/rename` is typed and eats the Enter that arrives in the same
    burst. My hand-run worked only because I happened to pause between the two.
    So the pause is the mechanism, not a politeness, and it is why the rig
    verifies submission rather than assuming it.
    """
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


def launch_command(spec, *, ledger, repo, sandbox=None, session="nxb"):
    """The shell line for one pane. Returns (command, enrolment_kind, refusal).

    `enrolment_kind` is "launch", "typed" or None -- never a boolean. A
    launch-bound rule and a typed one are different KINDS of barrier and a
    boolean would erase exactly the difference that matters.
    """
    if spec["runtime"] == "claude_code":
        # Named AND enrolled before it renders a frame: -n sets the display
        # name at launch and the rule is bound at the same moment, so there is
        # no window in which the pane is anonymous or unenrolled.
        cmd, refusal = enroll_command(
            spec["name"], ledger=ledger, repo=repo,
            role=spec.get("role", "worker"), session=session,
            model=spec.get("model"), effort=spec.get("effort"),
            instructions=spec.get("instructions"))
        return cmd, "launch", refusal
    if spec["runtime"] == "codex":
        # No --append-system-prompt and no --name: named by /rename after
        # launch, and enrolled by TYPING the rule in once it is named.
        # `sandbox` remains an explicit opt-in: passing one is a deliberate
        # choice to give a Codex pane LESS than the fleet's declared posture,
        # and it is recorded in the command the operator can read on screen.
        flag = f"--sandbox {sandbox}" if sandbox else CODEX_YOLO
        extra = model_flags("codex", spec.get("model"), spec.get("effort"))
        return " ".join(["codex", flag, *extra]), "typed", None
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
             name_deadline=30.0, enrol_deadline=90.0):
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
    created = _tmux("new-session", "-d", "-s", session, "-c", pane_dirs[0],
                    "-x", str(width), "-y", str(height))
    if created.returncode != 0:
        return _refuse(RIG_NO_TMUX,
                       f"tmux new-session failed: {created.stderr.strip()}")

    # Panes run a SHELL and are then typed into, rather than having the runtime
    # as the pane process. A runtime that dies then leaves its error on screen
    # instead of taking the pane with it, which is the difference between a
    # debuggable rig and a vanishing one.
    pane_ids = [_tmux("list-panes", "-t", _exact(session),
                      "-F", "#{pane_id}").stdout.split()[0]]
    for index in range(1, len(plan["panes"])):
        made = _tmux("split-window", "-t", _exact_window(session),
                     "-c", pane_dirs[index], "-P", "-F", "#{pane_id}")
        if made.returncode != 0:
            return _refuse(RIG_NO_TMUX,
                           f"split-window failed: {made.stderr.strip()}")
        pane_ids.append(made.stdout.strip())
    _tmux("select-layout", "-t", _exact_window(session), plan["layout"])

    panes, problems = [], []
    for spec, pane in zip(plan["panes"], pane_ids):
        spec = dict(spec, name=scoped_name(session, spec["name"]))
        cmd, enrolment, refusal = launch_command(
            spec, ledger=ledger, repo=repo, session=session)
        entry = {"name": spec["name"], "runtime": spec["runtime"],
                 "role": spec["role"], "pane": pane,
                 **{k: spec[k] for k in ("model", "effort", "instructions")
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
            entry.update(state="REFUSED", reason=reason,
                         screen_tail=capture(entry["pane"]).strip()[-300:])
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
            rule = (typed_orchestrator_rule(entry["name"], ledger=ledger,
                                            repo=repo, session=session)
                    if entry.get("role") == "orchestrator"
                    else typed_enrolment_rule(entry["name"], ledger=ledger,
                                              repo=repo))
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

    # STARTUP INSTRUCTIONS, typed last and deliberately UNMARKED.
    #
    # They are the operator briefing his own pane, so they arrive the way he
    # would type them: no marker, no task id. Marking them would be a lie --
    # the marker means "automated directive, validate before acting" and this
    # is not one -- and it would also make a worker refuse its own setup for
    # want of a task id nobody minted.
    #
    # Typed AFTER enrolment so the enrolment rule is in place first, and only
    # for panes that actually came up: briefing a refused pane types into
    # whatever is on that screen.
    for entry in panes:
        text = entry.get("instructions")
        if not text or entry.get("state") != "READY":
            continue
        if entry["runtime"] == "claude_code":
            # Already bound in its system prompt at launch, which is the
            # stronger form. Typing it again would only add a message that
            # can be argued with.
            entry["role_binding"] = "launch"
            continue
        send_line(entry["pane"], f"STANDING ROLE FOR THIS SESSION, from your "
                                 f"operator: {' '.join(str(text).split())} "
                                 f"This applies to every message from now on.")
        entry["role_binding"] = "typed"

    report = {"state": "REFUSED" if problems else "READY",
              "scenario": scenario, "session": session,
              "attach": f"tmux attach -t {session}",
              "panes": panes,
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
        rule = (typed_orchestrator_rule(entry["name"], ledger=ledger,
                                        repo=repo, session=session)
                if entry.get("role") == "orchestrator"
                else typed_enrolment_rule(entry["name"], ledger=ledger,
                                          repo=repo))
        send_line(pane, rule)
        if await_ack(pane, entry["name"], deadline=enrol_deadline):
            re_enrolled.append(entry["name"])
        else:
            entry["enrolment"] = None
            unprotected.append(entry["name"])

    if state is not None and ledger:
        save_rig(ledger, session, {"session": session,
                                   "panes": list(known.values())})
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
