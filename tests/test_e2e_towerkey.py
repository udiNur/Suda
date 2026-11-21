#!/usr/bin/env python3
"""End to end: Shift+T opens the tower from anywhere (the owner, tower m333: "a shortcut to reach the tower in Suda,
something with T"). T alone stays the list of tasks. From another space too, and he stays in his space. The same
harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_e2e
from test_e2e import SIZES


class TowerKey(test_e2e.Suda):
    def test_shift_t_opens_the_tower(self):
        if 'tower' not in self.state()['threads']:
            self.ok('new', 'tower', 'מגדל: תפעול', '--state', 'working', '--note', 'שקט', '--by', 'e2e')
        if 'e2e-tk' not in self.state()['threads']:
            self.ok('new', 'e2e-tk', 'נושא רגיל', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-tk', 'נושא רגיל')
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.browser.press('Shift+KeyT')
        self.browser.wait('JSON.stringify(view.ch==="tower")', what='the tower open')
        # from the palette too
        self.browser.eval('(()=>{openChannel("e2e-tk");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-tk")', what='back in the thread')
        self.browser.eval('(()=>{openSwitcher();return "ok";})()')
        self.browser.fill('#sw-query', 'מגדל')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row")].some(r=>r.innerText.includes(KEYS.shift+" T")))', what='the tower with its key in the palette')
        # in the help
        self.browser.eval('(()=>{closeSwitcher();showHelp();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#help").innerText.includes("המגדל"))', what='the key in the help')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in TowerKey.__dict__:
        setattr(TowerKey, _name, None)


if __name__ == '__main__':
    unittest.main()
