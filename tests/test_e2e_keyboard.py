#!/usr/bin/env python3
"""End to end: the conversation moves with the on-screen keyboard (the owner, thread suda m269).

"When the keyboard opens the scroll position moves ... I don't see what was above." The keyboard takes the lower
part of the screen: the log's window gets shorter from below, and before this the log stayed where it was, so
what he had just read above the composer went under the keyboard. The same harness as test_e2e.py (headless
Chrome, the real board server on loopback, a temporary board); a headless browser has no on-screen keyboard, so
the window is made shorter instead, which is what the page sees when one opens. What is checked:

  - at the end of the conversation he stays at the end while the window gets shorter and taller again;
  - further up, the message that stood just above the composer stays at the same distance above it, and the log
    is back at the very same place when the window is tall again;
  - the same when the composer grows with several lines of his, at a computer too;
  - a window at a computer that is made shorter is not a keyboard: there the log stays where it stood;
  - none of these moves is told to the server as a place he chose.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES


class Keyboard(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-keyboard'
    TITLE = 'שיחה ארוכה מול המקלדת'
    AT_END = 'JSON.stringify(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop<=2)'
    # the last message that shows above the composer: which one, how far its bottom is from the window's lower
    # edge, where the log stands, and how tall its window is
    EDGE = ('(()=>{const box=scroller.getBoundingClientRect(),rows=[...document.querySelectorAll("#log .msg")].filter(n=>n.dataset.mid),'
            'row=[...rows].reverse().find(n=>n.getBoundingClientRect().top<box.bottom-4);'
            'return JSON.stringify({row:row.dataset.mid,off:Math.round(row.getBoundingClientRect().bottom-box.bottom),top:Math.round(scroller.scrollTop),tall:Math.round(box.height)});})()')

    def edge(self):
        return self.browser.eval(self.EDGE)

    def tall(self, test, what):
        """Wait until the log's window has the height the test asks for, and until the page has drawn since.

        The page answers a new height when the browser next draws (that is when a ResizeObserver is told), and a
        headless browser draws only now and then: asking for the height is not enough, the page must be given two
        frames. On a phone a frame comes every few milliseconds."""
        self.browser.wait('JSON.stringify((h=>%s)(Math.round(scroller.getBoundingClientRect().height)))' % test, what=what)
        self.browser.eval('(async()=>{await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));return "ok";})()')
        return self.edge()

    def place_on_server(self):
        path = self.board / 'places.json'
        return (json.loads(path.read_text(encoding='utf-8')).get('places') or {}).get(self.TID) if path.is_file() else None

    def test_what_stood_above_the_composer_stays_above_it(self):
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 25):
            self.ok('say', self.TID, '--from', 'fork', '-', '--state', 'working', '--note', 'שורה', '--by', 'fork', input='הודעה מספר %d\n\n' % n + 'שורה נוספת\n\n' * 3)
        for size in (SIZES[0], SIZES[2]):
            name, w, h = size
            with self.subTest(size=name):
                self.open_thread(size, self.TID, self.TITLE)
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=24)', what='the long conversation')
                self.browser.eval('(()=>{scroller.scrollTop=1e9;return "ok";})()')
                self.browser.wait(self.AT_END, what='the end of the conversation')
                full = self.edge()['tall']

                phone = size is SIZES[0]             # the on-screen keyboard belongs to the phone's layout
                # 1. at the end: the keyboard comes up and goes down, and he is still at the end
                self.browser.viewport(w, h - 300)
                self.tall('h<=%d' % (full - 250), 'the window shorter, as with the keyboard up')
                self.assertTrue(self.browser.eval(self.AT_END), 'at the end, the keyboard came up and the last message went under it')
                self.browser.viewport(w, h)
                self.tall('h>=%d' % (full - 2), 'the window tall again')
                self.assertTrue(self.browser.eval(self.AT_END), 'at the end, the keyboard went down and he is not at the end')

                # 2. further up: what stood just above the composer stays just above it, and comes back down with the keyboard
                self.browser.eval('(()=>{scroller.scrollTop=Math.round(scroller.scrollHeight*0.45);return "ok";})()')
                before = self.edge()
                if 'place' in self.ops:
                    told = self.until(lambda: (lambda p: p if p and p.get('bottom') is False else None)(self.place_on_server()), what='his place in the middle on the server')
                self.browser.viewport(w, h - 300)
                up = self.tall('h<=%d' % (full - 250), 'the window shorter, as with the keyboard up')
                if phone:
                    self.assertEqual(up['row'], before['row'], 'another message stands above the composer once the keyboard is up')
                    self.assertLessEqual(abs(up['off'] - before['off']), 2, (before, up))
                else:
                    # a window at a computer that is made shorter is not a keyboard: the log stays where it stood
                    self.assertEqual(up['top'], before['top'], (before, up))
                self.browser.viewport(w, h)
                down = self.tall('h>=%d' % (full - 2), 'the window tall again')
                self.assertEqual(down['row'], before['row'])
                self.assertLessEqual(abs(down['off'] - before['off']), 2, (before, down))
                self.assertLessEqual(abs(down['top'] - before['top']), 2, 'the log is not back where it stood: %r' % ((before, down),))

                # 3. the composer grows with his lines: the same
                self.browser.fill('#input', '\n'.join('שורה %d של הודעה ארוכה' % i for i in range(1, 7)))
                grown = self.tall('h<=%d' % (full - 40), 'the composer taller, the window shorter')
                self.assertEqual(grown['row'], before['row'], 'another message stands above the composer once it grew')
                self.assertLessEqual(abs(grown['off'] - before['off']), 2, (before, grown))
                self.browser.fill('#input', '')
                back = self.tall('h>=%d' % (full - 2), 'the composer small again')
                self.assertLessEqual(abs(back['top'] - before['top']), 2, (before, back))

                # 4. these were the page's own moves: the server heard of no new place
                if 'place' in self.ops:
                    time.sleep(2.6)
                    self.assertEqual(self.place_on_server()['ts'], told['ts'], 'a move the page made itself was told as a place he chose')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Keyboard.__dict__:
        setattr(Keyboard, _name, None)


if __name__ == '__main__':
    unittest.main()
