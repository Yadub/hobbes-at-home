"""Backups away from this Mac: an encrypted copy of the dashboard in iCloud Drive, made daily and checked weekly.

Each copy is an encrypted disk image (AES-256, made by macOS's hdiutil), so any Mac can open it: double-click it
and type the recovery key. Inside: the catalog (a consistent copy), the photos the owner added (uploads/), the
code (a git bundle of every branch, when it runs from a git copy), a manifest (every file's checksum, the
catalog's row counts) and how to restore. Keychain items (sign-ins, keys, passwords) are left out: after a
restore, WHOOP is signed in again.

The recovery key is made on first use and kept in the Keychain (`backup.recovery_key`). The owner keeps a copy
in Passwords: without it the copies can't be opened, and a Mac that's lost takes its Keychain with it.

The check opens the newest copy read-only, compares every file with the manifest, checks the catalog's
integrity and the code bundle, and closes it. A failed copy or check is a notification ("backups"), once per
problem a day. Kept: the newest 14 copies and the first of each month; older ones are removed from the folder
(iCloud Drive keeps them in Recently Deleted for 30 days). Nothing else in the folder is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets as pysecrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import config, db, jobs, push, secrets

ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
FOLDER_NAME = "Hobbes at Home Backups"
KEY_NAME = "backup.recovery_key"
REPO = Path(__file__).resolve().parents[2]
KEEP = 14
CHECK_EVERY = timedelta(days=7)
EVERY = 3600                # looks hourly whether a copy (or a check) is due
NAME = re.compile(r"^Hobbes at Home (\d{4}-\d{2}-\d{2}) (\d{4})\.dmg$")
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: easy to read and type
INCLUDES = ["Everything Hobbes at Home keeps (the catalog)", "Photos you added"]
EXCLUDES = ["The WHOOP sign-in and the dashboard's keys: sign in again after a restore"]
RESTORE = """Hobbes at Home backups

Each "Hobbes at Home <date>.dmg" here is an encrypted copy of Hobbes at Home on your Mac, made daily. To open
one, double-click it and type the recovery key (saved in your Passwords app).

Inside:
  catalog.db        everything Hobbes at Home keeps: diet, health, Hobbes AI, settings
  uploads/          photos you added
  code.bundle       the code with its history (only when it runs from a git copy)
  manifest.json     what's inside, with checksums

To restore on a Mac:
  1. Install Hobbes at Home (see its README), then stop it: hobbes service stop
  2. Copy catalog.db to ~/.hobbes/catalog.db, and uploads/ to ~/.hobbes/uploads/
  3. Start it again: hobbes service install
  4. Sign in to WHOOP again and turn notifications on. These live in the Mac's Keychain, not in the copies.
"""


class BackupError(Exception):
    user_facing = True


def _offline() -> bool:
    return os.environ.get("HOBBES_OFFLINE") == "1"


def folder() -> Path:
    """iCloud Drive's folder, or HOBBES_OFFSITE. Never the real one offline (tests, trials)."""
    if os.environ.get("HOBBES_OFFSITE"):
        return Path(os.environ["HOBBES_OFFSITE"]).expanduser()
    if _offline():
        raise BackupError("Offline: backups don't go to iCloud Drive.")
    return ICLOUD / FOLDER_NAME


def recovery_key() -> str:
    """The key the copies are encrypted with: made once, kept in the Keychain."""
    key = secrets.get(KEY_NAME)
    if not key:
        raw = "".join(pysecrets.choice(ALPHABET) for _ in range(24))
        key = "-".join(raw[i:i + 4] for i in range(0, 24, 4))
        secrets.put(KEY_NAME, key)
    return key


# ---------------------------------------------------------------- the disk image (replaced in tests)

