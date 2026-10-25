import { useState } from "react";
import { api, useLoad } from "../../api/client";
import type { DrinksSpan, DrinksView } from "../../api/client";
import { Segmented } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { today } from "../../lib/dates";
import { oneDp, whole } from "../../lib/format";

type Guide = DrinksView["reference"]["caffeine"];

/** You against the aim and the typical figures, on one scale: the bar is you, the line is the aim, the dots
 *  are the typical figures (named in the rows below). */
function Scale({ you, guide, colour }: { you: number; guide: Guide; colour: string }) {
  const top = Math.max(guide.aim * 1.25, you * 1.1, ...guide.typical.map((t) => t.value * 1.1));
  const at = (v: number) => `${Math.min(100, (v / top) * 100)}%`;
  return (
    <div aria-hidden="true" style={{ position: "relative", height: 14, borderRadius: 7, background: "var(--fill-3)", margin: "14px 0 6px" }}>
      <div style={{ position: "absolute", inset: "0 auto 0 0", width: at(you), borderRadius: 7, background: colour }} />
      {guide.typical.map((t) => (
        <span key={t.label} style={{ position: "absolute", top: 4, left: `calc(${at(t.value)} - 3px)`, width: 6, height: 6, borderRadius: 3, background: "var(--label-2)" }} />
      ))}
      <span style={{ position: "absolute", top: -4, bottom: -4, left: `calc(${at(guide.aim)} - 1px)`, width: 2, borderRadius: 1, background: "var(--label)" }} />
    </div>
  );
}

function Verdict({ over }: { over: boolean }) {
  return <span className="footnote" style={{ color: over ? "var(--caution)" : "var(--good)", fontWeight: 600 }}>{over ? "Above the aim" : "Within the aim"}</span>;
}

function Caffeine({ s, guide }: { s: DrinksSpan; guide: Guide }) {
  if (s.caffeine_per_day === null || s.caffeine_per_day === undefined) return null;
  const v = s.caffeine_per_day;
  return (
    <Section header="Caffeine" footer={`${guide.aim_text} Source: ${guide.aim_source}. Typical figures: ${guide.typical.map((t) => t.source).join("; ")}.`}>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 28 }}>
            <div><div className="caption secondary">A day</div><div className="value">{whole(v)}<span className="unit">mg</span></div></div>
            <div><div className="caption secondary">A week</div><div className="value">{whole(s.caffeine_per_week ?? v * 7)}<span className="unit">mg</span></div></div>
          </div>
          <Verdict over={v > guide.aim} />
        </div>
        <Scale you={v} guide={guide} colour="var(--energy)" />
      </div>
      <List>
        <Row title="Aim" value={`Up to ${whole(guide.aim)} mg a day`} sub={`${whole(guide.aim * 7)} mg a week`} />
        {guide.typical.map((t) => <Row key={t.label} title={t.label} value={`${whole(t.value)} mg a day`} />)}
        <Row title="Highest day" value={`${whole(s.caffeine_highest ?? 0)} mg`} />
        <Row title={`Days over ${whole(guide.aim)} mg`} value={`${s.caffeine_days_over} of ${s.logged_days}`} />
      </List>
    </Section>
  );
}

function Alcohol({ s, guide }: { s: DrinksSpan; guide: Guide }) {
  if (s.alcohol_units_per_week === null || s.alcohol_units_per_week === undefined) return null;
  const v = s.alcohol_units_per_week;
  return (
    <Section header="Alcohol, a week" footer={`A UK unit is 8 g of pure alcohol: about half a pint of 4% beer, or a 25 ml shot of a spirit. ${guide.aim_text} Source: ${guide.aim_source}. Typical figures: ${guide.typical.map((t) => t.source).join("; ")}.`}>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
          <div className="value">{oneDp(v)}<span className="unit">units</span></div>
          <Verdict over={v > guide.aim} />
        </div>
        <Scale you={v} guide={guide} colour="var(--assistant)" />
      </div>
      <List>
        <Row title="Aim" value={`Up to ${whole(guide.aim)} units`} />
        {guide.typical.map((t) => <Row key={t.label} title={t.label} value={`${oneDp(t.value)} units`} />)}
        <Row title="Heaviest day" value={`${oneDp(s.alcohol_heaviest_day ?? 0)} units`} />
        <Row title="Drink-free days" value={`${s.alcohol_free_days} of ${s.logged_days}`} />
      </List>
    </Section>
  );
}

export function DrinksPage() {
  const day = today();
  const v = useLoad(() => api.GET("/api/diet/drinks", { params: { query: { day } } }), [day]);
  const [span, setSpan] = useState<"week" | "month">("week");
  const d = v.data;
  const s = d ? d[span] : null;

  return (
    <Page title="Caffeine and Alcohol" backTo="/diet" backLabel="Diet">
      {v.error && <div className="notice error">{v.error}</div>}
      {d && !d.enabled && (
        <div className="notice">Tracking is off. Turn it on in Goal, Caffeine and Alcohol.</div>
      )}
      {d && s && (
        <>
          <div className="card" style={{ marginBottom: 22, display: "flex", gap: 28 }}>
            <div><div className="caption secondary">Caffeine today</div><div className="value small">{whole(d.today.caffeine)}<span className="unit">mg</span></div></div>
            <div><div className="caption secondary">Alcohol today</div><div className="value small">{oneDp(d.today.alcohol_units ?? 0)}<span className="unit">units</span></div></div>
          </div>

          <div style={{ marginBottom: 8 }}>
            <Segmented label="Period" value={span} onChange={setSpan}
              options={[{ value: "week", label: "Last 7 Days" }, { value: "month", label: "Last 30 Days" }]} />
          </div>
          <p className="footnote secondary" style={{ margin: "0 4px 22px" }}>
            {s.logged_days
              ? `Averaged over the ${s.logged_days === 1 ? "one day" : `${s.logged_days} days`} you logged food${s.logged_days < s.days ? `, of ${s.days}; days with nothing logged are left out` : ""}.${s.today_left_out ? " Today counts once it's over." : ""}`
              : "Nothing logged in this period yet."}
            {d.pending > 0 ? ` Working out caffeine and alcohol for ${d.pending} earlier ${d.pending === 1 ? "item" : "items"}…` : ""}
          </p>

          <Caffeine s={s} guide={d.reference.caffeine} />
          <Alcohol s={s} guide={d.reference.alcohol} />
        </>
      )}
    </Page>
  );
}
