"""Hostile review of several open questions in one thread (suda m508). Each test asserts the CORRECT outcome:
a FAIL is a real hole. Uses the CLI harness of test_threads (temp board, page ops through `ingest`)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import test_threads

ROOT = _paths.APP


class AdvQ(test_threads.ThreadsTests):
    def ids(self, t):
        return [q['id'] for q in t['questions']]

    def state(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def write_state(self, data):
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False))

    def test_same_words_from_another_agent_are_not_silently_taken_back(self):
        """Two agents ask the same short words ("להמשיך?") about different things. The second ask silently ends the
        first agent's question: its buttons die, his answer is filed under m2, and the first agent (waiting for
        re.q == m1) never learns. Either both stay open, or the ask says which question it took back."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', '--from', 'fork', env=e(1))          # m1
        r = self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', '--from', 'tower', env=e(2))      # m2
        t = self.thread(env=e(2))
        self.assertTrue(len(t['questions']) == 2 or 'm1' in r.stdout + r.stderr,
                        f'm1 (asked by fork) taken back silently by tower: open={self.ids(t)} out={r.stdout!r} err={r.stderr!r}')

    def test_a_refused_ask_leaves_an_archived_thread_closed(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        for i in range(1, 6):
            self.run_cli('ask', 'topic', f'שאלה {i}?', '--options', 'כן,לא', env=e(i))
        data = self.state()
        data['threads']['topic'].update(status='closed', closed_by='auto', closed_ts=self.T0 + 6 * 3600)
        self.write_state(data)
        self.run_cli('ask', 'topic', 'שאלה 6?', '--options', 'כן,לא', ok=False, env=e(7))
        t = self.thread(env=e(7))
        self.assertEqual((t['status'], len(t['messages']), self.ids(t)), ('closed', 5, ['m1', 'm2', 'm3', 'm4', 'm5']))

    def test_his_answer_to_an_older_question_is_not_pushed_back_to_him(self):
        """m1 m2 open; m3 arrives (pushed). His screen still shows m2 as the newest; he answers m1 by its button.
        His own answer must not make the thread news again (a second push for the same m3)."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', env=e(2))
        self.run_cli('ask', 'topic', 'ג?', '--options', 'כן,לא', env=e(3))                              # m3
        before = self.thread(env=e(3)).get('alert')
        self.assertTrue(before and before['pushed'])
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm1', 'under': 'm2'}, env=e(3.1))['ok'])
        t = self.thread(env=e(3.1))
        self.assertEqual(self.ids(t), ['m2', 'm3'])
        after = t.get('alert')
        self.assertTrue(after is None or after['pushed'] == before['pushed'],
                        f'pushed again for his own answer: before={before} after={after}')

    def test_an_old_page_reply_is_filed_under_the_question_it_closed(self):
        """A page from before `under` knew only `question` (the newest). Its typed reply closes the newest: the
        agent of that question must be able to tell from `threads pending` that this reply answered it."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', '--from', 'tower', env=e(2))           # m2
        self.ingest(text='תשובה מדף ישן', cid='c1', env=e(3))
        t = self.thread(env=e(3))
        # Decided (option c; see test_adv_b.test_typed_reply_is_not_filed_as_the_answer_to_a_question_it_never_saw):
        # which question such a reply answers cannot be known, so it closes none and names none, and it reaches the
        # agents in `pending`. Nothing is closed without a word to its agent.
        self.assertEqual(self.ids(t), ['m1', 'm2'])
        self.assertNotIn('re', t['messages'][-1])
        self.assertEqual(t['state'], 'on-owner')
        self.assertIn(t['messages'][-1]['id'], [r['msg_id'] for r in json.loads(self.run_cli('pending', env=e(3)).stdout)])

    def test_a_tap_naming_a_question_of_another_thread_is_refused(self):
        e = self.at
        self.run_cli('new', 'a', 'א', env=e(0))
        self.run_cli('new', 'b', 'ב', env=e(0))
        self.run_cli('say', 'b', '--from', 'fork', 'דיווח', env=e(0.5))                                  # b:m1 not a question
        self.run_cli('ask', 'a', 'שאלה?', '--options', 'כן,לא', env=e(1))                                # a:m1
        self.run_cli('ask', 'b', 'שאלה?', '--options', 'כן,לא', env=e(1))                                # b:m2
        self.assertFalse(self.post({'op': 'reply', 'thread': 'b', 'text': 'כן', 'cid': 'c1', 'q': 'm1'}, ok=False, env=e(2))['ok'])
        self.assertEqual(self.ids(self.thread('b', env=e(2))), ['m2'])
        self.assertEqual(self.ids(self.thread('a', env=e(2))), ['m1'])

    def test_rollback_old_cli_answering_the_newest_keeps_the_older_open(self):
        """Rollback: the old CLI (master) answers the newest (writes question=None, leaves `questions`). Back on
        the new code, the older question that nobody answered must still be open."""
        e = self.at
        old = Path(self.tmp.name) / 'threads_master.py'
        shown = subprocess.run(['git', 'show', 'master:suda/threads.py'], cwd=ROOT, capture_output=True, text=True)
        if shown.returncode:        # a master from before the app moved into suda/
            shown = subprocess.run(['git', 'show', 'master:threads.py'], cwd=ROOT, capture_output=True, text=True, check=True)
        old.write_text(shown.stdout)
        # master's threads.py loads what lies beside it (store.py, sqlite177): the old CLI gets master's own copy
        store = subprocess.run(['git', 'show', 'master:suda/store.py'], cwd=ROOT, capture_output=True, text=True)
        if not store.returncode:
            (old.parent / 'store.py').write_text(store.stdout)
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', env=e(2))
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm2'}))
        before = (self.board / 'state.json').read_bytes()
        r = subprocess.run([sys.executable, str(old), 'ingest'], env=e(3), capture_output=True, text=True)
        if 'VERSION = 2\n' in old.read_text(encoding='utf-8'):
            # master is still the version before the owner's id (v3): it refuses the newer file and leaves it alone
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertEqual((self.board / 'state.json').read_bytes(), before)
            self.assertEqual(self.ids(self.thread(env=e(4))), ['m1', 'm2'])
            return
        self.assertEqual(r.returncode, 0, r.stderr)
        t = self.thread(env=e(4))
        self.assertEqual(self.ids(t), ['m1'], 'the older question vanished after a rollback answered the newest')

    def test_two_open_with_the_same_options_digits_answer_the_newest_on_the_server_too(self):
        """Same option labels in both; the page's digit sends q=newest. The server closes exactly that one."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', env=e(2))
        self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm2', 'under': 'm2'}, env=e(3))
        t = self.thread(env=e(3))
        self.assertEqual((self.ids(t), t['messages'][-1]['re']['q'], t['state'], t['note']), (['m1'], 'm2', 'on-owner', 'א?'))

    def test_under_naming_a_plain_message_closes_nothing(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דיווח', env=e(0.5))                             # m1
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))                                # m2
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', env=e(2))                                # m3
        self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c1', 'under': 'm1'}, env=e(3))
        self.assertEqual(self.ids(self.thread(env=e(3))), ['m2', 'm3'])

    def test_replace_all_then_a_stale_tick_form_is_refused(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'מה?', '--multi', '--options', 'א,ב,ג', env=e(1))                    # m1
        self.run_cli('ask', 'topic', 'עכשיו?', '--options', 'כן,לא', '--replace-all', env=e(2))          # m2
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'q': 'm1', 'answer': {'': ['א']}}, ok=False, env=e(3))['ok'])
        self.assertEqual(self.ids(self.thread(env=e(3))), ['m2'])


# Only the scenarios of this file: the inherited ones run in test_threads.
for _name in dir(test_threads.ThreadsTests):
    if _name.startswith('test') and _name not in AdvQ.__dict__:
        setattr(AdvQ, _name, None)


if __name__ == '__main__':
    unittest.main()
