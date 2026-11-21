#!/usr/bin/env python3
"""Hostile review of "mark all as read" on a section (m490). Every test asserts the CORRECT outcome: a FAIL is a hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

TOAST_UNDO = ('(()=>{const bs=[...document.querySelectorAll(".toast button")].filter(b=>b.textContent.includes("בטל"));'
              'if(!bs.length)return "none";bs[%d].click();return "ok";})()')


class AdvRA(test_e2e.Suda):
    def report(self, tid, title):
        if tid not in self.state()['threads']:
            self.ok('new', tid, title, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            self.ok('say', tid, '--from', 'fork', 'דוח ' + tid)

    def working(self, tid, title):
        if tid not in self.state()['threads']:
            self.ok('new', tid, title, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            self.ok('say', tid, '--from', 'fork', 'התקדמות ' + tid, '--state', 'working', '--note', 'בונה', '--by', 'e2e')

    def page(self, ids, size=SIZES[2]):
        self.open(size)
        self.browser.wait('JSON.stringify(synced&&!!document.querySelector(".sec-h"))', what='the list')
        self.browser.eval('(()=>{for(const id of %s)localStorage.setItem(PREFIX+"seen:"+id,"0");render();return "ok";})()' % list(ids))
        self.browser.wait('JSON.stringify(%s.every(id=>thread(id)&&unreadOf(thread(id))>0))' % list(ids), what='unread')

    # 1. A new report that lands inside the 5 s is dismissed and told "seen" although he never saw it.
    def test_1_new_message_inside_window_is_not_dismissed(self):
        tid = 'e2e-adv-ra-rep1'
        self.report(tid, 'דוח ראשון')
        self.working('e2e-adv-ra-other1', 'נושא אחר פתוח')
        self.page([tid])
        # (another thread is the one on his screen: the report is not read by being on the screen)
        self.browser.eval('(()=>{openChannel("e2e-adv-ra-other1");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-adv-ra-other1")', what='another thread open')
        n = self.browser.eval('thread("%s").messages.length' % tid)
        self.browser.eval('(()=>{READ_ALL_MS=4000;document.querySelector(".sec-on-owner .sec-read").click();return "ok";})()')
        self.ok('say', tid, '--from', 'fork', 'דוח שני שלא ראה')
        self.browser.wait('JSON.stringify(thread("%s").messages.length>%d)' % (tid, n), what='the new message on the page')
        newest = self.thread(tid)['messages'][-1]['id']
        time.sleep(5.5)
        t = self.thread(tid)
        self.assertEqual(t['state'], 'on-owner', 'a report he never saw was dismissed by read-all')
        self.assertNotEqual((t.get('seen') or {}).get('msg'), newest, 'the server was told an unseen message was seen')

    # 2. Page in the background when the timer fires: tellSeen returns, nothing retries for threads not open.
    def test_2_hidden_at_fire_time_server_still_hears(self):
        tid = 'e2e-adv-ra-w2'
        self.working(tid, 'בעבודה רקע')
        self.page([tid])
        self.browser.eval('(()=>{READ_ALL_MS=1200;document.querySelector(".sec-working .sec-read").click();'
                          'Object.defineProperty(document,"hidden",{get:()=>true,configurable:true});'
                          'document.dispatchEvent(new Event("visibilitychange"));return "ok";})()')
        time.sleep(2.5)
        self.browser.eval('(()=>{delete document.hidden;document.dispatchEvent(new Event("visibilitychange"));return String(document.hidden);})()')
        self.until(lambda: (self.thread(tid).get('seen') or {}).get('msg'), timeout=10,
                   what='the server told it was seen after he came back')

    # 3. Second press on "on him" (the button stays while a report waits), then undo the first: the second timer
    # still dismisses on the server while the page shows it unread again.
    def test_3_undo_after_double_press_leaves_page_and_server_agreeing(self):
        tid = 'e2e-adv-ra-rep3'
        self.report(tid, 'דוח לחיצה כפולה')
        self.page([tid])
        self.browser.eval('(()=>{READ_ALL_MS=3000;document.querySelector(".sec-on-owner .sec-read").click();return "ok";})()')
        still = self.browser.eval('JSON.stringify(!!document.querySelector(".sec-on-owner .sec-read"))')
        if not still:
            self.skipTest('button gone after the first press')
        self.browser.eval('(()=>{document.querySelector(".sec-on-owner .sec-read").click();return "ok";})()')
        self.assertEqual(self.browser.eval(TOAST_UNDO % 0), 'ok')
        time.sleep(4.5)
        unread = self.browser.eval('unreadOf(thread("%s"))' % tid)
        state = self.thread(tid)['state']
        self.assertEqual(state, 'on-owner', 'he pressed undo and the report was still dismissed (unread=%s)' % unread)

    # 4. He opens a thread of the section inside the window, then presses undo: the thread he read is unread again.
    def test_4_undo_does_not_unread_a_thread_opened_meanwhile(self):
        a, b = 'e2e-adv-ra-w4a', 'e2e-adv-ra-w4b'
        self.working(a, 'בעבודה 4א')
        self.working(b, 'בעבודה 4ב')
        self.page([a, b])
        self.browser.eval('(()=>{READ_ALL_MS=60000;document.querySelector(".sec-working .sec-read").click();openChannel("%s");return "ok";})()' % a)
        self.browser.wait('JSON.stringify(view.ch==="%s")' % a, what='the thread open')
        self.assertEqual(self.browser.eval(TOAST_UNDO % 0), 'ok')
        self.assertEqual(self.browser.eval('unreadOf(thread("%s"))' % a), 0, 'the thread he opened and read is unread again after undo')

    # 5. Keyboard: focus on the button is lost at every render (focus restore knows only [data-id] and .sec-toggle).
    def test_5_focus_on_read_button_survives_render(self):
        tid = 'e2e-adv-ra-w5'
        self.working(tid, 'בעבודה מקלדת')
        self.page([tid])
        got = self.browser.eval('(()=>{document.querySelector(".sec-working .sec-read").focus();render();'
                                'const a=document.activeElement;return JSON.stringify(!!a&&a.classList.contains("sec-read"));})()')
        self.assertTrue(got, 'keyboard focus on "mark all as read" is dropped by an update')

    # 6. Phone 360: the touch button must not overlap the count or push the head out of the row.
    def test_6_phone_head_layout(self):
        tid = 'e2e-adv-ra-w6'
        self.working(tid, 'בעבודה טלפון')
        self.page([tid], SIZES[0])
        geo = self.browser.eval('(()=>{document.documentElement.classList.add("touch");'
                                'const h=document.querySelector(".sec-working .sec-h"),b=h.querySelector(".sec-read"),c=h.querySelector(".sec-count");'
                                'const R=e=>e.getBoundingClientRect();const rb=R(b),rc=R(c),rh=R(h);'
                                'return JSON.stringify({w:rb.width,h:rb.height,overlap:!(rb.right<=rc.left||rb.left>=rc.right),'
                                'inside:rb.left>=rh.left-1&&rb.right<=rh.right+1,headW:rh.width,vw:innerWidth});})()')
        self.assertGreaterEqual(min(geo['w'], geo['h']), 40, geo)
        self.assertFalse(geo['overlap'], geo)
        self.assertTrue(geo['inside'], geo)


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvRA.__dict__:
        setattr(AdvRA, _name, None)


if __name__ == '__main__':
    unittest.main()
