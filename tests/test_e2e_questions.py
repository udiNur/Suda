#!/usr/bin/env python3
"""End to end: several open questions in one thread (the owner, thread suda m508: "when there are two questions, one
cancels the other"). Before, `threads ask` replaced the open question, so the buttons of the first one died
unanswered. Now an agent asks two questions; both show in the strip with their buttons at 360 and at 1280, the
newest first, and the buttons in each asking message stay live. He answers the OLDER one: the newer stays, and the
thread stays on him. Then the digit 1 answers the newer one, and the turn goes to the agents. The same harness as
test_e2e.py (headless Chrome, the real board server on loopback, a temporary board).

QUESTIONS_SHOTS=<folder> keeps a screenshot of the strip with two questions at each size.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-qs'
TITLE = 'שתי שאלות פתוחות'
# The question blocks of the strip, in order: [{q, newest, live: answers that can be pressed, digits}].
BLOCKS = r'''[...document.querySelectorAll("#pin .pin-q")].map(b=>({q:b.dataset.q,newest:b.classList.contains("newest"),
    live:[...b.querySelectorAll("button.option")].filter(x=>!x.disabled&&x.offsetParent).length,
    digits:b.querySelectorAll("button.option kbd.num").length}))'''
STRIP = 'JSON.stringify((()=>{const s=%s;return s.length===%%d?s:null;})())' % BLOCKS
# The answers under an asking message that can be pressed (null: the message is not drawn).
ROW = r'''(()=>{const row=[...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid==="%s");if(!row)return null;
  return [...row.querySelectorAll(".opts .opt")].filter(b=>!b.disabled).length;})()'''


class SeveralQuestions(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def ids(self):
        return [q['id'] for q in self.thread(TID).get('questions') or []]

    def shot(self, name):
        where = os.environ.get('QUESTIONS_SHOTS')
        if where:
            os.makedirs(where, exist_ok=True)
            self.browser.eval('(()=>{document.querySelector("#pin").scrollTop=0;return "ok";})()')
            time.sleep(0.4)
            self.browser.run('screenshot', os.path.join(where, name + '.png'))

    def test_two_questions_stay_open_and_each_is_answered_by_itself(self):
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('ask', TID, 'למזג את PR 7 לפני הפריסה?', '--options', 'למזג,לחכות'), 'm1')
        self.assertEqual(self.ok('ask', TID, 'לאיזו סביבה לפרוס?', '--options', 'סטייג׳ינג,פרודקשן,שתיהן', '--from', 'tower'), 'm2')
        self.assertEqual(self.ids(), ['m1', 'm2'])
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, TID, TITLE)
                strip = self.browser.wait(STRIP % 2, what='both questions in the strip')
                self.assertEqual([b['q'] for b in strip], ['m2', 'm1'])                    # the newest first
                self.assertEqual([b['newest'] for b in strip], [True, False])
                self.assertEqual([b['live'] for b in strip], [3, 2])                       # every answer of both can be pressed
                self.assertEqual(strip[1]['digits'], 0)                                    # 1 to 9 answer the newest only
                if size[0] == 'desktop':
                    self.assertEqual(strip[0]['digits'], 3)
                for mid, n in (('m1', 2), ('m2', 3)):                                       # and under each asking message
                    self.assertEqual(self.browser.wait('JSON.stringify(%s)' % (ROW % mid), what='the buttons of ' + mid), n)
                # the strip stays inside the screen at the phone's width
                width = self.browser.eval('JSON.stringify(Math.round(document.querySelector("#pin").scrollWidth-document.querySelector("#pin").clientWidth))')
                self.assertLessEqual(width, 0)
                self.shot('strip-%d' % size[1])
        # He answers the OLDER question from its own button in the strip (1280 wide).
        self.browser.click('#pin .pin-q.older button.option')
        self.until(lambda: self.ids() == ['m2'], timeout=20, what='m1 answered, m2 still open')
        t = self.thread(TID)
        self.assertEqual((t['question']['id'], t['state']), ('m2', 'on-owner'))
        self.assertEqual(t['messages'][-1]['re']['q'], 'm1')
        self.assertEqual(t['messages'][-1]['text'], 'למזג')
        strip = self.browser.wait(STRIP % 1, timeout=20, what='one question left in the strip')
        self.assertEqual((strip[0]['q'], strip[0]['live']), ('m2', 3))
        self.browser.wait('JSON.stringify(%s===0)' % (ROW % 'm1'), what="m1's buttons go quiet")
        # Then the digit 1 answers the newer one, and the turn goes to the agents.
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.browser.press('Digit1')
        self.browser.wait('JSON.stringify(localOf(thread(view.ch)).some(m=>m.answers==="m2"))', what='the digit chose an answer of m2')
        self.until(lambda: self.ids() == [], timeout=30, what='m2 answered')
        t = self.thread(TID)
        self.assertEqual((t['question'], t['state']), (None, 'working'))
        self.assertEqual((t['messages'][-1]['re']['q'], t['messages'][-1]['text']), ('m2', 'סטייג׳ינג'))
        self.browser.wait('JSON.stringify(!document.querySelector("#pin .pin-q"))', timeout=20, what='the strip without questions')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in SeveralQuestions.__dict__:
        setattr(SeveralQuestions, _name, None)


if __name__ == '__main__':
    unittest.main()
