import json
import os

import pytest

from hobbes import ai, config, db, jobs, maintenance, secrets

from .conftest import codex_calls


def test_catalog_is_created_private_and_migrated(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert oct(config.home().stat().st_mode & 0o777) == "0o700"
    assert oct(config.db_path().stat().st_mode & 0o777) == "0o600"
    assert db.migrate(conn) == len(db.MIGRATIONS)  # again: nothing to do


def test_newer_catalog_is_refused(conn):
    conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer version"):
        db.migrate(conn)


def test_write_lock_rolls_back(conn):
    with pytest.raises(ValueError), db.write_lock(conn):
        db.set_setting(conn, "a", "1")
        raise ValueError
    assert db.get_setting(conn, "a") is None


def test_backup_never_overwrites(conn):
    first = maintenance.backup_now(conn)
    assert first and first.exists()
    assert maintenance.backup_now(conn) is None  # one per day
    assert maintenance.last_backup_at() is not None
    with pytest.raises(FileExistsError):
        db.backup(conn, first)


def test_job_runs_and_records_result(conn):
    @jobs.handler("test.add")
    def add(_conn, payload):
        return {"sum": payload["a"] + payload["b"]}

    job_id = jobs.enqueue(conn, "test.add", {"a": 2, "b": 3})
    assert jobs.run_one(conn)
    j = jobs.get(conn, job_id)
    assert j and j["status"] == "done" and j["result"] == {"sum": 5}
    assert not jobs.run_one(conn)  # nothing left


def test_failed_job_retries_later_then_fails(conn):
    @jobs.handler("test.broken")
    def broken(_conn, payload):
        raise RuntimeError("no luck")

    job_id = jobs.enqueue(conn, "test.broken", max_attempts=2)
    assert jobs.run_one(conn)
    j = jobs.get(conn, job_id)
    assert j and j["status"] == "queued" and j["error"] == "no luck" and j["run_after"] > db.now()
    assert not jobs.run_one(conn)  # not due yet
    conn.execute("UPDATE jobs SET run_after = ? WHERE id = ?", (db.now(), job_id))
    assert jobs.run_one(conn)
    j = jobs.get(conn, job_id)
    assert j and j["status"] == "failed" and j["attempts"] == 2


def test_unknown_kind_fails_at_once(conn):
    job_id = jobs.enqueue(conn, "test.nobody")
    jobs.run_one(conn)
    j = jobs.get(conn, job_id)
    assert j and j["status"] == "failed" and "Nothing runs" in j["error"]


def test_interrupted_jobs_run_again(conn):
    job_id = jobs.enqueue(conn, "backup")
    conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    assert jobs.recover(conn) == 1
    j = jobs.get(conn, job_id)
    assert j and j["status"] == "queued"


def test_periodic_jobs_are_queued_once(conn):
    first = jobs.schedule_due(conn)
    kinds = {jobs.get(conn, i)["kind"] for i in first}  # type: ignore[index]
    assert "backup" in kinds
    assert jobs.schedule_due(conn) == []  # already waiting
    while jobs.run_one(conn):
        pass
    assert jobs.schedule_due(conn) == []  # ran just now


def test_ask_with_schema_and_images(scratch, conn, tmp_path):
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    answer = ai.ask("What's this?", schema=ai.CHECK_SCHEMA, images=[photo], kind="test", conn=conn)
    assert answer == {"ok": True, "reply": "hello"}
    (call,) = codex_calls(scratch)
    args = call["args"]
    assert args[0] == "exec" and "--ephemeral" in args and "--ignore-user-config" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert f"--image={photo.resolve()}" in args
    assert 'web_search="live"' not in args
    off = {args[i + 1] for i, a in enumerate(args) if a == "--config" and args[i + 1].startswith("features.")}
    assert {f"features.{f}=false" for f in ("apps", "plugins", "browser_use", "computer_use", "multi_agent")} <= off
    assert call["prompt"] == "What's this?"
    assert call["cwd"].startswith(str(config.scratch_dir().resolve())) or "/ai-" in call["cwd"]
    assert not any(config.scratch_dir().iterdir())  # the run's folder is cleaned up
    run = conn.execute("SELECT * FROM ai_runs").fetchone()
    assert run["ok"] == 1 and run["images"] == 1 and run["kind"] == "test"


def test_ask_text_and_search(scratch, conn, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", "Just text.")
    assert ai.ask("hi", search=True, conn=conn) == "Just text."
    args = codex_calls(scratch)[0]["args"]
    assert args[args.index('web_search="live"') - 1] == "--config"


def test_ask_failures_are_plain_and_recorded(conn, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    with pytest.raises(ai.AIError, match="something went wrong"):
        ai.ask("hi", conn=conn)
    monkeypatch.delenv("FAKE_CODEX_FAIL")
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"ok": "yes"}))
    with pytest.raises(ai.AIError, match="shape"):
        ai.ask("hi", schema=ai.CHECK_SCHEMA, conn=conn)
    assert [r["ok"] for r in conn.execute("SELECT ok FROM ai_runs")] == [0, 0]


