import { useSyncExternalStore } from "react";
import type { AnchorHTMLAttributes, MouseEvent } from "react";

// A very small router: the address bar's path is the page. Links call `go`; back and forward work.

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}

export function useQuery(): URLSearchParams {
  const search = useSyncExternalStore(subscribe, () => window.location.search);
  return new URLSearchParams(search);
}

let depth = 0;

export function go(to: string, { replace = false } = {}) {
  if (to === window.location.pathname + window.location.search) return;
  if (replace) window.history.replaceState(null, "", to);
  else {
    window.history.pushState(null, "", to);
    depth += 1;
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

/** Back within the app when there's somewhere to go back to, otherwise to `fallback`. */
export function back(fallback: string) {
  if (depth > 0) {
    depth -= 1;
    window.history.back();
  } else go(fallback, { replace: true });
}

/** `/diet/meal/:id` against a path: the parameters, or null. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/");
  const a = path.replace(/\/$/, "").split("/");
  if (p.length !== a.length) return null;
  const out: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    const seg = p[i] ?? "";
    const val = a[i] ?? "";
    if (seg.startsWith(":")) out[seg.slice(1)] = decodeURIComponent(val);
    else if (seg !== val) return null;
  }
  return out;
}

export function Link({ to, onClick, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    go(to);
  };
  return <a href={to} onClick={handle} {...rest} />;
}
