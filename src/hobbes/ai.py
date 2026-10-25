"""The AI engine. Every AI call goes through `ask`, which runs the AI the owner chose in setup, signed in with
their own plan: Claude (Claude Code, `claude -p`) or ChatGPT (Codex, `codex exec`). Features never call either
themselves, so a provider is one function here.

Each call runs in its own scratch folder, with no saved session, ignoring the owner's own settings for that tool
(what's trusted for coding isn't inherited), with every tool switched off but web search (and, for Claude, reading
the pages found), and photos attached to the prompt:
* Codex: `--ignore-user-config`, read-only sandbox, and everything but thinking, web search and photos off (OFF),
  above all the ChatGPT apps connected to the account (Gmail with send and delete, Calendar, Drive).
* Claude: `--restricted --safe-mode --strict-mcp-config` (no settings, plugins, hooks, MCP servers or commands),
  `--tools` names only WebSearch and WebFetch (or nothing), and `dontAsk` refuses anything else.
With a JSON schema, the answer must be exactly that shape, and it's checked again before it's returned.

At most two calls run at once; each is recorded in `ai_runs` (kind, time taken, outcome).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import config, db, jobs

_SLOTS = threading.BoundedSemaphore(2)
# Codex features the dashboard's calls never get. "apps" is the one that matters most: without this, every call
# can use the ChatGPT apps on the owner's account (found on codex 0.162: 202 tools, Gmail send and delete
# among them). Switched off with -c (an unknown --disable stops Codex), and checked against `codex features
# list` once per Codex binary: a name it no longer knows means calls are refused, never run with it maybe on.
OFF = ("apps", "plugins", "remote_plugin", "multi_agent", "image_generation", "goals", "browser_use",
       "computer_use", "in_app_browser")
_FEATURES_CHECKED: dict[str, str | None] = {}
_STATUS_CACHE: dict[str, dict[str, Any]] = {}
_PATH_EXTRA = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")]

PROVIDERS = {
    "claude": {"name": "Claude", "tool": "Claude Code", "command": "claude", "env": "HOBBES_CLAUDE",
               "install": "Install Claude Code (brew install --cask claude-code), then run `claude` once to sign in.",
               "sign_in": "Run `claude` in Terminal and sign in with your Claude account."},
    "codex": {"name": "ChatGPT", "tool": "Codex", "command": "codex", "env": "HOBBES_CODEX",
              "install": "Install Codex (brew install codex), then run `codex login` to sign in with ChatGPT.",
              "sign_in": "Run `codex login` in Terminal and sign in with your ChatGPT account."},
}
SETTING = "ai.provider"


class AIError(Exception):
    user_facing = True


def tool_path(provider: str) -> str | None:
    spec = PROVIDERS[provider]
    if os.environ.get(spec["env"]):
        return os.environ[spec["env"]]
    return shutil.which(spec["command"], path=os.pathsep.join([os.environ.get("PATH", ""), *_PATH_EXTRA]))


def codex_path() -> str | None:
    return tool_path("codex")


def _env() -> dict[str, str]:
    # Claude Code refuses to start inside another Claude Code session; the dashboard's calls are never that.
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env["PATH"] = os.pathsep.join([env.get("PATH", ""), *_PATH_EXTRA])
    return env


def provider(conn: Any = None) -> str:
    """The AI the owner chose; until they do, whichever is installed (Codex first)."""
    own = conn is None
    c = conn or db.connect()
    try:
        chosen = db.get_setting(c, SETTING)
    finally:
        if own:
            c.close()
    if chosen in PROVIDERS:
        return chosen
    return "claude" if not tool_path("codex") and tool_path("claude") else "codex"


def set_provider(conn: Any, name: str) -> None:
    if name not in PROVIDERS:
        raise ValueError("Choose claude or codex.")
    db.set_setting(conn, SETTING, name)


def _run_quick(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=_env())


def provider_status(name: str, refresh: bool = False) -> dict:
    """Whether that AI's tool is installed and signed in. Cached for five minutes (each check runs it)."""
    cached = _STATUS_CACHE.get(name)
    if not refresh and cached and cached["at"] > time.time() - 300:
        return cached["value"]
    spec = PROVIDERS[name]
    path = tool_path(name)
    value: dict[str, Any] = {"provider": name, "name": spec["name"], "tool": spec["tool"], "installed": bool(path),
                             "version": None, "signed_in": False, "plan": None, "detail": None}
    if path:
        try:
            v = _run_quick([path, "--version"])
            words = (v.stdout or v.stderr).strip().split()
            if v.returncode == 0 and words:
                value["version"] = words[0] if name == "claude" else words[-1]
            if name == "claude":
                s = _run_quick([path, "auth", "status"])
                try:
                    info = json.loads(s.stdout)
                except ValueError:
                    info = {}
                value["signed_in"] = bool(info.get("loggedIn"))
                value["plan"] = info.get("subscriptionType")
                value["detail"] = "Signed in" if value["signed_in"] else spec["sign_in"]
            else:
                s = _run_quick([path, "login", "status"])
                detail = (s.stdout or s.stderr).strip().splitlines()
                value["signed_in"] = s.returncode == 0 and "logged in" in (detail[0] if detail else "").lower()
                value["detail"] = (detail[0] if detail else None) if value["signed_in"] else spec["sign_in"]
        except (OSError, subprocess.SubprocessError) as e:
            value["detail"] = str(e)
    else:
        value["detail"] = spec["install"]
    _STATUS_CACHE[name] = {"at": time.time(), "value": value}
    return value


