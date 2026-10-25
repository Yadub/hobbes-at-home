"""The change log behind Undo. Every edit or removal the owner makes records the row as it was, so it
can be put back. Nothing the owner made is ever deleted from the catalog: removals set `deleted_at`."""

from __future__ import annotations

import json
import sqlite3

from . import db

# Tables Undo may write to, and the columns it restores.
_TABLES = {
    "meal_items": ("name", "food_id", "portion", "grams", "kcal", "protein", "carbs", "fat", "fibre", "per100",
                   "basis", "confidence", "ai", "edited_at", "deleted_at", "caffeine", "alcohol"),
    "meals": ("eaten_at", "day", "slot", "note", "title", "deleted_at"),
    "assistant_tasks": ("deleted_at",),
    "assistant_facts": ("topic", "label", "value", "deleted_at"),
    "assistant_suggestions": ("status", "decided_at"),
}


def row(conn: sqlite3.Connection, table: str, row_id: int) -> dict | None:
    assert table in _TABLES
    r = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(r) if r else None


def record(conn: sqlite3.Connection, kind: str, table: str, row_id: int, before: dict, after: dict | None) -> int:
    cur = conn.execute("INSERT INTO changes (at, kind, target, before, after) VALUES (?, ?, ?, ?, ?)",
                       (db.now(), kind, f"{table}:{row_id}", json.dumps(before),
                        json.dumps(after) if after is not None else None))
    assert cur.lastrowid is not None
    return cur.lastrowid


def undo(conn: sqlite3.Connection, change_id: int) -> dict:
    """Put a row back as it was before this change. Refused when something changed it again since,
    so a later edit is never silently lost."""
    with db.write_lock(conn):
        ch = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
        if not ch:
            raise LookupError("There's no such change.")
        if ch["undone_at"]:
            raise ValueError("That change has already been undone.")
        table, _, rid = ch["target"].partition(":")
        later = conn.execute("SELECT 1 FROM changes WHERE target = ? AND id > ? AND undone_at IS NULL",
                             (ch["target"], change_id)).fetchone()
        if later:
            raise ValueError("It has been changed again since, so this can't be undone.")
        before = json.loads(ch["before"])
        cols = _TABLES[table]
        conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                     [before.get(c) for c in cols] + [int(rid)])
        conn.execute("UPDATE changes SET undone_at = ? WHERE id = ?", (db.now(), change_id))
    return {"table": table, "id": int(rid), "kind": ch["kind"]}
