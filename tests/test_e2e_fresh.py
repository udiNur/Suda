#!/usr/bin/env python3
"""End to end: a new build of Suda on the server (the owner, thread suda m232).

"When there's an update because you pushed something, have a button at the top that refreshes." The same harness
as test_e2e.py: headless Chrome, the real board server on loopback, the CLI behind its hook, a temporary board.
What is checked, on the phone's size and on the desktop's:

  - the same page published again (a new date on the file, the same bytes) shows nothing;
  - another build shows the strip within seconds of the next thing that happens on the board;
  - one press loads it: the same conversation, the words he was typing, and the place he stood at.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES


class Fresh(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-fresh'
    TITLE = 'נושא לבדיקת גרסה חדשה'
    SHOWN = 'JSON.stringify(!document.querySelector("#newer").hidden)'

    def current_shell(self, size):
        """The worker keeps the page's file and opens with the kept copy. A scenario that put another file on the
        server waits here until the worker has read it, so that the next opening is of that file."""
        self.open(size)
        self.browser.wait('(async()=>{if(!("serviceWorker" in navigator)||!window.isSecureContext)return "true";await navigator.serviceWorker.ready;'
                          'const now_=await (await fetch(location.pathname,{cache:"no-store"})).text(),kept=await (await caches.open("suda-shell-1")).match(location.pathname);'
                          'return JSON.stringify(!!kept&&(await kept.text())===now_);})()', timeout=20, what='the worker to keep the page that is on the server')

    def say(self, text):
        self.ok('say', self.TID, '--from', 'fork', text, '--state', 'working', '--note', 'בודקים גרסה חדשה')

    def test_a_new_build_shows_one_button_that_loads_it_where_he_was(self):
        self.ok('new', self.TID, self.TITLE, '--summary', 'הדף מתפרסם מחדש בזמן שהוא פתוח', '--state', 'working', '--note', 'בודקים גרסה חדשה', '--by', 'e2e')
        for i in range(14):
            self.say('הודעה מספר %d, עם מספיק טקסט כדי שהשיחה תהיה ארוכה מהמסך.\n\n- פרט ראשון\n- פרט שני' % i)
        page = self.board / 'suda.html'
        original = page.read_bytes()
        self.addCleanup(page.write_bytes, original)
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                page.write_bytes(original)
                self.current_shell(size)
                self.open_thread(size, self.TID, self.TITLE)
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=14)', what='the long conversation')
                self.assertEqual(self.browser.eval(self.SHOWN), False, 'the strip on a page that just loaded')

                # 1. the same page published again: the date moves, and nothing is shown
                time.sleep(4.2)                      # the page asks at most once in a few seconds
                page.write_bytes(original)
                stamp = int(page.stat().st_mtime)
                self.say('משהו קורה בלוח אחרי פרסום חוזר, מסך ' + size[0])
                self.browser.wait('JSON.stringify(buildStamp===%d)' % stamp, timeout=20, what='the page to notice the new date')
                self.assertEqual(self.browser.eval(self.SHOWN), False, 'the same page published again was taken for a new build')

                # 2. another build: the strip, within seconds of the next thing that happens
                time.sleep(4.2)
                changed = original.replace('<span data-t>Go to a topic</span>'.encode(), '<span data-t>Go to a topic </span>'.encode())
                self.assertNotEqual(changed, original)
                page.write_bytes(changed)
                self.say('משהו קורה בלוח אחרי גרסה חדשה, מסך ' + size[0])
                self.browser.wait(self.SHOWN, timeout=20, what='the strip that says there is a new build')
                self.assertIn('גרסה חדשה', self.browser.eval('JSON.stringify(document.querySelector("#newer").innerText)'))

                # 3. one press loads it: the same conversation, his words, his place
                self.browser.eval('(()=>{const s=document.querySelector("#scroll");s.scrollTop=Math.round(s.scrollHeight*0.35);window.__old=1;return "ok";})()')
                self.browser.wait('JSON.stringify(document.querySelector("#scroll").scrollHeight-document.querySelector("#scroll").clientHeight-document.querySelector("#scroll").scrollTop>200)',
                                  what='the log scrolled up')
                draft = 'מילים שהוא באמצע לכתוב, מסך ' + size[0]
                self.browser.fill('#input', draft)
                before = self.browser.eval('JSON.stringify(placeNow())')
                self.assertFalse(before['bottom'])
                self.assertTrue(before['at'])
                self.browser.click('#newer')
                self.browser.wait('JSON.stringify(typeof window.__old==="undefined"&&document.readyState==="complete"&&document.querySelectorAll("#log .msg").length>=14)',
                                  timeout=20, what='the new build loaded')
                self.browser.wait('JSON.stringify(placeNow().at===%s)' % json.dumps(before['at']), what='his place in the conversation')
                after = self.browser.eval('JSON.stringify({place:placeNow(),draft:document.querySelector("#input").value,hash:location.hash,shown:!document.querySelector("#newer").hidden,'
                                          'new_:document.querySelector("#jump-to span").textContent})')
                self.assertEqual(after['hash'], '#' + self.TID)
                self.assertEqual(after['draft'], draft)
                self.assertLessEqual(abs(after['place']['off'] - before['off']), 3, (before, after['place']))
                self.assertEqual(after['new_'], 'מעבר לנושא ', 'the page that loaded is not the new build')
                self.assertFalse(after['shown'], 'the strip is still shown on the build it announced')
                self.browser.fill('#input', '')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Fresh.__dict__:
        setattr(Fresh, _name, None)


if __name__ == '__main__':
    unittest.main()
