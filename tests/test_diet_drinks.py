"""Caffeine and alcohol: carried by every reading, worked out once for older items, and summed up."""

import json

from hobbes import changes, jobs
from hobbes.diet import drinks, labels, meals

from .conftest import codex_calls
from .test_diet import ai_item, reply


def read(conn, monkeypatch, when, *items):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply(list(items), title="Drinks"))
    meal_id = meals.create(conn, eaten_at=when, note="drinks", photos=[])
    assert jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "ready"
    return m


CAPPUCCINO = ai_item("Cappuccino", 200, 60, portion="1 cup", caffeine=40)
BEER = ai_item("Kingfisher Ultra beer", 330, 43, portion="1 can", alcohol=3.9)


def test_a_reading_carries_caffeine_and_alcohol(conn, monkeypatch, scratch):
    m = read(conn, monkeypatch, "2026-10-21T18:00:00+05:30", CAPPUCCINO, BEER)
    cappuccino, beer = m["items"]
    assert cappuccino["caffeine"] == 80.0 and cappuccino["alcohol"] == 0.0
    assert beer["alcohol"] == 12.9 and drinks.units(beer["alcohol"]) == 1.6  # a 330 ml can at 5%
    assert m["totals"]["caffeine"] == 80.0 and meals.day_summary(conn, "2026-10-21")["eaten"]["alcohol"] == 12.9
    assert "caffeine (mg" in codex_calls(scratch)[-1]["prompt"]

    done = meals.edit_item(conn, beer["id"], grams=165)  # half the can: half the alcohol
    assert meals.get(conn, m["id"])["items"][1]["alcohol"] == 6.4  # type: ignore[index]
    changes.undo(conn, done["change_id"])
    assert meals.get(conn, m["id"])["items"][1]["alcohol"] == 12.9  # type: ignore[index]


def older_items(conn):
    """Two items logged before caffeine and alcohol were read: per100 without them."""
    meal_id = meals.create(conn, eaten_at="2026-10-20T09:00:00+05:30", note="old", photos=[], analyse=False)
    ids = [meals._insert_item(conn, meal_id, n, name=name, grams=grams, portion="", basis="estimate",
                              confidence="high", ai_reading=None,
                              per100={"kcal": kcal, "protein": 1, "carbs": 5, "fat": 2, "fibre": 0})
           for n, (name, grams, kcal) in enumerate([("Cappuccino", 200, 60), ("Red wine", 150, 85)])]
    conn.execute("UPDATE meals SET status = 'ready', title = 'Old' WHERE id = ?", (meal_id,))
    return meal_id, ids


def test_older_items_are_worked_out_once(conn, monkeypatch, scratch):
    meal_id, (coffee, wine) = older_items(conn)
    item = meals.get(conn, meal_id)["items"][0]  # type: ignore[index]
    assert item["caffeine"] is None and drinks.missing(conn) == 2
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"items": [
        {"ref": f"i{coffee}", "caffeine": 40, "alcohol": 0}, {"ref": f"i{wine}", "caffeine": 0, "alcohol": 9.5}]}))
    assert drinks.backfill(conn) == {"items": 2, "left": 0}
    coffee_row, wine_row = meals.get(conn, meal_id)["items"]  # type: ignore[index]
    assert coffee_row["caffeine"] == 80.0 and wine_row["alcohol"] == 14.2 and wine_row["per100"]["alcohol"] == 9.5
    prompt = codex_calls(scratch)[-1]["prompt"]
    assert '"name": "Red wine"' in prompt and f'"ref": "i{wine}"' in prompt
    change = conn.execute("SELECT id FROM changes WHERE kind = 'item.drinks' ORDER BY id DESC").fetchone()
    changes.undo(conn, change["id"])  # recorded like any other change
    assert meals.get(conn, meal_id)["items"][1]["alcohol"] is None  # type: ignore[index]


def test_an_item_the_ai_skips_is_left_for_the_next_run(conn, monkeypatch):
    _, (coffee, _wine) = older_items(conn)
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"items": [{"ref": f"i{coffee}", "caffeine": 40, "alcohol": 0}]}))
    assert drinks.backfill(conn) == {"items": 1, "left": 1}


