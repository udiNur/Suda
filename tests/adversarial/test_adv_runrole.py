"""Hostile review of "only the tower sees a run request in threads pending" (2026-11-20).

Each test asserts the SAFE outcome: a failure is a hole. Run: python3 -m unittest test_adv_runrole
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import json
import unittest

from test_threads import CLI as test_threads_cli
from test_threads import ThreadsTests as _T     # (not bound at module level as a TestCase: the loader would run it)

_T = {k: getattr(_T, k) for k in ('setUp', 'run_cli', 'at', 'post', 'T0')}


class Base(unittest.TestCase):
    setUp = _T['setUp']
    run_cli = _T['run_cli']
    at = _T['at']
    post = _T['post']
    T0 = _T['T0']

    def ask(self):
        """A tower block, his tap on it (m2), then a plain reply (m3)."""
        e = self.at
        self.run_cli('new', 'topic', 'title', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', 'here:\n```\n! echo hi\n```', env=e(0))
        run = {'msg_id': 'm1', 'block_index': 0, 'sha256': hashlib.sha256(b'! echo hi').hexdigest()}
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'under': None, 'cid': 'r1', 'run': run}, env=e(1))['ok'])
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'and more', 'under': None, 'cid': 'r2'}, env=e(2))['ok'])
        return run

    def agent(self, *args, ok=True):
        env = dict(self.at(3))
        env.pop('THREADS_ROLE', None)
        if ok is None:      # whatever it answers
            import subprocess, sys
            return subprocess.run([sys.executable, str(test_threads_cli), *args], env=env, capture_output=True, text=True)
        return self.run_cli(*args, env=env, ok=ok)

    def tower_rows(self):
        return json.loads(self.run_cli('pending', '--as', 'tower', env=self.at(3)).stdout)


class Holes(Base):
    def test_mail_of_a_run_request_tells_the_tower_to_ask_as_the_tower(self):
        """notify() mails "run: threads pending" for every reply, the ▶ request too. The tower that does what the
        mail says (and its watch.md, cron backup and watchdog all run plain `threads pending`) gets nothing."""
        self.ask()
        mails = [json.loads(line)['args'][-1] for line in self.record.read_text().splitlines()]
        run_mail = next(m for m in mails if '(m2)' in m)
        self.assertIn('--as tower', run_mail, run_mail)

    def test_history_of_another_row_does_not_carry_a_pending_run_request(self):
        """The plain reply m3 is shown to every agent, with `history` = every earlier message: his pending ▶ request
        (m2, "▶ run the command from message m1") and the tower's block m1 with the command itself."""
        self.ask()
        rows = json.loads(self.agent('pending').stdout)
        self.assertEqual([r['msg_id'] for r in rows], ['m3'])
        self.assertNotIn('m2', [h['id'] for h in rows[0]['history']], rows[0]['history'])

    def test_show_json_does_not_hand_a_pending_run_request_to_an_agent(self):
        self.ask()
        t = json.loads(self.agent('show', 'topic', '--json').stdout)
        live = [m['id'] for m in t['messages'] if m.get('status') == 'pending' and 'run' in m]
        self.assertEqual(live, [], 'show --json gives any agent the pending run request')

    def test_show_does_not_print_a_pending_run_request_to_an_agent(self):
        self.ask()
        text = self.agent('show', 'topic').stdout
        self.assertNotIn('בקשת הרצה', text)

    def test_list_json_does_not_hand_a_pending_run_request_to_an_agent(self):
        self.ask()
        rows = json.loads(self.agent('list', '--json').stdout)
        live = [m['id'] for t in rows for m in t['messages'] if m.get('status') == 'pending' and 'run' in m]
        self.assertEqual(live, [], 'list --json gives any agent the pending run request')

    def test_a_run_that_is_not_a_dict_stays_out_of_an_agents_pending(self):
        """Malformed state: `run` stored as a string (or a list). The filter is isinstance(run, dict), so the row goes
        to every agent, with its `command: {name: run}` beside it."""
        self.ask()
        path = self.root / 'boards/threads/state.json'
        state = json.loads(path.read_text())
        m2 = state['threads']['topic']['messages'][1]
        m2['run'] = '! echo hi'
        m2['command'] = {'name': 'run', 'args': ''}
        path.write_text(json.dumps(state))
        rows = json.loads(self.agent('pending').stdout)
        self.assertEqual([r['msg_id'] for r in rows], ['m3'], rows)

    def test_an_agent_cannot_ack_away_the_towers_run_request(self):
        """An agent that never sees m2 in `pending` still finds it in `show` and may `threads ack topic m2` (or react
        ✅ on it): the request leaves the tower's pending and is never run, with no trace of who took it."""
        self.ask()
        self.agent('ack', 'topic', 'm2', ok=None)
        self.assertIn('m2', [r['msg_id'] for r in self.tower_rows()])


class Held(Base):
    def test_role_resolution(self):
        """Case and spaces of THREADS_ROLE; an explicit --as wins over the environment, both ways."""
        self.ask()
        ids = lambda *args, role=None: [r['msg_id'] for r in json.loads(self.run_cli(
            'pending', *args, env=dict(self.at(3), **({'THREADS_ROLE': role} if role is not None else {}))).stdout)]
        for role in ('TOWER', ' tower\n', 'Tower'):
            self.assertEqual(ids(role=role), ['m2', 'm3'], role)
        for role in ('', 'towerx', 'tower,fork', 'fork'):
            self.assertEqual(ids(role=role), ['m3'], role)
        self.assertEqual(ids('--as', 'agent', role='tower'), ['m3'])
        self.assertEqual(ids('--as', 'tower', role='fork'), ['m2', 'm3'])
        self.run_cli('pending', '--as', 'Tower', ok=False, env=self.at(3))

    def test_tower_flow_still_works(self):
        """asked-already, ack, run-status: none of them reads pending."""
        run = self.ask()
        self.assertEqual(self.tower_rows()[0]['run']['command'], '! echo hi')
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'under': None, 'cid': 'r3', 'run': run}, ok=False, env=self.at(3))['ok'])
        self.run_cli('ack', 'topic', 'm2', env=dict(self.at(4), THREADS_ROLE='tower'))     # the tower acks as the tower
        self.run_cli('run-status', 'topic', 'm1', '0', 'ok', env=self.at(5))


if __name__ == '__main__':
    unittest.main()
