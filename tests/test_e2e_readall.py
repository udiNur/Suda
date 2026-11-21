#!/usr/bin/env python3
"""End to end: "mark all as read" on a section of the list (the owner, thread suda m490).

"I want, on a category, 'mark all as read' the moment I am on hover." The list has sections (on him, at work,
done); each says how many of its threads have something new. The same harness as test_e2e.py. What is checked:

  - on the wide screen the section's button appears on hover only, and only where something is unread;
  - a press marks every thread of the section read at once, and nothing of another section;
  - "בטל" in its toast brings it all back;
  - when it is not taken back: a thread that only reported is read (out of "on him", as E does), while a real
    question stays on him; the server hears that they were seen.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

UNREAD = 'JSON.stringify(Object.fromEntries(Object.values(data.threads).map(t=>[t.id,unreadOf(t)])))'
BUTTON = ('(()=>{const b=document.querySelector(".sec-%s .sec-read");if(!b)return JSON.stringify(null);'
          'return JSON.stringify({op:+getComputedStyle(b).opacity,label:b.getAttribute("aria-label")||b.textContent});})()')


class ReadAll(test_e2e.Suda):
    def with_threads(self):
        if 'e2e-ra-w1' in self.state()['threads']:
            return
        for tid in ('e2e-ra-w1', 'e2e-ra-w2'):
            self.ok('new', tid, 'בעבודה ' + tid[-1], '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            self.ok('say', tid, '--from', 'fork', 'התקדמות ' + tid, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        # on him: a plain report (to read) and a real question
        self.ok('new', 'e2e-ra-report', 'דוח לקריאה', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.ok('say', 'e2e-ra-report', '--from', 'fork', 'דוח: הכל עבר')
        self.ok('new', 'e2e-ra-ask', 'שאלה אמיתית', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.ok('ask', 'e2e-ra-ask', 'להמשיך?', '--options', 'כן,לא')

    def open_list(self):
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(synced&&!!document.querySelector(".sec-working"))', what='the list')
        # a device that has seen nothing of these
        self.browser.eval('(()=>{for(const id of ["e2e-ra-w1","e2e-ra-w2","e2e-ra-report","e2e-ra-ask"])localStorage.setItem(PREFIX+"seen:"+id,"0");render();return "ok";})()')
        self.browser.wait('JSON.stringify(unreadOf(thread("e2e-ra-w1"))>0)', what='unread threads')

    def test_a_section_is_marked_read_from_its_head_and_can_be_taken_back(self):
        self.with_threads()
        self.open_list()
        # not on the page until the pointer is on the section's head
        self.assertEqual(self.browser.eval(BUTTON % 'working')['op'], 0)
        self.browser.pointer('.sec-working .sec-h', 'move', 'mouse') if hasattr(self.browser, 'pointer') else None
        self.browser.run('hover', '.sec-working .sec-h')
        self.browser.wait('JSON.stringify(+getComputedStyle(document.querySelector(".sec-working .sec-read")).opacity===1)', what='the button on hover')
        self.assertIn('כנקרא', self.browser.eval(BUTTON % 'working')['label'])
        import os
        if os.environ.get('READALL_SHOTS'):
            self.browser.run('screenshot', os.path.join(os.environ['READALL_SHOTS'], 'hover.png'))
        before = self.browser.eval(UNREAD)
        self.browser.eval('(()=>{READ_ALL_MS=60000;document.querySelector(".sec-working .sec-read").click();return "ok";})()')
        after = self.browser.eval(UNREAD)
        self.assertEqual((after['e2e-ra-w1'], after['e2e-ra-w2']), (0, 0), after)
        self.assertEqual(after['e2e-ra-ask'], before['e2e-ra-ask'], 'another section was marked too')
        self.assertIsNone(self.browser.eval(BUTTON % 'working'), 'the button stays where nothing is unread')
        # take it back
        self.browser.eval('(()=>{[...document.querySelectorAll(".toast button")].find(b=>b.textContent.includes("בטל")).click();return "ok";})()')
        back = self.browser.eval(UNREAD)
        self.assertEqual((back['e2e-ra-w1'], back['e2e-ra-w2']), (before['e2e-ra-w1'], before['e2e-ra-w2']), back)

    def test_on_him_a_report_is_read_and_a_question_stays(self):
        self.with_threads()
        self.open_list()
        self.assertEqual((self.thread('e2e-ra-report')['state'], self.thread('e2e-ra-ask')['state']), ('on-owner', 'on-owner'))
        self.browser.eval('(()=>{READ_ALL_MS=800;document.querySelector(".sec-on-owner .sec-read").click();return "ok";})()')
        self.until(lambda: self.thread('e2e-ra-report')['state'] == 'done', what='the report read on the server')
        time.sleep(1.0)
        ask = self.thread('e2e-ra-ask')
        self.assertEqual(ask['state'], 'on-owner', 'a real question was dismissed')
        self.assertTrue(ask.get('question'), ask)
        self.until(lambda: (self.thread('e2e-ra-ask').get('seen') or {}).get('msg'), what='the server told it was seen')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in ReadAll.__dict__:
        setattr(ReadAll, _name, None)


if __name__ == '__main__':
    unittest.main()
