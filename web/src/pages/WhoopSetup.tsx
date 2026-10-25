import { useEffect, useState } from "react";
import { api, problemText, useLoad, waitForJob } from "../api/client";
import { useToast } from "../components/Controls";
import { Spinner } from "../components/Icons";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";
import { go, useQuery } from "../router";

const CALLBACK = "/api/whoop/callback";

function when(iso: string | null | undefined) {
  if (!iso) return "Not yet";
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? `Today, ${time}` : `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

export function WhoopSetup() {
  const q = useQuery();
  const s = useLoad(() => api.GET("/api/whoop/status"));
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  // WHOOP compares the address exactly, and "localhost" is what was registered for this Mac.
  const [redirect, setRedirect] = useState(`${window.location.origin.replace("//127.0.0.1", "//localhost")}${CALLBACK}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(q.get("error"));
  const toast = useToast();
  const st = s.data;

  useEffect(() => {
    if (!st) return;
    if (st.client_id) setClientId(st.client_id);
    if (st.redirect_uri) setRedirect(st.redirect_uri);
  }, [st]);

  useEffect(() => {
    if (q.get("connected")) {
      toast({ text: "WHOOP connected. Fetching the last 90 days…" });
      go("/settings/whoop", { replace: true });
    } else if (q.get("error")) {
      go("/settings/whoop", { replace: true });
    }
  }, [q, toast]);

  async function connect() {
    setBusy("connect");
    setError(null);
    const { data, error: err } = await api.POST("/api/whoop/setup", {
      body: { client_id: clientId, client_secret: secret || null, redirect_uri: redirect },
    });
    if (err) { setError(problemText(err)); setBusy(null); return; }
    window.location.href = data.auth_url; // WHOOP's sign-in; it sends you back here
  }

  async function syncNow() {
    setBusy("sync");
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/whoop/sync");
      if (err) throw new Error(problemText(err));
      const job = await waitForJob(data.job_id, 120_000);
      if (job.status === "failed") throw new Error(job.error ?? "The sync failed.");
      const r = job.result as { stored?: number } | null;
      toast({ text: `Synced ${r?.stored ?? 0} readings` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The sync failed.");
    }
    setBusy(null);
    s.reload();
  }

  async function disconnect() {
    setBusy("disconnect");
    const { error: err } = await api.POST("/api/whoop/disconnect");
    if (err) setError(problemText(err));
    else toast({ text: "WHOOP disconnected; your synced data is kept" });
    setBusy(null);
    s.reload();
  }

  const name = st?.profile ? [st.profile.first_name, st.profile.last_name].filter(Boolean).join(" ") : "";

  return (
    <Page title="WHOOP" backTo="/settings" backLabel="Settings">
      {error && <div className="notice error" role="alert">{error}</div>}
      {s.error && <div className="notice error">{s.error}</div>}

      {st?.connected ? (
        <>
          <Section header="Account">
            <List>
              <Row title="Signed in as" value={name || "WHOOP"} />
              {st.profile?.email && <Row title="Email" value={st.profile.email} />}
            </List>
          </Section>
          <Section header="Sync" footer="The dashboard checks WHOOP every 30 minutes for strain, energy burned, steps, recovery, sleep and weight.">
            <List>
              <Row title="Last synced" value={when(st.last_sync_at)} />
              {st.last_error && <Row title={<span className="danger" style={{ whiteSpace: "normal" }}>{st.last_error}</span>} />}
              <Row title={busy === "sync" ? "Syncing…" : "Sync Now"} tone="tinted" onClick={syncNow} disabled={!!busy}
                chevron={false} trailing={busy === "sync" ? <Spinner label="Syncing" /> : undefined} />
            </List>
          </Section>
          <Section header="AI" footer="Off: your WHOOP data stays out of Hobbes AI's view of your day and the Health page's advice. On: the AI you chose in Settings sees it, on your own plan.">
            <List>
              <div className="row">
                <span className="row-main"><span className="row-title">Share With the AI</span></span>
                <input className="switch" type="checkbox" role="switch" aria-label="Share WHOOP data with the AI"
                  checked={st.share_with_ai} disabled={!!busy}
                  onChange={async (e) => {
                    const { error: err } = await api.PUT("/api/whoop/share", { body: { share_with_ai: e.target.checked } });
                    if (err) toast({ text: problemText(err) });
                    s.reload();
                  }} />
              </div>
            </List>
          </Section>
          <Section footer="Everything already synced is kept. You can also remove the dashboard's access in the WHOOP app.">
            <List><Row title="Disconnect" tone="destructive" onClick={disconnect} disabled={!!busy} chevron={false} /></List>
          </Section>
        </>
      ) : st ? (
        <>
          <Section header="Your WHOOP app" footer="From developer-dashboard.whoop.com, under your app. The secret is kept in this Mac's Keychain and never shown again.">
            <List>
              <div className="row">
                <span className="row-main"><span className="row-title">Client ID</span></span>
                <input className="field" aria-label="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)}
                  autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="Paste" />
              </div>
              <div className="row">
                <span className="row-main"><span className="row-title">Client Secret</span></span>
                <input className="field" type="password" aria-label="Client Secret" value={secret} onChange={(e) => setSecret(e.target.value)}
                  autoComplete="off" placeholder={st.configured ? "Saved" : "Paste"} />
              </div>
            </List>
          </Section>
          <Section header="Redirect address" footer="Must be one of the Redirect URIs in your WHOOP app. If WHOOP only took the localhost one, connect from a browser on the Mac itself.">
            <List>
              <div className="row">
                <input className="field left" aria-label="Redirect address" value={redirect} onChange={(e) => setRedirect(e.target.value)}
                  autoCapitalize="none" autoCorrect="off" spellCheck={false} />
              </div>
            </List>
          </Section>
          <button className="button block" onClick={connect} disabled={!!busy || !clientId || (!secret && !st.configured)}>
            {busy === "connect" ? "Opening WHOOP…" : "Connect WHOOP"}
          </button>
        </>
      ) : null}
    </Page>
  );
}
