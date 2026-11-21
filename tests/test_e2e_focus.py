#!/usr/bin/env python3
"""End to end: the reply box has the keys by default, and one key brings them back (the owner, thread suda m500).

"Sometimes when I move into the pane I am not in the text box below. I would rather it were, by default; and if I
left it, how do I get back with one press?" Opening a thread on the desktop already put the keys in the box, and R
already went back to it; coming back to the window did not, and nothing said R. The same harness as test_e2e.py.
On a touch screen nothing takes the keys by itself: the keyboard would cover the conversation at every thread.
What is checked (desktop):

  - a thread opened: the box has the keys;
  - the keys lost to nowhere (a click on empty space, another window), then back to the window: the box has them;
  - text he selected in the conversation is not taken from him; a field elsewhere keeps the keys;
  - while the box does not have the keys, its hint line says R; R brings them back.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-focus'
TITLE = 'פוקוס בתיבה'
IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'


class Focus(test_e2e.Suda):
    def test_the_box_has_the_keys_and_gets_them_back(self):
        if TID not in self.state()['threads']:
            self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            self.ok('say', TID, '--from', 'fork', 'שורה ראשונה של שיחה שאפשר לסמן בה טקסט', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], TID, TITLE)
        self.browser.wait(IN_BOX, what='the box with the keys on opening')
        # lost to nowhere, then back to the window
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.assertFalse(self.browser.eval(IN_BOX))
        hint = self.browser.eval('JSON.stringify(getComputedStyle(document.querySelector("#hint .hint-r")).display!=="none"&&document.querySelector("#hint .hint-r").textContent)')
        self.assertTrue(hint and 'R' in hint, hint)
        self.browser.eval('(()=>{window.dispatchEvent(new Event("focus"));return "ok";})()')
        self.browser.wait(IN_BOX, what='the box with the keys after coming back to the window')
        self.assertEqual(self.browser.eval('JSON.stringify(getComputedStyle(document.querySelector("#hint .hint-r")).display)'), 'none')
        # text he selected is his: coming back does not take it away
        self.browser.eval('(()=>{document.activeElement.blur();const p=document.querySelector("#log .msg .md p");const r=document.createRange();r.selectNodeContents(p);getSelection().removeAllRanges();getSelection().addRange(r);window.dispatchEvent(new Event("focus"));return "ok";})()')
        time.sleep(0.4)
        self.assertFalse(self.browser.eval(IN_BOX), 'his selection was taken away')
        self.browser.eval('(()=>{getSelection().removeAllRanges();return "ok";})()')
        # a field elsewhere keeps the keys
        self.browser.eval('(()=>{openFind();return "ok";})()')
        self.browser.wait('JSON.stringify(document.activeElement&&document.activeElement.id==="find-q")', what='the find field')
        self.browser.eval('(()=>{window.dispatchEvent(new Event("focus"));return "ok";})()')
        time.sleep(0.4)
        self.assertEqual(self.browser.eval('JSON.stringify(document.activeElement.id)'), 'find-q')
        self.browser.press('Escape')
        # R from nowhere
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.browser.press('KeyR')
        self.browser.wait(IN_BOX, what='R back to the box')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Focus.__dict__:
        setattr(Focus, _name, None)


if __name__ == '__main__':
    unittest.main()
