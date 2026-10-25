"""Coding sessions on this Mac: the owner's Claude Code and Codex sessions, and whether each is working,
waiting for them, idle or ended. Read only: the dashboard lists them and never sends them anything.

Claude Code: `claude agents --json`, its supported list of running sessions (in a terminal or in the
background), each with a status (busy, waiting and for what, idle). Codex: the local app-server its CLI and
app share, asked over its control socket (a WebSocket on a Unix socket) with two read-only calls,
`initialize` and `thread/list`: a thread is active (perhaps waiting on an approval or an answer), idle, or
notLoaded when nothing has it open. Nothing else may be called on either: no messages, no approvals.

Each session seen is a row in coding_sessions. One that drops out of its tool's list is marked ended, but
only when the tool answered, so an error doesn't end them all. Codex threads closed in the last day are shown
as ended too. Ended sessions are shown for a day; rows are kept.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__, db, jobs

TOOLS = {"claude": "Claude Code", "codex": "Codex"}
LIVE = ("working", "waiting", "idle", "error")
CLAUDE_DIRS = (Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
CODEX_SOCKET = Path.home() / ".codex" / "app-server-control" / "app-server-control.sock"
CODEX_SOURCES = ["cli", "vscode", "appServer"]  # not exec (the dashboard's own AI calls) or sub-agents
FRESH = 15                  # seconds a check is good for, when the page asks
SHOW_ENDED = 24 * 3600      # ended sessions are listed for a day
EVERY = 600                 # checked in the background too, so endings are noticed between visits
_LOCK = threading.Lock()


class Unavailable(Exception):
    """The tool isn't installed or isn't running: nothing to list, which isn't an error."""


def _offline() -> bool:
    return os.environ.get("HOBBES_OFFLINE") == "1"


def _iso(seconds: float | None) -> str | None:
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------- Claude Code

def claude_list() -> list[dict]:
    """`claude agents --json`: the running sessions as Claude Code reports them. Replaced in tests."""
    if _offline():
        raise Unavailable("offline")
    exe = shutil.which("claude") or next((str(d / "claude") for d in CLAUDE_DIRS if (d / "claude").exists()), None)
    if not exe:
        raise Unavailable("Claude Code isn't installed.")
    try:
        r = subprocess.run([exe, "agents", "--json"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"Claude Code didn't answer ({e}).") from None
    if r.returncode:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "Claude Code couldn't list its sessions.")
    found = json.loads(r.stdout or "[]")
    return found if isinstance(found, list) else []


def _claude(s: dict) -> dict | None:
    sid = s.get("sessionId") or s.get("id")
    if not sid:
        return None
    status, bg_state = s.get("status"), (s.get("state") or "").lower()
    state = {"busy": "working", "waiting": "waiting", "idle": "idle"}.get(status or "")
    if state is None:
        state = "waiting" if bg_state == "blocked" else "working"
    cwd = s.get("cwd") or ""
    background = s.get("kind") == "background"
    return {"session_id": str(sid), "name": s.get("name") or Path(cwd).name, "cwd": cwd,
            "kind": "background" if background else "interactive", "state": state,
            "waiting_for": s.get("waitingFor") if state == "waiting" else None,
            "open_with": f"claude attach {s['id']}" if background and s.get("id") else None,
            "started_at": _iso((s.get("startedAt") or 0) / 1000), "ended_at": None}


# ---------------------------------------------------------------- Codex

def codex_list() -> list[dict]:
    """Codex's threads from its local app-server: `thread/list`, nothing else. Replaced in tests."""
    if _offline():
        raise Unavailable("offline")
    if not CODEX_SOCKET.exists():
        raise Unavailable("Codex isn't running.")
    from websockets.exceptions import WebSocketException
    from websockets.sync.client import unix_connect

    try:
        with unix_connect(str(CODEX_SOCKET), uri="ws://localhost/", open_timeout=5, close_timeout=2,
                          max_size=16 * 2**20) as ws:
            def call(n: int, method: str, params: dict) -> Any:
                ws.send(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params}))
                end = time.monotonic() + 10
                while (left := end - time.monotonic()) > 0:
                    m = json.loads(ws.recv(timeout=left))
                    if m.get("id") == n:  # anything else is a notification, not ours
                        if "error" in m:
                            raise RuntimeError(f"Codex: {(m['error'] or {}).get('message') or 'error'}")
                        return m.get("result")
                raise TimeoutError

            call(1, "initialize", {"clientInfo": {"name": "hobbes", "title": "Hobbes at Home",
                                                  "version": __version__}})
            ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized"}))
            result = call(2, "thread/list", {"limit": 50, "archived": False, "sourceKinds": CODEX_SOURCES})
    except (ConnectionRefusedError, FileNotFoundError):
        raise Unavailable("Codex isn't running.") from None
    except (OSError, TimeoutError, WebSocketException, ValueError) as e:
        raise RuntimeError(f"Codex didn't answer ({e or type(e).__name__}).") from None
    data = (result or {}).get("data")
    return data if isinstance(data, list) else []


