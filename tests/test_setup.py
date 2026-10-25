"""`hobbes setup`: the AI and the region, asked or given as options."""

import argparse

import pytest

from hobbes import ai, cli, db, region, setup


def args(**kw):
    base = {"ai": None, "country": None, "cuisine": None, "currency": None, "port": 8799, "service": False,
            "tailscale": False, "yes": False}
    return argparse.Namespace(**{**base, **kw})


def run(a, answers):
    said = []
    replies = iter(answers)
    setup.run(a, ask=lambda q: next(replies), say=said.append)
    return said


def test_asks_which_ai_when_both_are_signed_in_and_the_region(conn, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    said = run(args(), ["1", "n", "IN", "", ""])
    assert ai.provider(conn) == "claude"
    assert region.get(conn)["currency"] == "INR" and region.get(conn)["chosen"]
    assert any("Not started" in s for s in said)


def test_options_and_a_bad_country(conn, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    run(args(ai="codex", country="GB", cuisine="Mostly Italian", yes=True), [])
    assert ai.provider(conn) == "codex" and region.fill("{eats}", conn) == "They mostly eat Mostly Italian."
    with pytest.raises(RuntimeError, match="two-letter"):
        run(args(country="Britain", yes=True), [])


def test_no_ai_yet(conn, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setenv("HOBBES_CODEX", "")
    monkeypatch.setenv("HOBBES_CLAUDE", "")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(ai, "_PATH_EXTRA", [])
    said = run(args(yes=True), [])
    assert any("Neither AI is ready yet" in s for s in said)
    assert db.get_setting(conn, ai.SETTING) is None


def test_the_command_is_wired(monkeypatch):
    seen = {}
    monkeypatch.setattr(setup, "run", lambda a: seen.update(vars(a)))
    cli.main(["setup", "--ai", "claude", "--country", "US", "--yes", "--no-service"])
    assert seen["ai"] == "claude" and seen["service"] is False and seen["yes"] is True
