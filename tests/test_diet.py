import json

import pytest

from hobbes import changes, db, health, jobs
from hobbes.diet import meals, targets

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def old_table_item(conn, item_id):
    """Make an item what one matched to the food tables (since removed) looks like: a foods row it points at."""
    conn.execute("INSERT OR IGNORE INTO foods (id, source, name, kcal, protein, carbs, fat, fibre, servings, "
                 "created_at, updated_at) VALUES ('indb:D1', 'indb', 'Toor dal (cooked)', 110, 6.5, 15, 3, 3, "
                 "'[{\"name\": \"1 katori\", \"grams\": 150}]', ?, ?)", (db.now(), db.now()))
    grams = conn.execute("SELECT grams FROM meal_items WHERE id = ?", (item_id,)).fetchone()[0]
    per100 = {"kcal": 110, "protein": 6.5, "carbs": 15, "fat": 3, "fibre": 3}
    conn.execute("UPDATE meal_items SET food_id = 'indb:D1', basis = 'table', per100 = ?, kcal = ?, protein = ?, "
                 "carbs = ?, fat = ?, fibre = ? WHERE id = ?",
                 (json.dumps(per100), *(round(per100[k] * grams / 100, 1) for k in per100), item_id))


def reply(items, title="Dal, rice and phulkas", not_food=False):
    return json.dumps({"title": title, "not_food": not_food, "items": items})


def ai_item(name, grams, kcal, portion="1 katori", confidence="medium", brand="", caffeine=0, alcohol=0):
    return {"name": name, "brand": brand, "portion": portion, "grams": grams, "confidence": confidence,
            "per_100g": {"kcal": kcal, "protein": 5, "carbs": 15, "fat": 3, "fibre": 2, "caffeine": caffeine,
                         "alcohol": alcohol}}


# ---------------------------------------------------------------- logging and reading meals

def test_meal_from_photo_and_note(conn, monkeypatch, scratch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([
        ai_item("Toor dal", 150, 120),
        ai_item("Phulka", 60, 290, portion="2 phulkas"),
        ai_item("Achaar", 10, 200),
    ]))
    meal_id = meals.create(conn, eaten_at="2026-10-17T13:05:00+05:30", note="2 phulkas", photos=[JPEG])
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "analysing" and m["day"] == "2026-10-17" and m["slot"] == "lunch"
    assert (meals.photo_dir(meal_id) / "0.jpg").read_bytes() == JPEG
    assert jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "ready" and m["title"] == "Dal, rice and phulkas"
    dal, phulka, achaar = m["items"]  # the AI's own estimates, as they are
    assert dal["food_id"] is None and dal["basis"] == "estimate" and dal["kcal"] == 180.0  # 120 × 1.5
    assert phulka["kcal"] == 174.0 and achaar["kcal"] == 20.0
    assert m["totals"]["kcal"] == 374.0
    (call,) = [json.loads(line) for line in (scratch / "codex.log").read_text().splitlines()]  # no label lookup
    assert "2 phulkas" in call["prompt"] and any(a.startswith("--image=") for a in call["args"])
    assert "search_terms" not in call["prompt"] and 'web_search="live"' not in " ".join(call["args"])


def test_not_food(conn, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([], title="A cat", not_food=True))
    meal_id = meals.create(conn, eaten_at="2026-10-17T09:00:00+05:30", note="", photos=[JPEG])
    jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "failed" and "No food" in (m["error"] or "")


