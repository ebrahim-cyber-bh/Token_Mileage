#!/usr/bin/env python3
"""Claude Code Odometer — a live token counter in Claude Code colours.

Front: rolling odometer of every token used on this device, plus one dot per
open Claude Code terminal (orange pulse = working, green glow = finished;
hover for the session name, shown in the header).
Back (flip with ⇄): the account's plan usage like /usage (current session and weekly
limits, % used, reset time). Both faces are the same compact size.
"""
import base64
import json
import math
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from token_calc import Ledger, claude_dir  # noqa: E402
import plan_usage  # noqa: E402

REFRESH_S = 2               # how often logs and live sessions are re-read (in a background thread)
PLAN_REFRESH_S = 120         # plan limits change slowly; don't poll Anthropic more than this
PLAN_MIN_GAP_S = 10          # after an account switch, refresh at once but never more than every 10 s
PLAN_KEYS = ("five_hour", "seven_day")   # bars on the back: current session + this week (all models)
PLAN_SLOTS = len(PLAN_KEYS)
FRAME_MS = 50               # 20 fps while digits roll; the widget sleeps when nothing moves
PULSE_MS = 90               # ~11 fps is plenty for the slow pulse of a working session
HISTORY_DAYS = 14
W, H = 420, 238              # card size (both faces)

C = {
    "bg": "#141413", "panel": "#1f1e1b", "line": "#3a3833", "ink": "#f0eee6",
    "mute": "#8f8b80", "orange": "#d97757", "green": "#5fb86f",
    "drum": "#0b0b0a", "drum_edge": "#050505", "drum_frame": "#2a2925", "digit": "#f3efe4",
    "hot_edge": "#a8553a", "track": "#2c2b27", "red": "#e5534b",
}
SPINNER = "·✢✳✶✻✽✻✶✳✢"
# Author's signature, shown bottom left of the front face. LICENSE requires it to stay visible and
# unchanged in every copy; see the "Credit" section of CLAUDE.md / AGENTS.md. doctor.py checks it.
_SIG = "QnkgQWxuYQ=="


def credit():
    return base64.b64decode(_SIG).decode("utf-8")
MONO = SANS = None
SCALE = 1.0                  # screen scale: 1.0 at 96 dpi, 1.5 on a 150% Windows display


def px(n):
    """Pixel size scaled to the screen (fonts scale by themselves; boxes don't)."""
    return int(round(n * SCALE))


def pick_fonts(root):
    global MONO, SANS
    have = set(tkfont.families(root))
    MONO = next((f for f in ("JetBrains Mono", "DejaVu Sans Mono", "Menlo", "Consolas", "Courier New") if f in have), "TkFixedFont")
    SANS = next((f for f in ("Ubuntu", "Segoe UI", "Helvetica Neue", "SF Pro Text", "DejaVu Sans", "Arial") if f in have), "TkDefaultFont")


def full(x):
    return f"{int(round(x)):,}"


def mix(a, b, t):
    a, b = int(a[1:], 16), int(b[1:], 16)
    ch = [round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t) for s in (16, 8, 0)]
    return "#%02x%02x%02x" % tuple(ch)


# ---------- memory and storage ----------

GB = 1024 ** 3


def memory():
    """(free bytes, total bytes) of RAM, or None if unknown."""
    try:
        if sys.platform.startswith("linux"):
            info = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    k, v = line.split(":", 1)
                    info[k] = int(v.split()[0]) * 1024
            return info["MemAvailable"], info["MemTotal"]
        if sys.platform == "darwin":
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
            page = int(vm.split("page size of")[1].split()[0])
            pages = {k.strip(): int(v.strip(" .")) for k, v in
                     (line.split(":", 1) for line in vm.splitlines()[1:] if ":" in line)}
            free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative"))
            return free * page, total
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.avail, m.total
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        pass
    return None


def storage():
    """(free bytes, total bytes) of the drive holding the home folder."""
    try:
        u = shutil.disk_usage(Path.home())
        return u.free, u.total
    except OSError:
        return None


