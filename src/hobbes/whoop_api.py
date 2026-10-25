"""The WHOOP API (under /api/whoop): set up, sign in, sync, disconnect."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import jobs, whoop
from .web.deps import Conn

router = APIRouter()


class WhoopProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class WhoopStatus(BaseModel):
    share_with_ai: bool = Field(description="The owner chose to let the AI see WHOOP data (off by default).")
    configured: bool
    connected: bool
    client_id: str | None
    redirect_uri: str | None
    profile: WhoopProfile | None
    last_sync_at: str | None
    last_error: str | None


class WhoopShare(BaseModel):
    share_with_ai: bool


class WhoopSetup(BaseModel):
    client_id: str
    client_secret: str | None = None
    redirect_uri: str


class SignIn(BaseModel):
    auth_url: str


class JobId(BaseModel):
    job_id: int


@router.get("/api/whoop/status", response_model=WhoopStatus)
def get_status(conn: Conn) -> Any:
    return whoop.status(conn)


@router.put("/api/whoop/share", response_model=WhoopStatus)
def put_share(conn: Conn, body: WhoopShare) -> Any:
    """Let the AI see WHOOP data (Hobbes AI's view of your day, the Health page's advice), or not."""
    whoop.set_shared_with_ai(conn, body.share_with_ai)
    return whoop.status(conn)


@router.post("/api/whoop/setup", response_model=SignIn)
def setup(conn: Conn, body: WhoopSetup) -> Any:
    """Save the WHOOP app's keys (the secret goes to the Keychain) and return where to sign in."""
    try:
        whoop.configure(conn, body.client_id, body.client_secret, body.redirect_uri)
        return {"auth_url": whoop.start(conn)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/whoop/callback", include_in_schema=False)
def callback(request: Request, conn: Conn, code: str = "", state: str = "", error: str = "",
             error_description: str = "") -> RedirectResponse:
    """WHOOP sends the browser here after sign-in; the answer is shown on the WHOOP settings page."""
    def back(**q: str) -> RedirectResponse:
        return RedirectResponse("/settings/whoop?" + urllib.parse.urlencode(q), 303)

    if error or not code:
        return back(error=error_description or error or "WHOOP didn't sign in.")
    try:
        whoop.finish(conn, code, state)
    except whoop.WhoopError as e:
        return back(error=str(e))
    jobs.enqueue(conn, "whoop.sync", {"full": True}, max_attempts=3)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()
    return back(connected="1")


@router.post("/api/whoop/sync", response_model=JobId)
def sync_now(request: Request, conn: Conn) -> Any:
    if not whoop.status(conn)["connected"]:
        raise HTTPException(400, "WHOOP isn't connected.")
    job_id = jobs.enqueue(conn, "whoop.sync", max_attempts=1)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()
    return {"job_id": job_id}


@router.post("/api/whoop/disconnect", response_model=WhoopStatus)
def disconnect(conn: Conn) -> Any:
    whoop.disconnect(conn)
    return whoop.status(conn)
