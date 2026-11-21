#!/usr/bin/env python3
"""End to end: the ▶ button of a command block says what became of his request (task 123, thread suda m430).

▶ הרץ → (he asks) ⏳ ממתין למגדל → (the tower picked it up: threads ack, or run-status running) ⏳ רץ →
(threads run-status … ok|fail) ✓ בוצע HH:MM / ✗ נכשל HH:MM, which he may press to run it again. The button changes
its words in place: nothing moves. Same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

TOWER_MSG = 'להריץ:\n```sh\n! echo hello\n```\n'
BTN = 'JSON.stringify((()=>{const b=document.querySelector("#log .code-bar button.run");if(!b)return null;const r=b.getBoundingClientRect(),bar=b.closest(".code-bar").getBoundingClientRect();return [b.textContent,b.disabled,b.dataset.runState||"",Math.round(r.height),Math.round(r.top-bar.top),Math.round(bar.height)]})())'


class Runs(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def btn(self):
        return self.browser.eval(BTN)

    def wait_state(self, state):
        return self.browser.wait('JSON.stringify((%s)?.[2]===%r)' % (BTN[len('JSON.stringify('):-1], state), timeout=15, what='the button to say ' + state)

    def test_the_run_button_follows_the_request_to_its_end(self):
        self.needs('run')
        tid = 'rn-one'
        self.ok('new', tid, 'הרצה', '--state', 'working', '--note', 'x')
        self.ok('say', tid, '--from', 'tower', TOWER_MSG, '--state', 'on-owner', '--note', 'להריץ?')
        self.open_thread(SIZES[0], tid, 'הרצה')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .code-bar button.run"))', what='the run button')
        first = self.btn()
        self.assertIn('הרץ', first[0])
        self.assertFalse(first[1])
        # he asks
        self.browser.click('#log .code-bar button.run')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the run dialog')
        self.browser.click('#run-ok')
        self.wait_state('waiting')
        self.assertIn('ממתין', self.btn()[0])
        req = self.until(lambda: next((m['id'] for m in self.thread(tid)['messages'] if m.get('run')), None), what='his request on the server')
        # the tower picked it up
        self.ok('ack', tid, req, '--as', 'tower')
        self.wait_state('running')
        self.assertIn('רץ', self.btn()[0])
        self.assertTrue(self.btn()[1], 'pressable while it runs')
        # done
        self.ok('run-status', tid, 'm1', '0', 'ok', '--note', 'hello')
        self.wait_state('ok')
        done = self.btn()
        self.assertIn('בוצע', done[0])
        self.assertRegex(done[0], r'\d\d:\d\d')
        self.assertFalse(done[1], 'not pressable again')
        self.assertEqual((done[3], done[4], done[5]), (first[3], first[4], first[5]), 'the button or its bar changed its height or moved in the bar')
        self.browser.run('screenshot', '/tmp/suda-run-ok.png')
        # failed, the next time
        self.ok('run-status', tid, 'm1', '0', 'fail', '--note', 'exit 1')
        self.wait_state('fail')
        self.assertIn('נכשל', self.btn()[0])
        # and he may run it again
        self.browser.click('#log .code-bar button.run')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the dialog again')
        self.browser.press('Escape')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Runs.__dict__:
        setattr(Runs, _name, None)


if __name__ == '__main__':
    unittest.main()