def test_ai_failure_marks_the_meal(conn, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    meal_id = meals.create(conn, eaten_at="2026-10-17T09:00:00+05:30", note="poha", photos=[])
    jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "failed" and "Read Again" in (m["error"] or "")
    assert "something went wrong" in (jobs.get(conn, m["job_id"]) or {})["error"]  # the detail is kept


@pytest.mark.parametrize("kwargs, message", [
    ({"eaten_at": "2026-10-17T09:00:00", "note": "x", "photos": []}, "offset"),
    ({"eaten_at": "yesterday", "note": "x", "photos": []}, "ISO 8601"),
    ({"eaten_at": "2026-10-17T09:00:00+05:30", "note": "", "photos": []}, "Add a photo"),
    ({"eaten_at": "2026-10-17T09:00:00+05:30", "note": "", "photos": [b"GIF89a"]}, "JPEG"),
])
def test_meal_input_is_checked(conn, kwargs, message):
    with pytest.raises(ValueError, match=message):
        meals.create(conn, **kwargs)


# ---------------------------------------------------------------- edits, learning and undo

def _one_dal_meal(conn, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([ai_item("Dal fry", 150, 300)]))
    meal_id = meals.create(conn, eaten_at="2026-10-17T20:00:00+05:30", note="dal", photos=[])
    jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m
    return m


def test_edit_grams_then_undo(conn, monkeypatch):
    m = _one_dal_meal(conn, monkeypatch)
    item = m["items"][0]
    done = meals.edit_item(conn, item["id"], grams=75)
    after = meals.get(conn, m["id"])
    assert after and after["items"][0]["grams"] == 75 and abs(after["items"][0]["kcal"] - item["kcal"] / 2) <= 0.1
    changes.undo(conn, done["change_id"])
    back = meals.get(conn, m["id"])
    assert back and back["items"][0]["grams"] == 150 and back["items"][0]["kcal"] == item["kcal"]
    with pytest.raises(ValueError, match="already"):
        changes.undo(conn, done["change_id"])


def test_undo_refuses_when_changed_again(conn, monkeypatch):
    m = _one_dal_meal(conn, monkeypatch)
    first = meals.edit_item(conn, m["items"][0]["id"], grams=100)
    meals.edit_item(conn, m["items"][0]["id"], grams=120)
    with pytest.raises(ValueError, match="changed again"):
        changes.undo(conn, first["change_id"])


def test_remove_and_restore_item_and_meal(conn, monkeypatch):
    m = _one_dal_meal(conn, monkeypatch)
    gone = meals.remove_item(conn, m["items"][0]["id"])
    after = meals.get(conn, m["id"])
    assert after and after["items"] == []
    changes.undo(conn, gone["change_id"])
    after = meals.get(conn, m["id"])
    assert after and len(after["items"]) == 1
    meal_gone = meals.remove_meal(conn, m["id"])
    assert meals.get(conn, m["id"]) is None
    assert conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 1  # kept, marked removed
    changes.undo(conn, meal_gone["change_id"])
    assert meals.get(conn, m["id"])


def test_log_again_copies_without_ai(conn, monkeypatch, scratch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([ai_item("Toor dal", 150, 120)]))
    meal_id = meals.create(conn, eaten_at="2026-10-16T13:00:00+05:30", note="dal", photos=[JPEG])
    jobs.run_one(conn)
    calls = len((scratch / "codex.log").read_text().splitlines())
    copy_id = meals.log_again(conn, meal_id, "2026-10-17T13:30:00+05:30")
    copy = meals.get(conn, copy_id)
    assert copy and copy["status"] == "ready" and copy["day"] == "2026-10-17" and copy["totals"]["kcal"] == 180.0
    assert (meals.photo_dir(copy_id) / "0.jpg").exists()
    assert len((scratch / "codex.log").read_text().splitlines()) == calls


# ---------------------------------------------------------------- targets

def _profile(conn, weight=80.0):
    targets.save_profile(conn, {"sex": "male", "birth_year": 1993, "height_cm": 178})
    health.store(conn, [{"type": "weight", "value": weight, "unit": "kg", "start": "2026-10-15T07:30:00+05:30"}])


def test_targets_need_a_profile(conn):
    t = targets.for_day(conn, "2026-10-17")
    assert not t["ready"] and set(t["missing"]) == {"weight", "height", "birth year", "sex"}


def test_targets_lose_slightly_without_activity(conn):
    _profile(conn)
    t = targets.for_day(conn, "2026-10-17")
    b = 10 * 80 + 6.25 * 178 - 5 * 33 + 5          # 1752.5
    expected = round((b * 1.375 - 7700 * 0.25 / 7) / 10) * 10
    assert t["ready"] and t["bmr"] == round(b) and t["kcal"] == expected
    assert t["protein"] == 130                      # 1.6 × 80 = 128 → nearest 5
    assert "lose 0.25 kg a week" in t["kcal_how"]


def test_targets_follow_activity_from_health(conn):
    _profile(conn)
    health.store(conn, [{"type": "active_energy", "value": 600, "unit": "kcal",
                         "start": "2026-10-17T00:00:00+05:30", "daily": True}])
    t = targets.for_day(conn, "2026-10-17")
    b = 1752.5
    assert t["active_kcal"] == 600
    assert t["kcal"] == round((b * 1.2 + 300 - 275) / 10) * 10


def test_targets_set_by_hand_and_goal_history(conn):
    _profile(conn)
    targets.save_goal(conn, {"goal": "maintain", "rate": 0.5, "kcal_override": 2100, "protein_override": 140,
                             "eat_back": 0})
    t = targets.for_day(conn, "2026-10-17")
    assert t["kcal"] == 2100 and t["protein"] == 140 and t["goal"]["rate"] == 0
    assert conn.execute("SELECT COUNT(*) FROM diet_goals").fetchone()[0] == 1
    targets.save_goal(conn, {"goal": "lose", "rate": 0.25})
    assert conn.execute("SELECT COUNT(*) FROM diet_goals").fetchone()[0] == 2  # kept, not overwritten
    targets.save_goal(conn, {"goal": "lose", "rate": 0.25})
    assert conn.execute("SELECT COUNT(*) FROM diet_goals").fetchone()[0] == 2  # unchanged: nothing new stored


def test_macro_targets_follow_calories_protein_and_fat_share(conn):
    _profile(conn)
    targets.save_goal(conn, {"goal": "maintain", "kcal_override": 2000, "protein_override": 150, "eat_back": 0,
                             "fat_pct": 0.3})
    t = targets.for_day(conn, "2026-10-17")
    assert t["kcal"] == 2000 and t["protein"] == 150
    assert t["fat"] == round(2000 * 0.3 / 9)                       # 67 g
    assert t["carbs"] == round((2000 - 150 * 4 - 67 * 9) / 4)      # 199 g
    assert t["fibre"] == 28
    assert t["split"] == {"protein": 30, "carbs": 40, "fat": 30}
    with pytest.raises(ValueError, match="fat share"):
        targets.save_goal(conn, {"goal": "lose", "fat_pct": 0.6})


def test_no_macro_targets_without_calories(conn):
    t = targets.for_day(conn, "2026-10-17")
    assert t["carbs"] is None and t["fat"] is None and t["split"] is None


def test_day_summary(conn, monkeypatch):
    _profile(conn)
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([ai_item("Toor dal", 150, 120)]))
    meals.create(conn, eaten_at="2026-10-17T13:00:00+05:30", note="dal", photos=[])
    jobs.run_one(conn)
    s = meals.day_summary(conn, "2026-10-17")
    assert s["eaten"]["kcal"] == 180.0
    assert s["left"]["kcal"] == s["targets"]["kcal"] - 180
    assert s["left"]["carbs"] == round(s["targets"]["carbs"] - s["eaten"]["carbs"])
    assert s["left"]["fat"] == round(s["targets"]["fat"] - s["eaten"]["fat"])
    assert meals.day_summary(conn, "2026-10-18")["meals"] == []