def test_on_by_default_and_turning_it_on_works_out_what_is_missing(conn):
    assert drinks.enabled(conn)
    older_items(conn)
    drinks.set_enabled(conn, False)
    assert drinks.backfill_job(conn, {}) == {"skipped": "tracking is off"}
    drinks.set_enabled(conn, True)
    queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'diet.drinks_backfill' AND status = 'queued'")
    assert queued.fetchone()[0] == 1
    drinks.set_enabled(conn, True)  # not twice
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'diet.drinks_backfill'").fetchone()[0] == 1


def test_week_and_month_are_averaged_over_logged_days(conn, monkeypatch):
    read(conn, monkeypatch, "2026-10-20T18:00:00+05:30", CAPPUCCINO, BEER)
    read(conn, monkeypatch, "2026-10-21T09:00:00+05:30", ai_item("Cappuccino", 400, 60, caffeine=40))
    read(conn, monkeypatch, "2026-10-01T09:00:00+05:30", ai_item("Espresso", 60, 9, caffeine=700))
    week = drinks.span(conn, "2026-10-21", 7)
    assert (week["logged_days"], week["caffeine_per_day"], week["caffeine_highest"]) == (2, 120, 160)
    assert (week["caffeine_total"], week["caffeine_per_week"], week["alcohol_units_total"]) == (240, 840, 1.6)
    assert week["alcohol_units_per_week"] == 5.6  # 1.6 units over 2 logged days, as a week
    assert (week["alcohol_free_days"], week["alcohol_heaviest_day"], week["caffeine_days_over"]) == (1, 1.6, 0)
    month = drinks.span(conn, "2026-10-21", 30)
    assert month["logged_days"] == 3 and month["caffeine_days_over"] == 1  # 420 mg on 1 October
    empty = drinks.span(conn, "2026-09-01", 7)
    assert empty["caffeine_per_day"] is None and empty["alcohol_units_per_week"] is None


def test_through_the_api(client, conn, monkeypatch):
    read(conn, monkeypatch, "2026-10-21T18:00:00+05:30", CAPPUCCINO, BEER)
    v = client.get("/api/diet/drinks", params={"day": "2026-10-21"}).json()
    assert v["enabled"] is True and v["today"] == {"caffeine": 80, "alcohol_units": 1.6}
    assert v["reference"]["alcohol"]["aim"] == 14 and v["reference"]["caffeine"]["aim"] == 400
    day = client.get("/api/diet/day", params={"day": "2026-10-21"}).json()
    assert day["eaten"]["caffeine"] == 80.0 and day["meals"][0]["items"][1]["alcohol"] == 12.9
    off = client.put("/api/diet/drinks", params={"day": "2026-10-21"}, json={"enabled": False}).json()
    assert off["enabled"] is False


def test_a_drinks_label_adds_up_with_its_alcohol():
    beer = {"kcal": 43, "protein": 0.3, "carbs": 3.6, "fat": 0, "fibre": 0, "caffeine": 0, "alcohol": 3.9}
    whisky = {"kcal": 222, "protein": 0, "carbs": 0, "fat": 0, "fibre": 0, "caffeine": 0, "alcohol": 31.6}
    assert labels.adds_up(beer) and labels.adds_up(whisky)
    assert not labels.adds_up({**beer, "alcohol": -1})


def test_today_is_left_out_of_the_averages_until_it_is_over(conn, monkeypatch):
    read(conn, monkeypatch, "2026-10-20T09:00:00+05:30", ai_item("Espresso", 100, 9, caffeine=300))
    read(conn, monkeypatch, "2026-10-21T09:00:00+05:30", ai_item("Cappuccino", 125, 60, caffeine=40))  # so far
    assert drinks.span(conn, "2026-10-21", 7, now="2026-10-21")["caffeine_per_day"] == 300
    assert drinks.span(conn, "2026-10-21", 7, now="2026-10-21")["today_left_out"] is True
    assert drinks.span(conn, "2026-10-21", 7, now="2026-10-22")["caffeine_per_day"] == 175
    only = drinks.span(conn, "2026-10-20", 7, now="2026-10-20")  # the only day logged still counts
    assert only["caffeine_per_day"] == 300 and only["today_left_out"] is False
