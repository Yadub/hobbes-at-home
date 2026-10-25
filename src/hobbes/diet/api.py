"""The diet API (under /api/diet), plus Undo."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import ai, changes, db, health, jobs, region
from ..web.deps import Conn
from . import drinks, explain, foods, meals, targets

router = APIRouter()


def _call[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Plain errors from the diet code become plain HTTP answers."""
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

class Nutrients(BaseModel):
    kcal: float
    protein: float
    carbs: float
    fat: float
    fibre: float | None = None
    caffeine: float | None = Field(default=None, description="mg; None until worked out (diet/drinks.py).")
    alcohol: float | None = Field(default=None, description="Grams of pure alcohol; a UK unit is 8 g.")


class Serving(BaseModel):
    name: str
    grams: float


class Food(BaseModel):
    id: str
    source: str
    name: str
    aliases: list[str]
    group: str
    kcal: float
    protein: float
    carbs: float
    fat: float
    fibre: float | None
    servings: list[Serving]


class Item(BaseModel):
    id: int
    meal_id: int
    name: str
    food_id: str | None
    portion: str
    grams: float
    kcal: float
    protein: float
    carbs: float
    fat: float
    fibre: float | None
    caffeine: float | None
    alcohol: float | None
    per100: Nutrients
    basis: Literal["table", "estimate", "owner", "label"]
    confidence: str
    ai_grams: float | None
    label_url: str | None
    edited_at: str | None


class Meal(BaseModel):
    id: int
    eaten_at: str
    day: str
    slot: str
    note: str
    photos: int
    status: Literal["analysing", "ready", "failed"]
    job_id: int | None
    title: str
    error: str | None
    totals: Nutrients
    items: list[Item]


class UsualMeal(Meal):
    times: int = Field(description="How often it was had in the last 90 days.")
    usual_at: str | None = Field(description="The time of day it's usually had (HH:MM), when it's mostly one time.")


class ItemWhy(BaseModel):
    item_id: int
    why: str
    doubt: str = Field(description="What's most likely to be off, or empty.")


class Explanation(BaseModel):
    summary: str
    items: list[ItemWhy]
    at: str


class ExplainStarted(BaseModel):
    explanation: Explanation | None = Field(description="The kept one, when the meal hasn't changed since.")
    job_id: int | None = Field(description="Otherwise the job working one out.")


class RedoIn(BaseModel):
    correction: str = Field(min_length=1, max_length=500)


class Weight(BaseModel):
    kg: float
    day: str
    source: str


class Goal(BaseModel):
    goal: Literal["lose", "maintain", "gain"]
    rate: float
    activity: Literal["sedentary", "light", "moderate", "very"]
    eat_back: float
    protein_per_kg: float
    kcal_override: int | None
    protein_override: int | None
    fat_pct: float = 0.3
    saved: bool = False


class Split(BaseModel):
    protein: int
    carbs: int
    fat: int


class Targets(BaseModel):
    ready: bool
    kcal: int | None
    protein: int | None
    carbs: int | None = None
    fat: int | None = None
    fibre: int | None = None
    split: Split | None = None
    goal: Goal
    weight: Weight | None
    active_kcal: int | None
    activity_source: str | None = None
    resting_kcal: int | None
    bmr: int | None = None
    maintenance: int | None = None
    kcal_how: str | None = None
    protein_how: str | None = None
    missing: list[str]
    notes: list[str]


class Left(BaseModel):
    kcal: int | None
    protein: int | None
    carbs: int | None = None
    fat: int | None = None
    fibre: int | None = None


class Day(BaseModel):
    day: str
    meals: list[Meal]
    eaten: Nutrients
    targets: Targets
    left: Left


class HistoryDay(BaseModel):
    day: str
    meals: int
    kcal: int
    protein: int
    carbs: int
    fat: int
    target_kcal: int | None
    target_protein: int | None


class Point(BaseModel):
    day: str
    value: float


class History(BaseModel):
    days: list[HistoryDay]
    weight: list[Point]
    active: list[Point]


class Profile(BaseModel):
    sex: Literal["male", "female"] | None
    birth_year: int | None
    height_cm: float | None
    height_from_health: bool = False


class DrinksToday(BaseModel):
    caffeine: float
    alcohol_units: float | None


