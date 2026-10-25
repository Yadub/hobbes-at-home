#!/usr/bin/env python3
"""Stands in for the `codex` command in tests. It records how it was called and answers from
FAKE_CODEX_REPLY (or {"ok": true, "reply": "hello"}); FAKE_CODEX_FAIL=1 makes it fail.

FAKE_CODEX_REPLIES (a file of JSON lines) gives a different reply to each call, in order, for trial
runs: each line is {"reply": <JSON or text>, "delay": <seconds>, "fail": true}, all optional. Once the
lines run out, FAKE_CODEX_REPLY applies again."""

import json
import os
import sys
import time


def _next_scripted():
    path = os.environ.get("FAKE_CODEX_REPLIES")
    if not path or not os.path.exists(path):
        return None
    import fcntl

    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = [line for line in open(path).read().splitlines() if line.strip()]
        count = path + ".n"
        n = int(open(count).read() or 0) if os.path.exists(count) else 0
        if n >= len(lines):
            return None
        with open(count, "w") as fh:
            fh.write(str(n + 1))
    return json.loads(lines[n])


def _claude(args):
    """Claude Code: `--version`, `auth status`, and `-p` with stream-json in and out."""
    if args[:1] == ["--version"]:
        print("9.9.9 (Claude Code)")
        sys.exit(0)
    if args[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}))
        sys.exit(0)
    if args[:1] != ["-p"]:
        sys.exit(2)
    message = json.loads(sys.stdin.readline())["message"]
    texts = [c["text"] for c in message["content"] if c["type"] == "text"]
    images = [c for c in message["content"] if c["type"] == "image"]
    log = os.environ.get("FAKE_CODEX_LOG")
    if log:
        with open(log, "a") as fh:
            fh.write(json.dumps({"args": args, "prompt": "\n".join(texts), "cwd": os.getcwd(),
                                 "images": len(images), "tool": "claude"}) + "\n")
    scripted = _next_scripted()
    if scripted and scripted.get("delay"):
        time.sleep(float(scripted["delay"]))
    print(json.dumps({"type": "system", "subtype": "init"}))
    if os.environ.get("FAKE_CODEX_FAIL") == "1" or (scripted and scripted.get("fail")):
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "result": "something went wrong"}))
        sys.exit(1)
    reply = os.environ.get("FAKE_CODEX_REPLY", json.dumps({"ok": True, "reply": "hello"}))
    if scripted and "reply" in scripted:
        r = scripted["reply"]
        reply = r if isinstance(r, str) else json.dumps(r)
    structured = None
    if "--json-schema" in args:
        try:
            structured = json.loads(reply)
        except ValueError:
            structured = None
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": reply,
                      **({"structured_output": structured} if structured is not None else {})}))
    sys.exit(0)


args = sys.argv[1:]
if os.environ.get("FAKE_AS") == "claude":
    _claude(args)
if args[:1] == ["--version"]:
    print("codex-cli 9.9.9")
    sys.exit(0)
if args[:2] == ["features", "list"]:  # FAKE_CODEX_FEATURES (comma-separated) replaces the real list
    names = os.environ.get("FAKE_CODEX_FEATURES", "apps,plugins,remote_plugin,multi_agent,image_generation,goals,"
                           "browser_use,computer_use,in_app_browser,web_search_request").split(",")
    for name in names:
        print(f"{name:<40} stable             true")
    sys.exit(0)
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
    sys.exit(0)
if args[:1] == ["app-server"]:  # just enough JSON-RPC for the usage check
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("id") == 1:
            print(json.dumps({"id": 1, "result": {"userAgent": "fake"}}), flush=True)
        elif msg.get("id") == 2:
            print(json.dumps({"id": 2, "result": {"rateLimits": {
                "planType": "plus", "primary": {"usedPercent": 6, "windowDurationMins": 300, "resetsAt": 1792241157},
                "secondary": {"usedPercent": 1, "windowDurationMins": 10080, "resetsAt": 1792827957}}}}), flush=True)
            sys.exit(0)
    sys.exit(0)
if args[:1] != ["exec"]:
    sys.exit(2)

prompt = sys.stdin.read()
log = os.environ.get("FAKE_CODEX_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"args": args, "prompt": prompt, "cwd": os.getcwd()}) + "\n")
scripted = _next_scripted()
if scripted and scripted.get("delay"):
    time.sleep(float(scripted["delay"]))
if os.environ.get("FAKE_CODEX_FAIL") == "1" or (scripted and scripted.get("fail")):
    print("error: something went wrong", file=sys.stderr)
    sys.exit(1)
reply = os.environ.get("FAKE_CODEX_REPLY", json.dumps({"ok": True, "reply": "hello"}))
if scripted and "reply" in scripted:
    r = scripted["reply"]
    reply = r if isinstance(r, str) else json.dumps(r)
out = args[args.index("--output-last-message") + 1]
with open(out, "w") as fh:
    fh.write(reply)
