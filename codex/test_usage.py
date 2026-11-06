import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import token_calc
import plan_usage

class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(p/'codex'), 'CODEX_MILEAGE_DATA': str(p/'data')})
        self.env.start()
        self.path = p/'codex/sessions/test.jsonl'; self.path.parent.mkdir(parents=True)
        self.write('session_meta', {'id': 'session1', 'cwd': '/project'})
        self.write('turn_context', {'model': 'test-model'})
        self.led = token_calc.Ledger()
    def tearDown(self):
        self.led.db.close(); self.env.stop(); self.tmp.cleanup()
    def write(self, typ, payload):
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'type':typ, 'timestamp':'2026-11-01T20:00:00Z', 'payload':payload})+'\n')
    def usage(self, i, o, cache=0, reason=0):
        return dict(zip(token_calc.KEYS, [i,cache,o,reason]))
    def test_duplicate_formats_and_restart(self):
        u = self.usage(100,20,80,5)
        self.write('token_usage_record', {'thread_token_usage':u})
        self.write('event_msg', {'type':'token_count', 'info':{'total_token_usage':u}})
        self.led.scan()
        self.assertEqual(sum(r['tokens'] for r in self.led.snapshot()),120)
        self.assertEqual(self.led.scan(),0)
        self.led.db.close(); self.led = token_calc.Ledger(); self.led.scan()
        self.assertEqual(sum(r['tokens'] for r in self.led.snapshot()),120)
        self.write('event_msg', {'type':'token_count','info':{'total_token_usage':self.usage(150,30,100,8)}})
        self.led.scan()
        self.assertEqual(sum(r['tokens'] for r in self.led.snapshot()),180)
    def test_partial_line_then_complete_and_archive(self):
        data = json.dumps({'type':'event_msg','timestamp':'2026-11-01T20:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':self.usage(50,10)}}})
        with self.path.open('a', encoding='utf-8') as f: f.write(data[:40])
        self.led.scan(); self.assertEqual(len(self.led.snapshot()),0)
        with self.path.open('a', encoding='utf-8') as f: f.write(data[40:]+'\n')
        self.led.scan(); self.assertEqual(self.led.snapshot()[0]['tokens'],60)
        dest = self.path.parent.parent/'archived_sessions/test.jsonl';dest.parent.mkdir();self.path.rename(dest)
        self.led.scan(); self.assertEqual(sum(r['tokens'] for r in self.led.snapshot()),60)
        dest.unlink(); self.led.scan(); self.assertEqual(len(self.led.snapshot()),1)
    def test_rate_limits_and_malformed_line(self):
        with self.path.open('a', encoding='utf-8') as f: f.write('{broken json\n')
        self.write('event_msg', {'type':'token_count','info': None, 'rate_limits':{'limit_id':'codex','primary':{'used_percent':25,'window_minutes':300,'resets_at':1793600000}}})
        self.led.scan(); result = plan_usage.fetch()
        self.assertTrue(result['ok']); self.assertEqual(result['limits'][0]['pct'],25)
        self.assertIn('not live', result['note'])
    def test_empty_limit_type_keeps_real_snapshot(self):
        real = {'limit_id':'codex','primary':{'used_percent':33,'window_minutes':300,'resets_at':1793600000}}
        self.write('event_msg', {'type':'token_count','info':None,'rate_limits':real})
        self.write('event_msg', {'type':'token_count','info':None,'rate_limits':{'limit_id':'premium','primary':None,'secondary':None}})
        self.led.scan(); result = plan_usage.fetch()
        self.assertTrue(result['ok']); self.assertEqual(result['limits'][0]['pct'],33)
    def test_recovers_snapshot_already_overwritten(self):
        self.write('event_msg', {'type':'token_count','info':None,'rate_limits':{'limit_id':'codex','primary':{'used_percent':33,'window_minutes':300,'resets_at':1793600000}}})
        self.led.db.execute("INSERT OR REPLACE INTO settings VALUES ('limits',?)", (json.dumps({'timestamp':'2026-11-02T00:00:00Z','limits':{'limit_id':'premium','primary':None,'secondary':None}}),))
        self.led.db.commit(); plan_usage._next_recover = 0.0
        result = plan_usage.fetch()
        self.assertTrue(result['ok']); self.assertEqual(result['limits'][0]['pct'],33)
    def test_replayed_older_cumulative_total(self):
        for i,o in [(100,20),(50,10),(150,30)]:
            self.write('event_msg', {'type':'token_count','info':{'total_token_usage':self.usage(i,o)}})
        self.led.scan(); self.assertEqual(sum(r['tokens'] for r in self.led.snapshot()),180)

if __name__ == '__main__': unittest.main()