def _hdiutil(args: list[str], key: str, timeout: float) -> subprocess.CompletedProcess[bytes]:
    if _offline():
        raise BackupError("Offline: no disk images are made.")
    try:
        return subprocess.run(["hdiutil", *args], input=key.encode() + b"\0", capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise BackupError(f"macOS's disk image tool didn't run ({e}).") from None


def _why(r: subprocess.CompletedProcess[bytes]) -> str:
    lines = (r.stderr or r.stdout).decode(errors="replace").strip().splitlines()
    return lines[-1].removeprefix("hdiutil: ") if lines else f"exit {r.returncode}"


def make_image(src: Path, dest: Path, key: str, volname: str) -> None:
    """An encrypted, compressed disk image of `src`'s contents, opened with `key`."""
    r = _hdiutil(["create", "-encryption", "AES-256", "-stdinpass", "-srcfolder", str(src),
                  "-volname", volname, "-format", "UDZO", str(dest)], key, timeout=900)
    if r.returncode:
        raise BackupError(f"The encrypted copy couldn't be made: {_why(r)}")


@contextmanager
def open_image(path: Path, key: str) -> Iterator[Path]:
    """The image opened read-only, out of sight (not in Finder), and always closed again."""
    tmp = config.home() / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    mount = Path(tempfile.mkdtemp(prefix="backup-check-", dir=tmp))
    r = _hdiutil(["attach", "-readonly", "-nobrowse", "-noautoopen", "-stdinpass", "-mountpoint",
                  str(mount), str(path)], key, timeout=600)
    if r.returncode:
        mount.rmdir()
        raise BackupError(f"The copy couldn't be opened with the recovery key: {_why(r)}")
    try:
        yield mount
    finally:
        for extra in ([], ["-force"]):
            if subprocess.run(["hdiutil", "detach", "-quiet", *extra, str(mount)], capture_output=True,
                              timeout=120).returncode == 0:
                break
        try:
            mount.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------- making a copy

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tables(path: Path) -> tuple[int, dict[str, int]]:
    c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                         "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return c.execute("PRAGMA user_version").fetchone()[0], \
            {n: c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        c.close()


def _bundle(dest: Path) -> str | None:
    """The code, every branch, as one file. A problem here doesn't stop the copy: it's noted instead."""
    if not (REPO / ".git").exists():
        return "The code isn't in a git repository here, so it isn't included."
    try:
        r = subprocess.run(["git", "-C", str(REPO), "bundle", "create", str(dest), "--all"], capture_output=True,
                           text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return f"The code couldn't be included ({e})."
    if r.returncode:
        dest.unlink(missing_ok=True)
        lines = (r.stderr or "").strip().splitlines()
        return f"The code couldn't be included ({lines[-1] if lines else 'git failed'})."
    return None


def copies() -> list[Path]:
    """The copies in the folder, oldest first (their names sort by date and time)."""
    f = folder()
    return sorted(p for p in f.iterdir() if NAME.match(p.name)) if f.is_dir() else []


def prune() -> list[str]:
    """Keep the newest KEEP and the first copy of each month; remove the rest (only files named as copies)."""
    found = copies()
    keep = set(found[-KEEP:])
    months: set[str] = set()
    for p in found:
        m = NAME.match(p.name)
        assert m
        if m.group(1)[:7] not in months:
            months.add(m.group(1)[:7])
            keep.add(p)
    removed = []
    for p in found:
        if p not in keep:
            p.unlink()
            removed.append(p.name)
    return removed


def make(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Make today's copy in the folder. Returns its name, size and any note (e.g. code left out)."""
    now = (now or datetime.now(UTC)).astimezone()
    name = f"Hobbes at Home {now:%Y-%m-%d %H%M}.dmg"
    key = recovery_key()
    dest_dir = folder()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "How to restore.txt").write_text(RESTORE)
    except OSError as e:
        raise BackupError(f"The dashboard can't write to {dest_dir} ({e.strerror or e}). If macOS asked, allow "
                          "access to iCloud Drive; it's in System Settings, Privacy & Security.") from None
    if (dest_dir / name).exists():
        raise BackupError(f"{name} is already there.")
    work_root = config.home() / "tmp"
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="backup-", dir=work_root))
    try:
        stage = work / "Hobbes at Home"
        stage.mkdir()
        db.backup(conn, stage / "catalog.db")
        uploads = config.home() / "uploads"
        if uploads.is_dir():
            shutil.copytree(uploads, stage / "uploads")
        note = _bundle(stage / "code.bundle")
        (stage / "How to restore.txt").write_text(RESTORE)
        schema, tables = _tables(stage / "catalog.db")
        files = {str(p.relative_to(stage)): {"size": p.stat().st_size, "sha256": _sha256(p)}
                 for p in sorted(stage.rglob("*")) if p.is_file()}
        manifest = {"made_at": now.isoformat(timespec="seconds"), "schema": schema, "tables": tables,
                    "files": files, "note": note, "not_included": EXCLUDES}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=1))
        image = work / name
        make_image(stage, image, key, f"Hobbes at Home {now:%Y-%m-%d}")
        size = image.stat().st_size
        try:
            shutil.move(image, dest_dir / name)  # the same disk: a rename, so iCloud never sees half a file
        except OSError as e:
            raise BackupError(f"The copy couldn't be put in {dest_dir} ({e.strerror or e}).") from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"name": name, "size": size, "note": note, "removed": prune()}


