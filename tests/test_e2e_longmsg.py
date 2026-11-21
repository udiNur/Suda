#!/usr/bin/env python3
"""End to end: a very long message is folded, a tap opens it (suda-fixes 74; the owner, suda-connectivity m3: "messages
that are long enough, but only really long ones, should shrink, with a button to open them, because scrolling past them
is a nightmare; maybe a setting for it").

- From 3000 characters (the default) a message shows its first part and a button with its size; a shorter one is
  shown whole, with no button.
- The button opens it and folds it again; open, it stays open when the conversation is drawn again.
- Find in the thread opens a folded message when its hit is in it.
- The setting (Settings, "הודעות ארוכות"): 1500, 3000, 6000 or never, for this device.
The same harness as test_e2e.py."""
import json
import unittest

import _paths  # noqa: F401  (the test folders on sys.path)
import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
TID = 'e2e-longmsg'
TITLE = 'הודעות ארוכות'
LONG = '\n\n'.join('פסקה %d: ' % i + 'מילים בעברית שחוזרות על עצמן כדי שההודעה תהיה ארוכה מאוד. ' * 6 for i in range(12)) + '\n\nסוף ההודעה הארוכה: המחט'
MID = 'הודעה באורך בינוני. ' * 100           # about 2000 characters: folded only at 1500
SHORT = 'הודעה קצרה'
FOLDED = '#log .msg .body.folded'


class LongMessages(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for text in (LONG, MID, SHORT):
            cls.ok('say', TID, '--from', 'fork', '-', input=text + '\n')

    def show(self, size, at=None):
        self.browser.open(self.origin + '/' + test_e2e.SLUG + '/state.json')
        key = json.dumps(test_e2e.SLUG + ':long-at')
        self.browser.eval('(()=>{%s;return 1})()' % ('localStorage.removeItem(%s)' % key if at is None else 'localStorage.setItem(%s,%s)' % (key, json.dumps(str(at)))))
        self.open_thread(size, TID, TITLE)
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg .body").length>=3)', what='the messages')

    def bodies(self):      # (not state(): the harness's own state() reads the board)
        return self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].filter(m=>m.querySelector(".body")).map(m=>{'
                                 'const b=m.querySelector(".body"),u=m.querySelector(".unfold");'
                                 'return {len:b.textContent.length,folded:b.classList.contains("folded"),h:b.getBoundingClientRect().height,'
                                 'button:u?u.textContent:null,open:u?u.getAttribute("aria-expanded"):null}}))')

    def test_only_a_really_long_message_folds_and_a_tap_opens_it(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                self.show(size)
                long_, mid, short = self.bodies()[-3:]
                self.assertTrue(long_['folded'], long_)
                self.assertIn('הצג את כל ההודעה', long_['button'])
                self.assertIn(format(len(LONG), ','), long_['button'], 'it says how long it is')
                self.assertLess(long_['h'], 420, 'folded, it takes a part of the screen: %s' % long_)
                for m in (mid, short):
                    self.assertFalse(m['folded'], m)
                    self.assertIsNone(m['button'], m)
                self.browser.click('#log .msg .unfold')
                got = self.bodies()[-3]
                self.assertFalse(got['folded'])
                self.assertEqual(got['open'], 'true')
                self.assertGreater(got['h'], long_['h'] * 2, 'open, the whole message')
                # drawn again: it stays open
                self.browser.eval('(()=>{logSignature="";render();return 1})()')
                self.assertFalse(self.bodies()[-3]['folded'], 'drawn again, it stays open')
                self.browser.click('#log .msg .unfold')
                self.assertTrue(self.bodies()[-3]['folded'], 'and the button folds it again')

    def test_find_in_the_thread_opens_a_folded_message_where_its_hit_is(self):
        self.show(DESK)
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector(%s))' % json.dumps(FOLDED)))
        self.browser.eval('(()=>{openFind();const q=document.querySelector("#find-q");q.value="המחט";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("mark.hl.cur"))', what='the hit')
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("mark.hl.cur").closest(".body.folded"))'), 'the hit is in sight: its message opened')

    def test_the_threshold_is_his_choice(self):
        self.show(DESK, at=1500)
        self.assertEqual([m['folded'] for m in self.bodies()[-3:]], [True, True, False], 'from 1500 the middle one folds too')
        self.show(DESK, at=0)
        self.assertEqual([m['folded'] for m in self.bodies()[-3:]], [False, False, False], 'never')
        # the setting itself, in Settings
        self.show(DESK)
        self.browser.eval('(()=>{openNotify();return 1})()')
        chips = self.browser.eval('JSON.stringify([...document.querySelectorAll("#notify-body .chip")].map(b=>[b.textContent,b.getAttribute("aria-pressed")]).filter(c=>/תווים|אף פעם/.test(c[0])))')
        self.assertEqual([c[0] for c in chips], ['1,500 תווים', '3,000 תווים', '6,000 תווים', 'אף פעם'])
        self.assertEqual([c[1] for c in chips], ['false', 'true', 'false', 'false'])


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(LongMessages(name) for name in sorted(vars(LongMessages)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