def status(refresh: bool = False, conn: Any = None) -> dict:
    """The chosen AI's status."""
    return provider_status(provider(conn), refresh)


def choices(refresh: bool = False, conn: Any = None) -> dict:
    return {"provider": provider(conn), "providers": [provider_status(n, refresh) for n in PROVIDERS]}


_USAGE_CACHE: dict[str, Any] = {}


def _window(w: dict | None) -> dict | None:
    if not isinstance(w, dict) or w.get("usedPercent") is None:
        return None
    return {"used_percent": float(w["usedPercent"]), "window_minutes": w.get("windowDurationMins"),
            "resets_at": w.get("resetsAt")}


def usage(refresh: bool = False, conn: Any = None) -> dict:
    """How much of the Codex allowance is used: the 5-hour session window and the weekly one, from Codex's
    own app-server (`account/rateLimits/read`, which costs nothing). Cached for two minutes. Claude Code
    doesn't tell other apps its limits, so for Claude only the plan is known."""
    value: dict[str, Any] = {"available": False, "plan": None, "session": None, "week": None, "detail": None}
    if provider(conn) == "claude":
        st = provider_status("claude")
        return {**value, "plan": st["plan"], "detail": "Claude Code doesn't share its limits with other apps."}
    if not refresh and _USAGE_CACHE.get("at", 0) > time.time() - 120:
        return _USAGE_CACHE["value"]
    path = codex_path()
    if not path:
        value["detail"] = "Codex isn't installed."
        return value
    try:
        p = subprocess.Popen([path, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, env=_env())
    except OSError as e:
        value["detail"] = str(e)
        return value
    lines: list[str] = []
    done = threading.Event()

    def read() -> None:
        assert p.stdout is not None
        for line in p.stdout:
            lines.append(line)
            if '"id":2' in line.replace(" ", ""):
                done.set()
                return
        done.set()

    threading.Thread(target=read, daemon=True).start()
    try:
        assert p.stdin is not None
        for msg in ({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"clientInfo": {"name": "hobbes", "title": "Hobbes at Home", "version": "0.1.0"}}},
                    {"jsonrpc": "2.0", "method": "initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"}):
            p.stdin.write(json.dumps(msg) + "\n")
            p.stdin.flush()
        done.wait(15)
    except OSError as e:
        value["detail"] = str(e)
    finally:
        p.kill()
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == 2:
            limits = (msg.get("result") or {}).get("rateLimits") or {}
            value.update(available=bool(limits), plan=limits.get("planType"), session=_window(limits.get("primary")),
                         week=_window(limits.get("secondary")),
                         detail=None if limits else (msg.get("error") or {}).get("message"))
    if not value["available"] and not value["detail"]:
        value["detail"] = "Codex didn't report its limits."
    _USAGE_CACHE.update(at=time.time(), value=value)
    return value


