"""Backups in iCloud Drive: an encrypted copy of the catalog, photos and code, checked against its manifest,
pruned to 14 and one a month, and a notification when a copy or check fails. The disk image is faked (a tar
that opens only with the right key); hdiutil itself is tried on the Mac after a deploy."""

import hashlib
import json
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

from hobbes import config, db, jobs, maintenance, offsite, push, secrets

from .test_push import APPLE, Device, b64


@pytest.fixture
def icloud(tmp_path, monkeypatch):
    dest = tmp_path / "iCloud" / "Hobbes at Home Backups"
    monkeypatch.setenv("HOBBES_OFFSITE", str(dest))
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (repo / "README").write_text("the dashboard")
    subprocess.run([*git, "add", "README"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "first"], check=True)
    monkeypatch.setattr(offsite, "REPO", repo)

    def make_image(src, path, key, volname):
        with tarfile.open(path, "w:gz") as t:
            t.add(src, arcname=".")
            lock = Path(tempfile.mkdtemp(dir=tmp_path)) / ".key"
            lock.write_text(hashlib.sha256(key.encode()).hexdigest())
            t.add(lock, arcname=".key")

    @contextmanager
    def open_image(path, key):
        out = Path(tempfile.mkdtemp(dir=tmp_path))
        with tarfile.open(path) as t:
            t.extractall(out, filter="data")
        if (out / ".key").read_text() != hashlib.sha256(key.encode()).hexdigest():
            raise offsite.BackupError("The copy couldn't be opened with the recovery key: Authentication error")
        yield out

    monkeypatch.setattr(offsite, "make_image", make_image)
    monkeypatch.setattr(offsite, "open_image", open_image)
    return dest


def test_a_copy_has_everything_and_checks_out(conn, icloud):
    db.set_setting(conn, "diet.target", "2000")
    photo = config.home() / "uploads" / "people" / "1" / "face.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"\xff\xd8 a face")
    out = offsite.run(conn, copy=True, verify=True)
    assert "error" not in out and "check_error" not in out, out
    (made,) = offsite.copies()
    assert made.name == out["made"] and offsite.NAME.match(made.name)
    assert (icloud / "How to restore.txt").read_text().startswith("Hobbes at Home backups")

    with offsite.open_image(made, offsite.recovery_key()) as root:
        manifest = json.loads((root / "manifest.json").read_text())
        inside = {"catalog.db", "uploads/people/1/face.jpg", "code.bundle", "How to restore.txt"}
        assert inside <= set(manifest["files"])
        assert manifest["tables"]["settings"] >= 1 and manifest["schema"] == db.connect().execute(
            "PRAGMA user_version").fetchone()[0]
        assert manifest["note"] is None  # the code is in it
        assert (root / "uploads/people/1/face.jpg").read_bytes() == b"\xff\xd8 a face"

    st = offsite.status(conn)
    assert st["copies"] == 1 and st["last_name"] == made.name and st["check_ok"] is True and st["last_error"] is None
    assert st["checked_name"] == made.name and st["last_size"] > 0


def test_the_key_is_kept_in_the_keychain_and_needed(conn, icloud):
    key = offsite.recovery_key()
    assert key == offsite.recovery_key() and len(key) == 29 and key.count("-") == 5
    assert set(key.replace("-", "")) <= set(offsite.ALPHABET)
    assert secrets.get(offsite.KEY_NAME) == key
    assert key not in json.dumps([list(r) for r in conn.execute("SELECT * FROM settings")])
    offsite.run(conn, copy=True, verify=False)
    secrets.put(offsite.KEY_NAME, "WRONG-KEY")
    out = offsite.run(conn, copy=False, verify=True)
    assert "recovery key" in out["check_error"] and offsite.status(conn)["check_ok"] is False


def test_a_damaged_copy_is_caught(conn, icloud, monkeypatch):
    offsite.run(conn, copy=True, verify=False)
    opened = offsite.open_image

    @contextmanager
    def damaged(path, key):
        with opened(path, key) as root:
            (root / "How to restore.txt").write_text("changed")
            yield root

    monkeypatch.setattr(offsite, "open_image", damaged)
    out = offsite.run(conn, copy=False, verify=True)
    assert out["check_error"] == "How to restore.txt in the copy doesn't match what was saved."


def test_failures_are_told_once_a_day(conn, icloud, monkeypatch):
    d = Device()
    push.add_device(conn, APPLE, b64(d.public), b64(d.auth), "iPhone")

    def blocked(*a, **k):
        raise offsite.BackupError("The dashboard can't write to iCloud Drive (Operation not permitted).")

    monkeypatch.setattr(offsite, "make", blocked)
    for _ in range(2):
        out = offsite.run(conn, copy=True, verify=True)
    assert out == {"error": "The dashboard can't write to iCloud Drive (Operation not permitted)."}
    sent = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM jobs WHERE kind = 'push.send'")]
    assert len(sent) == 1 and sent[0]["kind"] == "backups" and sent[0]["title"] == "Backup to iCloud failed"
    assert sent[0]["url"] == "/settings/backups"
    assert offsite.status(conn)["last_error"].startswith("The dashboard can't write")

    # The copy on this Mac failing is told too.
    monkeypatch.setattr(maintenance, "backup_now", lambda conn: (_ for _ in ()).throw(OSError("No space left")))
    with pytest.raises(OSError):
        maintenance.backup_job(conn, {})
    assert json.loads(conn.execute("SELECT payload FROM jobs WHERE kind = 'push.send' ORDER BY id DESC"
                                   ).fetchone()[0])["title"] == "Backup on this Mac failed"


