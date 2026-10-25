"""Coding sessions (under /api/sessions): the owner's Claude Code and Codex sessions on this Mac and their
state. Read only; there is deliberately no way to send a session anything. See sessions.py."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import sessions
from .web.deps import Conn

router = APIRouter()


class CodingSession(BaseModel):
    id: int
    tool: Literal["claude", "codex"]
    session_id: str
    name: str
    cwd: str
    kind: str = Field(description="claude: interactive or background; codex: where it was started (cli, vscode, …)")
    state: Literal["working", "waiting", "idle", "error", "ended"]
    waiting_for: str | None
    open_with: str | None = Field(description="What to type at the Mac to open it, when there's a command for it.")
    started_at: str | None
    state_since: str
    ended_at: str | None


class CodingTool(BaseModel):
    tool: Literal["claude", "codex"]
    label: str
    available: bool
    error: str | None
    checked_at: str | None


class CodingSessions(BaseModel):
    tools: list[CodingTool]
    sessions: list[CodingSession]


@router.get("/api/sessions", response_model=CodingSessions)
def get_sessions(conn: Conn) -> Any:
    """Live sessions first (waiting for the owner, then working, then idle), then those ended today."""
    sessions.check(conn)
    return sessions.listing(conn)