# ---------------------------------------------------------------- Apple Health

def test_health_readings_are_converted_and_deduplicated(conn):
    r = health.store(conn, [
        {"type": "Weight", "value": 176.4, "unit": "lb", "start": "2026-10-17T07:00:00+05:30"},
        {"type": "body_fat_percentage", "value": 0.215, "unit": "%", "start": "2026-10-17T07:00:00+05:30"},
        {"type": "HKQuantityTypeIdentifierHeight", "value": 1.78, "unit": "m", "start": "2026-01-01 09:00:00 +0530"},
        {"type": "steps", "value": 400, "unit": "count", "start": "2026-10-17T08:00:00+05:30"},
        {"type": "steps", "value": 600, "unit": "count", "start": "2026-10-17T09:00:00+05:30"},
        {"type": "blood_glucose", "value": 5, "unit": "mmol/L", "start": "2026-10-17T07:00:00+05:30"},
        {"type": "weight", "value": "heavy", "unit": "kg", "start": "2026-10-17T07:00:00+05:30"},
    ])
    assert r == {"received": 7, "stored": 5, "skipped": 2}
    assert round(health.latest(conn, "weight")["value"], 1) == 80.0  # type: ignore[index]
    assert health.latest(conn, "body_fat")["value"] == 21.5  # type: ignore[index]
    assert health.latest(conn, "height")["value"] == 178.0  # type: ignore[index]
    assert health.day_total(conn, "steps", "2026-10-17") == 1000
    health.store(conn, [{"type": "steps", "value": 650, "unit": "count", "start": "2026-10-17T09:00:00+05:30"}])
    assert health.day_total(conn, "steps", "2026-10-17") == 1050  # same reading updated, not added
    health.store(conn, [{"type": "steps", "value": 7000, "unit": "count", "start": "2026-10-17T00:00:00+05:30",
                         "daily": True}])
    assert health.day_total(conn, "steps", "2026-10-17") == 7000  # a whole-day total wins over readings


