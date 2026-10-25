"""Watches and routines: a job run again on a schedule.

A watch is a finished job looked at again (daily or weekly) and told apart from the last look: a fare that
fell, a table that opened up, an offer that started or ended. It can carry the owner's condition ("a
return fare under 1,200"): then it only reports when that's met. A routine is a job done afresh on a
schedule (every Thursday at 05:00, say): "what's on in town this weekend". Both are usually set by the
owner in the job's own conversation; the round reads that from their words (runner.py, "schedule").

Each run is an ordinary round of the job (runner.py) with `watch` or `routine` in its payload. What it
found is kept on the row, marked unseen until the owner opens the job, and goes into the morning brief.
A job waiting on the owner's answer isn't run again until it's answered. At most MAX_ACTIVE watches and
routines together, as each run uses some of the AI allowance. A routine with no hour runs at
ROUTINE_HOUR, before the morning brief is written.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db, jobs
from . import tasks

EVERY = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
ROUTINE_EVERY = ("daily", "weekly", "monthly")
ROUTINE_HOUR = 5
MAX_ACTIVE = 10
CHECK = 15 * 60
DAYS = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


def _utc(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds")


def get(conn: sqlite3.Connection, task_id: int) -> dict | None:
    return tasks.watch_of(conn, task_id)


def _check(conn: sqlite3.Connection, task_id: int) -> None:
    """(Inside the caller's write lock.) The job exists and there's room for one more."""
    if conn.execute("SELECT 1 FROM assistant_tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)).fetchone() is None:
        raise LookupError("There's no such task.")
    active = conn.execute("SELECT COUNT(*) FROM assistant_watches WHERE stopped_at IS NULL AND task_id != ?",
                          (task_id,)).fetchone()[0]
    if active >= MAX_ACTIVE:
        raise ValueError(f"You already have {MAX_ACTIVE} watches and routines. Stop one first: each run uses "
                         "some of the AI allowance.")


def _upsert(conn: sqlite3.Connection, task_id: int, kind: str, every: str, next_at: datetime,
            condition: str | None, day: int | None, hour: int | None) -> None:
    conn.execute(
        "INSERT INTO assistant_watches (task_id, kind, every, next_at, condition, day, hour, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (task_id) DO UPDATE SET kind = excluded.kind, "
        "every = excluded.every, next_at = excluded.next_at, condition = excluded.condition, day = excluded.day, "
        "hour = excluded.hour, stopped_at = NULL",
        (task_id, kind, every, _utc(next_at), condition, day, hour, db.now()))


def watch(conn: sqlite3.Connection, task_id: int, every: str, now: datetime | None = None,
          condition: str | None = None) -> dict:
    """Watch a job (or change how often). The first look is one period from now: it was just done.
    `condition`: when to tell the owner, in their words; None keeps the one it has, "" means any change
    that matters."""
    if every not in EVERY:
        raise ValueError("Watch daily or weekly.")
    now = now or datetime.now(UTC)
    with db.write_lock(conn):
        _check(conn, task_id)
        if condition is None:
            had = conn.execute("SELECT condition FROM assistant_watches WHERE task_id = ? AND kind = 'watch' AND "
                               "stopped_at IS NULL", (task_id,)).fetchone()
            condition = had["condition"] if had else None
        condition = " ".join((condition or "").split())[:300] or None
        _upsert(conn, task_id, "watch", every, now + EVERY[every], condition, None, None)
        then = (f"it will tell you when there's {condition}" if condition
                else "it will look again and tell you what changes")
        tasks.add_step(conn, task_id, "watch", f"Watching {every}: {then}")
    w = get(conn, task_id)
    assert w
    return w


def next_run(every: str, day: int | None, hour: int | None, after: datetime) -> datetime:
    """A routine's next run after `after`, in local time: daily at its hour, weekly on its weekday (1 is
    Monday), monthly on its day (1 to 28)."""
    local = after.astimezone()
    at = local.replace(hour=ROUTINE_HOUR if hour is None else hour, minute=0, second=0, microsecond=0)
    if every == "daily":
        return at if at > local else at + timedelta(days=1)
    if every == "weekly":
        at += timedelta(days=((day or 1) - 1 - at.weekday()) % 7)
        return at if at > local else at + timedelta(days=7)
    at = at.replace(day=day or 1)
    if at > local:
        return at
    return at.replace(year=at.year + 1, month=1) if at.month == 12 else at.replace(month=at.month + 1)


def when_text(every: str, day: int | None, hour: int | None) -> str:
    """"Thursdays, 05:00", "Every day, 07:00", "On the 1st, 05:00"."""
    at = f"{ROUTINE_HOUR if hour is None else hour:02d}:00"
    if every == "daily":
        return f"Every day, {at}"
    if every == "weekly":
        return f"{DAYS[(day or 1) - 1]}, {at}"
    d = day or 1
    suffix = "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"On the {d}{suffix}, {at}"


def routine_slot(every: str, day: int | None, hour: int | None, now: datetime | None = None) -> tuple:
    """(day, hour) as kept: a weekday 1 to 7, or a day of the month up to 28, today's if not given; no
    day for a daily routine; no hour unless one between 0 and 23 was given."""
    local = (now or datetime.now(UTC)).astimezone()
    if every == "weekly":
        day = day if day and 1 <= day <= 7 else local.isoweekday()
    elif every == "monthly":
        day = min(day, 28) if day and day >= 1 else min(local.day, 28)
    else:
        day = None
    return day, hour if hour is not None and 0 <= hour <= 23 else None


def routine(conn: sqlite3.Connection, task_id: int, every: str, day: int | None = None, hour: int | None = None,
            now: datetime | None = None) -> dict:
    """Make a job a routine: done afresh every day, every week on a weekday (1 is Monday) or every month on
    a day (1 to 28; later days become the 28th), at an hour (local; ROUTINE_HOUR if not said). A weekday or
    day not given is today's."""
    if every not in ROUTINE_EVERY:
        raise ValueError("A routine runs daily, weekly or monthly.")
    now = now or datetime.now(UTC)
    day, hour = routine_slot(every, day, hour, now)
    with db.write_lock(conn):
        _check(conn, task_id)
        _upsert(conn, task_id, "routine", every, next_run(every, day, hour, now), None, day, hour)
        tasks.add_step(conn, task_id, "watch", f"Routine: {when_text(every, day, hour)}. It does the job afresh "
                       "each time")
    w = get(conn, task_id)
    assert w
    return w


