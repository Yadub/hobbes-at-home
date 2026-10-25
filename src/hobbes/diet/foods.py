"""Foods from the food tables the dashboard used to bundle. The tables were removed (the owner trusts the
AI's estimate and products' labels instead), but the rows stay in the catalog because older meal items point
at them (`meal_items.food_id`). Values are per 100 g."""

from __future__ import annotations

import json
import sqlite3

NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fibre")


def get(conn: sqlite3.Connection, food_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    return as_dict(r) if r else None


def as_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["servings"] = json.loads(d["servings"] or "[]")
    d["group"] = d.pop("grp")
    d["aliases"] = [a for a in (d["aliases"] or "").split("|") if a]
    return d