# ---------------------------------------------------------------- checking a copy

def check(path: Path | None = None) -> dict:
    """Open a copy (the newest by default) with the recovery key and check everything in it."""
    path = path or (copies()[-1] if copies() else None)
    if path is None:
        raise BackupError("There's no copy to check yet.")
    with open_image(path, recovery_key()) as mount:
        root = mount if (mount / "manifest.json").exists() else mount / "Hobbes at Home"
        try:
            manifest = json.loads((root / "manifest.json").read_text())
        except (OSError, ValueError):
            raise BackupError("The copy opened, but its list of contents is missing or damaged.") from None
        for rel, want in manifest["files"].items():
            p = root / rel
            if not p.is_file() or p.stat().st_size != want["size"] or _sha256(p) != want["sha256"]:
                raise BackupError(f"{rel} in the copy doesn't match what was saved.")
        c = sqlite3.connect(f"file:{root / 'catalog.db'}?mode=ro&immutable=1", uri=True)
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            c.close()
        if ok != "ok":
            raise BackupError(f"The catalog in the copy isn't intact ({ok}).")
        if _tables(root / "catalog.db") != (manifest["schema"], manifest["tables"]):
            raise BackupError("The catalog in the copy doesn't have the rows that were saved.")
        if (root / "code.bundle").is_file() and (REPO / ".git").exists():
            r = subprocess.run(["git", "-C", str(REPO), "bundle", "verify", "--quiet", str(root / "code.bundle")],
                               capture_output=True, text=True, timeout=300)
            if r.returncode:
                raise BackupError("The code in the copy didn't check out.")
    return {"name": path.name, "rows": sum(manifest["tables"].values()), "files": len(manifest["files"])}


# ---------------------------------------------------------------- status, schedule, notifications

def _get(conn: sqlite3.Connection) -> dict:
    return json.loads(db.get_setting(conn, "offsite.status") or "{}")


def _put(conn: sqlite3.Connection, **changes: Any) -> dict:
    st = _get(conn) | changes
    db.set_setting(conn, "offsite.status", json.dumps(st))
    return st


def tell(conn: sqlite3.Connection, what: str, error: str) -> None:
    """A notification for a problem, once a day per problem."""
    st = _get(conn)
    told = st.get("told") or {}
    today = datetime.now().date().isoformat()
    if told.get("error") == error and told.get("day") == today:
        return
    push.notify(conn, "backups", f"Backup {what} failed", error, "/settings/backups")
    _put(conn, told={"error": error, "day": today})


def key_saved(conn: sqlite3.Connection) -> None:
    _put(conn, key_saved_at=db.now())


ENABLED = "offsite.enabled"  # off until the owner turns it on: the first use makes macOS ask about iCloud Drive


def enabled(conn: sqlite3.Connection) -> bool:
    return db.get_setting(conn, ENABLED) == "1"


def set_enabled(conn: sqlite3.Connection, on: bool) -> None:
    db.set_setting(conn, ENABLED, "1" if on else "0")


def status(conn: sqlite3.Connection) -> dict:
    """What the page shows. From the settings only: it never touches the folder, which macOS may hold while it
    asks the owner (see `reachable`)."""
    st = _get(conn)
    keys = ("last_ok_at", "last_name", "last_size", "last_note", "last_error", "last_tried_at", "checked_at",
            "check_ok", "check_error", "checked_name", "key_saved_at")
    return {"enabled": enabled(conn),
            "folder": str(folder()) if os.environ.get("HOBBES_OFFSITE") else "iCloud Drive › " + FOLDER_NAME,
            "copies": st.get("copies") or 0, **{k: st.get(k) for k in keys}, "includes": INCLUDES,
            "excludes": EXCLUDES}


