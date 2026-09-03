"""Shared process-spawn machinery for runtimes the broker owns end to end.

Extracted in nxb-027, when a second adapter was needed. It is NOT new code:
these are the Codex adapter's spawn and drain loops moved verbatim, because
four separate bug classes were found in them (a bare readline; the same
readline in a second loop; select-readiness mistaken for line-readiness; an
unbounded write) and duplicating that into a second file would mean every
future fix had to be applied twice, in a project whose own standing rule is to
name the violated property and audit for it everywhere.

A subclass supplies only what genuinely differs between runtimes. Everything
else, including the interrupting deadline, the bounded writer, the EOF
unregister and the kill discipline, is shared and must stay shared.
"""

import collections
import json
import os
import selectors
import signal
import subprocess
import time

from nxb.deadline import Deadline
from nxb.failsignal import detect


#: H2-1. The child decides how much it emits, so the broker decides how much it
#: records. Without this a chatty or hostile child fills the disk and makes the
#: recording loop unbounded work at the peer's discretion.
_MAX_EVENTS_BYTES = 8 * 1024 * 1024


class _BoundedWriter:
    """A file that stops at a byte cap and says so once."""

    __slots__ = ("_fh", "_written", "_cap", "truncated")

    def __init__(self, fh, cap=_MAX_EVENTS_BYTES):
        self._fh, self._cap, self._written, self.truncated = fh, cap, 0, False

    def write(self, text):
        if self.truncated:
            return
        data = text[: max(0, self._cap - self._written)]
        if data:
            self._fh.write(data)
            self._written += len(data)
        if self._written >= self._cap:
            self.truncated = True
            self._fh.write('\n{"type":"nxb.truncated","reason":'
                           '"event stream exceeded the recording cap"}\n')

    def flush(self):
        self._fh.flush()

    def close(self):
        self._fh.close()


class _LineReader:
    """Non-blocking line reader over a raw fd.

    selectors alone is NOT enough, and this is the third appearance of the
    same bug class in this adapter. select() reports readiness per BYTE;
    readline() still blocks until it sees a NEWLINE. A child that writes a
    partial line and then stops therefore re-blocks the loop for as long as it
    likes, and the deadline is never consulted. Measured [nxb-011]: a fake
    runtime printing `{"type":"thread.` then sleeping held a 3 second budget
    for 30 seconds.

    So we own the buffering: os.read never waits for a newline, and an
    unterminated tail is simply never a line.
    """

    def __init__(self, stream):
        self.fd = stream.fileno()
        self.stream = stream
        self._buf = ""
        #: Complete lines that have been split off but not yet consumed.
        #: They live HERE and not in the generator, because a consumer that
        #: breaks out of the loop (spawn does, on the start signal) abandons
        #: the generator, and anything it had already split off would be lost
        #: with it. Measured nxb-027: a child emitting its start frame and its
        #: result frame in ONE write lost the result entirely, so the turn read
        #: as never having completed. Latent in the Codex path since nxb-010.
        self._pending = collections.deque()
        self.eof = False

    def drain_ready(self):
        """Read whatever is available now; yield only COMPLETE lines.

        Un-consumed lines survive the caller breaking out of the loop, so the
        reader can be handed from spawn to drain without losing frames.
        """
        try:
            chunk = os.read(self.fd, 65536)
        except (BlockingIOError, InterruptedError):
            chunk = b""
        except OSError:
            self.eof = True
            chunk = b""
        else:
            if not chunk:
                self.eof = True
        if chunk:
            self._buf += chunk.decode("utf-8", "replace")
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._pending.append(line + "\n")
        while self._pending:
            yield self._pending.popleft()

    @property
    def has_pending(self):
        return bool(self._pending)


