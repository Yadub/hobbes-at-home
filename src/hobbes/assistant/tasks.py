"""Assistant tasks: what the owner asked for, where it has got to, and a log of every step.

A task is worked on in rounds. Each round is one background job (`assistant.turn`, in runner.py) that
sees the whole task so far and ends with the job done, or with ONE question for the owner (status
needs_you). The owner's answer, or a change they ask for ("cheaper"), starts another round.

Only one round runs at a time per task. A message sent while a round is running is kept and picked
up by the next round, which is queued as soon as the current one finishes.

Statuses: working (a round is queued or running), needs_you, done, failed (the last round failed;
Try Again), cancelled (stopped by the owner; Resume starts another round). Removing a task only
hides it (deleted_at), with Undo.
"""

from __future__ import annotations

import json
import sqlite3

from .. import changes, db, jobs
from . import profile

STATUSES = ("working", "needs_you", "done", "failed", "cancelled")
OWNER_KINDS = ("asked", "answer", "refine")
MAX_TEXT = 2000
TURN_KIND = "assistant.turn"
STUCK = "It stopped unexpectedly. Try again."


def clean(text: str | None) -> str:
    return (text or "").strip()[:MAX_TEXT]


def add_step(conn: sqlite3.Connection, task_id: int, kind: str, text: str, data: dict | None = None) -> int:
    cur = conn.execute("INSERT INTO assistant_steps (task_id, at, kind, text, data) VALUES (?, ?, ?, ?, ?)",
                       (task_id, db.now(), kind, text, json.dumps(data) if data is not None else None))
    assert cur.lastrowid is not None
    return cur.lastrowid


def _row(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM assistant_tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)).fetchone()
    if not r:
        raise LookupError("There's no such task.")
    return r


def queue_turn(conn: sqlite3.Connection, task_id: int, watch: bool = False, routine: bool = False) -> int:
    """Queue the next round (inside the caller's write lock). One attempt only: a failed round costs
    a few minutes of the AI allowance, so trying again is the owner's call. `watch`: a scheduled look
    again at a watched job; `routine`: a routine's scheduled run (watches.py)."""
    turn = conn.execute("UPDATE assistant_tasks SET turns = turns + 1 WHERE id = ? RETURNING turns",
                        (task_id,)).fetchone()[0]
    payload = ({"task_id": task_id, "turn": turn} | ({"watch": True} if watch else {})
               | ({"routine": True} if routine else {}))
    job_id = jobs.enqueue(conn, TURN_KIND, payload, max_attempts=1)
    conn.execute("UPDATE assistant_tasks SET status = 'working', job_id = ?, error = NULL, finished_at = NULL, "
                 "updated_at = ? WHERE id = ?", (job_id, db.now(), task_id))
    return job_id


def create(conn: sqlite3.Connection, request: str) -> int:
    """A new job."""
    text = clean(request)
    if not text:
        raise ValueError("Say what you need.")
    now = db.now()
    with db.write_lock(conn):
        cur = conn.execute("INSERT INTO assistant_tasks (request, status, created_at, updated_at) "
                           "VALUES (?, 'working', ?, ?)", (text, now, now))
        task_id = cur.lastrowid
        assert task_id is not None
        add_step(conn, task_id, "asked", text)
        queue_turn(conn, task_id)
    return task_id


def message(conn: sqlite3.Connection, task_id: int, text: str) -> str:
    """The owner answers the question or asks for a change. Returns which it was."""
    text = clean(text)
    if not text:
        raise ValueError("Write something first.")
    with db.write_lock(conn):
        t = _row(conn, task_id)
        kind = "answer" if t["status"] == "needs_you" else "refine"
        q = json.loads(t["question"]) if t["question"] else None
        add_step(conn, task_id, kind, text, {"question": q["text"]} if kind == "answer" and q else None)
        if t["status"] != "working":
            conn.execute("UPDATE assistant_tasks SET question = NULL WHERE id = ?", (task_id,))
            queue_turn(conn, task_id)
        else:
            conn.execute("UPDATE assistant_tasks SET updated_at = ? WHERE id = ?", (db.now(), task_id))
    return kind


def retry(conn: sqlite3.Connection, task_id: int) -> None:
    """Run another round after a failure, or pick a stopped task up again."""
    with db.write_lock(conn):
        t = _row(conn, task_id)
        if t["status"] not in ("failed", "cancelled"):
            raise ValueError("Only a task that failed or was stopped can be started again.")
        add_step(conn, task_id, "retry", "Trying again" if t["status"] == "failed" else "Picked up again")
        queue_turn(conn, task_id)


def stop(conn: sqlite3.Connection, task_id: int) -> None:
    """Stop a task that's working. A round already under way finishes in the background, and what it
    comes back with is set aside."""
    with db.write_lock(conn):
        t = _row(conn, task_id)
        if t["status"] != "working":
            raise ValueError("It isn't working on this right now.")
        now = db.now()
        conn.execute("UPDATE assistant_tasks SET status = 'cancelled', finished_at = ?, updated_at = ? WHERE id = ?",
                     (now, now, task_id))
        add_step(conn, task_id, "stopped", "Stopped by you")


