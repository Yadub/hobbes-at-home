import json
import typing

from hobbes import jobs
from hobbes.assistant import actions, api, profile

from .test_assistant import answer


def test_a_task_through_the_api(client, conn, monkeypatch):
    r = client.post("/api/assistant/tasks", json={"request": "Compare flights Mumbai–Bangkok, first week of December"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "working" and task["title"].startswith("Compare flights")
    assert [s["kind"] for s in task["steps"]] == ["asked"]

    q = {"text": "Which day suits you?", "why": "Fares differ a lot.", "choices": ["1 Dec", "3 Dec"]}
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(answer(status="needs_you", question=q)))
    jobs.run_one(conn)
    listing = client.get("/api/assistant/tasks").json()
    (summary,) = listing["tasks"]
    assert summary["status"] == "needs_you" and summary["question"]["choices"] == ["1 Dec", "3 Dec"]
    assert summary["latest"] == "Which day suits you?" and summary["pick"] == "Casa Lisboa"

    r = client.post(f"/api/assistant/tasks/{task['id']}/messages", json={"text": "3 Dec"})
    assert r.json()["status"] == "working"
    stopped = client.post(f"/api/assistant/tasks/{task['id']}/stop").json()
    assert stopped["status"] == "cancelled"
    assert client.post(f"/api/assistant/tasks/{task['id']}/stop").status_code == 400
    assert client.post(f"/api/assistant/tasks/{task['id']}/retry").json()["status"] == "working"

    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(answer()))
    while jobs.run_one(conn):
        pass
    done = client.get(f"/api/assistant/tasks/{task['id']}").json()
    assert done["status"] == "done" and done["result"]["recommended"] == 0
    assert done["result"]["actions"][0]["status"] == "proposed"

    change = client.delete(f"/api/assistant/tasks/{task['id']}").json()["change_id"]
    assert client.get(f"/api/assistant/tasks/{task['id']}").status_code == 404
    assert client.get("/api/assistant/tasks").json()["tasks"] == []
    assert client.post(f"/api/undo/{change}").status_code == 200
    assert client.get(f"/api/assistant/tasks/{task['id']}").status_code == 200


def test_bad_requests(client):
    assert client.post("/api/assistant/tasks", json={"request": ""}).status_code == 422
    assert client.post("/api/assistant/tasks", json={"request": "   "}).status_code == 400
    assert client.get("/api/assistant/tasks/99").status_code == 404
    assert client.post("/api/assistant/tasks/99/messages", json={"text": "hi"}).status_code == 404
    assert client.post("/api/assistant/profile", json={"topic": "travel", "label": "Seat", "value": "Aisle",
                                                       "extra": 1}).status_code == 200
    assert client.post("/api/assistant/profile", json={"topic": "moon", "label": "Seat",
                                                       "value": "Aisle"}).status_code == 422


def test_from_another_site_is_refused(client):
    r = client.post("/api/assistant/tasks", json={"request": "Book everything"},
                    headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403


def test_profile_through_the_api(client):
    view = client.get("/api/assistant/profile").json()
    assert view["facts"] == [] and view["suggestions"] == []
    assert {"topic": "ids", "label": "Passport number", "example": "", "secret": True} in view["prompts"]

    made = client.post("/api/assistant/profile", json={"topic": "ids", "label": "Passport number",
                                                       "value": "Z1234567", "secret": True}).json()
    (fact,) = client.get("/api/assistant/profile").json()["facts"]
    assert fact == {"id": made["fact_id"], "topic": "ids", "label": "Passport number", "value": "", "secret": True,
                    "updated_at": fact["updated_at"]}
    assert "Z1234567" not in client.get("/api/assistant/profile").text

    seat = client.post("/api/assistant/profile", json={"topic": "travel", "label": "Seat", "value": "Aisle"}).json()
    edit = client.patch(f"/api/assistant/profile/{seat['fact_id']}", json={"value": "Window"}).json()
    client.post(f"/api/undo/{edit['change_id']}")
    values = {f["label"]: f["value"] for f in client.get("/api/assistant/profile").json()["facts"]}
    assert values["Seat"] == "Aisle"
    gone = client.delete(f"/api/assistant/profile/{seat['fact_id']}").json()
    assert len(client.get("/api/assistant/profile").json()["facts"]) == 1
    client.post(f"/api/undo/{gone['change_id']}")
    assert len(client.get("/api/assistant/profile").json()["facts"]) == 2
    assert client.patch("/api/assistant/profile/999", json={"value": "x"}).status_code == 404


def test_suggestions_through_the_api(client, conn):
    task_id = conn.execute("INSERT INTO assistant_tasks (request, created_at, updated_at) VALUES ('x', 'now', 'now')"
                           ).lastrowid
    profile.suggest(conn, task_id, [{"topic": "travel", "label": "Seat", "value": "Aisle", "why": "asked"}])
    assert client.get("/api/assistant/tasks").json()["suggestions"] == 1
    (s,) = client.get("/api/assistant/profile").json()["suggestions"]
    added = client.post(f"/api/assistant/suggestions/{s['id']}/accept").json()
    assert added["fact_id"] and added["change_id"]
    assert client.post(f"/api/assistant/suggestions/{s['id']}/accept").status_code == 400
    assert client.post("/api/assistant/suggestions/99/dismiss").status_code == 404


def test_api_topics_match_the_profile():
    assert typing.get_args(api.Topic) == profile.TOPICS
    assert typing.get_args(api.AssistantAction.model_fields["kind"].annotation) == actions.KINDS
