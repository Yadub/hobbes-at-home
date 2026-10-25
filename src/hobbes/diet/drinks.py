"""Caffeine and alcohol: how much is in what the owner logs, and how that compares.

Every reading gives each item's caffeine (mg) and alcohol (grams of pure alcohol) per 100 g, and the item keeps
them for the amount eaten (meal_items.caffeine and .alcohol). Items read before that are worked out once by the
AI (backfill), in batches, whenever tracking is on and some are missing. Tracking is a setting, on unless the
owner turns it off (Goals); when it's off nothing is shown, but new readings still carry the numbers.

Stats cover the last 7 and 30 days, averaged over the days with anything logged (days with nothing logged would
make the averages look lower than they are), against the guidance and typical figures in REFERENCE.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from .. import ai, changes, db, jobs, region
from . import meals

SETTING = "diet.track_drinks"
UNIT_G = 8.0  # a UK unit of alcohol: 8 g (10 ml) of pure alcohol
CAFFEINE_DAY_LIMIT = 400
BATCH = 40

# Figures to compare with, each with where it comes from. Alcohol in UK units a week, caffeine in mg a day. A
# figure with "countries" is shown only to owners who live there.
REFERENCE = {
    "caffeine": {
        "aim": 400,
        "aim_text": "Up to 400 mg a day for healthy adults, and no more than 200 mg at once (about two espressos). "
                    "Less in pregnancy (200 mg a day).",
        "aim_source": "European Food Safety Authority (2015)",
        "typical": [
            {"value": 150, "label": "Young adults in India", "countries": ["IN"],
             "source": "a study of 560 students in Telangana (2024); India has no national figure"},
            {"value": 230, "label": "US adults who have caffeine", "source": "NHANES 2011–16"},
        ],
    },
    "alcohol": {
        "aim": 14,
        "aim_text": "Up to 14 units a week, spread over three or more days, with several drink-free days. "
                    "The WHO says no amount of alcohol is without risk.",
        "aim_source": "UK Chief Medical Officers (2016)",
        "typical": [
            {"value": 9.3, "label": "Average adult in India", "countries": ["IN"],
             "source": "WHO, 2019: 4.9 litres of pure alcohol a year per adult, non-drinkers included"},
            {"value": 23.6, "label": "People who drink, worldwide", "source": "WHO: 27 g of alcohol a day"},
        ],
    },
}


def reference(conn: sqlite3.Connection) -> dict:
    code = region.get(conn)["country_code"]
    return {k: {**v, "typical": [t for t in v["typical"] if code in t.get("countries", [code])]}
            for k, v in REFERENCE.items()}


def enabled(conn: sqlite3.Connection) -> bool:
    """On unless the owner has turned it off."""
    return db.get_setting(conn, SETTING) != "0"


def set_enabled(conn: sqlite3.Connection, on: bool) -> bool:
    db.set_setting(conn, SETTING, "1" if on else "0")
    if on:
        queue_backfill(conn)
    return on


_MISSING = ("FROM meal_items i JOIN meals m ON m.id = i.meal_id WHERE i.deleted_at IS NULL AND m.deleted_at IS NULL "
            "AND (i.caffeine IS NULL OR i.alcohol IS NULL)")


def missing(conn: sqlite3.Connection) -> int:
    """Items whose caffeine and alcohol haven't been worked out yet."""
    return conn.execute(f"SELECT COUNT(*) {_MISSING}").fetchone()[0]


def queue_backfill(conn: sqlite3.Connection) -> int | None:
    if not missing(conn):
        return None
    queued = conn.execute("SELECT id FROM jobs WHERE kind = 'diet.drinks_backfill' AND status IN ('queued', 'running')"
                          ).fetchone()
    return queued[0] if queued else jobs.enqueue(conn, "diet.drinks_backfill", {}, max_attempts=2)


BACKFILL_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"ref": {"type": "string"}, "caffeine": {"type": "number"}, "alcohol": {"type": "number"}},
        "required": ["ref", "caffeine", "alcohol"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}

BACKFILL_PROMPT = """You add caffeine and alcohol to items already in someone's food diary. Do not run any commands.

They mostly eat and drink in {country}. For each item below (its name, the household measure, the grams eaten, which
is ml for a drink, and its energy per 100 g), give per 100 g as eaten:
- caffeine: mg (coffee, tea, cola, energy drinks, chocolate, pre-workouts); 0 when it has none. A cappuccino or
  latte is about 40 mg per 100 g, brewed coffee about 40, espresso about 200, tea about 20, cola about 10.
- alcohol: grams of pure alcohol, a drink's ABV % × 0.79 (3.9 for a 5% beer, 9.5 for 12% wine, 31.6 for a 40%
  spirit); 0 when it has none.
Typical values for what's named; ref exactly as given, one answer for every item.

Items (JSON):
{items}"""


