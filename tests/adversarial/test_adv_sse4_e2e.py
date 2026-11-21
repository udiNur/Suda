#!/usr/bin/env python3
"""Hostile review of sse153, fourth pass (probeDue/probeLink, the cuttable fetch, cutStuck, QUIET_POSTS), end to end.
The board server is the in-process one of the harness: a test slows or fails its answers by wrapping its handler
(never the real server). Each test asserts the SAFE outcome: a failure is a real hole.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_adv_sse4_e2e.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e_resume
from test_e2e_resume import HOLD_LINE, FREE_LINE

DROP_LINE = '(()=>{try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()'
# POSTs of these ops: they reach the server only `ms` later (a dropped link); the page's own abort stops them first.
STUCK_POST = r"""((ops,ms)=>{
  const real=window.__realFetch||(window.__realFetch=window.fetch.bind(window));window.__posts=[];
  window.fetch=(url,opts)=>{
    let op='';try{op=JSON.parse(opts&&opts.body||'{}').state.op;}catch{}
    if(String(url).includes('/api/state')&&ops.includes(op)){
      const rec={op,t:Date.now(),cut:false};window.__posts.push(rec);
      return new Promise((done,fail)=>{const t=setTimeout(()=>real(url,opts).then(done,fail),ms);
        if(opts&&opts.signal)opts.signal.addEventListener('abort',()=>{rec.cut=true;clearTimeout(t);fail(new DOMException('aborted','AbortError'));});});
    }
    return real(url,opts);};
  return 'ok';})(%s,%d)"""
REAL_FETCH = '(()=>{if(window.__realFetch)window.fetch=window.__realFetch;return "ok";})()'


class Page(test_e2e_resume.Resume):
    TID = 'adv-sse4'
    TITLE = 'בדיקה עוינת רביעית'

    def setUp(self):
        super().setUp()
        self.net = {'events': 0, 'reads': 0, 'down': False}
        self.hits = {'events': 0, 'probe': 0, 'post': 0}
        H = self.server.RequestHandlerClass
        get, post = H.do_GET, H.do_POST
        net, hits = self.net, self.hits

        def do_GET(h):
            path = h.path
            if '/events' in path:
                hits['events'] += 1
            if 'probe=' in path:
                hits['probe'] += 1
            if net['down'] and not path.split('?')[0].endswith(('.html', '.js', '.css', '.ico', '.png', '.svg', '.webmanifest')):
                h.send_error(502)               # the gateway answers; the board server behind it is down
                return
            if '/events' in path and net['events']:
                time.sleep(net['events'])        # opening the line takes this long (TCP, TLS, the first bytes)
            elif ('summary.json' in path or '/changes' in path) and 'probe=' not in path and net['reads']:
                time.sleep(net['reads'])
            return get(h)

        def do_POST(h):
            hits['post'] += 1
            if net['down']:
                h.send_error(502)
                return
            return post(h)
        H.do_GET, H.do_POST = do_GET, do_POST
        self.addCleanup(setattr, H, 'do_GET', get)
        self.addCleanup(setattr, H, 'do_POST', post)

    def test_a_line_slower_to_open_than_a_probe_opens_and_the_board_arrives(self):
        """A weak link: a new connection (the line) takes 5 s to give its first bytes, a request on a kept-alive one
        about none, a summary or change file 3.5 s. The probe gets its answer every 3 s and closes the line that is
        still connecting (lineFails back to 0, so its own backoff never grows); every tick while the line is down cuts
        reads older than 3 s, so no reading of the board ends."""
        self.open_board()
        self.net.update(events=5, reads=3.5)
        self.browser.eval('(()=>{window.__t0=Date.now();window.__conn=[];window.__reads=[];const c=connection;connection=up=>{window.__conn.push([up,Date.now()-window.__t0]);return c(up);};'
                          'const r=readState;readState=async()=>{const a=Date.now()-window.__t0,was=readsOk;await r();window.__reads.push([a,Date.now()-window.__t0,readsOk>was]);};return "ok";})()')
        self.browser.eval(DROP_LINE)
        self.say('נשמר כשהקו נפל')
        board = self.seq()
        time.sleep(45)
        got = self.browser.eval('JSON.stringify({open:linkOpen,applied:appliedNumber,fresh:live.dataset.fresh})')
        got.update(board=board, events=self.hits['events'], probes=self.hits['probe'],
                   ups=[c for c in self.browser.eval('JSON.stringify(window.__conn)') if c[0]],
                   reads=self.browser.eval('JSON.stringify(window.__reads)'))
        self.net.update(events=0, reads=0)
        self.assertTrue(got['open'] and got['applied'] >= board,
                        'after 45 s on a link that works (slowly), no line and the board not on the screen: %s' % got)

    def test_with_the_line_down_a_slow_reading_still_ends(self):
        """The line cannot open (held), the link works but slowly: every file of the board takes 5 s. Before this
        change the 20 s reading of a page without a line got through in 5 s. Now every tick while the line is down cuts
        reads older than 3 s: no reading can end, and the board never reaches the screen."""
        self.open_board()
        self.addCleanup(self.browser.eval, FREE_LINE)
        self.browser.eval(HOLD_LINE)
        self.net['reads'] = 5
        self.say('נשמר כשהקו לא נפתח')
        board = self.seq()
        time.sleep(45)
        got = self.browser.eval('JSON.stringify({applied:appliedNumber,notice:noticeText})')
        self.net['reads'] = 0
        self.assertGreaterEqual(got['applied'], board, 'a link that works, 5 s a file, and in 45 s no reading ended: %s' % got)

    def test_a_reply_waiting_through_a_server_restart_behind_the_gateway_is_not_given_up(self):
        """The board server restarts (30 s) behind the gateway, which answers 502 at once. The probe takes any answer
        for "the link is back": every 3 s lineBack, sendAgain(true), and the waiting reply goes again regardless of
        its due time; each 502 counts as "heard", and after RETRY_HEARD of them the reply is marked failed (his to
        send again), in under half a minute."""
        self.open_board()
        self.net['down'] = True
        self.browser.eval(DROP_LINE)
        time.sleep(1)
        text = 'תשובה בזמן אתחול השרת %d' % time.time()
        self.browser.fill('#input', text)
        self.browser.click('#send')
        time.sleep(30)
        got = self.browser.eval('JSON.stringify([...optimistic.values()].flat().filter(m=>m.text===%s).map(m=>({d:m.delivery,heard:m.heard,tries:m.tries,error:m.error||""})))' % json.dumps(text))
        hits = dict(self.hits)
        self.net['down'] = False
        self.assertFalse([m for m in got if m['d'] == 'failed'],
                         'a 30 s restart behind the gateway gave up on his reply: %s (line attempts %d, posts %d)' % (got, hits['events'], hits['post']))
        self.until(lambda: [m['text'] for m in self.thread(self.TID)['messages']].count(text) == 1, timeout=30, what='the reply after the restart')

    def test_a_draft_cut_while_the_line_is_down_reaches_the_server_when_it_is_back(self):
        """He types; a second later the draft is posted, and the link has dropped: the post is stuck. Every tick while
        the line is down cuts it after 3 s (a quiet post). Nothing posts it again: not the line's return, not a
        reading. His other devices never get the draft (until he types again, opens a thread or leaves the tab)."""
        self.open_board()
        self.addCleanup(self.browser.eval, REAL_FETCH)
        self.addCleanup(self.browser.eval, FREE_LINE)
        self.browser.eval(STUCK_POST % (json.dumps(['draft']), 60000))
        self.browser.eval(HOLD_LINE)
        text = 'טיוטה בקו שנפל %d' % time.time()
        self.browser.fill('#input', text)
        time.sleep(6)
        posts = self.browser.eval('JSON.stringify(window.__posts)')
        self.browser.eval(REAL_FETCH)
        self.browser.eval(FREE_LINE)
        time.sleep(10)
        drafts = (self.board / 'drafts.json').read_text(encoding='utf-8') if (self.board / 'drafts.json').exists() else ''
        self.assertIn(text, drafts, 'the draft was cut (%s) and never reached the server after the line came back' % posts)

    def test_an_idle_good_link_sends_no_probe(self):
        self.open_board()
        time.sleep(2)
        before = dict(self.hits)
        time.sleep(30)
        self.assertEqual((self.hits['probe'] - before['probe'], self.hits['events'] - before['events']), (0, 0))


for _name in dir(test_e2e_resume.Resume):
    if _name.startswith('test') and _name not in Page.__dict__:
        setattr(Page, _name, None)


if __name__ == '__main__':
    unittest.main()
