"""Update check and one-click update for Token Mileage. Standard library only.

- check() downloads one small file (version.json, a few bytes) at most once a day. It sends no
  usage data, no account details and no token counts: it is a plain download.
  Turn it off with `install.py --no-update-check` or the environment variable TOKEN_MILEAGE_NO_UPDATE_CHECK=1.
- apply() updates the program files. A git clone is updated with `git pull --ff-only`. A downloaded
  copy fetches that version's zip from the project's GitHub release and copies its files over this
  folder. Usage history lives in the data folder, not here, so it is never touched.

The same file sits in the Claude meter (repo root) and the Codex meter (codex/); keep both identical.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "ebrahim-cyber-bh/Token_Mileage"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/site/version.json"
ASSET_URL = "https://github.com/{repo}/releases/download/v{version}/token-mileage-{kind}.zip"
CHECK_EVERY_S = 24 * 3600
UA = {"User-Agent": "token-mileage-updater"}
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def parse(v):
    """'1.10.2' -> (1, 10, 2); anything odd sorts as oldest."""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def local_version(here):
    try:
        return (Path(here) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def _config(data_dir):
    try:
        return json.loads((Path(data_dir) / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def enabled(data_dir):
    if os.environ.get("TOKEN_MILEAGE_NO_UPDATE_CHECK"):
        return False
    return _config(data_dir).get("update_check", True) is not False


def latest(timeout=10):
    """{'version': '1.2.0', 'notes': '...'} from the project site, or None."""
    try:
        with urllib.request.urlopen(urllib.request.Request(VERSION_URL, headers=UA), timeout=timeout) as r:
            d = json.loads(r.read(64 * 1024))
        return d if isinstance(d, dict) and isinstance(d.get("version"), str) else None
    except (OSError, ValueError):
        return None


def check(here, data_dir, force=False):
    """The newer version string if one is out, else None. Network at most once a day (unless force)."""
    if not force and not enabled(data_dir):
        return None
    cache = Path(data_dir) / "update.json"
    try:
        c = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    if force or time.time() - c.get("checked", 0) > CHECK_EVERY_S:
        info = latest()
        c = {"checked": time.time(), "latest": (info or {}).get("version") or c.get("latest")}
        try:
            cache.write_text(json.dumps(c), encoding="utf-8")
        except OSError:
            pass
    v = c.get("latest")
    return v if v and parse(v) > parse(local_version(here)) else None


def git_root(here):
    for d in (Path(here), Path(here).parent):
        if (d / ".git").exists():
            return d
    return None


def _safe_members(z, top):
    """Zip entries inside `top/`, with no absolute paths or '..' (a bad zip can't write elsewhere)."""
    out = []
    for name in z.namelist():
        p = Path(name)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != top:
            raise ValueError(f"unexpected file in update: {name}")
        if not name.endswith("/"):
            out.append(name)
    return out


def apply(here, kind, log=print):
    """Update the program in `here` ('claude' or 'codex'). Returns True when files changed."""
    here = Path(here)
    root = git_root(here)
    if root:
        log(f"Git copy found in {root}: running git pull")
        r = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"], capture_output=True, text=True, **NO_WINDOW)
        log((r.stdout + r.stderr).strip())
        if r.returncode:
            log("git pull did not finish (local changes?). Nothing was changed.")
            return False
        return "Already up to date" not in r.stdout

    info = latest()
    if not info:
        log("Could not reach the update server. Nothing was changed.")
        return False
    v, mine = info["version"], local_version(here)
    if parse(v) <= parse(mine):
        log(f"Already up to date ({mine}).")
        return False
    url = ASSET_URL.format(repo=REPO, version=v, kind=kind)
    top = f"token-mileage-{kind}"
    log(f"Downloading {v} from {url}")
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "update.zip"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, zpath.open("wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as e:
            log(f"Download failed ({e}). The release may still be building; try again in a few minutes.")
            return False
        with zipfile.ZipFile(zpath) as z:
            names = _safe_members(z, top)
            z.extractall(Path(tmp) / "x", names)
        src = Path(tmp) / "x" / top
        if not (src / "token_popup.py").exists() or local_version(src) != v:
            log("The download does not look like a Token Mileage release. Nothing was changed.")
            return False
        for f in src.rglob("*"):
            if f.is_file():
                dest = here / f.relative_to(src)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
    log(f"Updated {mine} -> {v}.")
    return True
