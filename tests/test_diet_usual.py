"""Log Again: what's usually had, around this time of day, first."""

from datetime import datetime, timedelta

from hobbes.diet import meals

IST = "+05:30"


def logged(conn, when: str, title: str, *items: str) -> int:
    meal_id = meals.create(conn, eaten_at=when, note=title, photos=[], analyse=False)
    for n, name in enumerate(items or (title,)):
        meals._insert_item(conn, meal_id, n, name=name, grams=100, portion="", basis="estimate", confidence="high",
                           per100={"kcal": 100, "protein": 5, "carbs": 10, "fat": 3, "fibre": 0}, ai_reading=None)
    conn.execute("UPDATE meals SET status = 'ready', title = ? WHERE id = ?", (title, meal_id))
    return meal_id


def day(n: int, hhmm: str) -> str:
    return (datetime(2026, 10, 21) - timedelta(days=n)).strftime("%Y-%m-%d") + f"T{hhmm}:00{IST}"


def morning_and_evening(conn):
    shakes = ["Chocolate Isopure protein shake", "Isopure whey isolate protein shake",
              "Isopure Zero Carb protein shake"]
    for n in range(10, 0, -1):
        logged(conn, day(n, "08:30"), "Cappuccino")
        logged(conn, day(n, "08:40"), "Mixed vegetable juice" if n % 2 else "Vegetable juice")
        logged(conn, day(n, "09:00"), shakes[n % 3])
        logged(conn, day(n, "20:00"), "Dal and rice", "Toor dal", "Jeera rice")
    logged(conn, day(1, "21:30"), "Pizza")  # the newest, but only once


def titles(conn, at: str, limit: int = 3) -> list[str]:
    return [m["title"] for m in meals.usual_meals(conn, datetime.fromisoformat(at), limit=limit)]


def test_the_morning_usuals_come_first_in_the_morning(conn):
    morning_and_evening(conn)
    top = meals.usual_meals(conn, datetime.fromisoformat(day(0, "08:15")), limit=3)
    assert {m["title"] for m in top} == {"Cappuccino", "Mixed vegetable juice", "Isopure whey isolate protein shake"}
    shake = next(m for m in top if "Isopure" in m["title"])
    assert shake["times"] == 10  # three names, one shake; the newest copy is the one logged again
    assert next(m for m in top if "juice" in m["title"])["times"] == 10  # and two names, one juice
    cappuccino = next(m for m in top if m["title"] == "Cappuccino")
    assert cappuccino["usual_at"] == "08:30" and cappuccino["items"] == []


def test_the_evening_meal_comes_first_in_the_evening(conn):
    morning_and_evening(conn)
    assert titles(conn, day(0, "20:15"), 1) == ["Dal and rice"]
    assert "Pizza" not in titles(conn, day(0, "08:15"), 4)  # newest, but had once, late at night


def test_just_had_drops_down(conn):
    morning_and_evening(conn)
    logged(conn, day(0, "08:00"), "Cappuccino")
    assert titles(conn, day(0, "08:20"))[0] != "Cappuccino"
    assert titles(conn, day(0, "16:00"), 6).count("Cappuccino") == 1  # later in the day it's back up


def test_a_dish_is_not_the_same_as_a_meal_containing_it(conn):
    logged(conn, day(2, "13:00"), "Naan")
    logged(conn, day(1, "13:00"), "Butter chicken and naan", "Butter chicken", "Naan")
    got = meals.usual_meals(conn, datetime.fromisoformat(day(0, "13:00")))
    assert sorted(m["title"] for m in got) == ["Butter chicken and naan", "Naan"]


def test_through_the_api(client, conn):
    morning_and_evening(conn)
    r = client.get("/api/diet/recent", params={"at": day(0, "08:15")})
    assert r.status_code == 200, r.text
    first = r.json()[0]
    assert first["title"] in {"Cappuccino", "Mixed vegetable juice", "Isopure whey isolate protein shake"}
    assert first["times"] == 10 and first["usual_at"]
    assert client.get("/api/diet/recent", params={"at": "tomorrow"}).status_code == 400
    assert client.get("/api/diet/recent", params={"at": "2026-10-21T08:15:00"}).status_code == 400
    assert client.get("/api/diet/recent").status_code == 200
