"""Where the dashboard keeps its data. Everything lives under one folder, ~/.hobbes by default
(HOBBES_HOME moves it, which tests and trial runs use so they never touch the real catalog)."""

from __future__ import annotations

import os
from pathlib import Path

PORT = 8780


def home() -> Path:
    return Path(os.environ.get("HOBBES_HOME") or Path.home() / ".hobbes").expanduser()


def db_path() -> Path:
    return home() / "catalog.db"


def log_dir() -> Path:
    return home() / "logs"


def backup_dir() -> Path:
    return home() / "backups"


def scratch_dir() -> Path:
    """Short-lived working files (one folder per AI run). Nothing here is kept."""
    return home() / "tmp"


def private(path: Path) -> None:
    """Only this account may read or change one of the dashboard's own files."""
    try:
        if path.stat().st_mode & 0o077:
            path.chmod(0o600)
    except OSError:
        pass


def secure_home() -> Path:
    """Make the data folder if needed, readable by this account alone: it will hold health
    readings, meal photos and the assistant's notes."""
    h = home()
    h.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if h.stat().st_mode & 0o077:
            h.chmod(0o700)
    except OSError:
        pass
    return h
