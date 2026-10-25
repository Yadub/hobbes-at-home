"""Diet: redoing one item with the owner's correction (in place, with Undo), and "Why these numbers?" (the AI's
explanation, kept until the meal changes)."""

import json

import pytest

from hobbes import changes, jobs
from hobbes.diet import explain, meals

from .conftest import codex_calls
from .test_diet import JPEG, ai_item, old_table_item, reply


def _meal(conn, monkeypatch, photos=()):
    """Dal (from an old table food) and pickle (the AI's estimate)."""
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([ai_item("Toor dal", 150, 120), ai_item("Achaar", 10, 200)]))
    meal_id = meals.create(conn, eaten_at="2026-10-17T13:05:00+05:30", note="dal and pickle", photos=list(photos))
    assert jobs.run_one(conn)
    m = meals.get(conn, meal_id)
    assert m and m["status"] == "ready"
    old_table_item(conn, m["items"][0]["id"])
    return meals.get(conn, meal_id)


def test_redo_one_item_with_a_correction_then_undo(conn, monkeypatch, scratch):
    m = _meal(conn, monkeypatch, photos=[JPEG])
    dal, achaar = m["items"]
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"item": ai_item("Moong dal", 300, 105, portion="2 katoris")}))
    with pytest.raises(ValueError, match="what's different"):
        meals.queue_redo(conn, dal["id"], "   ")
    job_id = meals.queue_redo(conn, dal["id"], "it was moong dal,   about 2 katoris")
    assert jobs.run_one(conn)
    result = json.loads(conn.execute("SELECT result FROM jobs WHERE id = ?", (job_id,)).fetchone()[0])
    after = meals.get(conn, m["id"])
    assert after
    redone = after["items"][0]
    assert redone["id"] == dal["id"] and redone["name"] == "Moong dal" and redone["grams"] == 300
    assert redone["kcal"] == round(redone["per100"]["kcal"] * 3, 1)  # the numbers follow the new amount
    assert after["items"][1] == achaar  # the others are left alone
    prompt = codex_calls(scratch)[-1]["prompt"]
    assert "it was moong dal, about 2 katoris" in prompt and '"name": "Toor dal"' in prompt
    assert "dal and pickle" in prompt
    assert any(a.startswith("--image=") for a in codex_calls(scratch)[-1]["args"])

    changes.undo(conn, result["change_id"])
    back = meals.get(conn, m["id"])
    assert back and back["items"][0]["name"] == "Toor dal" and back["items"][0]["grams"] == 150
    assert back["items"][0]["ai_grams"] == 150  # the earlier reading is back too


def test_why_these_numbers_is_kept_until_the_meal_changes(conn, monkeypatch, scratch):
    m = _meal(conn, monkeypatch)
    dal, achaar = m["items"]
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"summary": "Most of the energy is the dal.", "items": [
        {"ref": "i1", "why": "One katori is about 150 g; the Indian Nutrient Databank's toor dal.", "doubt": ""},
        {"ref": "i2", "why": "A spoon of pickle; the AI's own estimate.", "doubt": "Oil makes it vary."},
        {"ref": "i9", "why": "Not an item.", "doubt": ""}]}))
    started = explain.queue(conn, m["id"])
    assert started["explanation"] is None and started["job_id"]
    assert explain.queue(conn, m["id"])["job_id"] == started["job_id"]  # not asked twice
    assert jobs.run_one(conn)
    facts = json.loads(codex_calls(scratch)[-1]["prompt"].split("The meal (JSON):\n", 1)[1])
    assert facts["items"][0]["values_from"].startswith("Toor dal (cooked), in the Indian Nutrient Databank")
    assert facts["items"][1]["values_from"] == "the AI's own estimate"
    assert facts["items"][0]["ai_estimate_per_100g"]["kcal"] == 120

    kept = explain.cached(conn, m["id"])
    assert kept and kept["summary"] == "Most of the energy is the dal."
    doubts = [(x["item_id"], x["doubt"]) for x in kept["items"]]
    assert doubts == [(dal["id"], ""), (achaar["id"], "Oil makes it vary.")]
    calls = len(codex_calls(scratch))
    assert explain.queue(conn, m["id"])["explanation"] == kept and len(codex_calls(scratch)) == calls

    meals.edit_item(conn, dal["id"], grams=75)  # the meal changed: the explanation is stale
    assert explain.cached(conn, m["id"]) is None
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"summary": "x", "items": []}))
    jobs.run_one(conn) if explain.queue(conn, m["id"])["job_id"] else None
    facts = json.loads(codex_calls(scratch)[-1]["prompt"].split("The meal (JSON):\n", 1)[1])
    assert facts["items"][0]["changed_by_owner"] is True and facts["items"][0]["first_read_grams"] == 150


