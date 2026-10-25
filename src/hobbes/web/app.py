"""The web app: the API under /api and the built frontend (web/, built into ./static) everywhere else."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .. import (
    __version__,
    ai,
    db,
    health_api,
    jobs,
    maintenance,
    offsite_api,
    push_api,
    region,
    sessions_api,
    whoop_api,
)
from ..assistant import api as assistant_api
from ..diet import api as diet_api
from . import access
from .deps import Conn

STATIC = Path(__file__).parent / "static"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
PUBLIC = ("/manifest.webmanifest", "/favicon.ico", "/apple-touch-icon.png")  # served without signing in
NOT_BUILT = ("The dashboard's pages haven't been built yet. On the Mac, run:\n\n"
             "    npm --prefix web ci && npm --prefix web run build\n")


# ---------------------------------------------------------------- API shapes

class Meta(BaseModel):
    name: str
    version: str
    build: str
    who: str | None
    tailnet_url: str | None


class AIStatus(BaseModel):
    provider: Literal["claude", "codex"]
    name: str = Field(description="What the owner knows it as: Claude or ChatGPT.")
    tool: str = Field(description="The program that runs it on the Mac: Claude Code or Codex.")
    installed: bool
    version: str | None
    signed_in: bool
    plan: str | None
    detail: str | None


class AIChoices(BaseModel):
    provider: Literal["claude", "codex"]
    providers: list[AIStatus]


class AIChoiceIn(BaseModel):
    provider: Literal["claude", "codex"]


class JobCounts(BaseModel):
    queued: int
    running: int
    done: int
    failed: int


class UsageWindow(BaseModel):
    used_percent: float
    window_minutes: int | None
    resets_at: int | None


class AIUsage(BaseModel):
    available: bool
    plan: str | None
    session: UsageWindow | None
    week: UsageWindow | None
    detail: str | None


class Country(BaseModel):
    code: str
    name: str


class Region(BaseModel):
    country_code: str
    country: str
    currency: str
    symbol: str
    cuisine: str
    chosen: bool = Field(description="False until the owner chooses; the Mac's region is used meanwhile.")
    countries: list[Country]


class RegionIn(BaseModel):
    country: str = Field(min_length=2, max_length=2, description="Two-letter country code.")
    cuisine: str = Field("", max_length=200, description="What they mostly eat, in their words; empty for the usual.")
    currency: str = Field("", max_length=3, description="ISO currency code; empty for the country's.")


class Status(BaseModel):
    ai: AIStatus
    jobs: JobCounts
    last_backup_at: str | None
    https: bool


class Job(BaseModel):
    id: int
    kind: str
    status: str
    result: dict | None
    error: str | None
    attempts: int
    created_at: str
    started_at: str | None
    finished_at: str | None


class Queued(BaseModel):
    job_id: int


# ---------------------------------------------------------------- app


def create_app(*, db_path: Path | None = None, owner: str | None = None, tailnet_name: str | None = None,
               tailnet_url: str | None = None, https: bool = False, run_jobs: bool = True,
               build: str = "dev") -> FastAPI:
    """`owner`: the Mac's own Tailscale login (devices signed in with it are the owner too).
    `tailnet_name`: this Mac's MagicDNS name, answered alongside localhost."""
    extra_hosts: set[str] = set()
    if tailnet_name:
        full = tailnet_name.lower()
        extra_hosts |= {full, full.split(".", 1)[0]}
    worker = jobs.Worker(db_path) if run_jobs else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.connect(db_path).close()  # create or migrate the catalog before anything else
        if worker:
            await worker.start()
        yield
        if worker:
            await worker.stop()

    app = FastAPI(title="Hobbes at Home", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.owner = owner.strip().lower() if owner else None
    app.state.db_path = db_path
    app.state.tailnet_url = tailnet_url
    app.state.worker = worker

    @app.middleware("http")
    async def guard(request: Request, call_next):
        problem = access.guard_problem(request, extra_hosts)
        if problem:
            return JSONResponse({"detail": problem[1]}, status_code=problem[0])
        path = request.url.path
        public = path in PUBLIC or path.startswith("/icons/")
        if not public and not access.is_owner(request):
            if path.startswith("/api/"):
                return JSONResponse({"detail": access.PRIVATE}, status_code=403)
            return PlainTextResponse(access.PRIVATE, 403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        if path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Content-Security-Policy"] = CSP
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/api/meta", response_model=Meta)
    def meta(request: Request) -> Meta:
        return Meta(name="Hobbes at Home", version=__version__, build=build, who=access.who(request),
                    tailnet_url=tailnet_url)

    @app.get("/api/status", response_model=Status)
    def status(conn: Conn) -> Status:
        return Status(ai=AIStatus(**ai.status(conn=conn)), jobs=JobCounts(**jobs.counts(conn)),
                      last_backup_at=maintenance.last_backup_at(), https=https)

    @app.get("/api/jobs", response_model=list[Job])
    def recent_jobs(conn: Conn, limit: int = 20) -> list[Job]:
        return [Job(**j) for j in jobs.recent(conn, max(1, min(limit, 100)))]

    @app.get("/api/jobs/{job_id}", response_model=Job)
    def one_job(job_id: int, conn: Conn) -> Job:
        j = jobs.get(conn, job_id)
        if not j:
            raise HTTPException(404, "No such job.")
        return Job(**j)

    @app.get("/api/ai/usage", response_model=AIUsage)
    def ai_usage(conn: Conn) -> AIUsage:
        """What's left of the allowance (Codex: the 5-hour session and the week, as Codex reports it)."""
        return AIUsage(**ai.usage(conn=conn))

    @app.get("/api/ai/providers", response_model=AIChoices)
    def ai_providers(conn: Conn, refresh: bool = False) -> AIChoices:
        """Claude and ChatGPT: which is chosen, and whether each is installed and signed in on this Mac."""
        return AIChoices(**ai.choices(refresh, conn=conn))

    @app.put("/api/ai/provider", response_model=AIChoices)
    def ai_choose(conn: Conn, body: AIChoiceIn) -> AIChoices:
        """Use Claude or ChatGPT for every AI call from now on."""
        ai.set_provider(conn, body.provider)
        return AIChoices(**ai.choices(conn=conn))

    def _region(conn) -> Region:
        r = region.get(conn)
        countries = sorted(({"code": c, "name": v[0].removeprefix("the ")} for c, v in region.COUNTRIES.items()),
                           key=lambda c: c["name"])
        return Region(**{k: r[k] for k in Region.model_fields if k in r}, countries=[Country(**c) for c in countries])

    @app.get("/api/region", response_model=Region)
    def get_region(conn: Conn) -> Region:
        """Where the owner lives and what they mostly eat: how meals are read, where labels are looked up and
        the currency Hobbes AI gives prices in."""
        return _region(conn)

    @app.put("/api/region", response_model=Region)
    def put_region(conn: Conn, body: RegionIn) -> Region:
        try:
            region.put(conn, body.country, body.cuisine, body.currency)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return _region(conn)

    @app.post("/api/ai/check", response_model=Queued)
    def ai_check(conn: Conn) -> Queued:
        """Queue a tiny AI call that proves the AI works from the dashboard (uses a little of the
        allowance, so it only runs when asked)."""
        job_id = jobs.enqueue(conn, "ai.check", max_attempts=1)
        if worker:
            worker.wake()
        return Queued(job_id=job_id)

    app.include_router(diet_api.router)
    app.include_router(health_api.router)
    app.include_router(whoop_api.router)
    app.include_router(assistant_api.router)
    app.include_router(push_api.router)
    app.include_router(sessions_api.router)
    app.include_router(offsite_api.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_missing(rest: str):
        raise HTTPException(404, "No such API.")

    @app.get("/{rest:path}", include_in_schema=False)
    def frontend(rest: str):
        """The built frontend: a real file when one matches, otherwise index.html (the app routes). A missing
        file (a name with an extension, like /favicon.ico) is 404, not the page: browsers keep what they get."""
        index = STATIC / "index.html"
        if not index.exists():
            return PlainTextResponse(NOT_BUILT, 503)
        if rest:
            candidate = (STATIC / rest).resolve()
            if candidate.is_file() and candidate.is_relative_to(STATIC.resolve()):
                cache = "public, max-age=31536000, immutable" if rest.startswith("assets/") else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if "." in rest.rsplit("/", 1)[-1]:
                return PlainTextResponse("Not found.", 404)
        return FileResponse(index, media_type="text/html")

    return app
