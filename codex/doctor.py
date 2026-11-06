"""Check local Codex Mileage requirements without reading sign-in credentials."""
import importlib.util
from pathlib import Path
from token_calc import codex_dir

def main():
    here=Path(__file__).resolve().parent
    source=(here/'token_popup.py').read_text(encoding='utf-8')
    checks={'Python Tk module': importlib.util.find_spec('tkinter') is not None,
            'Codex session logs': (codex_dir()/'sessions').is_dir(),
            'By Alna credit': '_SIG = "QnkgQWxuYQ=="' in source and 'text=credit()' in source,
            'License': (here.parent/'LICENSE').exists()}
    for label,ok in checks.items(): print(f'[{"ok" if ok else "fail"}] {label}')
    return 0 if all(checks.values()) else 1

if __name__=='__main__': raise SystemExit(main())
