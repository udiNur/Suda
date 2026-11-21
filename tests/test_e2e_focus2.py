#!/usr/bin/env python3
"""End to end: after a pick in ⌘K the keys are in the reply box (the owner, thread suda m532: "when I am in the box
and do Command K and pick something, it does not jump into the message; I have to click with the mouse to get
there"). The same harness as test_e2e.py. At the desktop size, from the reply box: ⌘K and a thread picked by Enter,
by a click, and a command (one that opens no window of its own): the keys are in the reply box of the thread on
the screen.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e_gallery import Cdp
from test_e2e import SIZES

IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'


class FocusAfterPick(test_e2e.Suda):
    def threads_(self):
        for tid, title in (('e2e-fa', 'נושא ראשון לפוקוס'), ('e2e-fb', 'נושא שני לפוקוס')):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', 'working', '--note', 'בונה', '--by', 'e2e')

    def pick(self, words, by_click=False):
        self.browser.wait(IN_BOX, what='the box with the keys first')
        self.browser.press('Meta+KeyK')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        self.browser.fill('#sw-query', words)
        time.sleep(0.4)
        if by_click:
            self.browser.eval('(()=>{document.querySelector("#sw-results .sw-row.active").click();return "ok";})()')
        else:
            self.browser.press('Enter')
        self.browser.wait('JSON.stringify(document.querySelector("#switcher").hidden)', what='the palette closed')

    def test_a_pick_in_the_palette_leaves_the_keys_in_the_reply_box(self):
        self.threads_()
        self.open_thread(SIZES[2], 'e2e-fa', 'נושא ראשון לפוקוס')
        self.pick('נושא שני לפוקוס')
        self.browser.wait('JSON.stringify(view.ch==="e2e-fb")', what='the thread picked')
        self.browser.wait(IN_BOX, what='the box after a thread picked by Enter')
        self.pick('נושא ראשון לפוקוס', by_click=True)
        self.browser.wait('JSON.stringify(view.ch==="e2e-fa")', what='the thread picked by a click')
        self.browser.wait(IN_BOX, what='the box after a thread picked by a click')
        self.pick('מראה כהה')
        self.browser.wait(IN_BOX, what='the box after a command')
        self.pick('נושא ראשון לפוקוס')            # the thread already on the screen
        self.browser.wait(IN_BOX, what='the box after picking the thread on the screen')

    def test_on_a_touch_screen_the_box_takes_the_keys_only_once_a_real_keyboard_is_used(self):
        """A phone used by finger: opening a thread raises no keyboard (nothing takes the keys). A phone with its
        physical keyboard (m532: he presses ⌘K on the phone): once a real key was pressed, a pick in the palette
        and a thread opened leave the keys in the reply box."""
        self.threads_()
        self.open_thread(SIZES[0], 'e2e-fa', 'נושא ראשון לפוקוס')       # (a page of Suda for the browser's own controls to find)
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
        self.addCleanup(lambda: cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': False}))
        self.open_thread(SIZES[0], 'e2e-fa', 'נושא ראשון לפוקוס')
        self.assertTrue(self.browser.eval('JSON.stringify(matchMedia("(pointer:coarse)").matches)'), 'no touch screen to test on')
        self.browser.eval('(()=>{document.documentElement.classList.remove("keyed");document.activeElement.blur();openChannel("e2e-fb");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-fb")', what='a thread opened by finger')
        time.sleep(0.5)
        self.assertFalse(self.browser.eval(IN_BOX), 'by finger alone the box took the keys (the phone keyboard would cover the conversation)')
        # his physical keyboard: a real key, then ⌘K and a pick
        self.browser.press('Shift')
        self.browser.press('Meta+KeyK')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        self.browser.fill('#sw-query', 'נושא ראשון לפוקוס')
        time.sleep(0.4)
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(view.ch==="e2e-fa")', what='the thread picked on the phone')
        self.browser.wait(IN_BOX, what='the box after a pick on a phone with its keyboard')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in FocusAfterPick.__dict__:
        setattr(FocusAfterPick, _name, None)


if __name__ == '__main__':
    unittest.main()
