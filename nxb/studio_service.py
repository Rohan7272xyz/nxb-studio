"""Install NXB Studio as an always-on macOS user LaunchAgent.

The server remains loopback-only; launchd removes the terminal ceremony, not
the security boundary.  A user agent is the right scope because Studio owns
the operator's tmux sessions, browser token, and home-directory state.  A
system daemon would run as the wrong user and widen the privilege boundary.
"""

import os
import plistlib
import re
import shutil
import socket
import subprocess
import time


LABEL = "com.nxb.studio"
DEFAULT_PORT = 8787


class StudioServiceError(RuntimeError):
    """A service operation refused or launchd did not complete it."""


def service_paths(home=None):
    home = os.path.abspath(os.path.expanduser(home or "~"))
    state = os.path.join(home, ".nxb")
    return {
        "home": home,
        "state": state,
        "plist": os.path.join(home, "Library", "LaunchAgents",
                              f"{LABEL}.plist"),
        "stdout": os.path.join(state, "studio-service.log"),
        "stderr": os.path.join(state, "studio-service.error.log"),
    }


def _target(uid=None):
    return f"gui/{os.getuid() if uid is None else uid}/{LABEL}"


def _domain(uid=None):
    return f"gui/{os.getuid() if uid is None else uid}"


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=20, check=False)


def _service_print(uid=None):
    return _launchctl("print", _target(uid))


def _is_loaded(uid=None):
    return _service_print(uid).returncode == 0


def _listener(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(.2)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _wait_for(port, wanted, *, deadline=10.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if _listener(port) is wanted:
            return True
        time.sleep(.1)
    return _listener(port) is wanted


def _clean_path():
    """Keep installed runtime paths, drop per-process Codex bootstrap paths."""
    entries = []
    for path in (os.environ.get("PATH") or "").split(os.pathsep):
        if (not path or path.startswith("/var/run/") or
                "/.codex/tmp/" in path or "codex-path" in path):
            continue
        if os.path.isdir(path) and path not in entries:
            entries.append(path)
    for command in ("python3", "tmux", "claude", "codex"):
        found = shutil.which(command)
        directory = os.path.dirname(found) if found else None
        if directory and directory not in entries:
            entries.insert(0, directory)
    for path in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
                 "/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        if path not in entries:
            entries.append(path)
    return os.pathsep.join(entries)


def launch_agent(ledger, repo, *, port=DEFAULT_PORT, python=None, home=None):
    """The complete launchd declaration, with no shell/profile dependency."""
    paths = service_paths(home)
    ledger = os.path.abspath(os.path.expanduser(ledger))
    repo = os.path.abspath(os.path.expanduser(repo))
    python = python or shutil.which("python3")
    if not python or not os.path.isabs(python):
        raise StudioServiceError("python3 did not resolve to an absolute path")
    if not os.path.isfile(ledger):
        raise StudioServiceError(f"no ledger at {ledger}")
    if not os.path.isfile(os.path.join(repo, "nxb", "__main__.py")):
        raise StudioServiceError(f"{repo} is not an NXB checkout")
    environment = {
        "HOME": paths["home"],
        "NXB_STUDIO_MANAGED": "1",
        "PATH": _clean_path(),
        "PYTHONPATH": repo,
    }
    for key in ("LANG", "LC_ALL", "LC_CTYPE"):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    return {
        "Label": LABEL,
        "ProgramArguments": [
            os.path.abspath(python), "-m", "nxb", "studio", "--no-open",
            "--port", str(int(port)), "--ledger", ledger,
        ],
        "WorkingDirectory": repo,
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        # A bare true intentionally restarts both crashes and clean exits. The
        # supported way to stop permanently is `studio uninstall`, which
        # unloads the job before removing its declaration.
        "KeepAlive": True,
        "ThrottleInterval": 3,
        "ProcessType": "Background",
        "StandardOutPath": paths["stdout"],
        "StandardErrorPath": paths["stderr"],
    }


def _write_plist(path, document):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "wb") as handle:
            plistlib.dump(document, handle, sort_keys=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _pid(text):
    match = re.search(r"^\s*pid\s*=\s*(\d+)\s*$", text or "", re.MULTILINE)
    return int(match.group(1)) if match else None


def status(*, port=DEFAULT_PORT, home=None):
    paths = service_paths(home)
    printed = _service_print()
    loaded = printed.returncode == 0
    return {
        "state": ("RUNNING" if loaded and _listener(port)
                  else "LOADED" if loaded else "NOT_INSTALLED"),
        "label": LABEL,
        "loaded": loaded,
        "reachable": _listener(port),
        "pid": _pid(printed.stdout) if loaded else None,
        "url": f"http://127.0.0.1:{int(port)}",
        "plist": paths["plist"],
        "stdout": paths["stdout"],
        "stderr": paths["stderr"],
    }


def install(ledger, repo, *, port=DEFAULT_PORT, python=None, home=None):
    if shutil.which("launchctl") is None:
        raise StudioServiceError("launchctl is unavailable; this requires macOS")
    paths = service_paths(home)
    document = launch_agent(ledger, repo, port=port, python=python, home=home)
    os.makedirs(paths["state"], exist_ok=True)

    if _is_loaded():
        stopped = _launchctl("bootout", _target())
        if stopped.returncode != 0:
            raise StudioServiceError(
                f"could not unload the existing Studio service: "
                f"{stopped.stderr.strip() or stopped.stdout.strip()}")
        _wait_for(port, False)
    if _listener(port):
        raise StudioServiceError(
            f"127.0.0.1:{port} is already in use by a process outside the "
            "Studio service. Stop that one-time server, then install again.")

    _write_plist(paths["plist"], document)
    loaded = _launchctl("bootstrap", _domain(), paths["plist"])
    if loaded.returncode != 0:
        raise StudioServiceError(
            f"launchctl bootstrap failed: "
            f"{loaded.stderr.strip() or loaded.stdout.strip()}")
    _launchctl("enable", _target())
    kicked = _launchctl("kickstart", "-k", _target())
    if kicked.returncode != 0:
        raise StudioServiceError(
            f"launchctl kickstart failed: "
            f"{kicked.stderr.strip() or kicked.stdout.strip()}")
    if not _wait_for(port, True):
        report = status(port=port, home=home)
        raise StudioServiceError(
            "Studio was installed but did not become reachable. Check "
            f"{report['stderr']}.")
    return status(port=port, home=home)


def restart(*, port=DEFAULT_PORT, home=None):
    if not _is_loaded():
        raise StudioServiceError(
            "Studio is not installed. Run: python3 -m nxb studio install")
    kicked = _launchctl("kickstart", "-k", _target())
    if kicked.returncode != 0:
        raise StudioServiceError(
            f"launchctl restart failed: "
            f"{kicked.stderr.strip() or kicked.stdout.strip()}")
    if not _wait_for(port, True):
        raise StudioServiceError("Studio did not become reachable after restart")
    return status(port=port, home=home)


def uninstall(*, port=DEFAULT_PORT, home=None):
    paths = service_paths(home)
    if _is_loaded():
        stopped = _launchctl("bootout", _target())
        if stopped.returncode != 0:
            raise StudioServiceError(
                f"launchctl bootout failed: "
                f"{stopped.stderr.strip() or stopped.stdout.strip()}")
        _wait_for(port, False)
    try:
        os.remove(paths["plist"])
    except FileNotFoundError:
        pass
    return {"state": "UNINSTALLED", "label": LABEL,
            "plist": paths["plist"],
            "detail": "drafts, token, ledger, and logs were preserved"}