def features_problem(path: str) -> str | None:
    """Why calls can't run safely with this Codex (a switch in OFF it no longer knows), or None."""
    try:
        key = f"{path}:{Path(path).resolve().stat().st_mtime_ns}"
    except OSError:
        key = path
    if key in _FEATURES_CHECKED:
        return _FEATURES_CHECKED[key]
    try:
        r = subprocess.run([path, "features", "list"], capture_output=True, text=True, timeout=30, env=_env())
        known = {line.split()[0] for line in r.stdout.splitlines() if line.strip()}
        missing = [f for f in OFF if f not in known]
        problem = None if r.returncode == 0 and not missing else (
            f"This version of Codex doesn't have the switch {', '.join(missing) or '(none listed)'} the dashboard "
            "uses to keep its AI away from your connected apps (Gmail, Calendar, Drive), so AI calls are paused "
            "until the dashboard is updated for it.")
    except (OSError, subprocess.SubprocessError) as e:
        problem = f"Codex's features couldn't be checked ({e}), so AI calls are paused."
    _FEATURES_CHECKED[key] = problem
    return problem


def ask(prompt: str, *, schema: dict | None = None, images: list[Path] | tuple[Path, ...] = (),
        search: bool = False, kind: str = "ask", timeout: float = 300,
        conn: Any = None) -> Any:
    """Ask the chosen AI. With `schema` (a JSON Schema for the whole answer), the parsed JSON is returned;
    otherwise the answer's text. `images` are attached to the prompt; `search` lets it search the
    web. Raises AIError with a plain explanation on any failure."""
    name = provider(conn)
    spec = PROVIDERS[name]
    path = tool_path(name)
    if not path:
        raise AIError(f"{spec['tool']} isn't installed on the Mac. {spec['install']}")
    if name == "codex":
        problem = features_problem(path)
        if problem:
            raise AIError(problem)
    for img in images:
        if not Path(img).is_file():
            raise AIError(f"Image not found: {img}")
    config.secure_home()
    config.scratch_dir().mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ai-", dir=config.scratch_dir()))
    run = _claude if name == "claude" else _codex
    tool = spec["tool"]

    started, t0 = db.now(), time.monotonic()
    error: str | None = None
    try:
        with _SLOTS:
            text, structured = run(path, work, prompt, schema, images, search, timeout)
        if schema is None:
            if not text:
                raise AIError(f"{tool} finished without an answer.")
            return text
        answer = structured
        if answer is None:
            try:
                answer = json.loads(text)
            except ValueError:
                raise AIError(f"{tool}'s answer wasn't the JSON that was asked for.") from None
        problem = check_shape(answer, schema)
        if problem:
            raise AIError(f"{tool}'s answer didn't match the expected shape: {problem}")
        return answer
    except AIError as e:
        error = str(e)
        raise
    finally:
        _record(conn, kind, started, int((time.monotonic() - t0) * 1000), error, len(images), search)
        if error is None:
            shutil.rmtree(work, ignore_errors=True)


def _call(cmd: list[str], stdin: str, work: Path, timeout: float, tool: str) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=work, env=_env())
    except subprocess.TimeoutExpired:
        raise AIError(f"{tool} took longer than {timeout:g} seconds and was stopped.") from None
    except OSError as e:
        raise AIError(f"{tool} couldn't be started: {e}") from None
    return r


def _codex(path: str, work: Path, prompt: str, schema: dict | None, images: Any, search: bool,
           timeout: float) -> tuple[str, Any]:
    out = work / "answer.txt"
    cmd = [path, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
           "--sandbox", "read-only", "--cd", str(work), "--output-last-message", str(out), "--color", "never"]
    for feature in OFF:
        cmd += ["--config", f"features.{feature}=false"]
    if schema is not None:
        (work / "schema.json").write_text(json.dumps(schema))
        cmd += ["--output-schema", str(work / "schema.json")]
    cmd += [f"--image={Path(i).resolve()}" for i in images]
    if search:
        # `--search` belongs to the interactive codex only; exec takes the setting (checked on codex 0.162)
        cmd += ["--config", 'web_search="live"']
    if os.environ.get("HOBBES_CODEX_MODEL"):
        cmd += ["--model", os.environ["HOBBES_CODEX_MODEL"]]
    r = _call(cmd, prompt, work, timeout, "Codex")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise AIError("Codex failed: " + (" ".join(tail) or f"exit code {r.returncode}"))
    return (out.read_text().strip() if out.exists() else ""), None


