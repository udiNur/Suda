#!/usr/bin/env python3
"""Spaces (task 114, the owner in thread suda m377, m380, m392, m418, m425): a few separate spaces of threads (the first:
support tickets), switched with a small square at the top-left of the page, like Slack's workspaces. Nothing is
always on the screen when there is one space only.

    threads space add <id> "<name>" [--prefix sup-]... [--letter X] [--color #rrggbb]
    threads space set <id> [--name …] [--prefix …]... [--letter …] [--color …]
    threads space rm <id>
    threads space list [--json]
    threads move <thread> --space <id|main>

A thread is in the space its own choice names (`space`), else in the first space whose prefix its id starts with,
else in the main one ('main', always there, never stored). The tower's thread is always in the main space. The page
moves a thread with the op 'space-move' and adds a space with 'space-new'."""
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


class Spaces(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-spaces-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.board = root / 'boards/threads'
        self.record = root / 'mail.jsonl'
        recorder = root / 'record.py'
        recorder.write_text("import json, os, sys\nwith open(os.environ['NOTIFY_RECORD'], 'a') as f:\n f.write(json.dumps(sys.argv[1:])+'\\n')\n")
        self.env = dict(os.environ, BOARDS_DIR=str(root / 'boards'), NOTIFY_RECORD=str(self.record),
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]))
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'TUIOS_PANE_ID', 'THREADS_CONFIG_DIR'):
            self.env.pop(key, None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (root / '.threads-config/threads').mkdir(parents=True)
        (root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')
        for tid in ('main-one', 'sup-8', 'sup-9', 'tower'):
            self.cli('new', tid, 'נושא ' + tid, '--state', 'working', '--note', 'x')

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def data(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def ingest(self, op):
        (self.board / 'state').mkdir(exist_ok=True)
        (self.board / 'state/state.json').write_text(json.dumps(op, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(CLI), 'ingest'], env=self.env, capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_space_is_added_listed_changed_and_removed(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        sp = self.data()['spaces']
        self.assertEqual(len(sp), 1)
        self.assertEqual((sp[0]['id'], sp[0]['name'], sp[0]['prefix'], sp[0]['letter']), ('support', 'תמיכה', ['sup-'], 'ת'))
        self.assertRegex(sp[0]['color'], r'^#[0-9a-f]{6}$')
        listed = json.loads(self.cli('space', 'list', '--json').stdout)
        self.assertEqual([s['id'] for s in listed], ['main', 'support'])
        self.assertEqual({s['id']: s['threads'] for s in listed}, {'main': ['main-one', 'tower'], 'support': ['sup-8', 'sup-9']})
        self.cli('space', 'set', 'support', '--name', 'לקוחות', '--letter', 'ל', '--color', '#123abc')
        self.assertEqual({k: self.data()['spaces'][0][k] for k in ('name', 'letter', 'color')}, {'name': 'לקוחות', 'letter': 'ל', 'color': '#123abc'})
        # a thread that chose this space goes back to the main one when the space goes
        self.cli('move', 'main-one', '--space', 'support')
        self.cli('space', 'rm', 'support')
        self.assertEqual(self.data().get('spaces'), [])
        self.assertNotIn('space', self.data()['threads']['main-one'])

    def test_a_thread_is_moved_in_and_out(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.cli('move', 'sup-8', '--space', 'main')            # a ticket he keeps in front of him
        self.cli('move', 'main-one', '--space', 'support')
        t = self.data()['threads']
        self.assertEqual((t['sup-8']['space'], t['main-one']['space']), ('main', 'support'))
        listed = {s['id']: s['threads'] for s in json.loads(self.cli('space', 'list', '--json').stdout)}
        self.assertEqual(listed, {'main': ['sup-8', 'tower'], 'support': ['main-one', 'sup-9']})
        # nobody's turn moves, nobody is told
        self.assertFalse(self.record.exists() and self.record.read_text().strip())

    def test_what_is_refused(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        for args in (('space', 'add', 'support', 'שוב'),                  # the same id
                     ('space', 'add', 'main', 'ראשי'),                    # the main space is not stored
                     ('space', 'add', 'Bad_Id', 'x'),
                     ('space', 'add', 'x1', ''),
                     ('space', 'add', 'x2', 'א' * 41),
                     ('space', 'add', 'x3', 'שם', '--prefix', '../'),
                     ('space', 'add', 'x4', 'שם', '--color', 'red'),
                     ('space', 'add', 'x5', 'שם', '--letter', 'abc'),
                     ('space', 'rm', 'nope'), ('space', 'rm', 'main'),
                     ('move', 'sup-8', '--space', 'nope'), ('move', 'nope', '--space', 'main'),
                     ('move', 'tower', '--space', 'support')):              # the tower's thread is always in the main space
            self.cli(*args, ok=False)
        for n in range(7):
            self.cli('space', 'add', f's{n}', f'מרחב {n}')
        self.cli('space', 'add', 's8', 'אחד יותר מדי', ok=False)            # eight at most: spaces are few
        self.assertEqual(len(self.data()['spaces']), 8)

    def test_the_page_moves_a_thread_and_adds_a_space(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        got = self.ingest({'op': 'space-move', 'thread': 'main-one', 'space': 'support'})
        self.assertEqual((got['ok'], got['space']), (True, 'support'), got)
        self.assertEqual(self.data()['threads']['main-one']['space'], 'support')
        self.assertTrue(self.ingest({'op': 'space-move', 'thread': 'main-one', 'space': 'main'})['ok'])
        self.assertEqual(self.data()['threads']['main-one']['space'], 'main')
        made = self.ingest({'op': 'space-new', 'name': 'לקוחות גדולים'})
        self.assertTrue(made['ok'], made)
        new = next(s for s in self.data()['spaces'] if s['id'] == made['space'])
        self.assertEqual((new['name'], new['letter'], new['prefix']), ('לקוחות גדולים', 'ל', []))
        for bad in ({'op': 'space-move', 'thread': 'main-one', 'space': 'nope'}, {'op': 'space-move', 'thread': 'tower', 'space': 'support'},
                    {'op': 'space-move', 'thread': 'main-one', 'space': ['x']}, {'op': 'space-new', 'name': ''},
                    {'op': 'space-new', 'name': 'x' * 41}, {'op': 'space-new'}):
            self.assertFalse(self.ingest(bad)['ok'], bad)

    def test_the_summary_carries_the_spaces_and_the_choices(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.cli('move', 'main-one', '--space', 'support')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual([s['id'] for s in summary['spaces']], ['support'])
        self.assertEqual(summary['threads']['main-one']['space'], 'support')
        self.assertIn('space-move', summary['ops'])

    def test_a_damaged_spaces_list_is_refused_like_any_damage(self):
        data = self.data()
        data['spaces'] = 'oops'
        (self.board / 'state.json').write_text(json.dumps(data), encoding='utf-8')
        self.assertIn('spaces', self.cli('list', ok=False).stderr)


if __name__ == '__main__':
    unittest.main()
