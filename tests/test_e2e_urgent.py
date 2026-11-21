#!/usr/bin/env python3
"""End to end: the order inside a section, and "urgent" (the owner, thread suda m501, approved in m505).

He chooses, on this device, how a section is ordered: by the place numbers (as always) or what moved last on top.
A thread marked urgent (by him on the page, or by an agent with `threads urgent <id>`) is first in its section,
with a red mark, until the mark is taken away or the thread is closed. The same harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import unittest

import test_e2e
from test_e2e import SIZES

MINE = '[...document.querySelectorAll("#channels .sec-working .ch")].map(b=>b.dataset.id).filter(i=>i.startsWith("e2e-u")).join()'
ORDER = 'JSON.stringify(' + MINE + ')'


class Urgent(test_e2e.Suda):
    def test_urgent_first_and_the_order_he_chose(self):
        for tid in ('e2e-u1', 'e2e-u2', 'e2e-u3'):
            if tid not in self.state()['threads']:
                self.ok('new', tid, 'נושא ' + tid[-1], '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(synced&&document.querySelectorAll("#channels .sec-working .ch").length>=3)', what='the list')
        self.assertEqual(self.browser.eval('JSON.stringify(listOrder())'), 'recent', 'the last message on top is the default (suda-fixes m8)')
        self.browser.eval('(()=>{setListOrder("slot");return "ok";})()')
        self.browser.wait('JSON.stringify((%s)==="e2e-u1,e2e-u2,e2e-u3")' % MINE, what='the place numbers')
        # an agent marks the last one urgent: it is first, with its mark
        self.ok('urgent', 'e2e-u3')
        self.browser.wait('JSON.stringify((%s).startsWith("e2e-u3"))' % MINE, what='the urgent one first')
        self.assertIn('דחוף', self.browser.eval('JSON.stringify(document.querySelector("#channels .ch[data-id=e2e-u3]").innerText)'))
        if os.environ.get('URGENT_SHOTS'):
            self.browser.run('screenshot', os.path.join(os.environ['URGENT_SHOTS'], 'urgent.png'))
        # what moved last on top: u2 says something now
        self.ok('say', 'e2e-u2', '--from', 'fork', 'עדכון', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.browser.eval('(()=>{setListOrder("recent");return "ok";})()')
        self.browser.wait('JSON.stringify((%s)==="e2e-u3,e2e-u2,e2e-u1")' % MINE, what='urgent, then what moved last')
        self.browser.eval('(()=>{setListOrder("slot");return "ok";})()')
        # his press takes the mark away
        self.browser.eval('(()=>{setUrgent("e2e-u3",false);return "ok";})()')
        self.until(lambda: 'urgent' not in self.thread('e2e-u3'), what='the mark taken away on the server')
        self.browser.wait('JSON.stringify((%s)==="e2e-u1,e2e-u2,e2e-u3")' % MINE, what='back to the numbers')
        # and his press puts it on
        self.browser.eval('(()=>{setUrgent("e2e-u2",true);return "ok";})()')
        self.until(lambda: self.thread('e2e-u2').get('urgent'), what='the mark on the server')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Urgent.__dict__:
        setattr(Urgent, _name, None)


if __name__ == '__main__':
    unittest.main()
