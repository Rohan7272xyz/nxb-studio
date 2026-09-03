"""The roster: the human-owned population of workers, and its refusal.

Rohan's design. He spawns and names panes himself; the broker DISCOVERS that
roster; the orchestrator dispatches to those live named workers. If he asks for
three and only two exist, THE BROKER REFUSES, and that refusal is what makes
the orchestrator ask him whether to create the third.

**His roster is the ceiling. No agent runs that he did not invoke and name.**
That is a refusal rather than an obligation to emit, which is why it lives in
the mechanism instead of in anyone's good behaviour.

TWO MEASURED FACTS SHAPE THIS, both taken on 2026-08-28:

1. **Socket existence is not liveness, and the gap is not small.** 26 sockets
   were present and only 12 answered: FOURTEEN WERE STALE. A roster built on
   existence would have offered more dead workers than live ones, which is
   worse than refusing, because the orchestrator would dispatch into silence.
   Liveness is `connect()`. Not `ps` on the pid in the filename either: pids
   are recycled, so a stale socket whose number now belongs to an unrelated
   process reads as alive.

2. **A socket does not yield a NAME**, but the session registry does.
   The socket filenames are pids and no name appears on the process command
   line, so for one task this roster was live, addressable and UNNAMED. The
   source turned out to be `~/.claude/sessions/<pid>.json`, which carries both
   the display name and `messagingSocketPath`. Measured 2026-08-28: 27
   sockets, 12 live, 12 of 12 resolved to a name.

   Two things make it usable rather than merely available. It is keyed on
   `messagingSocketPath`, not on the pid in the filename, so the binding is the
   registry's own claim about which socket it owns (measured: 0 disagreements,
   but a convention that happens to hold is not one to depend on). And
   `nameSource` distinguishes a name Rohan TYPED from one the system derived
   for itself -- `derived` names look like `rohan-7b` -- so the roster can
   exclude the latter. A derived name is not a declaration, and this roster's
   whole premise is that the population is declared.

DELIBERATELY ABSENT: any fallback to spawning. If a named worker is missing the
answer is a refusal. Quietly spawning a fresh child in its place would produce
exactly the black-box agent this design exists to prevent, arriving through a
convenience.
"""

import json
import os
import socket

SOCKET_DIR = "/tmp/cc-socks"

#: Published refusal reasons. See contract/roster.json.
ROSTER_INSUFFICIENT = "roster_insufficient"
ROSTER_UNKNOWN_WORKER = "roster_unknown_worker"
ROSTER_UNNAMED = "roster_unnamed"

#: How an operator creates one more worker. `-n/--name` sets the display name
#: AT LAUNCH, so there is no rename step to forget.
CREATE_COMMAND = "claude --yolo -n {name!r}"

#: A liveness probe must not hang on a socket nobody is reading.
PROBE_TIMEOUT_S = 0.5

#: Where the runtime records live sessions. Read for NAMES ONLY.
SESSION_REGISTRY = "~/.claude/sessions"

#: `nameSource` values that are NOT a human declaration. `derived` is the
#: system naming itself (`rohan-7b`), which is the opposite of the property
#: this roster needs. A missing nameSource is NOT excluded: it predates the
#: field, and excluding it would drop real declared workers -- measured, it
#: would have dropped "Worker 1" and refused a worker that exists.
UNDECLARED_NAME_SOURCES = frozenset({"derived"})


class RosterEntry:
    __slots__ = ("address", "name", "alive", "source")

    def __init__(self, address, *, name=None, alive=False, source="socket_dir"):
        self.address = address
        self.name = name
        self.alive = alive
        self.source = source

    def as_dict(self):
        return {"address": self.address, "name": self.name,
                "alive": self.alive, "source": self.source}

    def __repr__(self):
        return f"<RosterEntry {self.name or self.address} alive={self.alive}>"


