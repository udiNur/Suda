#!/usr/bin/env python3
"""Merging a thread into another (task 113, the owner in thread suda m377): "a merge state, so that one thread can
be merged into another, and it shows in the thread it was merged into, and on the other side it is a finished
thread, under a 'merged' category."

    threads merge <src> --into <dst> [--by NAME]

The source is closed and remembers where it went (merged_into); the target remembers where its new parts came
from (merged_from) and gets one message that says so, with the source's story in numbers; the open tasks of the
source move to the target (numbered there anew, each knowing its old number, and the old one says where it
went). Nothing is deleted. A second merge of the same two is nothing new. The page does the same through the
op 'merge'."""
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


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-merge-', dir=ROOT)
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
        self.cli('new', 'big', 'הנושא הגדול', '--state', 'working', '--note', 'x', '--by', 'a1')
        self.cli('new', 'small', 'נושא קטן', '--state', 'working', '--note', 'x', '--by', 'a2')
        self.cli('say', 'small', '--from', 'fork', 'הודעה ראשונה בקטן')
        self.cli('say', 'small', '--from', 'owner', 'תשובה שלי בקטן')
        self.cli('say', 'small', '--from', 'fork', 'עוד הודעה', '--state', 'working', '--note', 'y')
        self.cli('task', 'add', 'big', 'משימה של הגדול', '--owner', 'a1')
        self.cli('task', 'add', 'small', 'פתוחה 1', '--owner', 'a2')
        self.cli('task', 'add', 'small', 'גמורה', '--owner', 'a2')
        self.cli('task', 'add', 'small', 'פתוחה 2', '--owner', 'owner')
        self.cli('task', 'set', 'small', '2', 'done', '--note', 'נעשה')
        self.cli('task', 'set', 'small', '3', 'working', '--note', 'בדרך')

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def state(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def t(self, tid):
        return self.state()['threads'][tid]

    def ingest(self, op):
        (self.board / 'state').mkdir(exist_ok=True)
        (self.board / 'state/state.json').write_text(json.dumps(op, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(CLI), 'ingest'], env=self.env, capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])

    # ── the CLI ──────────────────────────────────────────────────────────────

    def test_the_source_closes_under_merged_and_the_target_tells_where_its_new_parts_came_from(self):
        before = self.t('small')
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        src, dst = self.t('small'), self.t('big')
        # the source: closed, merged, with its whole history
        self.assertEqual((src['status'], src['merged_into'], src['state']), ('closed', 'big', 'done'))
        self.assertEqual([m['id'] for m in src['messages']], [m['id'] for m in before['messages']])
        self.assertIsNone(src['question'])
        self.assertIn('big', src['note'])
        # the target: still open, one message that tells of the merge, and where it came from
        self.assertEqual(dst['status'], 'open')
        self.assertEqual(dst['merged_from'], ['small'])
        block = dst['messages'][-1]
        self.assertEqual(block['merge']['thread'], 'small')
        self.assertEqual(block['merge']['title'], 'נושא קטן')
        self.assertEqual(block['merge']['messages'], 3)
        self.assertEqual(block['merge']['by'], 'tower')
        self.assertIn('small', block['text'])
        self.assertNotEqual(block['from'], 'owner', 'a merge is not a reply of his for the tower')
        # every task moved, the done one too (suda-fixes task 34: the target holds the whole list), numbered after the
        # target's own; the old ones say where they went
        moved = [k for k in dst['tasks'] if k.get('moved_from')]
        self.assertEqual([(k['n'], k['text'], k['status'], k['owner'], k['moved_from']) for k in moved],
                         [(2, 'פתוחה 1', 'todo', 'a2', {'thread': 'small', 'n': 1}), (3, 'גמורה', 'done', 'a2', {'thread': 'small', 'n': 2}),
                          (4, 'פתוחה 2', 'working', 'owner', {'thread': 'small', 'n': 3})])
        self.assertEqual(moved[2]['note'], 'בדרך')
        self.assertEqual(moved[1]['note'], 'נעשה')
        old = {k['n']: k for k in src['tasks']}
        self.assertEqual((old[1]['status'], old[1]['moved_to']), ('done', {'thread': 'big', 'n': 2}))
        self.assertEqual((old[2]['status'], old[2]['moved_to']), ('done', {'thread': 'big', 'n': 3}))
        self.assertEqual((old[3]['status'], old[3]['moved_to']), ('done', {'thread': 'big', 'n': 4}))
        self.assertEqual(old[2]['note'], 'נעשה', 'a done one keeps its own line')
        self.assertEqual(block['merge']['tasks'], [[1, 2], [2, 3], [3, 4]])
        # nobody is rung or mailed for it
        self.assertFalse(self.record.exists() and self.record.read_text().strip(), 'a merge sent mail')

    def test_a_second_merge_of_the_same_two_is_nothing_new(self):
        self.cli('merge', 'small', '--into', 'big')
        once = self.state()
        r = self.cli('merge', 'small', '--into', 'big')
        self.assertEqual(self.state()['threads'], once['threads'])
        self.assertIn('already', r.stdout + r.stderr)      # (the CLI speaks English here: no config.json)

    def test_what_cannot_be_merged(self):
        self.cli('new', 'gone', 'סגור', '--state', 'working', '--note', 'x')
        self.cli('close', 'gone', '--force')
        self.cli('new', 'tower', 'מגדל', '--state', 'working', '--note', 'x')
        for args, words in ((('small', '--into', 'small'), 'itself'),
                            (('small', '--into', 'gone'), 'closed'),
                            (('small', '--into', 'nope'), 'not found'),
                            (('nope', '--into', 'big'), 'not found'),
                            (('tower', '--into', 'big'), 'tower'),
                            (('small', '--into', 'Bad_Id'), '')):
            r = self.cli('merge', *args, ok=False)
            self.assertIn(words, r.stderr, args)
        self.assertEqual(self.t('small')['status'], 'open')
        # merged into one, it cannot be merged into another
        self.cli('new', 'third', 'שלישי', '--state', 'working', '--note', 'x')
        self.cli('merge', 'small', '--into', 'big')
        self.assertIn('big', self.cli('merge', 'small', '--into', 'third', ok=False).stderr)
        # a thread that has others merged into it can itself be merged on: its story goes along
        self.cli('merge', 'big', '--into', 'third')
        self.assertEqual(self.t('third')['merged_from'], ['big'])
        self.assertEqual(self.t('small')['merged_into'], 'big')

    def test_writing_into_the_merged_thread_points_to_where_it_went(self):
        self.cli('merge', 'small', '--into', 'big')
        for args in (('say', 'small', '--from', 'fork', 'שלום'), ('state', 'small', 'working', '--note', 'x'),
                     ('ask', 'small', 'שאלה?'), ('task', 'add', 'small', 'חדשה'), ('task', 'set', 'small', '1', 'working')):
            r = self.cli(*args, ok=False)
            self.assertIn('big', r.stderr, args)
        self.assertEqual(len(self.t('small')['messages']), 3)

    def test_reopened_it_is_no_longer_merged_and_the_target_keeps_its_story(self):
        self.cli('merge', 'small', '--into', 'big')
        self.cli('reopen', 'small')
        src, dst = self.t('small'), self.t('big')
        self.assertEqual(src['status'], 'open')
        self.assertNotIn('merged_into', src)
        self.assertEqual(dst['messages'][-1]['merge']['thread'], 'small')
        self.cli('say', 'small', '--from', 'fork', 'חזרתי', '--state', 'working', '--note', 'x')
        # merged again: a second story; the tasks that went the first time do not go twice
        self.cli('merge', 'small', '--into', 'big')
        self.assertEqual(len([m for m in self.t('big')['messages'] if m.get('merge')]), 2)
        self.assertEqual(len([k for k in self.t('big')['tasks'] if k.get('moved_from')]), 3)      # the done one too (task 34)

    def test_a_reply_of_his_still_waiting_in_the_source_tells_the_tower_where_to_answer(self):
        self.cli('merge', 'small', '--into', 'big')
        rows = [r for r in json.loads(self.cli('pending').stdout) if r['thread'] == 'small']
        self.assertEqual([r['merged_into'] for r in rows], ['big'])

    def test_the_summary_carries_both_ends(self):
        self.cli('merge', 'small', '--into', 'big')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['threads']['small']['merged_into'], 'big')
        self.assertEqual(summary['threads']['big']['merged_from'], ['small'])
        self.assertIn('merge', summary['ops'])

    # ── the page ─────────────────────────────────────────────────────────────

    def test_the_page_merges_through_the_op(self):
        got = self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big'})
        self.assertEqual((got['ok'], got['into']), (True, 'big'), got)
        self.assertEqual(self.t('small')['merged_into'], 'big')
        self.assertEqual(self.t('big')['messages'][-1]['merge']['by'], 'owner')
        again = self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big'})
        self.assertEqual(again['ok'], True)
        self.assertEqual(len([m for m in self.t('big')['messages'] if m.get('merge')]), 1)
        for bad in ({'op': 'merge', 'thread': 'big', 'into': 'big'}, {'op': 'merge', 'thread': 'big'},
                    {'op': 'merge', 'thread': 'big', 'into': ['x']}, {'op': 'merge', 'thread': 'big', 'into': 'nope'}):
            self.assertEqual(self.ingest(bad)['ok'], False, bad)


if __name__ == '__main__':
    unittest.main()
