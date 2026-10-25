"""Meals: logging, reading them with the AI, and edits with Undo.

A meal is saved at once with its photos and note, then read in the background. The AI names each item
and estimates its portion in grams and its nutrients per 100 g, and that estimate is used; for a branded
product, its nutrition label is looked up online instead (`labels`). There are no food tables: items from
before they were removed may still point at one (`food_id`, basis "table").
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .. import ai, changes, config, db, jobs, region
from . import foods, labels, targets

MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 12 * 1024 * 1024
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF")  # JPEG, PNG, WebP
NUTRIENTS = foods.NUTRIENTS
# Also per 100 g, kept apart from the nutrients: caffeine in mg, alcohol in grams of pure alcohol (diet/drinks.py).
EXTRAS = ("caffeine", "alcohol")
SLOTS = ("breakfast", "lunch", "snack", "dinner")


def photo_dir(meal_id: int) -> Path:
    return config.home() / "uploads" / "meals" / str(meal_id)


def slot_for(t: datetime) -> str:
    h = t.hour + t.minute / 60
    if 4 <= h < 11:
        return "breakfast"
    if 11 <= h < 15.5:
        return "lunch"
    if 15.5 <= h < 18.5:
        return "snack"
    return "dinner"


def create(conn: sqlite3.Connection, *, eaten_at: str, note: str, photos: list[bytes], slot: str | None = None,
           analyse: bool = True) -> int:
    """Save a meal (its photos go under uploads/meals/<id>/) and queue it to be read."""
    try:
        t = datetime.fromisoformat(eaten_at)
    except ValueError:
        raise ValueError("The time must be ISO 8601, like 2026-10-17T13:05:00+05:30.") from None
    if t.tzinfo is None:
        raise ValueError("The time needs its UTC offset, like +05:30.")
    note = (note or "").strip()[:2000]
    if not note and not photos:
        raise ValueError("Add a photo or say what you ate.")
    if len(photos) > MAX_PHOTOS:
        raise ValueError(f"Up to {MAX_PHOTOS} photos per meal.")
    for p in photos:
        if len(p) > MAX_PHOTO_BYTES:
            raise ValueError("A photo is too large (over 12 MB).")
        if not p.startswith(_IMAGE_MAGIC):
            raise ValueError("Photos must be JPEG, PNG or WebP.")
    if slot is not None and slot not in SLOTS:
        raise ValueError("Unknown meal.")
    now = db.now()
    with db.write_lock(conn):
        cur = conn.execute(
            "INSERT INTO meals (eaten_at, day, slot, note, photos, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (t.isoformat(), t.date().isoformat(), slot or slot_for(t), note, len(photos),
             "analysing" if analyse else "ready", now, now))
        meal_id = cur.lastrowid
        assert meal_id is not None
    if photos:
        d = photo_dir(meal_id)
        d.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(photos):
            (d / f"{i}.jpg").write_bytes(p)
            config.private(d / f"{i}.jpg")
    if analyse:
        queue_analysis(conn, meal_id)
    return meal_id


def queue_analysis(conn: sqlite3.Connection, meal_id: int) -> int:
    job_id = jobs.enqueue(conn, "diet.analyse", {"meal_id": meal_id}, max_attempts=2)
    conn.execute("UPDATE meals SET status = 'analysing', job_id = ?, error = NULL, updated_at = ? WHERE id = ?",
                 (job_id, db.now(), meal_id))
    return job_id


# ---------------------------------------------------------------- reading a meal with the AI

PER100 = {
    "type": "object",
    "properties": {k: {"type": "number"} for k in (*NUTRIENTS, *EXTRAS)},
    "required": [*NUTRIENTS, *EXTRAS],
    "additionalProperties": False,
}
MEAL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "not_food": {"type": "boolean"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "brand": {"type": "string"},
                    "portion": {"type": "string"},
                    "grams": {"type": "number"},
                    "per_100g": PER100,
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["name", "brand", "portion", "grams", "per_100g", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "not_food", "items"],
    "additionalProperties": False,
}

PROMPT = """You estimate what someone ate, for their own food diary. Do not run any commands.

