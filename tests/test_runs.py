#!/usr/bin/env python3
"""What became of a command he asked the tower to run (task 123, the owner in thread suda m430: "after a command was
run, I want its mark to update to done").

    threads run-status <id> <mN> <block> running|ok|fail [--note "<one line>"]

<mN> is the tower's message with the block and <block> is `run.block_index` of the pending row (0 = the first
block). It is kept on the tower's message, per block; nobody's turn moves and nobody is told."""
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
TOWER_MSG = 'מריץ:\n```sh\n! echo hello\n```\nואחר כך:\n```sh\n! uptime\n```\n'


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-runs-', dir=ROOT)
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
        self.cli('new', 'ops', 'פקודות', '--state', 'working', '--note', 'x')
        self.cli('say', 'ops', '--from', 'tower', TOWER_MSG, '--state', 'on-owner', '--note', 'להריץ?')     # m1
        self.cli('say', 'ops', '--from', 'fork', 'סתם הודעה', '--state', 'working', '--note', 'y')              # m2

    def ask(self, mid, block, command):
        """He presses ▶ on block `block` of the tower's message `mid` and confirms: the page's own op."""
        import hashlib
        (self.board / 'state').mkdir(exist_ok=True)
        op = {'op': 'reply', 'thread': 'ops', 'text': '▶ הרץ', 'cid': f'run-{mid}-{block}-{len(self.t()["messages"])}',
              'run': {'msg_id': mid, 'block_index': block, 'sha256': hashlib.sha256(command.encode()).hexdigest()}}
        (self.board / 'state/state.json').write_text(json.dumps(op, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(CLI), 'ingest'], env=self.env, capture_output=True, text=True)
        got = json.loads(r.stdout.strip().splitlines()[-1])
        assert got.get('ok'), got
        return got['msg_id']

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def t(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))['threads']['ops']

    def msg(self, mid):
        return next(m for m in self.t()['messages'] if m['id'] == mid)

    def test_the_tower_says_what_became_of_a_block(self):
        self.ask('m1', 0, '! echo hello')
        self.ask('m1', 1, '! uptime')
        if self.record.exists():
            self.record.unlink()        # his two requests told the tower, as they should; what follows tells nobody
        before = self.t()
        self.cli('run-status', 'ops', 'm1', '0', 'running')
        self.assertEqual(self.msg('m1')['runs']['0']['state'], 'running')
        self.cli('run-status', 'ops', 'm1', '0', 'ok', '--note', 'יצא hello')
        self.cli('run-status', 'ops', 'm1', '1', 'fail', '--note', 'exit 1')
        runs = self.msg('m1')['runs']
        self.assertEqual((runs['0']['state'], runs['0']['note'], runs['1']['state']), ('ok', 'יצא hello', 'fail'))
        self.assertIsInstance(runs['0']['ts'], float)
        after = self.t()
        self.assertEqual((after['state'], after['note'], after['state_by']), (before['state'], before['note'], before['state_by']))
        self.assertFalse(self.record.exists() and self.record.read_text().strip(), 'a run status sent mail')

    def test_what_is_refused(self):
        self.ask('m1', 0, '! echo hello')
        for args in (('run-status', 'ops', 'm1', '1', 'ok'),         # a block he never asked to run
                     ('run-status', 'ops', 'm1', '2', 'ok'),        # there is no third block
                     ('run-status', 'ops', 'm1', '-1', 'ok'),
                     ('run-status', 'ops', 'm2', '0', 'ok'),        # not the tower's message with a block
                     ('run-status', 'ops', 'm9', '0', 'ok'),
                     ('run-status', 'nope', 'm1', '0', 'ok'),
                     ('run-status', 'ops', 'm1', '0', 'done'),
                     ('run-status', 'ops', 'm1', '0', 'ok', '--note', 'x' * 201)):
            self.cli(*args, ok=False)
        self.assertNotIn('runs', self.msg('m1'))

    def test_the_summary_carries_it(self):
        self.ask('m1', 0, '! echo hello')
        self.cli('run-status', 'ops', 'm1', '0', 'ok')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        tail = {m['id']: m for m in summary['threads']['ops']['messages']}
        self.assertEqual(tail['m1']['runs']['0']['state'], 'ok')


if __name__ == '__main__':
    unittest.main()
