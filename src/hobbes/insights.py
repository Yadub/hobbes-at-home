"""The Health page: how the last week compares with the four weeks before, the owner's activities, the
everyday factors WHOOP Age is built from, and (on request) the AI's view of what to focus on.

WHOOP doesn't share WHOOP Age itself through its API, so the page shows the factors behind it, measured
against public guidance: 7-9 hours of sleep (AASM), at least 150 minutes a week of moderate activity or
75 of vigorous, or a mix (WHO, vigorous minutes counting double), muscle strengthening on at least two
days a week (WHO), and about 8,000 steps a day. Heart-rate zone minutes come from logged workouts only
(WHOOP's API has no all-day zone time).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from statistics import mean

from . import ai, db, health, jobs, whoop
from .diet import targets

# key, label, unit, which way is better (up, down, goal: follows the diet goal, None: neither), decimals,
# reading types to use (first found), whether today is still filling up (so the week ends yesterday)
METRICS: list[tuple[str, str, str, str | None, int, tuple[str, ...], bool]] = [
    ("recovery", "Recovery", "%", "up", 0, ("recovery",), False),
    ("hrv", "Heart rate variability", "ms", "up", 0, ("hrv_rmssd", "hrv"), False),
    ("resting_hr", "Resting heart rate", "bpm", "down", 0, ("resting_hr",), False),
    ("sleep", "Sleep", "h", "up", 1, ("sleep",), False),
    ("sleep_consistency", "Sleep consistency", "%", "up", 0, ("sleep_consistency",), False),
    ("strain", "Day strain", "", None, 1, ("strain",), True),
    ("steps", "Steps", "", "up", 0, ("steps",), True),
    ("energy", "Energy burned", "kcal", None, 0, ("total_energy", "active_energy"), True),
    ("weight", "Weight", "kg", "goal", 1, ("weight",), False),
]
# Muscle-strengthening sports (WHO counts any activity that works the major muscle groups against resistance)
STRENGTH = re.compile(r"weight|strength|functional|powerlifting|crossfit|calisthenics|bodybuilding|climbing|bouldering",
                      re.I)


def _series(conn: sqlite3.Connection, types: tuple[str, ...], since: str) -> tuple[str | None, list[dict]]:
    for t in types:
        s = health.series(conn, t, since)
        if s:
            return t, s
    return None, []


def _avg(points: list[dict], start: str, end: str) -> float | None:
    vals = [p["value"] for p in points if start <= p["day"] <= end]
    return mean(vals) if vals else None


def metric(conn: sqlite3.Connection, key: str, today: str, days: int = 90) -> dict:
    spec = next(m for m in METRICS if m[0] == key)
    _, label, unit, better, decimals, types, partial = spec
    t = date.fromisoformat(today)
    since = (t - timedelta(days=days - 1)).isoformat()
    used, points = _series(conn, types, since)
    last = t - timedelta(days=1) if partial else t
    recent = _avg(points, (last - timedelta(days=6)).isoformat(), last.isoformat())
    base = _avg(points, (last - timedelta(days=34)).isoformat(), (last - timedelta(days=7)).isoformat())
    change = pct = None
    status = "none"
    if recent is not None and base is not None:
        change = recent - base
        pct = 100 * change / base if base else None
        small = abs(change) < 0.3 if key == "weight" else (pct is not None and abs(pct) < 3)
        if better == "goal":
            goal = targets.goal(conn)["goal"]
            better = {"lose": "down", "gain": "up"}.get(goal)
            if better is None:  # maintaining: staying put is the aim
                status = "better" if small else "worse"
        if status == "none":
            if small or better is None:
                status = "same" if small else "neutral"
            else:
                status = "better" if (change > 0) == (better == "up") else "worse"
    return {"key": key, "label": label, "unit": unit, "decimals": decimals, "source": used,
            "recent": round(recent, decimals + 1) if recent is not None else None,
            "baseline": round(base, decimals + 1) if base is not None else None,
            "change": round(change, decimals + 1) if change is not None else None,
            "pct": round(pct, 1) if pct is not None else None, "status": status,
            "latest": points[-1] if points else None,
            "points": [p for p in points if p["day"] >= (t - timedelta(days=29)).isoformat()]}


def activities(conn: sqlite3.Connection, today: str) -> dict:
    t = date.fromisoformat(today)
    since = (t - timedelta(days=29)).isoformat()
    before = (t - timedelta(days=59)).isoformat()
    by_sport = [dict(r) for r in conn.execute(
        "SELECT sport, COUNT(*) AS sessions, ROUND(SUM(minutes)) AS minutes, ROUND(AVG(strain), 1) AS strain, "
        "ROUND(SUM(kcal)) AS kcal FROM workouts WHERE day >= ? GROUP BY sport ORDER BY SUM(minutes) DESC", (since,))]
    recent = [dict(r) for r in conn.execute(
        "SELECT sport, day, start, minutes, strain, kcal, avg_hr FROM workouts ORDER BY start DESC LIMIT 8")]
    totals = {}
    windows = {"last_30": (since, today), "previous_30": (before, (t - timedelta(days=30)).isoformat())}
    for name, (a, b) in windows.items():
        r = conn.execute("SELECT COUNT(*), COALESCE(SUM(minutes), 0) FROM workouts WHERE day BETWEEN ? AND ?",
                         (a, b)).fetchone()
        totals[name] = {"sessions": r[0], "minutes": round(r[1])}
    return {"by_sport": by_sport, "recent": recent, "totals": totals}


def _status(value: float | None, aim: float, close: float) -> str:
    if value is None:
        return "unknown"
    return "met" if value >= aim else "close" if value >= close else "below"


def drivers(conn: sqlite3.Connection, today: str) -> list[dict]:
    """The factors WHOOP Age is built from, over the last four weeks (those with data), against public guidance."""
    t = date.fromisoformat(today)
    since = (t - timedelta(days=27)).isoformat()
    _, sleep = _series(conn, ("sleep",), since)
    _, consistency = _series(conn, ("sleep_consistency",), since)
    _, steps = _series(conn, ("steps",), since)
    hours = mean(p["value"] for p in sleep) if sleep else None
    cons = mean(p["value"] for p in consistency) if consistency else None
    daily_steps = mean(p["value"] for p in steps if p["day"] < today) if steps else None
    zones = {str(i): 0.0 for i in range(6)}
    strength_days: set[str] = set()
    for w in conn.execute("SELECT sport, day, zones FROM workouts WHERE day >= ?", (since,)):
        for k, v in json.loads(w["zones"] or "{}").items():
            zones[k] = zones.get(k, 0) + float(v or 0)
        if STRENGTH.search(w["sport"]):
            strength_days.add(w["day"])
    # Weeks with data, so days before WHOOP or the iPhone sent anything (or while they didn't) don't count as rest
    covered = {r[0] for r in conn.execute("SELECT DISTINCT day FROM health_samples WHERE day >= ? AND day <= ? "
                                          "UNION SELECT DISTINCT day FROM workouts WHERE day >= ? AND day <= ?",
                                          (since, today, since, today))}
    weeks = min(4.0, max(1.0, len(covered) / 7))
    moderate = (zones["2"] + zones["3"]) / weeks
    vigorous = (zones["4"] + zones["5"]) / weeks
    who_minutes = moderate + 2 * vigorous
    sleep_status = "unknown" if hours is None else "met" if 7 <= hours <= 9 else "close" if hours >= 6.5 else "below"
    return [
        {"key": "sleep_hours", "label": "Hours of sleep", "value": round(hours, 1) if hours else None,
         "unit": "h a night", "aim": "7–9 h", "status": sleep_status},
        {"key": "sleep_consistency", "label": "Sleep consistency", "value": round(cons) if cons else None, "unit": "%",
         "aim": "80% or more", "status": _status(cons, 80, 70)},
        {"key": "cardio", "label": "Cardio minutes", "value": round(who_minutes), "unit": "a week",
         "aim": "150–300 (vigorous counts double)", "status": _status(who_minutes, 150, 100),
         "detail": f"{round(moderate)} min in zones 2–3 and {round(vigorous)} min in zones 4–5 a week, in workouts"},
        {"key": "strength", "label": "Strength training", "value": round(len(strength_days) / weeks, 1),
         "unit": "days a week", "aim": "2 or more", "status": _status(len(strength_days) / weeks, 2, 1),
         "detail": "Counts weights, functional fitness and climbing"},
        {"key": "steps", "label": "Daily steps", "value": round(daily_steps) if daily_steps else None, "unit": "a day",
         "aim": "8,000 or more", "status": _status(daily_steps, 8000, 6000)},
    ]


def overview(conn: sqlite3.Connection, today: str) -> dict:
    coach = db.get_setting(conn, "health.coach")
    return {"today": today, "metrics": [metric(conn, m[0], today) for m in METRICS],
            "activities": activities(conn, today), "drivers": drivers(conn, today),
            "coach": json.loads(coach) if coach else None}


COACH_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "focus": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "why": {"type": "string"}, "how": {"type": "string"},
                           "impact": {"type": "string", "enum": ["high", "medium", "low"]}},
            "required": ["title", "why", "how", "impact"], "additionalProperties": False}},
    },
    "required": ["summary", "focus"],
    "additionalProperties": False,
}


def _brief(o: dict) -> dict:
    """The overview without the day-by-day points, for the AI."""
    return {"metrics": [{k: v for k, v in m.items() if k not in ("points", "latest")} for m in o["metrics"]],
            "drivers": o["drivers"],
            "activities": {"by_sport": o["activities"]["by_sport"], "totals": o["activities"]["totals"]}}


@jobs.handler("health.coach")
def coach_job(conn: sqlite3.Connection, payload: dict) -> dict:
    if not whoop.shared_with_ai(conn):
        raise ai.AIError(whoop.NOT_SHARED)
    o = overview(conn, payload["today"])
    g = targets.goal(conn)
    prompt = "\n".join([
        "You are a careful health coach. Do not run any commands. Using this person's own data below (from their "
        "WHOOP and their food log), say what to focus on for the biggest effect on long-term health and on WHOOP "
        "Age, which WHOOP builds from sleep hours and consistency, time in heart-rate zones 1-3 and 4-5, strength "
        "training, daily steps, VO2 max, resting heart rate, heart rate variability and lean body mass.",
        "Give a two-sentence summary of how their last week went against the four weeks before (name what went "
        "up and down), then three to five focus points, most impactful first. Each: a short title, why (citing "
        "their numbers), how (concrete, for this week), and impact. Be specific and plain; no medical claims.",
        f"Their diet goal: {g['goal']} {g['rate']} kg a week.",
        "Data (recent = last 7 days, baseline = the 28 days before; zone minutes are from logged workouts only):",
        json.dumps(_brief(o)),
    ])
    answer = ai.ask(prompt, schema=COACH_SCHEMA, kind="health.coach", timeout=240, conn=conn)
    result = {**answer, "at": db.now()}
    db.set_setting(conn, "health.coach", json.dumps(result))
    return result


def metric_detail(conn: sqlite3.Connection, key: str, today: str, days: int) -> dict:
    m = metric(conn, key, today, days=max(days, 35))
    spec = next(x for x in METRICS if x[0] == key)
    since = (date.fromisoformat(today) - timedelta(days=days - 1)).isoformat()
    _, points = _series(conn, spec[5], since)
    return {**m, "points": points}


def keys() -> list[str]:
    return [m[0] for m in METRICS]
