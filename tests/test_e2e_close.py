#!/usr/bin/env python3
"""End to end: closing a thread from the page closes it on the server. Two functions of the page had one name
(closeTopic: the thread's close, and the new-topic dialog's close); the later one won, so the C key, the "close
topic" button of the details and the palette's close only closed a dialog that was not open (found by the review of
the slash commands). The same harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES


class CloseThread(test_e2e.Suda):
    def fresh(self, tid):
        self.ok('new', tid, 'נושא לסגירה ' + tid[-1], '--state', 'working', '--note', 'בודק', '--by', 'e2e')

    def test_the_c_key_and_the_details_button_close_the_thread(self):
        self.fresh('e2e-c1')
        self.open_thread(SIZES[2], 'e2e-c1', 'נושא לסגירה 1')
        self.browser.eval('(()=>{document.activeElement.blur();return "ok"})()')
        self.browser.press('KeyC')
        self.until(lambda: self.thread('e2e-c1')['status'] == 'closed', what='the thread closed by the C key')
        self.fresh('e2e-c2')
        self.open_thread(SIZES[2], 'e2e-c2', 'נושא לסגירה 2')
        self.browser.eval('(()=>{openDetails();return "ok"})()')
        time.sleep(0.5)
        self.browser.eval('(()=>{const b=[...document.querySelectorAll("#details button")].find(x=>x.textContent.trim()==="סגור נושא");if(!b)throw Error("no close button");b.click();return "ok"})()')
        self.until(lambda: self.thread('e2e-c2')['status'] == 'closed', what='the thread closed by the details button')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in CloseThread.__dict__:
        setattr(CloseThread, _name, None)


if __name__ == '__main__':
    unittest.main()
