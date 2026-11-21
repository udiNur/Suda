import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import unittest

import test_threads

ROOT = _paths.APP


class AdvTaskText(test_threads.ThreadsTests):
    """Hostile review of `threads task set --text` (tasktext140). FAIL = real hole."""

    def state_path(self):
        return self.board / 'state.json'

    def edit_task(self, fn, tid='topic', n=1):
        p = self.state_path()
        data = json.loads(p.read_text())
        task = next(k for k in data['threads'][tid]['tasks'] if k['n'] == n)
        fn(task)
        p.write_text(json.dumps(data, ensure_ascii=False))

    def base(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבנות את א', '--owner', 'fork', env=e(1))
        return e

    # --- malformed history already in state.json ---
    def test_adv_malformed_history_string_no_traceback(self):
        e = self.base()
        self.edit_task(lambda k: k.update(history='oops'))
        r = subprocess.run([sys.executable, str(test_threads.CLI), 'task', 'set', 'topic', '1', '--text', 'חדש'],
                           env=e(2), capture_output=True, text=True)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr)        # the task can still be corrected (history repaired)

    def test_adv_malformed_history_null_no_traceback(self):
        e = self.base()
        self.edit_task(lambda k: k.update(history=None))
        r = subprocess.run([sys.executable, str(test_threads.CLI), 'task', 'set', 'topic', '1', '--text', 'חדש'],
                           env=e(2), capture_output=True, text=True)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_adv_malformed_history_old_caller_unaffected(self):
        e = self.base()
        self.edit_task(lambda k: k.update(history='oops'))
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(2))
        self.assertEqual(self.thread(env=e(2))['tasks'][0]['status'], 'done')

    # --- validation ---
    def test_adv_whitespace_only_difference_records_nothing(self):
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', '--text', '\n  לבנות   את\tא \n', env=e(2))
        k = self.thread(env=e(2))['tasks'][0]
        self.assertEqual((k['text'], k.get('history')), ('לבנות את א', None))

    def test_adv_overlong_and_invisible_refused(self):
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', '--text', 'x' * 301, ok=False, env=e(2))
        self.run_cli('task', 'set', 'topic', '1', '--text', '‮‏​', ok=False, env=e(2))
        self.run_cli('task', 'set', 'topic', '1', '--text', '', ok=False, env=e(2))
        self.run_cli('task', 'set', 'topic', '1', '--text', ('y ' * 151), ok=False, env=e(2))  # 301 visible after one_line
        k = self.thread(env=e(2))['tasks'][0]
        self.assertEqual((k['text'], k.get('history')), ('לבנות את א', None))

    # Known, kept (review of tasktext140, Low): `short()` lets control characters through for task words, in
    # `task add` as on master; a fix belongs to both and to every short() field, not to --text alone. Strict.
    @unittest.expectedFailure
    def test_adv_control_chars_parity_with_add(self):
        """Pre-existing in `add` too: ESC survives one_line. Asserts that --text refuses it (FAIL = accepted)."""
        e = self.base()
        r = subprocess.run([sys.executable, str(test_threads.CLI), 'task', 'set', 'topic', '1', '--text', 'a\x1b[31mb\x07c'],
                           env=e(2), capture_output=True, text=True)
        k = self.thread(env=e(2))['tasks'][0]
        self.assertNotIn('\x1b', k['text'])

    # --- what a text-only / note-only set does to the rest ---
    def test_adv_text_only_keeps_by_archived_moved_to(self):
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(2))
        self.run_cli('task', 'archive', 'topic', '1', env=e(3))
        before = self.thread(env=e(3))['tasks'][0]
        self.run_cli('task', 'set', 'topic', '1', '--text', 'מילים אחרות', env=e(4))
        k = self.thread(env=e(4))['tasks'][0]
        self.assertEqual((k['status'], k['by'], k.get('archived')), ('done', before['by'], before.get('archived')))

    def test_adv_text_fix_does_not_move_a_done_thread(self):
        """Fixing a typo in an open task of a thread marked done flips the thread to working (turn moves)."""
        e = self.base()
        self.run_cli('state', 'topic', 'done', '--note', 'סיימתי', '--force', env=e(2))
        st = self.thread(env=e(2))['state']
        self.run_cli('task', 'set', 'topic', '1', '--text', 'לבנות את א!', env=e(3))
        self.assertEqual(self.thread(env=e(3))['state'], st)

    def test_adv_history_by_is_not_the_new_owner(self):
        """--text with --owner owner: history says owner corrected it, though an agent did."""
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', '--text', 'חדש', '--owner', 'owner', env=e(2))
        k = self.thread(env=e(2))['tasks'][0]
        self.assertNotEqual(k['history'][0]['by'], 'owner')

    def test_adv_same_text_alone_writes_nothing(self):
        e = self.base()
        before = self.thread(env=e(1))
        self.run_cli('task', 'set', 'topic', '1', '--text', 'לבנות את א', env=e(5))
        after = self.thread(env=e(5))
        self.assertEqual((after['tasks'][0]['updated'], after['updated']), (before['tasks'][0]['updated'], before['updated']))

    def test_adv_merge_keeps_history(self):
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', '--text', 'חדש', env=e(2))
        self.run_cli('new', 'other', 'אחר', env=e(3))
        self.run_cli('merge', 'topic', '--into', 'other', env=e(4))
        k = self.thread('other', env=e(4))['tasks'][-1]
        self.assertEqual(k.get('history', [{}])[0].get('text'), 'לבנות את א')

    def test_adv_merged_and_closed(self):
        e = self.base()
        self.run_cli('new', 'other', 'אחר', env=e(2))
        self.run_cli('merge', 'topic', '--into', 'other', env=e(3))
        self.run_cli('task', 'set', 'topic', '1', '--text', 'x', ok=False, env=e(4))
        self.run_cli('task', 'set', 'other', '1', '--text', 'בסגור', env=e(4))
        self.run_cli('close', 'other', env=e(5))
        r = self.run_cli('task', 'set', 'other', '1', '--text', 'בסגור 2', env=e(6))
        self.assertEqual(self.thread('other', env=e(6))['status'], 'closed')

    def test_adv_tasks_json_and_summary(self):
        e = self.base()
        self.run_cli('task', 'set', 'topic', '1', '--text', 'חדש', env=e(2))
        rows = json.loads(self.run_cli('tasks', 'topic', '--json', env=e(2)).stdout)
        self.assertEqual(rows[0]['text'], 'חדש')
        summary = json.loads((self.board / 'summary.json').read_text())
        st = json.loads((self.board / 'state.json').read_text())
        self.assertEqual(st['threads']['topic']['tasks'][0]['history'][0]['text'], 'לבנות את א')

    # --- old callers: byte-identical to master ---
    def test_adv_old_callers_identical_to_master(self):
        master = self.root / 'master_threads.py'
        shown = subprocess.run(['git', '-C', str(ROOT), 'show', 'master:suda/threads.py'], capture_output=True, text=True)
        if shown.returncode:        # a master from before the app moved into suda/
            shown = subprocess.run(['git', '-C', str(ROOT), 'show', 'master:threads.py'], capture_output=True, text=True, check=True)
        master.write_text(shown.stdout)
        # master's threads.py loads what lies beside it (store.py, sqlite177): the old CLI gets master's own copy
        store = subprocess.run(['git', '-C', str(ROOT), 'show', 'master:suda/store.py'], capture_output=True, text=True)
        if not store.returncode:
            (master.parent / 'store.py').write_text(store.stdout)
        steps = [('new', 'topic', 'כותרת'), ('task', 'add', 'topic', 'א', '--owner', 'fork'),
                 ('task', 'add', 'topic', 'ב'), ('task', 'set', 'topic', '1', 'building', '--note', 'רץ'),
                 ('task', 'set', 'topic', '1', 'done', '--owner', 'tower'), ('task', 'archive', 'topic', '1'),
                 ('task', 'set', 'topic', '1', 'todo'), ('state', 'topic', 'done', '--note', 'x', '--force'),
                 ('task', 'set', 'topic', '2', 'blocked', '--note', ' '), ('task', 'set', 'topic', '2', 'todo', '--owner', 'Human')]
        outs = []
        for cli in (str(master), str(test_threads.CLI)):
            boards = self.root / ('b-' + Path(cli).stem)
            # state.json is what is compared: both write it as their board (a master from before the SQLite store
            # knows no THREADS_STORE and writes it anyway)
            env = dict(self.env, BOARDS_DIR=str(boards), PYTHONPATH=str(ROOT), THREADS_STORE='file')
            for i, s in enumerate(steps):
                r = subprocess.run([sys.executable, cli, *s], env=dict(env, THREADS_NOW=str(self.T0 + i * 60)), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, (cli, s, r.stderr))
            outs.append(json.loads((boards / 'threads/state.json').read_text()))
        # the same but for the owner's id (version 3): master stores the id it had for him, this code 'owner'
        his = re.search(r"choices=\['tower', 'fork', '([^']+)'\]", master.read_text(encoding='utf-8'))
        if outs[0]['version'] < 3 and his:
            ids = {his[1]: 'owner', 'on-' + his[1]: 'on-owner'}
            rename = lambda v: {k: rename(x) for k, x in v.items()} if isinstance(v, dict) else [rename(x) for x in v] if isinstance(v, list) \
                else ids.get(v, v) if isinstance(v, str) else v
            outs[0] = {**rename(outs[0]), 'version': 3}
        # a task's events are new (suda-fixes task 34); everything else the old callers write stays as on master
        for k in outs[1]['threads']['topic']['tasks']:
            self.assertTrue(k.pop('events'), 'every task the old callers touched has its events')
        for k in outs[0]['threads']['topic']['tasks']:       # (master has the events too once task 34 is merged)
            k.pop('events', None)
        # the number of the last save is never below the clock (sse153): it differs between two runs by its nature
        for out in outs:
            out.pop('seq', None)
        # what he saved (bookmarks, suda-fixes 77) is a key the old callers never write: an empty one, missing on a
        # master from before it, is no difference
        if 'saved' not in outs[0] and outs[1].get('saved') == []:
            outs[1].pop('saved')
        self.assertEqual(outs[0], outs[1])


# the scenarios of ThreadsTests belong to that file; here the class only lends its board
for _name in dir(test_threads.ThreadsTests):
    if _name.startswith('test') and _name not in AdvTaskText.__dict__:
        setattr(AdvTaskText, _name, None)


if __name__ == '__main__':
    unittest.main()
