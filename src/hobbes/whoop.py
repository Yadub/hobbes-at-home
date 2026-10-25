"""WHOOP: sign-in (OAuth 2) and a sync every 30 minutes into the readings table Apple Health also uses
(source "WHOOP"): each day's energy burned, strain and steps (cycles), recovery, resting heart rate and
HRV, sleep, and body weight and height.

The app's Client ID and redirect address are settings; the Client Secret and the sign-in tokens live in
the Keychain. WHOOP rotates refresh tokens (each refresh returns a new one and invalidates the old), so
refreshes are serialised and the new token is saved before anything else happens.
"""

from __future__ import annotations

import json
import secrets as pysecrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from . import db, health, jobs, secrets

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer"
SCOPES = "offline read:profile read:body_measurement read:cycles read:recovery read:sleep read:workout"
SOURCE = "WHOOP"
CALLBACK_PATH = "/api/whoop/callback"
HISTORY_DAYS = 90
_LOCK = threading.Lock()


class WhoopError(Exception):
    user_facing = True


def transport(method: str, url: str, *, form: dict | None = None, headers: dict | None = None,
              timeout: float = 30) -> tuple[int, Any]:
    """One HTTPS request to WHOOP: (status, parsed JSON). Replaced in tests."""
    body = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Accept": "application/json", "User-Agent": "HobbesAtHome/0.1",
                                          **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WhoopError(f"WHOOP couldn't be reached ({e}).") from None
    try:
        return status, (json.loads(raw) if raw else None)
    except ValueError:
        return status, {"error": raw[:200].decode(errors="replace")}


# ---------------------------------------------------------------- settings and tokens

def _setting(conn: sqlite3.Connection, key: str) -> str | None:
    return db.get_setting(conn, f"whoop.{key}")


def _set(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (f"whoop.{key}",))
    else:
        db.set_setting(conn, f"whoop.{key}", value)


def _tokens() -> dict | None:
    raw = secrets.get("whoop.tokens")
    return json.loads(raw) if raw else None


def _save_tokens(data: dict) -> None:
    if not data.get("access_token"):
        raise WhoopError("WHOOP didn't return an access token.")
    old = _tokens() or {}
    secrets.put("whoop.tokens", json.dumps({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or old.get("refresh_token"),
        "expires_at": time.time() + int(data.get("expires_in") or 3600) - 60,
    }))


# WHOOP's API terms: its data goes to an AI only when the member has chosen that. Off until the owner turns it on.
AI_SETTING = "whoop.share_with_ai"
NOT_SHARED = ("Your WHOOP data isn't shared with the AI. To use it here, turn on Share With the AI in "
              "Settings, WHOOP.")


def shared_with_ai(conn: sqlite3.Connection) -> bool:
    """Whether health data may go to the AI: always when there's no WHOOP data, else only when the owner chose."""
    if db.get_setting(conn, AI_SETTING) == "1":
        return True
    return conn.execute("SELECT 1 FROM health_samples WHERE source = 'WHOOP' LIMIT 1").fetchone() is None


def set_shared_with_ai(conn: sqlite3.Connection, on: bool) -> None:
    db.set_setting(conn, AI_SETTING, "1" if on else "0")


def status(conn: sqlite3.Connection) -> dict:
    profile = _setting(conn, "profile")
    return {
        "share_with_ai": db.get_setting(conn, AI_SETTING) == "1",
        "configured": bool(_setting(conn, "client_id") and secrets.get("whoop.client_secret")),
        "connected": _tokens() is not None,
        "client_id": _setting(conn, "client_id"),
        "redirect_uri": _setting(conn, "redirect_uri"),
        "profile": json.loads(profile) if profile else None,
        "last_sync_at": _setting(conn, "last_sync_at"),
        "last_error": _setting(conn, "last_error"),
    }


