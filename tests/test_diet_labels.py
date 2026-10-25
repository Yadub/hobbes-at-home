"""Branded food: the product's nutrition label is looked up online and used instead of the AI's estimate."""

import json

import pytest

from hobbes import changes, jobs
from hobbes.diet import labels, meals

from .conftest import codex_calls
from .test_diet import ai_item, reply

LABEL = {"kcal": 380, "protein": 33, "carbs": 30, "fat": 13, "fibre": 9, "caffeine": 0, "alcohol": 0}


def label(index=0, found=True, per100=LABEL, grams=60, source="https://www.yogabars.in/products/protein-bar",
          product="Yoga Bar 20g Protein Bar Chocolate Brownie", portion="1 bar"):
    return {"index": index, "found": found, "product": product, "source": source, "per_100g": per100,
            "grams": grams, "portion": portion}


def script(monkeypatch, tmp_path, *replies):
    """One reply per Codex call, in order."""
    path = tmp_path / "replies.jsonl"
    path.write_text("".join(json.dumps({"reply": r} if not isinstance(r, dict) or "fail" not in r else r) + "\n"
                            for r in replies))
    monkeypatch.setenv("FAKE_CODEX_REPLIES", str(path))


def read(conn, note="yoga bar protein bar chocolate brownie and a toor dal"):
    meal_id = meals.create(conn, eaten_at="2026-10-20T16:00:00+05:30", note=note, photos=[])
    assert jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "ready"
    return m


BAR = ai_item("Protein bar", 50, 420, portion="1 bar", brand="Yoga Bar Protein Bar Chocolate Brownie")
DAL = ai_item("Toor dal", 150, 120)


def test_a_branded_item_uses_its_label(conn, monkeypatch, scratch, tmp_path):
    script(monkeypatch, tmp_path, json.loads(reply([BAR, DAL])), {"items": [label()]})
    bar, dal = read(conn)["items"]
    assert bar["basis"] == "label" and bar["name"] == "Yoga Bar 20g Protein Bar Chocolate Brownie"
    assert bar["per100"] == LABEL and bar["grams"] == 60 and bar["kcal"] == 228.0  # the label's bar size
    assert bar["ai_grams"] == 60 and bar["label_url"] == "https://www.yogabars.in/products/protein-bar"
    assert dal["basis"] == "estimate" and dal["label_url"] is None

    first, second = codex_calls(scratch)
    assert 'web_search="live"' not in " ".join(first["args"])  # reading the meal doesn't search
    assert 'web_search="live"' in " ".join(second["args"])
    assert '"brand": "Yoga Bar Protein Bar Chocolate Brownie"' in second["prompt"]
    assert "Toor dal" not in second["prompt"]
    runs = conn.execute("SELECT kind, search FROM ai_runs ORDER BY id").fetchall()
    assert [tuple(r) for r in runs] == [("diet.analyse", 0), ("diet.label", 1)]


def test_no_branded_item_means_no_search(conn, monkeypatch, scratch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([DAL]))
    read(conn, note="toor dal")
    assert len(codex_calls(scratch)) == 1


@pytest.mark.parametrize("answer, why", [
    (label(found=False, source=""), "The label wasn't found."),
    (label(source="yogabars.in"), "No page was given for the label."),
    (label(per100={**LABEL, "kcal": 900}), "The label's numbers didn't add up."),  # 33+30+13 g give ~370 kcal
    (label(per100={**LABEL, "fat": -1}), "The label's numbers didn't add up."),
    ({"fail": True}, "The label couldn't be looked up."),
])
def test_the_estimate_stays_when_the_label_cant_be_used(conn, monkeypatch, scratch, tmp_path, answer, why):
    script(monkeypatch, tmp_path, json.loads(reply([BAR, DAL])), answer if "fail" in answer else {"items": [answer]})
    bar = read(conn)["items"][0]
    assert bar["basis"] == "estimate" and bar["name"] == "Protein bar" and bar["grams"] == 50
    assert bar["per100"]["kcal"] == 420 and bar["label_url"] is None
    row = conn.execute("SELECT ai FROM meal_items WHERE id = ?", (bar["id"],)).fetchone()
    assert json.loads(row["ai"])["label"]["why"] == why


def test_adding_a_branded_item_looks_up_its_label(conn, monkeypatch, scratch, tmp_path):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([DAL]))
    m = read(conn, note="dal")
    script(monkeypatch, tmp_path, {"items": [BAR]}, {"items": [label()]})
    meals.queue_add(conn, m["id"], "and a yoga bar chocolate brownie protein bar")
    assert jobs.run_one(conn)
    bar = meals.get(conn, m["id"])["items"][1]  # type: ignore[index]
    assert bar["basis"] == "label" and bar["grams"] == 60 and bar["kcal"] == 228.0
    assert 'web_search="live"' in " ".join(codex_calls(scratch)[-1]["args"])


def test_redo_looks_up_the_label_of_the_corrected_product(conn, monkeypatch, scratch, tmp_path):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([DAL]))
    m = read(conn, note="dal")
    dal = m["items"][0]
    curd = ai_item("Greek yogurt", 100, 90, portion="1 cup", brand="Epigamia Greek Yogurt Blueberry")
    script(monkeypatch, tmp_path, {"item": curd},
           {"items": [label(per100={"kcal": 105, "protein": 7, "carbs": 13, "fat": 2.8, "fibre": 0, "caffeine": 0,
                                    "alcohol": 0}, grams=90,
                            product="Epigamia Greek Yogurt Blueberry", portion="1 cup (90 g)",
                            source="https://www.epigamia.com/products/greek-yogurt-blueberry")]})
    meals.queue_redo(conn, dal["id"], "it was an epigamia blueberry greek yogurt")
    assert jobs.run_one(conn)
    item = meals.get(conn, m["id"])["items"][0]
    assert item["basis"] == "label" and item["name"] == "Epigamia Greek Yogurt Blueberry" and item["grams"] == 90
    assert item["kcal"] == 94.5
    assert "their correction: it was an epigamia blueberry greek yogurt" in codex_calls(scratch)[-1]["prompt"].lower()

    change = conn.execute("SELECT id FROM changes WHERE kind = 'item.redo' ORDER BY id DESC").fetchone()
    changes.undo(conn, change["id"])
    assert meals.get(conn, m["id"])["items"][0]["name"] == "Toor dal"


def test_use_the_ai_estimate_instead_of_the_label(conn, monkeypatch, scratch, tmp_path):
    script(monkeypatch, tmp_path, json.loads(reply([BAR])), {"items": [label()]})
    bar = read(conn)["items"][0]
    meals.use_estimate(conn, bar["id"])
    after = meals.get(conn, bar["meal_id"])["items"][0]
    assert after["basis"] == "estimate" and after["per100"]["kcal"] == 420 and after["grams"] == 60
    assert after["label_url"] is None


def test_adds_up():
    assert labels.adds_up(LABEL)
    assert labels.adds_up({"kcal": 0, "protein": 0, "carbs": 0, "fat": 0, "fibre": 0})  # a diet drink
    assert not labels.adds_up({"kcal": 950, "protein": 0, "carbs": 0, "fat": 100, "fibre": 0})
    assert not labels.adds_up({**LABEL, "carbs": 80})  # more than 100 g in 100 g
