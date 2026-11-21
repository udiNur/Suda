#!/usr/bin/env python3
"""End to end: updates on a weak link (sse153). Every change of the board has a number; the page knows the last one
it applied and catches up from it after any break, by small deltas when it can and by the whole summary when in
doubt. The same harness as test_e2e.py: headless Chrome, the board server on loopback (THREADS_BOARDLIB_DIR), the
CLI behind its hook, a temporary board. What is checked:

  - a line dropped mid-stream: the page says so, and catches up by the changes alone when it is back;
  - changes.json failing (the browser aborts it): the page reads the whole summary and still catches up;
  - a gap (changes.json cut short): the whole summary, and the screen equals the board;
  - the mark never says "מעודכן" while the page is behind or offline;
  - two pages at once: each keeps its own number, and replies from both land exactly once;
  - a reply that waited for the line goes right after the line returns, and is not counted "deaf";
  - the change on the line (inline168, "event: delta"): a dropped line comes back with no read at all, and deltas
    lost mid-burst cost a read each, never a wrong screen.
Since inline168 the server sends each change on the line, so a page is never behind for long: the scenarios of
the read path (the changes, the whole summary, the mark of a page that is behind) drop the deltas (NO_DELTA), as
with a server from before it or a delta lost on the way.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest

import test_e2e
from test_e2e import SIZES

# what the page asked for since the last clear, by name (without the board's folder and the query); the first bytes
# of the summary only (its head, a Range request) are "summary.json:head"
ASKED = ('JSON.stringify(performance.getEntriesByType("resource").map(e=>{const n=new URL(e.name).pathname.split("/").slice(2).join("/");'
         'return n==="summary.json"&&(e.responseStatus===206||(e.decodedBodySize>0&&e.decodedBodySize<=64))?n+":head":n;})'
         '.filter(n=>/^(summary|state|changes)\\.json(:head)?$|^changes\\//.test(n)))')
CLEAR = '(()=>{performance.setResourceTimingBufferSize(5000);performance.clearResourceTimings();return "ok";})()'
# The page's line, held down: the next EventSource never opens (as on a phone whose link is gone), until let go.
HOLD_LINE = r"""(()=>{
  if(!window.__realES)window.__realES=window.EventSource;
  window.EventSource=function(){const fake={readyState:0,close(){fake.readyState=2;},addEventListener(){}};return fake;};
  try{events.close();}catch{}
  events=null;connection(false);listen();return 'ok';
})()"""
# Its reads of the board held too (a link that is gone for every request, not only the line).
HOLD_READS = r"""(()=>{const real=window.fetch;window.__readsFetch=real;
  window.fetch=(url,opts)=>/summary|changes|state\.json/.test(String(url))?Promise.reject(new TypeError('held')):real(url,opts);return 'ok';})()"""
FREE_READS = '(()=>{window.fetch=window.__readsFetch;return "ok";})()'
FREE_LINE = '(()=>{window.EventSource=window.__lineES||window.__realES;try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()'
# The line without its deltas: the page's 'delta' listener is skipped, so it reads every update as before inline168.
# window.__dropDelta(e), when set, decides for each delta (true: dropped); window.__deltas counts both.
NO_DELTA = r"""(()=>{
  if(!window.__realES)window.__realES=window.EventSource;
  const Real=window.__realES;window.__deltas={taken:0,dropped:0};
  window.__lineES=function(url,opts){const es=new Real(url,opts),add=es.addEventListener.bind(es);
    es.addEventListener=(type,fn,o)=>add(type,type!=='delta'?fn:e=>{if(window.__dropDelta?window.__dropDelta(e):true){window.__deltas.dropped++;return;}window.__deltas.taken++;fn(e);},o);
    return es;};
  window.EventSource=window.__lineES;
  try{events.close();}catch{}events=null;connection(false);listen();return 'ok';
})()"""
LINE_UP = 'JSON.stringify(!!events&&events.readyState===1&&numbered)'
# Every mark the header showed, with the page's number and the server's word at that moment.
WATCH_MARK = r"""(()=>{
  window.__marks=[];
  const note=()=>window.__marks.push({text:live.textContent,fresh:live.dataset.fresh,applied:appliedNumber,heard,t:Date.now()});
  note();new MutationObserver(note).observe(live,{childList:true,characterData:true,subtree:true,attributes:true});
  return 'ok';
})()"""
UP_TO_DATE = 'מעודכן'


class Resume(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-resume'
    TITLE = 'עדכונים על קו חלש'

    def setUp(self):
        if self.TID not in self.state()['threads']:
            self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            self.ok('new', self.TID + '-b', 'נושא שני', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.addCleanup(self.browser.run, 'set', 'offline', 'off', check=False)

    def say(self, text, tid=None):
        self.ok('say', tid or self.TID, '--from', 'fork', text, '--state', 'working', '--note', 'בודקים')

    def seq(self):
        return self.state()['seq']

    def summary(self):
        return json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))

    def asked(self, browser=None):
        return (browser or self.browser).eval(ASKED)

    def up_to_date(self, browser=None, timeout=25):
        """The page shows the board as it stands: its number is the board's, the summary it holds is the server's,
        what it draws comes from it, and the mark says so. (The page's own actions, a "seen" or a place, may move the
        board on meanwhile: then it is asked again.)"""
        browser = browser or self.browser
        end = time.monotonic() + timeout
        while True:
            seq = self.seq()
            browser.wait('JSON.stringify(appliedNumber>=%d&&live.dataset.fresh==="fresh")' % seq, timeout=max(1, end - time.monotonic()),
                         what='the page at number %d, up to date' % seq)
            got = browser.eval('JSON.stringify({held:base,mark:live.textContent,shown:Object.values(data.threads).map(t=>[t.id,t.title,t.status,(t.stamps||[]).map(s=>s[0])]).sort()})')
            summary = self.summary()
            if got['held']['seq'] == summary['seq'] == self.seq() or time.monotonic() > end:
                break
        self.assertEqual(got['held'], summary)
        want = sorted([t['id'], t['title'], 'open' if t['status'] == 'open' else 'closed', [s[0] for s in t['stamps']]] for t in summary['threads'].values())
        self.assertEqual(got['shown'], want)
        self.assertEqual(got['mark'], UP_TO_DATE)
        return summary['seq']

    def open_board(self, size=SIZES[2], browser=None):
        browser = browser or self.browser
        if browser is self.browser:
            self.open_thread(size, self.TID, self.TITLE)
        else:
            name, w, h = size
            browser.viewport(w, h)
            test_e2e.Suda.visits += 1
            browser.open(self.url + '?s=%s&n=%d#%s' % (name, test_e2e.Suda.visits, self.TID))
            browser.wait('JSON.stringify(document.body.innerText.includes(%s)&&!!document.querySelector("#input").offsetParent)' % json.dumps(self.TITLE),
                         what='the thread on the second page')
        browser.eval('(()=>{ahead=false;return "ok";})()')
        self.up_to_date(browser)

    def test_a_dropped_line_catches_up_by_the_changes_alone(self):
        self.open_board()
        self.browser.eval(NO_DELTA)                               # the read path: no change rides on the line
        self.browser.wait(LINE_UP, what='the line without deltas')
        self.browser.eval(WATCH_MARK)
        self.browser.eval(CLEAR)
        self.browser.eval(HOLD_LINE)
        self.browser.wait('JSON.stringify(live.textContent==="לא מחובר")', what='the mark of a line that is down')
        for i in range(5):                                       # more than a few: changes.json, not one file each
            self.say('בזמן שהקו נפל %d' % i)
        self.say('ובנושא השני', self.TID + '-b')
        time.sleep(1.5)
        self.assertEqual(self.browser.eval('JSON.stringify(live.textContent)'), 'לא מחובר')
        self.browser.eval(FREE_LINE)
        self.up_to_date()
        asked = self.asked()
        self.assertNotIn('summary.json', asked, 'a page a few changes behind read the whole summary: %s' % asked)
        # six changes: one small file holds them all (from the page's number on), or changes.json; never one file each
        changes = [n for n in asked if n.startswith('changes')]
        self.assertTrue(changes, asked)
        self.assertLessEqual(len([n for n in changes if n.startswith('changes/')]), 3, asked)
        # one or two behind: the small file of each change (named by the number it starts from), not even changes.json,
        # and the head of the summary beside it
        self.browser.eval(CLEAR)
        held = self.seq()
        self.say('אחת אחרי')
        self.up_to_date()
        asked = self.asked()
        self.assertIn('changes/%d.json' % held, asked)
        self.assertEqual([n for n in asked if not n.startswith('changes/') and n != 'summary.json:head'], [], asked)
        self.assertMarksHonest()

    def test_changes_json_failing_falls_back_to_the_whole_summary(self):
        self.open_board()
        self.browser.eval(NO_DELTA)
        self.browser.wait(LINE_UP, what='the line without deltas')
        self.browser.eval(CLEAR)
        self.browser.run('network', 'route', '**/changes*', '--abort')
        self.addCleanup(self.browser.run, 'network', 'unroute', check=False)
        self.say('כשהשינויים לא נקראים')
        self.say('ועוד אחת')
        self.up_to_date()
        self.assertIn('summary.json', self.asked())
        self.browser.run('network', 'unroute')

    def test_a_gap_reads_the_whole_summary_and_the_screen_equals_the_board(self):
        self.open_board()
        self.browser.eval(WATCH_MARK)
        self.browser.eval(HOLD_LINE)
        for i in range(4):
            self.say('לפני החור %d' % i)
        # changes.json cut short: the first changes the page needs are gone, and so are their own files
        changes = json.loads((self.board / 'changes.json').read_text())
        changes['entries'] = changes['entries'][-1:]
        (self.board / 'changes.json').write_text(json.dumps(changes, ensure_ascii=False))
        for path in (self.board / 'changes').glob('*.json'):
            if int(path.stem) != changes['entries'][-1]['from']:
                path.unlink()
        self.browser.eval(CLEAR)
        self.browser.eval(FREE_LINE)
        self.up_to_date()
        asked = self.asked()
        if os.environ.get('SUDA_E2E_SERVER') == 'own' and (self.board / 'suda.db').is_file():
            # Suda's own server answers changes/<n>.json from the store at any distance (sqlite177): the files' gap
            # is no gap for it, so the page catches up by one changes read; else it reads the whole summary
            self.assertTrue('summary.json' in asked or any(x.startswith('changes/') for x in asked), asked)
        else:
            self.assertIn('summary.json', asked)
        self.assertMarksHonest()

    def test_the_mark_never_says_up_to_date_while_behind_or_offline(self):
        self.open_board(SIZES[0])                                 # the phone: the mark is in the thread's header too
        self.browser.eval(NO_DELTA)                               # else the change comes on the line and the page is never behind
        self.browser.wait(LINE_UP, what='the line without deltas')
        self.browser.eval(WATCH_MARK)
        # behind: the server says a newer number, and the page cannot read it yet
        self.browser.eval(r"""(()=>{const real=window.fetch.bind(window);window.__realFetch=real;
          window.fetch=(url,opts)=>/changes|summary\.json|state\.json/.test(String(url))?Promise.reject(new TypeError('blocked')):real(url,opts);return 'ok';})()""")
        self.say('השרת יודע, הדף עוד לא')
        seq = self.seq()
        self.browser.wait('JSON.stringify(heard===%d)' % seq, timeout=15, what='the server to say the new number')
        self.browser.wait('JSON.stringify(live.textContent==="מתעדכן…")', what='the mark of a page that is behind')
        self.assertTrue(self.browser.eval('JSON.stringify(!document.querySelector("#h-fresh").hidden&&!!document.querySelector("#h-fresh").offsetParent)'),
                        'on the phone the thread header says it too')
        time.sleep(4)
        self.assertNotEqual(self.browser.eval('JSON.stringify(live.textContent)'), UP_TO_DATE)
        self.browser.eval('(()=>{window.fetch=window.__realFetch;return "ok";})()')
        self.up_to_date(timeout=30)
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#h-fresh").hidden)'))
        # offline: the browser's own network is gone. "לא מחובר", never "מעודכן", even with no error from the line
        self.browser.run('set', 'offline', 'on')
        self.browser.wait('JSON.stringify(live.textContent==="לא מחובר")', timeout=35, what='the mark of a page that is offline')
        self.say('בזמן שהדף מנותק')
        time.sleep(3)
        self.assertEqual(self.browser.eval('JSON.stringify(live.textContent)'), 'לא מחובר')
        self.browser.run('set', 'offline', 'off')
        self.up_to_date(timeout=35)
        # a line that is open and silent (no error, no word from the server): "לא מחובר" after 25 seconds
        self.browser.eval('(()=>{window.__onNumber=onNumber;onNumber=()=>{};return "ok";})()')
        quiet = time.monotonic()
        self.browser.wait('JSON.stringify(live.textContent==="לא מחובר")', timeout=40, what='the mark of a silent line')
        self.assertGreater(time.monotonic() - quiet, 15)
        self.browser.eval('(()=>{onNumber=window.__onNumber;return "ok";})()')
        self.up_to_date(timeout=30)
        self.assertMarksHonest()

    def test_a_dropped_line_comes_back_with_the_changes_on_the_line(self):
        """inline168: the line opens again with the page's number (since=), and the server sends what it missed on it
        first thing. The page still reads once when the line opens (lineBack checks at "open", before the body with
        the delta has come): at most the one small change file and the summary's head, never the whole summary or
        changes.json (six changes behind, which by reads alone would take changes.json). The deltas are counted (a
        page that ignored them would pass the read checks alone): the line's backlog is taken, nothing dropped."""
        self.open_board()
        self.browser.eval('(()=>{window.__dropDelta=()=>false;return "ok";})()')       # every delta taken, and counted
        self.browser.eval(NO_DELTA)
        self.browser.wait(LINE_UP, what='the line, deltas counted')
        self.browser.eval(WATCH_MARK)
        self.browser.eval(HOLD_LINE)
        self.browser.wait('JSON.stringify(live.textContent==="לא מחובר")', what='the mark of a line that is down')
        for i in range(5):
            self.say('בזמן הניתוק, על הקו %d' % i)
        self.say('ובנושא השני, על הקו', self.TID + '-b')
        self.browser.eval(CLEAR)
        self.browser.eval(FREE_LINE)
        self.up_to_date()
        asked = self.asked()
        self.assertEqual([n for n in asked if n in ('summary.json', 'changes.json', 'state.json')], [],
                         'the changes came on the line, yet the page read them whole: %s' % asked)
        self.assertLessEqual(len([n for n in asked if n.startswith('changes/')]), 1, asked)
        deltas = self.browser.eval('JSON.stringify(window.__deltas)')
        self.assertGreaterEqual(deltas['taken'], 1, 'the backlog on the line was not taken: %s' % deltas)
        self.assertEqual(deltas['dropped'], 0, deltas)
        self.assertMarksHonest()

    def test_deltas_lost_mid_burst_still_end_equal_to_the_board(self):
        """A burst whose deltas are lost on the way, every other one (a proxy, a cut): where the page lacks one it
        reads, and it ends equal to the board, every message once, the mark honest."""
        self.open_board()
        self.browser.eval('(()=>{window.__dropDelta=()=>false;return "ok";})()')       # first every delta is taken
        self.browser.eval(NO_DELTA)
        self.browser.wait(LINE_UP, what='the line, deltas taken')
        self.browser.eval(WATCH_MARK)
        for i in range(6):
            self.say('פרץ %d' % i)
        self.up_to_date()
        self.assertGreater(self.browser.eval('JSON.stringify(window.__deltas.taken)'), 0)
        self.browser.eval(CLEAR)
        self.browser.eval('(()=>{let k=0;window.__dropDelta=()=>(k++%2)===0;return "ok";})()')  # then every other one lost
        for i in range(6, 26):
            self.say('פרץ %d' % i)
            if i % 4 == 0:
                time.sleep(1.1)                                   # across several looks of the server: several deltas
        self.up_to_date(timeout=40)
        deltas = self.browser.eval('JSON.stringify(window.__deltas)')
        self.assertGreater(deltas['dropped'], 0, deltas)
        self.assertTrue([n for n in self.asked() if n.startswith('changes') or n == 'summary.json'], 'a lost delta, yet no read (the measure heads do not count)')
        shown = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].map(r=>(r.innerText.match(/פרץ \\d+/g)||[])).flat())')
        self.assertEqual(sorted(shown, key=lambda t: int(t.split()[1])), ['פרץ %d' % i for i in range(26)], 'every message of the burst, once')
        self.assertMarksHonest()

    def assertMarksHonest(self):
        """Every time the mark said "מעודכן", the page's number was the one the server had just said."""
        marks = self.browser.eval('JSON.stringify(window.__marks||[])')
        self.assertTrue(marks)
        for m in marks:
            if m['text'] == UP_TO_DATE:
                self.assertEqual(m['applied'], m['heard'], m)

    def test_two_pages_each_keep_their_number_and_replies_land_once(self):
        other = test_e2e.Browser('threads-e2e-resume2-%d' % id(self))
        try:
            other.launch()
        except Exception as e:
            self.skipTest('a second browser could not open: ' + str(e)[:200])
        self.addCleanup(other.close)
        self.open_board()
        self.open_board(SIZES[0], other)
        before = len(self.thread(self.TID)['messages'])
        # the second page drops for a while (its line and its reads: a probe would find the link and read): the two
        # pages stand at different numbers
        other.eval(HOLD_LINE)
        other.eval(HOLD_READS)
        self.say('רק הראשון רואה את זה עכשיו')
        self.up_to_date()
        self.assertLess(other.eval('JSON.stringify(appliedNumber)'), self.seq())
        other.eval(FREE_READS)
        other.eval(FREE_LINE)
        for page, text in ((self.browser, 'תשובה מהמחשב'), (other, 'תשובה מהטלפון')):
            page.fill('#input', text)
        for page in (self.browser, other):
            page.click('#send')
        self.until(lambda: len(self.thread(self.TID)['messages']) >= before + 3, timeout=25, what='both replies in the state')
        time.sleep(2)
        texts = [m['text'] for m in self.thread(self.TID)['messages'] if m['from'] == 'owner']
        self.assertEqual(texts.count('תשובה מהמחשב'), 1)
        self.assertEqual(texts.count('תשובה מהטלפון'), 1)
        for page in (self.browser, other):
            self.up_to_date(page)
            page.wait('JSON.stringify(document.body.innerText.includes("תשובה מהמחשב")&&document.body.innerText.includes("תשובה מהטלפון"))',
                      what='both replies on each page')
            self.assertEqual(page.eval('JSON.stringify([...optimistic.values()].flat().filter(m=>m.delivery!=="received").length)'), 0)

    def test_a_waiting_reply_goes_right_after_the_line_returns(self):
        self.open_board()
        # the line goes, and so does every request: the reply waits, and its tries move further apart
        self.browser.eval(HOLD_LINE)
        self.browser.eval(r"""(()=>{const real=window.fetch.bind(window);window.__realFetch=real;
          window.fetch=(url,opts)=>Promise.reject(new TypeError('offline'));return 'ok';})()""")
        text = 'נשלח כשהקו חוזר'
        self.browser.fill('#input', text)
        self.browser.click('#send')
        self.browser.wait('JSON.stringify([...optimistic.values()].flat().some(m=>m.text===%s&&m.delivery==="waiting"&&m.tries>=3))' % json.dumps(text),
                          timeout=40, what='the reply waiting, after a few tries')
        due = self.browser.eval('JSON.stringify([...optimistic.values()].flat().find(m=>m.text===%s).due-Date.now())' % json.dumps(text))
        self.assertGreater(due, 3000, 'the next try is far enough to tell "at once" from "when due"')
        # the line is back: the reply goes now, not when its next try is due
        back = time.monotonic()
        self.browser.eval('(()=>{window.fetch=window.__realFetch;return "ok";})()')
        self.browser.eval(FREE_LINE)
        self.until(lambda: any(m['text'] == text for m in self.thread(self.TID)['messages']), timeout=15, what='the reply in the state')
        self.assertLess(time.monotonic() - back, min(due / 1000, 8), 'the reply waited for its next try instead of going with the line')
        self.up_to_date()
        sent = self.browser.eval('JSON.stringify([...optimistic.values()].flat().find(m=>m.text===%s)||null)' % json.dumps(text))
        self.assertTrue(sent is None or (sent['delivery'] == 'received' and not sent.get('deaf')), sent)
        self.assertEqual([m['text'] for m in self.thread(self.TID)['messages']].count(text), 1)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Resume.__dict__:
        setattr(Resume, _name, None)


if __name__ == '__main__':
    unittest.main()