def configure(conn: sqlite3.Connection, client_id: str, client_secret: str | None, redirect_uri: str) -> None:
    client_id = client_id.strip()
    redirect_uri = redirect_uri.strip()
    parts = urllib.parse.urlsplit(redirect_uri)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path != CALLBACK_PATH:
        raise ValueError(f"The redirect address must end in {CALLBACK_PATH}, as entered in your WHOOP app.")
    if not client_id:
        raise ValueError("Enter the Client ID from your WHOOP app.")
    if client_secret:
        secrets.put("whoop.client_secret", client_secret.strip())
    elif not secrets.get("whoop.client_secret"):
        raise ValueError("Enter the Client Secret from your WHOOP app.")
    _set(conn, "client_id", client_id)
    _set(conn, "redirect_uri", redirect_uri)


def start(conn: sqlite3.Connection) -> str:
    """The WHOOP sign-in address to send the browser to. The state ties the answer to this request."""
    client_id, redirect = _setting(conn, "client_id"), _setting(conn, "redirect_uri")
    if not client_id or not redirect:
        raise ValueError("Set up the WHOOP app first.")
    state = pysecrets.token_urlsafe(24)
    _set(conn, "state", json.dumps({"value": state, "at": time.time()}))
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": SCOPES, "state": state})


def finish(conn: sqlite3.Connection, code: str, state: str) -> dict:
    """WHOOP sent the browser back with a code: exchange it for tokens and fetch who signed in."""
    saved = json.loads(_setting(conn, "state") or "{}")
    _set(conn, "state", None)
    if not saved or not pysecrets.compare_digest(str(saved.get("value")), state or "") \
            or time.time() - float(saved.get("at", 0)) > 900:
        raise WhoopError("That WHOOP sign-in has expired or didn't come from here. Try connecting again.")
    st, data = transport("POST", TOKEN_URL, form={
        "grant_type": "authorization_code", "code": code, "client_id": _setting(conn, "client_id"),
        "client_secret": secrets.get("whoop.client_secret"), "redirect_uri": _setting(conn, "redirect_uri")})
    if st != 200:
        raise WhoopError(f"WHOOP refused the sign-in: {_why(data)}")
    with _LOCK:
        _save_tokens(data)
    profile = get(conn, "/v2/user/profile/basic")
    _set(conn, "profile", json.dumps({k: profile.get(k) for k in ("first_name", "last_name", "email")}))
    _set(conn, "connected_at", db.now())
    _set(conn, "last_error", None)
    return profile


def disconnect(conn: sqlite3.Connection) -> None:
    """Forget the sign-in. The app's keys and every reading already synced are kept."""
    secrets.forget("whoop.tokens")
    _set(conn, "profile", None)
    _set(conn, "last_error", None)


def _why(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("error_description") or data.get("message") or data.get("error") or data)[:200]
    return str(data)[:200]


def _access_token(conn: sqlite3.Connection, force: bool = False) -> str:
    with _LOCK:
        t = _tokens()
        if not t:
            raise WhoopError("WHOOP isn't connected.")
        if not force and t["expires_at"] > time.time():
            return t["access_token"]
        if not t.get("refresh_token"):
            raise WhoopError("WHOOP's sign-in has expired. Connect again in Settings.")
        st, data = transport("POST", TOKEN_URL, form={
            "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
            "client_id": _setting(conn, "client_id"), "client_secret": secrets.get("whoop.client_secret"),
            "scope": "offline"})
        if st != 200:
            if st in (400, 401):
                secrets.forget("whoop.tokens")
                raise WhoopError("WHOOP's sign-in has expired. Connect again in Settings.")
            raise WhoopError(f"WHOOP didn't renew the sign-in: {_why(data)}")
        _save_tokens(data)
        return data["access_token"]


def get(conn: sqlite3.Connection, path: str, params: dict | None = None) -> Any:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(2):
        token = _access_token(conn, force=attempt > 0)
        st, data = transport("GET", url, headers={"Authorization": f"Bearer {token}"})
        if st == 200:
            return data
        if st == 401 and attempt == 0:
            continue  # the token was refused: renew it once and try again
        if st == 429:
            raise WhoopError("WHOOP asked us to slow down; the next sync will try again.")
        if st == 404 and path == "/v2/user/measurement/body":
            return {}
        raise WhoopError(f"WHOOP answered {st} for {path}: {_why(data)}")
    raise WhoopError("WHOOP refused the sign-in.")


