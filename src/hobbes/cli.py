"""The `hobbes` command: run the dashboard, install it as a background service, back up, check."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, ai, config, db, jobs, maintenance, service
from .web import net

REPO = Path(__file__).resolve().parents[2]


def _build() -> str:
    """Which code is running: the commit, plus "+" when there are uncommitted changes."""
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return (sha + ("+" if dirty else "")) if sha else __version__
    except (OSError, subprocess.SubprocessError):
        return __version__


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .web.app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t = net.info()
    scheme = "https" if t["https"] else "http"
    url = f"{scheme}://{t['name']}:{args.port}" if t["name"] else None
    app = create_app(owner=t["owner"], tailnet_name=t["name"], tailnet_url=url, https=t["https"],
                     build=f"{_build()} {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Hobbes at Home on http://127.0.0.1:{args.port}" + (f" and {url} (if published)" if url else ""))
    if t["owner"]:
        print(f"Owner on the tailnet: {t['owner']}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", proxy_headers=False)


def cmd_service(args: argparse.Namespace) -> None:
    if args.action == "install":
        service.install(args.port)
        print(f"Service installed and started on http://127.0.0.1:{args.port}")
        if args.tailscale:
            url, err = net.serve(args.port)
            print(f"Published to your tailnet: {url}" if url else f"Couldn't publish to the tailnet: {err}")
    elif args.action == "uninstall":
        p = service.port()
        service.uninstall()
        if p:
            net.unserve(p)
        print("Service removed. The catalog in", config.home(), "is untouched.")
    elif args.action == "stop":
        service.stop()
        print("Stopped. `hobbes service install` starts it again.")
    elif args.action == "restart":
        service.restart()
        print("Restarted.")
    elif args.action == "logs":
        print(service.log_tail())
    else:
        print(json.dumps({"installed": service.installed(), "running": service.running(),
                          "port": service.port()}, indent=2))
        print(net.serve_status().strip())


def cmd_backup(args: argparse.Namespace) -> None:
    conn = db.connect()
    made = maintenance.backup_now(conn, tag=args.tag or datetime.now().strftime("manual-%Y%m%d-%H%M%S"))
    print(f"Backed up to {made}" if made else "A backup with that name already exists; nothing written.")


def cmd_openapi(args: argparse.Namespace) -> None:
    """Write the API's schema, from which the frontend's types are generated."""
    from .web.app import create_app

    app = create_app(run_jobs=False)
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    Path(args.path).write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {args.path}")


def cmd_doctor(args: argparse.Namespace) -> None:
    t = net.info()
    s = ai.status(refresh=True, conn=db.connect())
    static = Path(__file__).parent / "web" / "static" / "index.html"
    checks = [
        ("Data folder", str(config.home())),
        ("Catalog schema", f"{db.migrate(db.connect())} (latest {len(db.MIGRATIONS)})"),
        ("Frontend built", "yes" if static.exists() else "no: npm --prefix web ci && npm --prefix web run build"),
        ("AI", f"{s['name']} through {s['tool']} {s['version'] or '(not found)'}; {s['detail']}"),
        ("AI tools", (ai.features_problem(path) if s["provider"] == "codex" and (path := ai.codex_path()) else None)
         or "web search and photos only; everything else switched off"),
        ("Tailscale name", t["name"] or "not found"),
        ("Tailscale owner", t["owner"] or "not found"),
        ("Tailnet HTTPS", "on" if t["https"] else "off (turn on HTTPS Certificates in the Tailscale admin console)"),
        ("Service", "running" if service.installed() and service.running() else
                    "installed, not running" if service.installed() else "not installed"),
        ("Last backup", maintenance.last_backup_at() or "none yet"),
    ]
    for name, value in checks:
        print(f"{name:16} {value}")


def cmd_setup(args: argparse.Namespace) -> None:
    from . import setup

    setup.run(args)


def cmd_run_jobs(args: argparse.Namespace) -> None:
    """Run queued jobs once, in the foreground (for trying things out without the service)."""
    conn = db.connect()
    n = 0
    while jobs.run_one(conn):
        n += 1
    print(f"Ran {n} job(s).")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="hobbes", description="Hobbes at Home, the dashboard on this Mac.")
    p.add_argument("--version", action="version", version=f"hobbes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="Set up Hobbes at Home: the AI, your region and the background service.")
    s.add_argument("--ai", choices=list(ai.PROVIDERS), help="Use Claude (claude) or ChatGPT (codex) without asking.")
    s.add_argument("--country", help="Two-letter country code, without asking.")
    s.add_argument("--cuisine", help="What you mostly eat, in a few words.")
    s.add_argument("--currency", help="Three-letter currency code.")
    s.add_argument("--port", type=int, default=config.PORT)
    s.add_argument("--no-service", dest="service", action="store_false", help="Don't install the background service.")
    s.add_argument("--tailscale", action="store_true", help="Publish it to your tailnet with tailscale serve.")
    s.add_argument("--yes", action="store_true", help="Accept the defaults; ask nothing.")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("serve", help="Run the dashboard in the foreground (listens on 127.0.0.1 only).")
    s.add_argument("--port", type=int, default=config.PORT)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("service", help="The background service (launchd).")
    s.add_argument("action", choices=["install", "uninstall", "stop", "restart", "status", "logs"])
    s.add_argument("--port", type=int, default=config.PORT)
    s.add_argument("--tailscale", action="store_true", help="Also publish it to your tailnet with tailscale serve.")
    s.set_defaults(fn=cmd_service)

    s = sub.add_parser("backup", help="Back up the catalog now (never overwrites a backup).")
    s.add_argument("--tag", help="Name the backup catalog-<tag>.db.")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("openapi", help="Write the API schema (for the frontend's types).")
    s.add_argument("path")
    s.set_defaults(fn=cmd_openapi)

    s = sub.add_parser("doctor", help="Check the setup.")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("run-jobs", help="Run queued jobs once in the foreground.")
    s.set_defaults(fn=cmd_run_jobs)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
