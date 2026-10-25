# Hobbes at Home

A private home dashboard that runs on your own Mac: a food diary that reads your meals from a photo or a
line of text, your health data from Apple Health and WHOOP, and Hobbes AI, an assistant that researches
jobs for you. The AI is Claude or ChatGPT, used through your own plan. Everything you log stays on your Mac.

It's named after Hobbes, a German Shepherd.

## What it does

- **Diet.** Take a photo of a meal, or type what you had ("2 slices of toast, scrambled eggs, a flat
  white"). The AI lists each item with its amount and nutrients. Branded food is looked up online
  (the brand's site or a big grocery seller) and the label's numbers are used. You can correct, redo
  or add items, and Undo is always there. You also get daily targets from your goal, caffeine and
  alcohol against public guidance, history charts, and Log Again (what you usually have at this time
  of day comes first).
- **Health.** Steps, sleep, heart rate, workouts and weight from Apple Health (sent by your iPhone),
  and WHOOP if you have one. Each measure compares your last week with the four weeks before.
- **Hobbes AI.** Give it a job ("find a quiet hotel in Lisbon for 12–15 November, with a pool"). It
  searches the web and comes back with options, prices and links, or asks one question when a wrong
  guess would be costly. It can keep an eye on something ("tell me if the fare drops") or do a job
  every week. It only researches: it never books, pays, sends or signs in to anything.
- **Notifications** on your phone or laptop, when a job is done or something you watch changes.
- **Backups.** The catalog is copied every 6 hours on the Mac. You can also keep a daily encrypted
  copy in iCloud Drive.
- **Coding sessions.** A read-only list of your Claude Code and Codex sessions on this Mac.

## Privacy

- Hobbes at Home listens on your Mac only (127.0.0.1). Nobody else can reach it unless you publish it
  to your own Tailscale network, and even then only you can open it.
- Your data lives in `~/.hobbes`, readable by your macOS account only. Passwords and keys are kept in
  the Mac's Keychain.
- AI calls go to Anthropic (Claude) or OpenAI (ChatGPT) through Claude Code or Codex, signed in with
  your own account. What's sent: the meal notes and photos you log, the jobs you give Hobbes AI, a short
  summary of your day for Hobbes AI, and your health data only if you allow it. The usual terms of your
  plan apply.
- WHOOP data goes to the AI only after you turn on Share With the AI in Settings, WHOOP.
- It sends nothing anywhere else: no analytics and no tracking.

## What you need

- A Mac that stays on, or one you use every day.
- [Homebrew](https://brew.sh).
- One of these, signed in:
  - **Claude** (a Pro or Max plan) with [Claude Code](https://claude.com/claude-code), or
  - **ChatGPT** (a Plus or Pro plan) with [Codex](https://github.com/openai/codex).
- For your phone: [Tailscale](https://tailscale.com) (free for personal use) on the Mac and the phone.

## Install

1. Install uv, which installs Hobbes at Home and the Python it needs:

   ```sh
   brew install uv
   ```

2. Install your AI and sign in. Use one of these, or both:

   ```sh
   brew install --cask claude-code && claude    # Claude: sign in when it asks, then type /exit
   brew install codex && codex login            # ChatGPT
   ```

3. Install Hobbes at Home:

   ```sh
   uv tool install https://github.com/Yadub/hobbes-at-home/releases/download/v0.1.0/hobbes_at_home-0.1.0-py3-none-any.whl
   uv tool update-shell                         # once, so your shell finds the `hobbes` command
   ```

4. Set it up. It asks which AI to use (if you have both), where you live and what you mostly eat
   (meals are read the way they're usually made there), and whether to start it now and at every login.

   ```sh
   hobbes setup
   ```

5. Open <http://localhost:8780> on the Mac.

`hobbes doctor` checks everything. You can change the AI and the region in Settings at any time.

## Use it from your phone

1. Install Tailscale on the Mac and the phone, signed in to the same account.
2. Publish Hobbes at Home to your tailnet. Answer yes when `hobbes setup` asks, or run
   `hobbes service install --tailscale`. It's then at `https://<your-mac>.<your-tailnet>.ts.net:8780`.
   `hobbes doctor` shows the address.
3. In the Tailscale admin console (DNS page), turn on HTTPS Certificates. Notifications need it.
4. Open the address in Safari on the phone and choose Share, Add to Home Screen.

Only your own Tailscale account can open it. It refuses changes from anyone else, and from other sites.

## Connect Apple Health

Your iPhone sends readings to the Mac. This needs Tailscale (see above). Settings, Apple Health shows
the exact address and two ways to set it up:

- the Health Auto Export app (paid; it can also send workouts), or
- a Shortcut you build yourself (free).

## Connect WHOOP (optional)

WHOOP lets each member make their own developer app, and Hobbes at Home uses yours:

1. At [developer-dashboard.whoop.com](https://developer-dashboard.whoop.com), create an app.
   - **Scopes:** read:profile, read:body_measurement, read:cycles, read:recovery, read:sleep,
     read:workout, and offline.
   - **Redirect URIs:** `http://localhost:8780/api/whoop/callback`, plus your tailnet address followed
     by `/api/whoop/callback` if you use Tailscale.
   - **Privacy policy:** WHOOP asks for a link. Fill in
     [docs/whoop-privacy-policy.md](docs/whoop-privacy-policy.md) and publish it, for example as a
     public GitHub gist.
2. In Hobbes at Home, open Settings, WHOOP. Paste the Client ID and Client Secret, then tap Connect
   WHOOP. The secret is kept in the Keychain.

It syncs every 30 minutes. The AI sees WHOOP data only if you turn on Share With the AI.

## Commands

| Command | What it does |
|---|---|
| `hobbes setup` | First run, or change the AI, the region or the service |
| `hobbes doctor` | Check the setup |
| `hobbes service install` | Start it now and at every login (`--tailscale` to publish it to your tailnet) |
| `hobbes service stop` / `restart` / `logs` / `status` | Manage the background service |
| `hobbes service uninstall` | Stop it and remove the service (your data stays) |
| `hobbes backup` | Back up the catalog now |

## Update

```sh
uv tool install --force <the new version's address from Releases>
hobbes service restart
```

The catalog is upgraded by itself when it starts.

## Uninstall

```sh
hobbes service uninstall
uv tool uninstall hobbes-at-home
```

Your data stays in `~/.hobbes` until you delete it. Keychain items are under "hobbes-at-home" in
Keychain Access.

## Good to know

- **Your AI plan.** Every AI call uses your own Claude or ChatGPT plan and counts towards its limits.
  Reading a meal is one call (two when a label is looked up). A Hobbes AI job is one call per round.
  Watches and routines run on their own schedule, and Hobbes AI suggests ideas about twice a day.
- **The AI is locked down.** Each call runs in an empty scratch folder with no saved session. It
  ignores your own Claude Code or Codex settings, plugins and MCP servers. It can't run commands or
  change files, and the only tool it gets is web search. It never sees the connected apps on your
  ChatGPT account. Text from web pages is treated as information, never as instructions.
- **Not medical advice.** The numbers are estimates, from an AI and from your devices.
- **Not affiliated** with Apple, WHOOP, Anthropic, OpenAI or Tailscale. Their names are trademarks of
  their owners.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
