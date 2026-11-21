#!/usr/bin/env python3
"""End to end: what became of each of his messages (task 118, thread suda m404).

Under every message of his, one small line that is always there and only changes: ✓ "התקבל" while it waits for an
agent, ✓✓ "נקלט" once an agent picked it up, ✅ "בוצע" when an agent marked it done (threads react … ✅) or every
task opened from it is done. The line never comes and goes, so the conversation never jumps; an agent's ✅ is not
shown a second time among the quick marks. Same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

ACK_OF = '(()=>{const r=[...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid===%r);const a=r&&r.querySelector(".ack");return a?[a.dataset.ack,a.textContent]:null})()'
ACK = 'JSON.stringify(' + ACK_OF + ')'
HEIGHT = 'JSON.stringify((()=>{const r=[...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid===%r);return r?Math.round(r.getBoundingClientRect().height):0})())'


class Acks(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def ack(self, mid):
        return self.browser.eval(ACK % mid)

    def wait_ack(self, mid, kind):
        return self.browser.wait('JSON.stringify((%s)?.[0]===%r)' % (ACK_OF % mid, kind), timeout=15, what=mid + ' to show ' + kind)

    def test_each_message_of_his_says_what_became_of_it_and_nothing_jumps(self):
        tid = 'ak-one'
        self.ok('new', tid, 'מה קרה להודעה', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('say', tid, '--from', 'owner', 'תעשה את זה')                     # m1
        self.ok('say', tid, '--from', 'owner', 'וגם את זה')                       # m2
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, tid, 'מה קרה להודעה')
                self.wait_ack('m1', 'received')
                self.assertIn('התקבל', self.ack('m1')[1])
        tall = self.browser.eval(HEIGHT % 'm1')
        # picked up: every one of them says so, not only the last
        self.ok('ack', tid, 'm1')
        self.ok('ack', tid, 'm2')
        self.wait_ack('m1', 'taken')
        self.wait_ack('m2', 'taken')
        self.assertIn('נקלט', self.ack('m1')[1])
        self.assertEqual(self.browser.eval(HEIGHT % 'm1'), tall, 'the message moved when it was picked up')
        # done by the agent's mark
        self.ok('react', tid, 'm1', '✅', '--by', 'e2e-agent')
        self.wait_ack('m1', 'done')
        self.assertIn('בוצע', self.ack('m1')[1])
        self.assertEqual(self.browser.eval(HEIGHT % 'm1'), tall, 'the message moved when it was done')
        chips = self.browser.eval('JSON.stringify([...([...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid==="m1").querySelectorAll(".reacts .react"))].map(b=>b.textContent))')
        self.assertNotIn('✅', chips, "the agent's ✅ is shown twice")
        # done because every task opened from it is done
        self.ok('task', 'add', tid, 'הדבר השני', '--from-msg', 'm2')
        self.ok('task', 'add', tid, 'ועוד חלק', '--from-msg', 'm2')
        self.ok('task', 'set', tid, '1', 'done')
        time.sleep(1.5)
        self.assertEqual(self.ack('m2')[0], 'taken', 'done while one of its tasks is still open')
        self.ok('task', 'set', tid, '2', 'done')
        self.wait_ack('m2', 'done')
        self.browser.run('screenshot', '/tmp/suda-acks.png')

    def test_his_own_check_mark_on_his_message_is_his_quick_mark(self):
        """His own ✅ (a quick mark from the message's bar) is still his chip, as before; only an agent's ✅ is the
        'done' of the line."""
        tid = 'ak-two'
        self.ok('new', tid, 'הסימן שלו', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('say', tid, '--from', 'owner', 'משהו')
        self.post({'op': 'react', 'thread': tid, 'msg': 'm1', 'emoji': '✅', 'on': True})
        self.open_thread(SIZES[2], tid, 'הסימן שלו')
        self.wait_ack('m1', 'received')
        chips = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg .reacts .react.mine")].map(b=>b.textContent))')
        self.assertIn('✅', chips)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Acks.__dict__:
        setattr(Acks, _name, None)


if __name__ == '__main__':
    unittest.main()
