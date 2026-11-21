#!/usr/bin/env python3
"""End to end: the page opens at once from the worker's kept copy, and coming back to it never loads it again
(the owner, thread suda m313/m317/m318).

"Every opening of Suda's screen sometimes takes a few seconds." and "every time I turn the screen off and open it
... I see it for a second and then it disappears and opens again". The worker keeps the page's own file and
answers an opening with it, reading the server's copy behind the opening; a newer build is then offered by the
strip, never loaded by itself. Coming back to a page whose line to the server was dropped opens the line again
and reads the state: the page stays the page it was. The same harness as test_e2e.py (headless Chrome, the real
board server on loopback, where a worker is allowed; a temporary board). What is checked:

  - the worker keeps the page from the first opening;
  - with another build on the server, the next opening still shows the kept one at once, the strip appears within
    seconds without anything else happening on the board, and one press loads the new build;
  - a page whose line to the server was closed opens it again when he comes back, takes in what he missed, and is
    not loaded again: what he typed, the rows he saw and the page itself are the same.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

KEPT = ('(async()=>{if(!("serviceWorker" in navigator)||!window.isSecureContext)return "null";await navigator.serviceWorker.ready;'
        'const kept=await (await caches.open("suda-shell-1")).match(location.pathname);return JSON.stringify(kept?await kept.text():"");})()')
BUILD = 'JSON.stringify(document.querySelector("#jump-to span").textContent)'        # the words on a button of the page: the test's two builds differ in them


class Shell(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-shell'
    TITLE = 'הדף נפתח מיד'

    def topic(self):
        if self.TID not in self.state()['threads']:
            self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            for n in range(1, 13):
                self.ok('say', self.TID, '--from', 'fork', 'הודעה מספר %d\n\nשורה נוספת' % n, '--state', 'working', '--note', 'בודקים')

    def kept_is(self, text, what):
        self.browser.wait('(async()=>{const kept=await (await caches.open("suda-shell-1")).match(location.pathname);return JSON.stringify(!!kept&&(await kept.text())===%s);})()' % json.dumps(text),
                          timeout=20, what=what)

    def test_an_opening_shows_the_kept_page_and_a_newer_build_is_offered(self):
        self.topic()
        page = self.board / 'suda.html'
        original = page.read_text(encoding='utf-8')
        self.addCleanup(page.write_text, original, encoding='utf-8')
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        if self.browser.eval(KEPT) is None:
            self.skipTest('this browser allows no worker on a loopback page')
        # 1. the worker keeps the page from the first opening
        self.kept_is(original, 'the worker to keep the page')
        self.assertIn('summary.json', original)                 # the page that is kept, not an error page
        # 2. another build is put on the server while no page is open
        self.browser.open('about:blank')
        changed = original.replace('<span data-t>Go to a topic</span>', '<span data-t>Go to a topic </span>')
        self.assertNotEqual(changed, original)
        time.sleep(1.1)                                         # a file's date has whole seconds
        page.write_text(changed, encoding='utf-8')
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(synced&&document.querySelectorAll("#log .msg").length>=12)', timeout=20, what='the thread')
        # the page that opened is the kept one: the opening did not wait for the server's copy
        self.assertEqual(self.browser.eval(BUILD), 'מעבר לנושא', 'the opening was not answered with the kept page')
        # ... and behind it the worker read the server's copy: the strip says so within seconds, with nothing else happening on the board
        self.browser.wait('JSON.stringify(!document.querySelector("#newer").hidden)', timeout=12, what='the strip that says there is a new build')
        self.kept_is(changed, 'the worker to keep the new build')
        self.assertEqual(self.browser.eval(BUILD), 'מעבר לנושא', 'the page was loaded again by itself')
        # 3. one press loads the new build, where he was
        self.browser.eval('(()=>{window.__old=1;return "ok";})()')
        self.browser.click('#newer')
        self.browser.wait('JSON.stringify(typeof window.__old==="undefined"&&document.readyState==="complete"&&typeof synced!=="undefined"&&synced)', timeout=20, what='the new build loaded')
        self.assertEqual(self.browser.eval(BUILD), 'מעבר לנושא ')
        self.assertEqual(self.browser.eval('JSON.stringify([location.hash,document.querySelector("#newer").hidden])'), ['#' + self.TID, True])
        # put back: the worker keeps the board's own page again for the scenarios that follow
        page.write_text(original, encoding='utf-8')
        self.browser.eval('(async()=>{await fetch(location.pathname,{cache:"no-store"});return "ok";})()')
        self.kept_is(original, 'the worker to keep the board\'s own page again')

    def test_coming_back_opens_the_line_again_and_never_loads_the_page_again(self):
        self.topic()
        self.open_thread(SIZES[0], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(synced&&online&&!thread(%s).partial&&document.querySelectorAll("#log .msg").length>=12)' % json.dumps(self.TID), timeout=20, what='the thread, connected')
        rows = self.browser.eval('JSON.stringify(document.querySelectorAll("#log .msg").length)')
        # what is his on the page: the page itself, the rows he sees, the words he is typing
        self.browser.fill('#input', 'מילים שהוא באמצע לכתוב')
        self.browser.eval('(()=>{window.__page=1;for(const row of document.querySelectorAll("#log .msg"))row.__kept=1;return "ok";})()')
        # the screen goes off: the page is hidden, and the browser drops the line to the server for good
        self.browser.eval('(()=>{window.__vis="hidden";Object.defineProperty(document,"visibilityState",{get:()=>window.__vis,configurable:true});'
                          'Object.defineProperty(document,"hidden",{get:()=>window.__vis==="hidden",configurable:true});'
                          'document.dispatchEvent(new Event("visibilitychange"));events.close();connection(false);return "ok";})()')
        self.assertEqual(self.browser.eval('JSON.stringify([events.readyState,online])'), [2, False])
        # meanwhile something is written
        self.ok('say', self.TID, '--from', 'fork', 'הודעה שנכתבה כשהמסך היה כבוי', '--state', 'working', '--note', 'בודקים')
        time.sleep(1)
        self.assertFalse(self.browser.eval('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה שנכתבה כשהמסך היה כבוי"))'), 'a closed line still brought the message')
        # the screen comes back on
        self.browser.eval('(()=>{window.__vis="visible";document.dispatchEvent(new Event("visibilitychange"));return "ok";})()')
        self.browser.wait('JSON.stringify(online&&events.readyState===1&&document.querySelector("#log").innerText.includes("הודעה שנכתבה כשהמסך היה כבוי"))', timeout=20,
                          what='the line open again and the message he missed')
        after = self.browser.eval('JSON.stringify({page:window.__page||0,kept:[...document.querySelectorAll("#log .msg")].filter(row=>row.__kept).length,rows:document.querySelectorAll("#log .msg").length,'
                                  'typed:document.querySelector("#input").value,title:document.querySelector("#h-title").textContent})')
        self.assertEqual(after, {'page': 1, 'kept': rows, 'rows': rows + 1, 'typed': 'מילים שהוא באמצע לכתוב', 'title': self.TITLE})
        # the same when the browser brings the page back from its own store of pages
        self.browser.eval('(()=>{events.close();connection(false);window.dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}));return "ok";})()')
        self.browser.wait('JSON.stringify(online&&events.readyState===1)', timeout=20, what='the line open again after the page came back from the browser\'s store')
        self.assertEqual(self.browser.eval('JSON.stringify(window.__page||0)'), 1)
        self.browser.fill('#input', '')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Shell.__dict__:
        setattr(Shell, _name, None)


if __name__ == '__main__':
    unittest.main()