class DrinksSpan(BaseModel):
    days: int
    start: str
    end: str
    logged_days: int = Field(description="Days with anything logged; the averages are over these.")
    today_left_out: bool = Field(description="Today has entries but is still filling up, so it isn't in the averages.")
    pending: int = Field(description="Items in the span whose caffeine and alcohol aren't worked out yet.")
    caffeine_total: float = Field(description="mg in the span, as logged.")
    caffeine_per_day: float | None
    caffeine_per_week: float | None = Field(description="mg a week: the daily average × 7.")
    caffeine_highest: float | None
    caffeine_days_over: int
    alcohol_units_total: float = Field(description="Units in the span, as logged.")
    alcohol_units_per_week: float | None
    alcohol_heaviest_day: float | None
    alcohol_free_days: int


class Typical(BaseModel):
    value: float
    label: str
    source: str


class Guidance(BaseModel):
    aim: float
    aim_text: str
    aim_source: str
    typical: list[Typical]


class DrinksReference(BaseModel):
    caffeine: Guidance
    alcohol: Guidance


class DrinksView(BaseModel):
    enabled: bool
    pending: int
    today: DrinksToday
    week: DrinksSpan
    month: DrinksSpan
    reference: DrinksReference


class DrinksIn(BaseModel):
    enabled: bool


class GoalsView(BaseModel):
    goal: Goal
    profile: Profile
    targets: Targets


class GoalsIn(BaseModel):
    goal: Literal["lose", "maintain", "gain"]
    rate: float = Field(ge=0, le=1)
    activity: Literal["sedentary", "light", "moderate", "very"] = "light"
    eat_back: float = Field(0.5, ge=0, le=1)
    protein_per_kg: float = Field(1.6, ge=0.6, le=3)
    kcal_override: int | None = Field(None, ge=800, le=6000)
    protein_override: int | None = Field(None, ge=20, le=400)
    fat_pct: float = Field(0.3, ge=0.15, le=0.45)
    sex: Literal["male", "female"] | None = None
    birth_year: int | None = Field(None, ge=1900, le=2100)
    height_cm: float | None = Field(None, ge=100, le=250)


class Created(BaseModel):
    meal_id: int
    job_id: int | None = None


class ChangeDone(BaseModel):
    change_id: int


class OwnNutrients(BaseModel):
    """The owner's own numbers for the amount eaten; any left out keep their value."""
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None


class ItemIn(BaseModel):
    grams: float | None = None
    portion: str | None = None
    name: str | None = None
    nutrients: OwnNutrients | None = None


class NewItem(BaseModel):
    text: str = Field(max_length=2000, description="What else they had, e.g. “a bowl of yoghurt”; the AI reads it.")


class MealIn(BaseModel):
    eaten_at: str | None = None
    slot: Literal["breakfast", "lunch", "snack", "dinner"] | None = None
    title: str | None = None
    note: str | None = None


class AgainIn(BaseModel):
    eaten_at: str


class WeightIn(BaseModel):
    kg: float = Field(ge=20, le=400)
    at: str


class SuggestIn(BaseModel):
    day: str


class JobRef(BaseModel):
    job_id: int


class Undone(BaseModel):
    table: str
    id: int
    kind: str


# ---------------------------------------------------------------- days, history, goals

