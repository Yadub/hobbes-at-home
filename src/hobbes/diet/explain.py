"""Why these numbers: the AI explains how a meal's items came to their amounts and nutrients.

The numbers were settled earlier (the AI's reading, a product's label, the owner's own changes); this explains
them as they are, from the facts behind each item, with the photos attached so it can say how a portion was
judged. It doesn't judge the meal or give advice. The answer is kept in meals.explanation with a fingerprint
of the meal (note, photos, items and their numbers), so it's reused until something changes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .. import ai, db, jobs
from . import foods, meals

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"ref": {"type": "string"}, "why": {"type": "string"}, "doubt": {"type": "string"}},
            "required": ["ref", "why", "doubt"],
            "additionalProperties": False,
        }},
    },
    "required": ["summary", "items"],
    "additionalProperties": False,
}

SOURCES = {
    "indb": "the Indian Nutrient Databank (its values are per 100 g of a recipe's raw ingredients)",
    "ifct": "the Indian Food Composition Tables 2017 (mostly raw foods)",
    "fndds": "USDA FoodData Central",
    "mine": "the owner's own foods",
}

PROMPT = """You explain to one person how their food diary arrived at the numbers for a meal they logged. Do not
run any commands.

The numbers were worked out earlier. An AI read the photo(s) and note into items, each with a portion in grams
and its own estimate of the nutrients per 100 g. For a branded product, its nutrition label was then looked
up online and, when found, used instead (with the label's pack size for counted packs). Some older items use
a food table's values instead. The owner may have changed an amount since, typed in their own numbers, added
an item, or asked for an item to be redone with a correction. Explain the numbers as they are, from the facts
below{photos}. Never invent other figures.

Plain British English, specific and short. Don't judge the meal or give diet advice: only explain the numbers.

- summary: one or two sentences on what makes up most of the meal's energy and protein.
- items, one for each item, with its ref exactly as given:
  - why: two or three sentences: how the amount was arrived at (the household measure and what it weighs,
    the photo, the note, or the owner's own change), where the per-100 g values come from (the product's label,
    which table and food, or the AI's own estimate), and what drives its numbers (for example
    the ghee for fat, the rice for carbs).
  - doubt: one sentence on what is most likely to be off and what it would change ("If it was two bowls,
    double it"), or an empty string when nothing stands out.

The meal (JSON):
{meal}"""


def fingerprint(m: dict) -> str:
    """What the explanation depends on: when this changes, it's stale."""
    numbers = [(i["id"], i["name"], i["grams"], i["food_id"], i["kcal"], i["protein"], i["carbs"], i["fat"])
               for i in m["items"]]
    parts = [m["note"], m["photos"], numbers]
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def facts(conn: sqlite3.Connection, m: dict) -> tuple[dict, dict[str, int]]:
    """The meal as the AI is told it, and which ref is which item."""
    refs: dict[str, int] = {}
    items = []
    for n, i in enumerate(m["items"], 1):
        ref = f"i{n}"
        refs[ref] = i["id"]
        row = conn.execute("SELECT ai FROM meal_items WHERE id = ?", (i["id"],)).fetchone()
        reading = json.loads(row["ai"]) if row and row["ai"] else {}
        food = foods.get(conn, i["food_id"]) if i["food_id"] else None
        fact: dict[str, Any] = {
            "ref": ref, "name": i["name"], "portion": i["portion"], "grams": i["grams"],
            "nutrients": {k: i[k] for k in ("kcal", "protein", "carbs", "fat", "fibre")},
            "per_100g_used": i["per100"],
            "values_from": ("the owner's own numbers, typed in by hand" if i["basis"] == "owner"
                            else f"{food['name']}, in {SOURCES.get(food['source'], food['source'])}" if food
                            else "the product's nutrition label, found online" if i["basis"] == "label"
                            else "the AI's own estimate"),
            "confidence_of_reading": i["confidence"],
        }
        if reading.get("per_100g") and food:
            fact["ai_estimate_per_100g"] = reading["per_100g"]
        if reading.get("grams") and abs(float(reading["grams"]) - float(i["grams"])) > 0.5:
            fact["first_read_grams"] = reading["grams"]
        if i.get("edited_at"):
            fact["changed_by_owner"] = True
        label = reading.get("label")
        if label and label.get("used") and i["basis"] == "label":
            fact["label"] = {"product": label["product"], "page": label["source"]}
            if abs(float(label.get("read_grams") or 0) - float(reading.get("grams") or 0)) > 0.5:
                fact["amount_from_label_pack_size"] = True
        elif label:
            fact["label_not_used"] = label.get("why")
        if reading.get("correction"):
            fact["owners_correction"] = reading["correction"]
        if not reading:
            fact["added_by_owner"] = True
        elif reading.get("added"):
            fact["added_later_as"] = reading["added"]
        items.append(fact)
    meal = {"title": m["title"], "note": m["note"] or None, "totals": m["totals"], "items": items}
    return meal, refs


def cached(conn: sqlite3.Connection, meal_id: int) -> dict | None:
    """The kept explanation, if the meal hasn't changed since."""
    m = meals.get(conn, meal_id)
    if not m:
        raise LookupError("There's no such meal.")
    row = conn.execute("SELECT explanation FROM meals WHERE id = ?", (meal_id,)).fetchone()
    kept = json.loads(row["explanation"]) if row and row["explanation"] else None
    if not kept or kept.get("for") != fingerprint(m):
        return None
    return {"summary": kept["summary"], "items": kept["items"], "at": kept["at"]}


def explain(conn: sqlite3.Connection, meal_id: int) -> dict:
    m = meals.get(conn, meal_id)
    if not m:
        raise LookupError("There's no such meal.")
    if not m["items"]:
        raise ValueError("There's nothing in this meal to explain yet.")
    meal, refs = facts(conn, m)
    images = sorted(meals.photo_dir(meal_id).glob("*.jpg"), key=lambda p: int(p.stem)) if m["photos"] else []
    prompt = (PROMPT.replace("{photos}", ", and the photo(s) attached" if images else "")
              .replace("{meal}", json.dumps(meal, ensure_ascii=False, indent=1)))
    answer = ai.ask(prompt, schema=SCHEMA, images=images, kind="diet.explain", timeout=240, conn=conn)
    by_item: list[dict] = []
    seen: set[int] = set()
    for x in answer["items"]:
        item_id = refs.get(str(x.get("ref")))
        if item_id is None or item_id in seen:
            continue
        seen.add(item_id)
        by_item.append({"item_id": item_id, "why": " ".join(str(x.get("why") or "").split())[:800],
                        "doubt": " ".join(str(x.get("doubt") or "").split())[:300]})
    kept = {"for": fingerprint(m), "at": db.now(), "summary": " ".join(answer["summary"].split())[:600],
            "items": by_item}
    conn.execute("UPDATE meals SET explanation = ? WHERE id = ?", (json.dumps(kept, ensure_ascii=False), meal_id))
    return {"summary": kept["summary"], "items": by_item, "at": kept["at"]}


def queue(conn: sqlite3.Connection, meal_id: int) -> dict:
    """The kept explanation when it's still right, or a job working one out."""
    found = cached(conn, meal_id)
    if found:
        return {"explanation": found, "job_id": None}
    m = meals.get(conn, meal_id)
    if m and not m["items"]:
        raise ValueError("There's nothing in this meal to explain yet.")
    busy = conn.execute("SELECT id FROM jobs WHERE kind = 'diet.explain' AND status IN ('queued', 'running') "
                        "AND json_extract(payload, '$.meal_id') = ?", (meal_id,)).fetchone()
    job_id = busy[0] if busy else jobs.enqueue(conn, "diet.explain", {"meal_id": meal_id}, max_attempts=1)
    return {"explanation": None, "job_id": job_id}


@jobs.handler("diet.explain")
def explain_job(conn: sqlite3.Connection, payload: dict) -> dict:
    e = explain(conn, int(payload["meal_id"]))
    return {"items": len(e["items"])}
