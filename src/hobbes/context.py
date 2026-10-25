"""The owner's life right now, in one compact snapshot: what's left to eat, how they slept and recovered,
and assistant jobs waiting on them.

Hobbes AI reads it with every job, so it works from the owner's real day. Each part is gathered on its own:
one that fails (or a feature not set up yet) is left out with a note, and never stops the rest.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from . import health, insights, whoop


def _diet(conn: sqlite3.Connection, day: str) -> dict:
    from .diet import meals

    s = meals.day_summary(conn, day)
    t = s["targets"]
    return {"eaten": {k: round(v) for k, v in s["eaten"].items() if v is not None},
            "targets": {k: t.get(k) for k in ("kcal", "protein", "carbs", "fat", "fibre")} if t["ready"] else None,
            "left": s["left"] if t["ready"] else None,
            "meals": [m["title"] or m["note"] for m in s["meals"]][:8],
            "goal": f"{t['goal']['goal']} {t['goal']['rate']} kg a week"}


def _health(conn: sqlite3.Connection, day: str) -> dict:
    if not whoop.shared_with_ai(conn):
        raise PermissionError(whoop.NOT_SHARED)
    o = insights.overview(conn, day)
    today = {}
    for kind in ("recovery", "sleep", "hrv_rmssd", "resting_hr", "strain", "steps"):
        r = health.latest(conn, kind)
        if r and r["day"] == day:
            v = health.day_total(conn, kind, day) if kind in health.CUMULATIVE else r["value"]
            if v is not None:
                today[kind] = round(v, 1)
    return {
        "today": today,
        "trends_last_7_days_vs_4_weeks": [
            {"measure": m["label"], "recent": m["recent"], "before": m["baseline"], "change_pct": m["pct"],
             "status": m["status"]} for m in o["metrics"] if m["recent"] is not None],
        "whoop_age_factors": [{"factor": d["label"], "value": d["value"], "aim": d["aim"], "status": d["status"]}
                              for d in o["drivers"]],
        "recent_workouts": [{"sport": w["sport"], "day": w["day"], "minutes": w["minutes"]}
                            for w in o["activities"]["recent"][:5]],
    }


def _assistant(conn: sqlite3.Connection, day: str) -> dict:
    from .assistant import tasks, watches

    open_ = [t for t in tasks.listing(conn, limit=30) if t["status"] in ("needs_you", "working", "failed")]
    unseen = watches.changed(conn)
    changed = [{"title": c["title"], "change": c["change"]} for c in unseen if c["kind"] == "watch"][:5]
    routines = [{"title": c["title"], "summary": c["change"]} for c in unseen if c["kind"] == "routine"][:5]
    return {"jobs": [{"title": t["title"] or t["request"][:80], "status": t["status"]} for t in open_[:8]],
            "watched_jobs_that_changed": changed, "routines_with_new_results": routines}


PARTS = {"diet": _diet, "health": _health, "assistant": _assistant}


def snapshot(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    day = now.date().isoformat()
    out: dict[str, Any] = {"now": now.strftime("%A %d %B %Y, %H:%M"), "day": day}
    missing = []
    for name, fn in PARTS.items():
        try:
            out[name] = fn(conn, day)
        except Exception:  # a part that isn't set up, or fails, is left out
            missing.append(name)
    if missing:
        out["not_available"] = missing
    return out


def as_text(snap: dict[str, Any], limit: int = 6000) -> str:
    """The snapshot as compact JSON for a prompt, cut to a size that keeps prompts quick."""
    import json

    text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"), default=str)
    return text if len(text) <= limit else text[:limit] + "…"
