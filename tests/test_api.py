from hobbes import jobs
from hobbes.web import app as app_module


def test_status(client):
    s = client.get("/api/status").json()
    assert s["ai"]["provider"] == "codex" and s["ai"]["signed_in"] is True
    assert s["jobs"] == {"queued": 0, "running": 0, "done": 0, "failed": 0}
    assert s["https"] is False


def test_ai_check_job(client, conn):
    job_id = client.post("/api/ai/check", json={}).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    jobs.run_one(conn)
    j = client.get(f"/api/jobs/{job_id}").json()
    assert j["status"] == "done"
    assert j["result"]["ok"] is True and j["result"]["reply"] == "hello"
    assert client.get("/api/jobs").json()[0]["id"] == job_id
    assert client.get("/api/jobs/999").status_code == 404


def test_frontend_not_built(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "STATIC", tmp_path / "nothing")
    r = client.get("/")
    assert r.status_code == 503 and "npm --prefix web" in r.text


def test_frontend_routes_and_files(client, monkeypatch, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>x</title>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")
    monkeypatch.setattr(app_module, "STATIC", static)
    page = client.get("/diet")
    assert page.status_code == 200 and "<title>x</title>" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    js = client.get("/assets/app.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    escape = client.get("/..%2Fsecret.txt")
    assert escape.text != "no"  # never a file outside static/
    assert escape.status_code in (200, 404)
    # A missing file isn't answered with the page (browsers would keep it as the icon).
    assert client.get("/favicon.ico").status_code == 404
    assert client.get("/people/12").status_code == 200


def test_choosing_claude_or_chatgpt(client):
    c = client.get("/api/ai/providers").json()
    assert c["provider"] == "codex"
    assert [(p["provider"], p["name"], p["signed_in"]) for p in c["providers"]] == \
        [("claude", "Claude", True), ("codex", "ChatGPT", True)]
    assert client.put("/api/ai/provider", json={"provider": "claude"}).json()["provider"] == "claude"
    assert client.get("/api/status").json()["ai"]["name"] == "Claude"
    u = client.get("/api/ai/usage").json()
    assert u["available"] is False and u["plan"] == "pro"
    assert client.put("/api/ai/provider", json={"provider": "gemini"}).status_code == 422


def test_codex_usage(client):
    u = client.get("/api/ai/usage").json()
    assert u["available"] and u["plan"] == "plus"
    assert u["session"] == {"used_percent": 6.0, "window_minutes": 300, "resets_at": 1792241157}
    assert u["week"]["used_percent"] == 1.0 and u["week"]["window_minutes"] == 10080