def test_keeps_fourteen_and_one_a_month(icloud):
    icloud.mkdir(parents=True)
    names = [f"Hobbes at Home 2026-{m:02d}-{d:02d} 0110.dmg" for m in (8, 9, 10) for d in range(1, 29, 3)]
    for n in names:
        (icloud / n).write_bytes(b"x")
    (icloud / "notes.txt").write_text("mine")
    (icloud / "Hobbes at Home old.dmg").write_bytes(b"x")
    removed = offsite.prune()
    kept = sorted(p.name for p in icloud.iterdir())
    assert names[-14:] == [n for n in kept if n in names][-14:]
    assert "Hobbes at Home 2026-08-01 0110.dmg" in kept and "Hobbes at Home 2026-09-01 0110.dmg" in kept
    assert "Hobbes at Home 2026-08-04 0110.dmg" in removed
    assert "notes.txt" in kept and "Hobbes at Home old.dmg" in kept  # only copies named as ours are touched
    assert len(removed) == len(names) - 14 - 2


def test_when_copies_and_checks_are_due(conn, icloud):
    night = datetime(2026, 10, 19, 0, 30).astimezone()
    morning = datetime(2026, 10, 19, 1, 10).astimezone()
    assert offsite.due(conn, night) == (False, True)   # not before 1:00; never checked
    assert offsite.due(conn, morning) == (True, True)
    offsite._put(conn, last_ok_at=morning.isoformat(), checked_at=morning.isoformat(), check_ok=True)
    assert offsite.due(conn, morning.replace(hour=15)) == (False, False)
    assert offsite.due(conn, datetime(2026, 10, 20, 1, 5).astimezone()) == (True, False)
    assert offsite.due(conn, datetime(2026, 10, 26, 2, 0).astimezone()) == (True, True)  # a week on


def test_backups_through_the_api(client, conn, icloud):
    s = client.get("/api/backups").json()
    assert s["offsite"]["copies"] == 0 and s["offsite"]["key_saved_at"] is None and not s["running"]
    assert s["offsite"]["enabled"] is False  # off until turned on: the first use makes macOS ask
    assert client.post("/api/backups/run", json={"what": "copy"}).status_code == 409
    assert offsite.backup_job(conn, {}) == {}
    assert client.put("/api/backups/icloud", json={"enabled": True}).json()["running"]  # the first copy, now
    assert jobs.run_one(conn)
    key = client.get("/api/backups/key").json()["key"]
    assert key == offsite.recovery_key()
    assert client.post("/api/backups/key/saved").json()["offsite"]["key_saved_at"]
    job_id = client.post("/api/backups/run", json={"what": "copy"}).json()["job_id"]
    assert client.get("/api/backups").json()["running"]
    assert jobs.run_one(conn)
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "done"
    s = client.get("/api/backups").json()["offsite"]
    assert s["copies"] == 1 and s["check_ok"] is True  # the same minute: the same copy, made again
    assert client.post("/api/backups/run", json={"what": "delete"}).status_code == 422


def test_tests_never_reach_icloud_or_make_images(conn, monkeypatch):
    monkeypatch.delenv("HOBBES_OFFSITE")
    with pytest.raises(offsite.BackupError, match="Offline"):
        offsite.folder()
    assert offsite.run(conn, copy=True, verify=True) == {"error": "Offline: backups don't go to iCloud Drive."}
    with pytest.raises(offsite.BackupError, match="Offline"):
        offsite.make_image(Path("."), Path("x.dmg"), "key", "x")
    assert offsite.status(conn)["folder"] == "iCloud Drive › Hobbes at Home Backups"


def test_while_macos_is_asking_nothing_waits(conn, icloud, monkeypatch):
    """macOS holds a call to iCloud Drive while it asks the owner; only a child process waits on it."""
    monkeypatch.setattr(offsite, "PROBE_CODE", "import time; time.sleep(60)")
    monkeypatch.setattr(offsite, "PROBE_WAIT", 0.2)
    monkeypatch.setattr(offsite, "_PROBE", None)
    started = datetime.now()
    with pytest.raises(offsite.BackupError, match="macOS is asking"):
        offsite.reachable()
    probe = offsite._PROBE
    assert probe is not None and probe.poll() is None  # still waiting, so the question stays on screen
    out = offsite.run(conn, copy=True, verify=True)
    assert out == {"error": offsite.ASKING} and offsite._PROBE is probe  # asked about again, not started again
    assert (datetime.now() - started).total_seconds() < 25
    assert offsite.status(conn)["last_error"] == offsite.ASKING
    probe.kill()

    monkeypatch.setattr(offsite, "PROBE_CODE", "raise PermissionError('Operation not permitted')")
    monkeypatch.setattr(offsite, "_PROBE", None)
    with pytest.raises(offsite.BackupError, match="didn't let the dashboard use .*Operation not permitted"):
        offsite.reachable()