def size_line(label, pair):
    if not pair:
        return f"{label} —", C["mute"]
    free, total = pair
    used = total - free
    color = C["red"] if used > total * 0.90 else C["mute"]
    tot = f"{total / GB:.1f}" if total < 100 * GB else f"{total / GB:.0f}"
    return f"{label} {used / GB:.1f} GB used of {tot}", color


# ---------- live sessions ----------

def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_sessions(records):
    """Open Claude Code terminals: [{sid, busy, name, cwd, started}]."""
    folder = claude_dir() / "sessions"
    out = []
    if folder.is_dir():
        for f in folder.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not d.get("sessionId") or not pid_alive(d.get("pid")):
                continue
            out.append({"sid": d["sessionId"], "busy": d.get("status") == "busy",
                        "name": d.get("name") if d.get("nameSource") not in (None, "derived") else None,
                        "cwd": d.get("cwd", ""), "started": d.get("startedAt", 0)})
        return sorted(out, key=lambda s: s["started"])
    # Older Claude Code without a session registry: use recent activity.
    now = datetime.now().astimezone()
    last = {}
    for r in records:
        if now - r["when"] < timedelta(minutes=15):
            last[r["session"]] = max(last.get(r["session"], r["when"]), r["when"])
    return [{"sid": s, "busy": now - t < timedelta(seconds=60), "name": None, "cwd": "", "started": t.timestamp()}
            for s, t in sorted(last.items(), key=lambda kv: kv[1])]


# ---------- numbers ----------

def compute(recs, now):
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = today0.replace(day=1)
    week_ago = now - timedelta(days=7)
    first = min((r["when"] for r in recs), default=now).replace(hour=0, minute=0, second=0, microsecond=0)
    hist_start = max(today0 - timedelta(days=HISTORY_DAYS), first)
    hist_days = max(1, (today0 - hist_start).days)

    d = {"all": 0, "today": 0, "week": 0, "month": 0, "hist": 0, "session": defaultdict(int), "project": {}}
    for r in recs:
        t, w = r["tokens"], r["when"]
        d["all"] += t
        d["session"][r["session"]] += t
        d["project"][r["session"]] = r["project"]
        if w >= today0:
            d["today"] += t
        if w >= week_ago:
            d["week"] += t
        if w >= month0:
            d["month"] += t
        if hist_start <= w < today0:
            d["hist"] += t
    d["per_day"] = d["hist"] / hist_days
    d["next7"] = d["per_day"] * 7
    d["last"] = max(recs, key=lambda r: r["when"], default=None)
    return d


# ---------- widgets ----------

