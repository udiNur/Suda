#!/usr/bin/env python3
"""A visible answer on HIS messages (task 118, the owner in thread suda m404): "when I tell an agent do this, do
that, and it does it, I would rather it marked a green ✅ on what I asked, so I do not feel it was left unanswered."

    threads react <id> <mN> ✅ [--by NAME] [--off]

An agent marks one of his messages done (or 👍 / ❓ like his own quick marks). It is the agent's mark, never his:
it does not take his own mark away, an agent cannot write in his name, and nobody's turn moves for it."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = _paths.APP
CLI = ROOT / 'threads.py'


class Acks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-acks-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.board = root / 'boards/threads'
        self.record = root / 'mail.jsonl'
        recorder = root / 'record.py'
        recorder.write_text("import json, os, sys\nwith open(os.environ['NOTIFY_RECORD'], 'a') as f:\n f.write(json.dumps(sys.argv[1:])+'\\n')\n")
        self.env = dict(os.environ, BOARDS_DIR=str(root / 'boards'), NOTIFY_RECORD=str(self.record),
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]))
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'TUIOS_PANE_ID'):
            self.env.pop(key, None)
        self.cli('new', 'job', 'עבודה', '--state', 'working', '--note', 'x', '--by', 'a1')
        self.cli('say', 'job', '--from', 'owner', 'תעשה את זה ואת זה')          # m1
        self.cli('say', 'job', '--from', 'fork', 'עושה', '--state', 'working', '--note', 'y')

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def t(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))['threads']['job']

    def msg(self, mid):
        return next(m for m in self.t()['messages'] if m['id'] == mid)

    def ingest(self, op):
        (self.board / 'state').mkdir(exist_ok=True)
        (self.board / 'state/state.json').write_text(json.dumps(op, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(CLI), 'ingest'], env=self.env, capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_agent_marks_his_message_done(self):
        before = self.t()
        self.cli('react', 'job', 'm1', '✅', '--by', 'a1')
        after = self.t()
        mark = self.msg('m1')['reactions']['✅']
        self.assertEqual(mark['by'], 'a1')
        self.assertIsInstance(mark['ts'], float)
        # nobody's turn moves, nobody is told
        self.assertEqual((after['state'], after['note'], after['state_by']), (before['state'], before['note'], before['state_by']))
        self.assertFalse(self.record.exists() and self.record.read_text().strip(), 'a mark sent mail')
        # again: nothing new; --off takes the agent's mark away
        self.cli('react', 'job', 'm1', '✅', '--by', 'a1')
        self.assertEqual(self.msg('m1')['reactions']['✅'], mark)
        self.cli('react', 'job', 'm1', '✅', '--off')
        self.assertNotIn('reactions', self.msg('m1'))

    def test_done_is_also_picked_up(self):
        """A ✅ on a message of his that no agent picked up yet picks it up as well: it leaves `threads pending`
        (the tower would send it to a fork again), and the turn still does not move."""
        before = self.t()
        self.assertIn('m1', [r['msg_id'] for r in json.loads(self.cli('pending').stdout)])
        self.cli('react', 'job', 'm1', '✅', '--by', 'a1')
        self.assertEqual(self.msg('m1')['status'], 'acked')
        self.assertNotIn('m1', [r['msg_id'] for r in json.loads(self.cli('pending').stdout)])
        self.assertEqual((self.t()['state'], self.t()['note']), (before['state'], before['note']))

    def test_without_a_name_it_is_an_agents_mark(self):
        self.cli('react', 'job', 'm1', '✅')
        self.assertEqual(self.msg('m1')['reactions']['✅']['by'], 'agent')

    def test_his_own_mark_is_never_taken_over_or_away(self):
        self.assertTrue(self.ingest({'op': 'react', 'thread': 'job', 'msg': 'm2', 'emoji': '👍', 'on': True})['ok'])
        self.cli('react', 'job', 'm2', '👍', '--by', 'a1')
        self.assertEqual(self.msg('m2')['reactions']['👍']['by'], 'owner')
        self.cli('react', 'job', 'm2', '👍', '--off')
        self.assertEqual(self.msg('m2')['reactions']['👍']['by'], 'owner')

    def test_what_is_refused(self):
        for args in (('react', 'job', 'm1', '🎉'), ('react', 'job', 'm99', '✅'), ('react', 'nope', 'm1', '✅'),
                     ('react', 'job', 'm1', '✅', '--by', 'owner'), ('react', 'job', 'm1', '✅', '--by', 'Owner'),
                     ('react', 'job', 'm1', '✅', '--by', 'auto')):
            self.cli(*args, ok=False)
        self.assertNotIn('reactions', self.msg('m1'))

    def test_a_merged_thread_points_to_where_it_went(self):
        self.cli('new', 'big', 'גדול', '--state', 'working', '--note', 'x')
        self.cli('merge', 'job', '--into', 'big')
        self.assertIn('big', self.cli('react', 'job', 'm1', '✅', ok=False).stderr)

    def test_the_page_still_shows_whose_mark_it_is(self):
        self.cli('react', 'job', 'm1', '✅', '--by', 'a1')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        tail = {m['id']: m for m in summary['threads']['job']['messages']}
        self.assertEqual(tail['m1']['reactions']['✅']['by'], 'a1')


if __name__ == '__main__':
    unittest.main()
