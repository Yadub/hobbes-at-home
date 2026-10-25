import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { api, problemText, useLoad } from "../api/client";
import { useToast } from "../components/Controls";
import { BellIcon, Spinner } from "../components/Icons";
import { List, Row, Section } from "../components/List";
import { Page } from "../components/Page";
import { shortWhen } from "./assistant/common";

const canPush = () => window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.userAgent.includes("Macintosh") && navigator.maxTouchPoints > 1);

function deviceName(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (isIOS()) return "iPad";
  if (/Android/.test(ua)) return "Android phone";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows PC";
  return "This device";
}

function keyBytes(b64: string): Uint8Array<ArrayBuffer> {
  const raw = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64.length % 4)) % 4));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function hashOf(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/** Notifications (push.py): this device on or off, which kinds, the devices that get them, and a test. */
export function NotificationsPage() {
  const s = useLoad(() => api.GET("/api/push"));
  const [mine, setMine] = useState<string | null>(null);  // this device's endpoint hash, if it's subscribed
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const d = s.data;
  const supported = canPush();
  const here = d?.devices.find((x) => x.endpoint_hash === mine);

  useEffect(() => {
    if (!supported) return;
    void currentSubscription().then(async (sub) => setMine(sub ? await hashOf(sub.endpoint) : null)).catch(() => setMine(null));
  }, [supported]);

  async function turnOn() {
    if (!d) return;
    setBusy(true);
    setError(null);
    try {
      // Asked straight from the tap: iPhones only ask for permission from one.
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        throw new Error(isIOS() ? "Notifications are off for the dashboard. Turn them on in the iPhone's Settings, Notifications, Home." : "Notifications are blocked for this site. Allow them in the browser's site settings.");
      }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const options = { userVisibleOnly: true, applicationServerKey: keyBytes(d.public_key) };
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe(options);
      }
      const j = sub.toJSON();
      const { error: err } = await api.POST("/api/push/devices", {
        body: { endpoint: sub.endpoint, p256dh: j.keys?.p256dh ?? "", auth: j.keys?.auth ?? "", label: deviceName() },
      });
      if (err) {
        // Subscribed with an older key of the dashboard's: start afresh once.
        await sub.unsubscribe();
        throw new Error(problemText(err));
      }
      setMine(await hashOf(sub.endpoint));
      toast({ text: "Notifications are on for this device" });
      s.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff(id: number, thisDevice: boolean) {
    setBusy(true);
    setError(null);
    if (thisDevice) await (await currentSubscription())?.unsubscribe().catch(() => false);
    const { error: err } = await api.DELETE("/api/push/devices/{device_id}", { params: { path: { device_id: id } } });
    setBusy(false);
    if (err) { setError(problemText(err)); return; }
    if (thisDevice) setMine(null);
    s.reload();
  }

  async function setKind(kind: string, on: boolean) {
    const { error: err } = await api.PUT("/api/push/kinds", { body: { [kind]: on } });
    if (err) { toast({ text: problemText(err) }); return; }
    s.reload();
  }

  async function test() {
    const { error: err } = await api.POST("/api/push/test");
    toast({ text: err ? problemText(err) : "Sent. It should arrive in a few seconds." });
    s.reload();
  }

  return (
    <Page title="Notifications" backTo="/settings" backLabel="Settings">
      {(error || s.error) && <div className="notice error" role="alert">{error ?? s.error}</div>}

      {!window.isSecureContext ? (
        <Section footer="Browsers allow notifications only on a secure (HTTPS) page. Turn on HTTPS Certificates in the Tailscale admin console (DNS page), then open the dashboard at its https:// address.">
          <List><Row icon={<BellIcon />} tile="var(--red)" title="Needs HTTPS" value="Not yet" /></List>
        </Section>
      ) : !supported ? (
        <Section footer={isIOS()
          ? "On iPhone, notifications come to the dashboard's Home Screen app. In Safari: Share, Add to Home Screen. Then open it from the Home Screen and come back here."
          : "This browser can't receive notifications from web pages."}>
          <List><Row icon={<BellIcon />} tile="var(--red)" title="Not available here" /></List>
        </Section>
      ) : (
        <Section footer={here ? "Turn this off to stop them on this device only." : "You'll be asked to allow notifications."}>
          <List>
            <label className="row has-icon">
              <span className="icon-tile" style={{ "--tile": "var(--red)" } as CSSProperties}><BellIcon /></span>
              <span className="row-main"><span className="row-title">On This {deviceName()}</span></span>
              {busy && <Spinner label="Working" />}
              <input type="checkbox" className="switch" checked={Boolean(here)} disabled={busy || !d}
                onChange={(e) => (e.target.checked ? turnOn() : here && turnOff(here.id, true))} />
            </label>
          </List>
        </Section>
      )}

      {d && (
        <Section header="Tell Me When" footer="These apply to every device. The text is encrypted for your devices; Apple (or the browser's push service) carries it without being able to read it.">
          <List>
            {d.kinds.map((k) => (
              <label key={k.kind} className="row">
                <span className="row-main"><span className="row-title" style={{ whiteSpace: "normal" }}>{k.label}</span></span>
                <input type="checkbox" className="switch" checked={k.on} onChange={(e) => setKind(k.kind, e.target.checked)} />
              </label>
            ))}
          </List>
        </Section>
      )}

      {d && d.devices.length > 0 && (
        <Section header="Devices">
          <List>
            {d.devices.map((x) => (
              <Row key={x.id} title={`${x.label}${x.endpoint_hash === mine ? " (this one)" : ""}`} chevron={false}
                sub={x.last_error ?? (x.last_ok_at ? `Last sent ${shortWhen(x.last_ok_at)}` : `Added ${shortWhen(x.created_at)}`)}
                trailing={<button type="button" className="as-inline quiet" disabled={busy}
                  onClick={() => turnOff(x.id, x.endpoint_hash === mine)}>Remove</button>} />
            ))}
            <Row title="Send a Test" tone="tinted" onClick={test} chevron={false} />
          </List>
        </Section>
      )}
    </Page>
  );
}
