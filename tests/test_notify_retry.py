#!/usr/bin/env python3
"""His phone through `snap notify` is tried once more by itself (control, 2026-11-17: 3 of the last 5 phone
alerts in notify.log timed out at 20 s, and a manual try right after went through).

A failed phone command is written back as owed (as before) and NOT logged; the sweep's timer tries it again at
its next run, after reading the state anew, so a thing that is over by then (answered, muted, the phone switched
off, quiet hours) does not ring. That second try waits longer (38 s) where nobody waits for it (the sweep, the
detached half of a page action); a command an agent runs never waits longer than before. Only a failure of a
second try is logged. Nothing runs in a process of its own that could die with the alert in it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import shlex
import sys
import unittest

import test_adv_e

# A stand-in for `snap notify` that records each call and fails the first N of them (N from the env).
FLAKY = ("import json, os, sys\nfrom pathlib import Path\n"
         "n = Path(os.environ['FLAKY_COUNT'])\ncount = int(n.read_text()) + 1 if n.exists() else 1\nn.write_text(str(count))\n"
         "with open(os.environ['TOLD_RECORD'], 'a') as f:\n f.write(json.dumps(['snap'] + sys.argv[1:]) + '\\n')\n"
         "sys.exit(1 if count <= int(os.environ.get('FLAKY_FAILS', '0')) else 0)\n")


class Retry(test_adv_e.Told):
    def flaky(self, fails):
        script = self.root / 'flaky.py'
        script.write_text(FLAKY)
        return dict(THREADS_SNAP_CMD=shlex.join([sys.executable, str(script)]), FLAKY_COUNT=str(self.root / 'flaky.count'), FLAKY_FAILS=str(fails))

    def log(self):
        path = self.board / 'notify.log'
        return [line for line in path.read_text().splitlines() if ' phone' in line] if path.exists() else []

    def alert(self, minute):
        return self.thread('topic', env=self.at(minute)).get('alert') or {}

    def ring(self, fails):
        """A question on him that the sweep hands to his phone, through a stand-in that fails `fails` times."""
        self.working()
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', env=self.at(1))
        flaky = self.flaky(fails)
        self.run_cli('sweep', '--quiet', env=self.at(17, **flaky))
        return flaky

    def test_a_phone_command_that_fails_once_is_tried_again_at_the_next_sweep_and_nothing_is_logged(self):
        flaky = self.ring(1)
        self.assertEqual(len(self.snaps()), 1)
        self.assertEqual(self.log(), [], 'a first failure was logged')
        self.run_cli('sweep', '--quiet', env=self.at(18, **flaky))         # the timer's next run, a minute later
        self.assertEqual(len(self.snaps()), 2, 'the failed phone command was not tried again at the next sweep')
        self.assertEqual(self.snaps()[0], self.snaps()[1], 'the second try is not the same alert')
        self.assertEqual(self.log(), [], 'a failure that the second try made good was logged')
        for minute in (19, 40):
            self.run_cli('sweep', '--quiet', env=self.at(minute, **flaky))
        self.assertEqual(len(self.snaps()), 2, 'rang again after it went through')

    def test_a_second_failure_is_logged_once(self):
        flaky = self.ring(2)
        self.run_cli('sweep', '--quiet', env=self.at(18, **flaky))
        self.assertEqual(len(self.snaps()), 2)
        self.assertEqual(len(self.log()), 1, self.log())
        self.assertEqual(self.alert(18).get('failed'), 2)

    def test_the_second_try_does_not_ring_when_he_answered_in_between(self):
        flaky = self.ring(1)
        # his answer, as the page sends it (naming the question on his screen: suda m508)
        self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'כן', 'under': 'm1'}, env=self.at(17.5))
        self.run_cli('sweep', '--quiet', env=self.at(18, **flaky))
        self.assertEqual(len(self.snaps()), 1, 'his phone rang for a question he had answered')

    def test_only_the_sweep_and_a_detached_tell_wait_long_for_a_second_try(self):
        r = self.inside('''
            import subprocess, json
            seen = []
            def fake(cmd, **kw):
                seen.append(kw.get('timeout'))
                raise subprocess.TimeoutExpired(cmd, kw.get('timeout'))
            threads.subprocess.run = fake
            row = {'id': 'topic', 'title': 't', 'note': 'n', 'url': ''}
            out = [threads.phone(row), threads.phone(dict(row, again=True))]
            threads.patient = True
            out += [threads.phone(row), threads.phone(dict(row, again=True)), threads.phone(dict(row, again='yes'))]
            print(json.dumps([out, seen]))
        ''', env=self.at(0, THREADS_SNAP_CMD='true'))
        self.assertEqual(r.returncode, 0, r.stderr)
        out, seen = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out, [False] * 5)
        self.assertEqual(seen, [20, 20, 20, 38, 20], 'a command an agent runs waits longer than before, or the sweep does not wait longer')


# The scenarios of test_adv_e.Told belong to that file; here the class only lends its board and helpers.
for _name in dir(test_adv_e.Told):
    if _name.startswith('test') and _name not in Retry.__dict__:
        setattr(Retry, _name, None)


if __name__ == '__main__':
    unittest.main()
