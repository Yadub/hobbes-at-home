import { useState } from "react";
import { api, problemText, useLoad, waitForJob } from "../api/client";
import type { Backups } from "../api/client";
import { ArchiveIcon, BellIcon, BoltIcon, CheckIcon, GlobeIcon, HeartIcon, LockIcon, PeopleIcon, Spinner } from "../components/Icons";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";
import { hardReload } from "../lib/updates";

function since(iso: string | null | undefined) {
  if (!iso) return "Not yet";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return sameDay ? `Today, ${time}` : `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

function backupsValue(b: Backups | undefined) {
  if (!b) return "";
  const o = b.offsite;
  if (!o.enabled) return since(b.local.last_at);
  if (o.last_error || o.check_ok === false) return <span style={{ color: "var(--bad)" }}>Needs a look</span>;
  if (!o.key_saved_at && o.last_ok_at) return "Save the key";
  return since(o.last_ok_at ?? b.local.last_at);
}

export function Settings() {
  const meta = useLoad(() => api.GET("/api/meta"));
  const status = useLoad(() => api.GET("/api/status"));
  const healthSum = useLoad(() => api.GET("/api/health/summary"));
  const whoopSt = useLoad(() => api.GET("/api/whoop/status"));
  const pushSt = useLoad(() => api.GET("/api/push"));
  const aiSt = useLoad(() => api.GET("/api/ai/providers"));
  const reg = useLoad(() => api.GET("/api/region"));
  const backups = useLoad(() => api.GET("/api/backups"));
  const [check, setCheck] = useState<{ busy: boolean; text?: string; ok?: boolean }>({ busy: false });

  async function testAi() {
    setCheck({ busy: true });
    try {
      const { data, error } = await api.POST("/api/ai/check");
      if (error) throw new Error(problemText(error));
      const job = await waitForJob(data.job_id);
      if (job.status === "failed") throw new Error(job.error ?? "The check failed.");
      const r = job.result as { reply?: string; seconds?: number } | null;
      setCheck({ busy: false, ok: true, text: `Answered in ${r?.seconds ?? "?"} s: “${r?.reply ?? ""}”` });
    } catch (e) {
      setCheck({ busy: false, ok: false, text: e instanceof Error ? e.message : "The check failed." });
    }
    status.reload();
  }

  async function choose(provider: "claude" | "codex") {
    const { error } = await api.PUT("/api/ai/provider", { body: { provider } });
    if (error) setCheck({ busy: false, ok: false, text: problemText(error) });
    else setCheck({ busy: false });
    aiSt.reload();
    status.reload();
  }

  const s = status.data;
  const jobsText = s ? (s.jobs.running + s.jobs.queued + s.jobs.failed === 0 ? "All clear"
    : [s.jobs.running && `${s.jobs.running} running`, s.jobs.queued && `${s.jobs.queued} waiting`,
      s.jobs.failed && `${s.jobs.failed} failed`].filter(Boolean).join(", ")) : "";

  return (
    <Page title="Settings" backTo="/" backLabel="Summary">
      {(status.error || meta.error) && <div className="notice error">{status.error ?? meta.error}</div>}

      <Section>
        <List>
          <Row icon={<PeopleIcon filled />} tile="var(--gray)" title="Signed in as" value={meta.data?.who ?? ""} />
          <Row icon={<GlobeIcon />} tile="#30b0c7" title="Region" to="/settings/region"
            value={reg.data ? (reg.data.chosen ? `${reg.data.country.replace(/^the /, "")} · ${reg.data.currency}` : "Choose") : ""} />
        </List>
      </Section>

      <Section header="Data" footer="WHOOP is read directly; Apple Health readings come from your iPhone. The catalog is backed up every day; backups are never deleted.">
        <List>
          <Row icon={<BoltIcon />} tile="#1c1c1e" title="WHOOP" to="/settings/whoop"
            value={whoopSt.data ? (whoopSt.data.connected ? (whoopSt.data.last_error ? "Needs attention" : since(whoopSt.data.last_sync_at)) : "Set up") : ""} />
          <Row icon={<HeartIcon />} tile="#ff2d55" title="Apple Health" to="/settings/health"
            value={healthSum.data?.last_sync ? since(healthSum.data.last_sync.at) : "Set up"} />
          <Row icon={<ArchiveIcon />} tile="#8e8e93" title="Backups" to="/settings/backups"
            value={backupsValue(backups.data)} />
        </List>
      </Section>

      <Section>
        <List>
          <Row icon={<BellIcon />} tile="var(--red)" title="Notifications" to="/settings/notifications"
            value={pushSt.data ? (pushSt.data.devices.length ? `${pushSt.data.devices.length} ${pushSt.data.devices.length === 1 ? "device" : "devices"}` : "Off") : ""} />
        </List>
      </Section>

      <Section header="AI" footer="Meals, health notes and Hobbes AI jobs are run by the AI you choose, on your own plan. The test uses a little of it.">
        <List>
          {(aiSt.data?.providers ?? []).map((p) => (
            <Row key={p.provider} title={p.name} onClick={() => choose(p.provider)} chevron={false}
              sub={p.installed && p.signed_in
                ? `${p.tool} ${p.version ?? ""}${p.plan ? ` · ${p.plan.charAt(0).toUpperCase()}${p.plan.slice(1)} plan` : ""}`
                : p.detail ?? ""}
              trailing={aiSt.data?.provider === p.provider ? <span style={{ color: "var(--tint-text)", display: "inline-flex" }} aria-label="Chosen"><CheckIcon /></span> : undefined} />
          ))}
          <Row title={check.busy ? "Testing…" : "Test the AI"} tone="tinted" onClick={testAi} disabled={check.busy}
            trailing={check.busy ? <Spinner label="Testing" /> : undefined} />
          {check.text && <Row title={<span className={check.ok ? "secondary" : "danger"} style={{ whiteSpace: "normal" }}>{check.text}</span>} />}
          <Row title="Background jobs" value={jobsText} />
        </List>
      </Section>

      <Section header="Connection" footer={s && !s.https
        ? "Turn on HTTPS Certificates in the Tailscale admin console (DNS page). Notifications and Face ID approvals need it."
        : undefined}>
        <List>
          <Row icon={<LockIcon />} tile={s?.https ? "#34c759" : "#ff9500"} title="Secure connection"
            value={s ? (s.https ? "HTTPS" : "Not yet") : ""} />
        </List>
      </Section>

      <Section header="App" footer={`Loads the newest version, as a browser's hard refresh would. The dashboard also offers this by itself after an update.${meta.data ? ` Running ${meta.data.name} ${meta.data.version}, build ${meta.data.build}.` : ""}`}>
        <List>
          <Row title="Reload App" tone="tinted" onClick={hardReload} chevron={false} />
        </List>
      </Section>
    </Page>
  );
}