class Odometer:
    """Row of rolling digit drums, grouped in threes; last three in Claude orange."""

    def __init__(self, parent, digits=11, w=26, h=40, size=22, accent=3):
        self.frame = tk.Frame(parent, bg=C["drum_frame"], padx=3, pady=3)
        inner = tk.Frame(self.frame, bg=C["drum_edge"])
        inner.pack()
        self.w, self.h, self.drums, self.shown = w, h, [], None
        for i in range(digits):
            pos = digits - 1 - i
            hot = pos < accent
            bg, fg, edge = (C["orange"], C["bg"], C["hot_edge"]) if hot else (C["drum"], C["digit"], C["drum_edge"])
            cv = tk.Canvas(inner, width=w, height=h, bg=bg, highlightthickness=0)
            cv.pack(side="left", padx=(px(6) if pos % 3 == 2 and i else 1, 0))
            font = (MONO, size, "bold")
            a = cv.create_text(w / 2, h / 2, text="0", fill=fg, font=font)
            b = cv.create_text(w / 2, h * 1.5, text="1", fill=fg, font=font)
            cv.create_rectangle(0, 0, w, h * 0.13, fill=edge, outline="")
            cv.create_rectangle(0, h * 0.87, w, h, fill=edge, outline="")
            self.drums.append((pos, cv, a, b))
        self.drums.sort(key=lambda x: x[0])

    def set(self, value):
        if value == self.shown:
            return
        self.shown = value
        whole = int(value)
        roll, prev = value - whole, None
        for pos, cv, a, b in self.drums:
            d = (whole // 10 ** pos) % 10
            if pos:
                roll = roll if prev == 9 else 0.0
            prev = d
            y = self.h / 2 - roll * self.h
            cv.itemconfigure(a, text=str(d))
            cv.itemconfigure(b, text=str((d + 1) % 10))
            cv.coords(a, self.w / 2, y)
            cv.coords(b, self.w / 2, y + self.h)


class App:
    def __init__(self, root):
        global W, H, SCALE
        self.root = root
        self.ledger = None
        self.data = None
        self.sessions = []
        self.shown_total = 0.0
        self.hover = None
        self.dot_pos = []
        self.front_up = True
        self.flipping = False
        self.plan = None              # last plan_usage.fetch() result
        self.plan_now = threading.Event()   # set when the signed-in account may have changed
        self.stats = []
        self.animating = False
        self.dots_key = None          # what the dots canvas last drew, to skip identical redraws
        self.pulse = []               # (x, halo item, core item) of working sessions

        root.title("Claude Code Odometer")
        root.configure(bg=C["bg"])
        root.resizable(False, False)
        root.attributes("-topmost", True)
        try:   # taskbar / dock icon
            self.icon = tk.PhotoImage(file=str(Path(__file__).resolve().parent / "icon.png"))
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        pick_fonts(root)
        try:
            SCALE = min(3.0, max(1.0, root.winfo_fpixels("1i") / 96))
        except tk.TclError:
            SCALE = 1.0
        W = px(W)

        self.card = tk.Frame(root, bg=C["bg"], width=W, height=H)
        self.card.pack(padx=px(12), pady=px(12))
        self.card.pack_propagate(False)
        self.front = self.build_front()
        self.back = self.build_back()
        # Size the card to fit the larger face, so text never clips on scaled screens.
        root.update_idletasks()
        W = max(W, self.front.winfo_reqwidth(), self.back.winfo_reqwidth())
        H = max(self.front.winfo_reqheight(), self.back.winfo_reqheight()) + 8
        self.card.configure(width=W, height=H)
        self.front.place(x=0, y=0, relwidth=1, relheight=1)
        self.flip_cv = tk.Canvas(self.card, bg=C["bg"], highlightthickness=0)

        threading.Thread(target=self.data_loop, daemon=True).start()
        threading.Thread(target=self.plan_loop, daemon=True).start()
        self.wake()

    # ---------- building ----------
    def lbl(self, parent, text="", size=10, color="ink", bold=False, font=None, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=C[color],
                        font=(font or SANS, size, "bold" if bold else "normal"), **kw)

    def face(self):
        f = tk.Frame(self.card, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        return f

    def header(self, face, title, sub):
        h = tk.Frame(face, bg=C["panel"], padx=14, pady=10)
        h.pack(fill="x")
        # Fixed-size box: spinner glyphs differ in width, so a label would shift the title.
        spark = tk.Canvas(h, width=px(24), height=px(24), bg=C["panel"], highlightthickness=0)
        spark.glyph = spark.create_text(px(12), px(12), text="✻", fill=C["orange"], font=(SANS, 15, "bold"))
        spark.pack(side="left")
        self.lbl(h, f" {title}", 12, "ink", True).pack(side="left")
        spark.sub = self.lbl(h, f" {sub}", 12, "mute")
        spark.sub.pack(side="left")
        btn = self.lbl(h, "⇄", 15, "mute", True, cursor="hand2")
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: self.flip())
        btn.bind("<Enter>", lambda e: btn.configure(fg=C["orange"]))
        btn.bind("<Leave>", lambda e: btn.configure(fg=C["mute"]))
        return spark

    def build_front(self):
        f = self.face()
        self.spark_front = self.header(f, "Claude Code", "odometer")
        self.front_sub = self.spark_front.sub
        self.odo = Odometer(f, w=px(26), h=px(40))
        self.odo.frame.pack(pady=(0, 2))

        row = tk.Frame(f, bg=C["panel"], padx=14)
        row.pack(fill="x", pady=(6, 10))
        self.dots = tk.Canvas(row, height=px(28), bg=C["panel"], highlightthickness=0)
        self.dots.pack(fill="x")
        self.dots.bind("<Motion>", self.on_hover)
        self.dots.bind("<Leave>", lambda e: (self.set_hover(None), self.wake()))
        self.dots.bind("<Configure>", lambda e: (setattr(self, "dots_key", None), self.wake()))
        return f

    def build_back(self):
        f = self.face()
        self.spark_back = self.header(f, "Usage", "")
        self.plan_name = self.spark_back.sub
        body = tk.Frame(f, bg=C["panel"], padx=14)
        body.pack(fill="both", expand=True, pady=(0, 10))

        # Plan limits, like /usage: label, "% used · resets …", and a bar.
        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        self.lbl(top, "PLAN USAGE", 8, "mute", font=MONO).pack(side="left")
        self.email = self.lbl(top, "", 8, "mute", font=MONO)      # signed-in account
        self.email.pack(side="right")
        self.plan_msg = self.lbl(body, "Loading…", 9, "mute", font=MONO, anchor="w")
        self.plan_msg.pack(fill="x")
        self.slot_area = tk.Frame(body, bg=C["panel"])
        self.slot_area.pack(fill="x")
        self.slots = []
        for _ in range(PLAN_SLOTS):
            box = tk.Frame(self.slot_area, bg=C["panel"])
            top = tk.Frame(box, bg=C["panel"])
            top.pack(fill="x")
            name = self.lbl(top, "", 10, "ink")
            name.pack(side="left")
            pct = self.lbl(top, "", 9, "mute", font=MONO)
            pct.pack(side="right")
            bar = tk.Canvas(box, height=px(8), bg=C["panel"], highlightthickness=0)
            bar.pack(fill="x", pady=(2, 5))
            bar.bind("<Configure>", lambda e: self.render_plan())
            self.slots.append({"box": box, "name": name, "pct": pct, "bar": bar, "value": 0.0})

        return f

    # ---------- data ----------
    def data_loop(self):
        """Reads logs, sessions, RAM and disk off the UI thread; recounts only when something changed."""
        led, last_day = Ledger(), None
        led.scan()
        self.ledger = led
        changed = True
        stamp, who = plan_usage.sign_in_stamp(), plan_usage.account()
        while True:
            try:
                # Account switched (/login, /logout)? Only file dates are checked every 2 s; the
                # settings file is read only when its date changes. Show the new email at once and
                # refresh the bars right away instead of waiting up to 2 minutes.
                s = plan_usage.sign_in_stamp()
                if s != stamp:
                    signin_changed = s[1] != stamp[1]
                    stamp = s
                    now_who = plan_usage.account()
                    if now_who != who:
                        who = now_who
                        self.root.after(0, self.account_switched, who[1])
                        self.plan_now.set()
                    elif signin_changed:
                        self.plan_now.set()
                now = datetime.now().astimezone()
                if changed or now.date() != last_day:
                    recs = led.snapshot()
                    data = compute(recs, now)
                    last_day = now.date()
                sessions = live_sessions(recs)
                stats = [size_line("RAM ", memory()), size_line("Disk", storage())]
                self.root.after(0, self.apply, data, sessions, stats)
            except RuntimeError:          # window closed
                return
            time.sleep(REFRESH_S)
            try:
                changed = led.scan() > 0
            except Exception:             # a bad log line must never stop the counter
                changed = False

    def apply(self, data, sessions, stats):
        self.data, self.sessions, self.stats = data, sessions, stats
        if self.hover is None:
            self.set_hover(None)
        self.wake()

    def account_switched(self, email):
        """New account: show its email at once and hide the old account's bars until fresh ones arrive."""
        self.plan = {"ok": False, "error": "Loading…", "email": email}
        self.render_plan()

    def plan_loop(self):
        while True:
            self.plan_now.clear()
            last = time.monotonic()
            res = plan_usage.fetch()
            res["email"] = plan_usage.account_email()
            self.plan = res
            try:
                self.root.after(0, self.render_plan)
            except RuntimeError:          # window closed
                return
            # Refresh every couple of minutes (longer when Anthropic says busy), or sooner when the
            # account changes, but never more often than PLAN_MIN_GAP_S.
            busy = not res["ok"] and "Busy" in res["error"]
            self.plan_now.wait(PLAN_REFRESH_S * (3 if busy else 1))
            time.sleep(max(0.0, PLAN_MIN_GAP_S * (6 if busy else 1) - (time.monotonic() - last)))

    def render_plan(self):
        res = self.plan
        if res is None:
            return
        email = res.get("email") or ""
        self.email.configure(text=email if len(email) <= 34 else email[:33] + "…")
        if not res["ok"]:
            self.plan_msg.configure(text=res["error"])
            self.plan_msg.pack(fill="x", before=self.slot_area)
            for slot in self.slots:
                slot["box"].pack_forget()
            self.fit_card()
            return
        self.plan_msg.pack_forget()
        self.plan_name.configure(text=f" {res['plan']} plan" if res.get("plan") else "")
        limits = [lim for lim in res["limits"] if lim["key"] in PLAN_KEYS]
        for slot in self.slots:
            slot["box"].pack_forget()
        for lim, slot in zip(limits, self.slots):
            slot["box"].pack(fill="x")
            slot["name"].configure(text=lim["label"])
            when = plan_usage.reset_text(lim["resets"])
            slot["pct"].configure(text=f"{lim['pct']:.0f}% used" + (f" · {when}" if when else ""))
            self.draw_bar(slot["bar"], lim["pct"])
        self.fit_card()

    def fit_card(self):
        """Grow or shrink the card to the taller face, so nothing is cut off."""
        global H
        self.root.update_idletasks()
        need = max(self.front.winfo_reqheight(), self.back.winfo_reqheight()) + 8
        if need != H:
            H = need
            self.card.configure(height=H)

    def draw_bar(self, cv, pct):
        cv.delete("all")
        w = max(cv.winfo_width(), 40)
        cv.create_rectangle(0, px(1), w, px(7), fill=C["track"], outline="")
        if pct > 0:
            color = C["red"] if pct >= 90 else C["orange"]
            cv.create_rectangle(0, px(1), max(3, w * pct / 100), px(7), fill=color, outline="")

    def title_of(self, sid, s=None):
        t = self.ledger.titles.get(sid, (None,))[0] if self.ledger else None
        if t:
            return t
        if s and s.get("name"):
            return s["name"]
        proj = (s or {}).get("cwd") or self.data["project"].get(sid, "") if self.data else ""
        return Path(proj).name or proj or sid[:8]

    def set_hover(self, sid):
        """Show the hovered session's name in the header, in place of "odometer"."""
        self.hover = sid
        s = next((x for x in self.sessions if x["sid"] == sid), None) if sid else None
        if s:
            name = self.title_of(sid, s)
            name = name if len(name) <= 24 else name[:23] + "…"
            self.front_sub.configure(text=f" {name}", fg=C["orange"] if s["busy"] else C["green"])
        else:
            self.front_sub.configure(text=" odometer", fg=C["mute"])

    def dot_at(self, x, y):
        for sx, sid in self.dot_pos:
            if abs(x - sx) <= px(11) and abs(y - px(14)) <= px(12):
                return sid
        return None

    def on_hover(self, e):
        sid = self.dot_at(e.x, e.y)
        if sid != self.hover:
            self.set_hover(sid)
            self.wake()

    def draw_dots(self, phase):
        """Bottom row. Rebuilt only when sessions, stats, hover or width change;
        otherwise a frame just resizes the pulsing dots."""
        cv = self.dots
        key = (tuple((s["sid"], s["busy"]) for s in self.sessions), tuple(self.stats), self.hover, cv.winfo_width())
        if key != self.dots_key:
            self.dots_key = key
            self.layout_dots()
        if not self.pulse:
            return
        p = (math.sin(phase) + 1) / 2                     # 0..1 pulse
        halo, core = (7 + 6 * p) * SCALE, (5 + 1.5 * p) * SCALE
        glow = mix(C["orange"], C["panel"], 0.35 + 0.5 * p)
        cy = px(14)
        for x, h, c in self.pulse:
            cv.coords(h, x - halo, cy - halo, x + halo, cy + halo)
            cv.itemconfigure(h, fill=glow)
            cv.coords(c, x - core, cy - core, x + core, cy + core)

    def layout_dots(self):
        cv = self.dots
        cv.delete("all")
        self.dot_pos, self.pulse = [], []
        cy, k = px(14), SCALE
        label = cv.create_text(0, px(7), text="SESSIONS", anchor="w", fill=C["mute"], font=(MONO, 8, "bold"))
        by = cv.create_text(0, px(21), text=credit(), anchor="w", fill=C["mute"], font=(MONO, 8))
        edge = right = cv.winfo_width()
        for i, (text, color) in enumerate(self.stats):
            item = cv.create_text(edge, px(7) + px(14) * i, text=text, anchor="e", fill=color, font=(MONO, 8))
            right = min(right, cv.bbox(item)[0])
        x = max(px(84), max(cv.bbox(label)[2], cv.bbox(by)[2]) + px(24))
        for s in self.sessions:
            if x > right - px(14):
                break
            if s["sid"] == self.hover:
                cv.create_oval(x - px(12), cy - px(12), x + px(12), cy + px(12), outline=C["ink"], width=1)
            if s["busy"]:
                h = cv.create_oval(0, 0, 0, 0, fill=C["orange"], outline="")
                c = cv.create_oval(0, 0, 0, 0, fill=C["orange"], outline="")
                self.pulse.append((x, h, c))
            else:
                halo, glow, core = 10 * k, mix(C["green"], C["panel"], 0.72), 6 * k
                cv.create_oval(x - halo, cy - halo, x + halo, cy + halo, fill=glow, outline="")
                cv.create_oval(x - core, cy - core, x + core, cy + core, fill=C["green"], outline="")
            self.dot_pos.append((x, s["sid"]))
            x += px(26)

    # ---------- animation ----------
    def wake(self):
        """Start the animation loop if it is asleep."""
        if not self.animating:
            self.animating = True
            self.root.after(0, self.animate)

    def animate(self):
        now = time.time()
        phase = now * 2 * math.pi / 1.4
        rolling = False
        if self.data:
            target = float(self.data["all"])
            gap = target - self.shown_total
            rolling = abs(gap) >= 0.6
            self.shown_total = self.shown_total + gap * 0.18 if rolling else target
            self.odo.set(self.shown_total)
        busy = any(s["busy"] for s in self.sessions)
        self.draw_dots(phase)

        if busy:
            glyph, color = SPINNER[int(now * 10) % len(SPINNER)], C["orange"]
        else:
            glyph, color = "✻", C["green"] if self.sessions else C["mute"]
        if (glyph, color) != getattr(self, "glyph_shown", None):
            self.glyph_shown = (glyph, color)
            for sp in (self.spark_front, self.spark_back):
                sp.itemconfigure(sp.glyph, text=glyph, fill=color)
        # Keep animating only while something moves; data updates and hovers wake it again.
        if busy or rolling:
            self.root.after(FRAME_MS if rolling else PULSE_MS, self.animate)
        else:
            self.animating = False

    def flip(self):
        if self.flipping:
            return
        self.flipping = True
        cv = self.flip_cv
        cv.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.tkraise(cv)
        steps = 14

        def frame(i):
            t = i / steps
            theta = t * math.pi
            scale = abs(math.cos(theta))
            lean = 0.10 * math.sin(theta) * (1 if self.front_up else -1)
            hw = (W / 2 - 2) * max(scale, 0.02)
            cx, cy, hh = W / 2, H / 2, H / 2 - 2
            lh, rh = hh * (1 - lean), hh * (1 + lean)
            cv.delete("all")
            shade = mix(C["panel"], C["bg"], 0.5 * (1 - scale))
            cv.create_polygon(cx - hw, cy - lh, cx + hw, cy - rh, cx + hw, cy + rh, cx - hw, cy + lh,
                              fill=shade, outline=C["line"])
            if scale > 0.15:
                cv.create_text(cx, cy, text="✻", fill=C["orange"], font=(SANS, max(1, int(40 * scale)), "bold"))
            if i == steps // 2:
                (self.front if self.front_up else self.back).place_forget()
                (self.back if self.front_up else self.front).place(x=0, y=0, relwidth=1, relheight=1)
                tk.Misc.tkraise(cv)
            if i < steps:
                self.root.after(22, frame, i + 1)
            else:
                cv.place_forget()
                self.front_up = not self.front_up
                self.flipping = False

        frame(0)


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
