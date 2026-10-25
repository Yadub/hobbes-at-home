"""The Apple Health API: the iPhone posts readings here; the dashboard reads a summary."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import health, insights, jobs
from .web.deps import Conn

router = APIRouter()


class SyncResult(BaseModel):
    received: int
    stored: int
    skipped: int


class Reading(BaseModel):
    type: str
    value: float
    unit: str
    day: str
    source: str


class LastSync(BaseModel):
    at: str
    format: str
    received: int
    stored: int
    skipped: int


class HealthSummary(BaseModel):
    last_sync: LastSync | None
    latest: list[Reading]
    endpoint: str


def _whole_day(kind: str | None, start: object) -> bool:
    """A cumulative reading timed at midnight is a day's total (how Health Auto Export sends days)."""
    t = health.parse_time(str(start or ""))
    return kind in health.CUMULATIVE and t is not None and (t.hour, t.minute, t.second) == (0, 0, 0)


def samples_from(body: Any) -> tuple[list[dict], str]:
    """Readings from whichever shape the phone sent:
    * {"data": {"metrics": [{name, units, data: [{date, qty, source?}]}]}}: Health Auto Export (JSON, v2);
    * {"lines": "<one JSON object per line>"}: the Shortcut, each line {m, u, v, start, end?, agg?};
    * {"samples": [{type, value, unit, start, end?, source?, daily?}]}: the dashboard's own shape."""
    if not isinstance(body, dict):
        raise HTTPException(400, "The body must be a JSON object.")
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("metrics"), list):
        out = []
        for metric in data["metrics"]:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name") or "")
            kind = health.canonical_type(name)
            for p in metric.get("data") or []:
                if not isinstance(p, dict):
                    continue
                value = p.get("qty")
                if kind == "sleep":  # summarised sleep: hours asleep, filed under the night's date
                    value = p.get("totalSleep") or p.get("asleep") or value
                out.append({"type": name, "unit": metric.get("units"), "value": value, "start": p.get("date"),
                            "source": p.get("source") or "", "daily": _whole_day(kind, p.get("date"))})
        return out, "health-auto-export"
    if isinstance(body.get("lines"), str):
        out = []
        for line in body["lines"].splitlines():
            try:
                x = json.loads(line)
            except ValueError:
                out.append({})  # counted as skipped
                continue
            if isinstance(x, dict):
                out.append({"type": x.get("m"), "unit": x.get("u"), "value": x.get("v"), "start": x.get("start"),
                            "end": x.get("end"), "source": str(body.get("source") or "Shortcut"),
                            "daily": x.get("agg") == "day"})
        return out, "shortcut"
    if isinstance(body.get("samples"), list):
        return [s for s in body["samples"] if isinstance(s, dict)], "samples"
    raise HTTPException(400, "Send Health Auto Export's JSON, the Shortcut's lines, or {\"samples\": [...]}.")


@router.post("/api/health/samples", response_model=SyncResult)
async def receive(request: Request, conn: Conn) -> Any:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "The body must be JSON.") from None
    samples, fmt = samples_from(body)
    return health.store(conn, samples, fmt=fmt)


@router.get("/api/health/summary", response_model=HealthSummary)
def summary(request: Request, conn: Conn) -> Any:
    latest = []
    for kind in health.UNITS:
        r = health.latest(conn, kind)
        if r:
            value = health.day_total(conn, kind, r["day"]) if kind in health.CUMULATIVE else r["value"]
            latest.append({"type": kind, "value": round(value or 0, 2), "unit": health.UNITS[kind], "day": r["day"],
                           "source": r["source"]})
    base = getattr(request.app.state, "tailnet_url", None) or str(request.base_url).rstrip("/")
    return {"last_sync": health.last_sync(conn), "latest": latest, "endpoint": f"{base}/api/health/samples"}


# ---------------------------------------------------------------- the Health page

class SeriesPoint(BaseModel):
    day: str
    value: float


class Metric(BaseModel):
    key: str
    label: str
    unit: str
    decimals: int
    source: str | None
    recent: float | None
    baseline: float | None
    change: float | None
    pct: float | None
    status: str
    latest: SeriesPoint | None
    points: list[SeriesPoint]


class SportRow(BaseModel):
    sport: str
    sessions: int
    minutes: float | None
    strain: float | None
    kcal: float | None


class WorkoutRow(BaseModel):
    sport: str
    day: str
    start: str
    minutes: float | None
    strain: float | None
    kcal: float | None
    avg_hr: float | None


class Totals(BaseModel):
    sessions: int
    minutes: float


class Activities(BaseModel):
    by_sport: list[SportRow]
    recent: list[WorkoutRow]
    totals: dict[str, Totals]


class Driver(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    aim: str
    status: str
    detail: str | None = None


class Focus(BaseModel):
    title: str
    why: str
    how: str
    impact: str


class Coach(BaseModel):
    summary: str
    focus: list[Focus]
    at: str


class Overview(BaseModel):
    today: str
    metrics: list[Metric]
    activities: Activities
    drivers: list[Driver]
    coach: Coach | None


class CoachIn(BaseModel):
    today: str


class CoachJob(BaseModel):
    job_id: int


def _day(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(400, "Days are written YYYY-MM-DD.") from None


@router.get("/api/health/overview", response_model=Overview)
def get_overview(conn: Conn, today: str) -> Any:
    return insights.overview(conn, _day(today))


@router.get("/api/health/metric/{key}", response_model=Metric)
def get_metric(conn: Conn, key: str, today: str, days: int = 90) -> Any:
    if key not in insights.keys():
        raise HTTPException(404, "No such measure.")
    return insights.metric_detail(conn, key, _day(today), max(7, min(days, 365)))


@router.post("/api/health/coach", response_model=CoachJob)
def ask_coach(request: Request, conn: Conn, body: CoachIn) -> Any:
    job_id = jobs.enqueue(conn, "health.coach", {"today": _day(body.today)}, max_attempts=1)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()
    return {"job_id": job_id}
