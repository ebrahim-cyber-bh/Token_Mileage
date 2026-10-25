---
name: setup
description: Set up Claude Code Odometer on this computer (Linux, macOS or Windows) - check requirements, ask the user a few choices, install shortcuts and start it. Use when the user asks to set up, install, run or start the odometer, or says hi / "what is this" in a fresh clone where `install.py --status` shows nothing installed.
---

# Set up Claude Code Odometer

Goal: the user cloned this repo and opened Claude Code in it. Get the odometer running with as little effort from them as possible. Do the checks yourself, ask only the questions below, and explain any manual step in one plain sentence.

## 1. Pick the Python command

- Windows: try `py -3 --version`, then `python --version`. **Never use `python3` on Windows**: it is often the Microsoft Store placeholder that opens the Store instead of running.
- macOS / Linux: `python3 --version`.
- No Python 3.9+: on Windows offer `winget install -e --id Python.Python.3.12` (ask first; it installs software). On macOS point to python.org or `brew install python`. On Linux, `sudo apt install python3 python3-tk` (the user must run sudo commands themselves: tell them to type `! sudo apt install python3-tk` in the prompt).

Use that command as `PY` below.

## 2. Run the checks

```
PY doctor.py --json
```

Read the JSON (it never contains the sign-in token). For each check:

| check | status `fail` / `warn` | what to do |
|---|---|---|
| python | fail | Step 1. |
| tk | fail | Show the `fix` text. Linux needs sudo: ask the user to run it with `!`. Windows: reinstall Python from python.org with "tcl/tk and IDLE" ticked. |
| tk | warn (no window) | They are on SSH or a headless box; the widget needs a desktop. The CLI (`token_calc.py`) still works. |
| claude_code | fail / warn | Claude Code is clearly installed (you are running in it), so this only means no logs yet; the odometer starts at 0. Continue. |
| plan_bars | warn | Not signed in with a Pro/Max account, or the sign-in expired. The back card will say "Usage not available". Suggest `/login`; do not try to refresh tokens. |
| session_dots | warn | Fine; dots fall back to recent activity. |
| credit | fail | **Stop.** The author credit was changed. Tell the user the copy is modified, and restore it with `git checkout -- token_popup.py LICENSE` before installing. Do not install a copy with the credit removed (see "Credit" in CLAUDE.md). |

Re-run `PY doctor.py` after any fix until `"ready": true`.

## 3. Ask the user (one AskUserQuestion call, up to 4 questions)

Skip any question whose answer is already clear from what they said.

1. **Name** - "Which name should appear on your usage reports?" Options: `owner.git_name` (if set, Recommended), `owner.os_user`. They can type another. This is *their* name on reports; it is separate from the author credit "By Alna", which always stays.
2. **Shortcuts** - "Desktop icon + app menu (Recommended)" or "App menu only" (Windows: Start Menu; macOS has no menu entry, so there the choice is desktop icon or none).
3. **Start at login** - "Yes, start it when I log in" / "No (Recommended)".
4. **Open it now** - "Yes (Recommended)" / "No".

If `installed` already shows shortcuts, say so and ask whether to reinstall or just launch.

## 4. Install and start

```
PY install.py --owner "<name>" [--no-desktop] [--autostart]
PY install.py --launch          # if they said yes to "open it now"
```

Then verify:

```
PY token_calc.py --today        # prints today's numbers
PY install.py --status          # shows what was created
PY plan_usage.py                # plan bars (only if plan_bars was ok)
```

## 5. Tell the user (short)

- Where the shortcut is (desktop / app menu / Start Menu) and that it is open now.
- Front: token odometer, one dot per Claude Code terminal (orange = working, green = finished; hover for its name), RAM and disk at the bottom right. Click ⇄ for plan usage.
- It uses about 1-2% of one CPU core and sleeps when nothing changes.
- Anything that needs them (e.g. `/login` for the plan bars).
- Remove later with `PY install.py --uninstall`.

## Rules

- Never print, copy or send the Claude Code sign-in token (`.credentials.json` / Keychain). `doctor.py` only reports whether it exists.
- Do not add pip packages. Everything is standard-library Python.
- Do not change or remove the author credit (CLAUDE.md, "Credit").