def collection(conn: sqlite3.Connection, path: str, start: datetime, end: datetime | None = None) -> list[dict]:
    out: list[dict] = []
    params: dict = {"start": start.astimezone(UTC).isoformat().replace("+00:00", "Z"), "limit": 25}
    if end:
        params["end"] = end.astimezone(UTC).isoformat().replace("+00:00", "Z")
    for _ in range(200):  # 200 pages × 25 records is far beyond any real history
        page = get(conn, path, params) or {}
        out.extend(page.get("records") or [])
        token = page.get("next_token")
        if not token:
            break
        params = {**params, "nextToken": token}
    return out


# ---------------------------------------------------------------- sync

def _local(ts: str | None, offset: str | None) -> datetime | None:
    if not ts:
        return None
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    try:
        sign = -1 if (offset or "+00:00").startswith("-") else 1
        hh, mm = (offset or "+00:00").lstrip("+-").split(":")
        return t.astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    except ValueError:
        return t


def cycle_day(start: datetime) -> str:
    """The date a WHOOP day belongs to. A cycle runs from falling asleep to falling asleep again, so it
    usually starts the evening before (or just after midnight): twelve hours in is always the waking day."""
    return (start + timedelta(hours=12)).date().isoformat()


def readings(cycles: list[dict], recoveries: list[dict], sleeps: list[dict]) -> list[dict]:
    """WHOOP records as readings for health.store. A cycle and its recovery count for the waking day they
    cover; a sleep for the morning you woke up. WHOOP's HRV is RMSSD, kept apart from Apple's SDNN."""
    out: list[dict] = []
    cycle_start: dict[Any, datetime] = {}
    for c in cycles:
        start = _local(c.get("start"), c.get("timezone_offset"))
        if not start:
            continue
        cycle_start[c.get("id")] = start
        end = _local(c.get("end"), c.get("timezone_offset"))
        score = c.get("score") or {}
        base = {"start": start.isoformat(), "end": end.isoformat() if end else None, "source": SOURCE, "daily": True,
                "day": cycle_day(start)}
        if c.get("score_state") == "SCORED" and score.get("kilojoule") is not None:
            out.append({**base, "type": "total_energy", "value": score["kilojoule"], "unit": "kJ"})
        if c.get("score_state") == "SCORED" and score.get("strain") is not None:
            out.append({**base, "type": "strain", "value": score["strain"], "unit": ""})
        if c.get("step_count") is not None:
            out.append({**base, "type": "steps", "value": c["step_count"], "unit": "count"})
    for r in recoveries:
        start = cycle_start.get(r.get("cycle_id"))
        score = r.get("score") or {}
        if not start or r.get("score_state") != "SCORED":
            continue
        base = {"start": start.isoformat(), "source": SOURCE, "day": cycle_day(start)}
        for kind, key, unit in (("recovery", "recovery_score", "%"), ("resting_hr", "resting_heart_rate", "bpm"),
                                ("hrv_rmssd", "hrv_rmssd_milli", "ms")):
            if score.get(key) is not None:
                out.append({**base, "type": kind, "value": score[key], "unit": unit})
    for s in sleeps:
        score = (s.get("score") or {}).get("stage_summary") or {}
        if s.get("nap") or s.get("score_state") != "SCORED" or not score:
            continue
        woke = _local(s.get("end"), s.get("timezone_offset"))
        asleep = sum(score.get(k) or 0 for k in ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
                                                 "total_rem_sleep_time_milli"))
        if woke and asleep:
            out.append({"type": "sleep", "value": asleep / 3_600_000, "unit": "h", "start": woke.isoformat(),
                        "source": SOURCE})
            whole = s.get("score") or {}
            for kind, key in (("sleep_consistency", "sleep_consistency_percentage"),
                              ("sleep_performance", "sleep_performance_percentage")):
                if woke and whole.get(key) is not None:
                    out.append({"type": kind, "value": whole[key], "unit": "%", "start": woke.isoformat(),
                                "source": SOURCE})
    return out