def _codex(t: dict, now: float) -> dict | None:
    if not t.get("id") or t.get("parentThreadId"):
        return None
    status = t.get("status") or {}
    flags = status.get("activeFlags") or []
    kind = status.get("type")
    if kind == "active":
        state = "waiting" if flags else "working"
    else:
        state = {"idle": "idle", "systemError": "error"}.get(kind or "", "ended")
    updated = t.get("updatedAt") or t.get("createdAt") or 0
    if state == "ended" and now - updated > SHOW_ENDED:
        return None
    waiting = {"waitingOnApproval": "approval", "waitingOnUserInput": "your answer"}
    cwd = t.get("cwd") or ""
    name = t.get("name") or " ".join((t.get("preview") or "").split())[:80] or Path(cwd).name
    return {"session_id": str(t["id"]), "name": name, "cwd": cwd, "kind": t.get("source") or "",
            "state": state, "waiting_for": ", ".join(waiting.get(f) or str(f) for f in flags) or None,
            "open_with": f"codex resume {t['id']}", "started_at": _iso(t.get("createdAt")),
            "ended_at": _iso(updated) if state == "ended" else None}


# ---------------------------------------------------------------- recording what was seen

def record(conn: sqlite3.Connection, tool: str, found: list[dict] | None, error: str | None = None,
           available: bool = True) -> None:
    """Save one tool's answer. `found` is None when the tool couldn't be asked: its sessions are left as
    they were. Otherwise a session that was live and isn't any more is marked ended."""
    now = db.now()
    with db.write_lock(conn):
        if found is not None:
            live = {s["session_id"] for s in found if s["state"] in LIVE}
            for s in found:
                row = conn.execute("SELECT state FROM coding_sessions WHERE tool = ? AND session_id = ?",
                                   (tool, s["session_id"])).fetchone()
                is_live = s["state"] in LIVE
                if row is None:
                    conn.execute(
                        "INSERT INTO coding_sessions (tool, session_id, name, cwd, kind, state, waiting_for, "
                        "open_with, started_at, first_seen_at, last_seen_at, state_since, ended_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (tool, s["session_id"], s["name"], s["cwd"], s["kind"], s["state"], s["waiting_for"],
                         s["open_with"], s["started_at"], now, now if is_live else (s["ended_at"] or now),
                         now if is_live else (s["ended_at"] or now), s["ended_at"]))
                    continue
                changed = row["state"] != s["state"]
                conn.execute(
                    "UPDATE coding_sessions SET name = ?, cwd = ?, kind = ?, state = ?, waiting_for = ?, "
                    "open_with = ?, started_at = coalesce(?, started_at), "
                    "last_seen_at = CASE WHEN ? THEN ? ELSE last_seen_at END, "
                    "state_since = CASE WHEN ? THEN ? ELSE state_since END, "
                    "ended_at = CASE WHEN ? THEN NULL ELSE coalesce(ended_at, ?) END "
                    "WHERE tool = ? AND session_id = ?",
                    (s["name"], s["cwd"], s["kind"], s["state"], s["waiting_for"], s["open_with"], s["started_at"],
                     is_live, now, changed, now if is_live else (s["ended_at"] or now), is_live,
                     s["ended_at"] or now, tool, s["session_id"]))
            gone = [r["session_id"] for r in conn.execute(
                f"SELECT session_id FROM coding_sessions WHERE tool = ? AND state IN ({','.join('?' * len(LIVE))})",
                (tool, *LIVE)) if r["session_id"] not in live]
            for sid in gone:
                conn.execute("UPDATE coding_sessions SET state = 'ended', waiting_for = NULL, state_since = ?, "
                             "ended_at = ? WHERE tool = ? AND session_id = ?", (now, now, tool, sid))
        db.set_setting(conn, f"sessions.{tool}", json.dumps(
            {"checked_at": now, "available": available, "error": error}))


def check(conn: sqlite3.Connection, force: bool = False) -> None:
    """Ask both tools, unless they were asked in the last few seconds."""
    with _LOCK:
        last = json.loads(db.get_setting(conn, "sessions.claude") or "{}").get("checked_at")
        if not force and last and datetime.fromisoformat(last) > datetime.now(UTC) - timedelta(seconds=FRESH):
            return
        now = time.time()
        for tool, ask, shape in (("claude", claude_list, _claude), ("codex", codex_list, lambda t: _codex(t, now))):
            try:
                found = [s for s in (shape(x) for x in ask()) if s]
            except Unavailable as e:
                record(conn, tool, [], None if str(e) == "offline" else str(e), available=False)
            except Exception as e:  # its sessions stay as they were; the page says it couldn't check
                record(conn, tool, None, str(e) or type(e).__name__)
            else:
                record(conn, tool, found)


def listing(conn: sqlite3.Connection) -> dict:
    since = (datetime.now(UTC) - timedelta(seconds=SHOW_ENDED)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT * FROM coding_sessions WHERE state != 'ended' OR ended_at >= ? ORDER BY "
        "CASE state WHEN 'waiting' THEN 0 WHEN 'error' THEN 1 WHEN 'working' THEN 2 WHEN 'idle' THEN 3 ELSE 4 END, "
        "CASE WHEN state = 'ended' THEN ended_at ELSE state_since END DESC", (since,))
    tools = []
    for tool, label in TOOLS.items():
        st = json.loads(db.get_setting(conn, f"sessions.{tool}") or "{}")
        tools.append({"tool": tool, "label": label, "available": bool(st.get("available", False)),
                      "error": st.get("error"), "checked_at": st.get("checked_at")})
    return {"tools": tools, "sessions": [
        {k: r[k] for k in ("id", "tool", "session_id", "name", "cwd", "kind", "state", "waiting_for", "open_with",
                           "started_at", "state_since", "ended_at")} for r in rows]}


@jobs.handler("sessions.check", every=EVERY)
def check_job(conn: sqlite3.Connection, payload: dict) -> dict[str, Any]:
    check(conn, force=True)
    return {s: n for s, n in conn.execute("SELECT state, count(*) FROM coding_sessions GROUP BY state")}
