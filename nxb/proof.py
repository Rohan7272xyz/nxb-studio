"""Liveness state.

This file used to implement a freshness budget: a proof aged, went stale, and
staleness changed the gate's answer. **The budget is deleted.** [nxb-014]

Why, in the order the reasoning actually ran:

  1. F-5's original job was detecting a runtime that could not receive work.
     H2 now does that directly, at dispatch time, in about 0.2 seconds, for
     free, with a receipt. [M: nxb-010, nxb-011]
  2. So a pre-check is no longer a safety property. It is a cost optimisation.
  3. The budget's value therefore rests entirely on a number, "how often does a
     runtime go stale while idle", that nobody has ever measured and that
     nothing in this project has observed for longer than a few minutes.
  4. Machinery justified by an unmeasured constant is machinery that will be
     tuned until it stops firing. That is the muting failure, arriving by a
     different road.

So staleness is gone, and with it PROVEN_FRESH, PROVEN_STALE, PROOF_INVALID,
the skew tolerance, and the gate's verification of proofs at dispatch time.

What survives is the asymmetry that was the real result:

    fail closed on DISPROVEN, fail open on UNPROVEN, make proving cheap.

A proof no longer grants permission, so forging one grants nothing and there is
nothing to alarm about. Verification survives in exactly one place, where it
still buys something: a disproof may only be lifted by a canary whose success
points at an artefact the runtime itself wrote.
"""

import json
import os
import re
import stat

DISPROVEN = "DISPROVEN"
NEVER_PROVEN = "NEVER_PROVEN"
PROVEN = "PROVEN"

#: The whole gate. Two rows, and only one of them refuses.
GATE = {
    DISPROVEN:    "REFUSE",
    NEVER_PROVEN: "ALLOW",
    PROVEN:       "ALLOW",
}

#: A forged proof could otherwise point the verifier at a 10GB file. Reading is
#: bounded in bytes, not only in lines: `readline` on a file with no newlines
#: is unbounded in length even when the loop around it is not.
_MAX_EVIDENCE_BYTES = 256 * 1024


def make_proof(*, runtime_id, proven_at, method, runtime_ref, evidence_path):
    return {
        "runtime_id": runtime_id,
        "proven_at": proven_at,
        "method": method,
        "runtime_ref": runtime_ref,
        "evidence_path": evidence_path,
    }


#: Where each runtime's own artefacts live. A proof must point INSIDE one of
#: these, so a path the broker never had any reason to read cannot be evidence.
#: This duplicates the adapters' defaults on purpose, because importing them
#: here would be a cycle; a test asserts the two copies agree, which is this
#: project's standing answer to a second copy of a contract.
EVIDENCE_ROOTS = {
    "codex": "~/.codex/sessions",
    "claude_code": "~/.claude/projects",
}

#: A runtime ref is a session or thread identifier. Anything short enough to be
#: a coincidence is not one. [PROOF-1]
_MIN_REF_LEN = 8


def _ref_is_anchored_in(name, ref):
    """True if `ref` appears in `name` as a whole token, not as a substring.

    PROOF-1: this used to be `ref not in basename`, a plain containment test,
    so a one-character ref matched almost any filename. Measured: ref 'o'
    verified /etc/hosts, 's' verified /etc/passwd, 'e' verified /etc/shells.
    An attacker choosing the ref needed no write access and nothing
    runtime-specific.
    """
    return re.search(r"(?:^|[^A-Za-z0-9])" + re.escape(ref)
                     + r"(?:$|[^A-Za-z0-9])", name) is not None


def codex_evidence_verifier(proof, *, roots=None):
    """True if this proof points at an artefact the named runtime itself wrote.

    `evidence_path` and `runtime_ref` are attacker-supplied in the general
    case, so this is written as if they were. Four separate things must hold,
    and each closes a defect that was measured rather than imagined:

      1. the ref is long enough and appears ANCHORED in the basename [PROOF-1]
      2. the path resolves inside the named runtime's own root [PROOF-1]
      3. the handle we actually read is fstat'd as a regular file [PROOF-2]
      4. a malformed path is refused, not raised [PROOF-3]
    """
    path = proof.get("evidence_path")
    ref = proof.get("runtime_ref")
    runtime_id = proof.get("runtime_id")
    if not path or not ref or not isinstance(ref, str):
        return False
    if len(ref) < _MIN_REF_LEN:
        return False

    table = EVIDENCE_ROOTS if roots is None else roots
    root = table.get(runtime_id)
    if root is None:
        # A runtime with no declared evidence root cannot be verified. Fail
        # closed: an unknown runtime is not a licence to accept any path.
        return False

    try:
        # PROOF-3: os.stat raises ValueError, not OSError, on an embedded NUL,
        # and the old handler caught only OSError. Same family as H2-3, where
        # the kill path caught too narrow a class.
        real = os.path.realpath(path)
        real_root = os.path.realpath(os.path.expanduser(root))
        if os.path.commonpath([real, real_root]) != real_root:
            return False
        if not _ref_is_anchored_in(os.path.basename(real), ref):
            return False

        # PROOF-2: the old code stat'd the PATH and then opened it, with
        # nothing tying the two together, so a directory an attacker controls
        # could present a regular file to the stat and a FIFO to the open.
        # O_NONBLOCK means even a FIFO cannot hang us here, and the fstat is on
        # the descriptor we are about to read, which is the only check that
        # cannot be raced.
        fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError):
        return False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = None
            return ref in handle.read(_MAX_EVIDENCE_BYTES)
    except (OSError, ValueError):
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class ProofStore:
    """Durable liveness state: the last proof, and any standing disproof.

    Only the disproof affects the gate. The proof is kept because it is the
    evidence that lifted the last disproof and it is useful to a human reading
    the file, not because anything is permitted on the strength of it.
    """

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _load(self):
        try:
            if not stat.S_ISREG(os.stat(self.path).st_mode):
                return {}
        except OSError:
            return {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, doc):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2)
        os.replace(tmp, self.path)

    def get(self, runtime_id):
        if runtime_id.startswith("!"):
            return None
        return self._load().get(runtime_id)

    def put(self, proof):
        """Record a proof. Deliberately does NOT lift a disproof."""
        doc = self._load()
        doc[proof["runtime_id"]] = proof
        self._write(doc)

    def get_disproof(self, runtime_id):
        return self._load().get("!disproof:" + runtime_id)

    def put_disproof(self, runtime_id, *, at, reason):
        doc = self._load()
        doc["!disproof:" + runtime_id] = {"runtime_id": runtime_id,
                                          "at": at, "reason": reason}
        self._write(doc)

    def clear_disproof(self, runtime_id, *, proof=None, verifier=None):
        """Lift a disproof. The ONLY place verification still buys anything.

        A caller with a proof must have it verified. A caller with no proof at
        all is an explicit operator override and is allowed, because refusing
        it would just send the operator to edit the JSON by hand, which is the
        forging failure in another costume.
        """
        if proof is not None and verifier is not None and not verifier(proof):
            return False
        doc = self._load()
        doc.pop("!disproof:" + runtime_id, None)
        self._write(doc)
        return True


def gate_state(proof_store, runtime_id):
    """The whole of F-5. Returns (state, action)."""
    if proof_store.get_disproof(runtime_id) is not None:
        return DISPROVEN, GATE[DISPROVEN]
    if proof_store.get(runtime_id) is None:
        return NEVER_PROVEN, GATE[NEVER_PROVEN]
    return PROVEN, GATE[PROVEN]
