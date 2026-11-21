#!/usr/bin/env python3
"""Hostile review of the page's automatic re-sending (suda.html, a9b8304..e40e44e): end to end.

The board server of test_e2e.py (loopback, a temporary board) behind a wire this file controls, for replies only:

  cut      the reply never reaches the server's handling (the line broke before it)
  lost     the server stores it, and its answer never reaches the page
  refuse   the server answers "no", with its reason
  status   an HTTP status and nothing stored (a gateway, a server in trouble, a wrong request)
  garbage  200 with a page that is not the board server's
  bare     200 {ok:false} and no receipt (a hook that broke)
  stored   the server takes it as it is
  hold     seconds the reply waits at the wire before any of the above

Every test states the CORRECT behaviour, so a FAIL is a hole; the ones named test_held_* are attacks that did
not get through. Nothing here binds beyond loopback or touches a real board.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import io
import json
from pathlib import Path
import re
import socket
import threading
import time
import unittest

import test_e2e
from test_e2e import SIZES, SLUG, png

ALWAYS = 10 ** 6
OUTBOX = SLUG + ':slack-outbox'
ROW = '[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s))'


class AdvSend(test_e2e.Suda):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Wire(base):
            guard = threading.Lock()
            rules = []          # {how, text, left, hold, ...}: the first one with tries left whose text is in the request
            seen = []           # one row for every reply that came in: {cid, body, how, at, n}
            live = {}           # cid → tries of it in the wire's hands right now
            peak = {}           # cid → the most at once
            slow_state = 0.0    # seconds every read of the state waits (a slow line at a load)

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
                # A line that is down is down for readings too (after the review the page tells "the line is down"
                # from "the server answers everything but this message", and gives up only on the second). A rule
                # marked `only` is that second case: one reply gets no answer, the rest of the line is fine.
                if re.search(r'/(summary|state)\.json|/full/', self.path):
                    with Wire.guard:
                        down = any(r['how'] == 'cut' and r['left'] > 0 and not r.get('only') and not r.get('hold') for r in Wire.rules)
                    if down:
                        return self.drop()
                if Wire.slow_state and re.search(r'/(summary|state)\.json', self.path):
                    time.sleep(Wire.slow_state)
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
                body, cid = raw.decode('utf-8', 'replace'), op.get('cid')
                with Wire.guard:
                    rule = next((r for r in Wire.rules if r['left'] > 0 and (r['text'] is None or r['text'] in body)), None)
                    how = rule['how'] if rule else 'stored'
                    if rule:
                        rule['left'] -= 1
                    Wire.seen.append({'cid': cid, 'body': body, 'how': how, 'at': time.monotonic(), 'n': sum(e['cid'] == cid for e in Wire.seen) + 1,
                                      'keepalive': None, 'op': op})
                    Wire.live[cid] = Wire.live.get(cid, 0) + 1
                    Wire.peak[cid] = max(Wire.peak.get(cid, 0), Wire.live[cid])
                try:
                    if rule and rule.get('hold'):
                        time.sleep(rule['hold'])
                    if how == 'cut':
                        return self.drop()
                    if how == 'refuse':
                        return self._json({'ok': False, 'applied': False, 'code': 1, 'out': [json.dumps({'ok': False, 'error': rule['reason']}, ensure_ascii=False)]})
                    if how == 'status':
                        return self._json({'ok': False, 'applied': False}, rule['status'])
                    if how == 'bare':
                        return self._json({'ok': False, 'applied': False, 'code': 1, 'out': ['Traceback (most recent call last):', "KeyError: 'x'"]})
                    if how == 'garbage':
                        page = b'<html><body>502 Bad Gateway</body></html>'
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html')
                        self.send_header('Content-Length', str(len(page)))
                        self.end_headers()
                        self.wfile.write(page)
                        return None
                    if how == 'lost':
                        real, self.wfile = self.wfile, io.BytesIO()
                        try:
                            super().do_POST()
                        finally:
                            self.wfile = real
                        return self.drop()
                    return super().do_POST()
                finally:
                    with Wire.guard:
                        Wire.live[cid] = max(0, Wire.live.get(cid, 1) - 1)       # a test that ended meanwhile cleared the count
        cls.wire = Wire
        cls.server.RequestHandlerClass = Wire

    # ── the wire ─────────────────────────────────────────────────────────────

    def setUp(self):
        self.one_tab()
        self.blank()
        self.calm()
        self.addCleanup(self.calm)
        self.addCleanup(self.one_tab)

    def calm(self):
        with self.wire.guard:
            del self.wire.rules[:]
            del self.wire.seen[:]
            self.wire.live.clear()
            self.wire.peak.clear()
            self.wire.slow_state = 0.0

    def rule(self, how, text=None, left=ALWAYS, hold=0, **more):
        with self.wire.guard:
            self.wire.rules.append(dict(more, how=how, text=text, left=left, hold=hold))

    def no_rules(self):
        with self.wire.guard:
            del self.wire.rules[:]

    def tries(self, text=None, how=None, cid=None):
        with self.wire.guard:
            return [e for e in self.wire.seen if (text is None or text in e['body']) and (how is None or e['how'] == how) and (cid is None or e['cid'] == cid)]

    # ── the browser ──────────────────────────────────────────────────────────

    def one_tab(self):
        """Only the first tab stays, and it is the one the next command talks to."""
        tabs = json.loads(self.browser.run('tab', 'list', '--json').stdout)['data']['tabs']
        for tab in tabs[1:]:
            self.browser.run('tab', 'close', tab['tabId'], check=False)
        self.browser.run('tab', tabs[0]['tabId'], check=False)

    def blank(self, outbox=None, forget=False):
        """A document of the board's own origin that is not the page: what the browser keeps for the page is set
        here, before the page loads. `outbox`: the unsent messages it will find; `forget`: no kept copy of the state."""
        self.browser.open(self.origin + '/' + SLUG + '/state.json')
        self.browser.eval('(async()=>{%s%s return "ok";})()' % (
            'localStorage.setItem(%s,%s);' % (json.dumps(OUTBOX), json.dumps(json.dumps(outbox, ensure_ascii=False))) if outbox is not None
            else 'localStorage.removeItem(%s);' % json.dumps(OUTBOX),
            'await new Promise(done=>{const r=indexedDB.deleteDatabase("suda-kept");r.onsuccess=r.onerror=r.onblocked=()=>done();});' if forget else ''))

    def show(self, tid, title, size=SIZES[0], synced=True):
        self.open_thread(size, tid, title)
        if synced:
            self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', what='the server\'s state on the page')

    def topic(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.show(tid, title)

    def write(self, text):
        self.browser.fill('#input', text)
        self.browser.click('#send')

    def nudge(self):
        """What tells the page that the line may be back: the browser is online, he is on the page again."""
        self.browser.eval('(()=>{window.dispatchEvent(new Event("online"));document.dispatchEvent(new Event("visibilitychange"));return "ok";})()')

    def row(self, text):
        return self.browser.eval('(()=>{const row=' + ROW % json.dumps(text) + ';if(!row)return JSON.stringify(null);'
                                 'const line=row.querySelector(".delivery");return JSON.stringify({failed:row.classList.contains("failed"),unsent:row.classList.contains("unsent"),'
                                 'says:line?line.innerText:"",buttons:line?[...line.querySelectorAll("button")].map(b=>b.textContent):[]});})()')

    def row_says(self, text, words, timeout=30):
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.innerText.includes(%s));})()' % json.dumps(words),
                          timeout=timeout, what='the row of %r to say %r' % (text[:30], words))

    def press(self, text, label, timeout=30):
        """A button of his message's own line, pressed as soon as it is there."""
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';const b=row&&[...row.querySelectorAll(".delivery button")].find(b=>b.textContent===%s);'
                          'if(!b)return JSON.stringify(false);b.click();return JSON.stringify(true);})()' % json.dumps(label), timeout=timeout, what='the button %r of %r' % (label, text[:30]))

    def mine(self, tid):
        return self.browser.eval('JSON.stringify((optimistic.get(%s)||[]).map(m=>({cid:m.cid,text:m.text,delivery:m.delivery,inFlight:!!m.inFlight,tries:m.tries||0,heard:m.heard||0,final:!!m.final,error:m.error||""})))' % json.dumps(tid))

    def his(self, tid):
        """His messages in the thread on the server, in the server's order: the text, or what else the message is."""
        return [m['text'] or ('<voice>' if m.get('voice') else '<snippet>' if m.get('snippet') else '') for m in self.thread(tid)['messages'] if m['from'] == 'owner']

    def arrived(self, tid, text, timeout=60):
        self.until(lambda: text in self.his(tid), timeout=timeout, what='%r on the server, with no press' % text[:30])
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&!row.classList.contains("failed")&&!/לא נשלח|מנסה שוב|שולח/.test(row.innerText));})()',
                          timeout=timeout, what='%r shown as received' % text[:30])
        time.sleep(1.5)
        self.assertEqual(self.his(tid).count(text), 1, 'the reply is in the thread exactly once')

    def never(self, probe, seconds, what):
        """`probe()` stays empty for `seconds`; what it gave, the moment it gave something."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            got = probe()
            if got:
                self.fail(what + ': ' + repr(got)[:300])
            time.sleep(0.4)

    # ══ holes ════════════════════════════════════════════════════════════════

    def test_a_reply_written_while_the_one_before_it_is_still_on_its_way_arrives_after_it(self):
        """Two replies in a row on a bad line. The first is still on its way (nothing has come back yet) when he
        sends the second; the first try of the first then breaks, and the page sends it again. His order must
        hold on the server."""
        tid = 'adv-order-fly'
        self.topic(tid, 'שתיים ברצף על קו רע')
        first, second = 'ראשונה: נשלחה ונתקעה בדרך', 'שנייה: נכתבה מיד אחריה'
        self.rule('cut', text=first, hold=3, left=1)             # the first try hangs three seconds, then the line breaks
        self.write(first)
        self.until(lambda: self.tries(first), what='the first reply on its way')
        self.write(second)
        self.arrived(tid, second)
        self.arrived(tid, first)
        self.assertEqual(self.his(tid), [first, second], 'the server holds his replies in another order than he wrote them')

    def test_a_recording_made_while_an_earlier_reply_waits_for_the_line_does_not_overtake_it(self):
        """A typed reply waits for the line (the page is trying again). A recording made after it goes through
        deliver() directly, not through the queue of the thread."""
        self.needs('voice')
        tid = 'adv-order-voice'
        self.topic(tid, 'הקלטה אחרי הודעה שמחכה')
        if not self.browser.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.skipTest('this browser has no microphone API on a loopback page')
        first = 'כתבתי את זה לפני ההקלטה'
        self.rule('cut', text=first)
        self.write(first)
        self.row_says(first, 'מנסה שוב')
        self.browser.wait('JSON.stringify(!!document.querySelector("#mic").offsetParent)', what='the record button')
        self.browser.pointer('#mic', 'pointerdown')
        time.sleep(3)
        self.browser.pointer('#mic', 'pointerup')
        self.browser.wait('JSON.stringify((optimistic.get(%s)||[]).some(m=>m.voice))' % json.dumps(tid), what='the recording among his unsent messages')
        self.never(lambda: [x for x in self.his(tid) if x != first] if first not in self.his(tid) else None, 20,
                   'the recording is on the server before the reply he wrote before it')
        self.no_rules()
        self.until(lambda: len(self.his(tid)) == 2, timeout=60, what='both on the server')
        self.assertEqual(self.his(tid)[0], first)

    def test_try_now_on_a_later_reply_does_not_send_it_before_the_earlier_one(self):
        """Two replies wait for the line, in his order. "נסה עכשיו" on the second one sends that one alone."""
        tid = 'adv-order-now'
        self.topic(tid, 'נסה עכשיו על השנייה')
        first, second = 'ראשונה: מחכה לקו', 'שנייה: מחכה מאחוריה'
        self.rule('cut', text=first)
        self.write(first)
        self.row_says(first, 'מנסה שוב')
        self.write(second)
        self.row_says(second, 'יישלח אחרי ההודעה הקודמת')          # not tried yet: it waits its turn behind the first, and says so (suda-fixes 20)
        self.press(second, 'נסה עכשיו')
        self.never(lambda: self.his(tid) if first not in self.his(tid) else None, 12, 'the second reply is on the server before the first')
        self.no_rules()
        self.arrived(tid, first)
        self.arrived(tid, second)
        self.assertEqual(self.his(tid), [first, second])

    def test_a_reply_he_deleted_in_one_tab_is_not_sent_by_another_tab_of_the_same_browser(self):
        """The line is down and his reply waits. He opens the board in a second tab (to see whether the server is
        alive): that tab finds the reply in the browser's store and tries it too. He deletes the reply in the first
        tab. It is deleted: no tab may send it when the line is back."""
        tid = 'adv-two-tabs'
        self.topic(tid, 'שתי לשוניות והודעה שנמחקה')
        text = 'הודעה שמחקתי לפני שהקו חזר'
        self.rule('cut', text=text)
        self.write(text)
        self.row_says(text, 'מנסה שוב')
        first_tab = next(t['tabId'] for t in json.loads(self.browser.run('tab', 'list', '--json').stdout)['data']['tabs'] if t['active'])
        self.browser.run('tab', 'new', '--label', 'other', self.url + '?s=other&n=1#' + tid)
        self.browser.wait('JSON.stringify(typeof optimistic!=="undefined"&&(optimistic.get(%s)||[]).some(m=>m.text===%s))' % (json.dumps(tid), json.dumps(text)),
                          timeout=40, what='the second tab to find the reply in the browser\'s store')
        self.browser.run('tab', first_tab)
        self.press(text, 'מחק')
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!row);})()', what='the reply gone from the first tab')
        self.assertEqual(self.mine(tid), [])
        self.no_rules()                                             # the line is back
        self.never(lambda: [x for x in self.his(tid) if x == text], 50, 'the reply he deleted reached the server (another tab sent it)')

    def test_after_a_reload_a_reply_with_a_picture_still_arrives_before_the_one_written_after_it(self):
        """A reply with a picture, then a reply with words, both cut; the page is loaded again (Snap). The picture
        comes back from the device's store a moment after the load; the words must wait for it."""
        self.needs('images')
        tid = 'adv-order-pic'
        self.topic(tid, 'תמונה ואחריה מילים, והדף נטען מחדש')
        shot = Path(self.tmp.name) / 'adv-shot.png'
        shot.write_bytes(png(320, 200))
        self.rule('cut')
        first, second = 'קודם: צילום המסך', 'אחר כך: ההסבר'
        self.browser.upload('#pic-file', shot)
        self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===1)', what='the picture in the tray')
        self.write(first)
        self.until(lambda: self.tries(first), what='the reply with the picture on its way')
        self.write(second)
        self.browser.wait('JSON.stringify((optimistic.get(%s)||[]).length===2)' % json.dumps(tid), what='both among his unsent messages')
        time.sleep(1.5)                                             # the picture is in the device's store
        self.browser.open('about:blank')
        self.no_rules()
        self.show(tid, 'תמונה ואחריה מילים, והדף נטען מחדש')
        self.arrived(tid, first)
        self.arrived(tid, second)
        stored = next(m for m in self.thread(tid)['messages'] if m['text'] == first)
        self.assertEqual([(i['w'], i['h']) for i in stored.get('images') or []], [(320, 200)], 'the picture went with its reply')
        self.assertEqual(self.his(tid), [first, second], 'the server holds his replies in another order than he wrote them')

    def quote_after_reload(self, tid, slow, forget):
        """A reply to a marked excerpt was on its way when the page went away. What the server stores when the page
        sends it again by itself, beside what it stores for the same reply sent from a page that is fully loaded."""
        title = 'תשובה לקטע מסומן ' + tid
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'יש מה לצטט', '--by', 'tower', input='שורה ראשונה של המגדל\n\nשורה שנייה של המגדל'), 'm1')
        words, excerpt = 'זו התשובה שלי לשורה השנייה', 'שורה שנייה של המגדל'
        shape = lambda m: (m['text'], (m.get('reply_to') or {}).get('id'), (m.get('reply_to') or {}).get('quote'))
        find = lambda cid: next((m for m in self.thread(tid)['messages'] if m.get('cid') == cid), None)
        # the same reply from a page that is fully loaded: what he meant
        self.show(tid, title)
        self.browser.eval('(()=>{const id=%s,msg={cid:"adv-quote-ref-"+id,from:"owner",text:%s,ts:now(),delivery:"sending",reply_to:"m1",quote:%s,under:null};'
                          'const list=optimistic.get(id)||[];list.push(msg);optimistic.set(id,list);persistOutbox();deliver(id,msg);return "ok";})()'
                          % (json.dumps(tid), json.dumps(words), json.dumps(excerpt)))
        meant = shape(self.until(lambda: find('adv-quote-ref-' + tid), timeout=40, what='the reply from the loaded page'))
        self.assertEqual(meant, (words, 'm1', excerpt))
        # the page went away while the same reply (another id) was on its way; it comes back and sends it by itself
        cid = 'adv-quote-again-' + tid
        entry = {'cid': cid, 'from': 'owner', 'text': words, 'ts': time.time() - 20, 'delivery': 'sending', 'auto': True, 'inFlight': True, 'reply_to': 'm1', 'quote': excerpt, 'under': None}
        self.blank(outbox=[[tid, [entry]]], forget=forget)
        self.wire.slow_state = slow
        self.show(tid, title, synced=False)
        got = shape(self.until(lambda: find(cid), timeout=60, what='the reply sent again by the page'))
        when = self.browser.eval('JSON.stringify({posts:performance.getEntriesByType("resource").filter(e=>/api\\/state$/.test(e.name)).map(e=>Math.round(e.startTime)),'
                                 'state:performance.getEntriesByName("suda:synced").map(e=>Math.round(e.startTime))})')
        self.assertEqual(got, meant, 'the reply the page sent again by itself is not the reply he wrote (ms since the load: its requests %s, the state %s)' % (when['posts'], when['state']))

    def test_a_reply_to_a_marked_excerpt_goes_again_as_he_wrote_it_when_the_state_is_slow_to_come(self):
        """No copy of the state on this device, and the state takes four seconds (a phone that just woke up)."""
        self.needs('quote')
        self.quote_after_reload('adv-quote-slow', slow=4, forget=True)

    def test_a_reply_to_a_marked_excerpt_goes_again_as_he_wrote_it_on_a_device_with_no_kept_copy(self):
        """No copy of the state on this device, and a line as fast as loopback."""
        self.needs('quote')
        self.quote_after_reload('adv-quote-fresh', slow=0, forget=True)

    def test_a_reply_to_a_marked_excerpt_goes_again_as_he_wrote_it_when_this_device_kept_a_copy_of_the_state(self):
        """The same on a device that kept a copy of the state from the last time (the usual case), on a slow line:
        the server's line opens before the kept copy has been read from the device's store."""
        self.needs('quote')
        self.quote_after_reload('adv-quote-kept', slow=4, forget=False)

    def test_two_replies_that_wait_for_the_line_do_not_keep_the_page_awake(self):
        """Two replies of one thread wait for the line. Until the next try of the first is due, nothing is to be
        done: the page must not wake up twenty times a second to find that out."""
        tid = 'adv-spin'
        self.topic(tid, 'שתי הודעות מחכות לקו')
        self.rule('cut')
        first, second = 'ראשונה: מחכה', 'שנייה: מחכה מאחוריה'
        self.write(first)
        self.until(lambda: len(self.tries(first)) >= 3, timeout=40, what='three tries of the first (its next one is ten seconds away)')
        self.write(second)
        self.browser.wait('JSON.stringify((optimistic.get(%s)||[]).filter(m=>m.delivery==="waiting"&&!m.inFlight).length===2)' % json.dumps(tid), what='both waiting')
        self.browser.eval('(()=>{window.__again=0;const real=sendAgain;sendAgain=function(all){window.__again++;return real(all);};return "ok";})()')
        time.sleep(4)
        woke, sent = self.browser.eval('JSON.stringify(window.__again)'), len(self.tries())
        self.assertLessEqual(woke, 8, 'in four seconds with nothing due the page ran its sending round %d times (%d requests reached the server meanwhile)' % (woke, sent))

    def test_what_the_page_before_this_showed_as_refused_is_not_stored_by_the_new_page_without_his_press(self):
        """The page before this change kept a refusal as {delivery:'failed', error:<the server's reason>} with no
        `final`. He saw "לא נשלח: השרשור סגור" and left it. The thread was opened again since. The new page loads."""
        tid = 'adv-legacy'
        title = 'הודעה שהדף הקודם סימן כמסורבת'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        text = 'הודעה שהשרת סירב לה לפני שלוש שעות'
        entry = {'cid': 'adv-legacy-1', 'from': 'owner', 'text': text, 'ts': time.time() - 3 * 3600, 'delivery': 'failed', 'inFlight': False, 'error': 'השרשור סגור', 'under': None}
        self.blank(outbox=[[tid, [entry]]])
        self.show(tid, title)
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row);})()', what='his unsent reply on the page')
        self.never(lambda: self.tries(cid='adv-legacy-1') and [(e['how'], e['n']) for e in self.tries(cid='adv-legacy-1')], 8, 'the page sent by itself a reply that the server had refused')
        self.assertEqual(self.his(tid), [])
        row = self.row(text)
        self.assertTrue(row['failed'], row)
        self.assertIn('השרשור סגור', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])

    def test_a_reply_the_state_already_holds_is_not_sent_again_at_a_load(self):
        """The server took the reply and its answer was lost with the page. At the next load the state already
        holds it: the page was to wait a moment for the state (RESTORE_WAIT) before sending anything again."""
        tid = 'adv-restore-wait'
        title = 'ההודעה כבר אצל השרת'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        text, cid = 'השרת כבר מחזיק את ההודעה הזאת', 'adv-restore-wait-1'
        status, result, receipt = self.post({'op': 'reply', 'thread': tid, 'cid': cid, 'text': text, 'under': None})
        self.assertTrue(receipt.get('ok'), (status, result))
        self.calm()
        entry = {'cid': cid, 'from': 'owner', 'text': text, 'ts': time.time() - 5, 'delivery': 'sending', 'auto': True, 'inFlight': True, 'under': None}
        self.blank(outbox=[[tid, [entry]]])
        self.wire.slow_state = 2                                    # the state comes within the 2.5 s the page says it waits for it
        self.show(tid, title, synced=False)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', timeout=30, what='the server\'s state on the page')
        time.sleep(4)
        self.assertEqual(self.his(tid), [text])
        self.assertEqual(self.mine(tid), [], 'the page still holds as unsent a reply that the state shows')
        self.assertEqual([(e['how'], e['n']) for e in self.tries(cid=cid)], [], 'the page did not wait for the state: it sent again a reply that the state already holds')

    def test_a_request_to_run_a_command_pressed_eleven_hours_ago_is_not_sent_by_the_page_at_a_load(self):
        """A press on "run" asks the tower to run a command on the Mac. The press was cut in the morning; nothing
        else was said in the thread since, so the server's own guard (`last`) lets it through. In the evening the
        page loads. (A decision more than a bug: is half a day the right window for THIS kind of message?)"""
        self.needs('run')
        tid, title = 'adv-run-late', 'בקשת הרצה מהבוקר'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'יש פקודה', '--by', 'tower', input=self.TOWER_TEXT), 'm1')
        digest = hashlib.sha256(test_e2e.command_of(self.TOWER_TEXT, 0).encode()).hexdigest()
        entry = {'cid': 'adv-run-late-1', 'from': 'owner', 'text': '▶ הרץ את הפקודה מהודעה m1', 'ts': time.time() - 11 * 3600, 'delivery': 'sending', 'auto': True, 'inFlight': True,
                 'under': None, 'run': {'msg_id': 'm1', 'block_index': 0, 'sha256': digest}, 'last': 'm1'}
        self.blank(outbox=[[tid, [entry]]])
        self.show(tid, title)
        self.never(lambda: [(r['text'], r['run']['command']) for r in self.pending() if r['thread'] == tid and r.get('run')], 12,
                   'the tower was asked to run a command he pressed eleven hours ago, with no press now')

    def test_an_entry_with_no_time_in_the_browsers_store_does_not_take_the_thread_down(self):
        """The stored outbox is read as it is. One entry whose `ts` is missing (or is not a number) is marked as not
        sent, which is right; but drawing it throws (timeNode: Invalid time value), so the conversation of that thread
        is not drawn at all, and a reply written there afterwards is never sent: deliver() draws before it posts.
        (The page before this change broke the same way: not a regression, but the new restore is where to mend it.)"""
        tid, title = 'adv-notime', 'רשומה בלי זמן'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'שלום', '--by', 'tower', input='הודעה של המגדל'), 'm1')
        bare = {'cid': 'adv-notime-1', 'from': 'owner', 'text': 'רשומה שאין לה זמן', 'delivery': 'waiting'}
        self.blank(outbox=[[tid, [bare]]])
        self.show(tid, title)
        time.sleep(4)
        self.assertEqual([(e['cid'], e['how']) for e in self.tries()], [], 'an entry with no time is never the page\'s to send')
        wrong = []
        if not self.browser.eval('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה של המגדל"))'):
            wrong.append('the conversation of the thread is not drawn')
        text = 'ועדיין אפשר לכתוב כאן'
        self.write(text)
        # it waits behind the entry nobody knows the fate of (his order, suda-fixes 54), and says so; he deletes that one, it goes
        try:
            self.row_says(text, 'ההודעה שלפניה לא נשלחה', timeout=10)
        except AssertionError as e:
            wrong.append('a reply written in that thread afterwards does not say what it waits for: %s' % str(e)[:200])
        self.assertEqual(wrong, [])
        self.press('רשומה שאין לה זמן', 'מחק')
        self.arrived(tid, text, timeout=25)

    def test_a_big_reply_on_a_line_that_answers_nothing_is_not_left_sending_without_end(self):
        """The 20 seconds after which the page gives up on a silent line are only for a request of up to 50 KB. A
        reply with a picture, a recording or a long paste has no limit: it stays "שולח…", with no button, for as long
        as the browser keeps the socket, and nothing tries it again. (The page before this change had no limit for
        any reply; what is asked here is that the big ones are not left out.)"""
        tid = 'adv-big-silent'
        self.topic(tid, 'הודעה גדולה על קו שלא עונה')
        self.rule('cut', text='adv-big-silent', hold=50, left=1)    # fifty seconds of silence, then the line breaks
        self.write('adv-big-silent ' + 'z' * 70000)
        self.until(lambda: self.tries('adv-big-silent'), what='the big reply on its way')
        time.sleep(32)
        state = self.mine(tid)
        buttons = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg.own .delivery button")].map(b=>b.textContent))')
        delivery = state[0]['delivery'] if state else 'with the server'        # after the review a large reply has its limit too, and may have arrived by now
        self.assertTrue(len(self.tries('adv-big-silent')) >= 2 or delivery != 'sending' or buttons,
                        'after 32 s of silence the reply is still %r, tried %d time(s), and its row offers %r' % (delivery, len(self.tries('adv-big-silent')), buttons))

    def test_a_reply_the_server_can_never_take_is_not_tried_without_end_and_does_not_hold_the_thread(self):
        """(Found by the server-side review; here at the page.) He marks words of a message and replies. The excerpt
        is cut at 500 UTF-16 units (excerptOf), and the cut lands inside an emoji: half a character. The board server
        cannot write that request and drops the connection with no answer, every time. For the page that is "no
        answer" (status 0), which never counts toward the six tries after which it leaves a server alone: it goes on
        every 30 s for half a day, the row says "trying again by itself", and every later reply of the thread waits
        behind it. The line itself is fine all along (the state is read, the server's line is open)."""
        self.needs('quote')
        tid, title = 'adv-poison', 'הודעה שהשרת לא יכול לקבל'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'יש מה לצטט', '--by', 'tower',
                                 input='a' * 498 + '\U0001F600' + ' ועוד כמה מילים אחרי הסמיילי'), 'm1')
        self.show(tid, title)
        # what the page does when he marks the whole message and presses "reply": after the review the excerpt is
        # cut by whole characters, so that way to such a reply is closed ...
        self.browser.eval('(()=>{startReply("m1",thread(%s).messages.find(m=>m.id==="m1").text);return "ok";})()' % json.dumps(tid))
        self.assertTrue(self.browser.eval('JSON.stringify(replyQuote(%s).isWellFormed())' % json.dumps(tid)), 'the excerpt ends in half a character')
        first, second = 'תשובה לקטע שסימנתי', 'הודעה רגילה שנכתבה אחריה'
        # ... and whatever else makes the server drop one reply without an answer, on a line that is fine, is played here
        self.rule('cut', text=first, only=True)
        self.write(first)
        self.row_says(first, 'מנסה שוב')
        self.write(second)
        for _ in range(14):                                         # the line "comes back" again and again: a try at each
            self.nudge()
            time.sleep(0.8)
        tried, row = len(self.tries(first)), self.row(first)
        left = len(list((self.board / 'state').glob('.state-*')))
        wrong = []
        if not (row or {}).get('failed'):
            wrong.append('after %d tries that got no answer, on a line that is otherwise fine (line open: %s), the page is still trying and the row says %r; '
                         '%d half-written files are left in the served state/ folder'
                         % (tried, self.browser.eval('JSON.stringify(online)'), (row or {}).get('says'), left))
        # what he wrote after it waits for his word on it, and says so (suda-fixes 54: his order); once he deletes it, it goes
        if second in self.his(tid):
            wrong.append('the reply written after it went past the one that failed')
        elif 'ההודעה שלפניה לא נשלחה' not in ((self.row(second) or {}).get('says') or ''):
            wrong.append('the reply written after it does not say what it waits for: %r' % (self.row(second) or {}).get('says'))
        self.assertEqual(wrong, [])
        self.press(first, 'מחק')
        self.arrived(tid, second)

    # ══ what held ════════════════════════════════════════════════════════════

    def test_held_a_reply_written_offline_goes_by_itself_when_the_browser_is_online_again(self):
        tid = 'adv-held-offline'
        self.topic(tid, 'נכתב בלי רשת')
        self.addCleanup(lambda: self.browser.run('set', 'offline', 'off', check=False))
        self.browser.run('set', 'offline', 'on')
        text = 'הודעה שנכתבה בלי רשת'
        self.write(text)
        self.row_says(text, 'מנסה שוב')
        row = self.row(text)
        self.assertEqual((row['failed'], row['unsent'], row['buttons']), (False, True, ['נסה עכשיו', 'מחק']), row)
        self.assertEqual(self.tries(text), [])
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#input").value)'), '')
        self.browser.run('set', 'offline', 'off')
        self.arrived(tid, text)
        self.assertEqual(len({e['cid'] for e in self.tries(text)}), 1)

    def test_held_a_reply_sent_in_the_moment_the_page_goes_away_arrives_once(self):
        tid, title = 'adv-held-leave', 'שלחתי והדף נלקח'
        self.topic(tid, title)
        text = 'שלחתי, ובאותו רגע הדף נלקח'
        self.browser.eval('(()=>{const el=document.querySelector("#input");el.focus();el.value=%s;el.dispatchEvent(new Event("input",{bubbles:true}));'
                          'document.querySelector("#send").click();location.href="about:blank";return "ok";})()' % json.dumps(text))
        self.until(lambda: text in self.his(tid), timeout=30, what='the reply on the server, although the page went away with the press')
        self.show(tid, title)
        time.sleep(5)
        self.assertEqual(self.his(tid).count(text), 1)
        self.assertEqual([m for m in self.mine(tid) if m['delivery'] != 'received'], [])

    def test_held_a_reply_he_deleted_while_the_page_was_trying_is_never_sent(self):
        tid = 'adv-held-delete'
        self.topic(tid, 'מחקתי בזמן שהדף ניסה')
        text = 'הודעה שמחקתי בזמן שהקו היה למטה'
        self.rule('cut', text=text)
        self.write(text)
        self.row_says(text, 'מנסה שוב')
        self.press(text, 'מחק')
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!row);})()', what='the reply gone')
        time.sleep(0.5)
        before = len(self.tries(text))
        self.no_rules()
        self.nudge()
        time.sleep(8)                                               # the try that was planned would have gone by now
        self.nudge()
        time.sleep(1)
        self.assertEqual(len(self.tries(text)), before, 'a try went after he deleted the reply')
        self.assertEqual(self.his(tid), [])
        self.browser.open('about:blank')                            # and a load does not bring it back
        self.show(tid, 'מחקתי בזמן שהדף ניסה')
        time.sleep(5)
        self.assertIsNone(self.row(text))
        self.assertEqual(len(self.tries(text)), before)
        self.assertEqual(self.his(tid), [])

    def test_held_what_the_server_refused_is_never_sent_again_by_itself_whatever_wakes_the_page(self):
        tid = 'adv-held-refused'
        self.topic(tid, 'סירוב, ואז כל מה שמעיר את הדף')
        text = 'הודעה שהשרת מסרב לה'
        self.rule('refuse', text=text, reason='השאלה הזאת כבר לא פתוחה')
        self.write(text)
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()', what='the refused reply marked as not sent')
        for _ in range(3):
            self.nudge()
            time.sleep(1)
        self.browser.open('about:blank')
        self.show(tid, 'סירוב, ואז כל מה שמעיר את הדף')
        time.sleep(5)                                               # longer than the wait of a load
        self.nudge()
        time.sleep(2)
        self.assertEqual([(e['how'], e['n']) for e in self.tries(text)], [('refuse', 1)])
        row = self.row(text)
        self.assertTrue(row['failed'], row)
        self.assertIn('השאלה הזאת כבר לא פתוחה', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        self.assertEqual(self.his(tid), [])

    def test_held_a_server_in_trouble_is_asked_six_times_and_then_left_alone(self):
        tid = 'adv-held-cap'
        self.topic(tid, 'שרת שעונה 503')
        text = 'הודעה לשרת שבצרות'
        self.rule('status', text=text, status=503)
        self.write(text)
        for _ in range(40):                                         # the line "comes back" again and again: no wait between tries
            if (self.row(text) or {}).get('failed'):
                break
            self.nudge()
            time.sleep(0.8)
        row = self.row(text)
        self.assertTrue(row and row['failed'], row)
        self.assertEqual(len(self.tries(text)), 6, 'RETRY_HEARD')
        for _ in range(4):
            self.nudge()
            time.sleep(0.6)
        self.browser.open('about:blank')
        self.show(tid, 'שרת שעונה 503')
        time.sleep(5)
        self.nudge()
        time.sleep(2)
        self.assertEqual(len(self.tries(text)), 6, 'the page went on asking a server that answered six times that it cannot')
        row = self.row(text)
        self.assertTrue(row['failed'], row)
        self.assertIn('לא נשלח', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        self.assertEqual(self.his(tid), [])
        self.no_rules()                                             # his own press still sends it
        self.press(text, 'נסה שוב')
        self.arrived(tid, text)

    def test_held_at_a_load_the_page_sends_nothing_that_is_old_taken_or_refused(self):
        tid = 'adv-held-load'
        title = 'מה שהדף מוצא בטעינה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        t = time.time()
        old = {'cid': 'adv-load-old', 'from': 'owner', 'text': 'נכתבה לפני שלוש עשרה שעות', 'ts': t - 13 * 3600, 'delivery': 'sending', 'auto': True, 'inFlight': True, 'under': None}
        taken = {'cid': 'adv-load-taken', 'from': 'owner', 'text': 'השרת אמר שקיבל אותה', 'ts': t - 60, 'delivery': 'received', 'id': 'm77', 'status': 'pending', 'under': None}
        refused = {'cid': 'adv-load-refused', 'from': 'owner', 'text': 'השרת סירב לה', 'ts': t - 60, 'delivery': 'failed', 'final': True, 'error': 'השרשור סגור', 'heard': 0, 'tries': 0, 'under': None}
        given_up = {'cid': 'adv-load-gave-up', 'from': 'owner', 'text': 'הדף התייאש ממנה', 'ts': t - 60, 'delivery': 'failed', 'final': True, 'error': 'לא ניתן לקרוא או לשמור את ההודעה', 'heard': 6, 'tries': 6, 'under': None}
        self.blank(outbox=[[tid, [old, taken, refused, given_up]]])
        self.show(tid, title)
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(old['text']) + ';return JSON.stringify(!!row);})()', what='the old reply on the page')
        time.sleep(6)
        self.nudge()
        time.sleep(2)
        self.assertEqual([(e['cid'], e['how']) for e in self.tries()], [])
        self.assertEqual(self.his(tid), [])
        row = self.row(old['text'])
        self.assertTrue(row['failed'], row)
        self.assertIn('לא ידוע אם ההודעה התקבלה', row['says'])
        self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        self.assertIn('השרשור סגור', self.row(refused['text'])['says'])
        self.assertEqual(self.row(given_up['text'])['buttons'], ['נסה שוב', 'מחק'])

    def test_held_one_reply_is_never_on_its_way_twice_at_once(self):
        tid = 'adv-held-once'
        self.topic(tid, 'ניסיון אחד בכל רגע')
        text = 'הודעה שהשרת לוקח לאט'
        self.rule('stored', text=text, hold=3)
        self.write(text)
        self.until(lambda: self.tries(text), what='the reply on its way')
        for _ in range(3):
            self.browser.eval('(()=>{const id=%s,m=(optimistic.get(id)||[])[0];if(m){deliver(id,m);deliver(id,m);}sendAgain(true);sendAgain(false);planAgain();'
                              'window.dispatchEvent(new Event("online"));document.dispatchEvent(new Event("visibilitychange"));return "ok";})()' % json.dumps(tid))
            time.sleep(0.4)
        self.arrived(tid, text)
        time.sleep(2)
        seen = self.tries(text)
        self.assertEqual(len(seen), 1, [(e['how'], e['n']) for e in seen])
        self.assertEqual(self.wire.peak.get(seen[0]['cid']), 1)

    def test_held_a_strange_answer_is_tried_again_and_a_plain_no_is_his(self):
        tid = 'adv-held-answers'
        self.topic(tid, 'תשובות משונות')
        gateway, broke, wrong = 'ענה שער ולא השרת', 'השרת נשבר בלי קבלה', 'הבקשה עצמה נדחתה'
        self.rule('garbage', text=gateway, left=2)
        self.rule('bare', text=broke)
        self.rule('status', text=wrong, status=404)
        self.write(gateway)
        self.arrived(tid, gateway)
        self.assertEqual([e['how'] for e in self.tries(gateway)], ['garbage', 'garbage', 'stored'])
        # each in a thread of its own: a failed one holds what comes after it in its thread (suda-fixes 54)
        for text in (broke, wrong):
            if text == wrong:
                self.topic(tid + '-2', 'תשובות משונות, שנייה')
            self.write(text)
            self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()', what='%r marked as not sent' % text)
        time.sleep(6)
        self.nudge()
        time.sleep(2)
        for text in (broke, wrong):
            self.assertEqual(len(self.tries(text)), 1, text)
            self.show(*((tid, 'תשובות משונות') if text == broke else (tid + '-2', 'תשובות משונות, שנייה')))
            row = self.row(text)
            self.assertIn('לא נשלח', row['says'])
            self.assertEqual(row['buttons'], ['נסה שוב', 'מחק'])
        self.assertEqual(self.his(tid), [gateway])

    def test_held_a_line_that_answers_nothing_is_given_up_after_twenty_seconds_and_the_reply_is_stored_once(self):
        tid = 'adv-held-limit'
        self.topic(tid, 'קו שלא עונה')
        text = 'הודעה על קו שלא עונה'
        self.rule('lost', text=text, hold=26, left=1)               # the first try: 26 s of silence, the server stores it, no answer
        self.write(text)
        self.row_says(text, 'שולח')
        self.until(lambda: len(self.tries(text)) >= 2, timeout=45, what='a second try while the first is still silent')
        first, second = self.tries(text)[:2]
        self.assertGreaterEqual(second['at'] - first['at'], 19)
        self.assertLess(second['at'] - first['at'], 26)
        self.arrived(tid, text, timeout=60)
        time.sleep(8)                                               # the silent first try has ended by now
        self.assertEqual(self.his(tid).count(text), 1)

    def test_held_two_replies_near_the_size_that_may_outlive_the_page_both_arrive_once(self):
        """A request that may outlive the page (keepalive) counts against 64KB for all of them together: a second
        big one while the first is on its way is refused by the browser itself, and must go again without it."""
        tid = 'adv-held-quota'
        self.topic(tid, 'שתי הודעות גדולות יחד')
        one, two = 'adv-big-one ' + 'x' * 44000, 'adv-big-two ' + 'y' * 44000
        self.rule('stored', text='adv-big-one', hold=3)
        self.write(one)
        self.until(lambda: self.tries('adv-big-one'), what='the first on its way')
        self.write(two)
        self.until(lambda: len([m for m in self.thread(tid)['messages'] if m['from'] == 'owner']) == 2, timeout=60, what='both on the server')
        time.sleep(3)
        self.assertEqual(len([m for m in self.thread(tid)['messages'] if m['from'] == 'owner']), 2)
        self.assertEqual(len({e['cid'] for e in self.tries()}), 2)
        self.assertEqual([m for m in self.mine(tid) if m['delivery'] != 'received'], [])

    def test_held_a_thread_that_closed_while_a_reply_waited_refuses_it_once_and_the_row_says_why(self):
        tid = 'adv-held-closed'
        self.topic(tid, 'הנושא נסגר בזמן שההודעה חיכתה')
        text = 'הודעה לנושא שנסגר בינתיים'
        self.rule('cut', text=text)
        self.write(text)
        self.row_says(text, 'מנסה שוב')
        self.ok('close', tid, '--by', 'tower', '--force')
        self.no_rules()
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()', timeout=60, what='the reply marked as not sent')
        before = len(self.tries(text))
        self.nudge()
        time.sleep(6)
        self.assertEqual(len(self.tries(text)), before)
        self.assertEqual(self.tries(text)[-1]['how'], 'stored')     # the wire let it through: the refusal is the server's own
        self.assertEqual(self.his(tid), [])
        self.assertIn('השרשור סגור', self.row(text)['says'])

    def test_held_a_reply_with_a_picture_cut_by_a_reload_arrives_whole_and_once(self):
        self.needs('images')
        tid = 'adv-held-pic'
        self.topic(tid, 'תמונה שנקטעה בטעינה מחדש')
        shot = Path(self.tmp.name) / 'adv-held-shot.png'
        shot.write_bytes(png(200, 120, shade=40))
        self.rule('cut')
        text = 'צילום מסך שנקטע'
        self.browser.upload('#pic-file', shot)
        self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===1)', what='the picture in the tray')
        self.browser.fill('.tray-caption[data-n="1"]', 'הכיתוב של התמונה')
        self.write(text)
        self.until(lambda: self.tries(text), what='the reply on its way')
        time.sleep(1.5)
        self.browser.open('about:blank')
        self.no_rules()
        self.show(tid, 'תמונה שנקטעה בטעינה מחדש')
        self.arrived(tid, text)
        stored = next(m for m in self.thread(tid)['messages'] if m['text'] == text)
        self.assertEqual([(i['w'], i['h'], i.get('caption')) for i in stored['images']], [(200, 120, 'הכיתוב של התמונה')])
        self.assertEqual(len({e['cid'] for e in self.tries(text)}), 1)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvSend.__dict__:
        setattr(AdvSend, _name, None)


if __name__ == '__main__':
    unittest.main()
