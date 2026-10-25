"""Apple Health data, sent from the owner's iPhone (the Mac can't read Health itself).

The phone posts readings to /api/health/samples. Each reading is stored once (same type, start time
and source replaces the earlier value, which is how a day's running total grows), converted to one
unit per type: kg, cm, %, kcal, steps.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from . import db

# Canonical type -> unit. Cumulative types are summed over a day; the rest use the latest reading.
UNITS = {
    "weight": "kg", "body_fat": "%", "lean_mass": "kg", "height": "cm", "bmi": "",
    "active_energy": "kcal", "resting_energy": "kcal", "steps": "count",
    "resting_hr": "bpm", "hrv": "ms", "sleep": "h",
    # from WHOOP: energy burned over the whole day (resting and active), strain 0-21, recovery %, and HRV as
    # RMSSD (Apple Health's HRV is SDNN, a different measure, so the two are kept apart)
    "total_energy": "kcal", "strain": "", "recovery": "%", "hrv_rmssd": "ms",
    "sleep_consistency": "%", "sleep_performance": "%",
}
CUMULATIVE = {"active_energy", "resting_energy", "steps", "total_energy"}

# The many names Apple Health, Shortcuts and export apps use for the same thing.
_ALIASES = {
    "weight": ["weight", "body_mass", "bodymass", "weight_body_mass", "hkquantitytypeidentifierbodymass"],
    "body_fat": ["body_fat", "body_fat_percentage", "bodyfatpercentage", "hkquantitytypeidentifierbodyfatpercentage"],
    "lean_mass": ["lean_mass", "lean_body_mass", "leanbodymass", "hkquantitytypeidentifierleanbodymass"],
    "height": ["height", "hkquantitytypeidentifierheight"],
    "bmi": ["bmi", "body_mass_index", "bodymassindex", "hkquantitytypeidentifierbodymassindex"],
    "active_energy": ["active_energy", "active_energy_burned", "activeenergy", "activeenergyburned",
                      "hkquantitytypeidentifieractiveenergyburned"],
    "resting_energy": ["resting_energy", "basal_energy_burned", "basal_energy", "restingenergy", "basalenergyburned",
                       "hkquantitytypeidentifierbasalenergyburned"],
    "steps": ["steps", "step_count", "stepcount", "hkquantitytypeidentifierstepcount"],
    "resting_hr": ["resting_hr", "resting_heart_rate", "restingheartrate", "hkquantitytypeidentifierrestingheartrate"],
    "hrv": ["hrv", "heart_rate_variability", "heart_rate_variability_sdnn", "heartratevariabilitysdnn",
            "hkquantitytypeidentifierheartratevariabilitysdnn"],
    "sleep": ["sleep", "sleep_analysis", "total_sleep", "sleepanalysis"],
    "total_energy": ["total_energy"],
    "strain": ["strain"],
    "recovery": ["recovery", "recovery_score"],
    "hrv_rmssd": ["hrv_rmssd"],
    "sleep_consistency": ["sleep_consistency", "sleep_consistency_percentage"],
    "sleep_performance": ["sleep_performance", "sleep_performance_percentage"],
}
_LOOKUP = {alias: canon for canon, names in _ALIASES.items() for alias in names}


def canonical_type(name: str) -> str | None:
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return _LOOKUP.get(key) or _LOOKUP.get(key.replace("_", ""))


def convert(kind: str, value: float, unit: str) -> float | None:
    """A reading in the type's canonical unit, or None when the unit makes no sense for the type."""
    u = (unit or "").strip().lower().replace(" ", "")
    if kind in ("weight", "lean_mass"):
        factor = {"kg": 1, "": 1, "g": 0.001, "lb": 0.45359237, "lbs": 0.45359237, "st": 6.35029318}.get(u)
    elif kind == "height":
        factor = {"cm": 1, "": 1, "m": 100, "in": 2.54, "ft": 30.48, "mm": 0.1}.get(u)
    elif kind == "body_fat":
        if u in ("%", "percent", ""):
            return value * 100 if value <= 1 else value   # Shortcuts gives 0.21 for 21 %
        factor = None
    elif kind in ("active_energy", "resting_energy", "total_energy"):
        factor = {"kcal": 1, "cal": 1, "kilocalories": 1, "": 1, "kj": 1 / 4.184}.get(u)
    elif kind == "steps":
        factor = 1 if u in ("count", "steps", "") else None
    elif kind == "sleep":
        factor = {"h": 1, "hr": 1, "hrs": 1, "hours": 1, "": 1, "min": 1 / 60, "s": 1 / 3600}.get(u)
    else:
        factor = 1
    if factor is None:
        return None
    return value * factor


