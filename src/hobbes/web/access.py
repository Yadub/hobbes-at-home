"""Who may use the dashboard, and which requests are refused.

One user: the owner. That's anyone at the Mac itself, or a device signed in to Tailscale with the
Mac's own account (the login `tailscale serve` adds to each request it forwards). Everyone else,
including other accounts on the tailnet, sees a "private" notice and nothing else.

Separately from who is asking, every request is checked so that a website open in the owner's own
browser can't use it to reach the dashboard: only this Mac's own names are answered (no DNS
rebinding), and changes are accepted only from the dashboard's own pages.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from . import net

PRIVATE = "This dashboard is private to its owner."
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "tailscale-user-login")
SAFE = {"GET", "HEAD", "OPTIONS"}
# Sent by the dashboard's own pages with uploads (which can't be JSON). A browser won't send a custom
# header from any other site without asking first, and the dashboard never agrees.
OWN_HEADER = "x-hobbes"


def _loopback_peer(request: Request) -> bool:
    client = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(client.split("%")[0])
    except ValueError:
        return client in ("testclient", "localhost")  # FastAPI's TestClient
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def forwarded(request: Request) -> bool:
    """Came through `tailscale serve`: a connection from this Mac carrying X-Forwarded-For."""
    return _loopback_peer(request) and bool(request.headers.get("x-forwarded-for"))


def tailnet_login(request: Request) -> str | None:
    """The Tailscale account a request came from. Believed only on a connection `tailscale serve`
    forwarded from this Mac: the app listens on 127.0.0.1 alone, so nobody else can set the header."""
    if not forwarded(request):
        return None
    login = request.headers.get("tailscale-user-login")
    return login.strip().lower() if login else None


def at_the_mac(request: Request) -> bool:
    """Made on this Mac itself: from a loopback address and not forwarded by a proxy. Other user
    accounts on the Mac count too; the data folder is private to the owner's account."""
    if any(request.headers.get(h) for h in _PROXY_HEADERS):
        return False
    return _loopback_peer(request)


def is_owner(request: Request) -> bool:
    if at_the_mac(request):
        return True
    owner = getattr(request.app.state, "owner", None)
    who = tailnet_login(request)
    return bool(owner and who and who == owner)


def who(request: Request) -> str | None:
    """How the owner is signed in on this request, for the dashboard to show."""
    if at_the_mac(request):
        return "this Mac"
    return tailnet_login(request)


def host_name(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v[1 : v.find("]")]
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def host_allowed(host: str, extra: set[str]) -> bool:
    """Only names that really mean this Mac: localhost, its own tailnet name, its addresses. Not any
    *.ts.net name: another tailnet's machine isn't this Mac."""
    if host in ("localhost", "127.0.0.1", "::1", "testserver") or host in extra:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip in net.TAILSCALE_V4 or ip in net.TAILSCALE_V6


def guard_problem(request: Request, extra_hosts: set[str]) -> tuple[int, str] | None:
    """Why this request must be refused, or None."""
    host = host_name(request.headers.get("host"))
    if not host_allowed(host, extra_hosts):
        return 421, "The dashboard only answers to this Mac's own names."
    if request.headers.get("tailscale-funnel-request"):
        return 403, "The dashboard isn't for the open internet: it only answers on your tailnet."
    if request.method in SAFE:
        return None
    origin = request.headers.get("origin")
    if origin and origin != "null":
        o = host_name(origin.split("://", 1)[-1].split("/", 1)[0])
        fwd = host_name(request.headers.get("x-forwarded-host"))
        if o not in (host, fwd):
            return 403, "Changes can only be made from the dashboard's own pages."
    elif request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        return 403, "Changes can only be made from the dashboard's own pages."
    length = request.headers.get("content-length")
    has_body = bool((length and length != "0") or request.headers.get("transfer-encoding"))
    ctype = (request.headers.get("content-type") or "").lower()
    is_json = ctype.startswith("application/json")
    is_upload = ctype.startswith("multipart/form-data")
    if has_body and not (is_json or is_upload):
        return 415, "The dashboard only accepts JSON and file uploads."
    # From a browser, a change must be JSON or carry the dashboard's own header. Either makes a browser
    # ask before sending it from any other page, and the dashboard never agrees. Tools that aren't
    # browsers (curl, scripts on the Mac) send no Origin or Sec-Fetch headers and aren't affected.
    from_browser = bool(origin) or request.headers.get("sec-fetch-site") is not None \
        or request.headers.get("sec-fetch-mode") is not None
    if from_browser and not is_json and request.headers.get(OWN_HEADER) != "1":
        return 403, "Changes can only be made from the dashboard's own pages."
    return None
