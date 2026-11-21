#!/usr/bin/env python3
"""End to end: a press on a PR chip has it looked at again a little later (the owner, thread suda m478).

"Only when needed: in the chat itself, update; out and back, update in the background; a press on the chip,
update a minute or two later, because sometimes I merge there." The server asks GitHub; the page only asks the
server (op link-meta). The same harness as test_e2e.py. What is checked: a press on a PR chip asks for that pull
request alone, after a while and once more later (the delays are shortened here); coming back to the page asks
for the open thread.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-prchip'
TITLE = 'צ\'יפ של PR'
PR = 'https://github.com/acme/orbit/pull/1640'


class PrChip(test_e2e.Suda):
    def test_a_press_on_a_pr_chip_asks_for_it_again_later(self):
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', 'נפתח ' + PR, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.needs('link-meta')
        self.open_thread(SIZES[0], TID, TITLE)
        self.browser.wait('JSON.stringify(synced&&!!document.querySelector("#log a.chip-link[data-kind=pr]"))', what='the chip')
        # the page's own posts are recorded; the delays are a second and two
        self.browser.eval('(()=>{window.__asked=[];const real=post;post=(s,...r)=>{if(s.op==="link-meta")window.__asked.push(s);return real(s,...r);};'
                          'CHIP_AGAIN=[1,2];linksAsked.clear();return "ok";})()')
        self.browser.eval('(()=>{const a=document.querySelector("#log a.chip-link[data-kind=pr]");a.addEventListener("click",e=>e.preventDefault(),{once:true});a.click();return "ok";})()')
        time.sleep(3.2)
        asked = self.browser.eval('JSON.stringify(window.__asked)')
        own = [a for a in asked if a.get('url') == PR]
        self.assertEqual(len(own), 2, asked)
        self.assertTrue(all(a['thread'] == TID for a in own), asked)
        # out and back: the open thread is asked about
        self.browser.eval('(()=>{window.__asked=[];linksAsked.clear();document.dispatchEvent(new Event("visibilitychange"));return "ok";})()')
        self.browser.wait('JSON.stringify(window.__asked.some(a=>a.thread===%s&&!a.url))' % json.dumps(TID), what='the thread asked about on coming back')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in PrChip.__dict__:
        setattr(PrChip, _name, None)


if __name__ == '__main__':
    unittest.main()
