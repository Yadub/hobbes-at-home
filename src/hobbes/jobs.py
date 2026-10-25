"""Background jobs: a table of work and a worker inside the app that runs it.

Anything slow or scheduled goes through here (AI calls, syncs, backups), so the web app answers at
once and nothing is lost if the Mac restarts mid-job: a job that was running is simply run again.
Failures are retried with a growing delay, then kept as failed with their error for the dashboard
to show.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import db

log = logging.getLogger("hobbes.jobs")

Handler = Callable[[sqlite3.Connection, dict], Any]
_HANDLERS: dict[str, Handler] = {}
_PERIODIC: dict[str, float] = {}


def handler(kind: str, every: float | None = None) -> Callable[[Handler], Handler]:
    """Register the function that runs jobs of this kind; `every` (seconds) also runs it on a schedule."""

    def wrap(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        if every:
            _PERIODIC[kind] = every
        return fn

    return wrap


def _at(seconds: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def enqueue(conn: sqlite3.Connection, kind: str, payload: dict | None = None, *,
            delay: float = 0, max_attempts: int = 3) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, payload, max_attempts, created_at, run_after) VALUES (?, ?, ?, ?, ?)",
        (kind, json.dumps(payload or {}), max_attempts, db.now(), _at(delay)))
    assert cur.lastrowid is not None
    return cur.lastrowid


def get(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return as_dict(row) if row else None


def as_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d["payload"] or "{}")
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [as_dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for status, n in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
        out[status] = n
    return out


def recover(conn: sqlite3.Connection) -> int:
    """Jobs left running when the app stopped go back in the queue."""
    return conn.execute("UPDATE jobs SET status = 'queued', run_after = ? WHERE status = 'running'",
                        (db.now(),)).rowcount


def _claim(conn: sqlite3.Connection) -> sqlite3.Row | None:
    with db.write_lock(conn):
        row = conn.execute("SELECT id FROM jobs WHERE status = 'queued' AND run_after <= ? ORDER BY id LIMIT 1",
                           (db.now(),)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = ?",
                     (db.now(), row["id"]))
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def run_one(conn: sqlite3.Connection) -> bool:
    """Run the next due job, if there is one. True when a job ran."""
    job = _claim(conn)
    if job is None:
        return False
    fn = _HANDLERS.get(job["kind"])
    try:
        if fn is None:
            raise LookupError(f"Nothing runs jobs of kind {job['kind']!r}.")
        result = fn(conn, json.loads(job["payload"] or "{}"))
    except Exception as e:  # a job's failure must never stop the worker
        log.warning("job %s (%s) failed: %s", job["id"], job["kind"], e)
        retry = fn is not None and job["attempts"] < job["max_attempts"]
        conn.execute("UPDATE jobs SET status = ?, error = ?, run_after = ?, finished_at = ? WHERE id = ?",
                     ("queued" if retry else "failed", _error_text(e), _at(30 * 2 ** (job["attempts"] - 1)),
                      None if retry else db.now(), job["id"]))
        return True
    conn.execute("UPDATE jobs SET status = 'done', result = ?, error = NULL, finished_at = ? WHERE id = ?",
                 (json.dumps(result) if result is not None else None, db.now(), job["id"]))
    return True


def _error_text(e: Exception) -> str:
    text = str(e) or e.__class__.__name__
    if not getattr(e, "user_facing", False):
        log.debug("".join(traceback.format_exception(e)))
    return text[:2000]


def schedule_due(conn: sqlite3.Connection) -> list[int]:
    """Queue each scheduled kind whose last run was long enough ago (and isn't already waiting)."""
    added = []
    for kind, every in _PERIODIC.items():
        waiting = conn.execute("SELECT 1 FROM jobs WHERE kind = ? AND status IN ('queued', 'running')",
                               (kind,)).fetchone()
        if waiting:
            continue
        last = conn.execute("SELECT MAX(finished_at) FROM jobs WHERE kind = ?", (kind,)).fetchone()[0]
        if last is None or last <= _at(-every):
            added.append(enqueue(conn, kind))
    return added


class Worker:
    """Runs jobs in the background while the app is up: `workers` at a time, each on its own
    connection, plus a scheduler for the periodic kinds."""

    def __init__(self, path: Path | None = None, workers: int = 2, poll: float = 1.0, schedule_every: float = 30):
        self.path, self.workers, self.poll, self.schedule_every = path, workers, poll, schedule_every
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()
        self._stopping = False

    def wake(self) -> None:
        """Something was just queued: don't wait for the next poll."""
        self._wake.set()

    async def start(self) -> None:
        conn = db.connect(self.path)
        recover(conn)
        conn.close()
        self._tasks = [asyncio.create_task(self._run(i)) for i in range(self.workers)]
        self._tasks.append(asyncio.create_task(self._schedule()))

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(self, _: int) -> None:
        conn = db.connect(self.path)
        try:
            while not self._stopping:
                try:
                    ran = await asyncio.to_thread(run_one, conn)
                except Exception:
                    log.exception("job worker")
                    ran = False
                if not ran:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), self.poll)
                    except TimeoutError:
                        pass
        finally:
            conn.close()

    async def _schedule(self) -> None:
        conn = db.connect(self.path)
        try:
            while not self._stopping:
                try:
                    if await asyncio.to_thread(schedule_due, conn):
                        self._wake.set()
                except Exception:
                    log.exception("job scheduler")
                await asyncio.sleep(self.schedule_every)
        finally:
            conn.close()
