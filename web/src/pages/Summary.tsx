import { useEffect } from "react";
import type { CSSProperties } from "react";
import { api, useLoad } from "../api/client";
import { Meter, Ring } from "../components/Controls";
import { ChecklistIcon, ChevronRight, CpuIcon, FlameIcon, ForkKnifeIcon, GearIcon, HeartIcon } from "../components/Icons";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";
import { SessionsCard } from "./assistant/Sessions";
import { longDate, today } from "../lib/dates";
import { oneDp, whole } from "../lib/format";
import { Link } from "../router";

const hue = (h: string, text: string) => ({ "--hue": h, "--hue-text": text }) as CSSProperties;

type Window = { used_percent: number; window_minutes: number | null; resets_at: number | null } | null | undefined;

function resets(at: number | null | undefined) {
  if (!at) return "";
  const d = new Date(at * 1000);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
}

/** What's left of one Codex usage window, as a meter that empties as it's used. */
function Allowance({ label, w }: { label: string; w: Window }) {
  if (!w) return null;
  const left = Math.max(0, 100 - w.used_percent);
  const low = left < 20;
  return (
    <div className="meter" style={{ "--hue": low ? "var(--caution)" : "var(--assistant)" } as CSSProperties}>
      <div className="meter-top">
        <span className="meter-label">{label}</span>
        <span className="meter-value num"><strong>{Math.round(left)}%</strong> left{w.resets_at ? ` · resets ${resets(w.resets_at)}` : ""}</span>
      </div>
      <div className="meter-track" role="meter" aria-label={`${label}: ${Math.round(left)}% left`} aria-valuenow={Math.round(left)}
        aria-valuemin={0} aria-valuemax={100}>
        <div className="meter-fill" style={{ width: `${left}%` }} />
      </div>
    </div>
  );
}

function AICard() {
  const u = useLoad(() => api.GET("/api/ai/usage"));
  const st = useLoad(() => api.GET("/api/status"));
  const ai = st.data?.ai;
  const { reload } = u;
  useEffect(() => {
    const t = window.setInterval(reload, 120_000);
    return () => window.clearInterval(t);
  }, [reload]);
  const d = u.data;
  return (
    <Link to="/settings" className="card summary-last" style={hue("var(--assistant)", "var(--label)")}>
      <div className="card-head">
        <span className="card-label"><CpuIcon />{ai?.name ?? "AI"}</span>
        <span className="card-meta">{d?.plan ? `${d.plan.charAt(0).toUpperCase()}${d.plan.slice(1)} plan` : ""}<ChevronRight /></span>
      </div>
      {d?.available ? (
        <div style={{ display: "grid", gap: 12 }}>
          <Allowance label="This session (5 hours)" w={d.session} />
          <Allowance label="This week" w={d.week} />
        </div>
      ) : (
        <p className="subhead secondary" style={{ margin: 0 }}>
          {ai && !ai.signed_in ? ai.detail : d ? (d.detail ?? "Usage isn't available right now.") : " "}
        </p>
      )}
    </Link>
  );
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <div className="caption secondary">{label}</div>
      <div className="value small">{value}{unit && <span className="unit">{unit}</span>}</div>
    </div>
  );
}