def probe_alive(address, timeout=PROBE_TIMEOUT_S):
    """Liveness by CONNECT, never by existence, and never by pid.

    Connects and closes immediately without sending a byte: the question is
    whether anyone is listening, and asking it must not deliver anything.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(address)
        return True
    except (OSError, socket.timeout):
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def session_registry_names(registry_dir=None):
    """Map socket address -> declared name, from the session registry.

    Returns a callable for `discover(name_source=...)`.

    Reads ONLY `*.json`. The same directory holds `<pid>.<hex>.key` files,
    which are secret material and are never opened; the glob makes that
    structural rather than a rule someone has to remember.

    LIVENESS IS NOT TAKEN FROM HERE. The registry carries a `status` field and
    it is deliberately ignored: it is a record of what a session last said
    about itself, and ROSTER-1 exists because a record of a past state read as
    a present one is how 14 dead sockets looked alive.
    """
    import glob

    directory = os.path.expanduser(registry_dir or SESSION_REGISTRY)
    mapping = {}
    for path in glob.glob(os.path.join(directory, "*.json")):
        try:
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue                    # a half-written record names nobody
        if not isinstance(record, dict):
            continue
        name = record.get("name")
        address = record.get("messagingSocketPath")
        if not name or not address:
            continue
        if record.get("nameSource") in UNDECLARED_NAME_SOURCES:
            continue
        mapping[address] = name

    def lookup(address):
        return mapping.get(address)

    return lookup


def discover(*, socket_dir=None, name_source=None, prober=probe_alive):
    """Return a Roster of LIVE panes. Stale sockets are dropped, not listed.

    `name_source` is a callable `(address) -> name or None`, defaulting to the
    session registry. Pass one explicitly to override it; pass a callable
    returning None to get the old unnamed behaviour.

    The two halves stay independent on purpose: liveness comes from a connect
    and naming comes from the registry, so a session that is recorded but dead
    is dropped, and a session that is live but undeclared is listed WITHOUT a
    name rather than with a guessed one.
    """
    directory = socket_dir or SOCKET_DIR
    if name_source is None:
        name_source = session_registry_names()
    entries = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for filename in names:
        if not filename.endswith(".sock"):
            continue
        address = os.path.join(directory, filename)
        if not prober(address):
            continue                      # stale: 14 of 26 were, on 2026-08-28
        name = None
        if name_source is not None:
            try:
                name = name_source(address)
            except Exception:                                  # noqa: BLE001
                name = None
        entries.append(RosterEntry(address, name=name, alive=True))
    return Roster(entries)


class Roster:
    def __init__(self, entries):
        self.entries = list(entries)

    def __len__(self):
        return len(self.entries)

    @property
    def named(self):
        return [e for e in self.entries if e.name]

    @property
    def names(self):
        return [e.name for e in self.named]

    def as_dict(self):
        return {"live": len(self.entries), "named": len(self.named),
                "workers": [e.as_dict() for e in self.entries]}

    # ------------------------------------------------------------- refusals

    def require(self, count, *, name_hint="Worker"):
        """Refusal dict if fewer than `count` live workers exist, else None.

        The refusal is THE PRODUCT, not an error path: it names what is
        missing and the exact command that would fix it, because a generic
        failure here is useless. The whole value is that the orchestrator can
        turn it into a question for the operator without inventing anything.
        """
        available = len(self.entries)
        if available >= count:
            return None
        missing = count - available
        have = self.names
        remedy = [CREATE_COMMAND.format(name=f"{name_hint} {i}")
                  for i in range(available + 1, count + 1)]
        # An unnamed roster says so rather than listing socket paths. The
        # person meant to ACT on this refusal cannot do anything with
        # /tmp/cc-socks/7018.sock, and printing it implies a precision the
        # roster does not have.
        if have:
            roster_text = ", ".join(have)
        elif available:
            roster_text = (f"{available} live but UNNAMED "
                           f"(no naming source; see roster_unnamed)")
        else:
            roster_text = "none"
        detail = (f"You asked for {count} worker{'s' if count != 1 else ''}, "
                  f"your roster has {available}: {roster_text}. "
                  f"Missing: {missing}.")
        return {
            "state": "REFUSED", "reason": ROSTER_INSUFFICIENT, "detail": detail,
            "requested": count, "available": available, "missing": missing,
            "roster": have, "remedy": remedy,
        }

    def require_names(self, wanted):
        """Refusal dict if any named worker is absent from the roster."""
        wanted = list(wanted)
        if not self.named and wanted:
            return {
                "state": "REFUSED", "reason": ROSTER_UNNAMED,
                "detail": (f"{len(self.entries)} live worker(s) are reachable but "
                           f"NONE can be named, so {wanted!r} cannot be resolved. "
                           f"Naming needs a source the socket layer does not "
                           f"provide."),
                "requested": wanted, "available": len(self.entries),
                "roster": [], "remedy": [],
            }
        present = set(self.names)
        missing = [w for w in wanted if w not in present]
        if not missing:
            return None
        return {
            "state": "REFUSED", "reason": ROSTER_UNKNOWN_WORKER,
            "detail": (f"Not on your roster: {', '.join(missing)}. "
                       f"Roster: {', '.join(sorted(present)) or 'none'}."),
            "requested": wanted, "available": len(self.named),
            "missing": missing, "roster": sorted(present),
            "remedy": [CREATE_COMMAND.format(name=m) for m in missing],
        }
