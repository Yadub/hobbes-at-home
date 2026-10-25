"""`hobbes setup`: the first run. Checks the Mac, picks the AI (Claude or ChatGPT) and the region, starts the
background service, and optionally publishes it to the owner's tailnet for their phone. Safe to run again: it
shows what's set and changes only what the owner answers differently.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import ai, config, db, region, service
from .web import net

Ask = Callable[[str], str]


def _yes(ask: Ask, question: str, default: bool) -> bool:
    answer = ask(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer.startswith("y")


def _choose_ai(conn, args: argparse.Namespace, ask: Ask, say: Callable[[str], None]) -> str | None:
    found = {p["provider"]: p for p in ai.choices(refresh=True, conn=conn)["providers"]}
    ready = [n for n, p in found.items() if p["installed"] and p["signed_in"]]
    if args.ai:
        choice = args.ai
    elif len(ready) == 2 and args.yes:
        choice = ai.provider(conn)
    elif len(ready) == 2:
        say("Both Claude (Claude Code) and ChatGPT (Codex) are signed in on this Mac.")
        answer = ask("Which should Hobbes at Home use? 1 Claude, 2 ChatGPT: ").strip()
        choice = "codex" if answer in ("2", "chatgpt", "codex") else "claude"
    elif ready:
        choice = ready[0]
    else:
        say("Neither AI is ready yet. Hobbes at Home needs one of them, on your own plan:")
        for p in found.values():
            say(f"  {p['name']}: {p['detail']}")
        say("Then run `hobbes setup` again. Everything else works meanwhile, apart from reading meals.")
        return None
    ai.set_provider(conn, choice)
    p = found[choice]
    if p["installed"] and p["signed_in"]:
        say(f"AI: {p['name']} through {p['tool']} {p['version'] or ''}".rstrip() + ".")
    else:
        say(f"AI: {p['name']}, not ready yet. {p['detail']}")
    return choice


def _choose_region(conn, args: argparse.Namespace, ask: Ask, say: Callable[[str], None]) -> None:
    r = region.get(conn)
    if args.country:
        country, cuisine, currency = args.country, args.cuisine or "", args.currency or ""
    elif args.yes:
        country, cuisine, currency = r["country_code"], "", ""
    else:
        say(f"Region: {r['country'].removeprefix('the ')} ({r['country_code']}), prices in {r['currency']}.")
        country = ask("Country, as its two-letter code (Enter to keep): ").strip() or r["country_code"]
        cuisine = ask("What do you mostly eat, in a few words? (Enter for the usual food where you live): ").strip()
        currency = ask("Currency, as its three-letter code (Enter for your country's): ").strip()
    while True:
        try:
            region.put(conn, country, cuisine, currency)
            break
        except ValueError as e:
            if args.yes or args.country:
                raise RuntimeError(str(e)) from None
            say(str(e))
            country = ask("Country code: ").strip()
    r = region.get(conn)
    say(f"Region: {r['country'].removeprefix('the ')}; meals read as {r['cuisine']}; prices in {r['currency']}.")


def run(args: argparse.Namespace, ask: Ask = input, say: Callable[[str], None] = print) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Hobbes at Home runs on macOS only, for now.")
    say("Setting up Hobbes at Home.\n")
    conn = db.connect()
    say(f"Your data stays on this Mac, in {config.home()} (readable by your account only).")

    choice = _choose_ai(conn, args, ask, say)
    if choice and not args.yes and _yes(ask, "Try the AI now? It uses a little of your plan.", False):
        try:
            answer = ai.ask("This is a connection test from a personal dashboard. Reply with ok set to true and "
                            "reply set to a short friendly greeting of at most eight words. Do not run any commands.",
                            schema=ai.CHECK_SCHEMA, kind="ai.check", timeout=180, conn=conn)
            say(f"It answered: “{answer['reply']}”")
        except ai.AIError as e:
            say(f"It didn't work: {e}")

    _choose_region(conn, args, ask, say)

    url = f"http://localhost:{args.port}"
    if args.service and (args.yes or _yes(ask, "Start Hobbes at Home now, and at every login?", True)):
        service.install(args.port)
        say(f"Started: {url}")
        t = net.info()
        if t["name"] and (args.tailscale or (not args.yes and _yes(
                ask, "Publish it to your tailnet, so your phone can open it (only you can reach it)?", False))):
            published, err = net.serve(args.port)
            say(f"On your tailnet: {published}" if published else f"Couldn't publish it to your tailnet: {err}")
    else:
        say(f"Not started. To start it later: hobbes service install (it then runs on {url}).")

    say("\nNext: open " + url + " on this Mac. In Settings you can connect Apple Health (from your iPhone) and "
        "WHOOP, and change the AI or the region. `hobbes doctor` checks everything.")
