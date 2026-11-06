"""Show the latest plan-limit snapshot recorded by Codex. Never read auth.json."""
import json
import sqlite3
import time
from datetime import datetime
from token_calc import data_dir, has_limits, recover_limits, when


_next_recover = 0.0


def sign_in_stamp():
    return (None, None)


def account():
    return (None, None)


def account_email():
    return None


def reset_text(value, now=None):
    if not value: return ''
    now = now or datetime.now().astimezone()
    if value <= now: return 'snapshot expired'
    return 'resets ' + value.strftime('%a %I:%M %p').replace(' 0', ' ')


def read_snapshot(timeout):
    with sqlite3.connect(data_dir() / 'usage.sqlite3', timeout=timeout) as db:
        return db.execute("SELECT data FROM settings WHERE key='limits'").fetchone()


def fetch(timeout=10):
    global _next_recover
    try:
        row = read_snapshot(timeout)
        if (not row or not has_limits(json.loads(row[0])['limits'])) and time.monotonic() >= _next_recover:
            _next_recover = time.monotonic() + 300     # log search is heavier: at most every 5 min
            if recover_limits():
                row = read_snapshot(timeout)
        if not row: return {'ok': False, 'error': 'No plan snapshot yet · use Codex first'}
        d = json.loads(row[0]); lim = d['limits']
        age = max(0, int((datetime.now().astimezone()-when(d['timestamp'])).total_seconds()/60))
        limits = []
        for name, key in [('primary','five_hour'), ('secondary','seven_day')]:
            v = lim.get(name)
            if not isinstance(v, dict) or v.get('used_percent') is None: continue
            minutes = v.get('window_minutes')
            label = '5-hour limit' if minutes == 300 else 'Weekly limit' if minutes == 10080 else f'{minutes}-minute limit' if minutes else name.title()
            reset = datetime.fromtimestamp(v['resets_at']).astimezone() if v.get('resets_at') else None
            limits.append({'key': key, 'label': label, 'pct': max(0,min(100,float(v['used_percent']))), 'resets': reset})
        if not limits: return {'ok': False, 'error': 'No plan limits in latest snapshot'}
        scope = lim.get('limit_name') or lim.get('limit_id') or 'Codex'
        return {'ok': True, 'plan': lim.get('plan_type'), 'limits': limits,
                'note': f'{scope} · recorded {age}m ago · not live'}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, OverflowError):
        return {'ok': False, 'error': 'Recorded usage not available'}

if __name__ == '__main__':
    from token_calc import utf8_stdout
    utf8_stdout()
    result = fetch()
    print(result.get('note') or result.get('error'))
    for item in result.get('limits', []):
        print(f"{item['label']}: {item['pct']:.1f}% used · {reset_text(item['resets'])}")
