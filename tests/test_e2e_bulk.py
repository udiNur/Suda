#!/usr/bin/env python3
"""End to end: several threads chosen at once in the list, and one action for all of them (the owner, suda m644
and suda-fixes m50: "choose many chats and apply an action to them"; built in suda-fixes m53 from the approved
mockup, version 2).

- Cmd+click (Ctrl+click elsewhere) adds a thread to the choice or takes it out; Shift+click chooses a range.
- On a phone a long press starts the choice and every tap then adds or removes a thread.
- The chosen rows are marked (and say so to a screen reader: aria-selected); a panel (a sheet on the phone)
  says how many and offers: mark read, snooze, merge into one of them, close. Merge and close ask once more;
  close and snooze can be taken back from their notice.
- Esc or "נקה בחירה" lets go; a live refresh keeps the choice and drops only the rows that went.
Every action goes through the page's own ops (/api/state: seen, done, snooze, merge, close). The same harness as
test_e2e.py (headless Chrome, the real board server on loopback, a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

DESK, PHONE = SIZES[2], SIZES[0]
HOST = '.bulk-host:not([hidden])'
PICKED = 'JSON.stringify([...document.querySelectorAll("#channels .ch.picked")].map(b=>b.dataset.id).sort())'
SELECTED = 'JSON.stringify([...document.querySelectorAll("#channels .ch[aria-selected=true]")].map(b=>b.dataset.id).sort())'


def row(tid):
    return '#channels .ch[data-id=%s]' % json.dumps(tid)


class Bulk(test_e2e.Suda):

    def fresh(self, *ids, said=False):
        for tid in ids:
            self.ok('new', tid, 'נושא ' + tid, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            if said:
                self.ok('say', tid, '--from', 'fork', 'דוח: ' + tid)

    def open_list(self, size=DESK):
        self.open(size)
        self.browser.wait('JSON.stringify(synced&&!!document.querySelector("#channels .ch"))', what='the list')

    def mod_click(self, tid, **keys):
        keys = keys or {'metaKey': True}
        self.browser.eval('(()=>{const b=document.querySelector(%s);if(!b)throw Error("no row "+%s);'
                          'b.dispatchEvent(new MouseEvent("click",Object.assign({bubbles:true,cancelable:true,button:0},%s)));return "ok";})()'
                          % (json.dumps(row(tid)), json.dumps(tid), json.dumps(keys)))

    def press(self, what):
        self.browser.click(HOST + ' [data-bulk=%s]' % what)

    def picked(self):
        return self.browser.eval(PICKED)

    def bar(self):
        return self.browser.eval('JSON.stringify((document.querySelector(%s)||{}).innerText||"")' % json.dumps(HOST))

    def test_cmd_and_ctrl_click_choose_two_and_mark_them_read(self):
        self.fresh('bk-r1', 'bk-r2', 'bk-r3', said=True)
        self.open_list()
        self.browser.eval('(()=>{READ_ALL_MS=400;return "ok";})()')
        self.mod_click('bk-r1')
        self.mod_click('bk-r2', ctrlKey=True)
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-r1","bk-r2"]))' % PICKED, what='two rows chosen')
        self.assertEqual(self.browser.eval(SELECTED), ['bk-r1', 'bk-r2'], 'a screen reader hears which are chosen')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector(%s).getAttribute("aria-selected"))' % json.dumps(row('bk-r3'))), 'false')
        self.assertIn('2 נושאים נבחרו', self.bar())
        self.browser.run('screenshot', '/tmp/suda-bulk-desktop.png')
        # a second Cmd+click takes one out, and gives it back
        self.mod_click('bk-r2')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-r1"]))' % PICKED, what='one taken out')
        self.mod_click('bk-r2')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-r1","bk-r2"]))' % PICKED, what='and back')
        self.press('read')
        self.browser.wait('JSON.stringify(unreadOf(thread("bk-r1"))===0&&unreadOf(thread("bk-r2"))===0&&unreadOf(thread("bk-r3"))>0)', what='both read here')
        self.browser.wait('JSON.stringify(!document.querySelector(%s))' % json.dumps(HOST), what='the choice let go after the action')
        # the server hears it through the page's own op, once the time to take it back is over
        self.until(lambda: all(self.thread(t).get('seen') for t in ('bk-r1', 'bk-r2')), what='seen on the server')
        self.assertFalse(self.thread('bk-r3').get('seen'))

    def test_shift_click_chooses_a_range_and_snooze_puts_them_all_away_with_an_undo(self):
        self.fresh('bk-s1', 'bk-s2', 'bk-s3')
        self.open_list()
        order = self.browser.eval('JSON.stringify([...document.querySelectorAll("#channels .ch[data-id^=bk-s]")].map(b=>b.dataset.id))')
        self.mod_click(order[0])
        self.mod_click(order[2], shiftKey=True)
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-s1","bk-s2","bk-s3"]))' % PICKED, what='the range')
        snoozes = self.browser.eval('JSON.stringify([...document.querySelectorAll(%s)].map(b=>b.textContent.trim()))' % json.dumps(HOST + ' [data-bulk=snooze]'))
        self.assertEqual(snoozes, self.browser.eval('JSON.stringify(snoozePresets(now()).map(p=>p.label))'), 'the same times as the snooze of one thread')
        self.browser.click(HOST + ' [data-bulk=snooze]')
        self.until(lambda: all(self.thread(t).get('snooze') for t in ('bk-s1', 'bk-s2', 'bk-s3')), what='all three asleep')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(n=>n.innerText.includes("נודניק ל-3 נושאים")))', what='the notice')
        self.browser.eval('(()=>{const b=[...document.querySelectorAll(".toast .text-btn")].find(x=>x.textContent.includes("בטל"));if(!b)throw Error("no undo");b.click();return "ok";})()')
        self.until(lambda: not any(self.thread(t).get('snooze') for t in ('bk-s1', 'bk-s2', 'bk-s3')), what='all three awake again')

    def test_merge_into_one_of_them_asks_first(self):
        self.needs('merge')
        self.fresh('bk-m1', 'bk-m2', 'bk-m3')
        self.open_list()
        for tid in ('bk-m1', 'bk-m2', 'bk-m3'):
            self.mod_click(tid)
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-m1","bk-m2","bk-m3"]))' % PICKED, what='three chosen')
        self.browser.click(HOST + ' [data-bulk=merge][data-into=bk-m3]')
        ask = self.browser.wait('JSON.stringify((document.querySelector(%s)||{}).innerText||"")' % json.dumps(HOST + ' .bulk-confirm'), what='the question before the merge')
        self.assertIn('למזג 2 נושאים לתוך «נושא bk-m3»', ask)
        time.sleep(0.6)
        self.assertFalse(self.thread('bk-m1').get('merged_into'), 'merged before he said so')
        # "ביטול" goes back to the actions, with the choice kept
        self.press('cancel')
        self.browser.wait('JSON.stringify(!document.querySelector(%s))' % json.dumps(HOST + ' .bulk-confirm'), what='the question gone')
        self.assertEqual(self.picked(), ['bk-m1', 'bk-m2', 'bk-m3'])
        self.browser.click(HOST + ' [data-bulk=merge][data-into=bk-m3]')
        self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' .bulk-confirm'), what='asked again')
        self.press('ok')
        self.until(lambda: self.thread('bk-m1').get('merged_into') == 'bk-m3' and self.thread('bk-m2').get('merged_into') == 'bk-m3', what='both merged')
        self.assertEqual(self.thread('bk-m3')['status'], 'open')
        self.browser.wait('JSON.stringify(!document.querySelector(%s))' % json.dumps(HOST), what='the choice let go')

    def test_close_asks_first_and_its_notice_opens_them_again(self):
        self.fresh('bk-c1', 'bk-c2')
        self.open_list()
        self.mod_click('bk-c1')
        self.mod_click('bk-c2')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-c1","bk-c2"]))' % PICKED, what='two chosen')
        self.press('close')
        ask = self.browser.wait('JSON.stringify((document.querySelector(%s)||{}).innerText||"")' % json.dumps(HOST + ' .bulk-confirm'), what='the question before closing')
        self.assertIn('לסגור 2 נושאים?', ask)
        self.browser.run('screenshot', '/tmp/suda-bulk-confirm.png')
        time.sleep(0.6)
        self.assertEqual(self.thread('bk-c1')['status'], 'open', 'closed before he said so')
        self.press('ok')
        self.until(lambda: self.thread('bk-c1')['status'] == 'closed' and self.thread('bk-c2')['status'] == 'closed', what='both closed')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(n=>n.innerText.includes("2 נושאים נסגרו")))', what='the notice')
        self.browser.eval('(()=>{const b=[...document.querySelectorAll(".toast .text-btn")].find(x=>x.textContent.includes("פתח מחדש"));if(!b)throw Error("no undo");b.click();return "ok";})()')
        self.until(lambda: self.thread('bk-c1')['status'] == 'open' and self.thread('bk-c2')['status'] == 'open', what='both open again')

    def test_esc_and_the_clear_button_let_go(self):
        self.fresh('bk-e1', 'bk-e2')
        self.open_list()
        self.mod_click('bk-e1')
        self.mod_click('bk-e2')
        self.browser.wait('JSON.stringify(%s.length>2)' % PICKED, what='two chosen')
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(%s==="[]"&&!document.querySelector(%s))' % (PICKED, json.dumps(HOST)), what='Esc let go')
        # with a question open, Esc first takes the question back, and only then the choice
        self.mod_click('bk-e1')
        self.mod_click('bk-e2')
        self.press('close')
        self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' .bulk-confirm'), what='the question')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(!document.querySelector(%s)&&%s.length>2)' % (json.dumps(HOST + ' .bulk-confirm'), PICKED), what='the question gone, the choice kept')
        self.press('clear')
        self.browser.wait('JSON.stringify(%s==="[]")' % PICKED, what='the clear button let go')
        # a plain click opens the thread, as always
        self.browser.click(row('bk-e2'))
        self.browser.wait('JSON.stringify(view.ch==="bk-e2")', what='the thread opened')

    def test_on_the_phone_a_long_press_starts_choosing_and_taps_add(self):
        self.fresh('bk-p1', 'bk-p2', 'bk-p3')
        self.open_list(PHONE)
        self.browser.pointer(row('bk-p1'), 'pointerdown')
        time.sleep(0.9)
        self.browser.pointer(row('bk-p1'), 'pointerup')         # a real phone may send no click after a long press
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-p1"]))' % PICKED, what='chosen by the long press')
        self.assertTrue(self.browser.eval('JSON.stringify(document.getElementById("rename").hidden)'), 'a finger held on a row chooses, it does not rename')
        self.browser.click(row('bk-p3'))
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-p1","bk-p3"]))' % PICKED, what='a tap adds')
        self.assertFalse(self.browser.eval('JSON.stringify(!!view.ch)'), 'a tap while choosing opens nothing')
        self.assertTrue(self.browser.visible('#bulk-sheet'), 'the sheet under the list')
        self.assertIn('2 נבחרו', self.bar())
        self.browser.run('screenshot', '/tmp/suda-bulk-phone.png')
        self.browser.click(row('bk-p3'))
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-p1"]))' % PICKED, what='a tap takes out')
        # snooze from the sheet: its times open under it
        self.press('snooze-menu')
        self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' [data-bulk=snooze]'), what='the times')
        self.browser.click(HOST + ' [data-bulk=snooze]')
        self.until(lambda: self.thread('bk-p1').get('snooze'), what='asleep')
        self.assertFalse(self.thread('bk-p3').get('snooze'))

    def test_the_choice_survives_a_live_refresh_and_drops_a_row_that_went(self):
        self.fresh('bk-l1', 'bk-l2', 'bk-l3')
        self.open_list()
        for tid in ('bk-l1', 'bk-l2', 'bk-l3'):
            self.mod_click(tid)
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-l1","bk-l2","bk-l3"]))' % PICKED, what='three chosen')
        # an agent writes in one, and another is closed from the CLI: the list is drawn again from the server
        self.ok('say', 'bk-l1', '--from', 'fork', 'עדכון חי')
        self.ok('close', 'bk-l3')
        self.browser.wait('JSON.stringify(thread("bk-l1").messages.length===1&&thread("bk-l3").status==="closed")', what='the refresh')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-l1","bk-l2"]))' % PICKED, what='the choice after the refresh')
        self.assertIn('2 נושאים נבחרו', self.bar())


    # ── from the hostile review ──────────────────────────────────────────────

    def test_the_question_names_a_thread_with_something_he_has_not_read(self):
        self.fresh('bk-u1', 'bk-u2')
        self.ok('say', 'bk-u2', '--from', 'fork', 'שאלה שלא נקראה: להמשיך?')
        self.open_list()
        self.browser.wait('JSON.stringify(unreadOf(thread("bk-u2"))>0)', what='the new message on the page')
        self.mod_click('bk-u1')
        self.mod_click('bk-u2')
        self.press('close')
        ask = self.browser.wait('JSON.stringify((document.querySelector(%s)||{}).innerText||"")' % json.dumps(HOST + ' .bulk-confirm'), what='the question')
        self.assertIn('שלא קראת', ask)
        self.assertIn('«נושא bk-u2»', ask)
        self.assertNotIn('«נושא bk-u1»', ask)

    def test_what_the_server_refuses_stays_chosen_with_its_reason(self):
        self.fresh('bk-x1', 'bk-x2')
        self.ok('say', 'bk-x2', '--from', 'fork', 'ראשונה', '--state', 'working', '--note', 'x')
        self.ok('say', 'bk-x2', '--from', 'fork', 'שנייה', '--state', 'working', '--note', 'x')
        self.open_list()
        self.browser.wait('JSON.stringify(thread("bk-x2").messages.length===2)', what='both messages on the page')
        self.mod_click('bk-x1')
        self.mod_click('bk-x2')
        # the page has not seen the last message of bk-x2 (as when it lands between his look and his press)
        self.browser.eval('(()=>{thread("bk-x2").messages.pop();return "ok";})()')
        self.press('close')
        self.press('ok')
        self.until(lambda: self.thread('bk-x1')['status'] == 'closed', what='the one that could close')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-x2"]))' % PICKED, what='the refused one still chosen')
        self.assertEqual(self.thread('bk-x2')['status'], 'open')
        note = self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].map(n=>n.innerText).find(t=>t.includes("נושא אחד נסגר"))||"")', what='the notice')
        self.assertIn('«נושא bk-x2» לא: הגיעה הודעה חדשה', note)

    def test_a_merge_question_with_nothing_left_to_merge_goes_away(self):
        self.needs('merge')
        self.fresh('bk-g1', 'bk-g2')
        self.open_list()
        self.mod_click('bk-g1')
        self.mod_click('bk-g2')
        self.browser.click(HOST + ' [data-bulk=merge][data-into=bk-g2]')
        self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' .bulk-confirm'), what='the question')
        self.ok('close', 'bk-g1')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-g2"])&&!document.querySelector(%s))' % (PICKED, json.dumps(HOST + ' .bulk-confirm')),
                          what='the question gone with the thread it would merge')

    def test_a_snooze_time_is_taken_when_he_presses_not_when_the_panel_was_drawn(self):
        self.fresh('bk-t1', 'bk-t2', 'bk-t3')
        self.open_list()
        self.mod_click('bk-t1')
        self.mod_click('bk-t2')
        first = self.browser.eval('JSON.stringify(snoozePresets(now())[0].label)')
        # hours later the same button means a later time
        self.browser.eval('(()=>{const real=snoozePresets;snoozePresets=n=>real(n).map((p,i)=>i?p:{...p,until:n+7200});return "ok";})()')
        self.browser.eval('(()=>{[...document.querySelectorAll(%s)].find(b=>b.textContent.trim()===%s).click();return "ok";})()'
                          % (json.dumps(HOST + ' [data-bulk=snooze]'), json.dumps(first)))
        self.until(lambda: self.thread('bk-t1').get('snooze') and self.thread('bk-t2').get('snooze'), what='asleep')
        self.browser.wait('JSON.stringify(!bulkBusy&&!document.querySelector(%s))' % json.dumps(HOST), what='the run over')
        until, set_at = self.thread('bk-t1')['snooze']['until'], self.thread('bk-t1')['snooze']['set']
        self.assertGreater(until - set_at, 5400)
        # a time that is no longer offered (its evening passed) is refused here, not sent
        self.mod_click('bk-t3')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["bk-t3"]))' % PICKED, what='another one chosen')
        self.browser.eval('(()=>{snoozePresets=n=>[];return "ok";})()')
        self.browser.eval('(()=>{document.querySelector(%s).click();return "ok";})()' % json.dumps(HOST + ' [data-bulk=snooze]'))
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(n=>n.innerText.includes("הזמן הזה כבר עבר")))', what='the refusal')
        time.sleep(0.5)
        self.assertFalse(self.thread('bk-t3').get('snooze'))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Bulk.__dict__:
        setattr(Bulk, _name, None)


if __name__ == '__main__':
    unittest.main()
