"""The assistant's API (under /api/assistant): tasks, watches on them, ideas for new ones, the owner's
profile, and suggestions for it.
Removals and profile edits are undone through /api/undo/{change_id}, like the rest of the dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, jobs
from ..web.deps import Conn
from . import ideas, profile, tasks, watches
from . import runner as _runner  # noqa: F401 (registers the job that runs each round)

router = APIRouter()

Status = Literal["working", "needs_you", "done", "failed", "cancelled"]
Topic = Literal["travel", "stays", "budget", "payments", "bookings", "food", "people", "ids", "other"]


def _call[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


def _wake(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()


# ---------------------------------------------------------------- shapes

class AssistantQuestion(BaseModel):
    text: str
    why: str
    choices: list[str]


class AssistantOption(BaseModel):
    title: str
    price: str | None
    when: str | None
    source: str | None
    link: str | None
    why: str


class AssistantAction(BaseModel):
    kind: Literal["book", "buy", "hold", "remind", "send", "fill_form", "other"]
    label: str
    option: int | None
    link: str | None
    status: Literal["proposed"]


class AssistantResult(BaseModel):
    summary: str
    options: list[AssistantOption]
    recommended: int | None = Field(description="Index into options of the one it recommends.")
    recommendation: str
    assumptions: list[str]
    actions: list[AssistantAction] = Field(description="What it would do next; version 1 never does them.")


class AssistantStep(BaseModel):
    id: int
    at: str
    kind: Literal["asked", "answer", "refine", "retry", "started", "step", "result", "question", "failed", "stopped",
                  "watch", "changed", "unchanged"]
    text: str
    result: AssistantResult | None = Field(None, description="What a round came back with (kind result).")


class AssistantSuggestion(BaseModel):
    id: int
    task_id: int | None
    topic: Topic
    label: str
    value: str
    why: str
    replaces: str | None


class AssistantWatch(BaseModel):
    kind: Literal["watch", "routine"] = Field(description="Watch: looks again for changes. Routine: done afresh.")
    every: Literal["daily", "weekly", "monthly"]
    condition: str | None = Field(description="A watch's condition, in the owner's words: when to tell them.")
    when: str | None = Field(description="A routine's schedule, e.g. 'Thursdays, 05:00'.")
    next_at: str
    last_check_at: str | None
    last_change: str | None
    last_change_at: str | None
    unseen: bool = Field(description="A change, or a routine's results, the owner hasn't opened the job to see yet.")


class AssistantTaskSummary(BaseModel):
    id: int
    request: str
    title: str
    status: Status
    question: AssistantQuestion | None
    latest: str | None
    summary: str | None
    pick: str | None
    options: int
    error: str | None
    watch: AssistantWatch | None
    created_at: str
    updated_at: str
    finished_at: str | None


class AssistantTask(AssistantTaskSummary):
    result: AssistantResult | None
    turns: int
    steps: list[AssistantStep]
    suggestions: list[AssistantSuggestion]


class AssistantTasks(BaseModel):
    tasks: list[AssistantTaskSummary]
    suggestions: int


class AssistantFact(BaseModel):
    id: int
    topic: Topic
    label: str
    value: str = Field(description="Empty for a secret, whose value stays in the Keychain.")
    secret: bool
    updated_at: str


class AssistantFactPrompt(BaseModel):
    topic: Topic
    label: str
    example: str
    secret: bool


class AssistantProfile(BaseModel):
    facts: list[AssistantFact]
    prompts: list[AssistantFactPrompt]
    suggestions: list[AssistantSuggestion]


class AssistantIdea(BaseModel):
    id: str
    title: str
    request: str
    why: str
    kind: Literal["travel", "stays", "food", "gifts", "tickets", "admin", "money", "people", "other"]
    watch: Literal["", "daily", "weekly"]


class AssistantIdeas(BaseModel):
    ideas: list[AssistantIdea]
    at: str | None = Field(description="When these were thought of.")
    thinking: bool = Field(description="Fresh ones are being thought of now.")


class AssistantWatchIn(BaseModel):
    every: Literal["daily", "weekly"]


class AssistantRequestIn(BaseModel):
    request: str = Field(min_length=1, max_length=tasks.MAX_TEXT)


class AssistantMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=tasks.MAX_TEXT)


class AssistantFactIn(BaseModel):
    topic: Topic
    label: str = Field(min_length=1, max_length=profile.MAX_LABEL)
    value: str = Field(min_length=1, max_length=profile.MAX_VALUE)
    secret: bool = False


class AssistantFactEdit(BaseModel):
    topic: Topic | None = None
    label: str | None = Field(None, max_length=profile.MAX_LABEL)
    value: str | None = Field(None, max_length=profile.MAX_VALUE)


class AssistantChange(BaseModel):
    change_id: int | None
    fact_id: int | None = None


# ---------------------------------------------------------------- tasks

def _task(conn: Conn, task_id: int) -> dict:
    t = tasks.get(conn, task_id)
    if not t:
        raise HTTPException(404, "There's no such task.")
    return t


@router.get("/api/assistant/tasks", response_model=AssistantTasks)
def list_tasks(conn: Conn) -> Any:
    return {"tasks": tasks.listing(conn), "suggestions": len(profile.suggestions(conn))}


@router.post("/api/assistant/tasks", response_model=AssistantTask)
def new_task(request: Request, conn: Conn, body: AssistantRequestIn) -> Any:
    task_id = _call(tasks.create, conn, body.request)
    _wake(request)
    return _task(conn, task_id)


@router.get("/api/assistant/tasks/{task_id}", response_model=AssistantTask)
def get_task(conn: Conn, task_id: int) -> Any:
    return _task(conn, task_id)


@router.post("/api/assistant/tasks/{task_id}/messages", response_model=AssistantTask)
def send_message(request: Request, conn: Conn, task_id: int, body: AssistantMessageIn) -> Any:
    """Answer its question, or ask for a change. Sent while it's working, it's taken into account in
    the next round, which starts as soon as this one finishes."""
    _call(tasks.message, conn, task_id, body.text)
    _wake(request)
    return _task(conn, task_id)


@router.post("/api/assistant/tasks/{task_id}/retry", response_model=AssistantTask)
def retry_task(request: Request, conn: Conn, task_id: int) -> Any:
    _call(tasks.retry, conn, task_id)
    _wake(request)
    return _task(conn, task_id)


@router.post("/api/assistant/tasks/{task_id}/stop", response_model=AssistantTask)
def stop_task(conn: Conn, task_id: int) -> Any:
    _call(tasks.stop, conn, task_id)
    return _task(conn, task_id)


@router.delete("/api/assistant/tasks/{task_id}", response_model=AssistantChange)
def remove_task(conn: Conn, task_id: int) -> Any:
    return _call(tasks.remove, conn, task_id)


# ---------------------------------------------------------------- watches

@router.put("/api/assistant/tasks/{task_id}/watch", response_model=AssistantTask)
def watch_task(conn: Conn, task_id: int, body: AssistantWatchIn) -> Any:
    _call(watches.watch, conn, task_id, body.every)
    return _task(conn, task_id)


@router.delete("/api/assistant/tasks/{task_id}/watch", response_model=AssistantTask)
def unwatch_task(conn: Conn, task_id: int) -> Any:
    _call(watches.stop, conn, task_id)
    return _task(conn, task_id)


@router.post("/api/assistant/tasks/{task_id}/watch/check", response_model=AssistantTask)
def check_now(request: Request, conn: Conn, task_id: int) -> Any:
    """Look again (or run the routine) now, whatever the schedule."""
    _call(watches.look_now, conn, task_id)
    _wake(request)
    return _task(conn, task_id)


@router.post("/api/assistant/tasks/{task_id}/seen", response_model=AssistantTask)
def seen_task(conn: Conn, task_id: int) -> Any:
    """The owner has opened the job: its latest change has been seen."""
    watches.seen(conn, task_id)
    return _task(conn, task_id)


# ---------------------------------------------------------------- ideas

def _ideas(conn: Conn) -> dict:
    busy = conn.execute("SELECT 1 FROM jobs WHERE kind = ? AND (status = 'running' OR (status = 'queued' AND "
                        "run_after <= ?))", (ideas.KIND, db.now())).fetchone() is not None
    return {"ideas": ideas.shown(conn), "at": ideas.stored(conn).get("at"), "thinking": busy}


@router.get("/api/assistant/ideas", response_model=AssistantIdeas)
def list_ideas(conn: Conn) -> Any:
    return _ideas(conn)


@router.post("/api/assistant/ideas/refresh", response_model=AssistantIdeas)
def refresh_ideas(request: Request, conn: Conn) -> Any:
    """Think of fresh ideas now (unless that's already happening)."""
    if not _ideas(conn)["thinking"]:
        jobs.enqueue(conn, ideas.KIND, {"force": True}, max_attempts=1)
        _wake(request)
    return _ideas(conn)


@router.post("/api/assistant/ideas/{idea_id}/start", response_model=AssistantTask)
def start_idea(request: Request, conn: Conn, idea_id: str) -> Any:
    task_id = _call(ideas.start, conn, idea_id)
    _wake(request)
    return _task(conn, task_id)


@router.post("/api/assistant/ideas/{idea_id}/dismiss", response_model=AssistantIdeas)
def dismiss_idea(conn: Conn, idea_id: str) -> Any:
    _call(ideas.dismiss, conn, idea_id)
    return _ideas(conn)


# ---------------------------------------------------------------- profile and suggestions

@router.get("/api/assistant/profile", response_model=AssistantProfile)
def get_profile(conn: Conn) -> Any:
    return {"facts": profile.facts(conn), "prompts": profile.prompts(conn), "suggestions": profile.suggestions(conn)}


@router.post("/api/assistant/profile", response_model=AssistantChange)
def add_fact(conn: Conn, body: AssistantFactIn) -> Any:
    return _call(profile.add, conn, topic=body.topic, label=body.label, value=body.value, secret=body.secret)


@router.patch("/api/assistant/profile/{fact_id}", response_model=AssistantChange)
def edit_fact(conn: Conn, fact_id: int, body: AssistantFactEdit) -> Any:
    return _call(profile.edit, conn, fact_id, **body.model_dump(exclude_none=True))


@router.delete("/api/assistant/profile/{fact_id}", response_model=AssistantChange)
def remove_fact(conn: Conn, fact_id: int) -> Any:
    return _call(profile.remove, conn, fact_id)


@router.post("/api/assistant/suggestions/{suggestion_id}/accept", response_model=AssistantChange)
def accept_suggestion(conn: Conn, suggestion_id: int) -> Any:
    return _call(profile.accept, conn, suggestion_id)


@router.post("/api/assistant/suggestions/{suggestion_id}/dismiss", response_model=AssistantChange)
def dismiss_suggestion(conn: Conn, suggestion_id: int) -> Any:
    return _call(profile.dismiss, conn, suggestion_id)
