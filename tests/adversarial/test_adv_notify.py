#!/usr/bin/env python3
"""
(worker-3: the tests of the first design, a retry in a detached process, were dropped with that design:
the second try is now the sweep's own, after it reads the state anew. The ones kept hold for both.)
Hostile review of the phone's second try (tell() hands a failed `snap notify` to a detached
`threads tell {..., "again": true}`). Every test asserts the CORRECT outcome: a FAILING test is a real hole;
a test named `test_held_...` is an attack the change withstood.

Temp boards inside the checkout, stand-ins for every outside service (test_adv_e.Box); no network.
    python3 -m unittest test_adv_notify -v
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import shlex
import sys
import time
import unittest

import test_adv_e
from test_notify_retry import FLAKY

# Fails its first call; its second call (the detached retry) kills the process that ran it, as a reboot,
# a logout or an OOM kill would; later calls succeed.
DIES = ("import json, os, signal, sys\nfrom pathlib import Path\n"
        "n = Path(os.environ['FLAKY_COUNT'])\ncount = int(n.read_text()) + 1 if n.exists() else 1\nn.write_text(str(count))\n"
        "with open(os.environ['TOLD_RECORD'], 'a') as f:\n f.write(json.dumps(['snap'] + sys.argv[1:]) + '\\n')\n"
        "if count == 2:\n os.kill(os.getppid(), signal.SIGKILL)\n"
        "sys.exit(1 if count <= 2 else 0)\n")


class Notify(test_adv_e.Told):
    def stand_in(self, body, fails=1):
        script = self.root / 'standin.py'
        script.write_text(body)
        return dict(THREADS_SNAP_CMD=shlex.join([sys.executable, str(script)]), FLAKY_COUNT=str(self.root / 'flaky.count'),
                    FLAKY_FAILS=str(fails))

    def log(self):
        path = self.board / 'notify.log'
        return path.read_text() if path.exists() else ''

    def first_try_fails(self):
        """A question on him; the sweep rings his phone at minute 17 and the first try fails at once."""
        self.working()
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', env=self.at(1))
        env = self.stand_in(FLAKY, fails=1)
        self.run_cli('sweep', '--quiet', env=self.at(17, **env))
        return env

    # ── the retry rings for something that is no longer on him ─────────────

    def _no_ring_after(self, *command, minute=17):
        env = self.first_try_fails()
        self.run_cli(*command, env=self.at(minute, **env))       # within the 2 s PHONE_PAUSE
        time.sleep(4.0)
        self.assertEqual(len(self.snaps()), 1, f'{command}: the detached retry rang his phone anyway')

    def test_retry_does_not_ring_after_he_answered(self):
        self._no_ring_after('say', 'topic', '--from', 'owner', 'כן')

    def test_retry_does_not_ring_for_a_muted_thread(self):
        self._no_ring_after('mute', 'topic')

    def test_retry_does_not_ring_once_the_phone_is_switched_off(self):
        self._no_ring_after('notify', '--snap', 'off')

    def test_retry_does_not_ring_in_quiet_hours_set_in_between(self):
        # T0 is 08:00 UTC; minute 17 is 08:17
        self._no_ring_after('notify', '--quiet', '08:00-09:00')

    # ── an alert lost when the detached retry never finishes ───────────────

    def test_held_a_sweep_during_the_retry_window_does_not_ring_again(self):
        self.working()
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', env=self.at(1))
        env = self.stand_in(FLAKY, fails=1)
        self.run_cli('sweep', '--quiet', env=self.at(17, **env))
        self.run_cli('sweep', '--quiet', env=self.at(17.5, **env))
        self.run_cli('sweep', '--quiet', env=self.at(19, **env))
        self.wait_for(lambda: len(self.snaps()) == 2, 'retry never came', seconds=10)
        time.sleep(1.0)
        self.assertEqual(len(self.snaps()), 2)

for _name in dir(test_adv_e.Told):
    if _name.startswith('test') and _name not in Notify.__dict__:
        setattr(Notify, _name, None)


if __name__ == '__main__':
    unittest.main()
