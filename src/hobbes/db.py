"""The catalog: one SQLite file. The schema only ever grows, one migration at a time, tracked in
PRAGMA user_version. A migration that has been deployed is never edited, and tables are never dropped
or rebuilt; anything removed from the app stays in the file."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import config

MIGRATIONS: list[str] = [
    # 1: the catalog as first released
    """
    -- background jobs, AI runs, settings
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',      -- queued, running, done, failed
        payload TEXT NOT NULL DEFAULT '{}',
        result TEXT,
        error TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        created_at TEXT NOT NULL,
        run_after TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX jobs_status ON jobs (status, run_after);
    CREATE INDEX jobs_kind ON jobs (kind, finished_at);

    CREATE TABLE ai_runs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        started_at TEXT NOT NULL,
        duration_ms INTEGER,
        ok INTEGER NOT NULL DEFAULT 0,
        images INTEGER NOT NULL DEFAULT 0,
        search INTEGER NOT NULL DEFAULT 0,
        error TEXT
    );

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    -- diet (foods, meals, goals), Apple Health samples, the change log behind Undo
    CREATE TABLE changes (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,             -- e.g. item.edit, item.delete, meal.delete
        target TEXT NOT NULL,           -- e.g. meal_items:12
        before TEXT NOT NULL,           -- the row as it was (JSON)
        after TEXT,                     -- the row afterwards (JSON), when there is one
        undone_at TEXT
    );

    CREATE TABLE foods (
        id TEXT PRIMARY KEY,            -- the source's own code, e.g. indb:ASC001, ifct:A001, mine:3
        source TEXT NOT NULL,
        name TEXT NOT NULL,
        aliases TEXT NOT NULL DEFAULT '',
        grp TEXT NOT NULL DEFAULT '',
        kcal REAL NOT NULL,             -- per 100 g, like the other nutrients
        protein REAL NOT NULL,
        carbs REAL NOT NULL,
        fat REAL NOT NULL,
        fibre REAL,
        servings TEXT NOT NULL DEFAULT '[]',
        hidden INTEGER NOT NULL DEFAULT 0,   -- no longer in the bundled data; kept for meals that use it
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE meals (
        id INTEGER PRIMARY KEY,
        eaten_at TEXT NOT NULL,         -- ISO time with the offset of the device it was logged on
        day TEXT NOT NULL,              -- that device's local date
        slot TEXT NOT NULL,             -- breakfast, lunch, snack, dinner
        note TEXT NOT NULL DEFAULT '',
        photos INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'analysing',   -- analysing, ready, failed
        job_id INTEGER,
        title TEXT NOT NULL DEFAULT '',
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    );
    CREATE INDEX meals_day ON meals (day);

    CREATE TABLE meal_items (
        id INTEGER PRIMARY KEY,
        meal_id INTEGER NOT NULL REFERENCES meals (id),
        position INTEGER NOT NULL DEFAULT 0,
        name TEXT NOT NULL,
        food_id TEXT REFERENCES foods (id),
        portion TEXT NOT NULL DEFAULT '',
        grams REAL NOT NULL,
        kcal REAL NOT NULL,
        protein REAL NOT NULL,
        carbs REAL NOT NULL,
        fat REAL NOT NULL,
        fibre REAL,
        per100 TEXT NOT NULL,           -- the per-100 g values used (JSON)
        basis TEXT NOT NULL,            -- table (from foods) or estimate (the AI's own)
        confidence TEXT NOT NULL DEFAULT 'medium',
        ai TEXT,                        -- what the AI read, kept as it was (JSON)
        edited_at TEXT,
        created_at TEXT NOT NULL,
        deleted_at TEXT
    );
    CREATE INDEX meal_items_meal ON meal_items (meal_id);


    CREATE TABLE diet_goals (
        id INTEGER PRIMARY KEY,         -- a new row for every change; the latest applies
        goal TEXT NOT NULL,             -- lose, maintain, gain
        rate REAL NOT NULL DEFAULT 0,   -- kg per week
        activity TEXT NOT NULL DEFAULT 'light',
        eat_back REAL NOT NULL DEFAULT 0.5,
        protein_per_kg REAL NOT NULL DEFAULT 1.6,
        kcal_override INTEGER,
        protein_override INTEGER,
        created_at TEXT NOT NULL
    );

    CREATE TABLE health_samples (
        id INTEGER PRIMARY KEY,
        type TEXT NOT NULL,             -- weight, body_fat, lean_mass, height, active_energy, resting_energy, steps
        start TEXT NOT NULL,
        end TEXT,
        day TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        daily INTEGER NOT NULL DEFAULT 0,   -- a whole day's total rather than one reading
        source TEXT NOT NULL DEFAULT '',
        received_at TEXT NOT NULL,
        UNIQUE (type, start, source, daily)
    );
    CREATE INDEX health_day ON health_samples (type, day);

    CREATE TABLE health_syncs (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        format TEXT NOT NULL,
        received INTEGER NOT NULL,
        stored INTEGER NOT NULL,
        skipped INTEGER NOT NULL,
        note TEXT
    );

    -- the share of calories from fat, which sets the fat and carb targets
    ALTER TABLE diet_goals ADD COLUMN fat_pct REAL NOT NULL DEFAULT 0.3;

    -- workouts (from WHOOP), with minutes in each heart-rate zone
    CREATE TABLE workouts (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        sport TEXT NOT NULL,
        start TEXT NOT NULL,
        end TEXT,
        day TEXT NOT NULL,
        minutes REAL,
        strain REAL,
        kcal REAL,
        avg_hr REAL,
        max_hr REAL,
        zones TEXT NOT NULL DEFAULT '{}',   -- minutes in zones 0-5 (JSON)
        distance_m REAL,
        received_at TEXT NOT NULL,
        UNIQUE (source, source_id)
    );
    CREATE INDEX workouts_day ON workouts (day);

    -- the assistant: tasks and their step log, the owner's profile, and suggestions for it
    CREATE TABLE assistant_tasks (
        id INTEGER PRIMARY KEY,
        request TEXT NOT NULL,          -- what the owner asked for, as written
        title TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'working',   -- working, needs_you, done, failed, cancelled
        question TEXT,                  -- the one question it's waiting on (JSON), when needs_you
        result TEXT,                    -- the latest result (JSON): summary, options, assumptions, actions
        error TEXT,
        turns INTEGER NOT NULL DEFAULT 0,   -- rounds of work queued so far; a round runs as one job
        job_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        finished_at TEXT,
        deleted_at TEXT
    );
    CREATE INDEX assistant_tasks_status ON assistant_tasks (status, updated_at);

    CREATE TABLE assistant_steps (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES assistant_tasks (id),
        at TEXT NOT NULL,
        kind TEXT NOT NULL,     -- asked, answer, refine, retry, started, step, result, question, failed, stopped
        text TEXT NOT NULL,
        data TEXT                       -- more detail (JSON), e.g. the whole result of a round
    );
    CREATE INDEX assistant_steps_task ON assistant_steps (task_id, id);

    CREATE TABLE assistant_facts (
        id INTEGER PRIMARY KEY,
        topic TEXT NOT NULL,            -- travel, stays, budget, food, people, ids, other
        label TEXT NOT NULL,            -- e.g. Home airport
        value TEXT NOT NULL DEFAULT '', -- empty for a secret, which lives in the Keychain
        secret INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    );

    CREATE TABLE assistant_suggestions (
        id INTEGER PRIMARY KEY,
        task_id INTEGER REFERENCES assistant_tasks (id),
        topic TEXT NOT NULL,
        label TEXT NOT NULL,
        value TEXT NOT NULL,
        why TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',      -- open, accepted, dismissed
        fact_id INTEGER REFERENCES assistant_facts (id),
        created_at TEXT NOT NULL,
        decided_at TEXT
    );

    -- assistant watches: a job looked at again on a schedule, and what changed
    CREATE TABLE assistant_watches (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL UNIQUE REFERENCES assistant_tasks (id),
        every TEXT NOT NULL,                -- daily, weekly
        next_at TEXT NOT NULL,              -- UTC: when it next looks again
        last_check_at TEXT,
        last_change TEXT,                   -- what changed last time something did, in a sentence
        last_change_at TEXT,
        unseen INTEGER NOT NULL DEFAULT 0,  -- a change the owner hasn't opened yet
        created_at TEXT NOT NULL,
        stopped_at TEXT                     -- no longer watched (kept)
    );
    CREATE INDEX assistant_watches_due ON assistant_watches (stopped_at, next_at);

    -- a watch can carry the owner's condition ("under 1,200"); a routine is a job done afresh on a schedule
    ALTER TABLE assistant_watches ADD COLUMN kind TEXT NOT NULL DEFAULT 'watch';  -- watch, routine
    ALTER TABLE assistant_watches ADD COLUMN condition TEXT;  -- watch: when to tell the owner, in their words
    ALTER TABLE assistant_watches ADD COLUMN day INTEGER;     -- routine: weekday 1-7 (Monday 1), or day of month
    ALTER TABLE assistant_watches ADD COLUMN hour INTEGER;    -- routine: local hour it runs

    -- devices that get notifications (Web Push); each one's push address and keys are in the Keychain
    CREATE TABLE push_devices (
        id INTEGER PRIMARY KEY,
        label TEXT NOT NULL,                -- "iPhone", "Mac": a name for the owner
        endpoint_hash TEXT NOT NULL UNIQUE, -- sha256 of its push address, to know it again
        host TEXT NOT NULL,                 -- the push service, e.g. web.push.apple.com
        created_at TEXT NOT NULL,
        last_ok_at TEXT,
        last_error TEXT,
        removed_at TEXT                     -- turned off, or the push service said it's gone (kept)
    );

    -- the owner's Claude Code and Codex sessions on this Mac, as last seen (read only; see sessions.py)
    CREATE TABLE coding_sessions (
        id INTEGER PRIMARY KEY,
        tool TEXT NOT NULL,                 -- claude, codex
        session_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        cwd TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT '',      -- claude: interactive, background; codex: cli, vscode, appServer
        state TEXT NOT NULL,                -- working, waiting, idle, error, ended
        waiting_for TEXT,                   -- "permission prompt", "approval", ...
        open_with TEXT,                     -- what to type at the Mac to open it
        started_at TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,         -- last seen live
        state_since TEXT NOT NULL,          -- when it entered its current state (as far as the dashboard saw)
        ended_at TEXT,
        UNIQUE (tool, session_id)
    );

    -- a meal's "Why these numbers?" from the AI, kept until the meal changes (diet/explain.py)
    ALTER TABLE meals ADD COLUMN explanation TEXT;  -- JSON: for (a fingerprint of the meal), at, summary, items

    -- caffeine and alcohol in each item, for the amount eaten (diet/drinks.py); NULL until worked out
    ALTER TABLE meal_items ADD COLUMN caffeine REAL;  -- mg
    ALTER TABLE meal_items ADD COLUMN alcohol REAL;   -- grams of pure alcohol (a UK unit is 8 g)
    """,
]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    """A connection with the schema up to date. Autocommit: writes that belong together go in
    `with write_lock(conn):`."""
    if path is None:
        config.secure_home()
        path = config.db_path()
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    migrate(conn)
    config.private(path)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise RuntimeError(f"The catalog is from a newer version of the dashboard (schema {version}).")
    for n in range(version, len(MIGRATIONS)):
        with write_lock(conn):
            for statement in _statements(MIGRATIONS[n]):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {n + 1}")
    return len(MIGRATIONS)


def _statements(script: str) -> list[str]:
    """Split a migration into statements, so they run inside one transaction (executescript would
    commit first)."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


@contextmanager
def write_lock(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A transaction that takes the write lock up front (BEGIN IMMEDIATE), for check-then-write."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def backup(conn: sqlite3.Connection, dest: Path) -> Path:
    """A consistent copy of the catalog, safe while the app is running. Never overwrites a file."""
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    config.private(dest)
    return dest


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
