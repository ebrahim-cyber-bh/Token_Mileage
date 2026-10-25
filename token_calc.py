#!/usr/bin/env python3
"""Claude Code token calculator.

Reads the local Claude Code transcripts and totals the tokens used on this
device, by day, project, model and session. Works on Linux, macOS and Windows
with only the Python standard library.

Accuracy notes
- Each API response is logged on several lines; they are merged by message id,
  so nothing is counted twice.
- Claude Code deletes old transcripts (after 30 days by default). Every
  response seen is also saved to a small ledger file, so totals never go down.
- Costs (CLI only) are estimates at API list prices.
"""
import argparse
import getpass
import hashlib
import html
import json
import os
import socket
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIELDS = ("input", "output", "cache_write", "cache_read")
READ_BLOCK = 1 << 20          # log files are read in 1 MB pieces to keep memory low


# ---------- locations and settings ----------

# On Windows, hide the console window that would flash up for each subprocess.
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def utf8_stdout():
    """Windows pipes default to a legacy code page that can't print "—", "█" or "✻"."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def projects_dirs():
    dirs = [claude_dir() / "projects", Path.home() / ".config" / "claude" / "projects"]
    seen, out = set(), []
    for d in dirs:
        if d.exists() and d.resolve() not in seen:
            seen.add(d.resolve())
            out.append(d)
    return out


def data_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "claude-odometer"
    d.mkdir(parents=True, exist_ok=True)
    return d


def owner_name():
    """Name shown on the reports: config file, env var, git name, then OS user."""
    try:
        name = json.loads((data_dir() / "config.json").read_text(encoding="utf-8")).get("owner")
        if name:
            return name
    except (OSError, ValueError):
        pass
    if os.environ.get("CLAUDE_ODOMETER_OWNER"):
        return os.environ["CLAUDE_ODOMETER_OWNER"]
    try:
        name = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True,
                              text=True, timeout=3, **NO_WINDOW).stdout.strip()
        if name:
            return name
    except (OSError, subprocess.SubprocessError):
        pass
    return getpass.getuser()


# ---------- prices (CLI only) ----------

# USD per million tokens: input, output, cache read. Cache writes: 5 min = 1.25x input, 1 h = 2x input.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}


def cost_of(model, u, fast=False):
    p = PRICES.get(model) or next((PRICES[k] for k in sorted(PRICES, key=len, reverse=True)
                                   if model.startswith(k)), None)
    if not p:
        return 0.0
    inp, out, read = p
    c = (u["input"] * inp + u["output"] * out + u["cw5m"] * inp * 1.25
         + u["cw1h"] * inp * 2.0 + u["cache_read"] * read) / 1_000_000
    return c * (2.0 if fast else 1.0)


# ---------- parsing ----------

def project_name(cwd, folder):
    if cwd:
        home = str(Path.home())
        return "~" + cwd[len(home):] if cwd.startswith(home) else cwd
    return folder


def make_record(when, model, project, session, u, fast):
    u = dict(u)
    u["cache_write"] = u["cw5m"] + u["cw1h"]
    return {"when": when, "model": model, "project": project, "session": session,
            "u": u, "fast": fast, "tokens": sum(u[f] for f in FIELDS), "cost": cost_of(model, u, fast)}


def parse_line(line, folder, stem):
    """Turn one transcript line into (key, record), or None if it holds no usage."""
    if '"usage"' not in line:
        return None
    try:
        e = json.loads(line)
    except ValueError:
        return None
    msg = e.get("message") or {}
    usage = msg.get("usage")
    model = msg.get("model", "")
    if not isinstance(usage, dict) or not model or model.startswith("<"):
        return None
    try:
        when = datetime.fromisoformat(e.get("timestamp").replace("Z", "+00:00")).astimezone()
    except (AttributeError, ValueError):
        return None
    cc = usage.get("cache_creation") or {}
    cw_total = usage.get("cache_creation_input_tokens", 0) or 0
    cw1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
    cw5m = cc.get("ephemeral_5m_input_tokens", cw_total - cw1h) or 0
    u = {"input": usage.get("input_tokens", 0) or 0, "output": usage.get("output_tokens", 0) or 0,
         "cw5m": cw5m, "cw1h": cw1h, "cache_read": usage.get("cache_read_input_tokens", 0) or 0}
    key = f"{msg['id']}|{e.get('requestId', '')}" if msg.get("id") else hashlib.sha1(line.encode()).hexdigest()
    return key, make_record(when, model, project_name(e.get("cwd"), folder),
                            e.get("sessionId", stem), u, usage.get("speed") == "fast")


def parse_title(line):
    """Session title lines: (session id, title) or None."""
    if '"ai-title"' not in line and '"custom-title"' not in line:
        return None
    try:
        e = json.loads(line)
    except ValueError:
        return None
    if e.get("type") == "custom-title":
        title = e.get("customTitle") or e.get("title")
        return (e.get("sessionId"), title, True) if title else None
    if e.get("type") == "ai-title" and e.get("aiTitle"):
        return e.get("sessionId"), e["aiTitle"], False
    return None


# ---------- ledger ----------

U_KEYS = ("input", "output", "cw5m", "cw1h", "cache_read")


class Ledger:
    """All responses ever seen on this device. Reads new transcript lines incrementally."""

    def __init__(self):
        self.path = data_dir() / "ledger.jsonl"
        self.records = {}
        self.titles = {}           # session id -> (title, is_custom)
        self.offsets = {}
        self.partial = {}
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        lines = 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    lines += 1
                    try:
                        d = json.loads(line)
                        rec = make_record(datetime.fromisoformat(d["t"]).astimezone(), d["m"], d["p"], d["s"],
                                          dict(zip(U_KEYS, d["u"])), bool(d.get("x")))
                    except (ValueError, KeyError, TypeError):
                        continue
                    self._merge(d["k"], rec)
        except OSError:
            pass
        if lines > len(self.records) * 1.5 + 200:
            self._rewrite()

    def _row(self, key, r):
        return json.dumps({"k": key, "t": r["when"].isoformat(), "m": r["model"], "p": r["project"],
                           "s": r["session"], "u": [r["u"][k] for k in U_KEYS], "x": int(r["fast"])})

    def _rewrite(self):
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for k, r in self.records.items():
                fh.write(self._row(k, r) + "\n")
        os.replace(tmp, self.path)

    def _merge(self, key, rec):
        """Keep the largest value of each counter. Returns True if anything changed."""
        old = self.records.get(key)
        if old is None:
            self.records[key] = rec
            return True
        if all(rec["u"][k] <= old["u"][k] for k in U_KEYS):
            return False
        u = {k: max(rec["u"][k], old["u"][k]) for k in U_KEYS}
        self.records[key] = make_record(old["when"], old["model"], old["project"], old["session"], u, old["fast"])
        return True

    def scan(self):
        """Read new transcript lines. Returns the number of new or updated responses."""
        changed = []
        for root in projects_dirs():
            for path in root.glob("**/*.jsonl"):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                start = self.offsets.get(path, 0)
                if size < start:
                    start, self.partial[path] = 0, b""
                if size == start:
                    continue
                # Read 1 MB at a time: logs can be hundreds of MB, and most lines hold no usage.
                try:
                    with open(path, "rb") as fh:
                        fh.seek(start)
                        rest = self.partial.get(path, b"")
                        left = size - start
                        while left > 0:
                            block = fh.read(min(left, READ_BLOCK))
                            if not block:
                                break
                            left -= len(block)
                            lines = (rest + block).split(b"\n")
                            rest = lines.pop()
                            self._take(lines, path, changed)
                except OSError:
                    continue
                self.offsets[path] = size - left
                self.partial[path] = rest
        if changed:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    for k in dict.fromkeys(changed):
                        fh.write(self._row(k, self.records[k]) + "\n")
            except OSError:
                pass
        return len(changed)

    def _take(self, lines, path, changed):
        with self.lock:
            for raw in lines:
                if b'"usage"' not in raw and b'-title"' not in raw:
                    continue
                line = raw.decode("utf-8", "replace")
                t = parse_title(line)
                if t and t[0] and (t[2] or not self.titles.get(t[0], ("", False))[1]):
                    self.titles[t[0]] = (t[1], t[2])
                hit = parse_line(line, path.parent.name, path.stem)
                if hit and self._merge(*hit):
                    changed.append(hit[0])

    def snapshot(self):
        with self.lock:
            return list(self.records.values())


def load(since=None):
    led = Ledger()
    led.scan()
    return [r for r in led.snapshot() if not since or r["when"] >= since]


# ---------- summaries ----------

def empty():
    return {f: 0 for f in FIELDS} | {"cost": 0.0, "calls": 0, "total": 0}


def add(bucket, r):
    for f in FIELDS:
        bucket[f] += r["u"][f]
    bucket["total"] += r["tokens"]
    bucket["cost"] += r["cost"]
    bucket["calls"] += 1


def summarise(rows):
    s = {"all": empty(), "day": defaultdict(empty), "project": defaultdict(empty),
         "model": defaultdict(empty), "session": defaultdict(empty), "session_info": {}}
    for r in rows:
        add(s["all"], r)
        add(s["day"][r["when"].strftime("%Y-%m-%d")], r)
        add(s["project"][r["project"]], r)
        add(s["model"][r["model"]], r)
        add(s["session"][r["session"]], r)
        info = s["session_info"].setdefault(r["session"], {"project": r["project"], "first": r["when"]})
        info["first"] = min(info["first"], r["when"])
    return s


def n(x):
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if x >= size:
            return f"{x / size:.2f}{unit}"
    return str(int(x))


def money(x):
    return f"${x:,.2f}"


def table(title, items, limit=None):
    print(f"\n{title}")
    print(f"  {'':34} {'input':>8} {'output':>8} {'cache wr':>9} {'cache rd':>9} {'total':>9} {'est. cost':>11}")
    for name, b in items[:limit]:
        label = name if len(name) <= 34 else "…" + name[-33:]
        print(f"  {label:34} {n(b['input']):>8} {n(b['output']):>8} {n(b['cache_write']):>9} "
              f"{n(b['cache_read']):>9} {n(b['total']):>9} {money(b['cost']):>11}")


def by_cost(d):
    return sorted(d.items(), key=lambda kv: kv[1]["cost"], reverse=True)


def print_report(s, args):
    a = s["all"]
    print(f"Claude Code token usage — {args.owner} @ {socket.gethostname()}")
    print(f"Period: {args.period_label}   API calls: {a['calls']:,}")
    print(f"Total tokens: {a['total']:,}   Estimated API cost: {money(a['cost'])}")
    table("By day (latest first)", sorted(s["day"].items(), reverse=True), args.top)
    table("By model", by_cost(s["model"]))
    table("By project", by_cost(s["project"]), args.top)
    sess = [(f"{s['session_info'][k]['first']:%m-%d %H:%M} {s['session_info'][k]['project'].split('/')[-1]}", v)
            for k, v in by_cost(s["session"])]
    table("Top sessions", sess, args.top)
    print("\nCosts are estimates at API list prices. On a Pro/Max plan this is the API-equivalent value, not your bill.")


def html_report(s, args):
    a = s["all"]
    days = sorted(s["day"].items())
    max_day = max((b["cost"] for _, b in days), default=0) or 1
    esc = html.escape

    def rows(items, limit=None):
        return "\n".join(
            f"<tr><td>{esc(name)}</td><td>{n(b['input'])}</td><td>{n(b['output'])}</td>"
            f"<td>{n(b['cache_write'])}</td><td>{n(b['cache_read'])}</td><td>{n(b['total'])}</td>"
            f"<td>{money(b['cost'])}</td></tr>" for name, b in items[:limit])

    head = ("<tr><th>Name</th><th>Input</th><th>Output</th><th>Cache write</th>"
            "<th>Cache read</th><th>Total</th><th>Est. cost</th></tr>")
    bars = "\n".join(
        f'<div class="bar" title="{d}: {money(b["cost"])} · {n(b["total"])} tokens">'
        f'<span style="height:{max(2, b["cost"] / max_day * 100):.1f}%"></span><i>{d[5:]}</i></div>'
        for d, b in days[-60:])
    sess = [(f"{s['session_info'][k]['first']:%Y-%m-%d %H:%M} · {s['session_info'][k]['project']}", v)
            for k, v in by_cost(s["session"])]
    cache_hit = a["cache_read"] / max(1, a["cache_read"] + a["cache_write"] + a["input"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Code Tokens — {esc(args.owner)}</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e5e4df;--accent:#c96442}}
@media (prefers-color-scheme:dark){{:root{{--bg:#191917;--card:#232321;--ink:#ecebe6;--mute:#9c9b95;--line:#363632;--accent:#e08a6a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:32px 16px}}h1{{margin:0;font-size:26px}}
.sub{{color:var(--mute);margin:4px 0 24px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.k{{color:var(--mute);font-size:13px}}.v{{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums}}
h2{{font-size:17px;margin:32px 0 10px}}.chart{{display:flex;align-items:flex-end;gap:3px;height:180px;overflow-x:auto;padding-bottom:20px}}
.bar{{flex:1;min-width:12px;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}}
.bar span{{background:var(--accent);border-radius:3px 3px 0 0;display:block}}
.bar i{{position:absolute;bottom:-18px;font-size:9px;color:var(--mute);font-style:normal;left:50%;transform:translateX(-50%) rotate(-45deg);white-space:nowrap}}
.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;white-space:normal;word-break:break-all}}th{{color:var(--mute);font-weight:500}}
footer{{color:var(--mute);font-size:13px;margin-top:32px}}
</style></head><body><main>
<h1>Claude Code token usage</h1>
<p class="sub">{esc(args.owner)} · device <b>{esc(socket.gethostname())}</b> · {esc(args.period_label)} · generated {datetime.now():%Y-%m-%d %H:%M}</p>
<div class="grid">
<div class="card"><div class="k">Estimated API cost</div><div class="v">{money(a['cost'])}</div></div>
<div class="card"><div class="k">Total tokens</div><div class="v">{a['total']:,}</div></div>
<div class="card"><div class="k">Output tokens</div><div class="v">{a['output']:,}</div></div>
<div class="card"><div class="k">Cache read share</div><div class="v">{cache_hit:.0%}</div></div>
<div class="card"><div class="k">API calls</div><div class="v">{a['calls']:,}</div></div>
<div class="card"><div class="k">Sessions</div><div class="v">{len(s['session']):,}</div></div>
</div>
<h2>Daily cost (last 60 active days)</h2><div class="card chart">{bars}</div>
<h2>By model</h2><div class="card wrap"><table>{head}{rows(by_cost(s['model']))}</table></div>
<h2>By project</h2><div class="card wrap"><table>{head}{rows(by_cost(s['project']), args.top)}</table></div>
<h2>By day</h2><div class="card wrap"><table>{head}{rows(sorted(s['day'].items(), reverse=True), args.top)}</table></div>
<h2>Top sessions</h2><div class="card wrap"><table>{head}{rows(sess, args.top)}</table></div>
<footer>Costs are estimates at Anthropic API list prices. On a Pro/Max subscription this is the API-equivalent value of your usage, not what you are billed.</footer>
</main></body></html>"""


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Claude Code token calculator for this device.")
    ap.add_argument("--days", type=int, help="only the last N days")
    ap.add_argument("--since", help="only from this date (YYYY-MM-DD)")
    ap.add_argument("--today", action="store_true", help="only today")
    ap.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    ap.add_argument("--html", nargs="?", const="report.html", help="also write an HTML report")
    ap.add_argument("--json", action="store_true", help="print totals as JSON")
    ap.add_argument("--owner", help="name shown on the report")
    args = ap.parse_args()
    args.owner = args.owner or owner_name()

    since = None
    now = datetime.now().astimezone()
    if args.today:
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        args.period_label = f"today ({since:%Y-%m-%d})"
    elif args.days:
        since = now - timedelta(days=args.days)
        args.period_label = f"last {args.days} days"
    elif args.since:
        since = datetime.fromisoformat(args.since).astimezone()
        args.period_label = f"since {args.since}"
    else:
        args.period_label = "all time"

    if not projects_dirs():
        sys.exit(f"No Claude Code data found in {claude_dir() / 'projects'}")

    s = summarise(load(since))
    if args.json:
        out = dict(s["all"])
        out["by_model"] = {m: dict(b) for m, b in s["model"].items()}
        out["owner"], out["device"], out["period"] = args.owner, socket.gethostname(), args.period_label
        print(json.dumps(out, indent=2))
    else:
        print_report(s, args)

    if args.html:
        path = Path(args.html)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        path.write_text(html_report(s, args), encoding="utf-8")
        print(f"\nHTML report: {path}")


if __name__ == "__main__":
    main()
