"""Every test runs against a scratch data folder, in-memory secrets, no Tailscale and a fake Codex,
so nothing here can touch the real catalog, the Keychain or the Codex allowance."""

import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hobbes import ai, db, region, secrets
from hobbes.web.app import create_app

FAKE_CODEX = Path(__file__).parent / "fake_codex.py"
FAKE_CLAUDE = Path(__file__).parent / "fake_claude.py"
OWNER = "owner@example.com"


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("HOBBES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOBBES_SECRETS", "memory")
    monkeypatch.setenv("HOBBES_OFFLINE", "1")
    monkeypatch.setenv("HOBBES_OFFSITE", str(tmp_path / "offsite"))  # never the real iCloud Drive
    monkeypatch.setenv("HOBBES_CODEX", str(FAKE_CODEX))
    monkeypatch.setenv("HOBBES_CLAUDE", str(FAKE_CLAUDE))
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "codex.log"))
    monkeypatch.delenv("HOBBES_CODEX_MODEL", raising=False)
    monkeypatch.delenv("HOBBES_CLAUDE_MODEL", raising=False)
    for fake in (FAKE_CODEX, FAKE_CLAUDE):
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(region, "mac_country", lambda: None)  # the default region, not this Mac's
    ai._STATUS_CACHE.clear()
    ai._USAGE_CACHE.clear()
    secrets._MEMORY.clear()
    return tmp_path


@pytest.fixture
def conn(scratch):
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def app():
    return create_app(owner=OWNER, tailnet_name="my-mac.tail1234.ts.net", run_jobs=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def codex_calls(scratch) -> list[dict]:
    import json

    log = scratch / "codex.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