def stop(conn: sqlite3.Connection, task_id: int) -> None:
    with db.write_lock(conn):
        cur = conn.execute("UPDATE assistant_watches SET stopped_at = ? WHERE task_id = ? AND stopped_at IS NULL "
                           "RETURNING kind", (db.now(), task_id))
        row = cur.fetchone()
        if not row:
            raise LookupError("That job isn't being watched or run as a routine.")
        tasks.add_step(conn, task_id, "watch",
                       "Stopped the routine" if row["kind"] == "routine" else "Stopped watching")


def seen(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE assistant_watches SET unseen = 0 WHERE task_id = ?", (task_id,))


def look_now(conn: sqlite3.Connection, task_id: int, now: datetime | None = None) -> int:
    """Look again (or run the routine) now, whatever the schedule. Returns the round's job id."""
    if get(conn, task_id) is None:
        raise LookupError("That job isn't being watched or run as a routine.")
    with db.write_lock(conn):
        t = conn.execute("SELECT status FROM assistant_tasks WHERE id = ?", (task_id,)).fetchone()
        if t["status"] == "working":
            raise ValueError("It's already working on it.")
        if t["status"] == "needs_you":
            raise ValueError("Answer its question first.")
        return _start(conn, task_id, now or datetime.now(UTC))


def _start(conn: sqlite3.Connection, task_id: int, now: datetime) -> int:
    """(Inside the caller's write lock.)"""
    w = conn.execute("SELECT * FROM assistant_watches WHERE task_id = ? AND stopped_at IS NULL", (task_id,)).fetchone()
    routine_ = w["kind"] == "routine"
    after = next_run(w["every"], w["day"], w["hour"], now) if routine_ else now + EVERY[w["every"]]
    conn.execute("UPDATE assistant_watches SET next_at = ? WHERE id = ?", (_utc(after), w["id"]))
    return tasks.queue_turn(conn, task_id, watch=not routine_, routine=routine_)


def due(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Start every watch and routine whose time has come (and whose job isn't busy or waiting on the owner)."""
    now = now or datetime.now(UTC)
    started = waiting = 0
    with db.write_lock(conn):
        for r in conn.execute(
                "SELECT w.task_id, t.status FROM assistant_watches w JOIN assistant_tasks t ON t.id = w.task_id "
                "WHERE w.stopped_at IS NULL AND t.deleted_at IS NULL AND w.next_at <= ? ORDER BY w.next_at",
                (_utc(now),)).fetchall():
            if r["status"] in ("working", "needs_you"):
                waiting += 1
                continue
            _start(conn, r["task_id"], now)
            started += 1
    return {"started": started, "waiting": waiting}


def record(conn: sqlite3.Connection, task_id: int, changed: bool, change: str) -> None:
    """What a watch's look found (inside the round's write lock)."""
    now = db.now()
    if changed and change:
        conn.execute("UPDATE assistant_watches SET last_check_at = ?, last_change = ?, last_change_at = ?, unseen = 1 "
                     "WHERE task_id = ?", (now, change, now, task_id))
        tasks.add_step(conn, task_id, "changed", change)
    else:
        conn.execute("UPDATE assistant_watches SET last_check_at = ? WHERE task_id = ?", (now, task_id))
        tasks.add_step(conn, task_id, "unchanged", "Looked again: nothing that matters has changed")


def ran(conn: sqlite3.Connection, task_id: int, summary: str) -> None:
    """A routine's run came back (inside the round's write lock): new results, unseen until opened."""
    now = db.now()
    conn.execute("UPDATE assistant_watches SET last_check_at = ?, last_change = ?, last_change_at = ?, unseen = 1 "
                 "WHERE task_id = ?", (now, summary or None, now, task_id))


def changed(conn: sqlite3.Connection) -> list[dict]:
    """Watched jobs with a change, and routines with results, the owner hasn't opened yet, newest first."""
    return [{"task_id": r["task_id"], "kind": r["kind"], "title": r["title"] or r["request"][:60],
             "change": r["last_change"], "at": r["last_change_at"]} for r in conn.execute(
        "SELECT w.*, t.title, t.request FROM assistant_watches w JOIN assistant_tasks t ON t.id = w.task_id "
        "WHERE w.stopped_at IS NULL AND w.unseen = 1 AND t.deleted_at IS NULL ORDER BY w.last_change_at DESC")]


@jobs.handler("assistant.watches", every=CHECK)
def watches_job(conn: sqlite3.Connection, payload: dict) -> dict[str, Any]:
    return due(conn)
