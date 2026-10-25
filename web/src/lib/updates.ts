import { useEffect, useRef, useState } from "react";

// The home-screen app has no reload button, so the dashboard checks whether it has been updated (its
// build changes on every deploy) when it comes back to the foreground and every few minutes, and
// offers a reload. Settings has a manual one too.

/** Load the newest version, bypassing anything the browser kept. */
export async function hardReload() {
  try {
    if ("caches" in window) for (const k of await caches.keys()) await caches.delete(k);
  } catch {
    // no Cache Storage over plain HTTP: nothing to clear
  }
  const url = new URL(window.location.href);
  url.searchParams.set("_r", String(Date.now()));
  window.location.replace(url.toString());
}

/** Drop the cache-busting parameter a hard reload added, so it doesn't stay in the address. */
export function tidyReloadParam() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("_r")) return;
  url.searchParams.delete("_r");
  window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
}

async function currentBuild(): Promise<string | null> {
  try {
    const r = await fetch("/api/meta", { cache: "no-store" });
    return r.ok ? ((await r.json()) as { build: string }).build : null;
  } catch {
    return null;
  }
}

export function useUpdateAvailable(): boolean {
  const first = useRef<string | null>(null);
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let stopped = false;
    const check = async () => {
      const b = await currentBuild();
      if (stopped || !b) return;
      if (first.current === null) first.current = b;
      else if (b !== first.current) setAvailable(true);
    };
    check();
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    const timer = window.setInterval(check, 5 * 60_000);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
      window.clearInterval(timer);
    };
  }, []);
  return available;
}