{eats} Read the attached photo(s) and/or their note and list each distinct item they ate.

For each item give:
- name: {naming}
- brand: for a packaged or branded product, or a dish from a named restaurant chain, the brand and product
  as exactly as the note or the pack in the photo gives them, e.g. "Amul Masti Dahi", "Yoga Bar Protein Bar
  Chocolate Brownie", "Starbucks Cappuccino tall"; its label is looked up online. "" for home food and
  anything without a brand.
- portion: the household measure, e.g. {measures}.
- grams: the edible amount eaten, as eaten (cooked weight for cooked food).
- per_100g: your estimate per 100 g as eaten, home-cooked: kcal, protein, carbs, fat, fibre (grams), caffeine (mg;
  coffee, tea, cola, energy drinks, chocolate; else 0) and alcohol (grams of pure alcohol: a drink's ABV % × 0.79,
  e.g. 3.9 for a 5% beer; else 0).
- confidence: high, medium or low, for the portion size especially.

{portions}

Quantities in the note override what the photo suggests. Only list what is visible or mentioned. If the
photo shows no food, set not_food to true and give no items. title: a short name for the meal, at most
six words, e.g. "Rice, lentils and salad".

Their note: {note}"""


def settle(item: dict, label: dict | None) -> dict:
    """What an AI item becomes: the product's label when one was found (`labels.look_up`), with its name and,
    for counted packs or pieces, its amount (kept as "as read"); otherwise the AI's own estimate."""
    use = label if label and label.get("used") else None
    grams = max(0.0, float(use["grams"] if use else item["grams"]))
    reading = {**item, "grams": grams}
    if label:
        reading["label"] = {**label, "read_grams": item["grams"]} if use else label
    return {"name": (use["product"] if use else item["name"]).strip()[:120], "grams": grams,
            "portion": (use["portion"] if use else item["portion"]).strip()[:60],
            "per100": use["per_100g"] if use else item["per_100g"], "basis": "label" if use else "estimate",
            "reading": reading}


def totals(per100: dict, grams: float) -> dict:
    """The amounts in `grams` of a food with these values per 100 g. Caffeine and alcohol stay None when
    they haven't been worked out (older items until drinks.backfill has run)."""
    out: dict[str, float | None] = {k: round(float(per100.get(k) or 0) * grams / 100, 1) for k in NUTRIENTS}
    for k in EXTRAS:
        out[k] = None if per100.get(k) is None else round(float(per100[k]) * grams / 100, 1)
    return out


def per100_json(per100: dict) -> str:
    return json.dumps({k: per100.get(k) for k in (*NUTRIENTS, *EXTRAS)})


def _insert_item(conn: sqlite3.Connection, meal_id: int, position: int, *, name: str, grams: float, portion: str,
                 per100: dict, basis: str, confidence: str, ai_reading: dict | None, food_id: str | None = None) -> int:
    t = totals(per100, grams)
    cur = conn.execute(
        "INSERT INTO meal_items (meal_id, position, name, food_id, portion, grams, kcal, protein, carbs, fat, fibre, "
        "caffeine, alcohol, per100, basis, confidence, ai, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (meal_id, position, name, food_id, portion, round(grams, 1), t["kcal"], t["protein"],
         t["carbs"], t["fat"], t["fibre"], t["caffeine"], t["alcohol"], per100_json(per100), basis, confidence,
         json.dumps(ai_reading) if ai_reading is not None else None, db.now()))
    assert cur.lastrowid is not None
    return cur.lastrowid


