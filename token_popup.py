#!/usr/bin/env python3
"""Claude Code Odometer — a live token counter in Claude Code colours.

Front: rolling odometer of every token used on this device, plus one dot per
open Claude Code terminal (orange pulse = working, green glow = finished;
hover for the session name, shown in the header).
Back (flip with ⇄): the account's plan usage like /usage (current session and weekly
limits, % used, reset time). Both faces are the same compact size.
"""
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

REFRESH_MS = 2000
PLAN_REFRESH_S = 120         # plan limits change slowly; don't poll Anthropic more than this
PLAN_KEYS = ("five_hour", "seven_day")   # bars on the back: current session + this week (all models)
PLAN_SLOTS = len(PLAN_KEYS)
FRAME_MS = 33
HISTORY_DAYS = 14
W, H = 420, 238              # card size (both faces)

C = {
    "bg": "#141413", "panel": "#1f1e1b", "line": "#3a3833", "ink": "#f0eee6",
    "mute": "#8f8b80", "orange": "#d97757", "green": "#5fb86f",
    "drum": "#0b0b0a", "drum_edge": "#050505", "drum_frame": "#2a2925", "digit": "#f3efe4",
    "hot_edge": "#a8553a", "track": "#2c2b27", "red": "#e5534b",
}
SPINNER = "·✢✳✶✻✽✻✶✳✢"
MONO = SANS = None


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
        k = ctypes.windll.kernel32
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
            cv.pack(side="left", padx=(6 if pos % 3 == 2 and i else 1, 0))
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
        global W, H
        self.root = root
        self.ledger = None
        self.data = None
        self.sessions = []
        self.shown_total = 0.0
        self.hover = None
        self.dot_pos = []
        self.front_up = True
        self.flipping = False
        self.spin = 0
        self.plan = None              # last plan_usage.fetch() result

        root.title("Claude Code Odometer")
        root.configure(bg=C["bg"])
        root.resizable(False, False)
        root.attributes("-topmost", True)
        pick_fonts(root)

        self.card = tk.Frame(root, bg=C["bg"], width=W, height=H)
        self.card.pack(padx=12, pady=12)
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

        threading.Thread(target=self.first_load, daemon=True).start()
        threading.Thread(target=self.plan_loop, daemon=True).start()
        self.tick()
        self.animate()

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
        spark = tk.Canvas(h, width=24, height=24, bg=C["panel"], highlightthickness=0)
        spark.glyph = spark.create_text(12, 12, text="✻", fill=C["orange"], font=(SANS, 15, "bold"))
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
        self.odo = Odometer(f)
        self.odo.frame.pack(pady=(0, 2))

        row = tk.Frame(f, bg=C["panel"], padx=14)
        row.pack(fill="x", pady=(6, 10))
        self.dots = tk.Canvas(row, height=28, bg=C["panel"], highlightthickness=0)
        self.dots.pack(fill="x")
        self.dots.bind("<Motion>", self.on_hover)
        self.dots.bind("<Leave>", lambda e: self.set_hover(None))
        return f

    def build_back(self):
        f = self.face()
        self.spark_back = self.header(f, "Usage", "")
        self.plan_name = self.spark_back.sub
        body = tk.Frame(f, bg=C["panel"], padx=14)
        body.pack(fill="both", expand=True, pady=(0, 10))

        # Plan limits, like /usage: label, "% used · resets …", and a bar.
        self.lbl(body, "PLAN USAGE", 8, "mute", font=MONO, anchor="w").pack(fill="x")
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
            bar = tk.Canvas(box, height=8, bg=C["panel"], highlightthickness=0)
            bar.pack(fill="x", pady=(2, 5))
            bar.bind("<Configure>", lambda e: self.render_plan())
            self.slots.append({"box": box, "name": name, "pct": pct, "bar": bar, "value": 0.0})

        return f

    # ---------- data ----------
    def first_load(self):
        led = Ledger()
        led.scan()
        self.ledger = led

    def plan_loop(self):
        while True:
            res = plan_usage.fetch()
            self.plan = res
            self.root.after(0, self.render_plan)
            # Back off when Anthropic says busy; otherwise refresh every couple of minutes.
            time.sleep(PLAN_REFRESH_S * (3 if not res["ok"] and "Busy" in res["error"] else 1))

    def render_plan(self):
        res = self.plan
        if res is None:
            return
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
        cv.create_rectangle(0, 1, w, 7, fill=C["track"], outline="")
        if pct > 0:
            color = C["red"] if pct >= 90 else C["orange"]
            cv.create_rectangle(0, 1, max(3, w * pct / 100), 7, fill=color, outline="")

    def tick(self):
        self.stats = [size_line("RAM ", memory()), size_line("Disk", storage())]
        if self.ledger:
            self.ledger.scan()
            recs = self.ledger.snapshot()
            self.data = compute(recs, datetime.now().astimezone())
            self.sessions = live_sessions(recs)
            if self.hover is None:
                self.set_hover(None)
        self.root.after(REFRESH_MS, self.tick)

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
            if abs(x - sx) <= 11 and abs(y - 14) <= 12:
                return sid
        return None

    def on_hover(self, e):
        sid = self.dot_at(e.x, e.y)
        if sid != self.hover:
            self.set_hover(sid)

    def draw_dots(self, phase):
        cv = self.dots
        cv.delete("all")
        self.dot_pos = []
        cv.create_text(0, 14, text="SESSIONS", anchor="w", fill=C["mute"], font=(MONO, 8, "bold"))
        edge = right = cv.winfo_width()
        for i, (text, color) in enumerate(getattr(self, "stats", [])):
            item = cv.create_text(edge, 7 + 14 * i, text=text, anchor="e", fill=color, font=(MONO, 8))
            right = min(right, cv.bbox(item)[0])
        x = 84
        for s in self.sessions:
            color = C["orange"] if s["busy"] else C["green"]
            if s["busy"]:
                p = (math.sin(phase) + 1) / 2                     # 0..1 pulse
                halo, glow = 7 + 6 * p, mix(C["orange"], C["panel"], 0.35 + 0.5 * p)
                core = 5 + 1.5 * p
            else:
                halo, glow, core = 10, mix(C["green"], C["panel"], 0.72), 6
            if s["sid"] == self.hover:
                cv.create_oval(x - 12, 2, x + 12, 26, outline=C["ink"], width=1)
            cv.create_oval(x - halo, 14 - halo, x + halo, 14 + halo, fill=glow, outline="")
            cv.create_oval(x - core, 14 - core, x + core, 14 + core, fill=color, outline="")
            self.dot_pos.append((x, s["sid"]))
            x += 26
            if x > right - 14:
                break

    # ---------- animation ----------
    def animate(self):
        phase = time.time() * 2 * math.pi / 1.4
        if self.data:
            target = float(self.data["all"])
            gap = target - self.shown_total
            self.shown_total = target if abs(gap) < 0.6 else self.shown_total + gap * 0.12
            self.odo.set(self.shown_total)
        self.draw_dots(phase)

        busy = any(s["busy"] for s in self.sessions)
        if busy:
            self.spin = (self.spin + 1) % (len(SPINNER) * 3)
            glyph, color = SPINNER[self.spin // 3], C["orange"]
        else:
            glyph, color = "✻", C["green"] if self.sessions else C["mute"]
        for sp in (self.spark_front, self.spark_back):
            sp.itemconfigure(sp.glyph, text=glyph, fill=color)
        self.root.after(FRAME_MS, self.animate)

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
