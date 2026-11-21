#!/usr/bin/env python3
"""End to end, with a slow server: how long until he sees the conversation (the owner, thread suda m313).

"Every opening of Suda's screen sometimes takes a few seconds to update." On his phone every answer of the
server costs a connection through the gateway (0.1 to 1.8 seconds were measured). Here the board server of
test_e2e.py is made slow in the same way: every read waits before it is answered. What is checked, and printed
as numbers (milliseconds since the opening began):

  - a first opening on a device that kept nothing waits for the server, as it must;
  - the next opening shows the page and the conversation long before the server answers: the page comes from
    the worker, the conversation from what the device kept; the server's answer then comes in on top.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import sys
import time
import unittest

import test_e2e
from test_e2e import SIZES

WAIT = 0.7          # seconds the server takes for every read
TIMES = ('(()=>{const nav=performance.getEntriesByType("navigation")[0],mark=n=>{const e=performance.getEntriesByName(n)[0];return e?Math.round(e.startTime):null;};'
         'return JSON.stringify({page:Math.round(nav.responseEnd),worker:nav.workerStart>0,thread:mark("suda:thread"),server:mark("suda:synced"),rows:document.querySelectorAll("#log .msg").length});})()')


class Speed(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-speed'
    TITLE = 'שיחה מול שרת איטי'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Slow(base):
            wait = 0.0

            def do_GET(self):
                if Slow.wait and not self.path.startswith('/events'):
                    time.sleep(Slow.wait)
                super().do_GET()

            def do_HEAD(self):
                if Slow.wait:
                    time.sleep(Slow.wait)
                super().do_HEAD()
        cls.slow = Slow
        cls.server.RequestHandlerClass = Slow

    def opening(self):
        self.browser.open('about:blank')
        self.open(SIZES[0], self.TID)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!thread(%s)&&!thread(%s).partial&&document.querySelectorAll("#log .msg").length>=40)' % (json.dumps(self.TID), json.dumps(self.TID)),
                          timeout=30, what='the conversation and the server\'s answer')
        return self.browser.eval(TIMES)

    def test_with_a_slow_server_the_conversation_is_on_the_screen_long_before_the_server_answers(self):
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 41):
            self.ok('say', self.TID, '--from', 'fork', 'הודעה מספר %d\n\nשורה נוספת' % n, '--state', 'working', '--note', 'בודקים')
        self.addCleanup(setattr, self.slow, 'wait', 0.0)
        # 1. a device that kept nothing, a slow server: everything waits for it
        self.slow.wait = WAIT
        cold = self.opening()
        self.assertFalse(cold['worker'])
        self.assertGreaterEqual(cold['thread'], WAIT * 2000 - 100, cold)             # the page, then the state: two answers of the server at least
        # the device now keeps the page (the worker), the state and the conversation
        self.browser.wait('(async()=>{if(!("serviceWorker" in navigator))return "true";await navigator.serviceWorker.ready;const rev=thread(%s).rev,s=await keptStore.get("summary"),f=await keptStore.get("full:%s"),'
                          'page=await (await caches.open("suda-shell-1")).match(location.pathname);return JSON.stringify(!!page&&!!s&&s.threads[%s].rev===rev&&!!f&&f.rev===rev);})()'
                          % (json.dumps(self.TID), self.TID, json.dumps(self.TID)), timeout=30, what='the device to keep the page, the state and the conversation')
        if not self.browser.eval('JSON.stringify("serviceWorker" in navigator&&window.isSecureContext)'):
            self.skipTest('this browser allows no worker on a loopback page')
        # 2. the next openings: the conversation is there at once, the server answers later
        warm = [self.opening() for _ in range(3)]
        print('\nslow server (%d ms for every read), ms since the opening began:' % int(WAIT * 1000), file=sys.stderr)
        print('  nothing kept on the device : page %(page)d, conversation %(thread)d, server answered %(server)d' % cold, file=sys.stderr)
        for w in warm:
            print('  page and state kept        : page %(page)d, conversation %(thread)d, server answered %(server)d' % w, file=sys.stderr)
        for w in warm:
            self.assertTrue(w['worker'], w)
            self.assertLess(w['page'], 300, w)                    # the page did not wait for the server
            self.assertLess(w['thread'], 500, w)                  # nor did the conversation
            self.assertGreaterEqual(w['server'], WAIT * 1000 - 100, w)
            self.assertLess(w['thread'] * 2, w['server'], w)
            self.assertEqual(w['rows'], cold['rows'])


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Speed.__dict__:
        setattr(Speed, _name, None)


if __name__ == '__main__':
    unittest.main()
