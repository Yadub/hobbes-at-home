"""Housekeeping jobs: the catalog backup on this Mac (every 6 hours; the copy away from it is offsite.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from . import config, db, jobs, offsite


def backup_now(conn, tag: str | None = None) -> Path | None:
    """Copy the catalog to backups/. One per day (or per tag); an existing backup is never replaced.
    Old backups aren't removed: the catalog is small, and keeping them is the safe default."""
    name = f"catalog-{tag}.db" if tag else f"catalog-{date.today().isoformat()}.db"
    dest = config.backup_dir() / name
    if dest.exists():
        return None
    config.backup_dir().mkdir(parents=True, exist_ok=True)
    config.backup_dir().chmod(0o700)
    return db.backup(conn, dest)


def last_backup_at() -> str | None:
    """When the most recent backup was made (ISO time), or None."""
    found = [p.stat().st_mtime for p in config.backup_dir().glob("catalog-*.db")] \
        if config.backup_dir().exists() else []
    return datetime.fromtimestamp(max(found), UTC).isoformat(timespec="seconds") if found else None


@jobs.handler("backup", every=6 * 3600)
def backup_job(conn, payload: dict) -> dict:
    try:
        made = backup_now(conn)
    except Exception as e:
        offsite.tell(conn, "on this Mac", str(e) or type(e).__name__)
        raise
    return {"made": made.name if made else None}
