"""Daily targets from the owner's goal, body and activity.

* Resting energy (BMR): Mifflin-St Jeor, from weight, height, age and sex.
* Maintenance: on a day with activity from Apple Health, BMR × 1.2 plus a share of the active energy
  burned so far ("eat back", half by default because trackers overestimate). Without activity data,
  BMR × the chosen activity level.
* Goal: a weekly rate; 1 kg of body weight ≈ 7,700 kcal, so 0.25 kg a week ≈ 275 kcal a day.
* Protein: grams per kg of body weight (1.6 by default, which helps keep muscle while losing fat).
* Fat: a share of the calories (30% by default); carbs: whatever calories are left after protein and fat;
  fibre: 14 g for every 1,000 kcal.

Either target can be set by hand instead; activity is still added on top when that's switched on.
Goals are never edited in place: each change is a new row, so history keeps the targets it had.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from .. import db, health

ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "very": 1.725}
KCAL_PER_KG = 7700
DEFAULT_GOAL = {"goal": "lose", "rate": 0.25, "activity": "light", "eat_back": 0.5, "protein_per_kg": 1.6,
                "kcal_override": None, "protein_override": None, "fat_pct": 0.3}
FIBRE_PER_1000_KCAL = 14
PROFILE_KEYS = ("sex", "birth_year", "height_cm")


def goal(conn: sqlite3.Connection) -> dict:
    r = conn.execute("SELECT * FROM diet_goals ORDER BY id DESC LIMIT 1").fetchone()
    return {**DEFAULT_GOAL, **({k: r[k] for k in DEFAULT_GOAL} if r else {}), "saved": bool(r)}


def save_goal(conn: sqlite3.Connection, values: dict) -> dict:
    g = {k: values.get(k, DEFAULT_GOAL[k]) for k in DEFAULT_GOAL}
    if g["goal"] not in ("lose", "maintain", "gain"):
        raise ValueError("The goal must be lose, maintain or gain.")
    if g["activity"] not in ACTIVITY:
        raise ValueError("Unknown activity level.")
    if g["goal"] == "maintain":
        g["rate"] = 0
    if not 0 <= float(g["rate"]) <= 1:
        raise ValueError("Choose a rate between 0 and 1 kg a week.")
    if not 0.15 <= float(g["fat_pct"]) <= 0.45:
        raise ValueError("Choose a fat share between 15% and 45%.")
    current = goal(conn)
    if current["saved"] and all(current[k] == (float(g[k]) if isinstance(g[k], int | float) and k not in
                                               ("kcal_override", "protein_override") else g[k]) for k in g):
        return current  # unchanged: no new history row
    conn.execute("INSERT INTO diet_goals (goal, rate, activity, eat_back, protein_per_kg, kcal_override, "
                 "protein_override, fat_pct, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (g["goal"], float(g["rate"]), g["activity"], float(g["eat_back"]), float(g["protein_per_kg"]),
                  g["kcal_override"], g["protein_override"], float(g["fat_pct"]), db.now()))
    return goal(conn)


def profile(conn: sqlite3.Connection) -> dict:
    p: dict = {k: db.get_setting(conn, f"profile.{k}") for k in PROFILE_KEYS}
    p["birth_year"] = int(p["birth_year"]) if p["birth_year"] else None
    p["height_cm"] = float(p["height_cm"]) if p["height_cm"] else None
    if p["height_cm"] is None:
        h = health.latest(conn, "height")
        if h:
            p["height_cm"] = round(h["value"], 1)
            p["height_from_health"] = True
    return p


def save_profile(conn: sqlite3.Connection, values: dict) -> dict:
    if values.get("sex") not in (None, "male", "female"):
        raise ValueError("Sex must be male or female (it changes the resting-energy formula).")
    for k in PROFILE_KEYS:
        if k in values and values[k] not in (None, ""):
            db.set_setting(conn, f"profile.{k}", str(values[k]))
    return profile(conn)


def weight_on(conn: sqlite3.Connection, day: str) -> dict | None:
    w = health.latest(conn, "weight", on_or_before=day) or health.latest(conn, "weight")
    return {"kg": round(w["value"], 1), "day": w["day"], "source": w["source"]} if w else None


def activity(conn: sqlite3.Connection, day: str, bmr_kcal: float | None) -> tuple[float | None, str | None]:
    """Energy burned through activity on a day, and where it came from. Apple Health's active energy when
    the phone sent it; otherwise WHOOP's energy for the day minus the resting part of it (resting energy for
    the hours the WHOOP day has run so far)."""
    active = health.day_total(conn, "active_energy", day)
    if active is not None:
        return active, "Apple Health"
    row = health.daily_row(conn, "total_energy", day)
    if row is None or bmr_kcal is None:
        return None, None
    start = datetime.fromisoformat(row["start"])
    end = datetime.fromisoformat(row["end"]) if row["end"] else datetime.now(UTC)
    hours = min(30.0, max(0.0, (end - start).total_seconds() / 3600))
    return max(0.0, row["value"] - bmr_kcal * hours / 24), row["source"] or "WHOOP"


def bmr(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)


def for_day(conn: sqlite3.Connection, day: str) -> dict:
    """The targets for one day, with how they were worked out. `ready` is False (and `missing` says
    what's needed) until there's enough to work them out."""
    g, p = goal(conn), profile(conn)
    w = weight_on(conn, day)
    resting = health.day_total(conn, "resting_energy", day)
    b_now = None
    if w and p.get("height_cm") and p.get("birth_year") and p.get("sex"):
        b_now = bmr(w["kg"], p["height_cm"], date.fromisoformat(day).year - int(p["birth_year"]), p["sex"])
    active, source = activity(conn, day, b_now)
    out: dict = {"goal": g, "weight": w, "active_kcal": round(active) if active is not None else None,
                 "activity_source": source, "resting_kcal": round(resting) if resting is not None else None,
                 "missing": [], "notes": []}

    missing = []
    if not w:
        missing.append("weight")
    if not p.get("height_cm"):
        missing.append("height")
    if not p.get("birth_year"):
        missing.append("birth year")
    if not p.get("sex"):
        missing.append("sex")

    kcal = protein = None
    if missing and not g["kcal_override"]:
        out["missing"] = missing
    else:
        if g["kcal_override"]:
            base = float(g["kcal_override"])
            how = "set by you"
            if active and g["eat_back"]:
                base += active * g["eat_back"]
                how += f", plus {round(g['eat_back'] * 100)}% of today's {round(active):,} kcal of activity ({source})"
        else:
            assert w and p["height_cm"] and p["birth_year"] and p["sex"]
            age = date.fromisoformat(day).year - int(p["birth_year"])
            b = bmr(w["kg"], p["height_cm"], age, p["sex"])
            out["bmr"] = round(b)
            if active is not None:
                maintenance = b * ACTIVITY["sedentary"] + active * g["eat_back"]
                how = (f"resting {round(b):,} kcal × 1.2, plus {round(g['eat_back'] * 100)}% of today's "
                       f"{round(active):,} kcal of activity ({source})")
            else:
                maintenance = b * ACTIVITY[g["activity"]]
                how = f"resting {round(b):,} kcal × {ACTIVITY[g['activity']]} for a {g['activity']} day"
            daily = KCAL_PER_KG * float(g["rate"]) / 7
            if g["goal"] == "lose":
                base = maintenance - daily
                how += f", minus {round(daily):,} kcal to lose {g['rate']:g} kg a week"
            elif g["goal"] == "gain":
                base = maintenance + daily
                how += f", plus {round(daily):,} kcal to gain {g['rate']:g} kg a week"
            else:
                base = maintenance
            out["maintenance"] = round(maintenance)
            if base < b:
                out["notes"].append("This is below your resting energy. A slower rate is easier to keep up.")
        kcal = round(base / 10) * 10
        out["kcal_how"] = how

    if g["protein_override"]:
        protein = int(g["protein_override"])
        out["protein_how"] = "set by you"
    elif w:
        protein = round(w["kg"] * float(g["protein_per_kg"]) / 5) * 5
        out["protein_how"] = f"{g['protein_per_kg']:g} g for each of your {w['kg']:g} kg"
    out.update(ready=kcal is not None, kcal=kcal, protein=protein, **macros(kcal, protein, float(g["fat_pct"])))
    return out


def macros(kcal: int | None, protein: int | None, fat_pct: float) -> dict:
    """Fat, carb and fibre targets in grams, and how the calories split, from the calorie and protein
    targets. Carbs never go below zero (a very high protein target simply leaves less for them)."""
    if kcal is None:
        return {"carbs": None, "fat": None, "fibre": None, "split": None}
    p_kcal = (protein or 0) * 4
    fat = round(kcal * fat_pct / 9)
    carbs = max(0, round((kcal - p_kcal - fat * 9) / 4))
    total = p_kcal + fat * 9 + carbs * 4 or 1
    return {"carbs": carbs, "fat": fat, "fibre": round(kcal / 1000 * FIBRE_PER_1000_KCAL),
            "split": {"protein": round(100 * p_kcal / total), "carbs": round(100 * carbs * 4 / total),
                      "fat": round(100 * fat * 9 / total)}}
