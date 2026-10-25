import { useState } from "react";
import { api, useLoad } from "../../api/client";
import { BarChart } from "../../components/Charts";
import type { Bar } from "../../components/Charts";
import { Segmented } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { addDays, dayLabel, parseDay, today } from "../../lib/dates";
import { whole } from "../../lib/format";

const RANGES = [{ value: 7, label: "W" }, { value: 30, label: "M" }, { value: 90, label: "3M" }];

export function HistoryPage() {
  const [range, setRange] = useState(7);
  const [showAll, setShowAll] = useState(false);
  const end = today();
  const start = addDays(end, -(range - 1));
  const h = useLoad(() => api.GET("/api/diet/history", { params: { query: { start, end } } }), [start, end]);

  const days = Array.from({ length: range }, (_, i) => addDays(start, i));
  const byDay = new Map((h.data?.days ?? []).map((d) => [d.day, d]));
  const label = (d: string) => parseDay(d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const kcal: Bar[] = days.map((d) => ({ key: d, label: label(d), value: byDay.get(d)?.kcal ?? null, target: byDay.get(d)?.target_kcal ?? null }));
  const protein: Bar[] = days.map((d) => ({ key: d, label: label(d), value: byDay.get(d)?.protein ?? null, target: byDay.get(d)?.target_protein ?? null }));
  const logged = [...(h.data?.days ?? [])].reverse();
  const span = `${parseDay(start).toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${parseDay(end).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;

  return (
    <Page title="History" backTo="/diet" backLabel="Diet">
      <div style={{ marginBottom: 16 }}>
        <Segmented label="Range" value={range} options={RANGES} onChange={setRange} />
      </div>
      <p className="footnote secondary" style={{ margin: "0 4px 12px" }}>{span}. Touch a column to read that day; days you didn't log are left empty.</p>
      {h.error && <div className="notice error">{h.error}</div>}

      <Section header="Calories">
        <BarChart bars={kcal} hue="var(--energy)" unit="kcal" title="Calories eaten each day" summaryLabel="DAILY AVERAGE" />
      </Section>
      <Section header="Protein">
        <BarChart bars={protein} hue="var(--protein)" unit="g" title="Protein eaten each day" summaryLabel="DAILY AVERAGE" height={140} />
      </Section>
      <Section header="All data">
        <List>
          {logged.length === 0 && <Row title={<span className="secondary">Nothing logged in this period.</span>} />}
          {(showAll ? logged : logged.slice(0, 7)).map((d) => (
            <Row key={d.day} title={dayLabel(d.day)} to={d.day === end ? "/diet" : `/diet?day=${d.day}`}
              sub={`${whole(d.protein)} g protein`}
              value={<span className="num">{whole(d.kcal)}{d.target_kcal ? ` / ${whole(d.target_kcal)}` : ""} kcal</span>} />
          ))}
          {logged.length > 7 && <Row title={showAll ? "Show Fewer" : `Show All ${logged.length} Days`} tone="tinted" onClick={() => setShowAll(!showAll)} chevron={false} />}
        </List>
      </Section>
    </Page>
  );
}
