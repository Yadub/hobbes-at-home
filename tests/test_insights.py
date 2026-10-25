import json
from datetime import date, timedelta

from hobbes import health, insights, jobs, whoop
from hobbes.diet import targets

TODAY = "2026-10-17"


def days_back(n: int) -> str:
    return (date.fromisoformat(TODAY) - timedelta(days=n)).isoformat()


def seed(conn, kind, values_by_offset, unit="", daily=False):
    health.store(conn, [{"type": kind, "value": v, "unit": unit, "start": f"{days_back(n)}T08:00:00+05:30",
                         "source": "WHOOP", "daily": daily} for n, v in values_by_offset.items()])


def test_a_week_against_the_four_before(conn):
    seed(conn, "resting_hr", {**{n: 58 for n in range(7, 35)}, **{n: 55 for n in range(0, 7)}}, "bpm")
    seed(conn, "hrv_rmssd", {**{n: 60 for n in range(7, 35)}, **{n: 60.5 for n in range(0, 7)}}, "ms")
    m = insights.metric(conn, "resting_hr", TODAY)
    assert m["recent"] == 55 and m["baseline"] == 58 and m["status"] == "better"  # lower is better
    assert len(m["points"]) == 30
    h = insights.metric(conn, "hrv", TODAY)
    assert h["source"] == "hrv_rmssd" and h["status"] == "same"  # under 3%: no real change


def test_steps_week_ends_yesterday(conn):
    seed(conn, "steps", {**{n: 8000 for n in range(1, 35)}, 0: 500}, "count", daily=True)
    m = insights.metric(conn, "steps", TODAY)
    assert m["recent"] == 8000  # today's half-finished count isn't averaged in


def test_weight_follows_the_diet_goal(conn):
    seed(conn, "weight", {**{n: 76 for n in range(7, 35)}, **{n: 75 for n in range(0, 7)}}, "kg")
    targets.save_goal(conn, {"goal": "lose", "rate": 0.25})
    assert insights.metric(conn, "weight", TODAY)["status"] == "better"
    targets.save_goal(conn, {"goal": "gain", "rate": 0.25})
    assert insights.metric(conn, "weight", TODAY)["status"] == "worse"
    targets.save_goal(conn, {"goal": "maintain"})
    assert insights.metric(conn, "weight", TODAY)["status"] == "worse"  # moved a kilo while maintaining


def test_no_data_is_plain(conn):
    m = insights.metric(conn, "recovery", TODAY)
    assert m["recent"] is None and m["status"] == "none" and m["points"] == []


def workout(i, day, sport, minutes, zones_min):
    start = f"{day}T07:00:00.000Z"
    end_h = 7 + minutes // 60
    end = f"{day}T{end_h:02d}:{minutes % 60:02d}:00.000Z"
    return {"id": f"w{i}", "start": start, "end": end, "timezone_offset": "+00:00",
            "sport_name": sport, "score_state": "SCORED",
            "score": {"strain": 10, "kilojoule": 1000, "zone_durations": {
                k: v * 60000 for k, v in zip(whoop._ZONES, zones_min, strict=True)}}}


def test_activities_and_drivers(conn):
    records = []
    for i in range(8):  # two strength sessions a week for four weeks, 40 min in zones 2-3 and 10 in 4-5 each
        records.append(workout(i, days_back(i * 3 + 1), "weightlifting", 60, [0, 10, 25, 15, 8, 2]))
    records.append(workout(99, days_back(2), "running", 30, [0, 0, 5, 10, 12, 3]))
    whoop.store_workouts(conn, records)
    seed(conn, "sleep", {n: 6.8 for n in range(0, 28)}, "h")
    seed(conn, "sleep_consistency", {n: 84 for n in range(0, 28)}, "%")
    seed(conn, "steps", {n: 9000 for n in range(0, 28)}, "count", daily=True)

    a = insights.activities(conn, TODAY)
    assert a["by_sport"][0]["sport"] == "Weightlifting" and a["by_sport"][0]["sessions"] == 8
    assert a["totals"]["last_30"]["sessions"] == 9

    d = {x["key"]: x for x in insights.drivers(conn, TODAY)}
    assert d["sleep_hours"]["status"] == "close" and d["sleep_consistency"]["status"] == "met"
    assert d["strength"]["value"] == 2.0 and d["strength"]["status"] == "met"
    # (8 × 40 + 15) moderate and (8 × 10 + 15) vigorous minutes over four weeks; vigorous counts double
    assert d["cardio"]["value"] == round((8 * 40 + 15) / 4 + 2 * (8 * 10 + 15) / 4)
    assert d["steps"]["status"] == "met"


def test_drivers_count_only_the_weeks_with_data(conn):
    # WHOOP sent data for the last two weeks only: two strength sessions a week is two, not one
    whoop.store_workouts(conn, [workout(i, days_back(i * 3 + 1), "weightlifting", 60, [0, 10, 25, 15, 8, 2])
                                for i in range(4)])
    seed(conn, "sleep", {n: 7.5 for n in range(0, 14)}, "h")
    d = {x["key"]: x for x in insights.drivers(conn, TODAY)}
    assert d["strength"]["value"] == 2.0 and d["strength"]["status"] == "met"


def test_coach_reads_the_overview_and_is_kept(client, conn, monkeypatch, scratch):
    whoop.set_shared_with_ai(conn, True)
    seed(conn, "recovery", {n: 60 for n in range(0, 20)}, "%")
    advice = {"summary": "Recovery held steady.", "focus": [
        {"title": "Sleep 30 minutes longer", "why": "6.8 h on average", "how": "Lights out by 23:00",
         "impact": "high"}]}
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(advice))
    job_id = client.post("/api/health/coach", json={"today": TODAY}).json()["job_id"]
    jobs.run_one(conn)
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    prompt = json.loads((scratch / "codex.log").read_text().splitlines()[-1])["prompt"]
    assert "WHOOP Age" in prompt and '"recovery"' in prompt and '"points"' not in prompt
    o = client.get("/api/health/overview", params={"today": TODAY}).json()
    assert o["coach"]["focus"][0]["title"] == "Sleep 30 minutes longer"
    assert {m["key"] for m in o["metrics"]} == set(insights.keys())


def test_metric_detail_api(client, conn):
    seed(conn, "sleep", {n: 7.0 for n in range(0, 60)}, "h")
    r = client.get("/api/health/metric/sleep", params={"today": TODAY, "days": 60}).json()
    assert len(r["points"]) == 60 and r["recent"] == 7.0
    assert client.get("/api/health/metric/nope", params={"today": TODAY}).status_code == 404