def sport_name(raw: str | None) -> str:
    """WHOOP's sport keys ("rock-climbing", "hiking-rucking") as words."""
    words = (raw or "activity").replace("-", " ").replace("_", " ").strip().lower()
    return {"hiking rucking": "hiking or rucking", "activity": "other activity"}.get(words, words).capitalize()


_ZONES = ("zone_zero_milli", "zone_one_milli", "zone_two_milli", "zone_three_milli", "zone_four_milli",
          "zone_five_milli")


def store_workouts(conn: sqlite3.Connection, records: list[dict]) -> int:
    """WHOOP workouts, one row each (updated in place as WHOOP rescores them)."""
    n = 0
    now = db.now()
    with db.write_lock(conn):
        for w in records:
            start = _local(w.get("start"), w.get("timezone_offset"))
            if not start or not w.get("id"):
                continue
            end = _local(w.get("end"), w.get("timezone_offset"))
            score = w.get("score") or {}
            zones = score.get("zone_durations") or {}
            conn.execute(
                "INSERT INTO workouts (source, source_id, sport, start, end, day, minutes, strain, kcal, avg_hr, "
                "max_hr, zones, distance_m, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (source, source_id) DO UPDATE SET sport = excluded.sport, end = excluded.end, "
                "minutes = excluded.minutes, strain = excluded.strain, kcal = excluded.kcal, avg_hr = excluded.avg_hr, "
                "max_hr = excluded.max_hr, zones = excluded.zones, distance_m = excluded.distance_m, "
                "received_at = excluded.received_at",
                (SOURCE, str(w["id"]), sport_name(w.get("sport_name")),
                 start.isoformat(), end.isoformat() if end else None, start.date().isoformat(),
                 round((end - start).total_seconds() / 60, 1) if end else None, score.get("strain"),
                 round(score["kilojoule"] / 4.184, 1) if score.get("kilojoule") is not None else None,
                 score.get("average_heart_rate"), score.get("max_heart_rate"),
                 json.dumps({str(i): round((zones.get(k) or 0) / 60000, 1) for i, k in enumerate(_ZONES)}),
                 score.get("distance_meter"), now))
            n += 1
    return n


def sync(conn: sqlite3.Connection, full: bool = False) -> dict:
    if _tokens() is None:
        return {"skipped": "not connected"}
    try:
        last = _setting(conn, "last_sync_at")
        now = datetime.now(UTC)
        since = now - timedelta(days=HISTORY_DAYS) if full or not last \
            else datetime.fromisoformat(last) - timedelta(days=3)  # scores settle over a day or two
        samples = readings(collection(conn, "/v2/cycle", since), collection(conn, "/v2/recovery", since),
                           collection(conn, "/v2/activity/sleep", since))
        workouts = store_workouts(conn, collection(conn, "/v2/activity/workout", since))
        body = get(conn, "/v2/user/measurement/body") or {}
        for kind, value in (("weight", body.get("weight_kilogram")),
                            ("height", (body.get("height_meter") or 0) * 100 or None)):
            if value is None:
                continue
            prev = conn.execute("SELECT value FROM health_samples WHERE type = ? AND source = ? "
                                "ORDER BY start DESC LIMIT 1", (kind, SOURCE)).fetchone()
            if prev is None or abs(prev[0] - value) >= 0.05:  # a new reading only when it changed
                samples.append({"type": kind, "value": value, "unit": "kg" if kind == "weight" else "cm",
                                "start": now.astimezone().isoformat(timespec="seconds"), "source": SOURCE})
        result = {**health.store(conn, samples, fmt="whoop"), "workouts": workouts}
    except WhoopError as e:
        _set(conn, "last_error", str(e))
        raise
    _set(conn, "last_sync_at", now.isoformat(timespec="seconds"))
    _set(conn, "last_error", None)
    return result


@jobs.handler("whoop.sync", every=1800)
def sync_job(conn: sqlite3.Connection, payload: dict) -> dict:
    return sync(conn, full=bool(payload.get("full")))
