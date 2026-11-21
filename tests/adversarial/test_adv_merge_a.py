#!/usr/bin/env python3
"""Adversarial review of the merge (task 113): state and server/CLI. Each test asserts the CORRECT outcome,
so a FAIL is a hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_merge

_M = test_merge.Merge


class MergeHoles(unittest.TestCase):
    setUp, cli, state, t, ingest = _M.setUp, _M.cli, _M.state, _M.t, _M.ingest

    def raw(self, *args):
        import subprocess, sys
        return subprocess.run([sys.executable, str(test_merge.CLI), *args], env=self.env, capture_output=True, text=True)

    def write(self, data):
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    # his own press must not push / ring him about the line it writes
    def test_his_own_merge_from_the_page_does_not_push_him(self):
        self.cli('say', 'big', '--from', 'fork', 'דוח: נגמר שלב א')        # big is on him (read this)
        last = self.t('big')['messages'][-1]['id']
        self.assertTrue(self.ingest({'op': 'seen', 'thread': 'big', 'last': last})['ok'])
        self.assertNotIn('alert', self.t('big'))
        self.assertTrue(self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big'})['ok'])
        self.assertNotIn('alert', self.t('big'), 'the merge line is news: a push (and later his phone) for his own press')

    # the page writes into a merged thread
    def test_the_page_cannot_reopen_a_moved_task_in_the_merged_source(self):
        self.cli('merge', 'small', '--into', 'big')
        got = self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'todo'})
        k = next(k for k in self.t('small')['tasks'] if k['n'] == 1)
        self.assertFalse(got['ok'], 'page op task wrote into a merged thread (the CLI refuses it)')
        self.assertEqual(k['status'], 'done')

    def test_a_moved_task_opened_again_after_reopen_moves_on_the_next_merge(self):
        self.cli('merge', 'small', '--into', 'big')
        self.cli('reopen', 'small')
        self.cli('task', 'set', 'small', '1', 'todo', '--note', 'עוד לא')
        self.cli('merge', 'small', '--into', 'big')
        left = [k['n'] for k in self.t('small')['tasks'] if k.get('status') != 'done']
        self.assertEqual(left, [], 'an open task stays behind in the closed, merged source (moved_to is never cleared)')

    def test_merge_does_not_close_over_a_question_he_has_not_seen(self):
        seen = self.t('small')['messages'][-1]['id']
        self.cli('ask', 'small', 'לאשר את המחיקה?', '--options', 'כן,לא')
        got = self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big', 'last': seen})
        self.assertFalse(got['ok'], 'merge ignores `last` (close and done honour it); the new question is dropped')
        self.assertIsNotNone(self.t('small')['question'])

    def test_a_target_whose_deadline_passes_is_not_archived_under_his_merge(self):
        self.cli('policy', '--resolved-hours', '0')
        self.cli('task', 'set', 'big', '1', 'done')
        self.cli('resolve', 'big', '--note', 'נגמר')
        self.assertEqual(self.t('big')['status'], 'open')
        time.sleep(1.1)
        got = self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big'})
        self.assertTrue(got['ok'], f'the sweep of the same command archived the target first: {got}')

    def test_moved_open_tasks_wake_a_target_that_says_done(self):
        self.cli('task', 'set', 'big', '1', 'done')
        self.cli('state', 'big', 'done', '--note', 'נגמר')
        self.cli('merge', 'small', '--into', 'big')
        big = self.t('big')
        self.assertTrue([k for k in big['tasks'] if k['status'] != 'done'])
        self.assertNotEqual(big['state'], 'done', 'a thread that says done with open tasks (task add calls undone())')

    # lifecycle / damaged state
    def test_an_open_thread_left_with_merged_into_is_not_stuck(self):
        self.cli('merge', 'small', '--into', 'big')
        data = self.state()
        data['threads']['small']['status'] = 'open'      # reopened by an older CLI: heal() mends the rest
        self.write(data)
        self.raw('reopen', 'small')                       # a no-op: it is open
        r = self.raw('say', 'small', '--from', 'fork', 'חזרתי')
        self.assertEqual(r.returncode, 0, 'open + merged_into: every write refused, reopen is a no-op, merge refused: stuck. ' + r.stderr)

    def test_rm_of_the_target_does_not_leave_a_false_merge(self):
        self.cli('merge', 'small', '--into', 'big')
        self.cli('rm', 'big', '--yes')
        self.cli('new', 'big', 'נושא אחר לגמרי', '--state', 'working', '--note', 'x')
        self.cli('merge', 'small', '--into', 'big')
        self.assertIn('small', self.t('big').get('merged_from', []),
                      'the new, unrelated "big" is taken as the old merge: "already merged", nothing moved')

    def test_an_agent_cannot_merge_in_his_name_or_as_the_archive(self):
        for by in ('owner', 'auto'):
            r = self.raw('merge', 'small', '--into', 'big', '--by', by)
            self.assertNotEqual(r.returncode, 0, f'--by {by} accepted (close refuses it)')

    def test_a_hand_edited_merged_from_does_not_crash_the_merge(self):
        data = self.state()
        data['threads']['big']['merged_from'] = None
        self.write(data)
        r = self.raw('merge', 'small', '--into', 'big')
        self.assertTrue(r.returncode == 0 or 'פגום' in r.stderr, r.stderr)

    def test_ack_of_his_reply_in_a_merged_source_keeps_it_merged_and_done(self):
        self.cli('merge', 'small', '--into', 'big')
        self.cli('ack', 'small', 'm2')
        src = self.t('small')
        self.assertEqual(src['state'], 'done', f"a closed merged thread now says {src['state']}: {src['note']}")


del _M      # not a test case of this file


if __name__ == '__main__':
    unittest.main()
