import json

from hobbes import jobs

from .test_diet import JPEG, ai_item, reply


def test_log_a_meal_end_to_end(client, conn, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply([ai_item("Toor dal", 150, 120)]))
    r = client.post("/api/diet/meals", data={"eaten_at": "2026-10-17T13:05:00+05:30", "note": "dal"},
                    files=[("photos", ("a.jpg", JPEG, "image/jpeg"))],
                    headers={"origin": "http://testserver", "x-hobbes": "1"})
    assert r.status_code == 200, r.text
    meal_id = r.json()["meal_id"]
    jobs.run_one(conn)

    day = client.get("/api/diet/day", params={"day": "2026-10-17"}).json()
    assert day["eaten"]["kcal"] == 180.0  # the AI's own 120 kcal per 100 g
    (meal,) = day["meals"]
    item = meal["items"][0]
    assert meal["id"] == meal_id and item["food_id"] is None and item["basis"] == "estimate"
    assert client.get(f"/api/diet/meals/{meal_id}/photos/0").content == JPEG
    assert client.get(f"/api/diet/meals/{meal_id}/photos/1").status_code == 404

    item_id = meal["items"][0]["id"]
    change = client.patch(f"/api/diet/items/{item_id}", json={"grams": 300}).json()["change_id"]
    assert client.get(f"/api/diet/meals/{meal_id}").json()["totals"]["kcal"] == 360.0
    assert client.post(f"/api/undo/{change}").json()["kind"] == "item.edit"
    assert client.get(f"/api/diet/meals/{meal_id}").json()["totals"]["kcal"] == 180.0

    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"items": [ai_item("Phulka", 60, 290, portion="2 phulkas")]}))
    job = client.post(f"/api/diet/meals/{meal_id}/items", json={"text": "2 phulkas"}).json()["job_id"]
    jobs.run_one(conn)
    (change_id,) = jobs.get(conn, job)["result"]["change_ids"]  # type: ignore[index]
    assert len(client.get(f"/api/diet/meals/{meal_id}").json()["items"]) == 2
    client.post(f"/api/undo/{change_id}")
    assert len(client.get(f"/api/diet/meals/{meal_id}").json()["items"]) == 1
    assert client.post(f"/api/diet/meals/{meal_id}/items", json={"text": " "}).status_code == 400
    hist = client.get("/api/diet/history", params={"start": "2026-10-11", "end": "2026-10-17"}).json()
    assert [d["day"] for d in hist["days"]] == ["2026-10-17"]


def test_meal_upload_from_another_site_is_refused(client):
    r = client.post("/api/diet/meals", data={"eaten_at": "2026-10-17T13:05:00+05:30", "note": "dal"},
                    headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403


def test_bad_input_is_a_plain_400(client):
    r = client.post("/api/diet/meals", data={"eaten_at": "2026-10-17T13:05:00", "note": "dal"},
                    files=[("photos", ("a.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 400 and "offset" in r.json()["detail"]
    assert client.get("/api/diet/day", params={"day": "17/10/2026"}).status_code == 400
    assert client.patch("/api/diet/items/999", json={"grams": 10}).status_code == 404


def test_goals_round_trip(client):
    body = {"goal": "lose", "rate": 0.25, "activity": "light", "sex": "female", "birth_year": 1995,
            "height_cm": 165}
    r = client.put("/api/diet/goals", params={"day": "2026-10-17"}, json=body)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["profile"] == {"sex": "female", "birth_year": 1995, "height_cm": 165.0, "height_from_health": False}
    assert view["targets"]["missing"] == ["weight"]
    w = client.post("/api/diet/weight", json={"kg": 62, "at": "2026-10-17T07:00:00+05:30"}).json()
    assert w["kg"] == 62
    t = client.get("/api/diet/goals", params={"day": "2026-10-17"}).json()["targets"]
    assert t["ready"] and t["kcal"] and t["protein"] == 100


def test_suggestions(client, conn, monkeypatch, scratch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"suggestions": [
        {"name": "Paneer bhurji", "portion": "1 katori", "kcal": 320, "protein": 20, "carbs": 8, "fat": 22,
         "why": "protein"}]}))
    job_id = client.post("/api/diet/suggest", json={"day": "2026-10-17"}).json()["job_id"]
    jobs.run_one(conn)
    j = client.get(f"/api/jobs/{job_id}").json()
    assert j["status"] == "done" and j["result"]["suggestions"][0]["name"] == "Paneer bhurji"
    prompt = json.loads((scratch / "codex.log").read_text().splitlines()[-1])["prompt"]
    assert "targets aren't set yet" in prompt and "Time now:" in prompt
