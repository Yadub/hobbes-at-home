import { useState } from "react";
import type { CSSProperties } from "react";
import { api, problemText, useLoad, waitForJob } from "../../api/client";
import type { HealthMetric, HealthOverview } from "../../api/client";
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle, HalfCircle, Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { dayLabel, longDate, today } from "../../lib/dates";
import { whole } from "../../lib/format";
import { Link } from "../../router";

export const HUES: Record<string, [string, string]> = {
  recovery: ["var(--heart)", "var(--heart-text)"], hrv: ["var(--heart)", "var(--heart-text)"],
  resting_hr: ["var(--heart)", "var(--heart-text)"], sleep: ["var(--sleep)", "var(--sleep-text)"],
  sleep_consistency: ["var(--sleep)", "var(--sleep-text)"], strain: ["var(--activity)", "var(--activity-text)"],
  steps: ["var(--activity)", "var(--activity-text)"], energy: ["var(--activity)", "var(--activity-text)"],
  weight: ["var(--body)", "var(--body-text)"],
};

export function fmt(v: number | null | undefined, decimals: number) {
  if (v === null || v === undefined) return "–";
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** A 30-day trend in the quiet de-emphasis grey, the latest day marked in the measure's colour. */
function Sparkline({ points }: { points: { day: string; value: number }[] }) {
  if (points.length < 2) return <div className="spark" />;
  const w = 120, h = 28, pad = 3;
  const vals = points.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const y = (v: number) => pad + (hi === lo ? 0.5 : 1 - (v - lo) / (hi - lo)) * (h - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const last = points[points.length - 1]!;
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path className="line" d={d} vectorEffect="non-scaling-stroke" />
      <circle className="dot" cx={x(points.length - 1)} cy={y(last.value)} r={3.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Delta({ m }: { m: HealthMetric }) {
  if (m.change === null || m.pct === null) return <span className="delta none">Not enough data yet</span>;
  const up = m.change > 0;
  const words = m.status === "better" ? "better" : m.status === "worse" ? "worse" : m.status === "same" ? "steady" : "";
  const size = m.key === "weight" ? `${fmt(Math.abs(m.change), 1)} kg` : `${Math.abs(m.pct).toFixed(0)}%`;
  return (
    <span className={`delta ${m.status}`} aria-label={`${up ? "Up" : "Down"} ${size} on the four weeks before${words ? `, ${words}` : ""}`}>
      {m.status === "same" ? null : up ? <ArrowUp /> : <ArrowDown />}
      {m.status === "same" ? "Steady" : `${size}${words ? ` · ${words}` : ""}`}
    </span>
  );
}

function Tile({ m }: { m: HealthMetric }) {
  const [hue, text] = HUES[m.key] ?? ["var(--tint)", "var(--label)"];
  return (
    <Link to={`/health/${m.key}`} className="tile" style={{ "--hue": hue, "--hue-text": text } as CSSProperties}>
      <span className="tile-label">{m.label}</span>
      <span className="value">{fmt(m.recent, m.decimals)}{m.unit && <span className="unit">{m.unit}</span>}</span>
      <Delta m={m} />
      <Sparkline points={m.points} />
    </Link>
  );
}

function StatusMark({ status }: { status: string }) {
  const [icon, words] = status === "met" ? [<CheckCircle key="i" />, "On track"] : status === "close" ? [<HalfCircle key="i" />, "Close"]
    : status === "below" ? [<AlertCircle key="i" />, "Below"] : [null, "No data"];
  return <span className={`status ${status}`}>{icon}{words}</span>;
}

function minutes(m: number | null | undefined) {
  if (!m) return "0 min";
  const h = Math.floor(m / 60);
  return h ? `${h} h ${Math.round(m % 60)} min` : `${Math.round(m)} min`;
}

function CoachCard({ o, reload }: { o: HealthOverview; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const c = o.coach;

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/health/coach", { body: { today: o.today } });
      if (err) throw new Error(problemText(err));
      const job = await waitForJob(data.job_id, 300_000);
      if (job.status === "failed") throw new Error(job.error ?? "No advice this time.");
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No advice this time.");
    }
    setBusy(false);
  }

  return (
    <Section header="Focus" footer={c ? `Written by the AI from your own numbers on ${new Date(c.at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}. General guidance, not medical advice.` : "The AI reads your trends, activities and the factors below, and picks what would help most. General guidance, not medical advice."}>
      <div className="card focus">
        {error && <p className="footnote danger" style={{ margin: 0 }}>{error}</p>}
        {c ? (
          <>
            <p className="callout" style={{ margin: 0 }}>{c.summary}</p>
            <ol>
              {c.focus.map((f) => (
                <li key={f.title}>
                  <span className="headline">{f.title}</span><span className="impact">{f.impact} impact</span>
                  <p className="subhead secondary" style={{ margin: "2px 0 0" }}>{f.why}</p>
                  <p className="subhead" style={{ margin: "4px 0 0" }}>{f.how}</p>
                </li>
              ))}
            </ol>
          </>
        ) : null}
        <button className={`button ${c ? "gray small" : ""}`} style={{ justifySelf: "start" }} onClick={ask} disabled={busy}>
          {busy ? <><Spinner label="Thinking" />Thinking…</> : c ? "Ask Again" : "What Should I Focus On?"}
        </button>
      </div>
    </Section>
  );
}

export function HealthPage() {
  const day = today();
  const o = useLoad(() => api.GET("/api/health/overview", { params: { query: { today: day } } }), [day]);
  const data = o.data;
  const a = data?.activities;

  return (
    <Page title="Health" eyebrow={longDate()}>
      {o.error && <div className="notice error">{o.error}</div>}
      {data && (
        <>
          <p className="footnote secondary" style={{ margin: "-4px 4px 12px" }}>Your last 7 days against the 4 weeks before.</p>
          <div className="tiles">{data.metrics.filter((m) => m.recent !== null || m.latest).map((m) => <Tile key={m.key} m={m} />)}</div>

          <CoachCard o={data} reload={o.reload} />

          <Section header="WHOOP Age factors" footer="WHOOP doesn't share WHOOP Age itself with other apps, so these are the everyday factors it's built from, over the last 4 weeks, against public guidance (sleep: AASM; activity and strength: WHO). Zone minutes count logged workouts only. VO2 max and lean body mass aren't available from WHOOP.">
            <List>
              {data.drivers.map((d) => (
                <Row key={d.key} title={d.label}
                  sub={`${d.value === null ? "No data yet" : `${d.value >= 100 ? whole(d.value) : fmt(d.value, Number.isInteger(d.value) ? 0 : 1)} ${d.unit}`} · aim ${d.aim}${d.detail ? `. ${d.detail}` : ""}`}
                  trailing={<StatusMark status={d.status} />} />
              ))}
            </List>
          </Section>

          {a && (
            <Section header="Activities, last 30 days" footer={`${a.totals.last_30?.sessions ?? 0} workouts, ${minutes(a.totals.last_30?.minutes)} in all; the 30 days before: ${a.totals.previous_30?.sessions ?? 0} workouts, ${minutes(a.totals.previous_30?.minutes)}.`}>
              <List>
                {a.by_sport.length === 0 && <Row title={<span className="secondary" style={{ whiteSpace: "normal" }}>No workouts logged on WHOOP in the last 30 days.</span>} />}
                {a.by_sport.map((s) => (
                  <Row key={s.sport} title={s.sport} sub={`${s.sessions} ${s.sessions === 1 ? "session" : "sessions"}${s.strain ? ` · average strain ${s.strain}` : ""}`}
                    value={minutes(s.minutes)} />
                ))}
              </List>
            </Section>
          )}
          {a && a.recent.length > 0 && (
            <Section header="Recent workouts">
              <List>
                {a.recent.map((w) => (
                  <Row key={w.start} title={w.sport}
                    sub={`${dayLabel(w.day)} · ${minutes(w.minutes)}${w.strain ? ` · strain ${w.strain.toFixed(1)}` : ""}${w.avg_hr ? ` · ${whole(w.avg_hr)} bpm average` : ""}`}
                    value={w.kcal ? `${whole(w.kcal)} kcal` : undefined} />
                ))}
              </List>
            </Section>
          )}
        </>
      )}
    </Page>
  );
}
