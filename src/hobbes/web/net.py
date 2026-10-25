"""Tailscale: this Mac's tailnet name and owner, and publishing the dashboard to the tailnet with
`tailscale serve`.

`tailscale serve` is used rather than listening on the network, because the macOS firewall silently
drops direct connections to the Python that uv installs; Tailscale is a signed app it lets through.
Each port's entry is separate, so publishing the dashboard leaves other entries alone.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess

TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

_TS_CLI = ["tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"]
# The macOS app binary acts as the CLI only when told to; under launchd it otherwise tries to open
# its window and does nothing.
_TS_ENV = dict(os.environ, TAILSCALE_BE_CLI="1")


def offline() -> bool:
    return os.environ.get("HOBBES_OFFLINE") == "1"


def cli() -> str | None:
    if offline():
        return None
    for c in _TS_CLI:
        if shutil.which(c) or (c.startswith("/") and os.path.exists(c)):
            return c
    return None


def _status() -> dict:
    c = cli()
    if not c:
        return {}
    try:
        out = subprocess.run([c, "status", "--json"], capture_output=True, text=True, timeout=5, env=_TS_ENV).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def info() -> dict:
    """This Mac on the tailnet: its MagicDNS name, the login it's signed in with (the owner), and
    whether the tailnet has HTTPS certificates turned on."""
    d = _status()
    me = d.get("Self") or {}
    user = (d.get("User") or {}).get(str(me.get("UserID")), {})
    login = user.get("LoginName")
    return {
        "name": (me.get("DNSName") or "").rstrip(".") or None,
        "owner": login.strip().lower() if login else None,
        "https": bool(d.get("CertDomains")),
    }


def serve(port: int) -> tuple[str | None, str | None]:
    """Publish http://127.0.0.1:port on the same port of the tailnet name: HTTPS when the tailnet has
    certificates, otherwise HTTP. Returns (url, error)."""
    c = cli()
    if not c:
        return None, "Tailscale's command-line tool wasn't found."
    t = info()
    err = "tailscale serve failed"

    def run(mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([c, "serve", "--bg", "--yes", f"--{mode}={port}", f"http://127.0.0.1:{port}"],
                              capture_output=True, text=True, timeout=25, env=_TS_ENV)

    for mode in ("https", "http") if t["https"] else ("http",):
        try:
            r = run(mode)
            if r.returncode and mode == "https" and 'already serving "http"' in (r.stderr or r.stdout):
                # Published over http before the tailnet had HTTPS: a port is one or the other, so this
                # port's http entry goes first (only this port's).
                subprocess.run([c, "serve", f"--http={port}", "off"], capture_output=True, timeout=10, env=_TS_ENV)
                r = run(mode)
        except (OSError, subprocess.SubprocessError) as e:
            err = str(e)
            continue
        if r.returncode == 0:
            return f"{mode}://{t['name'] or '<this-mac>'}:{port}", None
        lines = (r.stderr or r.stdout).strip().splitlines()
        err = lines[-1] if lines else err
    return None, err


def unserve(port: int) -> None:
    """Remove this port's entry only (both schemes); other ports' entries are untouched."""
    c = cli()
    if not c:
        return
    for mode in ("https", "http"):
        try:
            subprocess.run([c, "serve", f"--{mode}={port}", "off"], capture_output=True, timeout=10, env=_TS_ENV)
        except (OSError, subprocess.SubprocessError):
            pass


def serve_status() -> str:
    c = cli()
    if not c:
        return ""
    try:
        return subprocess.run([c, "serve", "status"], capture_output=True, text=True, timeout=10, env=_TS_ENV).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