# Claude Code's tools a call may use: none, or web search and reading the pages it finds.
CLAUDE_SEARCH_TOOLS = "WebSearch,WebFetch"


def _claude(path: str, work: Path, prompt: str, schema: dict | None, images: Any, search: bool,
            timeout: float) -> tuple[str, Any]:
    # Photos go in the message itself (stream-json input), so no file tool is needed to read them.
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in images:
        media = mimetypes.guess_type(str(img))[0] or "image/jpeg"
        content.append({"type": "image", "source": {"type": "base64", "media_type": media,
                                                    "data": base64.b64encode(Path(img).read_bytes()).decode()}})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    tools = CLAUDE_SEARCH_TOOLS if search else ""
    cmd = [path, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--restricted", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
           "--no-session-persistence", "--permission-mode", "dontAsk", "--tools", tools]
    if search:
        cmd += ["--allowedTools", tools]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    if os.environ.get("HOBBES_CLAUDE_MODEL"):
        cmd += ["--model", os.environ["HOBBES_CLAUDE_MODEL"]]
    r = _call(cmd, json.dumps(message) + "\n", work, timeout, "Claude Code")
    result: dict = {}
    for line in r.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "result":
            result = msg
    if r.returncode != 0 or not result or result.get("is_error") or result.get("subtype") != "success":
        why = str(result.get("result") or "").strip() or " ".join((r.stderr or r.stdout).strip().splitlines()[-3:])
        raise AIError("Claude Code failed: " + (why[:300] or f"exit code {r.returncode}"))
    return str(result.get("result") or "").strip(), result.get("structured_output")


def _record(conn: Any, kind: str, started: str, ms: int, error: str | None, images: int, search: bool) -> None:
    own = conn is None
    try:
        c = conn or db.connect()
        c.execute("INSERT INTO ai_runs (kind, started_at, duration_ms, ok, images, search, error) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)", (kind, started, ms, int(error is None), images, int(search), error))
        if own:
            c.close()
    except Exception:
        pass  # the record is a convenience; never fail a call over it


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def check_shape(value: Any, schema: dict, where: str = "answer") -> str | None:
    """A small check of the parts of JSON Schema the dashboard's schemas use (type, properties,
    required, items, enum). Codex enforces the schema already; this catches anything that slips."""
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    if types:
        ok = False
        for name in types:
            if name == "integer":
                ok = ok or (isinstance(value, int) and not isinstance(value, bool))
            elif name == "number":
                ok = ok or (isinstance(value, int | float) and not isinstance(value, bool))
            elif name in _TYPES:
                ok = ok or (isinstance(value, _TYPES[name]) and not (name != "boolean" and isinstance(value, bool)))
        if not ok:
            return f"{where} should be {' or '.join(types)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} should be one of {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{where} is missing {key!r}"
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                problem = check_shape(value[key], sub, f"{where}.{key}")
                if problem:
                    return problem
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            problem = check_shape(item, schema["items"], f"{where}[{i}]")
            if problem:
                return problem
    return None


CHECK_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reply": {"type": "string"}},
    "required": ["ok", "reply"],
    "additionalProperties": False,
}


@jobs.handler("ai.check")
def check_job(conn, payload: dict) -> dict:
    """A tiny call that proves the chosen AI works end to end from the dashboard."""
    t0 = time.monotonic()
    answer = ask("This is a connection test from a personal dashboard. Reply with ok set to true and "
                 "reply set to a short friendly greeting of at most eight words. Do not run any commands.",
                 schema=CHECK_SCHEMA, kind="ai.check", timeout=180, conn=conn)
    return {**answer, "seconds": round(time.monotonic() - t0, 1)}
