"""Plan usage limits for the Claude account signed in to Claude Code (what `/usage` shows).

Reads Claude Code's own sign-in on this device and asks Anthropic for the account's limits:
the current 5-hour session and the weekly limits, each as "% used" plus a reset time.

- The sign-in never leaves this device except to api.anthropic.com, and is never printed or saved.
- If the sign-in has expired, it is NOT refreshed here (that could sign Claude Code out).
  Opening Claude Code refreshes it, and the odometer picks it up again.
- The endpoint is the one Claude Code itself uses. It is not a public API, so its shape may change;
  anything unexpected shows as "not available" instead of crashing the odometer.

Standard library only.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Known limits, in the order /usage lists them. Unknown ones are added after these.
LABELS = [
    ("five_hour", "Current session"),
    ("seven_day", "This week · all models"),
    ("seven_day_opus", "This week · Opus"),
    ("seven_day_sonnet", "This week · Sonnet"),
    ("seven_day_oauth_apps", "This week · apps"),
]


def _config_dir():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def _read_oauth():
    """Claude Code's saved sign-in: a file on Linux/Windows, the Keychain on macOS."""
    raw = None
    path = _config_dir() / ".credentials.json"
    if path.exists():
        raw = path.read_text(encoding="utf-8")
    elif sys.platform == "darwin":
        try:
            raw = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            raw = None
    if not raw:
        return None
    try:
        return json.loads(raw).get("claudeAiOauth") or None
    except (ValueError, AttributeError):
        return None


def account_email():
    """Email of the account signed in to Claude Code (from its settings file), or None."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    path = Path(env).expanduser() / ".claude.json" if env else Path.home() / ".claude.json"
    try:
        acct = json.loads(path.read_text(encoding="utf-8")).get("oauthAccount") or {}
        email = acct.get("emailAddress")
        return email if isinstance(email, str) and "@" in email else None
    except (OSError, ValueError, AttributeError):
        return None


def _when(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def reset_text(when, now=None):
    """'resets 11:10 PM' today, 'resets Sat 9:00 AM' later in the week."""
    if not when:
        return ""
    now = now or datetime.now().astimezone()
    clock = when.strftime("%I:%M %p").lstrip("0")
    if when.date() == now.date():
        return f"resets {clock}"
    return f"resets {when.strftime('%a')} {clock}"


def fetch(timeout=10):
    """Returns {"ok": True, "plan": str|None, "limits": [{"key","label","pct","resets"}]}
    or {"ok": False, "error": "short reason for the card"}."""
    oauth = _read_oauth()
    if not oauth or not oauth.get("accessToken"):
        return {"ok": False, "error": "Sign in to Claude Code to see plan usage"}
    expires = oauth.get("expiresAt")
    if isinstance(expires, (int, float)) and expires / 1000 < time.time():
        return {"ok": False, "error": "Sign-in expired · open Claude Code to refresh"}

    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {oauth['accessToken']}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": "claude-odometer",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "error": "Sign-in not accepted · open Claude Code"}
        if e.code == 429:
            return {"ok": False, "error": "Busy · trying again shortly"}
        return {"ok": False, "error": f"Usage not available ({e.code})"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"ok": False, "error": "Offline · usage not available"}

    if not isinstance(body, dict):
        return {"ok": False, "error": "Usage not available"}
    known = dict(LABELS)
    order = [k for k, _ in LABELS] + sorted(k for k in body if k not in known)
    limits = []
    for key in order:
        v = body.get(key)
        if not isinstance(v, dict) or v.get("utilization") is None:
            continue
        try:
            pct = max(0.0, min(100.0, float(v["utilization"])))
        except (TypeError, ValueError):
            continue
        label = known.get(key) or key.replace("_", " ").capitalize()
        limits.append({"key": key, "label": label, "pct": pct, "resets": _when(v.get("resets_at"))})
    if not limits:
        return {"ok": False, "error": "No plan limits reported"}
    plan = oauth.get("subscriptionType")
    return {"ok": True, "plan": plan.capitalize() if isinstance(plan, str) else None, "limits": limits}


if __name__ == "__main__":
    from token_calc import utf8_stdout
    utf8_stdout()
    res = fetch()
    if not res["ok"]:
        print(res["error"])
        sys.exit(1)
    if res["plan"]:
        print(f"Plan: {res['plan']}" + (f"  ({account_email()})" if account_email() else ""))
    for lim in res["limits"]:
        bar = "█" * round(lim["pct"] / 5) + "░" * (20 - round(lim["pct"] / 5))
        print(f"{lim['label']:<26} {bar} {lim['pct']:5.1f}% used  {reset_text(lim['resets'])}")