HAE_SAMPLE = {"data": {"metrics": [  # Health Auto Export, JSON v2, grouped by day (a real capture's shape)
    {"name": "step_count", "units": "count", "data": [{"qty": 14420, "date": "2026-10-16 00:00:00 +0530",
                                                       "source": "Watch|iPhone"}]},
    {"name": "active_energy", "units": "kJ", "data": [{"date": "2026-10-16 00:00:00 +0530", "qty": 3247.667}]},
    {"name": "basal_energy_burned", "units": "kcal", "data": [{"date": "2026-10-16 00:00:00 +0530", "qty": 1650}]},
    {"name": "weight_body_mass", "units": "kg", "data": [{"date": "2026-10-16 00:00:00 +0530", "qty": 82.798}]},
    {"name": "body_fat_percentage", "units": "%", "data": [{"qty": 17.9, "date": "2026-10-16 00:00:00 +0530"}]},
    {"name": "resting_heart_rate", "units": "count/min", "data": [{"date": "2026-10-16 00:00:00 +0530", "qty": 61}]},
    {"name": "sleep_analysis", "units": "hr", "data": [{"totalSleep": 7.62, "deep": 0.6, "asleep": 0,
                                                        "date": "2026-10-16 00:00:00 +0530"}]},
    {"name": "vo2_max", "units": "ml/(kg·min)", "data": [{"date": "2026-10-16 00:00:00 +0530", "qty": 41}]},
    {"name": "height", "units": "cm", "data": []},
]}}


def test_health_auto_export_payload(client):
    r = client.post("/api/health/samples", json=HAE_SAMPLE, headers={"automation-name": "Dashboard"}).json()
    assert r == {"received": 8, "stored": 7, "skipped": 1}  # vo2_max isn't used yet
    latest = {x["type"]: x["value"] for x in client.get("/api/health/summary").json()["latest"]}
    assert latest["active_energy"] == round(3247.667 / 4.184, 2)
    assert latest["steps"] == 14420 and latest["weight"] == 82.8 and latest["sleep"] == 7.62
    assert latest["resting_hr"] == 61 and latest["resting_energy"] == 1650
    # the same day sent again later with a bigger total replaces it
    again = {"data": {"metrics": [{"name": "step_count", "units": "count",
                                   "data": [{"qty": 15000, "date": "2026-10-16 00:00:00 +0530"}]}]}}
    client.post("/api/health/samples", json=again)
    assert {x["type"]: x["value"] for x in client.get("/api/health/summary").json()["latest"]}["steps"] == 15000