def test_through_the_api(client, conn, monkeypatch):
    m = _meal(conn, monkeypatch)
    item_id = m["items"][0]["id"]
    assert client.get(f"/api/diet/meals/{m['id']}/explanation").json() is None
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"summary": "Mostly dal.", "items": [
        {"ref": "i1", "why": "One katori.", "doubt": ""}, {"ref": "i2", "why": "A spoon.", "doubt": ""}]}))
    r = client.post(f"/api/diet/meals/{m['id']}/explain").json()
    assert r["explanation"] is None and r["job_id"]
    assert jobs.run_one(conn)
    assert client.get(f"/api/diet/meals/{m['id']}/explanation").json()["summary"] == "Mostly dal."
    assert client.post(f"/api/diet/meals/{m['id']}/explain").json()["job_id"] is None
    assert client.post("/api/diet/meals/999/explain").status_code == 404

    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"item": ai_item("Moong dal", 300, 105)}))
    job = client.post(f"/api/diet/items/{item_id}/redo", json={"correction": "moong dal"}).json()["job_id"]
    assert jobs.run_one(conn)
    assert client.get(f"/api/jobs/{job}").json()["result"]["change_id"]
    assert client.post(f"/api/diet/items/{item_id}/redo", json={"correction": ""}).status_code == 422
    assert client.post("/api/diet/items/999/redo", json={"correction": "x"}).status_code == 404


def test_own_nutrients_scale_with_the_amount_and_undo(client, conn, monkeypatch):
    m = _meal(conn, monkeypatch)
    dal = m["items"][0]
    done = meals.edit_item(conn, dal["id"], nutrients={"protein": 18, "carbs": 30, "fat": 9, "kcal": None})
    item = meals.get(conn, m["id"])["items"][0]  # type: ignore[index]
    assert (item["protein"], item["carbs"], item["fat"], item["basis"]) == (18.0, 30.0, 9.0, "owner")
    assert item["kcal"] == dal["kcal"]  # left out: kept
    meals.edit_item(conn, dal["id"], grams=75)  # half the amount: half the numbers
    item = meals.get(conn, m["id"])["items"][0]  # type: ignore[index]
    assert (item["protein"], item["carbs"], item["fat"]) == (9.0, 15.0, 4.5)
    with pytest.raises(ValueError, match="Protein must be between"):
        meals.edit_item(conn, dal["id"], nutrients={"protein": -1})
    changes.undo(conn, conn.execute("SELECT max(id) FROM changes").fetchone()[0])  # the 75 g
    changes.undo(conn, done["change_id"])
    back = meals.get(conn, m["id"])["items"][0]  # type: ignore[index]
    assert back["protein"] == dal["protein"] and back["basis"] == dal["basis"]

    r = client.patch(f"/api/diet/items/{dal['id']}", json={"nutrients": {"fat": 12.5}})
    assert r.status_code == 200, r.text
    assert meals.get(conn, m["id"])["items"][0]["fat"] == 12.5  # type: ignore[index]
    assert client.patch(f"/api/diet/items/{dal['id']}", json={"nutrients": {"fat": 5000}}).status_code == 400
