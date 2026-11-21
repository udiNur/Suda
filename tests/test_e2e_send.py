#!/usr/bin/env python3
"""End to end, with a line that fails: a message he sent arrives, once, without another press (the owner, suda m332).

"Several times in the last hour I sent a message, it was not sent, and I had to try again." On his phone Snap
takes the page's renderer away the moment the screen goes dark and loads the page again when it is back; a send
that was on its way is cut. The page then showed "not sent" and waited for his finger. Here the board server of
test_e2e.py is made to fail the same ways, for replies only:

  - cut:    the line is down: a reply never reaches the server's handling, and the state cannot be read either;
  - deaf:   the line is fine, and one reply (by its words) gets no answer, every time;
  - lost:   the server stores the reply, and its answer never reaches the page;
  - refuse: the server answers "no", with its reason.

What is checked: a reply that was cut goes again by itself and is stored exactly once (also when the page was
loaded again in between, as Snap does); a reply whose answer was lost is never stored twice; what the server
refused is not sent again, and says why; and while the page is still trying, the row says so.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import io
import json
import socket
import threading
import time
import unittest

import test_e2e
from test_e2e import SIZES

ALWAYS = 10 ** 6


class Send(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Faulty(base):
            guard = threading.Lock()
            cut = 0             # replies still to be dropped before the server handles them (the line is down: no reading either)
            deaf = ''           # words: a reply that holds them gets no answer, on a line that is otherwise fine
            lose = 0            # replies whose answer is thrown away after the server stored them
            refuse = ''         # the reason every reply is refused with, nothing stored
            seen = []           # (cid, what happened to it) for every reply that came in

            def drop(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            def _json(self, obj, status=200):          # (either server: the skill's answers with _json, Suda's own with answer)
                parent = getattr(super(), '_json', None)
                return parent(obj, status) if parent else self.answer(obj, status)

            def do_GET(self, *a, **k):
                if Faulty.cut > 0 and ('summary.json' in self.path or 'state.json' in self.path or '/full/' in self.path or '/changes' in self.path):
                    return self.drop()
                return super().do_GET(*a, **k)

            def do_POST(self):
                if self.path.split('?')[0] != '/api/state':        # (the page names its board: ?board=)
                    return super().do_POST()
                raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                self.rfile = io.BytesIO(raw)
                try:
                    op = json.loads(raw)['state']
                except (ValueError, KeyError, TypeError):
                    op = None
                if not isinstance(op, dict) or op.get('op') != 'reply':
                    return super().do_POST()
                with Faulty.guard:
                    how = ('refused' if Faulty.refuse else 'deaf' if Faulty.deaf and Faulty.deaf in str(op.get('text')) else 'cut' if Faulty.cut > 0
                           else 'lost' if Faulty.lose > 0 else 'stored')
                    Faulty.cut -= how == 'cut'
                    Faulty.lose -= how == 'lost'
                    Faulty.seen.append((op.get('cid'), how))
                if how == 'refused':
                    return self._json({'ok': False, 'applied': False, 'code': 1, 'out': [json.dumps({'ok': False, 'error': Faulty.refuse}, ensure_ascii=False)]})
                if how in ('cut', 'deaf'):
                    return self.drop()
                if how == 'lost':
                    real, self.wfile = self.wfile, io.BytesIO()
                    try:
                        super().do_POST()
                    finally:
                        self.wfile = real
                    return self.drop()
                return super().do_POST()
        cls.faulty = Faulty
        cls.server.RequestHandlerClass = Faulty

    def setUp(self):
        self.calm()
        self.addCleanup(self.calm)

    def calm(self):
        with self.faulty.guard:
            self.faulty.cut = self.faulty.lose = 0
            self.faulty.refuse = self.faulty.deaf = ''
            del self.faulty.seen[:]

    def topic(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.browser.open('about:blank')
        self.open_thread(SIZES[0], tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', what='the server\'s state on the page')

    def write(self, text):
        self.browser.fill('#input', text)
        self.browser.click('#send')

    def his(self, tid, text):
        return [m for m in self.thread(tid)['messages'] if m['from'] == 'owner' and m['text'] == text]

    def row(self, text):
        """His message on the page: is it there, does it say it failed, and what its line of state says."""
        return self.browser.eval('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));if(!row)return JSON.stringify(null);'
                                 'const line=row.querySelector(".delivery");return JSON.stringify({failed:row.classList.contains("failed"),says:line?line.innerText:"",'
                                 'buttons:line?[...line.querySelectorAll("button")].map(b=>b.textContent):[]});})()' % json.dumps(text))

    def tries(self, how=None):
        with self.faulty.guard:
            return [cid for cid, what in self.faulty.seen if how is None or what == how]

    def arrived(self, tid, text, timeout=40):
        """The reply is in the thread on the server, and the page shows it as received: nobody pressed anything."""
        self.until(lambda: self.his(tid, text), timeout=timeout, what='the reply on the server, with no second press')
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&!row.classList.contains("failed")&&!/לא נשלח|מנסה שוב|שולח/.test(row.innerText));})()' % json.dumps(text),
                          timeout=timeout, what='the reply shown as received')
        time.sleep(1.5)                                             # whatever was still on its way has landed
        self.assertEqual(len(self.his(tid, text)), 1, 'the reply is in the thread exactly once')

    def test_a_reply_the_server_never_got_goes_again_by_itself_and_says_so_meanwhile(self):
        self.topic('e2e-send-cut', 'שליחה שנקטעה בדרך')
        self.faulty.cut = ALWAYS
        text = 'הודעה שנקטעה לפני שהגיעה'
        self.write(text)
        # while the line is down: nothing is lost, the row says the page is still trying, and it does try
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&/מנסה שוב/.test(row.innerText));})()' % json.dumps(text), timeout=20, what='the row to say the page tries again')
        self.until(lambda: len(self.tries('cut')) >= 3, timeout=30, what='more tries while the line is down')
        self.assertEqual(self.his('e2e-send-cut', text), [])
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#input").value)'), '')
        self.assertEqual(len(set(self.tries())), 1, 'every try carries the same id, so the server can tell a second one')
        # the line is back: the reply arrives, once, and nobody pressed "try again"
        self.faulty.cut = 0
        self.arrived('e2e-send-cut', text)

    def test_a_reply_cut_when_the_page_was_taken_away_goes_by_itself_when_the_page_is_back(self):
        self.topic('e2e-send-park', 'שליחה שנקטעה בכיבוי המסך')
        self.faulty.cut = ALWAYS
        text = 'שלחתי וכיביתי את המסך'
        self.write(text)
        self.until(lambda: self.tries('cut'), what='the reply on its way')
        # Snap takes the renderer away with the screen and loads the page again when he is back
        self.browser.open('about:blank')
        self.faulty.cut = 0
        self.open_thread(SIZES[0], 'e2e-send-park', 'שליחה שנקטעה בכיבוי המסך')
        self.arrived('e2e-send-park', text)

    def test_a_reply_whose_answer_was_lost_is_not_stored_twice(self):
        self.topic('e2e-send-lost', 'התשובה של השרת אבדה')
        self.faulty.lose = 1
        text = 'השרת קיבל, והדף לא שמע'
        self.write(text)
        self.arrived('e2e-send-lost', text)
        self.assertEqual(self.tries('lost'), self.tries('lost')[:1])
        self.assertEqual(len(set(self.tries())), 1)

    def test_what_the_server_refused_is_not_sent_again_and_says_why(self):
        self.topic('e2e-send-no', 'השרת סירב')
        self.faulty.refuse = 'השרשור סגור'
        text = 'הודעה שהשרת לא מקבל'
        self.write(text)
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&row.classList.contains("failed"));})()' % json.dumps(text), what='the refused reply marked as not sent')
        time.sleep(6)                                               # longer than the first waits between tries
        row = self.row(text)
        self.assertTrue(row['failed'], row)
        self.assertIn('לא נשלח', row['says'])
        self.assertIn('השרשור סגור', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        self.assertEqual(len(self.tries()), 1, 'a refusal is an answer: the page does not ask again by itself')
        self.assertEqual(self.his('e2e-send-no', text), [])
        # his own press still sends it, once the server takes it
        self.faulty.refuse = ''
        self.browser.eval('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          '[...row.querySelectorAll(".delivery button")].find(b=>b.textContent==="נסה שוב").click();return "ok";})()' % json.dumps(text))
        self.arrived('e2e-send-no', text)

    def test_replies_written_while_the_line_is_down_arrive_in_his_order(self):
        self.topic('e2e-send-order', 'שתי הודעות בזמן ניתוק')
        self.faulty.cut = ALWAYS
        first, second = 'ראשונה: כן', 'שנייה: ותמשיך לקטנים'
        self.write(first)
        self.until(lambda: self.tries('cut'), what='the first reply on its way')
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&/מנסה שוב/.test(row.innerText));})()' % json.dumps(first), timeout=20, what='the first reply waiting for the line')
        self.write(second)
        time.sleep(1)
        self.assertEqual([m['text'] for m in self.thread('e2e-send-order')['messages'] if m['from'] == 'owner'], [])
        self.faulty.cut = 0
        self.arrived('e2e-send-order', second)
        self.arrived('e2e-send-order', first)
        self.assertEqual([m['text'] for m in self.thread('e2e-send-order')['messages'] if m['from'] == 'owner'], [first, second])

    def test_an_answer_he_chose_goes_once_when_the_page_was_taken_away_inside_its_four_seconds(self):
        """One press chooses an answer, and four seconds are his to take it back. Leaving the page sends it at
        once (a request that outlives the page). Snap takes the renderer away with no word to the page: the answer
        then goes when the page is back, and in both cases the thread holds it once."""
        for tid, title, told in (('e2e-send-held', 'בחירה שנקטעה', True), ('e2e-send-held-2', 'בחירה שנקטעה בלי הודעה לדף', False)):
            with self.subTest(the_page_was_told=told):
                self.calm()
                self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
                self.ok('ask', tid, 'לאשר את המיזוג?', '--options', 'כן למזג,לא עכשיו')
                self.browser.open('about:blank')
                self.open_thread(SIZES[2], tid, title)
                self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&quickAnswers().length===2)', what='the two answers')
                if told:
                    self.browser.press('Digit1')                                # from the empty composer: one press chooses
                    cid = self.browser.wait('JSON.stringify(heldAnswer()?heldAnswer().cid:"")', what='the answer inside its four seconds')
                else:
                    # The renderer is taken away inside the four seconds: its clock stops with it, and the page
                    # hears nothing of its own end. What stays is what the browser's store holds.
                    cid = self.browser.eval('(()=>{quickAnswers()[0].click();const m=heldAnswer();clearTimeout(m.held);m.go=null;'
                                            'window.addEventListener("pagehide",e=>e.stopImmediatePropagation(),true);return m.cid;})()')
                    self.assertEqual(self.browser.eval('JSON.stringify(JSON.parse(store.get("slack-outbox","[]")).flatMap(row=>row[1]).filter(m=>m.cid===%s).map(m=>m.delivery))' % json.dumps(cid)), ['holding'])
                self.browser.open('about:blank')
                if not told:
                    time.sleep(1)
                    self.assertNotIn(cid, self.tries(), 'a page that was taken away sent nothing')
                self.open_thread(SIZES[2], tid, title)
                answers = lambda: [m['text'] for m in self.thread(tid)['messages'] if m['from'] == 'owner']
                self.until(lambda: answers(), timeout=40, what='the answer on the server, with no second press')
                self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!(optimistic.get(%s)||[]).some(m=>m.delivery!=="received"))' % json.dumps(tid), timeout=40, what='nothing left unsent on the page')
                time.sleep(1.5)
                self.assertEqual(answers(), ['כן למזג'])
                self.assertIn(cid, self.tries())

    def test_what_an_older_page_left_as_not_sent_is_not_sent_by_itself(self):
        """Before this change a message that failed stayed in the browser as "not sent" until he pressed. He may
        have written it again since: the new page must not send the old one hours later, behind his back."""
        self.topic('e2e-send-old', 'שאריות מהדף הישן')
        left = [['e2e-send-old', [{'cid': 'old-failed-1', 'from': 'owner', 'text': 'כן, מהדף הישן', 'ts': time.time() - 600, 'delivery': 'failed', 'inFlight': False,
                                   'error': 'אין תשובה מהשרת. ההודעה שמורה כאן', 'under': None},
                                  {'cid': 'old-sending-1', 'from': 'owner', 'text': 'נקטעה בדף הישן', 'ts': time.time() - 500, 'delivery': 'sending', 'inFlight': True, 'under': None}]]]
        self.browser.eval('(()=>{store.set("slack-outbox",%s);return "ok";})()' % json.dumps(json.dumps(left, ensure_ascii=False)))
        self.browser.open('about:blank')
        self.open_thread(SIZES[0], 'e2e-send-old', 'שאריות מהדף הישן')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&document.querySelectorAll("#log .msg.own.failed").length===2)', what='both leftovers shown as not sent')
        time.sleep(6)
        self.assertEqual([cid for cid in self.tries() if cid.startswith('old-')], [], 'nothing of it was sent')
        self.assertEqual([m for m in self.thread('e2e-send-old')['messages'] if m['from'] == 'owner'], [])
        for text in ('כן, מהדף הישן', 'נקטעה בדף הישן'):
            row = self.row(text)
            self.assertTrue(row['failed'], row)
            self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])

    def test_a_reply_that_alone_gets_no_answer_is_given_up_and_then_his_to_decide(self):
        """The hostile review: a reply the server cannot take in (it drops the request without a word) was tried
        every half minute for half a day, on a line that was fine all along. The page sees that the server answers
        everything else, stops after a few tries and says so. The replies behind it wait for him, and say why
        (suda-fixes 54: what he sent arrives in the order he sent it): once he deletes it, they go."""
        self.topic('e2e-send-deaf', 'הודעה שהשרת לא עונה לה')
        self.faulty.deaf = 'רעל'
        first, second = 'הודעה עם רעל שהשרת מפיל', 'הודעה רגילה שנכתבה אחריה'
        self.write(first)
        self.until(lambda: self.tries('deaf'), what='the first try')
        self.write(second)
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&row.classList.contains("failed"));})()' % json.dumps(first), timeout=90, what='the page to give up on the reply that gets no answer')
        row = self.row(first)
        self.assertIn('השרת לא עונה להודעה הזאת', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        tried = len(self.tries('deaf'))
        self.assertLessEqual(tried, 6, 'a few tries, not without end')
        self.assertIn('ההודעה שלפניה לא נשלחה', self.row(second)['says'])
        time.sleep(4)
        self.assertEqual(self.his('e2e-send-deaf', second), [], 'a later reply went past the one that failed')
        self.browser.eval('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          '[...row.querySelectorAll(".delivery button")].find(b=>b.textContent==="מחק").click();return "ok";})()' % json.dumps(first))
        self.arrived('e2e-send-deaf', second)
        time.sleep(4)
        self.assertEqual(len(self.tries('deaf')), tried, 'given up: no more tries by itself')
        self.assertEqual(self.his('e2e-send-deaf', first), [])

    def test_a_press_on_send_sends_the_reply_alone_with_no_draft_ahead_of_it(self):
        """ "Make the sending faster" (the owner, suda m352). A finger on the send button takes the focus out of the
        box first, and the page then sent the words twice: as a draft, and right behind it as the reply. The
        server takes the page's actions one at a time, so the reply waited for the draft. Now the press sends
        the reply alone; a box he really left still saves its draft."""
        self.topic('e2e-send-fast', 'שליחה בלי טיוטה לפניה')
        self.browser.eval('(()=>{window.SENT=[];const f=window.fetch;window.fetch=function(url,init){try{if(String(url).includes("/api/state"))SENT.push(JSON.parse(init.body).state.op);}catch{}return f.apply(this,arguments);};'
                          'const r=window.render;window.render=function(){SENT.push("(drawn)");return r.apply(this,arguments);};return "ok";})()')
        text = 'נשלחת לבד, בלי טיוטה לפניה'
        self.browser.eval('(()=>{const i=document.querySelector("#input");i.focus();i.value=%s;i.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()' % json.dumps(text))
        self.browser.eval('(()=>{const i=document.querySelector("#input");SENT.length=0;i.blur();document.querySelector("#send").click();return "ok";})()')     # as a finger does: out of the box, then the press
        self.arrived('e2e-send-fast', text)
        sent = self.browser.eval('JSON.stringify(SENT)')
        self.assertEqual([op for op in sent if op in ('draft', 'reply')], ['reply'], sent)
        # and the reply leaves before the page draws anything: on a phone a drawing takes long enough for the
        # screen to go dark, and the page to be taken away, with the reply still not on its way
        self.assertEqual(sent[0], 'reply', sent)
        # a box he left with words in it (no press on send) still saves them for his other devices
        self.browser.eval('(()=>{SENT.length=0;const i=document.querySelector("#input");i.focus();i.value="טיוטה שנשארת";i.dispatchEvent(new Event("input",{bubbles:true}));i.blur();return "ok";})()')
        self.browser.wait('JSON.stringify(SENT.includes("draft"))', timeout=10, what='the draft of a box he left')
        self.until(lambda: 'טיוטה שנשארת' in (self.board / 'drafts.json').read_text(encoding='utf-8') if (self.board / 'drafts.json').exists() else False, what='the draft on the server')

    def test_what_the_page_sends_does_not_wait_for_the_worker(self):
        """A reply must leave at once: on his phone the page is taken away the moment the screen goes dark. With a
        worker in charge of the page every request first waited for the worker (started again when it had been
        stopped); now the browser itself sends everything but the page's own file straight to the network."""
        self.topic('e2e-send-route', 'שליחה בלי לחכות ל-worker')
        if not self.browser.eval('JSON.stringify("serviceWorker" in navigator&&window.isSecureContext)'):
            self.skipTest('this browser allows no worker on a loopback page')
        self.browser.wait('(async()=>{await navigator.serviceWorker.ready;return JSON.stringify(!!navigator.serviceWorker.controller);})()', timeout=30, what='the worker in charge of the page')
        if not self.browser.eval('JSON.stringify("workerMatchedSourceType" in PerformanceResourceTiming.prototype)'):
            self.skipTest('this browser does not say which way a request of a worker\'s page took: ' + str(self.browser.eval('JSON.stringify(navigator.userAgent)')))
        self.open_thread(SIZES[0], 'e2e-send-route', 'שליחה בלי לחכות ל-worker')         # a load that the worker is in charge of from its start
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!navigator.serviceWorker.controller)', what='the state on a page of the worker')
        text = 'הודעה שלא עוברת דרך ה-worker'
        self.write(text)
        self.arrived('e2e-send-route', text)
        took = self.browser.eval('JSON.stringify(Object.fromEntries(performance.getEntriesByType("resource").filter(e=>/\\/api\\/state(\\?|$)|summary\\.json|\\/full\\/|\\/changes(\\.json|\\/)/.test(e.name))'
                                 '.map(e=>[new URL(e.name).pathname.replace(/^.*\\/(api\\/state|summary\\.json|full\\/.*|changes.*)$/,"$1").replace(/full\\/.*/,"full").replace(/changes.*/,"changes"),[e.workerMatchedSourceType,e.workerFinalSourceType]])))')
        self.assertEqual((took.get('api/state') or [])[:2], ['network', 'network'], took)       # the rule matched, and the network answered
        # what the page read after it: the summary, or (sse153) the change alone
        self.assertEqual((took.get('summary.json') or took.get('changes') or [])[:2], ['network', 'network'], took)
        # the page's own file is still the worker's: an opening is answered with the kept copy
        nav = self.browser.eval('(()=>{const n=performance.getEntriesByType("navigation")[0];return JSON.stringify([n.workerStart>0,n.workerMatchedSourceType||""]);})()')
        self.assertEqual(nav, [True, ''], nav)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Send.__dict__:
        setattr(Send, _name, None)


if __name__ == '__main__':
    unittest.main()
