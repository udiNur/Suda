#!/usr/bin/env python3
"""Hostile review of sse153, second pass, end to end (the harness of test_e2e_resume: headless Chrome, the board
server on loopback, a temporary board). Each test asserts the SAFE outcome: a failure is a real hole.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_adv_sse2_e2e.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import test_e2e
import test_e2e_resume
from test_e2e_resume import ASKED, CLEAR

ROOT = _paths.APP

# The line dies without knowing it (a phone asleep, its socket gone): no word reaches the page any more.
MUTE = '(()=>{window.__onNumber=onNumber;onNumber=()=>{};events.onmessage=null;return "ok";})()'
UNMUTE = '(()=>{onNumber=window.__onNumber;try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()'
HIDE = r"""(()=>{
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>!!window.__hidden});
  Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__hidden?'hidden':'visible'});
  window.__hidden=true;document.dispatchEvent(new Event('visibilitychange'));return 'ok';})()"""
SHOW = '(()=>{window.__hidden=false;document.dispatchEvent(new Event("visibilitychange"));return "ok";})()'
# The browser froze the page in its back-forward cache: the EventSource is closed with no error, and the next one
# does not open yet (a link that comes back slowly).
FREEZE = r"""(()=>{
  if(!window.__realES)window.__realES=window.EventSource;
  try{events.close();}catch{}
  window.EventSource=function(){const fake={readyState:0,close(){fake.readyState=2;},addEventListener(){}};return fake;};
  return 'ok';})()"""
THAW = '(()=>{dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}));return "ok";})()'
FREE = '(()=>{window.EventSource=window.__realES;try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()'
NOW = 'JSON.stringify({fresh:live.dataset.fresh,applied:appliedNumber,heard,ago:Date.now()-heardAt})'


class Page(test_e2e_resume.Resume):
    TID = 'adv-sse2'
    TITLE = 'בדיקה עוינת שנייה'

    def old_writer(self):
        old = Path(self.tmp.name) / 'old_threads.py'
        if not old.exists():
            old.write_text(subprocess.run(['git', '-C', str(ROOT), 'show', '60586da:threads.py'], capture_output=True, text=True, check=True).stdout)
        return old

    def old_say(self, text):
        r = subprocess.run([sys.executable, str(self.old_writer()), 'say', self.TID, '--from', 'fork', text], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_back_from_a_short_sleep_the_mark_never_says_fresh_over_a_board_that_moved(self):
        """The phone's screen goes off for a few seconds; its socket dies with it, without an error. A message
        arrives meanwhile. The screen comes back within 25 s of the last word: visibilitychange paints the mark
        first ("the mark first: a tab that slept shows nothing it heard before it slept as up to date"), but the word
        from before the sleep is under 25 s old, so it says "fresh"; and its refresh() takes that old word as its
        goal, so it reads nothing new."""
        self.open_board()
        self.addCleanup(self.browser.eval, UNMUTE)
        self.browser.eval(MUTE)
        self.browser.eval(HIDE)
        self.say('הגיע בזמן שהמסך כבוי')
        board = self.seq()
        time.sleep(1.5)
        self.browser.eval(SHOW)
        seen = []
        for _ in range(8):
            seen.append(self.browser.eval(NOW))
            time.sleep(0.5)
        bad = [s for s in seen if s['fresh'] == 'fresh' and s['applied'] != board]
        self.assertEqual(len(bad), 0, 'back from sleep: "fresh" while the page is at %s and the board at %d: %s' % (bad[0]['applied'] if bad else None, board, bad[:1]))

    def test_a_page_back_from_the_back_forward_cache_never_says_fresh_over_a_board_that_moved(self):
        """He opens a PR link and comes back with the browser's back button within 25 s; a save happened meanwhile.
        pageshow (persisted) paints the mark first: the last word is recent, so "fresh"; the new line is still
        opening (a weak link), and refresh() reads to the old word only."""
        self.open_board()
        self.addCleanup(self.browser.eval, FREE)
        self.browser.eval(FREEZE)
        self.say('הגיע בזמן שהדף היה במטמון')
        board = self.seq()
        time.sleep(1.5)
        self.browser.eval(THAW)
        seen = []
        for _ in range(8):
            seen.append(self.browser.eval(NOW))
            time.sleep(0.5)
        bad = [s for s in seen if s['fresh'] == 'fresh' and s['applied'] != board]
        self.assertEqual(len(bad), 0, 'back from the cache: "fresh" while the page is at %s and the board at %d: %s' % (bad[0]['applied'] if bad else None, board, bad[:1]))

    def test_after_an_unnumbered_write_a_failing_summary_read_never_leaves_fresh(self):
        """An older threads.py writes a message (same number, the pulse touched). The page hears its own number,
        reads the head and then the whole summary, and both fail (a weak link: the 200 KB file times out, the tiny
        "alive" still arrives). The page knows it could not vouch for its screen, yet every "alive" (its own number)
        keeps the mark on "fresh"."""
        self.open_board()
        self.addCleanup(self.say, 'שמירה ממוספרת אחרי הכותב הישן')
        self.addCleanup(self.browser.run, 'network', 'unroute', check=False)
        time.sleep(2)               # what the page itself saves on opening (a "seen") is read first
        self.up_to_date()
        self.browser.run('network', 'route', '**/summary.json*', '--abort')
        text = 'מכותב ישן בקו חלש %d' % time.time()
        self.old_say(text)
        self.browser.wait('JSON.stringify(!!noticeText)', timeout=20, what='the failed reading')
        time.sleep(11)              # at least one "alive" after it
        got = self.browser.eval('JSON.stringify({shown:JSON.stringify(data).includes(%s),fresh:live.dataset.fresh,applied:appliedNumber,heard,notice:noticeText})' % json.dumps(text))
        if os.environ.get('ADV_TRACE'):
            print('GOT', got, flush=True)
        self.assertTrue(got['shown'] or got['fresh'] != 'fresh',
                        'the page could not read the rewritten board and still says "up to date": %s' % got)

    def test_while_an_unnumbered_write_is_being_read_the_mark_is_not_fresh(self):
        """The same write on a slow link: the whole summary takes a few seconds. Meanwhile the screen is the old
        one. Is the mark "fresh" in that window? (onmessage sets heard to the page's own number before reading.)"""
        self.open_board()
        self.addCleanup(self.say, 'שמירה ממוספרת אחרי הכותב הישן')
        text = 'מכותב ישן בקו איטי %d' % time.time()
        self.browser.eval(r"""(()=>{const real=window.fetch.bind(window);window.__realFetch=real;
          window.fetch=(url,opts)=>/summary\.json/.test(String(url))&&!(opts&&opts.headers&&opts.headers.Range)?new Promise(r=>setTimeout(r,6000)).then(()=>real(url,opts)):real(url,opts);
          window.__samples=[];window.__sampler=setInterval(()=>window.__samples.push({t:Date.now(),fresh:live.dataset.fresh,shown:JSON.stringify(data).includes(%s),heardAt}),100);
          return 'ok';})()""" % json.dumps(text))
        self.addCleanup(self.browser.eval, '(()=>{window.fetch=window.__realFetch;clearInterval(window.__sampler);return "ok";})()')
        written = time.time() * 1000
        self.old_say(text)
        self.browser.wait('JSON.stringify(JSON.stringify(data).includes(%s))' % json.dumps(text), timeout=25, what='the old writer\'s message')
        samples = self.browser.eval('JSON.stringify(window.__samples)')
        bad = [s for s in samples if s['t'] > written + 1500 and s['fresh'] == 'fresh' and not s['shown']]
        self.assertEqual(len(bad), 0, '"fresh" for %.1f s while the screen did not show the rewritten board' % (len(bad) / 10))

    def test_touches_of_the_pulse_cost_only_the_head(self):
        """A pull request's state changes: threads.py touches .pulse, no new number. Five of them must cost five
        64-byte heads, never the whole summary or changes.json."""
        self.open_board()
        time.sleep(1.5)
        self.browser.eval(CLEAR)
        for _ in range(5):
            os.utime(self.board / '.pulse')
            time.sleep(1.3)
        time.sleep(1.5)
        asked = self.browser.eval(ASKED)
        self.assertEqual([n for n in asked if n != 'summary.json:head'], [], asked)
        self.assertLessEqual(len(asked), 7, asked)

    def test_a_numbered_and_an_unnumbered_save_in_one_poll_second_end_on_the_board(self):
        self.open_board()
        self.addCleanup(self.say, 'שמירה ממוספרת אחרי הכותב הישן')
        self.old_writer()
        text = 'ישן מיד אחרי ממוספר %d' % time.time()
        self.say('ממוספר רגע לפני')
        self.old_say(text)
        self.browser.wait('JSON.stringify(JSON.stringify(data).includes(%s))' % json.dumps(text), timeout=25, what='the old writer\'s message')
        end = time.monotonic() + 20         # the page's own "seen" may move the board on: it must follow
        while True:
            got = self.browser.eval('JSON.stringify({held:base,fresh:live.dataset.fresh})')
            if got['held'] == self.summary() or time.monotonic() > end:
                break
            time.sleep(0.5)
        self.assertEqual(got['held'], self.summary())


    def test_a_server_without_numbers_after_one_with_them_keeps_its_line(self):
        """The board server is put back to the version without numbers (a rollback, the skill's own copy) while the
        page is open. The page heard numbers before (`numbered` stays true), so the new line is never "legacy": no
        word for 25 s closes and reopens it again and again, and the mark says "not connected" over a line that
        works."""
        self.open_board()
        self.addCleanup(self.browser.eval, FREE)
        self.browser.eval(r"""(()=>{
          if(!window.__realES)window.__realES=window.EventSource;
          window.__lines=0;
          window.EventSource=function(){window.__lines++;const fake={readyState:0,close(){fake.readyState=2;},addEventListener(){}};
            setTimeout(()=>{fake.readyState=1;fake.onopen&&fake.onopen();fake.onmessage&&fake.onmessage({data:'changed',lastEventId:''});},50);return fake;};
          try{events.close();}catch{}events=null;connection(false);listen();return 'ok';})()""")
        time.sleep(33)
        got = self.browser.eval('JSON.stringify({lines:window.__lines,fresh:live.dataset.fresh})')
        self.assertEqual(got, {'lines': 1, 'fresh': 'legacy'}, 'a working line without numbers is torn down and called "not connected"')

for _name in dir(test_e2e_resume.Resume):
    if _name.startswith('test') and _name not in Page.__dict__:
        setattr(Page, _name, None)


if __name__ == '__main__':
    unittest.main()
