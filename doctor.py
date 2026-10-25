#!/usr/bin/env python3
"""Check that this computer can run Claude Code Odometer, and what is already set up.

    python3 doctor.py          # readable checklist
    python3 doctor.py --json   # same, as JSON (used by Claude Code during setup)

On Windows use `py doctor.py` or `python doctor.py`.
Exit code 0 = ready to install, 1 = something must be fixed first.
It never prints, saves or sends the Claude Code sign-in token.
"""
import getpass
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def check(name, status, detail, fix=None):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def os_name():
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def tk_fix():
    return {
        "windows": "Reinstall Python from python.org and keep 'tcl/tk and IDLE' ticked "
                   "(the Microsoft Store Python also includes it).",
        "macos": "Install Python from python.org (includes Tk), or `brew install python-tk`.",
        "linux": "sudo apt install python3-tk   (Fedora: sudo dnf install python3-tkinter; "
                 "Arch: sudo pacman -S tk)",
    }[os_name()]


SIGNATURE = "aab9b6aa910cf05b241ce8ebaa919926809b2794b50305f174585824f5947680"   # sha256 of the credit text


def signature_check():
    """The author's credit ("By Alna") must stay in the widget and the LICENSE. See CLAUDE.md "Credit"."""
    import base64
    import hashlib
    try:
        src = (HERE / "token_popup.py").read_text(encoding="utf-8")
        lic = (HERE / "LICENSE").read_text(encoding="utf-8")
        sig = src.split('_SIG = "', 1)[1].split('"', 1)[0]
        shown = base64.b64decode(sig).decode("utf-8")
        intact = (hashlib.sha256(shown.encode()).hexdigest() == SIGNATURE and "text=credit()" in src
                  and "By Alna" in lic)
    except (OSError, IndexError, ValueError):
        intact = False
    return check("credit", "ok" if intact else "fail",
                 "Author credit 'By Alna' is intact" if intact else "The author credit was removed or changed",
                 None if intact else "Restore it: git checkout -- token_popup.py LICENSE  (required by LICENSE)")


def run_checks():
    out = []
    v = sys.version_info
    out.append(check("python", "ok" if v >= (3, 9) else "fail",
                     f"Python {platform.python_version()} at {sys.executable}",
                     None if v >= (3, 9) else "Install Python 3.9 or newer from python.org."))

    # Tk: import, then try to open (and close) a hidden window.
    try:
        import tkinter as tk
        ver = tk.Tcl().eval("info patchlevel")
        try:
            r = tk.Tk()
            r.withdraw()
            dpi = r.winfo_fpixels("1i")
            r.destroy()
            out.append(check("tk", "ok", f"Tk {ver}, screen {dpi:.0f} dpi"))
        except tk.TclError as e:
            out.append(check("tk", "warn", f"Tk {ver} is installed but no window could open: {e}",
                             "Run it from a desktop session (not over SSH without a display)."))
    except ImportError:
        out.append(check("tk", "fail", "tkinter is missing", tk_fix()))

    from token_calc import claude_dir, data_dir, owner_name, projects_dirs
    cdir = claude_dir()
    claude_bin = shutil.which("claude")
    logs = sum(1 for d in projects_dirs() for _ in d.rglob("*.jsonl"))
    if logs:
        out.append(check("claude_code", "ok", f"{logs} Claude Code logs in {cdir}"
                         + (f"; CLI at {claude_bin}" if claude_bin else "")))
    elif cdir.exists() or claude_bin:
        out.append(check("claude_code", "warn", f"Claude Code found ({cdir}) but no logs yet",
                         "Use Claude Code once; the odometer starts at 0 until then."))
    else:
        out.append(check("claude_code", "fail", f"Claude Code not found ({cdir} is missing)",
                         "Install Claude Code and sign in, then run this again."))

    sess = cdir / "sessions"
    out.append(check("session_dots", "ok" if sess.is_dir() else "warn",
                     f"Live session files in {sess}" if sess.is_dir()
                     else "No session folder; dots will use recent activity instead",
                     None if sess.is_dir() else "Update Claude Code for exact working/finished dots."))

    # Sign-in for the plan bars: only check that it exists and when it expires.
    import plan_usage
    oauth = plan_usage._read_oauth()
    if not oauth or not oauth.get("accessToken"):
        out.append(check("plan_bars", "warn", "No Claude Code sign-in found; the back card will say "
                         "'Usage not available'", "Sign in to Claude Code with /login (a Pro/Max account)."))
    else:
        exp = oauth.get("expiresAt")
        expired = isinstance(exp, (int, float)) and exp / 1000 < time.time()
        plan = oauth.get("subscriptionType") or "unknown plan"
        out.append(check("plan_bars", "warn" if expired else "ok",
                         f"Signed in ({plan})" + ("; sign-in has expired" if expired else ""),
                         "Open Claude Code once; it refreshes the sign-in." if expired else None))

    out.append(signature_check())

    import install
    st = install.status()
    shortcuts = {k: v for k, v in st["installed"].items()}
    out.append(check("installed", "ok" if any(shortcuts.values()) else "info",
                     ", ".join(f"{k}: {'yes' if v else 'no'}" for k, v in shortcuts.items())))

    git_name = None
    try:
        git_name = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True,
                                  timeout=3, **({"creationflags": 0x08000000} if os.name == "nt" else {})
                                  ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "os": os_name(), "os_detail": platform.platform(),
        "python": sys.executable,
        "python_cmd": "py" if os.name == "nt" and shutil.which("py") else ("python" if os.name == "nt" else "python3"),
        "checks": out,
        "ready": all(c["status"] != "fail" for c in out),
        "owner": {"current": st["owner"], "shown_now": owner_name(), "git_name": git_name,
                  "os_user": getpass.getuser()},
        "installed": shortcuts, "paths": st["paths"], "data_dir": str(data_dir()),
    }


def main():
    from token_calc import utf8_stdout
    utf8_stdout()
    res = run_checks()
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        mark = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}
        print(f"Claude Code Odometer check ({res['os']}, {res['os_detail']})\n")
        for c in res["checks"]:
            print(f"{mark[c['status']]} {c['name']:<13} {c['detail']}")
            if c["fix"]:
                print(f"       {'':<13} fix: {c['fix']}")
        o = res["owner"]
        print(f"\nName on reports: {o['shown_now']}" + ("" if o["current"] else " (not set; install.py --owner)"))
        print("\nReady to install." if res["ready"] else "\nFix the [FAIL] items, then run this again.")
    sys.exit(0 if res["ready"] else 1)


if __name__ == "__main__":
    main()