class SpawnRefused(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def find_evidence(root, needle):
    """Locate the artefact a runtime wrote for `needle`, or None.

    Shared so a third adapter cannot reopen C14. The blank guard is the whole
    point: `"" in name` is TRUE FOR EVERY FILE, so a blank needle used to
    return the first file the walk reached, and `run_canary` accepted any
    non-None result as proof that a live round trip had happened. A liveness
    proof pointing at an unrelated file from a different month is a forged
    proof, produced by the instrument whose purpose is catching false greens.
    """
    if not needle or not isinstance(needle, str):
        return None
    root = os.path.expanduser(root)
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if needle in name and name.endswith(".jsonl"):
                return os.path.join(dirpath, name)
    return None


class ProcessAdapter:

    # ---- hooks a subclass must supply -----------------------------------
    runtime_id = "abstract"
    model = None

    def build_command(self, *, work_dir, prompt, out_path, schema_path=None):
        raise NotImplementedError

    def _match_start(self, evt):
        """(matched, ref). matched=True with ref=None means MALFORMED, which
        the caller reports as such rather than as a timeout."""
        raise NotImplementedError

    def _note_terminal(self, evt, terminal, handle):
        raise NotImplementedError

    def _reject_start(self, evt):
        """Reason to REFUSE a child that started, or None to accept it.

        Read-back, not trust. The start frame is the runtime's own report of
        what it actually holds, and a flag that was accepted is not a flag that
        took effect: `--permission-mode manual` was measured accepted and inert.
        A denylist checked only by passing it is a denylist that rots silently
        on the next release; checked HERE it fails loudly instead.
        """
        return None

    def _finalize(self, handle, terminal):
        """Default: the runtime wrote its own out_path and there is nothing
        to do. Overridden by runtimes whose answer arrives on stdout."""

    def spawn(self, *, work_dir, prompt, run_dir, start_timeout,
              out_path=None, schema_path=None, hold_stdin_open=False):
        """Spawn and wait for the START SIGNAL only. Returns a dict.

        `hold_stdin_open` exists solely so the F-13 trap can be exercised on
        purpose. Production callers never set it.
        """
        os.makedirs(run_dir, exist_ok=True)
        # nxb-031. The child runs HERE, set by the shared base rather than by
        # each adapter, because an adapter that merely *accepts* work_dir can
        # drop it and one did: Codex spent it on `-C`, Claude Code took it in
        # its signature and never read it, and Popen had no `cwd=`, so a
        # dispatched Claude Code child ran in the BROKER'S OWN SOURCE TREE with
        # Edit, Write and Bash. Setting it here makes ignoring it inexpressible
        # for every present and future adapter; a comment telling adapters not
        # to ignore it would not have.
        os.makedirs(work_dir, exist_ok=True)
        out_path = out_path or os.path.join(run_dir, "last-message.txt")
        events_path = os.path.join(run_dir, "events.jsonl")
        stderr_path = os.path.join(run_dir, "stderr.txt")

        cmd = self.build_command(work_dir=work_dir, prompt=prompt,
                                 out_path=out_path, schema_path=schema_path)

        events = _BoundedWriter(open(events_path, "w", encoding="utf-8"))
        errs = open(stderr_path, "w", encoding="utf-8")
        began = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=work_dir,
                # H2-8. Its own session and process group, so a kill reaches
                # the child's OWN children too. Without it a child shares the
                # broker's group: measured, a grandchild outlived the kill of
                # its parent and became a stray. That is the cause the
                # pattern-kill ban only removed the remedy for, and a ban held
                # by a docstring binds a person where this binds the process.
                start_new_session=True,
                stdin=subprocess.PIPE if hold_stdin_open else subprocess.DEVNULL,  # F-13
                stdout=subprocess.PIPE, stderr=errs, text=True, bufsize=1,
            )
        except OSError as exc:
            # A missing or unexecutable runtime binary. The first version of
            # this adapter let this propagate, so H2 could RAISE where H1
            # never can. The friendly path never exercises it, which is why it
            # survived until a hostile test asked. [nxb-011]
            events.close()
            errs.close()
            return {
                "started": False, "reason": "runtime_binary_unavailable",
                "detail": str(exc),
                "thread_id": None, "killed": False, "exit_code": None,
                "events_path": events_path, "out_path": out_path,
                "out_present": os.path.exists(out_path),
            }

        try:
            # H2-8. Recorded WHILE THE CHILD LIVES. After the leader is reaped
            # os.getpgid raises, so a group resolved at kill time is exactly
            # the group you can no longer find, and survivors stay unreachable.
            proc._nxb_pgid = os.getpgid(proc.pid)
        except OSError:
            proc._nxb_pgid = None

        thread_id = None
        started_at = None
        malformed = False

        # A timeout that cannot fire is not a timeout.
        #
        # The obvious implementation of F-15 checks the clock between reads
        # and then calls a BLOCKING readline(). Against the F-13 stdin trap
        # the child emits zero bytes, readline() blocks forever, and the
        # clock is never consulted again: the refusal is structurally
        # incapable of firing against the exact trap it exists for. That was
        # this adapter's first implementation and it hung for two minutes on
        # an eight second budget. Measured, nxb-010.
        #
        # So the wait is non-blocking. Every read is bounded by the remaining
        # budget, and the loop can always reach its own deadline.
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        reader = _LineReader(proc.stdout)
        registered = True
        with Deadline(start_timeout, breaker=lambda: self._break(proc)) as dl:
            try:
                while not dl.expired:
                    if not registered:
                        # H2-2. Once stdout is at EOF the selector reports it
                        # readable forever, so continuing to select on it burns
                        # a core. Nothing more can arrive; wait on the process
                        # instead, bounded, with the deadline's breaker behind.
                        try:
                            proc.wait(timeout=dl.slice(0.25))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    if not sel.select(timeout=dl.slice(0.25)):
                        continue
                    got_signal = False
                    for line in reader.drain_ready():
                        events.write(line)
                        events.flush()
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        matched, ref = self._match_start(evt)
                        if matched:
                            rejection = self._reject_start(evt)
                            if rejection is not None:
                                self._kill(proc)
                                events.close()
                                errs.close()
                                return {
                                    "started": False, "reason": rejection,
                                    "thread_id": None, "killed": True,
                                    "exit_code": proc.poll(),
                                    "events_path": events_path,
                                    "out_path": out_path,
                                    "out_present": os.path.exists(out_path),
                                }
                            thread_id = ref
                            started_at = time.monotonic() - began
                            if not thread_id:
                                # C14. "" is not None, so an identity test let
                                # a blank id through as a valid start. A start
                                # signal that names nothing did not start
                                # anything identifiable.
                                thread_id = None
                                malformed = True
                            got_signal = True
                            break
                    if got_signal:
                        break
                    if reader.eof and registered:
                        sel.unregister(proc.stdout)
                        registered = False
            finally:
                if registered:
                    sel.unregister(proc.stdout)
                sel.close()

        if thread_id is None:
            # F-15. Kill it. Do NOT leave the child alive, and do NOT infer
            # anything from the fact that it may still be running.
            killed = self._kill(proc)
            events.close()
            errs.close()
            return {
                "started": False,
                # A start signal that arrived but carried no id is NOT a
                # timeout, and reporting it as one sends the operator to look
                # at the clock instead of at the runtime.
                "reason": ("malformed_start_signal" if malformed
                           else "no_start_signal_within_timeout"),
                "thread_id": None,
                "killed": killed,
                "exit_code": proc.poll(),
                "events_path": events_path,
                "out_path": out_path,
                "out_present": os.path.exists(out_path),
            }

        return {
            "started": True,
            "thread_id": thread_id,
            "proc": proc,
            # Handed to drain rather than rebuilt there. See _LineReader.
            "reader": reader,
            "events": events,
            "errs": errs,
            "events_path": events_path,
            "out_path": out_path,
        }

    @staticmethod
    def _own_group(proc):
        """The child's process group, or None if it is not safe to signal.

        The guard is not decoration. If `start_new_session` ever failed to take
        effect the child would still be in the BROKER'S group, and a killpg
        would take out the broker, every sibling adapter and anything else
        sharing it. Refusing to signal a group we are inside is the difference
        between reaping a subtree and reaping ourselves.
        """
        pgid = getattr(proc, "_nxb_pgid", None)
        if pgid is None:
            try:
                pgid = os.getpgid(proc.pid)
            except (ProcessLookupError, OSError):
                return None
        try:
            if pgid == os.getpgid(0):
                return None
        except OSError:
            return None
        return pgid

    @classmethod
    def _signal_group(cls, proc, sig):
        pgid = cls._own_group(proc)
        if pgid is None:
            return False
        try:
            os.killpg(pgid, sig)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    @staticmethod
    def _break(proc):
        """The deadline's interrupter. Decisive on purpose.

        It fires only once the budget has elapsed, at which point we have
        already decided to abandon this child, so a graceful signal buys
        nothing: nxb-010 measured that a SIGINTed child exits 0 anyway, so the
        polite path was never carrying signal fidelity either. SIGKILL EOFs the
        pipes immediately, which is what unblocks a loop stuck in a read or a
        write.
        """
        try:
            if proc.poll() is None:
                # H2-8: the whole subtree, not just the leader.
                ProcessAdapter._signal_group(proc, signal.SIGKILL)
                proc.kill()
        except Exception:                                      # noqa: BLE001
            pass

    @classmethod
    def _kill(cls, proc):
        """Kill ONLY a process we hold a Popen handle for.

        Never by command-line pattern. On 2026-08-28 a `pkill -f "codex exec"`
        issued from this session to clean up its own strays also reaped
        another worker's unrelated Codex run, because that worker's shell
        wrapper carried the same string. On a machine running several agents,
        pattern killing is cross-tenant destructive and silent. F-15 needs
        this clause and the spec does not have it.
        """
        # H2-3. This used to catch only OSError, so anything else escaped into
        # a caller that had been promised a refusal rather than an exception.
        # And its two three-second waits could push a caller past the very
        # deadline this function exists to enforce; they are one second now,
        # with the deadline's own breaker behind them as the backstop.
        try:
            if proc.poll() is not None:
                return False
            # H2-8: signal the GROUP so the child's own children go too.
            # proc.send_signal remains as the fallback for the case where the
            # group is not safe to signal.
            if not cls._signal_group(proc, signal.SIGINT):
                proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            # The leader exiting is NOT the subtree exiting. Measured: a
            # grandchild survived a clean SIGINT kill of its parent, because a
            # non-interactive shell sets SIGINT to IGNORE for background jobs.
            # So the group is reaped unconditionally, after the leader is
            # dealt with, using the pgid captured while it was alive.
            cls._signal_group(proc, signal.SIGKILL)
            return True
        except Exception:                                      # noqa: BLE001
            return False

    def drain(self, handle, *, budget, abort_on_announced_failure=False):
        """Read to completion. Returns the terminal facts, never a verdict.

        `abort_on_announced_failure` stops as soon as the runtime announces its
        own failure, rather than sitting out the budget waiting to discover the
        output file is absent. Off by default: for ordinary work a single
        announced error may still be recovered from by the runtime's own retry,
        and aborting it would be the broker overruling a live child. The canary
        turns it on, because a canary that saw an error did not observe the
        clean round trip it exists to observe. [M: nxb-022]
        """
        proc, events = handle["proc"], handle["events"]
        terminal = {"turn_completed": False, "turn_failed": False, "error": False}
        announced = None
        aborted = False
        # Same non-blocking discipline as spawn(). This loop originally used a
        # bare readline() too: the identical bug, in a second place, which I
        # only noticed because a test made me reread the file. A budget checked
        # around a blocking read is not a budget.
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        reader = handle.get("reader") or _LineReader(proc.stdout)
        registered = True
        with Deadline(budget, breaker=lambda: self._break(proc)) as dl:
            try:
                while not dl.expired:
                    if not registered:
                        try:
                            proc.wait(timeout=dl.slice(0.25))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    if not reader.has_pending and not sel.select(
                            timeout=dl.slice(0.25)):
                        continue
                    for line in reader.drain_ready():
                        events.write(line)
                        events.flush()
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        self._note_terminal(evt, terminal, handle)
                        # The runtime volunteers this in ~0.6s. Absence of an
                        # output file, which is what this used to wait for,
                        # cannot be known until the budget has fully elapsed.
                        if announced is None:
                            announced = detect(evt, runtime_id=self.runtime_id)
                            if announced is not None and abort_on_announced_failure:
                                aborted = True
                                break
                    if aborted:
                        break
                    if reader.eof and registered:
                        sel.unregister(proc.stdout)
                        registered = False
            finally:
                if registered:
                    sel.unregister(proc.stdout)
                sel.close()
        still_running = proc.poll() is None
        if still_running:
            self._kill(proc)
        events.close()
        # Hook: a runtime with no --output-file equivalent produces out_path
        # here, from whatever frame carried its answer. Runs AFTER the stream
        # closes and BEFORE out_present is computed, so F-14 still means what
        # it says.
        self._finalize(handle, terminal)
        handle["errs"].close()
        return {
            "exit_code": proc.poll(),
            # An abort is not a timeout. Reporting it as one would send the
            # operator to look at the clock instead of at the runtime, which is
            # the same error the malformed_start_signal clause exists to avoid.
            "drain_timed_out": still_running and not aborted,
            "announced_failure": announced,
            "aborted_on_announcement": aborted,
            # F-14: absence is a reliable failure signal; presence is NOT
            # a success signal and is deliberately not named "ok".
            "out_present": os.path.exists(handle["out_path"]),
            **terminal,
        }
