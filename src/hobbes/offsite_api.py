"""Backups (under /api/backups): the copies on this Mac and in iCloud Drive, the recovery key, and Back Up Now
or Check Now. See maintenance.py and offsite.py."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, jobs, maintenance, offsite
from .web.deps import Conn

router = APIRouter()


class LocalBackups(BaseModel):
    last_at: str | None
    copies: int


class OffsiteBackups(BaseModel):
    enabled: bool = Field(description="The owner turned on daily copies in iCloud Drive (off by default).")
    folder: str
    copies: int
    last_ok_at: str | None
    last_name: str | None
    last_size: int | None
    last_note: str | None
    last_error: str | None
    last_tried_at: str | None
    checked_at: str | None
    check_ok: bool | None
    check_error: str | None
    checked_name: str | None
    key_saved_at: str | None
    includes: list[str]
    excludes: list[str]


class Backups(BaseModel):
    local: LocalBackups
    offsite: OffsiteBackups
    running: bool


class RecoveryKey(BaseModel):
    key: str


class ICloudIn(BaseModel):
    enabled: bool


class BackupRunIn(BaseModel):
    what: Literal["copy", "check"]


class BackupRun(BaseModel):
    job_id: int


def _state(conn: Conn) -> dict:
    local = config.backup_dir()
    running = conn.execute("SELECT 1 FROM jobs WHERE kind = 'offsite.backup' AND status IN ('queued', 'running')"
                           ).fetchone() is not None
    return {"local": {"last_at": maintenance.last_backup_at(),
                      "copies": len(list(local.glob("catalog-*.db"))) if local.exists() else 0},
            "offsite": offsite.status(conn), "running": running}


@router.get("/api/backups", response_model=Backups)
def get_backups(conn: Conn) -> Any:
    return _state(conn)


@router.get("/api/backups/key", response_model=RecoveryKey)
def get_key() -> Any:
    """The recovery key the iCloud copies are encrypted with, to save in Passwords."""
    return {"key": offsite.recovery_key()}


@router.post("/api/backups/key/saved", response_model=Backups)
def key_saved(conn: Conn) -> Any:
    offsite.key_saved(conn)
    return _state(conn)


@router.put("/api/backups/icloud", response_model=Backups)
def put_icloud(request: Request, conn: Conn, body: ICloudIn) -> Any:
    """Daily encrypted copies in iCloud Drive, on or off. Turning them on makes the first copy now (macOS asks
    once whether Hobbes at Home may use iCloud Drive)."""
    offsite.set_enabled(conn, body.enabled)
    if body.enabled:
        jobs.enqueue(conn, "offsite.backup", {"copy": True, "check": True}, max_attempts=1)
        worker = getattr(request.app.state, "worker", None)
        if worker:
            worker.wake()
    return _state(conn)


@router.post("/api/backups/run", response_model=BackupRun)
def run(request: Request, conn: Conn, body: BackupRunIn) -> Any:
    """Back Up Now (a copy, then a check) or Check Now (the newest copy)."""
    if not offsite.enabled(conn):
        raise HTTPException(409, "Turn on iCloud backups first.")
    payload = {"copy": True, "check": True} if body.what == "copy" else {"copy": False, "check": True}
    job_id = jobs.enqueue(conn, "offsite.backup", payload, max_attempts=1)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()
    return {"job_id": job_id}
