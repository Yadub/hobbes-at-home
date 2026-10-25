import { useEffect, useState } from "react";
import { api, problemText, useLoad, waitForJob } from "../api/client";
import { useToast } from "../components/Controls";
import { Spinner } from "../components/Icons";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";

function when(iso: string | null | undefined) {
  if (!iso) return "Not yet";
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString()
    ? `Today, ${time}` : `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

const megabytes = (n: number) => `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)} MB`;

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Backups (maintenance.py, offsite.py): the encrypted copies in iCloud Drive, their recovery key, and the
 *  copies on this Mac. */
export function BackupsPage() {
  const s = useLoad(() => api.GET("/api/backups"));
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<"copy" | "check" | null>(null);
  const toast = useToast();
  const d = s.data;
  const o = d?.offsite;
  const running = Boolean(busy || d?.running);

  useEffect(() => {
    if (!d?.running || busy) return;
    const timer = window.setInterval(s.reload, 3000);
    return () => window.clearInterval(timer);
  }, [d?.running, busy, s.reload]);

  async function showKey() {
    const { data, error } = await api.GET("/api/backups/key");
    if (error) { toast({ text: problemText(error) }); return; }
    setKey(data.key);
  }

  async function saved() {
    const { error } = await api.POST("/api/backups/key/saved");
    if (error) { toast({ text: problemText(error) }); return; }
    setKey(null);
    s.reload();
  }

  async function run(what: "copy" | "check") {
    setBusy(what);
    try {
      const { data, error } = await api.POST("/api/backups/run", { body: { what } });
      if (error) throw new Error(problemText(error));
      const job = await waitForJob(data.job_id, 20 * 60_000);
      const r = job.result as { error?: string; check_error?: string } | null;
      const problem = job.error ?? r?.error ?? r?.check_error;
      toast({ text: problem ? problem : what === "copy" ? "Copied to iCloud Drive and checked" : "The newest copy checked out" });
    } catch (e) {
      toast({ text: e instanceof Error ? e.message : "That didn't work." });
    } finally {
      setBusy(null);
      s.reload();
    }
  }

  const keySection = (
    <Section header="Recovery Key" footer={o?.key_saved_at
      ? `You saved it on ${new Date(o.key_saved_at).toLocaleDateString(undefined, { day: "numeric", month: "long" })}. Each copy opens on any Mac: double-click it and type the key.`
      : "The copies in iCloud Drive are encrypted with this key. Save it in the Passwords app now: without it they can't be opened, and if the Mac is lost its Keychain goes with it."}>
      <List>
        {key ? (
          <>
            <div className="row">
              <span className="row-main">
                <span className="row-title" style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", userSelect: "all", letterSpacing: "0.04em" }}>{key}</span>
              </span>
            </div>
            <Row title="Copy" tone="tinted" chevron={false}
              onClick={async () => toast({ text: await copyText(key) ? "Copied. Paste it into Passwords." : "Couldn't copy: select it and copy." })} />
            {!o?.key_saved_at && <Row title="I've Saved It in Passwords" tone="tinted" chevron={false} onClick={saved} />}
            {o?.key_saved_at && <Row title="Hide" tone="tinted" chevron={false} onClick={() => setKey(null)} />}
          </>
        ) : (
          <Row title="Show Recovery Key" tone="tinted" chevron={false} onClick={showKey} />
        )}
      </List>
    </Section>
  );

  return (
    <Page title="Backups" backTo="/settings" backLabel="Settings">
      {s.error && <div className="notice error" role="alert">{s.error}</div>}

      {o && (
        <Section header="iCloud Drive" footer={o.enabled ? undefined : "An encrypted copy every day, so a lost or broken Mac loses nothing. When you turn it on, macOS asks once whether Hobbes at Home may use iCloud Drive."}>
          <List>
            <div className="row">
              <span className="row-main"><span className="row-title">Copy to iCloud Drive Daily</span></span>
              <input className="switch" type="checkbox" role="switch" aria-label="Copy to iCloud Drive daily"
                checked={o.enabled} disabled={running}
                onChange={async (e) => {
                  const { error } = await api.PUT("/api/backups/icloud", { body: { enabled: e.target.checked } });
                  if (error) toast({ text: problemText(error) });
                  s.reload();
                }} />
            </div>
          </List>
        </Section>
      )}

      {o?.enabled && !o.key_saved_at && keySection}

      {o?.enabled && (
        <Section footer={`Daily after 1:00, into ${o.folder}. The newest 14 copies are kept, and the first of each month. Each week the newest is opened with the key and checked, file by file.`}>
          <List>
            <Row title="Last Copy" value={when(o.last_ok_at)}
              sub={o.last_error ? <span style={{ color: "var(--bad)", whiteSpace: "normal" }}>{o.last_error}</span>
                : o.last_size ? [megabytes(o.last_size), o.last_note].filter(Boolean).join(" · ") : undefined} />
            <Row title="Last Check"
              value={o.checked_at ? (o.check_ok ? "Passed" : <span style={{ color: "var(--bad)" }}>Failed</span>) : "Not yet"}
              sub={o.check_error ? <span style={{ color: "var(--bad)", whiteSpace: "normal" }}>{o.check_error}</span>
                : o.checked_at ? when(o.checked_at) : undefined} />
            <Row title="Copies" value={String(o.copies)} />
            <Row title={busy === "copy" || (d?.running && !busy) ? "Backing Up…" : "Back Up Now"} tone="tinted" chevron={false}
              disabled={running} onClick={() => run("copy")} trailing={busy === "copy" || (d?.running && !busy) ? <Spinner label="Working" /> : undefined} />
            {o.copies > 0 && (
              <Row title={busy === "check" ? "Checking…" : "Check Now"} tone="tinted" chevron={false} disabled={running}
                onClick={() => run("check")} trailing={busy === "check" ? <Spinner label="Checking" /> : undefined} />
            )}
          </List>
        </Section>
      )}

      {o?.enabled && (
        <Section header="In Each Copy" footer={o.excludes.join(". ") + "."}>
          <List>
            {o.includes.map((x) => <Row key={x} title={<span style={{ whiteSpace: "normal" }}>{x}</span>} />)}
          </List>
        </Section>
      )}

      {o?.enabled && o.key_saved_at && keySection}

      {d && (
        <Section header="On This Mac" footer="The catalog only, every 6 hours, in ~/.hobbes/backups. These are on the same disk as the dashboard, so they don't help if the Mac is lost.">
          <List>
            <Row title="Last Backup" value={when(d.local.last_at)} />
            <Row title="Copies" value={String(d.local.copies)} />
          </List>
        </Section>
      )}
    </Page>
  );
}
