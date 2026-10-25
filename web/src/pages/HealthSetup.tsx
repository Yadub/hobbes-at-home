import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, useLoad } from "../api/client";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";
import { dayLabel } from "../lib/dates";
import { oneDp, whole } from "../lib/format";

const NAMES: Record<string, [string, (v: number) => string]> = {
  weight: ["Weight", (v) => `${oneDp(v)} kg`],
  body_fat: ["Body fat", (v) => `${oneDp(v)} %`],
  lean_mass: ["Lean body mass", (v) => `${oneDp(v)} kg`],
  height: ["Height", (v) => `${whole(v)} cm`],
  active_energy: ["Active energy", (v) => `${whole(v)} kcal`],
  resting_energy: ["Resting energy", (v) => `${whole(v)} kcal`],
  steps: ["Steps", (v) => whole(v)],
  sleep: ["Sleep", (v) => `${Math.floor(v)} h ${Math.round((v % 1) * 60)} min`],
  resting_hr: ["Resting heart rate", (v) => `${whole(v)} bpm`],
  hrv: ["Heart rate variability", (v) => `${whole(v)} ms`],
  hrv_rmssd: ["Heart rate variability (WHOOP)", (v) => `${whole(v)} ms`],
  total_energy: ["Energy burned", (v) => `${whole(v)} kcal`],
  strain: ["Strain", (v) => oneDp(v)],
  recovery: ["Recovery", (v) => `${whole(v)} %`],
};

function Steps({ items }: { items: ReactNode[] }) {
  return (
    <ol className="subhead" style={{ margin: 0, padding: "12px 16px 12px 34px", display: "grid", gap: 8, background: "var(--surface)", borderRadius: 10 }}>
      {items.map((x, i) => <li key={i} style={{ paddingLeft: 2 }}>{x}</li>)}
    </ol>
  );
}

export function HealthSetup() {
  const s = useLoad(() => api.GET("/api/health/summary"));
  const url = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = s.data?.endpoint ?? "";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard access needs HTTPS; until then, select the address so it can be copied by hand.
      url.current?.select();
      document.execCommand("copy");
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  const last = s.data?.last_sync;
  return (
    <Page title="Apple Health" backTo="/settings" backLabel="Settings">
      <Section header="Received" footer={last ? `Last sent ${new Date(last.at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}: ${last.stored} ${last.stored === 1 ? "reading" : "readings"} kept${last.skipped ? `, ${last.skipped} not used` : ""}.` : "Nothing has arrived yet."}>
        <List>
          {(s.data?.latest ?? []).map((r) => {
            const [name, fmt] = NAMES[r.type] ?? [r.type, (v: number) => String(v)];
            return <Row key={r.type} title={name} sub={`${dayLabel(r.day)}${r.source ? ` · ${r.source}` : ""}`} value={fmt(r.value)} />;
          })}
          {s.data && s.data.latest.length === 0 && <Row title={<span className="secondary">No readings yet</span>} />}
        </List>
      </Section>

      <Section header="Address for your iPhone" footer="Your iPhone needs Tailscale switched on. In the Tailscale app, turn on VPN On Demand so it connects by itself.">
        <List>
          <div className="row">
            <input ref={url} className="field left num" readOnly value={s.data?.endpoint ?? ""} aria-label="Address" onFocus={(e) => e.target.select()} />
            <button type="button" className="button small tinted" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          </div>
        </List>
      </Section>

      <Section header="Set up with Health Auto Export" footer="iPhone only lets apps read Health while it's unlocked, so new readings arrive when you use your phone.">
        <Steps items={[
          <>Install <strong>Health Auto Export</strong> from the App Store and start Premium (about $25 once, or $7 a year; 7-day free trial). It sends your data only to the address you give it.</>,
          <>Let it read: Steps, Active Energy, Resting Energy, Weight, Body Fat Percentage, Lean Body Mass, Height, Resting Heart Rate, Heart Rate Variability and Sleep.</>,
          <>Tap <strong>Automations</strong> › <strong>New</strong> › <strong>REST API</strong>. Paste the address above as the URL.</>,
          <>Data Type: <strong>Health Metrics</strong>. Choose the metrics above. Format: <strong>JSON</strong>, Export Version <strong>2</strong>.</>,
          <>Turn on <strong>Summarize Data</strong> with Time Grouping <strong>Days</strong>, and <strong>Batch Requests</strong>. Date Range: Default. Sync every hour.</>,
          <>For your history, open the automation and use <strong>Manual Export</strong> for the last 90 days.</>,
          <>To keep it current, add Health Auto Export's widget, or in Shortcuts make an automation: when an app you open every day is opened, run Health Auto Export's <strong>Run Automation</strong>.</>,
        ]} />
      </Section>

      <Section footer="Both ways can send to the same address; readings for the same time are stored once.">
        <details className="card">
          <summary className="headline" style={{ cursor: "pointer" }}>Free instead: a Shortcut</summary>
          <div className="subhead secondary" style={{ display: "grid", gap: 8, marginTop: 10 }}>
            <p style={{ margin: 0 }}>A Shortcut can send the same readings without another app. It takes longer to build, and it can't send workouts.</p>
            <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }}>
              <li>For Steps, Active Energy and Resting Energy: <em>Find Health Samples</em> (last 2 days, Group By Day, unit count or kcal), then <em>Repeat with Each</em> with a <em>Text</em>:{" "}
                <code>{'{"m":"step_count","u":"count","agg":"day","start":"[Start Date, ISO 8601]","v":"[Value]"}'}</code>, then <em>Add to Variable</em> Lines.</li>
              <li>For Weight, Body Fat Percentage and Lean Body Mass: the same without Group By, and without <code>"agg"</code>.</li>
              <li><em>Combine Text</em> Lines with New Lines.</li>
              <li><em>Get Contents of URL</em>: the address above, Method POST, Request Body JSON with a Text field <code>lines</code> set to the combined text.</li>
              <li>In Automations: when an app you open daily is opened, run this Shortcut, set to run immediately.</li>
            </ol>
          </div>
        </details>
      </Section>
    </Page>
  );
}