def test_shortcut_lines(client):
    lines = "\n".join(json.dumps(x) for x in [
        {"m": "step_count", "u": "count", "agg": "day", "start": "2026-10-16T00:00:00+05:30", "v": "9,412"},
        {"m": "weight", "u": "kg", "start": "2026-10-17T07:41:00+05:30", "end": "2026-10-17T07:41:00+05:30",
         "v": "78,4"},
        {"m": "body_fat_percentage", "u": "%", "start": "2026-10-17T07:41:00+05:30", "v": "0.18"},
        {"m": "sleep", "start": "2026-10-16T23:00:00+05:30", "end": "2026-10-17T01:00:00+05:30", "v": "Core"},
    ]) + "\nnot json"
    r = client.post("/api/health/samples", json={"source": "iphone-shortcut", "days": 2, "lines": lines}).json()
    assert r == {"received": 5, "stored": 3, "skipped": 2}
    latest = {x["type"]: x["value"] for x in client.get("/api/health/summary").json()["latest"]}
    assert latest == {"weight": 78.4, "body_fat": 18.0, "steps": 9412}


def test_own_shape_and_bad_bodies(client):
    own = {"samples": [{"type": "weight", "value": 79.5, "unit": "kg", "start": "2026-10-17T07:00:00+05:30"}]}
    assert client.post("/api/health/samples", json=own).json()["stored"] == 1
    assert client.post("/api/health/samples", json={"nope": 1}).status_code == 400
    assert client.post("/api/health/samples", json=[1, 2]).status_code == 400


@pytest.mark.parametrize("text, value", [("9,412", 9412), ("78,4", 78.4), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
                                         ("82.79", 82.79), (" 7 000 ", 7000), ("", None), ("Core", None), (True, None)])
def test_locale_numbers(text, value):
    assert health.number(text) == value


def test_use_the_ai_estimate_instead_of_an_old_table_food(conn, monkeypatch):
    m = _one_dal_meal(conn, monkeypatch)
    old_table_item(conn, m["items"][0]["id"])
    item = meals.get(conn, m["id"])["items"][0]  # type: ignore[index]
    assert item["basis"] == "table" and item["kcal"] == 165.0
    done = meals.use_estimate(conn, item["id"])
    after = meals.get(conn, m["id"])["items"][0]  # type: ignore[index]
    assert after["basis"] == "estimate" and after["food_id"] is None
    assert after["kcal"] == 450.0 and after["grams"] == item["grams"]  # the AI's 300 kcal per 100 g × 150 g
    changes.undo(conn, done["change_id"])
    assert meals.get(conn, m["id"])["items"][0] == item  # type: ignore[index]
    copy = meals.get(conn, meals.log_again(conn, m["id"], "2026-10-18T20:00:00+05:30"))
    assert copy and copy["items"][0]["food_id"] == "indb:D1"  # an old table food is kept on a copy
    with pytest.raises(ValueError, match="no AI estimate"):
        meals.use_estimate(conn, copy["items"][0]["id"])


# ---------------------------------------------------------------- adding an item by saying what it was

def test_add_items_from_text_then_undo(conn, monkeypatch, scratch):
    m = _one_dal_meal(conn, monkeypatch)
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"items": [ai_item("Curd (dahi)", 150, 60, portion="1 katori"),
                                                                 ai_item("Papad", 12, 370, portion="1 papad")]}))
    with pytest.raises(ValueError, match="what you had"):
        meals.queue_add(conn, m["id"], "  ")
    job_id = meals.queue_add(conn, m["id"], "a katori of curd   and a papad")
    assert jobs.run_one(conn)
    result = jobs.get(conn, job_id)["result"]  # type: ignore[index]
    after = meals.get(conn, m["id"])
    assert after and [i["name"] for i in after["items"]] == ["Dal fry", "Curd (dahi)", "Papad"]
    assert after["items"][1]["kcal"] == 90.0 and after["items"][1]["basis"] == "estimate"
    assert after["items"][1]["ai_grams"] == 150  # "As read" works for an added item too
    prompt = json.loads((scratch / "codex.log").read_text().splitlines()[-1])["prompt"]
    assert "a katori of curd and a papad" in prompt and "Dal fry (1 katori)" in prompt
    for change_id in result["change_ids"]:
        changes.undo(conn, change_id)
    back = meals.get(conn, m["id"])
    assert back and [i["name"] for i in back["items"]] == ["Dal fry"]
