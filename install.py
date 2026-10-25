#!/usr/bin/env python3
"""Create a desktop shortcut (and app-menu entry on Linux) for Claude Code Odometer.

    python3 install.py                      # shortcut only
    python3 install.py --owner "Your Name"  # also set the name shown on the odometer
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
sys.path.insert(0, str(HERE))
from token_calc import data_dir  # noqa: E402


def desktop_dir():
    if sys.platform.startswith("linux"):
        try:
            d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
            if d:
                return Path(d)
        except OSError:
            pass
    if sys.platform == "win32":
        try:
            d = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True).stdout.strip()
            if d:
                return Path(d)
        except OSError:
            pass
    return Path.home() / "Desktop"


def linux():
    entry = f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment=Live Claude Code token odometer
Exec="{sys.executable}" "{APP}"
Icon={HERE / 'icon.svg'}
Terminal=false
Categories=Utility;Monitor;
StartupWMClass=Tk
"""
    menu = Path.home() / ".local/share/applications/claude-odometer.desktop"
    menu.parent.mkdir(parents=True, exist_ok=True)
    menu.write_text(entry, encoding="utf-8")
    desk = desktop_dir() / "claude-odometer.desktop"
    desk.parent.mkdir(parents=True, exist_ok=True)
    desk.write_text(entry, encoding="utf-8")
    for p in (menu, desk):
        p.chmod(0o755)
    # GNOME only launches desktop icons that are marked as trusted.
    subprocess.run(["gio", "set", str(desk), "metadata::trusted", "true"], capture_output=True)
    return [menu, desk]


def mac():
    desk = desktop_dir() / f"{NAME}.command"
    desk.write_text(f'#!/bin/bash\nnohup "{sys.executable}" "{APP}" >/dev/null 2>&1 &\n'
                    "osascript -e 'tell application \"Terminal\" to close front window' >/dev/null 2>&1 &\n")
    desk.chmod(0o755)
    return [desk]


def windows():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    lnk = desktop_dir() / f"{NAME}.lnk"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{exe}';$s.Arguments='\"{APP}\"';$s.WorkingDirectory='{HERE}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return [lnk]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", help="name shown on the odometer")
    args = ap.parse_args()
    if args.owner:
        cfg = data_dir() / "config.json"
        cfg.write_text(json.dumps({"owner": args.owner}), encoding="utf-8")
        print(f"Owner set to {args.owner}")
    made = windows() if sys.platform == "win32" else mac() if sys.platform == "darwin" else linux()
    for p in made:
        print(f"Created {p}")


if __name__ == "__main__":
    main()
