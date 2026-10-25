import json
import time
import urllib.parse

import pytest

from hobbes import db, health, jobs, secrets, whoop
from hobbes.diet import targets

REDIRECT = "http://localhost:8780/api/whoop/callback"


class FakeWhoop:
    """Plays WHOOP's sign-in and API: rotating refresh tokens, paged collections, a 401 on demand."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.refresh = "r1"
        self.access = "a1"
        self.reject_next_get = False
        self.refresh_broken = False
        self.weight = 80.0

    def __call__(self, method, url, *, form=None, headers=None, timeout=30):
        self.calls.append((method, url, form or {}))
        if url == whoop.TOKEN_URL:
            if form["grant_type"] == "authorization_code":
                assert form["client_secret"] == "s3cret" and form["redirect_uri"] == REDIRECT
                return 200, {"access_token": self.access, "refresh_token": self.refresh, "expires_in": 3600}
            if self.refresh_broken or form["refresh_token"] != self.refresh:
                return 400, {"error": "invalid_grant"}
            n = int(self.refresh[1:]) + 1
            self.refresh, self.access = f"r{n}", f"a{n}"
            return 200, {"access_token": self.access, "refresh_token": self.refresh, "expires_in": 3600}
        assert headers and headers["Authorization"] == f"Bearer {self.access}" or self.reject_next_get
        if self.reject_next_get:
            self.reject_next_get = False
            return 401, {"message": "expired"}
        path = urllib.parse.urlsplit(url).path.removeprefix("/developer")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if path == "/v2/user/profile/basic":
            return 200, {"user_id": 7, "email": "owner@example.com", "first_name": "Yadu", "last_name": "B"}
        if path == "/v2/user/measurement/body":
            return 200, {"height_meter": 1.78, "weight_kilogram": self.weight, "max_heart_rate": 190}
        if path == "/v2/cycle":
            if q.get("nextToken") == "p2":
                return 200, {"records": [CYCLE_1], "next_token": None}
            return 200, {"records": [CYCLE_2], "next_token": "p2"}
        if path == "/v2/recovery":
            return 200, {"records": [RECOVERY_1], "next_token": None}
        if path == "/v2/activity/sleep":
            return 200, {"records": [SLEEP_1, NAP], "next_token": None}
        if path == "/v2/activity/workout":
            return 200, {"records": [WORKOUT_1], "next_token": None}
        return 404, {"message": "no"}


CYCLE_1 = {"id": 1, "start": "2026-10-16T01:30:00.000Z", "end": "2026-10-17T01:45:00.000Z", "timezone_offset": "+05:30",
           "score_state": "SCORED", "step_count": 9100, "score": {"strain": 12.4, "kilojoule": 10460.0}}
CYCLE_2 = {"id": 2, "start": "2026-10-17T01:45:00.000Z", "end": None, "timezone_offset": "+05:30",
           "score_state": "SCORED", "step_count": 2300, "score": {"strain": 4.1, "kilojoule": 3138.0}}
RECOVERY_1 = {"cycle_id": 2, "sleep_id": "s1", "score_state": "SCORED",
              "score": {"recovery_score": 71, "resting_heart_rate": 54, "hrv_rmssd_milli": 62.5}}
SLEEP_1 = {"id": "s1", "start": "2026-10-16T17:30:00.000Z", "end": "2026-10-17T01:40:00.000Z",
           "timezone_offset": "+05:30", "nap": False, "score_state": "SCORED",
           "score": {"stage_summary": {"total_light_sleep_time_milli": 12_600_000,
                                       "total_slow_wave_sleep_time_milli": 5_400_000,
                                       "total_rem_sleep_time_milli": 7_200_000}}}
NAP = {**SLEEP_1, "id": "n1", "nap": True}
SLEEP_1["score"]["sleep_consistency_percentage"] = 82
WORKOUT_1 = {"id": "w1", "start": "2026-10-16T12:30:00.000Z", "end": "2026-10-16T13:30:00.000Z",
             "timezone_offset": "+05:30", "sport_name": "weightlifting", "score_state": "SCORED",
             "score": {"strain": 9.8, "kilojoule": 1673.6, "average_heart_rate": 121, "max_heart_rate": 165,
                       "zone_durations": {"zone_zero_milli": 0, "zone_one_milli": 900_000, "zone_two_milli": 1_500_000,
                                          "zone_three_milli": 900_000, "zone_four_milli": 300_000,
                                          "zone_five_milli": 0}}}


@pytest.fixture
def fake(monkeypatch):
    f = FakeWhoop()
    monkeypatch.setattr(whoop, "transport", f)
    return f


def connect(conn):
    whoop.configure(conn, "client-1", "s3cret", REDIRECT)
    url = whoop.start(conn)
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
    whoop.finish(conn, "code-1", state)


def test_sign_in(conn, fake):
    whoop.configure(conn, "client-1", "s3cret", REDIRECT)
    url = whoop.start(conn)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert url.startswith(whoop.AUTH_URL) and q["redirect_uri"] == REDIRECT and "offline" in q["scope"]
    assert len(q["state"]) >= 16
    with pytest.raises(whoop.WhoopError, match="expired or didn't come from here"):
        whoop.finish(conn, "code-1", "forged")
    url = whoop.start(conn)
    whoop.finish(conn, "code-1", dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"])
    s = whoop.status(conn)
    assert s["connected"] and s["profile"]["first_name"] == "Yadu"
    assert secrets.get("whoop.client_secret") == "s3cret"  # in the Keychain (memory in tests), not the catalog
    assert "s3cret" not in str(list(conn.execute("SELECT * FROM settings")))


@pytest.mark.parametrize("redirect, client_id, secret, message", [
    ("http://localhost:8780/callback", "c", "s", "must end in"),
    (REDIRECT, "", "s", "Client ID"),
    (REDIRECT, "c", None, "Client Secret"),
])
def test_setup_is_checked(conn, redirect, client_id, secret, message):
    with pytest.raises(ValueError, match=message):
        whoop.configure(conn, client_id, secret, redirect)


def test_sync_maps_whoop_to_readings(conn, fake):
    connect(conn)
    result = whoop.sync(conn)
    assert result["skipped"] == 0
    day16, day17 = "2026-10-16", "2026-10-17"
    assert round(health.day_total(conn, "total_energy", day16)) == 2500  # 10,460 kJ
    assert health.day_total(conn, "steps", day16) == 9100
    assert health.day_total(conn, "steps", day17) == 2300
    assert health.latest(conn, "recovery")["value"] == 71  # type: ignore[index]
    assert health.latest(conn, "hrv_rmssd")["value"] == 62.5  # type: ignore[index]
    assert health.latest(conn, "hrv") is None  # Apple's SDNN isn't mixed with WHOOP's RMSSD
    sleep = health.latest(conn, "sleep")
    assert sleep and sleep["day"] == day17 and sleep["value"] == 7.0  # filed under the morning, nap left out
    assert health.latest(conn, "weight")["value"] == 80.0  # type: ignore[index]
    assert health.latest(conn, "height")["value"] == 178.0  # type: ignore[index]
    assert health.latest(conn, "sleep_consistency")["value"] == 82  # type: ignore[index]
    w = conn.execute("SELECT * FROM workouts").fetchone()
    assert whoop.sport_name("rock-climbing") == "Rock climbing" and whoop.sport_name(None) == "Other activity"
    assert w["sport"] == "Weightlifting" and w["minutes"] == 60 and round(w["kcal"]) == 400 and w["day"] == day16
    assert json.loads(w["zones"]) == {"0": 0, "1": 15.0, "2": 25.0, "3": 15.0, "4": 5.0, "5": 0}
    paths = [urllib.parse.urlsplit(u).path for m, u, _ in fake.calls if m == "GET"]
    assert paths.count("/developer/v2/cycle") == 2  # followed next_token
    # a second sync stores no new weight reading unless the weight changed
    whoop.sync(conn)
    assert conn.execute("SELECT COUNT(*) FROM health_samples WHERE type = 'weight'").fetchone()[0] == 1
    fake.weight = 79.4
    whoop.sync(conn)
    assert health.latest(conn, "weight")["value"] == 79.4  # type: ignore[index]


def test_a_whoop_day_belongs_to_the_waking_day(conn):
    late = {"id": 5, "start": "2026-10-16T18:20:00.000Z", "end": None, "timezone_offset": "+05:30",  # 23:50 local
            "score_state": "SCORED", "step_count": 2624, "score": {"strain": 10.3, "kilojoule": 5016.0}}
    early = {"id": 4, "start": "2026-10-15T18:31:00.000Z", "end": "2026-10-16T18:20:00.000Z",  # 00:01 local
             "timezone_offset": "+05:30", "score_state": "SCORED", "step_count": 5181,
             "score": {"strain": 1.7, "kilojoule": 7365.0}}
    rec = {"cycle_id": 5, "score_state": "SCORED", "score": {"recovery_score": 58}}
    health.store(conn, whoop.readings([late, early], [rec], []))
    assert health.day_total(conn, "strain", "2026-10-17") == 10.3  # started last night: today's
    assert health.day_total(conn, "strain", "2026-10-16") == 1.7
    assert health.latest(conn, "recovery")["day"] == "2026-10-17"  # type: ignore[index]


def test_wrongly_filed_readings_are_refiled_on_the_next_sync(conn):
    reading = {"type": "strain", "value": 10.3, "unit": "", "start": "2026-10-16T23:50:00+05:30", "source": "WHOOP",
               "daily": True}
    health.store(conn, [reading])
    assert health.day_total(conn, "strain", "2026-10-16") == 10.3
    health.store(conn, [{**reading, "day": "2026-10-17"}])
    assert health.day_total(conn, "strain", "2026-10-16") is None
    assert health.day_total(conn, "strain", "2026-10-17") == 10.3
    assert conn.execute("SELECT COUNT(*) FROM health_samples").fetchone()[0] == 1


def test_two_whoop_days_on_one_date_add_up(conn):
    for start, value in (("2026-10-12T00:58:00+05:30", 1567.0), ("2026-10-12T22:03:00+05:30", 1931.0)):
        health.store(conn, [{"type": "total_energy", "value": value, "unit": "kcal", "start": start, "source": "WHOOP",
                             "daily": True, "day": "2026-10-13"}])
    assert health.day_total(conn, "total_energy", "2026-10-13") == 3498.0


def test_refresh_rotates_and_401_retries_once(conn, fake):
    connect(conn)
    t = whoop._tokens()
    assert t
    expired = {"access_token": "a1", "refresh_token": "r1", "expires_at": time.time() - 5}
    secrets.put("whoop.tokens", json.dumps(expired))
    whoop.get(conn, "/v2/user/profile/basic")
    assert whoop._tokens()["refresh_token"] == "r2"  # type: ignore[index]
    fake.reject_next_get = True
    whoop.get(conn, "/v2/user/profile/basic")
    assert whoop._tokens()["refresh_token"] == "r3"  # type: ignore[index]
    refreshes = [f for m, u, f in fake.calls if u == whoop.TOKEN_URL and f.get("grant_type") == "refresh_token"]
    assert [f["refresh_token"] for f in refreshes] == ["r1", "r2"]


def test_a_dead_refresh_token_disconnects(conn, fake):
    connect(conn)
    fake.refresh_broken = True
    secrets.put("whoop.tokens", '{"access_token": "a1", "refresh_token": "r1", "expires_at": 0}')
    with pytest.raises(whoop.WhoopError, match="Connect again"):
        whoop.sync(conn)
    s = whoop.status(conn)
    assert not s["connected"] and "Connect again" in (s["last_error"] or "")


def test_disconnect_keeps_the_data(conn, fake):
    connect(conn)
    whoop.sync(conn)
    whoop.disconnect(conn)
    assert not whoop.status(conn)["connected"] and whoop.status(conn)["configured"]
    assert health.latest(conn, "recovery")
    assert whoop.sync(conn) == {"skipped": "not connected"}


def test_api_round_trip(client, conn, fake):
    setup = {"client_id": "client-1", "client_secret": "s3cret", "redirect_uri": REDIRECT}
    r = client.post("/api/whoop/setup", json=setup)
    assert r.status_code == 200, r.text
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.json()["auth_url"]).query))["state"]
    back = client.get("/api/whoop/callback", params={"code": "code-1", "state": state}, follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/settings/whoop?connected=1"
    queued = [j for j in jobs.recent(conn) if j["kind"] == "whoop.sync"]
    assert queued and queued[0]["payload"] == {"full": True}
    jobs.run_one(conn)
    assert client.get("/api/whoop/status").json()["last_sync_at"]
    denied = client.get("/api/whoop/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert "error=access_denied" in denied.headers["location"]
    assert client.post("/api/whoop/disconnect").json()["connected"] is False
    assert client.post("/api/whoop/sync").status_code == 400


def test_targets_use_whoop_energy_when_health_has_none(conn):
    targets.save_profile(conn, {"sex": "male", "birth_year": 1993, "height_cm": 178})
    health.store(conn, [{"type": "weight", "value": 80, "unit": "kg", "start": "2026-10-15T07:00:00+05:30"}])
    health.store(conn, [{"type": "total_energy", "value": 2600, "unit": "kcal", "source": "WHOOP", "daily": True,
                         "start": "2026-10-16T07:00:00+05:30", "end": "2026-10-17T07:00:00+05:30"}])
    t = targets.for_day(conn, "2026-10-16")
    b = 10 * 80 + 6.25 * 178 - 5 * 33 + 5  # 1752.5 over a 24-hour WHOOP day
    assert t["activity_source"] == "WHOOP" and t["active_kcal"] == round(2600 - b)
    assert t["kcal"] == round((b * 1.2 + (2600 - b) * 0.5 - 275) / 10) * 10
    assert "(WHOOP)" in t["kcal_how"]
    health.store(conn, [{"type": "active_energy", "value": 500, "unit": "kcal", "daily": True,
                         "start": "2026-10-16T00:00:00+05:30"}])
    t = targets.for_day(conn, "2026-10-16")
    assert t["activity_source"] == "Apple Health" and t["active_kcal"] == 500


def test_periodic_sync_is_harmless_when_not_connected(conn):
    jobs.enqueue(conn, "whoop.sync")
    jobs.run_one(conn)
    assert jobs.recent(conn)[0]["result"] == {"skipped": "not connected"}
    assert db.get_setting(conn, "whoop.last_sync_at") is None


def test_whoop_data_reaches_the_ai_only_when_the_owner_chooses(client, conn):
    from hobbes import context

    from .test_insights import seed

    assert "health" in context.snapshot(conn)  # no WHOOP data yet: Apple Health's may go
    seed(conn, "recovery", {n: 60 for n in range(0, 10)}, "%")  # stored with source WHOOP
    snap = context.snapshot(conn)
    assert "health" not in snap and "health" in snap["not_available"]
    job = client.post("/api/health/coach", json={"today": "2026-10-17"}).json()["job_id"]
    jobs.run_one(conn)
    assert "isn't shared with the AI" in client.get(f"/api/jobs/{job}").json()["error"]
    assert client.put("/api/whoop/share", json={"share_with_ai": True}).json()["share_with_ai"] is True
    assert "health" in context.snapshot(conn)