export function Summary() {
  const day = today();
  const diet = useLoad(() => api.GET("/api/diet/day", { params: { query: { day } } }), [day]);
  const hs = useLoad(() => api.GET("/api/health/summary"));

  const d = diet.data;
  const t = d?.targets;
  const latest = (type: string) => hs.data?.latest.find((r) => r.type === type && r.day === day);
  const active = latest("active_energy");
  const steps = latest("steps");
  const strain = latest("strain");
  const burned = latest("total_energy");
  const recovery = latest("recovery");
  const sleep = latest("sleep");
  const hrv = latest("hrv_rmssd") ?? latest("hrv");
  const rhr = latest("resting_hr");

  return (
    <Page title="Summary" eyebrow={longDate()}
      trailing={<Link to="/settings" className="bar-button" aria-label="Settings"><GearIcon /></Link>}>
      {diet.error && <div className="notice error">{diet.error}</div>}

      <h2 className="section-header big">Today</h2>
      {/* Two columns side by side on a wide screen, each card its own height; one column on a phone, in
          the order Diet, Activity, Recovery, AI, coding sessions. */}
      <div className="cards summary-cols">
        <div className="summary-col">
          <Link to="/diet" className="card" style={hue("var(--energy)", "var(--energy-text)")}>
            <div className="card-head">
              <span className="card-label"><ForkKnifeIcon />Diet</span>
              <span className="card-meta">{d ? `${d.meals.length} ${d.meals.length === 1 ? "meal" : "meals"}` : ""}<ChevronRight /></span>
            </div>
            {t?.ready && d ? (
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{ flex: 1, display: "grid", gap: 12 }}>
                  <div>
                    <div className="value">{whole(Math.abs(d.left.kcal ?? 0))}<span className="unit">kcal {(d.left.kcal ?? 0) < 0 ? "over" : "left"}</span></div>
                    <div className="subhead secondary num">{whole(d.eaten.kcal)} of {whole(t.kcal)} eaten</div>
                  </div>
                  <div style={hue("var(--protein)", "")}><Meter label="Protein" hue="var(--protein)" value={d.eaten.protein} max={t.protein} /></div>
                </div>
                <Ring value={d.eaten.kcal} max={t.kcal ?? 0} hue="var(--energy)" size={84} stroke={11}
                  label={`${whole(d.eaten.kcal)} of ${whole(t.kcal)} kcal eaten`} />
              </div>
            ) : (
              <p className="subhead secondary" style={{ margin: 0 }}>
                {d ? "Set your goal to see what's left for today." : " "}
              </p>
            )}
          </Link>

          <Link to="/health" className="card" style={hue("var(--activity)", "var(--activity-text)")}>
            <div className="card-head">
              <span className="card-label"><FlameIcon />Activity</span>
              <span className="card-meta">{strain || burned || active || steps ? "Today" : ""}<ChevronRight /></span>
            </div>
            {strain || burned || active || steps ? (
              <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                {strain && <Stat label="Strain" value={oneDp(strain.value)} />}
                {burned ? <Stat label="Energy burned" value={whole(burned.value)} unit="kcal" />
                  : active && <Stat label="Active energy" value={whole(active.value)} unit="kcal" />}
                {steps && <Stat label="Steps" value={whole(steps.value)} />}
              </div>
            ) : (
              <p className="subhead secondary" style={{ margin: 0 }}>Energy burned and steps appear here once Apple Health or WHOOP is connected.</p>
            )}
          </Link>

          {(recovery || sleep) && (
            <Link to="/health" className="card" style={hue("var(--heart)", "var(--heart-text)")}>
              <div className="card-head">
                <span className="card-label"><HeartIcon />Recovery</span>
                <span className="card-meta">Today<ChevronRight /></span>
              </div>
              <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                {recovery && <Stat label="Recovery" value={whole(recovery.value)} unit="%" />}
                {sleep && <Stat label="Sleep" value={`${Math.floor(sleep.value)}h ${Math.round((sleep.value % 1) * 60)}m`} />}
                {hrv && <Stat label="HRV" value={whole(hrv.value)} unit="ms" />}
                {rhr && <Stat label="Resting HR" value={whole(rhr.value)} unit="bpm" />}
              </div>
            </Link>
          )}

        </div>
        <div className="summary-col">
          <AICard />
          <SessionsCard />
        </div>
      </div>

      <Section header="Also here">
        <List>
          <Row icon={<ChecklistIcon />} tile="var(--assistant)" title="Hobbes AI" sub="Jobs researched for you" to="/assistant" />
        </List>
      </Section>
    </Page>
  );
}
