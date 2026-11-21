#!/usr/bin/env python3
"""Hostile review of ecbc23e (inlinefix): an update taken from the line asks for the summary's head (64 bytes, never
waited for) when measureDue says the newest latency sample is old, so slow mode still learns his latency.

Each test asserts the SAFE outcome, so it fails on the code that has the hole:

- the measure head is a read of the board that nothing can cut: it takes the reading's signal (readSignal), and
  the reading ends (readDone) the moment it returns, so the way is out of onTheWay before the head has even left.
  A head stuck on a dropped link is never stopped by cutStuck, the very thing that keeps a stuck read from holding
  one of the browser's 6 connections;
- nothing holds a second measure back while the first is still on its way: measureDue looks only at samples that
  landed, so on exactly the loaded link it is meant to see (a head that takes seconds) every update asks again;
- while the page is hidden its samples never count (awayGaps), so measureDue stays due and every update asks for a
  head that can tell nothing;
- measureDue takes a sample from the future (the clock stepped back) as fresh: no measure until the clock passes it;
- test_e2e_resume's new scenario "a dropped line comes back with the changes on the line" passes just as well on a
  page that drops every delta: it does not test the deltas.

Uses the harness of test_e2e (agent-browser, a temp board, the board server of the html-interview-board skill).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

import test_e2e
import test_e2e_resume as resume

PAGE = _paths.APP / 'suda.html'

# The summary's head requests (a Range on summary.json?t=): each is recorded (when it left, its signal aborted or
# not, whether it is still on its way), and its answer is held back HOLD ms (the request itself goes at once, on the
# page's own fetch and with the page's own signal): a link whose round trip under load is that long.
HELD_HEADS = r'''(()=>{
  if(!window.__plainFetch)window.__plainFetch=window.fetch;
  const plain=window.__plainFetch;window.__heads=[];
  window.fetch=(url,opts)=>{
    const s=String(url&&url.url||url),range=opts&&opts.headers&&(opts.headers.Range||opts.headers.range);
    if(!(/summary\.json\?t=/.test(s)&&range))return plain(url,opts);
    const h={at:Date.now(),aborted:false,done:false,hidden:document.hidden,stack:String(Error().stack).split('\n').slice(2,5).join(' | ')};
    window.__heads.push(h);
    const p=plain(url,opts);
    return new Promise((ok,fail)=>{
      const sig=opts.signal;
      if(sig)sig.addEventListener('abort',()=>{h.aborted=true;h.done=true;fail(new DOMException('cut','AbortError'));});
      setTimeout(()=>p.then(r=>{h.done=true;ok(r);},e=>{h.done=true;fail(e);}),%d);
    });
  };
  return "ok";
})()'''
HEADS = 'JSON.stringify(window.__heads||[])'
FAKE_HIDDEN = r'''(()=>{
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
  Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'hidden'});
  document.dispatchEvent(new Event('visibilitychange'));return "ok";
})()'''
FAKE_SHOWN = r'''(()=>{
  delete document.hidden;delete document.visibilityState;
  document.dispatchEvent(new Event('visibilitychange'));return "ok";
})()'''


class InlineFix(resume.Resume):
    """Only the scenarios of this file."""

    TID = 'e2e-inlinefix'
    TITLE = 'מדידה של הקו'

    def inline_or_skip(self):
        if not ('_inline_delta' in (test_e2e.SKILL / 'answer_server.py').read_text(encoding='utf-8')
                and self.browser.eval('JSON.stringify(typeof measureDue==="function")')):
            self.skipTest('a server or a page from before the measure')

    def wait_applied(self, seq, timeout=20):
        self.browser.wait('JSON.stringify(appliedNumber>=%d&&!reading)' % seq, timeout=timeout, what='the page at %d' % seq)

    def test_a_measure_head_stuck_on_a_dropped_link_is_cut_with_the_other_reads(self):
        """The link drops while the measure is on its way (the answer never comes). cutStuck, run when the line is found
        silent or comes back, stops every read that left over a second ago, so that none holds a connection. The
        measure head must be one of them."""
        self.open_board()
        self.inline_or_skip()
        self.browser.eval(HELD_HEADS % 60000)
        self.browser.eval('(()=>{linkWaits.length=0;return "ok";})()')       # no sample in the last 2 s: a measure is due
        self.say('מדידה על קו שנפל')
        seq = self.seq()
        self.wait_applied(seq)
        heads = self.browser.eval(HEADS)
        self.assertTrue(heads, 'no measure was asked for, so nothing to cut (the scenario did not happen)')
        time.sleep(1.3)
        self.browser.eval('(()=>{cutStuck(false);cutStuck(true);return "ok";})()')    # the line found silent, then back
        heads = self.browser.eval(HEADS)
        stuck = [h for h in heads if not h['aborted'] and not h['done']]
        self.assertEqual(stuck, [], 'a measure head on a dead link outlives cutStuck and holds its connection: %s' % stuck)

    def test_one_measure_at_a_time_on_a_link_whose_round_trip_is_seconds(self):
        """The loaded link the measure is for: a head takes 6 s to come back. Updates come about every 1.5 s, each taken
        from the line. One measure on its way is enough: the next one waits for it (or for MEASURE_GAP after it)."""
        self.open_board()
        self.inline_or_skip()
        self.browser.eval(HELD_HEADS % 6000)
        self.browser.eval('(()=>{linkWaits.length=0;return "ok";})()')
        for i in range(5):
            self.say('עדכון בעומס %d' % i)
            self.wait_applied(self.seq())
            time.sleep(1.0)
        heads = self.browser.eval(HEADS)
        print('HEADS on a 6 s link, 5 updates:', len(heads), [h['stack'][:90] for h in heads])
        on_way = [h for h in heads if h['at'] - heads[0]['at'] < 5500] if heads else []
        self.assertLessEqual(len(on_way), 1, 'measures asked while one was still on its way: %d %s' % (len(on_way), on_way))

    def test_a_hidden_page_asks_for_no_measure_that_cannot_count(self):
        """While the page is hidden every read is left out of the measures (awayGaps), so a head asked then tells
        slow mode nothing; and since no sample ever lands, measureDue stays due and every update asks again."""
        self.open_board()
        self.inline_or_skip()
        self.browser.eval(HELD_HEADS % 0)
        self.addCleanup(lambda: self.browser.eval(FAKE_SHOWN))
        self.browser.eval(FAKE_HIDDEN)
        self.browser.eval('(()=>{linkWaits.length=0;return "ok";})()')
        for i in range(3):
            self.say('בזמן שהדף מוסתר %d' % i)
            self.wait_applied(self.seq())
            time.sleep(2.3)                                       # past MEASURE_GAP each time
        heads = self.browser.eval(HEADS)
        waits = self.browser.eval('JSON.stringify(linkWaits.slice())')
        print('HIDDEN: heads', len(heads), 'waits', waits)
        self.assertEqual(waits, [], 'a sample counted while hidden (then the head was not useless)')
        self.assertEqual([h for h in heads if h['hidden']], [], 'heads asked while hidden, none of which can count: %d' % len(heads))

    def test_the_comeback_scenario_tells_a_page_that_ignores_the_deltas(self):
        """test_e2e_resume.test_a_dropped_line_comes_back_with_the_changes_on_the_line says the changes came on the
        line. Run its steps on a page that drops every delta (NO_DELTA): its assertions must not all hold there, or
        it does not test the deltas at all."""
        self.open_board()
        self.inline_or_skip()
        self.browser.eval(resume.NO_DELTA)                        # every delta dropped: the read path alone
        self.browser.wait(resume.LINE_UP, what='the line without deltas')
        self.browser.eval(resume.WATCH_MARK)
        self.browser.eval(resume.HOLD_LINE)
        self.browser.wait('JSON.stringify(live.textContent==="לא מחובר")', what='the mark of a line that is down')
        for i in range(5):
            self.say('בזמן הניתוק, בלי קו %d' % i)
        self.say('ובנושא השני, בלי קו', self.TID + '-b')
        self.browser.eval(resume.CLEAR)
        self.browser.eval(resume.FREE_LINE)
        self.up_to_date()
        asked = self.asked()
        deltas = self.browser.eval('JSON.stringify(window.__deltas)')
        whole = [n for n in asked if n in ('summary.json', 'changes.json', 'state.json')]
        files = [n for n in asked if n.startswith('changes/')]
        print('COMEBACK without deltas: asked %s, deltas %s' % (asked, deltas))
        self.assertEqual(deltas['taken'], 0, deltas)
        original_passes = not whole and len(files) <= 1 and deltas['taken'] >= 1 and deltas['dropped'] == 0      # (its checks, as fixed)
        self.assertFalse(original_passes, 'the comeback test passes on a page that took no delta at all: asked %s' % asked)


class MeasureDuePure(unittest.TestCase):
    """measureDue under node (the page's pure functions)."""

    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_sample_from_the_future_does_not_hold_the_measure_off(self):
        """The clock stepped back an hour (set by hand, a phone that fixed its time): the newest sample's t is ahead of
        now, nowMs-t is negative, and measureDue says "a sample a moment ago" for the whole hour: no measure, so slow
        mode learns nothing while the line brings every update."""
        self.pure_js(r"""
        const T=1e9;
        assert.strictEqual(measureDue([{ms:900,t:T+3600000}],T,false),true,'a sample an hour ahead is not fresh');
        assert.strictEqual(measureDue([{ms:900,t:T+3600000}],T,true),true);
        """)


for _name in dir(resume.Resume):
    if _name.startswith('test') and _name not in InlineFix.__dict__:
        setattr(InlineFix, _name, None)


if __name__ == '__main__':
    unittest.main()