def number(v: object) -> float | None:
    """A reading's value, also from text formatted for the phone's locale ("9,412", "78,4")."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    t = str(v or "").strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace("'", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(",") < t.rfind(".") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = t.replace(",", "") if len(tail) == 3 and head.lstrip("-").isdigit() else head.replace(",", "") + "." + tail
    try:
        return float(t)
    except ValueError:
        return None


def parse_time(text: str) -> datetime | None:
    """ISO 8601, plus the "2026-10-17 08:02:00 +0530" style some exporters use."""
    t = (text or "").strip()
    if not t:
        return None
    for candidate in (t, t.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\s*([+-]\d{2}):?(\d{2})$", t)
    if m:
        try:
            return datetime.fromisoformat(f"{m[1]}T{m[2]}{m[3]}:{m[4]}")
        except ValueError:
            return None
    return None


def store(conn: sqlite3.Connection, samples: list[dict], fmt: str = "samples") -> dict:
    """Store readings: [{type, value, unit, start, end?, source?, daily?, day?}]. `day` files a reading under
    another date than its start's (a WHOOP day starts the evening before). Unknown types and readings that
    can't be read are skipped and counted, never guessed."""
    stored = skipped = 0
    now = db.now()
    with db.write_lock(conn):
        for s in samples:
            kind = canonical_type(str(s.get("type", "")))
            start = parse_time(str(s.get("start") or s.get("date") or ""))
            raw = number(s.get("value"))
            value = convert(kind, raw, str(s.get("unit") or "")) if kind and raw is not None else None
            if not kind or start is None or value is None:
                skipped += 1
                continue
            end = parse_time(str(s.get("end") or ""))
            day = str(s.get("day") or "") if _DAY.match(str(s.get("day") or "")) else start.date().isoformat()
            conn.execute(
                "INSERT INTO health_samples (type, start, end, day, value, unit, daily, source, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (type, start, source, daily) DO UPDATE SET "
                "value = excluded.value, end = excluded.end, day = excluded.day, unit = excluded.unit, "
                "received_at = excluded.received_at",
                (kind, start.isoformat(), end.isoformat() if end else None, day, round(value, 3),
                 UNITS[kind], int(bool(s.get("daily"))), str(s.get("source") or "")[:120], now))
            stored += 1
        conn.execute("INSERT INTO health_syncs (at, format, received, stored, skipped) VALUES (?, ?, ?, ?, ?)",
                     (now, fmt, len(samples), stored, skipped))
    return {"received": len(samples), "stored": stored, "skipped": skipped}


def latest(conn: sqlite3.Connection, kind: str, on_or_before: str | None = None) -> dict | None:
    q = "SELECT value, start, day, source FROM health_samples WHERE type = ?"
    args: list = [kind]
    if on_or_before:
        q += " AND day <= ?"
        args.append(on_or_before)
    r = conn.execute(q + " ORDER BY start DESC LIMIT 1", args).fetchone()
    return dict(r) if r else None


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def daily_row(conn: sqlite3.Connection, kind: str, day: str) -> dict | None:
    """A day's whole-day total of a type, with the span it covers. Totals from one source for different
    periods of the day (two WHOOP days ending on the same date) add up; when several sources sent one,
    the one heard from last is used, since they describe the same day."""
    rows = conn.execute("SELECT id, value, start, end, source, received_at FROM health_samples "
                        "WHERE type = ? AND day = ? AND daily = 1", (kind, day)).fetchall()
    if not rows:
        return None
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["source"], []).append(r)
    chosen = max(groups.values(), key=lambda g: max((r["received_at"], r["id"]) for r in g))
    ends = [r["end"] for r in chosen]
    return {"value": sum(r["value"] for r in chosen), "start": min(r["start"] for r in chosen),
            "end": None if any(e is None for e in ends) else max(ends), "source": chosen[0]["source"]}


def day_total(conn: sqlite3.Connection, kind: str, day: str) -> float | None:
    """A cumulative type's total for one day: the day's own total when one was sent (see daily_row),
    otherwise the sum of that day's readings."""
    daily = daily_row(conn, kind, day)
    if daily:
        return daily["value"]
    r = conn.execute("SELECT SUM(value), COUNT(*) FROM health_samples WHERE type = ? AND day = ? AND daily = 0",
                     (kind, day)).fetchone()
    return r[0] if r[1] else None


def series(conn: sqlite3.Connection, kind: str, since: str) -> list[dict]:
    """One value per day from `since`: the day's last reading (or total, for cumulative types)."""
    days = [r[0] for r in conn.execute("SELECT DISTINCT day FROM health_samples WHERE type = ? AND day >= ? "
                                       "ORDER BY day", (kind, since))]
    out = []
    for d in days:
        if kind in CUMULATIVE:
            v = day_total(conn, kind, d)
        else:
            r = conn.execute("SELECT value FROM health_samples WHERE type = ? AND day = ? ORDER BY start DESC LIMIT 1",
                             (kind, d)).fetchone()
            v = r[0] if r else None
        if v is not None:
            out.append({"day": d, "value": round(v, 2)})
    return out


def last_sync(conn: sqlite3.Connection) -> dict | None:
    r = conn.execute("SELECT * FROM health_syncs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None
