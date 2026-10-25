"""Coding sessions: Claude Code's and Codex's answers turned into one list of working, waiting, idle and ended
sessions, endings noticed only when a tool answered, and nothing that can send a session anything."""

import time

import pytest

from hobbes import sessions


@pytest.fixture
def tools(monkeypatch):
    """What each tool answers: a list, or an exception to raise."""
    answers: dict = {"claude": [], "codex": []}

    def ask(tool):
        def fn():
            a = answers[tool]
            if isinstance(a, Exception):
                raise a
            return a
        return fn

    monkeypatch.setattr(sessions, "claude_list", ask("claude"))
    monkeypatch.setattr(sessions, "codex_list", ask("codex"))
    return answers


def claude(sid, status="busy", **kw):
    return {"pid": 1, "cwd": f"/Users/me/coding/{sid}", "kind": "interactive", "startedAt": 1792219611570,
            "sessionId": sid, "name": f"{sid}-1", "status": status, **kw}


def codex(tid, kind="idle", flags=(), updated=None, **kw):
    status = {"type": kind, **({"activeFlags": list(flags)} if kind == "active" else {})}
    return {"id": tid, "name": f"Thread {tid}", "cwd": "/Users/me/coding/codex", "status": status, "source": "cli",
            "createdAt": time.time() - 3600, "updatedAt": updated or time.time() - 60, **kw}


def states(conn):
    return {(s["tool"], s["session_id"]): (s["state"], s["waiting_for"]) for s in sessions.listing(conn)["sessions"]}


def test_both_tools_in_one_list(conn, tools):
    tools["claude"] = [claude("dash"), claude("photos", "waiting", waitingFor="permission prompt"),
                       claude("climb", "idle"),
                       {**claude("bg", "busy"), "kind": "background", "id": "d5a24797"}]
    tools["codex"] = [codex("t1", "active"), codex("t2", "active", ["waitingOnApproval"]), codex("t3"),
                      codex("old", "notLoaded", updated=time.time() - 3 * 86400),
                      codex("recent", "notLoaded", updated=time.time() - 600),
                      codex("sub", "active", parentThreadId="t1")]
    sessions.check(conn, force=True)
    got = sessions.listing(conn)["sessions"]
    assert states(conn) == {
        ("claude", "dash"): ("working", None), ("claude", "photos"): ("waiting", "permission prompt"),
        ("claude", "climb"): ("idle", None), ("claude", "bg"): ("working", None),
        ("codex", "t1"): ("working", None), ("codex", "t2"): ("waiting", "approval"), ("codex", "t3"): ("idle", None),
        ("codex", "recent"): ("ended", None)}  # a thread closed today; not one closed days ago, nor a sub-agent
    assert [s["state"] for s in got][:2] == ["waiting", "waiting"] and got[-1]["state"] == "ended"
    bg = next(s for s in got if s["session_id"] == "bg")
    assert bg["kind"] == "background" and bg["open_with"] == "claude attach d5a24797"
    assert next(s for s in got if s["session_id"] == "t3")["open_with"] == "codex resume t3"
    assert next(s for s in got if s["session_id"] == "dash")["name"] == "dash-1"


def test_a_session_that_goes_is_ended_but_not_when_the_tool_fails(conn, tools):
    tools["claude"] = [claude("dash"), claude("photos")]
    tools["codex"] = [codex("t1")]
    sessions.check(conn, force=True)

    # Claude couldn't be asked: its sessions stay as they were, and the page says why.
    tools["claude"] = RuntimeError("Claude Code didn't answer (timed out).")
    sessions.check(conn, force=True)
    assert states(conn)[("claude", "dash")] == ("working", None)
    claude_tool = sessions.listing(conn)["tools"][0]
    assert claude_tool["error"] == "Claude Code didn't answer (timed out)."

    # It answers again without one of them: that one has ended.
    tools["claude"] = [claude("dash", "idle")]
    sessions.check(conn, force=True)
    assert states(conn)[("claude", "photos")] == ("ended", None)
    assert states(conn)[("claude", "dash")] == ("idle", None)
    assert sessions.listing(conn)["tools"][0]["error"] is None

    # Codex not running at all: its sessions have ended; that isn't an error.
    tools["codex"] = sessions.Unavailable("Codex isn't running.")
    sessions.check(conn, force=True)
    assert states(conn)[("codex", "t1")] == ("ended", None)
    assert sessions.listing(conn)["tools"][1]["available"] is False

    # A session seen again is live again.
    tools["codex"] = [codex("t1", "active")]
    sessions.check(conn, force=True)
    row = next(s for s in sessions.listing(conn)["sessions"] if s["session_id"] == "t1")
    assert row["state"] == "working" and row["ended_at"] is None


def test_ended_sessions_are_listed_for_a_day(conn, tools):
    tools["claude"] = [claude("dash")]
    sessions.check(conn, force=True)
    tools["claude"] = []
    sessions.check(conn, force=True)
    assert states(conn)[("claude", "dash")][0] == "ended"
    conn.execute("UPDATE coding_sessions SET ended_at = '2026-01-01T00:00:00+00:00'")
    assert sessions.listing(conn)["sessions"] == []
    assert conn.execute("SELECT count(*) FROM coding_sessions").fetchone()[0] == 1  # kept


def test_a_recent_check_is_reused(conn, tools):
    calls = []
    tools["claude"] = [claude("dash")]
    original = sessions.claude_list
    sessions.claude_list = lambda: calls.append(1) or original()
    try:
        sessions.check(conn)
        sessions.check(conn)
        assert len(calls) == 1
        sessions.check(conn, force=True)
        assert len(calls) == 2
    finally:
        sessions.claude_list = original


def test_offline_lists_nothing(conn):
    sessions.check(conn, force=True)  # the tests run with HOBBES_OFFLINE=1: neither tool is asked
    assert sessions.listing(conn)["sessions"] == []
    assert all(t["error"] is None and not t["available"] for t in sessions.listing(conn)["tools"])


def test_the_api_is_read_only(client, tools):
    tools["claude"] = [claude("dash", "waiting", waitingFor="input needed")]
    r = client.get("/api/sessions")
    assert r.status_code == 200, r.text
    (s,) = r.json()["sessions"]
    assert s["state"] == "waiting" and s["waiting_for"] == "input needed" and s["tool"] == "claude"
    assert [t["tool"] for t in r.json()["tools"]] == ["claude", "codex"]
    # Nothing under /api/sessions changes anything.
    methods = {m for route in client.app.routes if getattr(route, "path", "").startswith("/api/sessions")
               for m in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}