def backfill(conn: sqlite3.Connection, max_batches: int = 10) -> dict:
    """Work out caffeine and alcohol for items that don't have them, BATCH at a time, recorded for Undo."""
    done, last_id = 0, 0
    for _ in range(max_batches):
        rows = conn.execute(f"SELECT i.id, i.name, i.portion, i.grams, i.per100 {_MISSING} AND i.id > ? "
                            "ORDER BY i.id LIMIT ?", (last_id, BATCH)).fetchall()
        if not rows:
            break
        last_id = rows[-1]["id"]
        listing = [{"ref": f"i{r['id']}", "name": r["name"], "portion": r["portion"], "grams": r["grams"],
                    "kcal_per_100g": json.loads(r["per100"]).get("kcal")} for r in rows]
        answer = ai.ask(region.fill(BACKFILL_PROMPT, conn).replace("{items}", json.dumps(listing, ensure_ascii=False)),
                        schema=BACKFILL_SCHEMA, kind="diet.drinks", timeout=300, conn=conn)
        got = {a["ref"]: a for a in answer["items"]}
        with db.write_lock(conn):
            for r in rows:
                a = got.get(f"i{r['id']}")
                before = changes.row(conn, "meal_items", r["id"])
                if not a or not before or before["deleted_at"]:
                    continue  # left for the next run
                per100 = json.loads(before["per100"])
                per100["caffeine"] = round(min(max(float(a["caffeine"]), 0.0), 2000.0), 2)
                per100["alcohol"] = round(min(max(float(a["alcohol"]), 0.0), 80.0), 2)
                t = meals.totals(per100, before["grams"])
                new = {**before, "per100": meals.per100_json(per100), "caffeine": t["caffeine"],
                       "alcohol": t["alcohol"]}
                conn.execute("UPDATE meal_items SET per100 = ?, caffeine = ?, alcohol = ? WHERE id = ?",
                             (new["per100"], new["caffeine"], new["alcohol"], r["id"]))
                changes.record(conn, "item.drinks", "meal_items", r["id"], before, new)
                done += 1
    return {"items": done, "left": missing(conn)}


@jobs.handler("diet.drinks_backfill", every=1800)
def backfill_job(conn: sqlite3.Connection, payload: dict) -> dict:
    if not enabled(conn):
        return {"skipped": "tracking is off"}
    return backfill(conn)


# ---------------------------------------------------------------- stats

def units(grams: float | None) -> float | None:
    return None if grams is None else round(grams / UNIT_G, 1)


def _days(conn: sqlite3.Connection, start: str, end: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT m.day, SUM(i.caffeine) AS caffeine, SUM(i.alcohol) AS alcohol, "
        "SUM(CASE WHEN i.caffeine IS NULL OR i.alcohol IS NULL THEN 1 ELSE 0 END) AS pending "
        "FROM meals m JOIN meal_items i ON i.meal_id = m.id "
        "WHERE m.deleted_at IS NULL AND i.deleted_at IS NULL AND m.day BETWEEN ? AND ? GROUP BY m.day",
        (start, end)).fetchall()
    return {r["day"]: {"caffeine": float(r["caffeine"] or 0), "alcohol": float(r["alcohol"] or 0),
                       "pending": int(r["pending"])} for r in rows}


def span(conn: sqlite3.Connection, end: str, length: int, now: str | None = None) -> dict:
    """The last `length` days up to `end`, averaged over the days with anything logged. Today is still filling
    up, so it's left out unless it's the only day with anything logged."""
    start = (date.fromisoformat(end) - timedelta(days=length - 1)).isoformat()
    days = _days(conn, start, end)
    today = now or date.today().isoformat()
    today_left_out = today in days and len(days) > 1
    if today_left_out:
        del days[today]
    n = len(days)
    caffeine = [d["caffeine"] for d in days.values()]
    alcohol = [d["alcohol"] for d in days.values()]
    return {
        "days": length, "start": start, "end": end, "logged_days": n, "today_left_out": today_left_out,
        "pending": sum(d["pending"] for d in days.values()),
        "caffeine_total": round(sum(caffeine)),
        "caffeine_per_day": round(sum(caffeine) / n) if n else None,
        "caffeine_per_week": round(sum(caffeine) / n * 7) if n else None,
        "caffeine_highest": round(max(caffeine)) if n else None,
        "caffeine_days_over": sum(1 for c in caffeine if c > CAFFEINE_DAY_LIMIT),
        "alcohol_units_total": round(sum(alcohol) / UNIT_G, 1),
        "alcohol_units_per_week": round(sum(alcohol) / UNIT_G / n * 7, 1) if n else None,
        "alcohol_heaviest_day": units(max(alcohol)) if n else None,
        "alcohol_free_days": sum(1 for a in alcohol if a == 0),
    }


def view(conn: sqlite3.Connection, today: str) -> dict:
    t = _days(conn, today, today).get(today, {"caffeine": 0.0, "alcohol": 0.0, "pending": 0})
    return {
        "enabled": enabled(conn), "pending": missing(conn),
        "today": {"caffeine": round(t["caffeine"]), "alcohol_units": units(t["alcohol"])},
        "week": span(conn, today, 7), "month": span(conn, today, 30), "reference": reference(conn),
    }