def _check_day(day: str) -> str:
    try:
        return datetime.strptime(day, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(400, "Days are written YYYY-MM-DD.") from None


@router.get("/api/diet/day", response_model=Day)
def day(conn: Conn, day: str) -> Any:
    return meals.day_summary(conn, _check_day(day))


@router.get("/api/diet/history", response_model=History)
def history(conn: Conn, start: str, end: str) -> Any:
    s, e = _check_day(start), _check_day(end)
    return {"days": meals.history(conn, s, e),
            "weight": [p for p in health.series(conn, "weight", s) if p["day"] <= e],
            "active": [p for p in health.series(conn, "active_energy", s) if p["day"] <= e]}


@router.get("/api/diet/recent", response_model=list[UsualMeal])
def recent(conn: Conn, at: str | None = None) -> Any:
    """Meals to log again, what's usually had around `at` (ISO 8601 with its offset; now by default) first."""
    try:
        when = datetime.fromisoformat(at) if at else datetime.now().astimezone()
    except ValueError:
        raise HTTPException(400, "The time must be ISO 8601, like 2026-10-21T08:30:00+05:30.") from None
    if when.tzinfo is None:
        raise HTTPException(400, "The time needs its UTC offset.")
    return meals.usual_meals(conn, when)


@router.get("/api/diet/goals", response_model=GoalsView)
def get_goals(conn: Conn, day: str) -> Any:
    return {"goal": targets.goal(conn), "profile": targets.profile(conn),
            "targets": targets.for_day(conn, _check_day(day))}


@router.get("/api/diet/drinks", response_model=DrinksView)
def get_drinks(conn: Conn, day: str) -> Any:
    """Caffeine and alcohol: today, the last 7 and 30 days, and the figures to compare with."""
    return drinks.view(conn, _check_day(day))


@router.put("/api/diet/drinks", response_model=DrinksView)
def put_drinks(request: Request, conn: Conn, body: DrinksIn, day: str) -> Any:
    """Track caffeine and alcohol (on by default). Turning it on works out any items logged without them."""
    drinks.set_enabled(conn, body.enabled)
    _wake(request)
    return drinks.view(conn, _check_day(day))


@router.put("/api/diet/goals", response_model=GoalsView)
def put_goals(conn: Conn, body: GoalsIn, day: str) -> Any:
    values = body.model_dump()
    with db.write_lock(conn):
        _call(targets.save_profile, conn, {k: values[k] for k in targets.PROFILE_KEYS})
        _call(targets.save_goal, conn, values)
    return get_goals(conn, day)


@router.post("/api/diet/weight", response_model=Weight)
def add_weight(conn: Conn, body: WeightIn) -> Any:
    result = health.store(conn, [{"type": "weight", "value": body.kg, "unit": "kg", "start": body.at,
                                  "source": "Hobbes at Home"}], fmt="dashboard")
    if not result["stored"]:
        raise HTTPException(400, "That weight couldn't be saved; check the time.")
    w = targets.weight_on(conn, body.at[:10])
    assert w
    return w


# ---------------------------------------------------------------- meals and items

@router.post("/api/diet/meals", response_model=Created)
async def create_meal(request: Request, conn: Conn, eaten_at: str = Form(...), note: str = Form(""),
                      slot: str | None = Form(None), photos: list[UploadFile] = File(default=[])) -> Any:
    data = [await p.read(meals.MAX_PHOTO_BYTES + 1) for p in photos[: meals.MAX_PHOTOS + 1]]
    meal_id = _call(meals.create, conn, eaten_at=eaten_at, note=note, photos=data, slot=slot or None)
    _wake(request)
    m = meals.get(conn, meal_id)
    return {"meal_id": meal_id, "job_id": m["job_id"] if m else None}


@router.get("/api/diet/meals/{meal_id}", response_model=Meal)
def get_meal(conn: Conn, meal_id: int) -> Any:
    m = meals.get(conn, meal_id)
    if not m:
        raise HTTPException(404, "There's no such meal.")
    return m


@router.patch("/api/diet/meals/{meal_id}", response_model=ChangeDone)
def edit_meal(conn: Conn, meal_id: int, body: MealIn) -> Any:
    return _call(meals.edit_meal, conn, meal_id, **body.model_dump(exclude_none=True))


@router.delete("/api/diet/meals/{meal_id}", response_model=ChangeDone)
def remove_meal(conn: Conn, meal_id: int) -> Any:
    return _call(meals.remove_meal, conn, meal_id)


@router.post("/api/diet/meals/{meal_id}/again", response_model=Created)
def log_again(conn: Conn, meal_id: int, body: AgainIn) -> Any:
    return {"meal_id": _call(meals.log_again, conn, meal_id, body.eaten_at)}


@router.post("/api/diet/meals/{meal_id}/analyse", response_model=JobRef)
def reanalyse(request: Request, conn: Conn, meal_id: int) -> Any:
    if not meals.get(conn, meal_id):
        raise HTTPException(404, "There's no such meal.")
    job_id = meals.queue_analysis(conn, meal_id)
    _wake(request)
    return {"job_id": job_id}


@router.post("/api/diet/meals/{meal_id}/items", response_model=JobRef)
def add_item(request: Request, conn: Conn, meal_id: int, body: NewItem) -> Any:
    """The AI reads what they typed into items added to the meal; the job's result has their change_ids."""
    job_id = _call(meals.queue_add, conn, meal_id, body.text)
    _wake(request)
    return {"job_id": job_id}


@router.patch("/api/diet/items/{item_id}", response_model=ChangeDone)
def edit_item(conn: Conn, item_id: int, body: ItemIn) -> Any:
    return _call(meals.edit_item, conn, item_id, **body.model_dump(exclude_none=True))


@router.post("/api/diet/items/{item_id}/estimate", response_model=ChangeDone)
def use_estimate(conn: Conn, item_id: int) -> Any:
    """Use the AI's own estimate for this item instead of its label's or an old table food's values (Undo puts
    them back)."""
    return _call(meals.use_estimate, conn, item_id)


@router.delete("/api/diet/items/{item_id}", response_model=ChangeDone)
def remove_item(conn: Conn, item_id: int) -> Any:
    return _call(meals.remove_item, conn, item_id)


@router.post("/api/diet/items/{item_id}/redo", response_model=JobRef)
def redo_item(request: Request, conn: Conn, item_id: int, body: RedoIn) -> Any:
    """Read one item again with the owner's correction ("it was lentil soup, about 2 bowls"); the job's
    result has the change_id for Undo."""
    job_id = _call(meals.queue_redo, conn, item_id, body.correction)
    _wake(request)
    return {"job_id": job_id}


@router.get("/api/diet/meals/{meal_id}/explanation", response_model=Explanation | None)
def get_explanation(conn: Conn, meal_id: int) -> Any:
    """Why these numbers, when it has been worked out and the meal hasn't changed since."""
    return _call(explain.cached, conn, meal_id)


@router.post("/api/diet/meals/{meal_id}/explain", response_model=ExplainStarted)
def start_explain(request: Request, conn: Conn, meal_id: int) -> Any:
    out = _call(explain.queue, conn, meal_id)
    if out["job_id"]:
        _wake(request)
    return out


@router.get("/api/diet/meals/{meal_id}/photos/{n}", include_in_schema=False)
def photo(conn: Conn, meal_id: int, n: int) -> FileResponse:
    m = conn.execute("SELECT photos FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not m or not 0 <= n < m[0]:
        raise HTTPException(404, "There's no such photo.")
    path = meals.photo_dir(meal_id) / f"{n}.jpg"
    if not path.exists():
        raise HTTPException(404, "There's no such photo.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})


# ---------------------------------------------------------------- foods

@router.get("/api/diet/foods/{food_id}", response_model=Food)
def get_food(conn: Conn, food_id: str) -> Any:
    f = foods.get(conn, food_id)
    if not f:
        raise HTTPException(404, "There's no such food.")
    return f


# ---------------------------------------------------------------- suggestions

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {"suggestions": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "portion": {"type": "string"}, "kcal": {"type": "number"},
                       "protein": {"type": "number"}, "carbs": {"type": "number"}, "fat": {"type": "number"},
                       "why": {"type": "string"}},
        "required": ["name", "portion", "kcal", "protein", "carbs", "fat", "why"], "additionalProperties": False}}},
    "required": ["suggestions"],
    "additionalProperties": False,
}