_PROBE: subprocess.Popen[bytes] | None = None
PROBE_CODE = "import os, sys; os.makedirs(sys.argv[1], exist_ok=True); os.listdir(sys.argv[1])"
PROBE_WAIT = 20.0
ASKING = ("macOS is asking whether the dashboard may use iCloud Drive. Answer it on the Mac's screen (Screen "
          "Sharing works), then tap Back Up Now.")


def reachable(wait: float | None = None) -> None:
    """Can the dashboard use the folder? Tried in a child process: when macOS wants the owner's permission
    for iCloud Drive it holds the call until someone answers, and a held call can't be cancelled. A child
    still waiting is left waiting (so the question stays on screen) and asked about again next time."""
    global _PROBE
    if _PROBE is None or _PROBE.poll() is not None:
        _PROBE = subprocess.Popen([sys.executable, "-c", PROBE_CODE, str(folder())], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _PROBE.wait(timeout=PROBE_WAIT if wait is None else wait)
    except subprocess.TimeoutExpired:
        raise BackupError(ASKING) from None
    if _PROBE.returncode:
        lines = (_PROBE.stderr.read() if _PROBE.stderr else b"").decode(errors="replace").strip().splitlines()
        raise BackupError(f"macOS didn't let the dashboard use {folder()} ({lines[-1] if lines else 'refused'}). "
                          "Allow it in System Settings, Privacy & Security, Files and Folders.")


def _error(e: Exception) -> str:
    return str(e) if isinstance(e, (BackupError, OSError)) else f"{type(e).__name__}: {e}"


def run(conn: sqlite3.Connection, copy: bool, verify: bool) -> dict:
    out: dict[str, Any] = {}
    if copy:
        _put(conn, last_tried_at=db.now())
    try:
        reachable()
    except BackupError as e:
        _put(conn, **({"last_error": str(e)} if copy else {"checked_at": db.now(), "check_ok": False,
                                                            "check_error": str(e)}))
        tell(conn, "to iCloud" if copy else "check", str(e))
        return {"error": str(e)} if copy else {"check_error": str(e)}
    if copy:
        try:
            made = make(conn)
        except Exception as e:  # recorded and told; the next hourly look tries again
            _put(conn, last_error=_error(e))
            tell(conn, "to iCloud", _error(e))
            out["error"] = _error(e)
            return out
        _put(conn, last_ok_at=db.now(), last_name=made["name"], last_size=made["size"], last_note=made["note"],
             last_error=None, copies=len(copies()))
        out["made"] = made["name"]
    if verify:
        try:
            checked = check()
        except Exception as e:
            _put(conn, checked_at=db.now(), check_ok=False, check_error=_error(e), copies=len(copies()))
            tell(conn, "check", _error(e))
            out["check_error"] = _error(e)
            return out
        _put(conn, checked_at=db.now(), check_ok=True, check_error=None, checked_name=checked["name"],
             copies=len(copies()))
        out["checked"] = checked
    return out


def due(conn: sqlite3.Connection, now: datetime | None = None) -> tuple[bool, bool]:
    """(make a copy, check one): a copy each day, after 1:00; a check a week after the last good one."""
    now = (now or datetime.now(UTC)).astimezone()
    st = _get(conn)
    last = st.get("last_ok_at")
    copy = now.hour >= 1 and (not last or datetime.fromisoformat(last).astimezone().date() < now.date())
    checked = st.get("checked_at")
    verify = not checked or not st.get("check_ok") or datetime.fromisoformat(checked) < now - CHECK_EVERY
    return copy, verify


@jobs.handler("offsite.backup", every=EVERY)
def backup_job(conn: sqlite3.Connection, payload: dict) -> dict[str, Any]:
    """Hourly: today's copy if it isn't made yet, and the weekly check. `copy`/`check` in the payload force
    them (Back Up Now, Check Now)."""
    if not enabled(conn):
        return {}
    copy, verify = due(conn)
    copy = bool(payload.get("copy", copy))
    verify = bool(payload.get("check", verify and (copy or bool(_get(conn).get("copies")))))
    if not copy and not verify:
        return {}
    return run(conn, copy, verify)
