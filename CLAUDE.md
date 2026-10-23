# CLAUDE.md: Token Mileage (Claude Code Odometer)

Notes for a Claude Code session that installs, adapts or extends this project. Read this before changing code.

## What it is
A desktop widget plus a CLI that count the tokens Claude Code uses on one device and show the signed-in account's plan limits (like `/usage`). Python 3.9+ standard library only: **do not add pip dependencies**. The goal is that it runs anywhere Python + Tk runs.

## Install for the user (typical request: "set this up for me")
1. `python3 --version` (3.9+) and `python3 -c "import tkinter"`. On Linux, if Tk is missing, ask the user to run `sudo apt install python3-tk` (needs their password).
2. `python3 install.py --owner "<their name>"`. This creates the desktop shortcut (and an app-menu entry on Linux).
3. Launch it with `python3 token_popup.py &` (or the shortcut). Check: `python3 token_calc.py --today` prints numbers.
4. On Windows use `python`, and launch with `pythonw token_popup.py` so no console window stays open.

## Architecture
```
~/.claude/projects/**/*.jsonl ──► token_calc.Ledger ──► ledger.jsonl (own copy, survives 30-day cleanup)
                                       │
                                       ├──► token_calc.py CLI / --json / --html report
                                       └──► token_popup.App (refresh every 2 s)
~/.claude/sessions/*.json ───────────► live session dots (working / finished)
Claude Code sign-in ──► plan_usage.fetch() ──► api.anthropic.com/api/oauth/usage (every 120 s) ──► back-card bars
```

- **token_calc.py**
  - `parse_line()` turns one transcript line into a usage record. `Ledger` reads new lines incrementally and **dedupes by message id + request id**: each streamed reply is logged several times. Breaking this doubles every total.
  - `data_dir()` is the per-OS store (`ledger.jsonl`, `config.json` with `owner`).
  - `PRICES` are API list prices per model, used for cost estimates only.
- **token_popup.py**
  - `App` builds two "faces" (`build_front`, `build_back`) inside `self.card`, and `flip()` animates between them on a canvas.
  - `compute()` produces the totals for today, the last 7 days, this month and the forecast.
  - `plan_loop()` runs in a background thread and calls `plan_usage.fetch()`. `render_plan()` draws the bars (`PLAN_KEYS` decides which limits are shown). `fit_card()` resizes the card when the back's height changes.
  - Colours are in `C` (Claude Code palette). Sizes come from `W`, `H`.
- **plan_usage.py**
  - Reads Claude Code's OAuth sign-in: `$CLAUDE_CONFIG_DIR/.credentials.json` or `~/.claude/.credentials.json`; on macOS, the Keychain item `Claude Code-credentials`.
  - Calls the usage endpoint with `anthropic-beta: oauth-2025-04-20`. The response has keys like `five_hour`, `seven_day`, `seven_day_opus`, each `{utilization, resets_at}`.
  - Returns `{"ok", "plan", "limits":[{key,label,pct,resets}]}` or `{"ok": False, "error"}`.

## Rules when changing it
- **Never print, log, save or send the OAuth token** anywhere except `api.anthropic.com`. Never refresh it here: refreshing rotates tokens and can sign Claude Code out. If it has expired, tell the user to open Claude Code.
- The usage endpoint is **not a public API**. Keep every field access defensive. Unknown or missing data must show "Usage not available", never crash the widget.
- Poll the usage endpoint at most every 120 s, and back off on HTTP 429.
- Keep the UI thread free: network and file scans run in threads, and UI updates go through `root.after(...)`.
- Token totals must stay deduplicated, and the ledger must only grow (it is the history after Claude Code deletes old logs).
- `report.html` and `ledger.jsonl` contain the user's personal usage data. Never commit them (`report.html` is in `.gitignore`; the ledger lives outside the repo).
- Stay cross-platform: use `pathlib`, no shell-only tricks, and check `sys.platform` for OS-specific bits (Keychain, Windows DPI, desktop folder).

## Ideas to extend
- Show `seven_day_opus` / `seven_day_sonnet` too: add the keys to `PLAN_KEYS` in `token_popup.py`.
- Alerts: notify when the session limit passes 80% / 90%.
- Per-project budgets from `token_calc.py --json`.
- Combine several devices by syncing each device's `ledger.jsonl` to a shared folder (merge by the same message-id key).

## Quick checks after a change
```bash
python3 -c "import ast;[ast.parse(open(f).read()) for f in ('token_popup.py','token_calc.py','plan_usage.py')]"
python3 token_calc.py --today
python3 plan_usage.py            # plan bars in the terminal (needs Claude Code signed in)
python3 token_popup.py           # flip with ⇄ and check both faces
```
