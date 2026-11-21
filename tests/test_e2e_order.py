#!/usr/bin/env python3
"""End to end: the order of a conversation with two devices on a weak link (suda-fixes 28).

The phone and the desktop are in the same thread; both lines are down (each page hears nothing) while agents
write and he answers from both. When the lines are back, each page must show the conversation in the server's
order, and at no moment may two messages the server numbered stand on the screen in another order. (His own
reply, while the server has not confirmed it, is drawn at the end: it has no number yet. A message the server
numbered before it then arrives above it: that is its place.)

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_e2e_order.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
import test_e2e_resume
from test_e2e import SIZES
from test_e2e_resume import FREE_LINE, HOLD_LINE

# Every order of numbered rows the log showed, as the page drew them.
WATCH_ORDER = r"""(()=>{
  window.__orders=[];
  const note=()=>{const ids=[...document.querySelectorAll('#log .msg[data-mid]')].map(r=>r.dataset.mid).filter(Boolean);
    const last=window.__orders.at(-1);if(!last||last.join()!==ids.join())window.__orders.push(ids);};
  note();new MutationObserver(note).observe(document.querySelector('#log'),{childList:true,subtree:true,attributes:true,attributeFilter:['data-mid']});
  return 'ok';
})()"""
ORDERS = 'JSON.stringify(window.__orders||[])'
SHOWN = "JSON.stringify([...document.querySelectorAll('#log .msg')].map(r=>r.dataset.mid||'').filter(Boolean))"
PENDING = 'JSON.stringify([...optimistic.values()].flat().filter(m=>m.delivery!=="received").length)'


class Order(test_e2e_resume.Resume):
    TID = 'e2e-order'
    TITLE = 'סדר עם שני מכשירים'

    def server_order(self):
        return [m['id'] for m in self.thread(self.TID)['messages']]

    def assertInServerOrder(self, browser, what):
        order = self.server_order()
        place = {mid: i for i, mid in enumerate(order)}
        for ids in browser.eval(ORDERS):
            at = [place[mid] for mid in ids if mid in place]
            self.assertEqual(at, sorted(at), '%s: the log once stood in another order than the server\'s: %s (server %s)' % (what, ids, order))
        shown = browser.eval(SHOWN)
        self.assertEqual(shown, [mid for mid in order if mid in shown], what)
        self.assertEqual(shown[-6:], order[-6:], '%s: the end of the conversation is not the server\'s' % what)

    def test_two_devices_on_a_weak_link_end_in_the_servers_order(self):
        other = test_e2e.Browser('threads-e2e-order2-%d' % id(self))
        try:
            other.launch()
        except Exception as e:
            self.skipTest('a second browser could not open: ' + str(e)[:200])
        self.addCleanup(other.close)
        self.open_board()
        self.open_board(SIZES[0], other)
        for page in (self.browser, other):
            page.eval(WATCH_ORDER)
            page.eval(HOLD_LINE)
        stamp = int(time.time())
        self.say('סוכן אחד %d' % stamp)
        self.browser.fill('#input', 'תשובה מהמחשב %d' % stamp)
        self.browser.click('#send')
        self.say('סוכן שניים %d' % stamp)
        other.fill('#input', 'תשובה מהטלפון %d' % stamp)
        other.click('#send')
        self.say('סוכן שלוש %d' % stamp)
        self.until(lambda: sum(str(stamp) in m['text'] for m in self.thread(self.TID)['messages']) >= 5, timeout=30,
                   what='both replies and the three agent messages on the server')
        for page in (self.browser, other):
            page.eval(FREE_LINE)
        for page, what in ((self.browser, 'the desktop'), (other, 'the phone')):
            self.up_to_date(page)
            page.wait(PENDING.replace('JSON.stringify(', 'JSON.stringify(0===', 1), timeout=20, what='no reply left unconfirmed on ' + what)
            self.assertInServerOrder(page, what)


    def test_a_reply_stuck_on_a_dropped_connection_goes_again_when_the_line_is_back(self):
        """A silent drop: the reply's request left on a connection the network dropped, and no answer comes (the
        browser would wait a long time). When the line is back, it goes again at once on a fresh connection, by its
        cid: on the server once, within a few seconds of the line."""
        self.open_board()
        self.browser.eval(HOLD_LINE)
        self.browser.eval(r"""(()=>{const real=window.fetch.bind(window);window.__realFetch=real;
          window.fetch=(url,opts)=>String(url).includes('/api/state')&&opts&&opts.method==='POST'
            ?new Promise((_,fail)=>{const s=opts.signal;if(s)s.addEventListener('abort',()=>fail(new DOMException('aborted','AbortError')));})
            :real(url,opts);return 'ok';})()""")
        text = 'תקועה על חיבור שנפל %d' % time.time()
        self.browser.fill('#input', text)
        self.browser.click('#send')
        time.sleep(2)
        self.assertEqual([m['text'] for m in self.thread(self.TID)['messages']].count(text), 0)
        # the network is back: new connections work (the stuck one never answers)
        self.browser.eval('(()=>{window.fetch=window.__realFetch;return "ok";})()')
        back = time.monotonic()
        self.browser.eval(FREE_LINE)
        self.until(lambda: any(m['text'] == text for m in self.thread(self.TID)['messages']), timeout=20, what='the reply on the server')
        self.assertLess(time.monotonic() - back, 5, 'the reply waited on the dropped connection')
        time.sleep(2)
        self.assertEqual([m['text'] for m in self.thread(self.TID)['messages']].count(text), 1)
        self.up_to_date()

    def test_a_silent_line_is_opened_again_within_the_beat(self):
        """The server speaks every 10 s. A line that says nothing for 15 s (dead without knowing it) is opened again
        then, not after 25 s or more."""
        self.open_board()
        self.browser.eval('(()=>{window.__lines=0;const Real=window.EventSource;window.EventSource=function(u){window.__lines++;return new Real(u);};'
                          'window.__onNumber=onNumber;onNumber=()=>{};return "ok";})()')
        quiet = time.monotonic()
        self.browser.wait('JSON.stringify(window.__lines>=1)', timeout=25, what='a new line')
        took = time.monotonic() - quiet
        self.browser.eval('(()=>{onNumber=window.__onNumber;return "ok";})()')
        self.assertLess(took, 19, 'a silent line was kept %.1f s' % took)
        self.up_to_date()


for _name in dir(test_e2e_resume.Resume):
    if _name.startswith('test') and _name not in Order.__dict__:
        setattr(Order, _name, None)


if __name__ == '__main__':
    unittest.main()