def test_ask_without_codex(conn, monkeypatch):
    monkeypatch.setenv("HOBBES_CODEX", "")
    monkeypatch.setenv("HOBBES_CLAUDE", "")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(ai, "_PATH_EXTRA", [])
    with pytest.raises(ai.AIError, match="isn't installed"):
        ai.ask("hi", conn=conn)


def test_check_shape():
    schema = {"type": "object", "required": ["n", "items"], "properties": {
        "n": {"type": "integer"}, "items": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}}}}
    assert ai.check_shape({"n": 1, "items": ["a"]}, schema) is None
    assert ai.check_shape({"n": True, "items": []}, schema) == "answer.n should be integer"
    assert ai.check_shape({"n": 1, "items": ["c"]}, schema) == "answer.items[0] should be one of ['a', 'b']"
    assert ai.check_shape({"n": 1}, schema) == "answer is missing 'items'"


def test_codex_status(monkeypatch):
    s = ai.status(refresh=True)
    assert s == {"provider": "codex", "name": "ChatGPT", "tool": "Codex", "installed": True, "version": "9.9.9",
                 "signed_in": True, "plan": None, "detail": "Logged in using ChatGPT"}


def test_claude_status_and_the_default(conn, monkeypatch):
    s = ai.provider_status("claude", refresh=True)
    assert (s["version"], s["signed_in"], s["plan"]) == ("9.9.9", True, "pro")
    monkeypatch.setenv("HOBBES_CODEX", "")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(ai, "_PATH_EXTRA", [])
    assert ai.provider(conn) == "claude"  # not chosen yet: whichever is installed
    ai.set_provider(conn, "codex")
    assert ai.provider(conn) == "codex"  # chosen, even if it's missing (calls then say how to install it)


def test_ask_claude_locked_down(conn, scratch, monkeypatch, tmp_path):
    ai.set_provider(conn, "claude")
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"\xff\xd8 not really a jpeg")
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps({"ok": True, "reply": "hi"}))
    assert ai.ask("Look", schema=ai.CHECK_SCHEMA, images=[photo], search=True, conn=conn) == {"ok": True, "reply": "hi"}
    (call,) = codex_calls(scratch)
    args = call["args"]
    assert call["tool"] == "claude" and call["images"] == 1 and call["prompt"] == "Look"
    for flag in ("--restricted", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                 "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--tools") + 1] == "WebSearch,WebFetch"
    assert args[args.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert call["cwd"].startswith(str(config.scratch_dir()))

    assert ai.ask("Plain", conn=conn) == json.dumps({"ok": True, "reply": "hi"})  # text, without a schema
    args = codex_calls(scratch)[1]["args"]
    assert args[args.index("--tools") + 1] == "" and "--allowedTools" not in args and "--json-schema" not in args

    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    with pytest.raises(ai.AIError, match="Claude Code failed: something went wrong"):
        ai.ask("x", conn=conn)


def test_secrets_in_memory():
    assert os.environ["HOBBES_SECRETS"] == "memory"
    secrets.put("whoop", "token")
    assert secrets.get("whoop") == "token"
    secrets.forget("whoop")
    secrets.forget("whoop")  # missing is fine
    assert secrets.get("whoop") is None


def test_ask_refuses_a_codex_that_has_lost_a_switch(scratch, conn, monkeypatch):
    """A Codex that no longer knows "apps" can't be told to keep the connected apps (Gmail...) out: refuse."""
    monkeypatch.setattr(ai, "_FEATURES_CHECKED", {})
    monkeypatch.setenv("FAKE_CODEX_FEATURES", "plugins,remote_plugin,multi_agent,image_generation,goals,"
                       "browser_use,computer_use,in_app_browser")
    with pytest.raises(ai.AIError, match="doesn't have the switch apps"):
        ai.ask("hello", kind="test", conn=conn)
    assert codex_calls(scratch) == []  # never run
