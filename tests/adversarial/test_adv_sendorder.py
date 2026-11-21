#!/usr/bin/env python3
"""Hostile review of suda-fixes 54 (b005e40): what he sent arrives in the order he sent it.

The change: holdsOrder(m) (waiting, sending, in flight, an answer inside its undo, or failed and not a run request)
holds what came after it in waitsBehind, headDue and the sendAgain loop; waitReason/markBehind say why.

Every test states the SAFE outcome, so a FAIL is a hole. The ones named test_held_* are attacks that did not get
through (pinned). The e2e part uses the harness of test_adv_send_page.py (a loopback board server behind a wire
that can cut or refuse a reply by its words); nothing binds beyond 127.0.0.1 or touches a real board.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest

import test_e2e
import test_adv_send_page
from test_adv_send_page import ROW

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'


class SendOrderPure(unittest.TestCase):
    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_a_run_request_that_waits_for_its_next_try_is_not_held_by_a_failed_reply(self):
        """Hole: holdsOrder exempts a run request only once it has FAILED. A ▶ run request whose first try met a
        503 is 'waiting' for its next try; behind a reply of his that failed earlier in the thread, headDue never
        plans that try (Infinity), the sendAgain loop breaks at the failed reply before reaching it, and its row
        says "the one before it was not sent: send it again or delete it". The request was to go on its own
        (sendRun: "on its own, not behind a reply that waits"), and when he deletes the failed reply half an hour
        later it goes at once: deliver() never asks retries(), so the RETRY_RUN_FOR ten minutes are skipped and the
        tower runs a command he pressed long ago."""
        self.pure_js(r"""
        const failed={cid:'x',delivery:'failed',final:true,error:'השרשור סגור'};
        const run={cid:'r',delivery:'waiting',tries:1,due:5,run:{msg_id:'m1',block_index:0,sha256:'0'.repeat(64)}};
        assert.strictEqual(headDue([failed,run],true),5,'the next try of a run request is planned behind a failed reply');
        assert.strictEqual(waitReason([failed,run],run),'','a run request says it waits for a failed reply of his');
        """)

    def test_held_what_this_page_saw_of_the_wait_is_not_kept_in_the_browsers_store(self):
        """Pinned: `behind` is the page's own view of the moment. forStorage drops it, and unsentAtLoad drops it
        from what an older page left in the store, so a stale 'failed' reason never comes back at a load."""
        self.pure_js(r"""
        const m={cid:'y',from:'owner',text:'x',ts:1000,delivery:'waiting',auto:true,tries:0,behind:'failed'};
        assert.ok(!('behind' in forStorage(m)));
        assert.ok(!('behind' in unsentAtLoad(m,1010)));
        assert.ok(!('behind' in unsentAtLoad({...m,delivery:'failed',final:true},1010)));
        """)


class SendOrder(test_adv_send_page.AdvSend):
    """Only the scenarios of this file: the ones of the harness run in their own files."""

    def fails(self, text):
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()',
                          what='%r marked as not sent' % text[:30])

    def test_a_failed_reply_the_server_already_holds_does_not_hold_the_next_one(self):
        """Hole: the sendAgain loop breaks at a failed message BEFORE its "the state already holds it" check, which
        it does only for a waiting one. A reply the page gave up on may still have been stored (a gateway that
        answered 504 six times after the server took it, a big reply that reached the server after the page cut it,
        "unknown whether it arrived" at a load). The state shows it; the reply he wrote after it still waits behind
        it, saying "the one before it was not sent", for as long as he is in another thread (only drawing the
        thread itself, localOf, lets go of it). Before the change that reply went."""
        tid, other = 'so-held-landed', 'so-held-landed-elsewhere'
        title = 'נכשלה אבל השרת מחזיק אותה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', other, 'נושא אחר', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        first, second = 'הדף ויתר עליה אבל היא הגיעה', 'נכתבה אחריה ומחכה'
        status, result, receipt = self.post({'op': 'reply', 'thread': tid, 'cid': 'so-landed-1', 'text': first, 'under': None})
        self.assertTrue(receipt.get('ok'), (status, result))
        self.calm()
        t = time.time()
        x = {'cid': 'so-landed-1', 'from': 'owner', 'text': first, 'ts': t - 120, 'delivery': 'failed', 'final': True, 'auto': True,
             'error': 'השרת לא קיבל את ההודעה. היא שמורה כאן', 'heard': 6, 'tries': 6, 'under': None}
        y = {'cid': 'so-landed-2', 'from': 'owner', 'text': second, 'ts': t - 100, 'delivery': 'waiting', 'auto': True, 'tries': 1, 'due': 0, 'under': None}
        self.blank(outbox=[[tid, [x, y]]])
        self.show(other, 'נושא אחר')
        self.browser.wait('JSON.stringify(!!thread(%s)&&thread(%s).messages.some(m=>m.cid==="so-landed-1"))' % (json.dumps(tid), json.dumps(tid)),
                          what='the state on the page holds the reply the page gave up on')
        self.arrived_quietly(tid, second, 25)
        self.assertEqual(self.his(tid), [first, second])

    def arrived_quietly(self, tid, text, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end and text not in self.his(tid):
            time.sleep(0.5)
        self.assertIn(text, self.his(tid), 'the reply behind one the server already holds never went: %s' % self.mine(tid))

    def test_a_reply_waiting_behind_a_failed_one_offers_no_try_now_that_does_nothing(self):
        """Hole (minor): the row of a reply that waits behind a failed one says "send that one again or delete
        it", and next to it offers "נסה עכשיו". The press runs sendAgain(true), whose loop breaks at the failed
        one: nothing happens, nothing says why."""
        tid = 'so-try-now'
        self.topic(tid, 'נסה עכשיו מאחורי הודעה שנכשלה')
        first, second = 'נדחית ונשארת', 'מחכה מאחוריה'
        self.rule('refuse', text=first, reason='לא עכשיו')
        self.write(first)
        self.fails(first)
        self.write(second)
        self.row_says(second, 'ההודעה שלפניה לא נשלחה')
        row = self.row(second)
        self.assertNotIn('נסה עכשיו', row['buttons'], 'a button that can do nothing here: %r' % row)

    def test_a_run_request_is_not_held_behind_a_failed_reply(self):
        """Hole: the e2e of SendOrderPure's run test. A reply of his was refused. He presses ▶ on the tower's block;
        its first try meets a 503, so it waits for its next try, and that try never comes: the sendAgain loop
        breaks at the failed reply. The request was to go on its own (sendRun)."""
        self.needs('run')
        tid, title = 'so-run-behind', 'בקשת הרצה אחרי הודעה שנכשלה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'יש פקודה', '--by', 'tower', input=self.TOWER_TEXT), 'm1')
        self.show(tid, title)
        first = 'תשובה שהשרת דחה'
        self.rule('refuse', text=first, reason='לא עכשיו')
        self.rule('status', text='הרץ את הפקודה', status=503, left=1)
        self.write(first)
        self.fails(first)
        self.browser.wait('JSON.stringify([...document.querySelectorAll("button.run")].filter(b=>b.offsetParent).length===1)', what='the run button')
        self.browser.click('button.run')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the confirm sheet')
        self.browser.click('#run-ok')
        self.until(lambda: self.tries('הרץ את הפקודה'), what='the first try of the run request')
        end = time.monotonic() + 20
        while time.monotonic() < end and not [r for r in self.pending() if r['thread'] == tid and r.get('run')]:
            self.nudge()
            time.sleep(1)
        self.assertTrue([r for r in self.pending() if r['thread'] == tid and r.get('run')],
                        'the run request waits behind a failed reply of his: %s' % self.mine(tid))

    def test_a_reply_in_a_second_tab_does_not_go_past_one_that_failed_in_the_first(self):
        """Hole (minor; of the same kind before the change for one that waited): two tabs of the board, both open
        on the thread. In the first a reply is refused. In the second, which loaded before it, he writes the next
        one: that tab never heard of the failed one (outboxChanged only lets go of messages, it never takes in
        another tab's), so it sends at once. When he then presses "נסה שוב" in the first tab, the server holds
        them in the other order."""
        tid = 'so-two-tabs'
        title = 'שתי לשוניות והודעה שנכשלה'
        self.topic(tid, title)
        first_tab = next(t['tabId'] for t in json.loads(self.browser.run('tab', 'list', '--json').stdout)['data']['tabs'] if t['active'])
        self.browser.run('tab', 'new', '--label', 'other', self.url + '?s=other&n=%d#%s' % (int(time.time()), tid))
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!document.querySelector("#input").offsetParent)', timeout=40, what='the second tab')
        second_tab = next(t['tabId'] for t in json.loads(self.browser.run('tab', 'list', '--json').stdout)['data']['tabs'] if t['active'])
        first, second = 'נדחתה בלשונית הראשונה', 'נכתבה אחריה בלשונית השנייה'
        self.rule('refuse', text=first, reason='לא עכשיו', left=1)
        self.browser.run('tab', first_tab)
        self.write(first)
        self.fails(first)
        self.browser.run('tab', second_tab)
        self.write(second)
        self.never(lambda: self.his(tid), 8, 'a reply went past one that failed in another tab of the same browser')

    def test_the_line_under_an_answer_held_behind_a_failed_reply_does_not_promise_it_goes_in_a_moment(self):
        """Hole (minor): a reply of his was refused; he taps an answer. For its four seconds the answer's row says
        "נשלח בעוד רגע" (it goes in a moment), but it will not: it goes to wait behind the failed reply, until he
        sends that one again or deletes it. markBehind and waitReason are asked only of a waiting message."""
        tid = 'so-held-behind-failed'
        self.ok('new', tid, 'תשובה אחרי הודעה שנכשלה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', tid, 'לאשר את המיזוג?', '--options', 'כן למזג,לא עכשיו')
        self.show(tid, 'תשובה אחרי הודעה שנכשלה')
        self.browser.wait('JSON.stringify(quickAnswers().length===2)', what='the two answers')
        first = 'נכתבה לפני התשובה ונדחתה'
        self.rule('refuse', text=first, reason='לא עכשיו')
        self.write(first)
        self.fails(first)
        answer = self.browser.eval('(()=>{quickAnswers()[0].click();const m=heldAnswer();return m?m.text:"";})()')
        self.assertTrue(answer)
        says = self.row(answer)['says']
        self.assertNotIn('נשלח בעוד רגע', says, 'the held answer promises to go in a moment, behind a failed reply')

    def test_held_a_failed_reply_whose_picture_was_lost_can_still_be_deleted_and_the_queue_moves(self):
        """Pinned: a failed message whose picture this browser could not keep has no "נסה שוב" (lostPart), so its
        "מחק" is the only way to free the ones behind it. It is there, and the press frees them."""
        tid, title = 'so-lost-part', 'תמונה שאבדה ומה שאחריה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        t = time.time()
        x = {'cid': 'so-lost-1', 'from': 'owner', 'text': 'עם תמונה שאבדה', 'ts': t - 60, 'delivery': 'failed', 'final': True, 'auto': True,
             'error': 'התמונות של ההודעה הזאת לא נשמרו בדפדפן. צרף אותן שוב ושלח מחדש.', 'images': [{'name': 'a.png', 'lost': True}], 'under': None}
        second = 'נכתבה אחרי ההודעה עם התמונה'
        y = {'cid': 'so-lost-2', 'from': 'owner', 'text': second, 'ts': t - 50, 'delivery': 'waiting', 'auto': True, 'tries': 0, 'due': 0, 'under': None}
        self.blank(outbox=[[tid, [x, y]]])
        self.show(tid, title)
        self.row_says(second, 'ההודעה שלפניה לא נשלחה')
        self.assertEqual(self.row(x['text'])['buttons'], ['מחק'])
        self.never(lambda: self.his(tid), 5, 'a later message went past one that failed')
        self.press(x['text'], 'מחק')
        self.arrived(tid, second)


for _name in dir(test_adv_send_page.AdvSend):
    if _name.startswith('test') and _name not in SendOrder.__dict__:
        setattr(SendOrder, _name, None)


if __name__ == '__main__':
    unittest.main()
