"""Run the dashboard in the background at login with launchd."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from . import config

LABEL = "com.hobbes-at-home.serve"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def plist(port: int) -> dict:
    env = {
        # launchd starts with a bare PATH; Codex lives in Homebrew's folder, Claude Code in ~/.local/bin.
        "PATH": ":".join(["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"), "/usr/bin",
                          "/bin", "/usr/sbin", "/sbin"]),
        "PYTHONUNBUFFERED": "1",
    }
    for key in ("HOBBES_HOME", "HOBBES_CODEX_MODEL", "HOBBES_CLAUDE_MODEL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "hobbes", "serve", "--port", str(port)],
        "WorkingDirectory": str(config.home()),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        # Not "Background": macOS throttles a background job's disk access (about 50 times slower).
        "ProcessType": "Standard",
        "StandardOutPath": str(config.log_dir() / "serve.log"),
        "StandardErrorPath": str(config.log_dir() / "serve.err.log"),
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    if sys.platform != "darwin":
        raise RuntimeError("The background service uses launchd, which is macOS only.")
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def installed() -> bool:
    return PLIST.exists()


def running() -> bool:
    r = _launchctl("print", f"{_domain()}/{LABEL}")
    return r.returncode == 0 and "state = running" in r.stdout


def _wait_gone() -> None:
    # bootout returns before the old instance is gone; loading again too soon fails.
    for _ in range(50):
        if _launchctl("print", f"{_domain()}/{LABEL}").returncode != 0:
            return
        time.sleep(0.2)


def install(port: int) -> None:
    config.secure_home()
    config.log_dir().mkdir(parents=True, exist_ok=True)
    for name in ("serve.log", "serve.err.log"):
        os.close(os.open(config.log_dir() / name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    if installed():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        _wait_gone()
    with open(PLIST, "wb") as fh:
        plistlib.dump(plist(port), fh)
    r = None
    for _ in range(5):
        r = _launchctl("bootstrap", _domain(), str(PLIST))
        if r.returncode == 0 or "already" in (r.stderr + r.stdout).lower():
            return
        time.sleep(1)
    raise RuntimeError(((r.stderr or r.stdout).strip() if r else "") or "launchctl bootstrap failed")


def uninstall() -> None:
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    _wait_gone()
    PLIST.unlink(missing_ok=True)


def stop() -> None:
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    _wait_gone()


def restart() -> None:
    r = _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "launchctl kickstart failed")


def port() -> int | None:
    try:
        with open(PLIST, "rb") as fh:
            args = plistlib.load(fh).get("ProgramArguments") or []
        return int(args[args.index("--port") + 1])
    except (OSError, ValueError, IndexError, plistlib.InvalidFileException):
        return None


def log_tail(lines: int = 40) -> str:
    out = []
    for name in ("serve.log", "serve.err.log"):
        p = config.log_dir() / name
        if p.exists():
            out.append(f"--- {p}\n" + "\n".join(p.read_text(errors="replace").splitlines()[-lines:]))
    return "\n".join(out) or "No logs yet."
