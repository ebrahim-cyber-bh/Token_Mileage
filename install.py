#!/usr/bin/env python3
"""Install shortcuts for Claude Code Odometer on Linux, macOS or Windows.

    python3 install.py                      # desktop shortcut (+ app menu / Start Menu)
    python3 install.py --owner "Your Name"  # also set the name shown on reports
    python3 install.py --autostart          # also start it when you log in
    python3 install.py --no-desktop         # menu entry only, no desktop icon
    python3 install.py --status             # show what is installed
    python3 install.py --uninstall          # remove shortcuts and autostart (keeps your history)
    python3 install.py --launch             # start the odometer now, detached from this terminal

On Windows use `py` or `python` instead of `python3`.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "token_popup.py"
NAME = "Claude Code Odometer"
SLUG = "claude-odometer"
sys.path.insert(0, str(HERE))
from token_calc import NO_WINDOW, data_dir, utf8_stdout  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **NO_WINDOW, **kw)


def desktop_dir():
    try:
        if sys.platform.startswith("linux"):
            d = run(["xdg-user-dir", "DESKTOP"]).stdout.strip()
            if d:
                return Path(d)
        if sys.platform == "win32":
            d = run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"]).stdout.strip()
            if d:
                return Path(d)
    except OSError:
        pass
    return Path.home() / "Desktop"


def gui_python():
    """The Python that runs the widget. On Windows, pythonw.exe so no console window stays open."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return w
    return exe


def targets():
    """Every file this installer may create, by kind."""
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        progs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return {"desktop": desktop_dir() / f"{NAME}.lnk", "menu": progs / f"{NAME}.lnk",
                "autostart": progs / "Startup" / f"{NAME}.lnk"}
    if sys.platform == "darwin":
        return {"desktop": desktop_dir() / f"{NAME}.command",
                "autostart": Path.home() / "Library" / "LaunchAgents" / "com.claude-odometer.plist"}
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return {"desktop": desktop_dir() / f"{SLUG}.desktop",
            "menu": Path.home() / ".local" / "share" / "applications" / f"{SLUG}.desktop",
            "autostart": config / "autostart" / f"{SLUG}.desktop"}


# ---------- per-OS writers ----------

def linux_entry(path):
    entry = f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment=Live Claude Code token odometer
Exec="{gui_python()}" "{APP}"
Icon={HERE / 'icon.svg'}
Terminal=false
Categories=Utility;Monitor;
StartupWMClass=Tk
X-GNOME-Autostart-enabled=true
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry, encoding="utf-8")
    path.chmod(0o755)
    if path.parent == desktop_dir():
        # GNOME only launches desktop icons that are marked as trusted.
        try:
            run(["gio", "set", str(path), "metadata::trusted", "true"])
        except OSError:
            pass


def mac_entry(kind, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "autostart":
        path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.claude-odometer</string>
  <key>ProgramArguments</key><array><string>{gui_python()}</string><string>{APP}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""", encoding="utf-8")
        return
    path.write_text(f'#!/bin/bash\nnohup "{gui_python()}" "{APP}" >/dev/null 2>&1 &\n'
                    "osascript -e 'tell application \"Terminal\" to close front window' >/dev/null 2>&1 &\n",
                    encoding="utf-8")
    path.chmod(0o755)


def win_entry(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    q = lambda p: str(p).replace("'", "''")          # PowerShell single-quote escaping
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(path)}');"
          f"$s.TargetPath='{q(gui_python())}';$s.Arguments='\"{q(APP)}\"';"
          f"$s.WorkingDirectory='{q(HERE)}';$s.IconLocation='{q(HERE / 'icon.ico')}';"
          f"$s.Description='Live Claude Code token odometer';$s.Save()")
    res = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])
    if res.returncode != 0 or not path.exists():
        raise SystemExit(f"Could not create {path}: {res.stderr.strip() or 'PowerShell failed'}")


def write(kind, path):
    if sys.platform == "win32":
        win_entry(path)
    elif sys.platform == "darwin":
        mac_entry(kind, path)
    else:
        linux_entry(path)


# ---------- commands ----------

def launch():
    """Start the widget in the background, detached from the terminal (works the same on every OS)."""
    kw = {"cwd": str(HERE), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen([str(gui_python()), str(APP)], **kw)
    print(f"Started {NAME} (pid {p.pid})")


def status():
    owner = None
    try:
        owner = json.loads((data_dir() / "config.json").read_text(encoding="utf-8")).get("owner")
    except (OSError, ValueError):
        pass
    return {"owner": owner, "data_dir": str(data_dir()),
            "installed": {k: p.exists() for k, p in targets().items()},
            "paths": {k: str(p) for k, p in targets().items()}}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", help="name shown on the reports")
    ap.add_argument("--autostart", action="store_true", help="start the odometer when you log in")
    ap.add_argument("--no-desktop", action="store_true", help="skip the desktop icon")
    ap.add_argument("--status", action="store_true", help="print what is installed (JSON) and exit")
    ap.add_argument("--uninstall", action="store_true", help="remove shortcuts and autostart")
    ap.add_argument("--launch", action="store_true", help="start the odometer now")
    args = ap.parse_args()

    if args.launch and not (args.owner or args.autostart or args.no_desktop):   # --launch alone
        launch()
        return
    if args.status:
        print(json.dumps(status(), indent=2, ensure_ascii=False))
        return
    if args.uninstall:
        for p in targets().values():
            if p.exists():
                p.unlink()
                print(f"Removed {p}")
        print(f"Your history is kept in {data_dir()} (delete it yourself if you want).")
        return

    if args.owner:
        (data_dir() / "config.json").write_text(json.dumps({"owner": args.owner}, ensure_ascii=False),
                                                encoding="utf-8")
        print(f"Owner set to {args.owner}")
    t = targets()
    kinds = ["menu"] if "menu" in t else []
    if not args.no_desktop:
        kinds.append("desktop")
    if args.autostart:
        kinds.append("autostart")
    for kind in kinds:
        write(kind, t[kind])
        print(f"Created {t[kind]}")
    if not args.autostart and t["autostart"].exists():
        print(f"(Start at login is still on: {t['autostart']}. Run with --uninstall to remove everything.)")
    if args.launch:
        launch()


if __name__ == "__main__":
    main()
