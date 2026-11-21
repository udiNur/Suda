#!/usr/bin/env python3
"""End to end: his place in a thread follows him to another device, in Suda (the owner, thread suda m240).

"Sync his place (the last position he was at) in every chat across devices." The same harness as test_e2e.py:
headless Chrome, the real board server on loopback, the CLI behind its hook, a temporary board; and a second
browser with its own profile, which is another device. What is checked:

  - device A reads up to the middle of a thread: the server holds that place (places.json), not the state;
  - device B, already looking at the thread's end, is taken to A's place at the next change of the board;
  - A goes back to the end: B follows to the end;
  - B opened afresh, with nothing unread, lands where A stands; with something unread it lands on the "new" line;
  - a thread read on A is read on B: the mark in B's list goes.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest

import test_e2e
from test_e2e import SIZES, Browser


class Place(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-suda-place'
    TITLE = 'המקום שלי ב-Suda'
    PLACE = 'JSON.stringify(placeNow())'

    def pulse(self, text='משהו קורה בנושא אחר'):
        self.ok('say', 'e2e-suda-other', '--from', 'fork', text, '--state', 'working', '--note', 'בודקים')

    def place_on_server(self):
        path = self.board / 'places.json'
        return (json.loads(path.read_text(encoding='utf-8')).get('places') or {}).get(self.TID) if path.is_file() else None

    def visit(self, browser, size, tid, rows=20):
        name, w, h = size
        browser.viewport(w, h)
        test_e2e.Suda.visits += 1
        browser.open(self.url + '?s=%s&n=%d#%s' % (name, test_e2e.Suda.visits, tid))
        browser.wait('JSON.stringify(document.readyState==="complete"&&typeof has==="function"&&has("place")&&document.querySelectorAll("#log .msg").length>=%d)' % rows,
                     timeout=20, what='the thread on the device')

    def test_his_place_in_a_thread_follows_him_to_another_device(self):
        self.needs('place')
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', 'e2e-suda-other', 'נושא אחר', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 31):
            self.ok('say', self.TID, '--from', 'fork', '-', '--state', 'working', '--note', 'שורה', '--by', 'fork', input='הודעה מספר %d\n\n' % n + 'שורה נוספת\n\n' * 3)
        other = Browser('threads-e2e-suda-other-%d' % os.getpid())      # a second device: its own profile, its own local marks
        try:
            other.launch()
        except Exception as e:
            self.skipTest('a second browser could not open: ' + str(e)[:120])
        try:
            a, b = self.browser, other
            self.visit(a, SIZES[0], self.TID)
            self.visit(b, SIZES[2], self.TID)
            # both stand at the end, and say so
            self.until(lambda: (self.place_on_server() or {}).get('bottom') is True, what='the place at the end on the server')
            state_before = (self.board / 'state.json').stat().st_mtime_ns

            # 1. A reads up to the middle and stops there: the server holds the place, beside the state
            a.eval('(()=>{const s=document.querySelector("#scroll"),row=[...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid==="m12");'
                   's.scrollTop+=row.getBoundingClientRect().top-s.getBoundingClientRect().top;return "ok";})()')
            place = self.until(lambda: (lambda p: p if p and p.get('at') == 'm12' else None)(self.place_on_server()), what='A\'s place on the server')
            self.assertFalse(place['bottom'])
            self.assertEqual((self.board / 'state.json').stat().st_mtime_ns, state_before, 'a scroll rewrote the state')

            # 2. B, looking at the end, is taken to A's place at the next change of the board
            self.pulse()
            b.wait('JSON.stringify(placeNow().at==="m12"&&Math.abs(placeNow().off)<=3)', timeout=20, what='B at message 12, where A stands')
            # being taken there is not B's own scroll: B tells the server nothing, so the two devices never chase each other
            time.sleep(3.5)
            self.assertEqual(self.place_on_server()['ts'], place['ts'], 'B told the server a place it did not choose')

            # 3. A goes back to the end: B follows
            a.eval('(()=>{document.querySelector("#scroll").scrollTop=1e9;return "ok";})()')
            self.until(lambda: (self.place_on_server() or {}).get('bottom') is True, what='A\'s place at the end on the server')
            self.pulse('ועוד משהו')
            b.wait('JSON.stringify(placeNow().bottom===true)', timeout=20, what='B at the end, after A')

            # 4. A stops at message 20; B opened afresh, with nothing unread, lands there
            a.eval('(()=>{const s=document.querySelector("#scroll"),row=[...document.querySelectorAll("#log .msg")].find(n=>n.dataset.mid==="m20");'
                   's.scrollTop+=row.getBoundingClientRect().top-s.getBoundingClientRect().top;return "ok";})()')
            self.until(lambda: (lambda p: p if p and p.get('at') == 'm20' else None)(self.place_on_server()), what='A at message 20 on the server')
            self.visit(b, SIZES[2], self.TID)
            b.wait('JSON.stringify(placeNow().at==="m20"&&Math.abs(placeNow().off)<=3)', timeout=20, what='B opened afresh at message 20')

            # 5. a thread read on A is read on B: B looks at another thread, a message arrives, A (at the end) reads it
            self.visit(b, SIZES[2], 'e2e-suda-other', rows=1)
            a.eval('(()=>{document.querySelector("#scroll").scrollTop=1e9;return "ok";})()')
            self.ok('say', self.TID, '--from', 'fork', 'הודעה חדשה שנקראת רק במכשיר א', '--state', 'working', '--note', 'שורה')
            a.wait('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה חדשה שנקראת רק במכשיר א"))', what='the new message on A')
            self.until(lambda: self.thread(self.TID)['seen']['msg'] == 'm31', what='the server to hear that he saw it')
            b.wait('JSON.stringify(unreadOf(thread(%s))===0&&!document.querySelector(\'.ch[data-id="%s"].unread\'))' % (json.dumps(self.TID), self.TID),
                   timeout=20, what='the thread read on B too')
        finally:
            other.close()


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Place.__dict__:
        setattr(Place, _name, None)


if __name__ == '__main__':
    unittest.main()
