#!/usr/bin/env python3
"""Builds download zips for the Claude meter, Codex meter, and Chrome extension.

    python3 build_release.py dist

Each zip has one top folder (token-mileage-claude/ or token-mileage-codex/) that updater.py expects.
The extension archive has manifest.json at its root and must be extracted before Load unpacked.
Vercel runs it on every deploy (vercel.json) and serves the zips from site/downloads/.
"""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {"__pycache__", ".git", ".github", ".vercel", "codex", "site", "screenshots", "dist", "node_modules", "chrome-extension"}
SKIP_FILES = {"build_release.py", "report.html", "ledger.jsonl", "vercel.json", ".vercelignore"}


def files(folder, extra=()):
    for f in sorted(folder.rglob("*")):
        rel = f.relative_to(folder)
        if f.is_file() and not SKIP_DIRS & set(rel.parts) and f.name not in SKIP_FILES \
                and not f.name.startswith(".env") and not f.name.endswith((".pyc", ".bak")) and ".bak-" not in f.name:
            yield f, rel
    for f in extra:
        yield f, Path(f.name)


def build(out, kind, folder, extra=()):
    path = out / f"token-mileage-{kind}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f, rel in files(folder, extra):
            z.write(f, f"token-mileage-{kind}/{rel.as_posix()}")
    print(path, path.stat().st_size, "bytes")


def build_extension(out):
    # manifest.json at the ZIP root; extract before Chrome's Load unpacked.
    folder = HERE / "chrome-extension"
    path = out / "token-mileage-chrome-extension.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "content.js", "ui.js", "ui.css", "README.md", "AGENTS.md", "CLAUDE.md", "LICENSE", "integrity.json", "verify-integrity.cjs"):
            archive.write(folder / name, name)
        for icon in sorted((folder / "icons").glob("*.png")):
            archive.write(icon, icon.relative_to(folder))
    print(path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)
    build(out, "claude", HERE)
    build(out, "codex", HERE / "codex", extra=[HERE / "LICENSE"])

    build_extension(out)
