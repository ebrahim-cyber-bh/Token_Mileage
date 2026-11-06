#!/usr/bin/env python3
"""Local Codex usage ledger. No credentials, network requests, or model calls."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}
KEYS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')


def utf8_stdout():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def codex_dir():
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()


def data_dir():
    override = os.environ.get('CODEX_MILEAGE_DATA')
    if override:
        p = Path(override).expanduser()
    elif sys.platform == 'darwin':
        p = Path.home() / 'Library/Application Support/codex-odometer'
    elif os.name == 'nt':
        p = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'codex-odometer'
    else:
        p = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'codex-odometer'
    p.mkdir(parents=True, exist_ok=True)
    return p


def when(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone()


def counts(u):
    return [max(0, int(u.get(k) or 0)) for k in KEYS]


def has_limits(limits):
    """Codex also logs limit types with empty values (limit_id 'premium'); those must not replace real figures."""
    return isinstance(limits, dict) and any(isinstance(limits.get(k), dict) and limits[k].get('used_percent') is not None
                                            for k in ('primary', 'secondary'))


def recover_limits(files=20, tail=4_000_000):
    """Finds the newest real snapshot in recent logs and stores it. Returns True if one was found."""
    paths = [p for folder in ('sessions', 'archived_sessions') for p in (codex_dir() / folder).glob('**/*.jsonl')]
    paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:files]
    best = None
    for path in paths:
        with path.open('rb') as f:
            f.seek(max(0, path.stat().st_size - tail))
            for line in f.read().splitlines():
                if b'"rate_limits"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    limits, stamp = d['payload']['rate_limits'], d['timestamp']
                except (ValueError, KeyError, TypeError):
                    continue
                if has_limits(limits) and (not best or stamp > best['timestamp']):
                    best = {'timestamp': stamp, 'limits': limits}
    if not best:
        return False
    with sqlite3.connect(data_dir() / 'usage.sqlite3', timeout=5) as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES ('limits',?)", (json.dumps(best),))
    return True


class Ledger:
    """Incremental SQLite ledger with atomic offsets and deduplicated cumulative deltas.

    Both token_usage_record and token_count can describe the same response. Their
    cumulative session totals advance one shared watermark, so only one is counted.
    Cached input and reasoning are subsets, never added to input + output.
    """
    def __init__(self):
        self.db = sqlite3.connect(data_dir() / 'usage.sqlite3', timeout=15)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, pos INTEGER, state TEXT);
          CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, data TEXT);
          CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY, data TEXT);
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT);
        ''')
        self.titles = {}
        self.sessions = {s: json.loads(d) for s, d in self.db.execute('SELECT sid,data FROM sessions')}
        for sid, s in self.sessions.items():
            if s.get('title'): self.titles[sid] = (s['title'], False)

    def scan(self):
        changed = 0
        paths = set()
        for folder in ('sessions', 'archived_sessions'):
            paths.update((codex_dir() / folder).glob('**/*.jsonl'))
        with self.db:
            for path in sorted(paths):
                try:
                    size = path.stat().st_size
                    row = self.db.execute('SELECT pos,state FROM files WHERE path=?', (str(path),)).fetchone()
                    pos, state = (row[0], json.loads(row[1])) if row else (0, {})
                    if size < pos: pos = 0
                    if pos == size: continue
                    with path.open('rb') as f:
                        f.seek(pos)
                        while f.tell() < size:
                            line = f.readline()
                            if not line.endswith(b'\n'): break  # retry incomplete streamed JSON later
                            pos = f.tell()
                            if not any(x in line for x in (b'"session_meta"', b'"turn_context"', b'"token_count"', b'"token_usage_record"', b'"task_started"', b'"task_complete"', b'"turn_aborted"', b'"session_name"')):
                                continue
                            try:
                                d = json.loads(line)
                                changed += self._take(d, state, path)
                            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                                continue
                    self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?)', (str(path), pos, json.dumps(state)))
                except OSError:
                    continue
        return changed

    def _take(self, d, state, path):
        p = d.get('payload') or {}
        typ = d.get('type')
        if typ == 'session_meta':
            state['sid'] = p.get('id') or p.get('session_id') or path.stem
            state['cwd'] = p.get('cwd', '')
        sid = state.get('sid', path.stem)
        s = self.sessions.setdefault(sid, {'sid': sid, 'totals': [0]*4})
        s['cwd'] = state.get('cwd', s.get('cwd', ''))
        if typ == 'turn_context': s['model'] = p.get('model', s.get('model', 'unknown'))
        if typ == 'event_msg' and p.get('type') in ('task_started', 'task_complete', 'turn_aborted'):
            s['busy'] = p['type'] == 'task_started'
            s['activity'] = d['timestamp']
        if typ == 'event_msg' and p.get('type') == 'session_name':
            s['title'] = p.get('name') or p.get('title')
            self.titles[sid] = (s['title'], False)
        u = None
        limits = None
        if typ == 'token_usage_record':
            u = p.get('thread_token_usage')
        elif typ == 'event_msg' and p.get('type') == 'token_count':
            u = (p.get('info') or {}).get('total_token_usage')
            limits = p.get('rate_limits')
        change = 0
        if u:
            current = counts(u)
            previous = s.get('totals', [0]*4)
            # A lower watermark can be a replay/older copy: never count it again.
            delta = [max(0, a-b) for a,b in zip(current, previous)]
            s['totals'] = [max(a,b) for a,b in zip(current, previous)]
            if delta[0] or delta[2]:
                key = sid + ':' + ':'.join(map(str, current))
                rec = {'when': d['timestamp'], 'session': sid, 'project': s['cwd'],
                       'model': s.get('model', 'unknown'), 'u': dict(zip(KEYS, delta)),
                       'tokens': delta[0] + delta[2]}
                self.db.execute('INSERT OR IGNORE INTO records VALUES (?,?)', (key, json.dumps(rec)))
                change = 1
            if d['timestamp'] >= s.get('activity', ''):
                s['activity'] = d['timestamp']
        if has_limits(limits):
            old = self.db.execute("SELECT data FROM settings WHERE key='limits'").fetchone()
            if not old or d['timestamp'] >= json.loads(old[0])['timestamp']:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('limits',?)", (json.dumps({'timestamp': d['timestamp'], 'limits': limits}),))
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (sid, json.dumps(s)))
        return change

    def snapshot(self):
        out = []
        for data, in self.db.execute('SELECT data FROM records'):
            r = json.loads(data)
            r['when'] = when(r['when'])
            out.append(r)
        return out


def live_sessions(records):
    """Recent log activity, not proof of a live process (works in isolated sandboxes)."""
    now = datetime.now().astimezone()
    with sqlite3.connect(data_dir() / 'usage.sqlite3', timeout=5) as db:
        rows = db.execute('SELECT data FROM sessions').fetchall()
    out = []
    for data, in rows:
        s = json.loads(data)
        try:
            t = when(s['activity']); age = (now-t).total_seconds()
        except (KeyError, ValueError): continue
        if not 0 <= age < 900: continue
        out.append({'sid': s['sid'], 'busy': age < 120 and s.get('busy', True),
                    'name': s.get('title'), 'cwd': s.get('cwd', ''), 'started': t.timestamp()})
    return sorted(out, key=lambda s: s['started'])


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--today', action='store_true')
    ap.add_argument('--days', type=int)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    led = Ledger(); led.scan(); rows = led.snapshot()
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) if args.today else now-timedelta(days=args.days) if args.days else None
    if start: rows = [r for r in rows if r['when'] >= start]
    total = {k: sum(r['u'].get(k, 0) for r in rows) for k in KEYS}
    total['total_tokens'] = total['input_tokens'] + total['output_tokens']
    total['uncached_input_tokens'] = max(0, total['input_tokens']-total['cached_input_tokens'])
    total['sessions'] = len({r['session'] for r in rows})
    groups = {}
    for r in rows:
        for field in ('model', 'project', 'session'):
            bucket = groups.setdefault(field, {})
            bucket[r[field]] = bucket.get(r[field], 0) + r['tokens']
    if args.json: print(json.dumps({'totals': total, 'breakdown': groups}, indent=2))
    else:
        print('Codex Token Mileage · By Alna\nLocal recorded usage · not your subscription bill\n')
        for k,v in total.items(): print(f'{k.replace("_", " "):25} {v:>16,}')
        for field, bucket in groups.items():
            print(f'\nBy {field}')
            for key,value in sorted(bucket.items(), key=lambda kv: -kv[1])[:15]: print(f'  {value:>16,}  {key}')
    led.db.close()

if __name__ == '__main__': main()
