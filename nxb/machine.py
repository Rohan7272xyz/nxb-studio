"""What the MACHINE is doing under a rig, for the watch line. [nxb-082.4]

WHY. MEASURED 2026-09-13 on pact-dev: between 1:10 and 1:40 AM this Mac's
swap reached 25 of 26 GB with eight iOS simulators booted by sessions
outside the rig, and one builder's process sat in an uninterruptible wait
for twenty-five minutes. Everything the rig reported about that builder was
true and useless: alive, not busy, holding a task, gauge unchanged. The
cause was not in any log the rig kept, and finding it by hand took ten
minutes. A stall the machine caused should say so in the same line that
reports the stall.

WHAT IT READS, AND WHAT IT REFUSES TO READ. `sysctl`, `vm_stat`, `pgrep`
and `tmux list-clients`: each is a few milliseconds, and the watcher runs
this every pass. NOT `xcrun simctl list`, which takes about a second and
would put a minute of simulator queries into every hour of watching; one
`launchd_sim` process is one booted simulator, which is the same fact for
free. Nothing here spawns a runtime, types into a pane or costs a token.

THE NUMBERS THAT MATTER, in the order they went wrong that night:

  pressure   `kern.memorystatus_vm_pressure_level`: 1 normal, 2 warn,
             4 critical. Apple's own signal, and the one that moves first.
  swap       `vm.swapusage`. Total GROWS on demand on macOS, so the used
             fraction reads calm at any size; the absolute used figure is
             what showed 25 GB.
  load       one-minute average against the core count.
  sims       booted simulators and their `idb_companion` daemons. The
             companions are counted separately because they outlive the
             simulators they drove: eight were still running this morning
             with one simulator left on the machine.
"""

import os
import re
import subprocess

#: `kern.memorystatus_vm_pressure_level`, as Apple publishes it.
PRESSURE_NAMES = {1: "normal", 2: "warn", 4: "critical"}

#: The pressure level that alone means STRAINED. Deliberately `critical`
#: and not `warn`: MEASURED 2026-09-13 11:45 AM, this Mac sat at `warn` for
#: ten minutes straight with 3 GB free, no swap growth and a load of 3.5 on
#: ten cores, which is a working machine, not a stalling one. A watch line
#: that shouts every minute is a watch line nobody reads. `warn` is still
#: printed; it just does not raise the alarm on its own.
PRESSURE_STRAINED = 4

#: Above this one-minute load per core, the machine is oversubscribed
#: whatever the memory says. MEASURED that night: load passed 14 on 10
#: cores while three rigs and eight simulators shared the box.
LOAD_PER_CORE_STRAINED = 2.0

#: Absolute swap in use, in GB, that counts as strained on its own. The
#: 25 GB night began by crossing 8; below that this Mac is simply busy.
SWAP_STRAINED_GB = 8.0

_TIMEOUT_S = 3.0


def _run(*args):
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              timeout=_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _sysctl(name):
    return _run("sysctl", "-n", name).strip()


def _gb(text):
    """'2833.19M' -> 2.767. sysctl prints M, G or K with the suffix."""
    match = re.match(r"([\d.]+)([KMG])", text.strip())
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    return round(value / {"K": 1024 * 1024, "M": 1024, "G": 1}[unit], 2)


def _count(process):
    out = _run("pgrep", "-x", process)
    return len([line for line in out.splitlines() if line.strip()])


def _memory_free_gb():
    """Free plus inactive plus speculative pages: what a new process can
    have without waiting. `Pages free` alone reads near zero on a healthy
    Mac and would call every machine critical."""
    out = _run("vm_stat")
    if not out:
        return None
    size = 4096
    head = re.search(r"page size of (\d+) bytes", out)
    if head:
        size = int(head.group(1))
    pages = 0
    for label in ("Pages free", "Pages inactive", "Pages speculative"):
        found = re.search(rf"{label}:\s+(\d+)\.", out)
        if found:
            pages += int(found.group(1))
    return round(pages * size / (1024 ** 3), 2)


def clients(session=None):
    """[{'name', 'width', 'height'}]: the terminals attached to a rig.

    WHY A RIG CARES. A rig is built 240 columns wide and every pane is
    sized from that. MEASURED 2026-09-13: a client attached at 83 columns
    shrank pact-dev's window to 83 and its two builders to 39 and 43, which
    is where RIG-37's truncated footer came from. The narrow pane is the
    symptom; the attached client is the cause, and health should name it.
    """
    args = ["tmux", "list-clients", "-F",
            "#{client_name}\t#{client_width}\t#{client_height}"]
    if session:
        args += ["-t", session]
    found = []
    for line in _run(*args).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            found.append({"name": parts[0], "width": int(parts[1]),
                          "height": int(parts[2])})
        except ValueError:
            continue
    return found


def snapshot(session=None):
    """Everything above, in one dict. Costs milliseconds and no tokens."""
    swap = _sysctl("vm.swapusage")
    used = re.search(r"used\s*=\s*(\S+)", swap)
    total = re.search(r"total\s*=\s*(\S+)", swap)
    try:
        pressure = int(_sysctl("kern.memorystatus_vm_pressure_level") or 0)
    except ValueError:
        pressure = 0
    try:
        load1 = round(os.getloadavg()[0], 1)
    except OSError:
        load1 = None
    cores = os.cpu_count() or 1
    snap = {"free_gb": _memory_free_gb(),
            "swap_used_gb": _gb(used.group(1)) if used else None,
            "swap_total_gb": _gb(total.group(1)) if total else None,
            "pressure": pressure,
            "pressure_name": PRESSURE_NAMES.get(pressure, "unknown"),
            "load1": load1, "cores": cores,
            "simulators": _count("launchd_sim"),
            "companions": _count("idb_companion"),
            "clients": clients(session)}
    snap["strained"] = strained(snap)
    return snap


def strained(snap):
    """True when the machine, not the worker, is the reason for a stall."""
    if (snap.get("pressure") or 0) >= PRESSURE_STRAINED:
        return True
    if (snap.get("swap_used_gb") or 0) >= SWAP_STRAINED_GB:
        return True
    load1, cores = snap.get("load1"), snap.get("cores") or 1
    return load1 is not None and load1 >= LOAD_PER_CORE_STRAINED * cores


def line(snap):
    """'mem 3.6G, swap 2.8G, load 2.5, 1 sim, 8 companions'. Terse on
    purpose: it is appended to every watch line, once a minute, forever."""
    parts = []
    if snap.get("free_gb") is not None:
        parts.append(f"mem {snap['free_gb']:.1f}G")
    if snap.get("swap_used_gb") is not None:
        parts.append(f"swap {snap['swap_used_gb']:.1f}G")
    if snap.get("load1") is not None:
        parts.append(f"load {snap['load1']:.1f}")
    sims = snap.get("simulators") or 0
    if sims:
        parts.append(f"{sims} sim" + ("s" if sims != 1 else ""))
    orphans = (snap.get("companions") or 0) - sims
    if orphans > 0:
        # A companion with no simulator left is a daemon nobody killed. It
        # holds memory and a port, and this morning there were eight.
        parts.append(f"{orphans} orphan companion"
                     + ("s" if orphans != 1 else ""))
    if snap.get("pressure_name") not in ("normal", "unknown"):
        parts.append(f"pressure {snap['pressure_name']}")
    body = ", ".join(parts)
    return ("MACHINE STRAINED: " + body) if snap.get("strained") else body
