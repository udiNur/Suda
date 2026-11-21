#!/usr/bin/env python3
"""End to end: line wrapping is one choice for every block (the owner, thread suda m311).

"If I change something about line wrapping, make it the default for the next things that render too, so that it
is not always only on the last one." Before, the press on a block of code wrapped that block alone, and the next
message, the next thread and the next load were unwrapped again. The same harness as test_e2e.py (headless
Chrome, the real board server on loopback, a temporary board). What is checked:

  - a press on one block's "wrap lines" wraps every block of code on the page, and the block he pressed does not
    move on the screen;
  - a message that arrives afterwards, another thread, and the page loaded again are wrapped too;
  - by the keys alone: the chosen message's buttons reach the same press, and the keys stay on it;
  - the same choice is a command in the palette;
  - a long text on the whole screen has its own choice, kept the same way;
  - another tab of his that changes the choice is followed.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES

LONG = 'curl -sS -X POST "https://example.invalid/api/v1/machines/%d/refunds?reason=partial&amount=1250&currency=ILS&notify=true&dry_run=false" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"'
# every block of code in the log: how its lines are laid, what its button says, and whether a line runs past its edge
BLOCKS = ('JSON.stringify([...document.querySelectorAll("#log .code")].map(c=>({ws:getComputedStyle(c.querySelector("code")).whiteSpace,'
          'pressed:c.querySelector(".wrap-toggle").getAttribute("aria-pressed"),past:c.querySelector("pre").scrollWidth>c.querySelector("pre").clientWidth+1})))')
KEPT = 'JSON.stringify([localStorage.getItem("suda-wrap-code"),localStorage.getItem("suda-wrap-text")])'
READER = ('JSON.stringify({open:!document.querySelector("#reader").hidden,nowrap:document.querySelector("#reader-body").classList.contains("nowrap"),'
          'ws:getComputedStyle(document.querySelector("#reader-body")).whiteSpace,pressed:(document.querySelector("#reader-tools .nowrap-toggle")||{getAttribute:()=>null}).getAttribute("aria-pressed")})')


class Wrap(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-wrap'
    TITLE = 'קוד עם שורות ארוכות'

    def code(self, tid, n):
        self.ok('say', tid, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork',
                input='הודעה %d עם קוד:\n\n```sh\n%s\necho done %d\n```\n\nוטקסט אחרי הקוד.\n' % (n, LONG % n, n))

    def board_with_code(self):
        if self.TID in self.state()['threads']:
            return
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', 'e2e-wrap-other', 'נושא אחר עם קוד', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in (1, 2, 3):
            self.code(self.TID, n)
        self.code('e2e-wrap-other', 9)
        log = Path(self.tmp.name) / 'long.log'
        log.write_text('\n'.join('line %d of a long log: ' % i + 'x' * 400 for i in range(1, 40)), encoding='utf-8')
        self.ok('say', self.TID, '--from', 'fork', 'לוג מצורף', '--snippet', str(log), '--state', 'working', '--note', 'בודקים', '--by', 'fork')

    def fresh(self, size):
        """The thread on a page that has no choice of his yet."""
        self.open_thread(size, self.TID, self.TITLE)
        self.browser.eval('(()=>{localStorage.removeItem("suda-wrap-code");localStorage.removeItem("suda-wrap-text");return "ok";})()')
        self.open_thread(size, self.TID, self.TITLE)
        # the server's own state, not the copy this device kept from the round before
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&document.querySelectorAll("#log .code").length>=3)' % json.dumps(self.TID), what='the blocks of code')

    def blocks(self):
        return self.browser.eval(BLOCKS)

    def test_a_press_on_one_block_wraps_every_block_now_and_later(self):
        self.board_with_code()
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.fresh(size)
                # as the page starts: no block wraps, and a long line runs past the block's edge (it scrolls sideways)
                start = self.blocks()
                self.assertGreaterEqual(len(start), 3)
                self.assertTrue(all(b == {'ws': 'pre', 'pressed': 'false', 'past': True} for b in start), start)
                self.assertEqual(self.browser.eval(KEPT), [None, None])
                # 1. he presses "wrap lines" on the SECOND block: every block wraps, and the one under his finger stays where it was
                self.browser.eval('(()=>{document.querySelectorAll("#log .wrap-toggle")[1].scrollIntoView({block:"center"});return "ok";})()')
                time.sleep(0.4)
                top = 'JSON.stringify(Math.round(document.querySelectorAll("#log .wrap-toggle")[1].getBoundingClientRect().top))'
                before = self.browser.eval(top)
                self.browser.eval('(()=>{document.querySelectorAll("#log .wrap-toggle")[1].click();return "ok";})()')
                self.assertLessEqual(abs(self.browser.eval(top) - before), 1, 'the block he pressed jumped')
                wrapped = self.blocks()
                self.assertEqual(len(wrapped), len(start))
                self.assertTrue(all(b == {'ws': 'pre-wrap', 'pressed': 'true', 'past': False} for b in wrapped), wrapped)
                self.assertEqual(self.browser.eval(KEPT)[0], '1')
                self.browser.eval('(async()=>{await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));return "ok";})()')
                self.assertLessEqual(abs(self.browser.eval(top) - before), 1, 'the block he pressed moved once the browser had drawn')
                # 2. a message that arrives now is wrapped from its first moment
                n = 40 + SIZES.index(size)
                self.code(self.TID, n)
                self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes("echo done %d"))' % n, what='the new message')
                self.assertEqual(self.blocks()[-1], {'ws': 'pre-wrap', 'pressed': 'true', 'past': False})
                # 3. another thread, and the page loaded again
                self.open_thread(size, 'e2e-wrap-other', 'נושא אחר עם קוד')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .code").length>=1)', what='the other thread\'s code')
                self.assertEqual(self.blocks(), [{'ws': 'pre-wrap', 'pressed': 'true', 'past': False}])
                # 4. a press there turns it off again, for every block everywhere
                self.browser.click('#log .wrap-toggle')
                self.assertEqual(self.blocks(), [{'ws': 'pre', 'pressed': 'false', 'past': True}])
                self.assertEqual(self.browser.eval(KEPT)[0], '0')
                self.open_thread(size, self.TID, self.TITLE)
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .code").length>=3)', what='the blocks of code')
                self.assertTrue(all(b == {'ws': 'pre', 'pressed': 'false', 'past': True} for b in self.blocks()), self.blocks())

    def test_by_the_keys_alone_and_from_the_palette(self):
        self.board_with_code()
        self.fresh(SIZES[2])
        # the last message with code is chosen with the arrows; its buttons are walked with the side arrows
        self.browser.press('Escape')
        for _ in range(6):
            self.browser.press('ArrowUp')
            if self.browser.eval('JSON.stringify(!!document.activeElement.closest&&!!document.activeElement.querySelector&&!!document.activeElement.querySelector(".wrap-toggle"))'):
                break
        self.assertTrue(self.active()['isRow'], self.active())
        self.browser.press('Enter')
        for _ in range(12):
            if 'wrap-toggle' in self.active()['cls']:
                break
            self.browser.press('ArrowLeft')
        self.assertIn('wrap-toggle', self.active()['cls'], self.active())
        self.browser.press('Enter')
        self.assertTrue(all(b == {'ws': 'pre-wrap', 'pressed': 'true', 'past': False} for b in self.blocks()), self.blocks())
        self.assertIn('wrap-toggle', self.active()['cls'], 'the keys left the button he pressed')
        self.browser.press('Enter')                     # and off again, with the keys still on it
        self.assertTrue(all(b['ws'] == 'pre' and b['pressed'] == 'false' for b in self.blocks()), self.blocks())
        self.browser.press('Escape', 2)
        # the palette has the same choice as a command, named by what it will do
        rows = lambda: self.browser.eval('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row")].map(r=>r.innerText.replace(/\\s+/g," ").trim()))')
        find = lambda words: self.browser.eval('(()=>{const q=document.querySelector("#sw-query");q.value=%s;q.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()' % json.dumps(words))
        self.browser.press('Control+k')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        find('קטעי קוד')
        self.assertTrue(any('קטעי קוד: גלישת שורות ארוכות' in row for row in rows()), rows())
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(document.querySelector("#switcher").hidden)', what='the palette to close')
        self.assertTrue(all(b['ws'] == 'pre-wrap' and b['pressed'] == 'true' for b in self.blocks()), self.blocks())
        self.assertEqual(self.browser.eval(KEPT)[0], '1')
        self.browser.press('Control+k')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        find('קטעי קוד')
        self.assertTrue(any('קטעי קוד: בלי גלישת שורות' in row for row in rows()), rows())       # now it offers the way back
        self.browser.press('Escape')

    def test_a_long_text_on_the_whole_screen_keeps_its_own_choice(self):
        self.board_with_code()
        self.fresh(SIZES[2])
        show = lambda: (self.browser.eval('(()=>{[...document.querySelectorAll("#log .snip-acts .chipbtn")].find(b=>b.innerText.includes("הצג הכול")).click();return "ok";})()'),
                        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&document.querySelector("#reader-body").textContent.length>1000)', what='the long text on the whole screen'))
        close = lambda: (self.browser.press('Escape'), self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader to close'))
        # as the page starts, a long text wraps
        show()
        self.assertEqual(self.browser.eval(READER), {'open': True, 'nowrap': False, 'ws': 'pre-wrap', 'pressed': 'false'})
        # he turns wrapping off: kept, and so the next time, also after the page is loaded again
        self.browser.click('#reader-tools .nowrap-toggle')
        self.assertEqual(self.browser.eval(READER), {'open': True, 'nowrap': True, 'ws': 'pre', 'pressed': 'true'})
        self.assertEqual(self.browser.eval(KEPT), [None, '0'])            # the blocks of code have their own choice, untouched
        close()
        show()
        self.assertEqual(self.browser.eval(READER)['nowrap'], True)
        close()
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .snip-acts"))', what='the snippet')
        show()
        self.assertEqual(self.browser.eval(READER), {'open': True, 'nowrap': True, 'ws': 'pre', 'pressed': 'true'})
        # by the keys: the button is reached with Tab inside the reader, and Enter turns wrapping on again
        for _ in range(10):
            if 'nowrap-toggle' in self.active()['cls']:
                break
            self.browser.press('Tab')
        self.assertIn('nowrap-toggle', self.active()['cls'], self.active())
        self.browser.press('Enter')
        self.assertEqual(self.browser.eval(READER), {'open': True, 'nowrap': False, 'ws': 'pre-wrap', 'pressed': 'false'})
        self.assertEqual(self.browser.eval(KEPT)[1], '1')
        close()

    def test_another_tab_of_his_is_followed(self):
        self.board_with_code()
        self.fresh(SIZES[2])
        self.assertTrue(all(b['ws'] == 'pre' for b in self.blocks()))
        # what the browser tells a page when another tab of the same site wrote the choice
        self.browser.eval('(()=>{window.dispatchEvent(new StorageEvent("storage",{key:"suda-wrap-code",newValue:"1"}));return "ok";})()')
        self.assertTrue(all(b == {'ws': 'pre-wrap', 'pressed': 'true', 'past': False} for b in self.blocks()), self.blocks())
        self.browser.eval('(()=>{window.dispatchEvent(new StorageEvent("storage",{key:"suda-wrap-code",newValue:null}));return "ok";})()')
        self.assertTrue(all(b['ws'] == 'pre' and b['pressed'] == 'false' for b in self.blocks()), self.blocks())


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Wrap.__dict__:
        setattr(Wrap, _name, None)


if __name__ == '__main__':
    unittest.main()
