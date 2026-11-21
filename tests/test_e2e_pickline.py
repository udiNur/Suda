#!/usr/bin/env python3
"""End to end: a whole line he selected can be answered (the owner, suda m588: "sometimes when I select a whole
line I cannot reply to it"). A triple click, or a drag to the end of a line, makes a selection that ends at the
start of what follows: the next paragraph, or the next message. The reply chip must still offer to answer the
words he selected, in the message where they are. The same harness as test_e2e.py; real clicks through CDP.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e_gallery import Cdp
from test_e2e import SIZES

CHIP = 'JSON.stringify(!document.querySelector("#pick-chip").hidden)'


class PickLine(test_e2e.Suda):
    def thread_(self):
        if 'e2e-pl' not in self.state()['threads']:
            self.ok('new', 'e2e-pl', 'בחירת שורה שלמה', '--state', 'working', '--note', 'בודק', '--by', 'e2e')
            self.ok('say', 'e2e-pl', '--from', 'fork', '-', '--state', 'working', '--note', 'בודק', '--by', 'e2e',
                    input='השורה הראשונה של ההודעה\n\nהפסקה השנייה של אותה הודעה')
            self.ok('say', 'e2e-pl', '--from', 'tower', '-', '--state', 'working', '--note', 'בודק', '--by', 'e2e',
                    input='הודעה אחרת אחריה')

    def click3(self, cdp, x, y):
        for n in (1, 2, 3):
            for kind in ('mousePressed', 'mouseReleased'):
                cdp.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': n})
            time.sleep(0.05)

    def point_of(self, words):
        return self.browser.eval('JSON.stringify((()=>{const p=[...document.querySelectorAll("#log .msg .body p")].find(p=>p.textContent.includes(%r));'
                                 'const r=p.getBoundingClientRect();return [r.left+12,r.top+r.height/2];})())' % words)

    def picked(self):
        return self.browser.eval('JSON.stringify(picked&&picked.text)')

    def test_a_whole_line_picked_by_a_triple_click_can_be_answered(self):
        self.thread_()
        self.open_thread(SIZES[2], 'e2e-pl', 'בחירת שורה שלמה')
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        for words in ('הפסקה השנייה של אותה הודעה', 'השורה הראשונה של ההודעה'):     # the last line of a message, then a line with more under it
            with self.subTest(words=words):
                self.browser.eval('(()=>{getSelection().removeAllRanges();return "ok";})()')
                time.sleep(0.3)
                x, y = self.point_of(words)
                self.click3(cdp, x, y)
                self.browser.wait(CHIP, what='the reply chip beside a whole line', timeout=5)
                self.assertEqual(self.picked(), words)

    def test_a_selection_that_runs_into_the_next_message_answers_its_own(self):
        self.thread_()
        self.open_thread(SIZES[2], 'e2e-pl', 'בחירת שורה שלמה')
        # from the start of the second paragraph to the start of the next message's words (a drag that went one line too far)
        self.browser.eval('(()=>{const ps=[...document.querySelectorAll("#log .msg .body p")];'
                          'const a=ps.find(p=>p.textContent.includes("הפסקה השנייה")),b=ps.find(p=>p.textContent.includes("הודעה אחרת"));'
                          'const r=document.createRange();r.setStart(a.firstChild,0);r.setEnd(b.firstChild,0);'
                          'getSelection().removeAllRanges();getSelection().addRange(r);return "ok";})()')
        self.browser.wait(CHIP, what='the reply chip for a selection that ends in the next message', timeout=5)
        self.assertEqual(self.picked(), 'הפסקה השנייה של אותה הודעה')
        mid = self.browser.eval('JSON.stringify(picked.mid)')
        self.assertEqual(mid, self.thread('e2e-pl')['messages'][0]['id'])
        # and the reply goes, quoting exactly those words of that message
        self.browser.click('#pick-reply')
        self.browser.wait('JSON.stringify(document.activeElement===document.querySelector("#input"))', what='the box, ready for the reply')
        self.browser.fill('#input', 'תשובה לשורה')
        self.browser.click('#send')
        m = self.until(lambda: next((m for m in self.thread('e2e-pl')['messages'] if m.get('text') == 'תשובה לשורה'), None), what='the reply')
        self.assertEqual((m['reply_to']['id'], m['reply_to'].get('quote')), (mid, 'הפסקה השנייה של אותה הודעה'))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in PickLine.__dict__:
        setattr(PickLine, _name, None)


if __name__ == '__main__':
    unittest.main()