def remove(conn: sqlite3.Connection, task_id: int) -> dict:
    """Hide a task, with Undo. A task that's working is stopped first."""
    with db.write_lock(conn):
        before = changes.row(conn, "assistant_tasks", task_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such task.")
        now = db.now()
        if before["status"] == "working":
            conn.execute("UPDATE assistant_tasks SET status = 'cancelled', finished_at = ? WHERE id = ?",
                         (now, task_id))
            add_step(conn, task_id, "stopped", "Stopped when you removed it")
        conn.execute("UPDATE assistant_tasks SET deleted_at = ? WHERE id = ?", (now, task_id))
        change_id = changes.record(conn, "task.delete", "assistant_tasks", task_id, before,
                                   {**before, "deleted_at": now})
    return {"change_id": change_id}


# ---------------------------------------------------------------- reading

def _steps(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    """The job's log; each round's reply carries what it came back with, so the page can show the thread."""
    return [{"id": r["id"], "at": r["at"], "kind": r["kind"], "text": r["text"],
             "result": json.loads(r["data"]) if r["kind"] == "result" and r["data"] else None}
            for r in conn.execute("SELECT id, at, kind, text, data FROM assistant_steps WHERE task_id = ? ORDER BY id",
                                  (task_id,))]


def _summary(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    result = json.loads(r["result"]) if r["result"] else None
    latest = conn.execute("SELECT text FROM assistant_steps WHERE task_id = ? AND kind NOT IN ('asked', 'answer', "
                          "'refine') ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
    pick = None
    if result and result.get("recommended") is not None:
        options = result.get("options") or []
        if 0 <= result["recommended"] < len(options):
            pick = options[result["recommended"]]["title"]
    return {"id": r["id"], "request": r["request"], "title": r["title"] or _short(r["request"]),
            "status": r["status"], "question": json.loads(r["question"]) if r["question"] else None,
            "latest": latest["text"] if latest else None, "summary": result["summary"] if result else None,
            "pick": pick, "options": len(result.get("options") or []) if result else 0, "error": r["error"],
            "watch": watch_of(conn, r["id"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"], "finished_at": r["finished_at"]}


def watch_of(conn: sqlite3.Connection, task_id: int) -> dict | None:
    """The job's watch or routine (watches.py), if it has one."""
    from .watches import when_text

    w = conn.execute("SELECT * FROM assistant_watches WHERE task_id = ? AND stopped_at IS NULL", (task_id,)).fetchone()
    if w is None:
        return None
    routine = w["kind"] == "routine"
    return {"kind": w["kind"], "every": w["every"], "condition": w["condition"],
            "when": when_text(w["every"], w["day"], w["hour"]) if routine else None,
            "next_at": w["next_at"], "last_check_at": w["last_check_at"], "last_change": w["last_change"],
            "last_change_at": w["last_change_at"], "unseen": bool(w["unseen"])}


def get_title(conn: sqlite3.Connection, task_id: int) -> str:
    r = conn.execute("SELECT title, request FROM assistant_tasks WHERE id = ?", (task_id,)).fetchone()
    return (r["title"] or _short(r["request"])) if r else "Hobbes AI"


def _short(text: str, limit: int = 40) -> str:
    """A name for a task the AI hasn't named yet: the start of the request, cut at a word."""
    one = " ".join(text.split())
    if len(one) <= limit:
        return one
    cut = one[: limit - 1].rsplit(" ", 1)[0] if " " in one[: limit - 1] else one[: limit - 1]
    return cut.rstrip(" ,;:.-–") + "…"


def heal(conn: sqlite3.Connection) -> int:
    """A task still marked working whose round ended without saying so (the job failed before it
    started, say) is marked failed, so it can be tried again instead of spinning for ever."""
    sql = ("SELECT t.id FROM assistant_tasks t JOIN jobs j ON j.id = t.job_id "
           "WHERE t.status = 'working' AND t.deleted_at IS NULL AND j.status IN ('done', 'failed')")
    if not conn.execute(sql).fetchone():
        return 0
    now = db.now()
    with db.write_lock(conn):
        stuck = [r[0] for r in conn.execute(sql)]
        for task_id in stuck:
            conn.execute("UPDATE assistant_tasks SET status = 'failed', error = ?, finished_at = ?, updated_at = ? "
                         "WHERE id = ?", (STUCK, now, now, task_id))
            add_step(conn, task_id, "failed", STUCK)
    return len(stuck)


def get(conn: sqlite3.Connection, task_id: int) -> dict | None:
    heal(conn)
    r = conn.execute("SELECT * FROM assistant_tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)).fetchone()
    if not r:
        return None
    return {**_summary(conn, r), "result": json.loads(r["result"]) if r["result"] else None, "turns": r["turns"],
            "steps": _steps(conn, task_id), "suggestions": profile.suggestions(conn, task_id)}


def listing(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Tasks for the Assistant tab: everything open, and the most recent finished ones."""
    heal(conn)
    rows = conn.execute(
        "SELECT * FROM assistant_tasks WHERE deleted_at IS NULL "
        "ORDER BY CASE WHEN status IN ('needs_you', 'failed', 'working') THEN 0 ELSE 1 END, updated_at DESC, id DESC "
        "LIMIT ?", (limit,)).fetchall()
    return [_summary(conn, r) for r in rows]
