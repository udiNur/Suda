#!/usr/bin/env python3
"""End to end: moving between threads is fast and nothing jumps (the tower for the owner, thread suda m322).

"Back/forward and similar navigation (opening a thread, going back to the list, switching threads, the phone back
gesture) must be as fast and smooth as possible, with minimal jumps." The same harness as test_e2e.py (headless
Chrome, the real board server on loopback, a temporary board). What is checked, with the times printed:

  - coming back to a thread puts the very same rows on the screen, exactly where its log stood, in the same turn
    of the page (nothing is built again, nothing is drawn in between); also on the phone, through the list;
  - a long conversation that is opened for the first time shows its end at once and the rest right after, and he
    stays at its end; when he last stood further up, he lands there and is never shown the end first;
  - the conversations he is likeliest to open next are read ahead: opening one asks the server for nothing.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import sys
import time
import unittest

import test_e2e
from test_e2e import SIZES

LONG, SHORT = 'e2e-nav-long', 'e2e-nav-short'
# open a thread and say, in the same turn of the page: how long the script took, how many rows are there, where the log stands
GO = ('(()=>{const t0=performance.now();openChannel(%s);const ms=performance.now()-t0;return JSON.stringify({ms:Math.round(ms*10)/10,rows:document.querySelectorAll("#log .msg").length,'
      'kept:[...document.querySelectorAll("#log .msg")].filter(row=>row.__kept).length,top:Math.round(scroller.scrollTop),gap:Math.round(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop),'
      'short:logShort,title:document.querySelector("#h-title").textContent});})()')
ASKED = ('JSON.stringify(performance.getEntriesByType("resource").map(e=>new URL(e.name).pathname.split("/").slice(2).join("/")).filter(n=>/^full\\//.test(n)))')


class Nav(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def topics(self):
        if LONG in self.state()['threads']:
            return
        self.ok('new', LONG, 'שיחה ארוכה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', SHORT, 'שיחה קצרה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 131):
            self.ok('say', LONG, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork',
                    input='הודעה מספר %d\n\n- פרט ראשון\n- פרט שני\n\n```sh\necho %d\n```\n' % (n, n))
        for n in range(1, 4):
            self.ok('say', SHORT, '--from', 'fork', 'קצרה %d' % n, '--state', 'working', '--note', 'בודקים')

    def go(self, tid):
        return self.browser.eval(GO % json.dumps(tid))

    def whole(self, tid, n):
        self.browser.wait('JSON.stringify(synced&&view.ch===%s&&!thread(%s).partial&&logShort===null&&document.querySelectorAll("#log .msg").length===%d)' % (json.dumps(tid), json.dumps(tid), n),
                          timeout=30, what='all of %s on the page (%d messages)' % (tid, n))

    def test_coming_back_to_a_thread_puts_the_same_rows_where_they_stood(self):
        self.topics()
        times = {}
        for size in (SIZES[2], SIZES[0]):
            with self.subTest(size=size[0]):
                self.open_thread(size, LONG, 'שיחה ארוכה')
                self.whole(LONG, 130)
                # he reads somewhere in the middle (his own scroll), and the rows he sees are marked
                self.browser.eval('(()=>{scroller.scrollTop=Math.round(scroller.scrollHeight*0.4);scroller.dispatchEvent(new Event("scroll"));'
                                  'for(const row of document.querySelectorAll("#log .msg"))row.__kept=1;return "ok";})()')
                time.sleep(0.3)
                before = self.browser.eval('JSON.stringify({top:Math.round(scroller.scrollTop),first:[...document.querySelectorAll("#log .msg")].find(r=>r.getBoundingClientRect().bottom>scroller.getBoundingClientRect().top+1).dataset.mid})')
                self.assertGreater(before['top'], 500)
                # to another thread ...
                away = self.go(SHORT)
                self.assertEqual((away['rows'], away['title']), (3, 'שיחה קצרה'))
                # ... and back: in the same turn of the page the same rows are there, where the log stood
                back = self.go(LONG)
                self.assertEqual((back['rows'], back['kept'], back['title'], back['short']), (130, 130, 'שיחה ארוכה', None), back)
                self.assertLessEqual(abs(back['top'] - before['top']), 2, (before, back))
                first = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].find(r=>r.getBoundingClientRect().bottom>scroller.getBoundingClientRect().top+1).dataset.mid)')
                self.assertEqual(first, before['first'])
                time.sleep(0.5)                 # and it stays there once the browser has drawn and the page has settled
                self.assertLessEqual(abs(self.browser.eval('JSON.stringify(Math.round(scroller.scrollTop))') - before['top']), 2)
                times[size[0]] = back['ms']
                if size is SIZES[0]:
                    # the phone: back to the list with the browser's own back, and into the thread again
                    self.browser.eval('(()=>{history.back();return "ok";})()')
                    self.browser.wait('JSON.stringify(!view.ch)', what='the list')
                    again = self.go(LONG)
                    self.assertEqual((again['rows'], again['kept']), (130, 130), again)
                    self.assertLessEqual(abs(again['top'] - before['top']), 2, (before, again))
        print('\ncoming back to a thread of 130 messages (script time, ms): %s' % times, file=sys.stderr)

    def test_moving_between_the_list_and_conversations_lays_out_only_what_is_new(self):
        """ "When I go back or forward I want it as fast and as smooth as it can be" (the owner, suda m322). Measured with
        the page slowed like a phone, most of a move was the browser laying rows out again: the rows of the
        conversation he had just left (once more, only to see them go), and on the way back from the list every
        row of a conversation that had never changed. Now the rows of the thread he left are out of the page before
        anything is measured, and on the phone the conversation stays laid out behind the list."""
        self.topics()
        self.open_thread(SIZES[0], LONG, 'שיחה ארוכה')
        self.whole(LONG, 130)
        # 1. to another conversation: when the page first measures the log, none of the old rows is in it
        self.browser.eval('(()=>{window.SEEN=[];const f=window.heardScroll;window.heardScroll=function(){SEEN.push([view.ch,[...document.querySelectorAll("#log .msg")].filter(r=>r.__old).length]);return f.apply(this,arguments);};'
                          'for(const row of document.querySelectorAll("#log .msg"))row.__old=1;return "ok";})()')
        self.go(SHORT)
        seen = self.browser.eval('JSON.stringify(SEEN.filter(row=>row[0]===%s))' % json.dumps(SHORT))
        self.assertTrue(seen, 'the log was never measured')
        self.assertEqual(seen[0][1], 0, 'the rows of the thread he left were still in the page when the log was measured: %s' % seen[:3])
        # 2. back to the long one, then to the list with the phone's back: the conversation stays as it is, out of sight
        self.go(LONG)
        self.whole(LONG, 130)
        self.browser.eval('(()=>{scroller.scrollTop=Math.round(scroller.scrollHeight*0.4);scroller.dispatchEvent(new Event("scroll"));'
                          'for(const row of document.querySelectorAll("#log .msg"))row.__kept=1;return "ok";})()')
        time.sleep(0.4)
        top = self.browser.eval('JSON.stringify(Math.round(scroller.scrollTop))')
        self.browser.eval('(()=>{history.back();return "ok";})()')
        self.browser.wait('JSON.stringify(!view.ch)', what='the list')
        time.sleep(0.4)
        stood = self.browser.eval('JSON.stringify({pane:!document.querySelector("#pane").hidden,rows:document.querySelectorAll("#log .msg").length,top:Math.round(scroller.scrollTop),'
                                  'seen:getComputedStyle(document.querySelector("#chat")).visibility,list:!!document.querySelector("#channels [data-id]").offsetParent})')
        self.assertEqual(stood, {'pane': True, 'rows': 130, 'top': top, 'seen': 'hidden', 'list': True}, stood)
        # 3. into it again: not one row is taken out or put in, and the log stands where it stood
        self.browser.eval('(()=>{window.MOVED=0;new MutationObserver(list=>{for(const m of list)MOVED+=m.addedNodes.length+m.removedNodes.length;}).observe(document.querySelector("#log"),{childList:true});return "ok";})()')
        again = self.go(LONG)
        time.sleep(0.4)
        self.assertEqual((again['rows'], again['kept']), (130, 130), again)
        self.assertEqual(self.browser.eval('JSON.stringify(MOVED)'), 0, 'rows were taken out or put in on the way back')
        self.assertLessEqual(abs(self.browser.eval('JSON.stringify(Math.round(scroller.scrollTop))') - top), 2)
        self.assertTrue(self.browser.visible('#input'))
        # the wide screen has no list in front of the conversation: with no thread open the pane is away, as before
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', what='the state')
        self.browser.eval('(()=>{navigate({ch:null},false);return "ok";})()')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#pane").hidden&&!document.querySelector("#empty").hidden)'))

    def test_a_long_conversation_shows_its_end_first_and_nothing_moves(self):
        self.topics()
        self.open_thread(SIZES[2], SHORT, 'שיחה קצרה')
        self.browser.wait('JSON.stringify(synced&&!!thread(%s))' % json.dumps(LONG), what='the board')
        # the long conversation is on the device already (read ahead, or from an earlier scenario): what is timed is the drawing
        self.browser.wait('(()=>{wantThread(%s);return JSON.stringify(!thread(%s).partial);})()' % (json.dumps(LONG), json.dumps(LONG)), timeout=20, what='the long conversation on the device')
        self.browser.eval('(()=>{rowCaches.delete(%s);localStorage.removeItem(slug+":place:"+%s);placeBooks.delete(%s);return "ok";})()' % (json.dumps(LONG), json.dumps(LONG), json.dumps(LONG)))
        self.browser.eval('(()=>{window.STEPS=[];new MutationObserver(()=>STEPS.push(document.querySelectorAll("#log .msg").length)).observe(document.querySelector("#log"),{childList:true});return "ok";})()')
        first = self.go(LONG)
        # in the turn that opened it: only its end is drawn, and he is at the end
        self.assertEqual((first['short'], first['title']), (LONG, 'שיחה ארוכה'), first)
        self.assertTrue(40 <= first['rows'] <= 60, first)
        self.assertLessEqual(first['gap'], 2, first)
        # right after: all of it, and he is still at the end
        self.whole(LONG, 130)
        self.assertLessEqual(self.browser.eval('JSON.stringify(Math.round(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop))'), 2, 'he was moved from the end when the rest was drawn')
        # The rest came a part at a time, each after the browser had drawn the one before: laying all of it out in
        # one go held the page still for about a second on a phone, right when he starts to read or to write.
        steps = sorted(set(self.browser.eval('JSON.stringify(STEPS)')))
        self.assertEqual((steps[0], steps[-1]), (first['rows'], 130), steps)
        self.assertGreaterEqual(len(steps), 3, steps)
        self.assertLessEqual(max(b - a for a, b in zip(steps, steps[1:])), 45, steps)
        # a message that is not drawn yet is asked for (a link to it, the quote of a reply) while only the end is
        # there: the rest is drawn at once and he lands on it, instead of the jump being lost
        self.go(SHORT)
        self.browser.eval('(()=>{rowCaches.delete(%s);localStorage.removeItem(slug+":place:"+%s);placeBooks.delete(%s);return "ok";})()' % (json.dumps(LONG), json.dumps(LONG), json.dumps(LONG)))
        jump = self.browser.eval('(()=>{openChannel(%s);const short=logShort,rows=document.querySelectorAll("#log .msg").length,found=showMessage("m5");'
                                 'const row=[...document.querySelectorAll("#log .msg")].find(r=>r.dataset.mid==="m5"),box=row&&row.getBoundingClientRect(),view=scroller.getBoundingClientRect();'
                                 'return JSON.stringify({short,rows,found,all:document.querySelectorAll("#log .msg").length,seen:!!box&&box.top>=view.top-2&&box.top<view.bottom});})()' % json.dumps(LONG))
        self.assertEqual((jump['short'], jump['found'], jump['all'], jump['seen']), (LONG, True, 130, True), jump)
        self.assertTrue(40 <= jump['rows'] <= 60, jump)
        time.sleep(0.6)
        self.assertTrue(self.browser.eval('(()=>{const box=[...document.querySelectorAll("#log .msg")].find(r=>r.dataset.mid==="m5").getBoundingClientRect(),view=scroller.getBoundingClientRect();'
                                          'return JSON.stringify(box.top>=view.top-2&&box.bottom<=view.bottom+2);})()'), 'he was taken away from the message he asked for once the page settled')
        # the whole conversation arrives only after its last messages were shown (a device that did not keep it, or
        # kept an older copy): that too is drawn a part at a time, and he stays at the end
        self.go(SHORT)
        self.browser.eval('(()=>{const id=%s,t=thread(id);t.messages=t.messages.map((m,i)=>i<t.messages.length-4?{id:m.id,from:m.from,ts:m.ts,v:m.v,text:"",light:true}:m);t.partial=true;'
                          'held.delete(id);rowCaches.delete(id);placeBooks.delete(id);localStorage.removeItem(slug+":place:"+id);STEPS.length=0;return "ok";})()' % json.dumps(LONG))
        tail = self.go(LONG)
        self.assertLessEqual(tail['rows'], 60, tail)
        self.whole(LONG, 130)
        arrived = sorted(set(self.browser.eval('JSON.stringify(STEPS)')))
        self.assertEqual(arrived[-1], 130, arrived)
        self.assertGreaterEqual(len(arrived), 3, arrived)
        self.assertLessEqual(max(b - a for a, b in zip(arrived, arrived[1:])), 50, arrived)
        self.assertLessEqual(self.browser.eval('JSON.stringify(Math.round(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop))'), 2, 'he was moved from the end when the rest arrived')
        self.go(SHORT)
        self.go(LONG)
        self.whole(LONG, 130)                                       # the parts have all come
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#log .older"))'))
        # for comparison: the same conversation drawn all at once (as before), timed in the same page
        whole = self.browser.eval('(()=>{openChannel(%s);rowCaches.delete(%s);const t0=performance.now();navigate({ch:%s},false);rowCache.clear();logShort=null;logSignature="";render();'
                                  'return JSON.stringify({ms:Math.round((performance.now()-t0)*10)/10,rows:document.querySelectorAll("#log .msg").length});})()' % (json.dumps(SHORT), json.dumps(LONG), json.dumps(LONG)))
        print('\nopening a thread of 130 messages for the first time (script time, ms): its end first %s, all at once %s' % (first['ms'], whole['ms']), file=sys.stderr)
        # he last stood far up in it: it opens there, all of it drawn at once, and he is never shown the end first
        self.whole(LONG, 130)
        self.browser.eval('(()=>{const row=[...document.querySelectorAll("#log .msg")].find(r=>r.dataset.mid==="m20");scroller.scrollTop+=row.getBoundingClientRect().top-scroller.getBoundingClientRect().top;'
                          'scroller.dispatchEvent(new Event("scroll"));return "ok";})()')
        self.browser.wait('JSON.stringify(!!placeBooks.get(%s)&&!!placeBooks.get(%s).mine&&placeBooks.get(%s).mine.at==="m20")' % ((json.dumps(LONG),) * 3), timeout=15, what='his place at message 20, kept on the device')
        self.go(SHORT)
        self.browser.eval('(()=>{rowCaches.delete(%s);return "ok";})()' % json.dumps(LONG))
        far = self.go(LONG)
        self.assertEqual((far['short'], far['rows']), (None, 130), far)
        at = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].find(r=>r.getBoundingClientRect().bottom>scroller.getBoundingClientRect().top+1).dataset.mid)')
        self.assertEqual(at, 'm20')

    def test_the_threads_he_is_likeliest_to_open_are_read_ahead(self):
        self.topics()
        self.ok('new', 'e2e-nav-waits', 'נושא שמחכה לו', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 13):
            self.ok('say', 'e2e-nav-waits', '--from', 'fork', 'הודעה %d בנושא שמחכה' % n, '--state', 'working', '--note', 'בודקים')
        self.ok('ask', 'e2e-nav-waits', 'להמשיך?', '--options', 'כן,לא')
        self.open(SIZES[2])                                  # a page of the board, to empty what the device kept of that thread
        self.browser.eval('(async()=>{await keptStore.drop("full:e2e-nav-waits");return "ok";})()')
        self.open_thread(SIZES[2], SHORT, 'שיחה קצרה')
        self.assertTrue(self.browser.eval('JSON.stringify(thread("e2e-nav-waits").partial)'))
        # within a few seconds, with nothing asked of the page, the thread that waits for him is whole
        self.browser.wait('JSON.stringify(!thread("e2e-nav-waits").partial)', timeout=20, what='the thread that waits for him, read ahead')
        self.assertIn('full/e2e-nav-waits.json', self.browser.eval(ASKED))
        asked = len(self.browser.eval(ASKED))
        # he opens it: all of it is there in the same turn, and the server is asked for nothing more
        there = self.go('e2e-nav-waits')
        self.assertEqual((there['rows'], there['title']), (13, 'נושא שמחכה לו'), there)
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#log .older"))'))
        time.sleep(1)
        self.assertEqual(len(self.browser.eval(ASKED)), asked)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Nav.__dict__:
        setattr(Nav, _name, None)


if __name__ == '__main__':
    unittest.main()
