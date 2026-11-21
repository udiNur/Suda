#!/usr/bin/env python3
"""End to end: he saves a message and finds it again (suda-fixes 77; the owner, suda m787: "a feature to let me save
messages, e.g. this message I would like to keep").

- In a message's bar (a tap on it, on the phone) ☆ saves it; ★ by its time says it is saved; the menu has it too.
- "שמורות" (the list's foot, and Cmd+K) lists every saved message of every thread, the last saved first; a row opens
  the thread at that message; × takes it out.
- A saved message deep in a long thread, which the page holds only as a stamp, is listed with the start of its words.
The same harness as test_e2e.py."""
import json
import unittest

import _paths  # noqa: F401  (the test folders on sys.path)
import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES


class Saved(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ok('new', 'sv-a', 'חומרים להשקה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('say', 'sv-a', '--from', 'tower', 'כל החומרים שהכנו, במקום אחד: הדף, הלוח והקבצים')
        for i in range(30):
            cls.ok('say', 'sv-a', '--from', 'fork', 'עדכון %d' % i)
        cls.ok('new', 'sv-b', 'נושא אחר', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('say', 'sv-b', '--from', 'fork', 'הודעה בנושא אחר')

    def test_a_message_is_saved_from_its_bar_and_found_in_the_list_of_saved(self):
        for size in (DESK, COVER):
            with self.subTest(size=size[0]):
                self.ok('say', 'sv-b', '--from', 'fork', 'הודעה לשמור %s' % size[0])
                self.open_thread(size, 'sv-b', 'נושא אחר')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=2)', what='the messages')
                mid = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].at(-1).dataset.mid)')
                self.browser.eval('(()=>{const b=[...document.querySelectorAll("#log .msg")].at(-1).querySelector(\'.msg-acts button[aria-label^="שמור"]\');b.click();return 1})()')
                self.until(lambda: self.thread('sv-b')['messages'][int(mid[1:]) - 1].get('saved'), what='saved on the server')
                self.browser.wait('JSON.stringify(!!document.querySelector(\'#log .msg[data-mid="%s"] .saved-mark\'))' % mid, what='the star by its time')
                self.browser.eval('(()=>{openSaved();return 1})()')
                self.browser.wait('JSON.stringify(!!document.querySelector("#reader:not([hidden]) .saved-row"))', what='the list of saved')
                first = self.browser.eval('JSON.stringify(document.querySelector(".saved-row .saved-text").textContent)')
                self.assertIn('הודעה לשמור %s' % size[0], first, 'the last saved first')
                # a row opens its thread at the message
                self.browser.click('.saved-row .saved-go')
                self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden&&view.ch==="sv-b")', what='the thread')

    def test_a_saved_message_deep_in_a_long_thread_is_listed_and_opened(self):
        self.post({'op': 'save', 'thread': 'sv-a', 'msg': 'm1', 'on': True})
        self.open_thread(DESK, 'sv-b', 'נושא אחר')
        self.browser.eval('(()=>{openSaved();return 1})()')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".saved-row .saved-text")].some(t=>t.textContent.includes("כל החומרים שהכנו")))',
                          what='the old message, from its stamp')
        row = self.browser.eval('JSON.stringify([...document.querySelectorAll(".saved-row")].findIndex(r=>r.textContent.includes("כל החומרים שהכנו")))')
        self.browser.eval('(()=>{document.querySelectorAll(".saved-row .saved-go")[%d].click();return 1})()' % row)
        self.browser.wait('JSON.stringify(view.ch==="sv-a"&&!!document.querySelector(\'#log .msg[data-mid="m1"]\'))', timeout=20, what='the thread at the message')
        # × takes it out
        self.browser.eval('(()=>{openSaved();return 1})()')
        self.browser.wait('JSON.stringify(!!document.querySelector(".saved-row"))', what='the list')
        before = self.browser.eval('JSON.stringify(document.querySelectorAll(".saved-row").length)')
        self.browser.eval('(()=>{const r=[...document.querySelectorAll(".saved-row")].find(r=>r.textContent.includes("כל החומרים שהכנו"));r.querySelector(".saved-off").click();return 1})()')
        self.until(lambda: not self.thread('sv-a')['messages'][0].get('saved'), what='taken out on the server')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll(".saved-row").length)'), before - 1)


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(Saved(name) for name in sorted(vars(Saved)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
