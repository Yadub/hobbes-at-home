# Working on Hobbes at Home

## How it fits together

- **Backend:** Python 3.13, FastAPI and SQLite, in `src/hobbes`.
- **Frontend:** TypeScript and React, built by Vite from `web/` into `src/hobbes/web/static/` (not
  committed; the wheel includes it).
- **Access** (`web/access.py`): it listens on 127.0.0.1 only, and `tailscale serve` can publish it to
  the owner's tailnet. The owner is anyone at the Mac, or a request that Tailscale forwards from the
  Mac's own Tailscale login. Changes are accepted only from its own pages.
- **AI** (`ai.py`): every call goes through `ai.ask`, which runs the AI the owner chose. That is
  Claude through `claude -p`, or ChatGPT through `codex exec`. Each call runs read-only in a scratch
  folder, ignores the owner's own settings for that tool, and gets no tool but web search. With a JSON
  schema, the answer is checked again before it's returned. Prompts fill in the owner's region with
  `region.fill` (country, what they eat, currency, local grocery sellers).
- **Jobs** (`jobs.py`): slow or scheduled work goes through a table and a worker inside the app.
- **Secrets** live in the macOS Keychain (`secrets.py`), never in the catalog or in files.
- **Diet** (`diet/`): the AI reads meals into items. Branded items get a second call that looks up
  the label online. Caffeine and alcohol are tracked too.
- **Health** (`health.py`, `insights.py`, `whoop.py`): Apple Health readings are posted by the
  iPhone. WHOOP is synced through the owner's own developer app. WHOOP data reaches the AI only after
  the owner opts in (`whoop.shared_with_ai`).
- **Hobbes AI** (`assistant/`): research jobs, watches and routines, and ideas. It never books, pays,
  sends or signs in. `actions.py` records proposed actions, and nothing performs them.
- **Data folder:** `~/.hobbes` (catalog, backups, logs, uploads). `HOBBES_HOME` moves it.

## Rules the code keeps

- **Non-destructive.** Removals are soft (`deleted_at`). Edits go through `changes.py`, so they can be
  undone.
- **Migrations only add** (new tables, new columns). Never drop or rebuild a table, and never change a
  released migration.
- **Nothing outward-facing happens without the owner.** The AI only researches.
- **Wording:** plain and specific, in British spelling.

## Commands

```sh
uv sync                                   # Python and its tools
npm --prefix web ci                       # frontend packages
uv run pytest -q                          # hermetic: scratch data folder, fake Claude and Codex, no Keychain
uv run ruff check src tests && uv run pyright
npm --prefix web run gen:api              # after changing the API: regenerate the frontend's types
npm --prefix web run build                # type-checks, then builds into src/hobbes/web/static
uv build                                  # the wheel, with the built pages inside
```

- **Trial runs** use a scratch data folder:
  `HOBBES_HOME=/tmp/hobbes-trial HOBBES_SECRETS=memory uv run hobbes serve --port 8781`.
  `npm --prefix web run dev` serves the pages with live reload and passes `/api` to port 8781.
- **Fake AI:** `HOBBES_CODEX=tests/fake_codex.py` or `HOBBES_CLAUDE=tests/fake_claude.py` stand in for
  the real tools. `FAKE_CODEX_REPLY` gives the reply, and `FAKE_CODEX_REPLIES` (a file of JSON lines)
  gives one reply per call.
- **Design:** Apple's own apps are the reference (system colours, SF type, grouped lists, large titles,
  sheets). Colours are tokens in `web/src/styles/theme.css`. Check UI changes at phone and desktop widths.
- **Requests:** POSTs from curl need no Origin header. From a browser, they must be JSON or carry
  `X-Hobbes: 1`.
- **Dependencies** are pinned by date: `exclude-newer` in `pyproject.toml`, and
  `npm install --before=<date>` for the frontend. Upgrade on purpose: move the date, upgrade, then run
  everything.
