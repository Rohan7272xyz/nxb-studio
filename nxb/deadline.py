"""A deadline that can INTERRUPT, not one that hopes to be checked.

The blocking class has now appeared four times in this codebase: a bare
readline; the same bare readline in a second loop; select-readiness mistaken
for line-readiness; and an unbounded write. Each was fixed as an instance, and
a fifth audit would have bought a fifth instance.

They are one wrong pattern:

    while time.monotonic() < deadline:
        <an operation that may never return>

The clock is only consulted between operations, so any operation that does not
return makes the deadline unreachable. Making each operation individually
non-blocking is whack-a-mole: it requires every future author to notice that
their new call can block, which is exactly the noticing that failed four times.

What ends the class is a deadline enforced by something that can interrupt a
blocked operation from outside it. A timer thread fires a `breaker` at expiry.
For a child process the breaker kills it, which EOFs its pipes and unblocks any
read, and breaks any write with EPIPE. The loop no longer has to reach a check
to be bounded, so a blocking call inside it is survivable rather than fatal.

This does not make blocking calls correct. It makes them non-lethal, which is
the property the previous four fixes each provided for one call site only.
"""

import threading
import time


class Deadline:
    """A wall-clock budget with an out-of-band interrupter.

    Use as a context manager so the timer is always cancelled:

        with Deadline(5.0, breaker=lambda: kill(proc)) as dl:
            while not dl.expired:
                ...
    """

    __slots__ = ("_expiry", "_breaker", "_timer", "broken", "_lock")

    def __init__(self, seconds, *, breaker=None):
        self._expiry = time.monotonic() + max(0.0, float(seconds))
        self._breaker = breaker
        self._timer = None
        self.broken = False
        self._lock = threading.Lock()

    def __enter__(self):
        if self._breaker is not None:
            self._timer = threading.Timer(self.remaining, self._fire)
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(self, *exc):
        self.cancel()
        return False

    def _fire(self):
        with self._lock:
            if self.broken:
                return
            self.broken = True
        try:
            self._breaker()
        except Exception:                                      # noqa: BLE001
            # A breaker that raises must not take out the timer thread. The
            # whole point is that expiry is enforced even when things are
            # already going wrong.
            pass

    @property
    def remaining(self):
        return max(0.0, self._expiry - time.monotonic())

    @property
    def expired(self):
        return time.monotonic() >= self._expiry

    def slice(self, cap=0.25):
        """A bounded wait that never overshoots the deadline."""
        return min(cap, self.remaining) if self.remaining > 0 else 0.0

    def cancel(self):
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
