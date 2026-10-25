import { useState } from "react";
import { api, useLoad } from "../../api/client";
import { BarChart, LineChart } from "../../components/Charts";
import { Segmented } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { dayLabel, parseDay, today } from "../../lib/dates";
import { Delta, fmt, HUES } from "./HealthPage";

const BARS = new Set(["steps", "strain", "energy"]);

/** One measure over time: the chart, how the last week compares, and every day's value. */
export function MetricPage({ metricKey }: { metricKey: string }) {
  const [days, setDays] = useState(30);
  const day = today();
  const m = useLoad(() => api.GET("/api/health/metric/{key}", { params: { path: { key: metricKey }, query: { today: day, days } } }),
    [metricKey, day, days]);
  const data = m.data;
  const hue = (HUES[metricKey] ?? ["var(--tint)"])[0];
  const label = (d: string) => parseDay(d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const unit = data?.unit ?? "";

  return (
    <Page title={data?.label ?? "Health"} backTo="/health" backLabel="Health">
      {m.error && <div className="notice error">{m.error}</div>}
      <div style={{ marginBottom: 16 }}>
        <Segmented label="Range" value={days} onChange={setDays}
          options={[{ value: 30, label: "M" }, { value: 90, label: "3M" }, { value: 365, label: "Y" }]} />
      </div>
      {data && (
        <>
          <div className="card" style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span className="caption secondary" style={{ fontWeight: 600, letterSpacing: "0.02em" }}>LAST 7 DAYS</span>
            <span className="value">{fmt(data.recent, data.decimals)}{unit && <span className="unit">{unit}</span>}</span>
            <Delta m={data} />
            {data.baseline !== null && <span className="footnote secondary">The 4 weeks before: {fmt(data.baseline, data.decimals)} {unit}</span>}
          </div>
          <Section header="Over time">
            {data.points.length === 0 ? <div className="card subhead secondary">No readings in this period.</div>
              : BARS.has(metricKey)
                ? <BarChart bars={data.points.map((p) => ({ key: p.day, label: label(p.day), value: p.value }))} hue={hue}
                  unit={unit} title={data.label} summaryLabel="DAILY AVERAGE" />
                : <LineChart points={data.points.map((p) => ({ key: p.day, label: label(p.day), value: p.value }))} hue={hue}
                  unit={unit} title={data.label} />}
          </Section>
          <Section header="All data" footer={data.source ? `From ${data.source.includes("hrv_rmssd") ? "WHOOP (RMSSD)" : "WHOOP and Apple Health"}.` : undefined}>
            <List>
              {[...data.points].reverse().slice(0, 60).map((p) => (
                <Row key={p.day} title={dayLabel(p.day)} value={`${fmt(p.value, data.decimals)} ${unit}`} />
              ))}
            </List>
          </Section>
        </>
      )}
    </Page>
  );
}
