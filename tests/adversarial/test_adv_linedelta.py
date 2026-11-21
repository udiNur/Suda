#!/usr/bin/env python3
"""Hostile review of the update in one step (suda-fixes 61, m270): the page side.

The page keeps the line's last `event: delta` (lineDelta) until a reading uses it or another comes. Nothing ties
it to the reading it came for: a delta that a reading could not use (the page was not where the change starts, so
it read as before) stays, and its number is then the page's own. The next reading at that number (a pulse touched
under the same number, the line back, the page shown again) is answered by that old delta: catchUp gives the
page's own summary back, the delta's head (read by the server before the doubt began) vouches for it, and the
summary's head is never read. The doubt ends and the header says "up to date" over a summary that is not the
board's under that number. Before this change that reading always read the head.

Run with THREADS_BOARDLIB_DIR at the server review copy. Uses the harness of test_e2e (agent-browser, a temp board).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import sys
import time
import unittest

import test_e2e
from test_e2e import SIZES

# A slow link, in the page: the summary's head and the change files arrive DELAY ms after they were read (the
# request leaves at once, its answer waits), so a reading is still on its way when the next changes come.
SLOW = r'''(()=>{
  if(!window.__plainFetch)window.__plainFetch=window.fetch;
  const plain=window.__plainFetch;
  window.fetch=(url,opts)=>{
    const s=String(url&&url.url||url),p=plain(url,opts);
    return /summary\.json\?t=|\/changes(\/\d+)?\.json/.test(s)?p.then(r=>new Promise(done=>setTimeout(()=>done(r),%d))):p;
  };
  return "ok";
})()'''
# The page tells the server a thread was seen after its readings (a numbered save, which would write the summary again
# over the rewrite these scenarios make): those posts are answered here and never reach the server.
QUIET = r'''(()=>{
  const plain=window.fetch;
  window.fetch=(url,opts)=>opts&&opts.method==='POST'&&/"op":"seen"/.test(String(opts.body))
    ?Promise.resolve(new Response(JSON.stringify({ok:true,applied:true,out:['{"ok":true}']}),{headers:{'Content-Type':'application/json'}}))
    :plain(url,opts);
  return "ok";
})()'''
FAST = '(()=>{if(window.__plainFetch)window.fetch=window.__plainFetch;return "ok";})()'


class StaleLineDelta(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def board_number(self):
        return json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))['seq']

    def held(self):
        return self.browser.eval('JSON.stringify({seq:base&&base.seq,mark:base&&base.mark,'
                                 'delta:lineDelta&&lineDelta.seq,reading:!!reading})')

    def start(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(document.body.innerText.includes(%s))' % json.dumps(title), what='the board')
        self.browser.eval(QUIET)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&numbered&&!reading)', timeout=20, what='the numbered line')
        if not ('_inline_delta' in (test_e2e.SKILL / 'answer_server.py').read_text(encoding='utf-8')
                and self.browser.eval('JSON.stringify(typeof deltaOf==="function")')):
            self.skipTest('a server or a page from before the delta')
        self.until(lambda: self.held()['seq'] == self.board_number(), what='the page at the board number')

    def say(self, tid, text):
        self.ok('say', tid, '--from', 'fork', text, '--by', 'e2e', '--state', 'working', '--note', 'עובד')

    def still_rewritten(self, seq):
        text = (self.board / 'summary.json').read_text(encoding='utf-8')
        if '"mark"' in text or json.loads(text)['seq'] != seq:
            self.skipTest('a numbered save wrote the summary again over the rewrite: nothing to show')

    def rewrite_under_the_same_number(self, tid, title):
        """What a writer that does not number does (an older threads.py, a hand): the summary rewritten with other
        content under the same number and no mark, and the pulse touched (its number stays)."""
        path = self.board / 'summary.json'
        summary = json.loads(path.read_text(encoding='utf-8'))
        seq = summary['seq']
        summary['threads'][tid]['title'] = title
        content = {k: v for k, v in summary.items() if k not in ('seq', 'mark')}
        content['seq'] = seq
        tmp = path.with_name('.summary.rewrite')
        tmp.write_text(json.dumps(content, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(tmp, path)
        pulse = self.board / '.pulse'
        self.assertEqual(pulse.read_text().strip(), str(seq))
        later = time.time() + 1
        os.utime(pulse, (later, later))
        return seq

    def two_changes(self, tid):
        """Two changes, each in a poll of its own (each its own delta and "changed")."""
        self.say(tid, 'שינוי ראשון')
        time.sleep(1.6)
        self.say(tid, 'שינוי שני')
        return self.board_number()

    def test_a_delta_left_over_from_a_reading_does_not_vouch_for_a_summary_rewritten_under_its_number(self):
        """HOLE: on a slow link a reading R0 is on its way when two changes come (delta X to N1, then N1 to N2,
        each with its "changed"). R0 ends at X; the next reading cannot use the delta (it starts at N1, the page is
        at X), reads as before, reaches N2, and leaves lineDelta (N2) in place. Meanwhile a writer that does not
        number rewrites the summary under N2 and touches the pulse: the server says N2 again, and the reading for it
        is answered by the old delta (catchUp gives the page's own summary back, the delta's head vouches for it).
        The summary's head is never read, the rewrite never arrives, the header says up to date. Before the change
        that reading read the head, found no mark and read the summary whole."""
        tid = 'adv-stale-delta'
        self.start(tid, 'שרשור הדלתא הישנה')
        self.browser.eval(SLOW % 8000)
        self.browser.eval('(()=>{window.__rc=0;const plain=readChanges;readChanges=f=>{window.__rc++;return plain(f);};'
                          'refresh();return "ok";})()')       # R0 on its way (the page shown again, say)
        time.sleep(0.3)
        n2 = self.two_changes(tid)
        # R1 has left: it could not use the delta for N2 (the page is at X, the delta starts at N1)
        # (since the fix a reading takes the delta at its start: whether it is still held here no longer matters)
        self.browser.wait('JSON.stringify(window.__rc>=2&&!!reading&&heard===%d&&base.seq!==%d)' % (n2, n2),
                          timeout=30, what='the second reading on its way')
        time.sleep(1)
        self.rewrite_under_the_same_number(tid, 'כותרת שנכתבה מחדש באותו מספר')
        self.browser.wait('JSON.stringify(base&&base.seq===%d&&!reading)' % n2, timeout=30, what='the page at N2')
        self.browser.eval(FAST)
        time.sleep(3)
        self.still_rewritten(n2)
        self.assertTrue(self.browser.eval('JSON.stringify(document.body.innerText.includes("כותרת שנכתבה מחדש באותו מספר"))'),
                        'the page holds N2 as it was before the rewrite, and says: %s' % self.browser.eval('JSON.stringify(live.dataset.fresh)'))

    def test_pinned_with_no_delta_left_over_the_rewrite_under_the_same_number_is_read(self):
        """Pinned (passes): the same two changes on a quick link (each delta used by its own reading), then the
        same rewrite: the page reads the head, finds no mark and reads the summary whole."""
        tid = 'adv-used-delta'
        self.start(tid, 'שרשור הדלתא שנוצלה')
        self.two_changes(tid)
        self.until(lambda: self.held()['seq'] == self.board_number() and not self.held()['reading'], what='the page at N2')
        self.assertIsNone(self.held()['delta'], 'each delta was used by its reading')
        n2 = self.rewrite_under_the_same_number(tid, 'כותרת חדשה בלי מספר חדש')
        time.sleep(3)
        self.still_rewritten(n2)
        self.browser.wait('JSON.stringify(document.body.innerText.includes("כותרת חדשה בלי מספר חדש"))',
                          timeout=5, what='the summary rewritten under the page number, read whole')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in StaleLineDelta.__dict__:
        setattr(StaleLineDelta, _name, None)


if __name__ == '__main__':
    unittest.main()