class SuggestionOut(BaseModel):
    name: str
    portion: str
    kcal: float
    protein: float
    carbs: float
    fat: float
    why: str


@router.post("/api/diet/suggest", response_model=JobRef)
def suggest(request: Request, conn: Conn, body: SuggestIn) -> Any:
    job_id = jobs.enqueue(conn, "diet.suggest", {"day": _check_day(body.day)}, max_attempts=1)
    _wake(request)
    return {"job_id": job_id}


def _left_text(left: dict) -> str:
    parts = [f"{left['kcal']} kcal" if left.get("kcal") is not None else None]
    parts += [f"{left[k]} g {k}" for k in ("protein", "carbs", "fat") if left.get(k) is not None]
    return ", ".join(p for p in parts if p)


@jobs.handler("diet.suggest")
def suggest_job(conn: sqlite3.Connection, payload: dict) -> dict:
    s = meals.day_summary(conn, payload["day"])
    usual = [m["title"] for m in meals.usual_meals(conn, datetime.now().astimezone(), limit=15)]
    eaten_today = [m["title"] for m in s["meals"] if m["title"]]
    now = datetime.now()
    left = _left_text(s["left"]) if s["targets"]["ready"] else ""
    targets = (f"Left today: {left}." if left else
               "Their daily targets aren't set yet: suggest balanced, protein-forward options of 300-500 kcal.")
    prompt = "\n".join([
        "Suggest four meals or snacks this person could have next. Do not run any commands.",
        region.fill("{eats}", conn) + " Prefer what they already eat (listed below), with the portion adjusted, "
        "or simple home options like it; include at least one quick, high-protein option. Suit the time of day. "
        "For each: a household portion, kcal, protein, carbs and fat in grams for that portion, and one short "
        "reason (which target it helps). Never suggest more calories than are left.",
        "",
        f"Time now: {now:%H:%M}.",
        targets,
        f"Eaten today: {', '.join(eaten_today) or 'nothing yet'}.",
        f"Meals they often have: {', '.join(usual) or 'not known yet'}.",
    ])
    answer = ai.ask(prompt, schema=SUGGEST_SCHEMA, kind="diet.suggest", timeout=180, conn=conn)
    return {"suggestions": answer["suggestions"][:4], "left": s["left"]}


# ---------------------------------------------------------------- undo

@router.post("/api/undo/{change_id}", response_model=Undone)
def undo(conn: Conn, change_id: int) -> Any:
    return _call(changes.undo, conn, change_id)
