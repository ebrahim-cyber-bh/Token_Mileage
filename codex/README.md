# Codex Token Mileage

By Alna (Ebrahim Alnasser).

A separate Codex version of the Claude Token Mileage desktop odometer. It keeps the rolling digits, compact flip card, hoverable session dots, RAM/disk indicators, and visible **By Alna** credit. The Codex accent is mint green.

## Open it

```bash
cd Token_Mileage/codex
python3 token_popup.py          # Ubuntu / macOS
py token_popup.py               # Windows (never python3 there)
```

Python 3.9+ and Tk are required; no pip packages or API keys are needed. Ubuntu: `sudo apt install python3-tk` if Tk is missing. Windows: the python.org installer includes Tk; use `py` in every command below. On Linux, run the widget from your graphical desktop; a sandbox without desktop-display access cannot show its window.

```bash
python3 install.py                 # desktop + application menu shortcuts
python3 install.py --launch        # open the widget
python3 install.py --autostart     # optional login startup
python3 install.py --uninstall     # remove shortcuts, keep history
python3 doctor.py                  # check logs, Tk, and signature
python3 token_calc.py --today
python3 token_calc.py --days 7
python3 token_calc.py --json
python3 plan_usage.py
python3 -m unittest -v
```

## What it shows

- **Front:** all recorded tokens, animated digits, recent-session dots, and RAM/disk usage. Hover a dot for its project/session. Mint pulsing means recent activity; green means quieter activity. These are log-based hints, not verified process status. A session disappears after 15 minutes without activity.
- **Back:** the latest recorded plan-limit snapshot, with percentages and reset times. The compact card omits the recorded-age status line; figures are still snapshots, not live readings. It does not contact OpenAI, read credentials, refresh your sign-in, or claim to show live account limits. The snapshot may come from another session or an earlier account; it is not tied to a verified current login. **Open usage ↗** opens chatgpt.com/settings/usage in your browser for the live figures, and **↻** re-reads the snapshot now. Log entries with empty limits are ignored, so the card keeps the last real figures.
- **CLI:** input, cached input, output, reasoning output, uncached input, total, and model/project/session breakdowns.

Input already includes cached input; output already includes reasoning. **Total = input + output.** Neither subset is added again. These are recorded token counts, not subscription percentages or a monetary bill. See [OpenAI's usage documentation](https://developers.openai.com/api/docs/guides/agents-api/observability).

## Data and limitations

Reads `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions` (default `~/.codex`). Only usage events, model/project metadata, and activity markers are stored; prompts and answers are not copied. A SQLite ledger in the platform's `codex-odometer` data directory keeps usage after source logs are removed. Set `CODEX_MILEAGE_DATA` to override it.

File offsets and usage updates commit together. Cumulative usage watermarks deduplicate the paired `token_usage_record` / `token_count` formats, log replays, and archived copies. Partial final lines are retried when complete. The app incrementally reads new log bytes off the UI thread.

Logs are an implementation detail and may change. Usage without cumulative session totals is not counted. Deleted history from before the first scan cannot be recovered. Ephemeral Codex runs (`--ephemeral`), including the current analysis team's runs, may not save session logs and therefore may be absent. A fork that starts with inherited cumulative usage can include that inherited baseline; local logs are not an authoritative billing ledger. A lower cumulative watermark is treated as a replay rather than inventing additional usage.

This app is a derivative of the local Claude Token Mileage app. Its original attribution and LICENSE are preserved. It has its own shortcuts and data store.