def analyse(conn: sqlite3.Connection, meal_id: int) -> dict:
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal or meal["deleted_at"]:
        return {"skipped": "meal removed"}
    images = sorted(photo_dir(meal_id).glob("*.jpg"), key=lambda p: int(p.stem)) if meal["photos"] else []
    note = meal["note"] or "(no note; read the photo)"
    try:
        answer = ai.ask(region.fill(PROMPT, conn).replace("{note}", note), schema=MEAL_SCHEMA, images=images,
                        kind="diet.analyse", timeout=240, conn=conn)
    except ai.AIError as e:
        conn.execute("UPDATE meals SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                     (_plain(e), db.now(), meal_id))
        raise
    items = [] if answer["not_food"] else answer["items"]
    found = labels.look_up(conn, items, meal["note"])  # branded items only; a second call, with web search
    with db.write_lock(conn):
        # A re-read replaces the AI's items; the earlier ones are kept, marked removed.
        conn.execute("UPDATE meal_items SET deleted_at = ? WHERE meal_id = ? AND deleted_at IS NULL",
                     (db.now(), meal_id))
        for i, item in enumerate(items):
            v = settle(item, found.get(i))
            _insert_item(conn, meal_id, i, name=v["name"], grams=v["grams"], portion=v["portion"], per100=v["per100"],
                         basis=v["basis"], confidence=item["confidence"], ai_reading=v["reading"])
        status, error = "ready", None
        if answer["not_food"] or not items:
            status, error = "failed", "No food was found in this. Add a note saying what you ate, then read it again."
        conn.execute("UPDATE meals SET status = ?, title = ?, error = ?, updated_at = ? WHERE id = ?",
                     (status, answer["title"][:80], error, db.now(), meal_id))
    return {"items": len(items)}


def _plain(e: ai.AIError) -> str:
    """What to tell the owner when reading a meal fails; the full error stays in the job and ai_runs."""
    text = str(e)
    if "shape" in text or "JSON" in text or "without an answer" in text:
        return "The AI's answer was incomplete. Tap Read Again."
    if "longer than" in text:
        return "The AI took too long. Tap Read Again."
    if "isn't installed" in text or "couldn't be started" in text:
        return "The AI isn't available on the Mac right now. Check Settings, AI."
    return "The AI couldn't read this. Tap Read Again, or add a note."


@jobs.handler("diet.analyse")
def analyse_job(conn: sqlite3.Connection, payload: dict) -> dict:
    return analyse(conn, int(payload["meal_id"]))


# ---------------------------------------------------------------- redoing one item with the owner's correction

REDO_SCHEMA = {
    "type": "object",
    "properties": {"item": MEAL_SCHEMA["properties"]["items"]["items"]},
    "required": ["item"],
    "additionalProperties": False,
}
# The same rules for an item as a whole meal's reading uses, from its prompt.
_ITEM_RULES = PROMPT[PROMPT.index("For each item give:"):PROMPT.index("Quantities in the note")]
REDO_PROMPT = """You correct one item in someone's food diary. Do not run any commands.

{eats} They logged a meal{photos}; it
was read into items, and they say this one needs redoing. Their correction overrides the photo and the
earlier reading; keep whatever it doesn't change.

The item as it was read: {item}
Their note for the whole meal: {note}
Their correction: {correction}

Give the corrected item, as one item.

""" + _ITEM_RULES.replace("For each item give:", "For the item give:").rstrip() + "\n"


def queue_redo(conn: sqlite3.Connection, item_id: int, correction: str) -> int:
    """Check the request, then redo the item in the background (an AI call takes about half a minute)."""
    correction = " ".join((correction or "").split())[:500]
    if not correction:
        raise ValueError("Say what's different, for example “it was lentil soup, about 2 bowls”.")
    if not conn.execute("SELECT 1 FROM meal_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone():
        raise LookupError("There's no such item.")
    return jobs.enqueue(conn, "diet.redo_item", {"item_id": item_id, "correction": correction}, max_attempts=1)


def redo_item(conn: sqlite3.Connection, item_id: int, correction: str) -> dict:
    """Read one item again with the owner's correction and change it in place, recorded for Undo."""
    r = conn.execute("SELECT * FROM meal_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone()
    if not r:
        raise LookupError("There's no such item.")
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (r["meal_id"],)).fetchone()
    images = sorted(photo_dir(meal["id"]).glob("*.jpg"), key=lambda p: int(p.stem)) if meal["photos"] else []
    was = {"name": r["name"], "portion": r["portion"], "grams": r["grams"], "per_100g": json.loads(r["per100"])}
    prompt = (region.fill(REDO_PROMPT, conn).replace("{photos}", " with the photo(s) attached" if images else "")
              .replace("{item}", json.dumps(was, ensure_ascii=False))
              .replace("{note}", meal["note"] or "(none)")
              .replace("{correction}", correction))
    item = ai.ask(prompt, schema=REDO_SCHEMA, images=images, kind="diet.redo", timeout=240, conn=conn)["item"]
    label = labels.look_up(conn, [item], f"{meal['note'] or ''} (Their correction: {correction})").get(0)
    v = settle(item, label)
    per100 = v["per100"]
    reading = {**v["reading"], "correction": correction}
    with db.write_lock(conn):
        before = changes.row(conn, "meal_items", item_id)
        if not before or before["deleted_at"]:
            raise LookupError("That item was removed meanwhile.")
        new = {**before, **totals(per100, v["grams"]), "name": v["name"] or before["name"],
               "food_id": None, "portion": v["portion"],
               "grams": round(v["grams"], 1), "per100": per100_json(per100),
               "basis": v["basis"], "confidence": item["confidence"],
               "ai": json.dumps(reading),
               "edited_at": db.now()}
        conn.execute("UPDATE meal_items SET name = ?, food_id = ?, portion = ?, grams = ?, kcal = ?, protein = ?, "
                     "carbs = ?, fat = ?, fibre = ?, caffeine = ?, alcohol = ?, per100 = ?, basis = ?, confidence = ?, "
                     "ai = ?, edited_at = ? WHERE id = ?",
                     (new["name"], new["food_id"], new["portion"], new["grams"], new["kcal"], new["protein"],
                      new["carbs"], new["fat"], new["fibre"], new["caffeine"], new["alcohol"], new["per100"],
                      new["basis"], new["confidence"], new["ai"], new["edited_at"], item_id))
        change_id = changes.record(conn, "item.redo", "meal_items", item_id, before, new)
        conn.execute("UPDATE meals SET updated_at = ? WHERE id = ?", (db.now(), before["meal_id"]))
    return {"change_id": change_id, "meal_id": before["meal_id"], "name": new["name"]}


@jobs.handler("diet.redo_item")
def redo_job(conn: sqlite3.Connection, payload: dict) -> dict:
    return redo_item(conn, int(payload["item_id"]), str(payload["correction"]))


# ---------------------------------------------------------------- reading and editing

def item_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["per100"] = json.loads(d["per100"])
    reading = json.loads(d.pop("ai")) if d.get("ai") else None
    d["ai_grams"] = reading.get("grams") if reading else None
    label = (reading or {}).get("label") or {}
    d["label_url"] = label.get("source") if d["basis"] == "label" and label.get("used") else None
    return d


def meal_dict(conn: sqlite3.Connection, r: sqlite3.Row, with_items: bool = True) -> dict:
    d = dict(r)
    items = [item_dict(i) for i in conn.execute(
        "SELECT * FROM meal_items WHERE meal_id = ? AND deleted_at IS NULL ORDER BY position, id", (r["id"],))]
    d["totals"] = {k: round(sum(float(i[k] or 0) for i in items), 1) for k in (*NUTRIENTS, *EXTRAS)}
    d["items"] = items if with_items else []
    return d


def get(conn: sqlite3.Connection, meal_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM meals WHERE id = ? AND deleted_at IS NULL", (meal_id,)).fetchone()
    return meal_dict(conn, r) if r else None


OWN_LIMITS = {"kcal": 10000, "protein": 1000, "carbs": 1000, "fat": 1000}


def edit_item(conn: sqlite3.Connection, item_id: int, *, grams: float | None = None, portion: str | None = None,
              name: str | None = None, nutrients: dict | None = None) -> dict:
    """Change an item's amount, or put in its nutrients by hand (`nutrients`: kcal, protein, carbs, fat for
    the amount eaten; any left out keep their value). Own numbers are kept per 100 g, so a later change of
    amount scales them, and the item's basis becomes "owner". Recorded for Undo."""
    with db.write_lock(conn):
        before = changes.row(conn, "meal_items", item_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such item.")
        new = dict(before)
        per100 = json.loads(before["per100"])
        if name is not None:
            new["name"] = name.strip()[:120] or new["name"]
        if grams is not None:
            if not 0 < grams <= 5000:
                raise ValueError("Grams must be between 0 and 5,000.")
            new["grams"] = round(float(grams), 1)
        if portion is not None:
            new["portion"] = portion.strip()[:60]
        if nutrients:
            for k, v in nutrients.items():
                if k not in OWN_LIMITS:
                    raise ValueError(f"Unknown nutrient: {k}.")
                if v is None:
                    continue
                if not 0 <= float(v) <= OWN_LIMITS[k]:
                    raise ValueError(f"{k.capitalize()} must be between 0 and {OWN_LIMITS[k]:,}.")
                per100[k] = round(float(v) * 100 / new["grams"], 3)
            new["basis"] = "owner"
        new.update(totals(per100, new["grams"]))
        new["per100"] = json.dumps(per100)
        new["edited_at"] = db.now()
        conn.execute("UPDATE meal_items SET name = ?, food_id = ?, portion = ?, grams = ?, kcal = ?, protein = ?, "
                     "carbs = ?, fat = ?, fibre = ?, caffeine = ?, alcohol = ?, per100 = ?, basis = ?, edited_at = ? "
                     "WHERE id = ?",
                     (new["name"], new["food_id"], new["portion"], new["grams"], new["kcal"], new["protein"],
                      new["carbs"], new["fat"], new["fibre"], new["caffeine"], new["alcohol"], new["per100"],
                      new["basis"], new["edited_at"], item_id))
        change_id = changes.record(conn, "item.edit", "meal_items", item_id, before, new)
        conn.execute("UPDATE meals SET updated_at = ? WHERE id = ?", (db.now(), before["meal_id"]))
    return {"change_id": change_id, "meal_id": before["meal_id"]}


def use_estimate(conn: sqlite3.Connection, item_id: int) -> dict:
    """Use the AI's own per-100 g estimate for an item (from its reading) instead of its label's or an old
    table food's values, keeping its amount. Recorded for Undo."""
    with db.write_lock(conn):
        before = changes.row(conn, "meal_items", item_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such item.")
        estimate = (json.loads(before["ai"]) if before["ai"] else {}).get("per_100g")
        if not estimate:
            raise ValueError("There's no AI estimate for this item.")
        per100 = {k: float(estimate.get(k) or 0) for k in NUTRIENTS}
        had = json.loads(before["per100"])
        for k in EXTRAS:  # an older reading has no caffeine or alcohol: keep what was worked out since
            per100[k] = estimate[k] if estimate.get(k) is not None else had.get(k)
        new = {**before, **totals(per100, before["grams"]), "food_id": None, "basis": "estimate",
               "per100": per100_json(per100)}
        conn.execute("UPDATE meal_items SET food_id = NULL, kcal = ?, protein = ?, carbs = ?, fat = ?, fibre = ?, "
                     "caffeine = ?, alcohol = ?, per100 = ?, basis = 'estimate' WHERE id = ?",
                     (new["kcal"], new["protein"], new["carbs"], new["fat"], new["fibre"], new["caffeine"],
                      new["alcohol"], new["per100"], item_id))
        change_id = changes.record(conn, "item.estimate", "meal_items", item_id, before, new)
        conn.execute("UPDATE meals SET updated_at = ? WHERE id = ?", (db.now(), before["meal_id"]))
    return {"change_id": change_id, "meal_id": before["meal_id"]}


def remove_item(conn: sqlite3.Connection, item_id: int) -> dict:
    with db.write_lock(conn):
        before = changes.row(conn, "meal_items", item_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such item.")
        now = db.now()
        conn.execute("UPDATE meal_items SET deleted_at = ? WHERE id = ?", (now, item_id))
        change_id = changes.record(conn, "item.delete", "meal_items", item_id, before, {**before, "deleted_at": now})
    return {"change_id": change_id, "meal_id": before["meal_id"]}


ADD_SCHEMA = {
    "type": "object",
    "properties": {"items": MEAL_SCHEMA["properties"]["items"]},
    "required": ["items"],
    "additionalProperties": False,
}
ADD_PROMPT = """You add to someone's food diary. Do not run any commands.

{eats} They logged a meal and now
say they also had what's below. List each item it names (usually one), and nothing already in the meal.

The meal so far: {items}
What they add: {text}

""" + _ITEM_RULES.rstrip() + "\n"


def queue_add(conn: sqlite3.Connection, meal_id: int, text: str) -> int:
    """Check the request, then read what the owner typed into items in the background."""
    text = " ".join((text or "").split())[:500]
    if not text:
        raise ValueError("Say what you had, for example “a bowl of yoghurt”.")
    if not conn.execute("SELECT 1 FROM meals WHERE id = ? AND deleted_at IS NULL", (meal_id,)).fetchone():
        raise LookupError("There's no such meal.")
    return jobs.enqueue(conn, "diet.add_item", {"meal_id": meal_id, "text": text}, max_attempts=1)


def add_from_text(conn: sqlite3.Connection, meal_id: int, text: str) -> dict:
    """The AI reads what the owner typed into items (a branded one's label looked up), added at the end of
    the meal. Each is recorded so Undo removes it again."""
    meal = get(conn, meal_id)
    if not meal:
        raise LookupError("There's no such meal.")
    so_far = [f"{i['name']} ({i['portion'] or str(i['grams']) + ' g'})" for i in meal["items"]]
    prompt = (region.fill(ADD_PROMPT, conn).replace("{items}", "; ".join(so_far) or "(nothing yet)")
              .replace("{text}", text))
    items = ai.ask(prompt, schema=ADD_SCHEMA, kind="diet.add", timeout=240, conn=conn)["items"]
    if not items:
        raise ValueError("The AI didn't find any food in that.")
    found = labels.look_up(conn, items, text)
    change_ids, names = [], []
    with db.write_lock(conn):
        if not conn.execute("SELECT 1 FROM meals WHERE id = ? AND deleted_at IS NULL", (meal_id,)).fetchone():
            raise LookupError("That meal was removed meanwhile.")
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM meal_items WHERE meal_id = ?",
                           (meal_id,)).fetchone()[0]
        for n, item in enumerate(items):
            v = settle(item, found.get(n))
            item_id = _insert_item(conn, meal_id, pos + n, name=v["name"], grams=v["grams"], portion=v["portion"],
                                   per100=v["per100"], basis=v["basis"], confidence=item["confidence"],
                                   ai_reading={**v["reading"], "added": text})
            row = changes.row(conn, "meal_items", item_id)
            assert row
            # Adding is undone by removing; recorded the same way so Undo works.
            change_ids.append(changes.record(conn, "item.add", "meal_items", item_id,
                                             {**row, "deleted_at": db.now()}, row))
            names.append(v["name"])
        conn.execute("UPDATE meals SET status = 'ready', error = NULL, updated_at = ? WHERE id = ?",
                     (db.now(), meal_id))
    return {"change_ids": change_ids, "names": names, "meal_id": meal_id}


@jobs.handler("diet.add_item")
def add_job(conn: sqlite3.Connection, payload: dict) -> dict:
    return add_from_text(conn, int(payload["meal_id"]), str(payload["text"]))


def edit_meal(conn: sqlite3.Connection, meal_id: int, *, eaten_at: str | None = None, slot: str | None = None,
              title: str | None = None, note: str | None = None) -> dict:
    with db.write_lock(conn):
        before = changes.row(conn, "meals", meal_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such meal.")
        new = dict(before)
        if eaten_at is not None:
            t = datetime.fromisoformat(eaten_at)
            if t.tzinfo is None:
                raise ValueError("The time needs its UTC offset.")
            new.update(eaten_at=t.isoformat(), day=t.date().isoformat())
        if slot is not None:
            if slot not in SLOTS:
                raise ValueError("Unknown meal.")
            new["slot"] = slot
        if title is not None:
            new["title"] = title.strip()[:80]
        if note is not None:
            new["note"] = note.strip()[:2000]
        conn.execute("UPDATE meals SET eaten_at = ?, day = ?, slot = ?, title = ?, note = ?, updated_at = ? "
                     "WHERE id = ?",
                     (new["eaten_at"], new["day"], new["slot"], new["title"], new["note"], db.now(), meal_id))
        change_id = changes.record(conn, "meal.edit", "meals", meal_id, before, new)
    return {"change_id": change_id}


def remove_meal(conn: sqlite3.Connection, meal_id: int) -> dict:
    with db.write_lock(conn):
        before = changes.row(conn, "meals", meal_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such meal.")
        now = db.now()
        conn.execute("UPDATE meals SET deleted_at = ? WHERE id = ?", (now, meal_id))
        change_id = changes.record(conn, "meal.delete", "meals", meal_id, before, {**before, "deleted_at": now})
    return {"change_id": change_id}


def log_again(conn: sqlite3.Connection, meal_id: int, eaten_at: str) -> int:
    """A copy of a meal at a new time, with the same items and photos; no AI needed."""
    src = get(conn, meal_id)
    if not src:
        raise LookupError("There's no such meal.")
    t = datetime.fromisoformat(eaten_at)
    if t.tzinfo is None:
        raise ValueError("The time needs its UTC offset.")
    now = db.now()
    with db.write_lock(conn):
        cur = conn.execute(
            "INSERT INTO meals (eaten_at, day, slot, note, photos, status, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'ready', ?, ?, ?)",
            (t.isoformat(), t.date().isoformat(), slot_for(t), src["note"], src["photos"], src["title"], now, now))
        new_id = cur.lastrowid
        assert new_id is not None
        for i, item in enumerate(src["items"]):
            _insert_item(conn, new_id, i, name=item["name"], grams=item["grams"], portion=item["portion"],
                         per100=item["per100"], basis=item["basis"], confidence=item["confidence"], ai_reading=None,
                         food_id=item["food_id"])
    if src["photos"]:
        shutil.copytree(photo_dir(meal_id), photo_dir(new_id), dirs_exist_ok=True)
    return new_id


# ---------------------------------------------------------------- days and history

def day_summary(conn: sqlite3.Connection, day: str) -> dict:
    meals = [meal_dict(conn, r) for r in conn.execute(
        "SELECT * FROM meals WHERE day = ? AND deleted_at IS NULL ORDER BY eaten_at", (day,))]
    eaten = {k: round(sum(m["totals"][k] for m in meals), 1) for k in (*NUTRIENTS, *EXTRAS)}
    t = targets.for_day(conn, day)
    left = {k: round(t[k] - eaten[k]) if t.get(k) is not None else None
            for k in ("kcal", "protein", "carbs", "fat", "fibre")}
    return {"day": day, "meals": meals, "eaten": eaten, "targets": t, "left": left}


def history(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT m.day, COUNT(DISTINCT m.id) AS meals, COALESCE(SUM(i.kcal), 0) AS kcal, "
        "COALESCE(SUM(i.protein), 0) AS protein, COALESCE(SUM(i.carbs), 0) AS carbs, COALESCE(SUM(i.fat), 0) AS fat "
        "FROM meals m LEFT JOIN meal_items i ON i.meal_id = m.id AND i.deleted_at IS NULL "
        "WHERE m.deleted_at IS NULL AND m.day BETWEEN ? AND ? GROUP BY m.day ORDER BY m.day", (start, end)).fetchall()
    out = []
    for r in rows:
        t = targets.for_day(conn, r["day"])
        out.append({"day": r["day"], "meals": r["meals"], "kcal": round(r["kcal"]), "protein": round(r["protein"]),
                    "carbs": round(r["carbs"]), "fat": round(r["fat"]), "target_kcal": t["kcal"],
                    "target_protein": t["protein"]})
    return out


# What "the same meal" means for Log Again: the AI names a thing a little differently from day to day ("Isopure
# whey isolate protein shake", "Isopure Zero Carb protein shake"), so meals are compared by the words of their
# items, without amounts and joining words.
_SAME_SKIP = {"a", "an", "the", "of", "with", "and", "in", "on", "or", "for", "to", "one", "two", "three", "half",
              "small", "large", "medium", "big", "glass", "cup", "mug", "bowl", "piece", "pieces", "slice", "slices",
              "bite", "some", "plain", "cooked", "homemade", "home", "made", "fresh", "assumed"}
USUAL_DAYS = 90         # meals older than this aren't counted
USUAL_SPREAD = 2.5      # hours: how far from this time of day a meal still counts as "around now"
USUAL_HALF_LIFE = 21    # days: a meal had three weeks ago counts half as much as one had today


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[^\W_]+", text.lower()) if w not in _SAME_SKIP and not w.isdigit())


def _same(a: frozenset[str], b: frozenset[str]) -> bool:
    """Most of the smaller one's words are in the other, and neither is much bigger (so "Naan" isn't the same
    as "Butter chicken and naan")."""
    if not a or not b:
        return a == b
    small, big = sorted((len(a), len(b)))
    return len(a & b) / small >= 0.6 and small / big >= 0.5


def _minutes(t: datetime) -> float:
    return t.hour * 60 + t.minute


def usual_meals(conn: sqlite3.Connection, at: datetime, limit: int = 8) -> list[dict]:
    """Meals to log again, what the owner has most around this time of day first.

    Each distinct meal (see _same) scores for every time it was had in the last USUAL_DAYS days: more the
    nearer that was to this time of day, and more the more recent. Frequent meals still show at other times,
    just lower. One had within three hours of `at` on the same day drops down (it's just been logged). Each
    comes back as its newest copy, with how often it was had and, when it's usually had at one time of day,
    that time."""
    since = (at - timedelta(days=USUAL_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT m.*, group_concat(i.name, ' ') AS item_names FROM meals m "
        "LEFT JOIN meal_items i ON i.meal_id = m.id AND i.deleted_at IS NULL "
        "WHERE m.deleted_at IS NULL AND m.status = 'ready' AND m.title != '' AND m.eaten_at >= ? "
        "GROUP BY m.id ORDER BY m.eaten_at DESC", (since,)).fetchall()
    now_min = _minutes(at)
    groups: list[dict] = []
    for r in rows:
        words = _words(r["item_names"] or r["title"])
        g = next((g for g in groups if _same(g["words"], words)), None)
        if g is None:
            g = {"row": r, "words": words, "score": 0.0, "times": 0, "angles": [], "just_had": False}
            groups.append(g)
        t = datetime.fromisoformat(r["eaten_at"])
        gap = abs(_minutes(t) - now_min) / 60
        gap = min(gap, 24 - gap)
        age = max(0.0, (at - t).total_seconds() / 86400)
        g["score"] += (math.exp(-gap * gap / (2 * USUAL_SPREAD ** 2)) + 0.15) * 0.5 ** (age / USUAL_HALF_LIFE)
        g["times"] += 1
        g["angles"].append(2 * math.pi * _minutes(t) / 1440)
        if t.date() == at.date() and abs((at - t).total_seconds()) <= 3 * 3600:
            g["just_had"] = True
    for g in groups:
        if g["just_had"]:
            g["score"] *= 0.3
    groups.sort(key=lambda g: -g["score"])
    out = []
    for g in groups[:limit]:
        d = meal_dict(conn, g["row"], with_items=False)
        d.pop("item_names", None)
        n = len(g["angles"])
        x, y = sum(math.cos(a) for a in g["angles"]) / n, sum(math.sin(a) for a in g["angles"]) / n
        usual_at = None
        if n >= 3 and math.hypot(x, y) >= 0.75:  # mostly at one time of day
            m = round((math.atan2(y, x) % (2 * math.pi)) * 1440 / (2 * math.pi) / 15) * 15 % 1440
            usual_at = f"{m // 60:02d}:{m % 60:02d}"
        out.append({**d, "times": g["times"], "usual_at": usual_at})
    return out
