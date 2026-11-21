#!/usr/bin/env python3
"""Hostile review of choosing many threads at once in Suda's list (suda m644). Every test asserts the SAFE outcome:
a failure here is a hole. Same harness as test_e2e_bulk.py (headless Chrome, the real board server on loopback,
a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES
import test_e2e_bulk
from test_e2e_bulk import HOST, PICKED, row


DESK, PHONE = SIZES[2], SIZES[0]
CONFIRM = HOST + ' .bulk-confirm'


class AdvBulk(test_e2e_bulk.Bulk):

    def ask_text(self):
        return self.browser.wait('JSON.stringify((document.querySelector(%s)||{}).innerText||"")' % json.dumps(CONFIRM), what='the question')

    # ── High: a message that lands while the question is on the screen ────────

    def test_close_does_not_swallow_a_message_that_landed_while_he_was_asked(self):
        self.fresh('av-c1', 'av-c2')
        self.open_list()
        self.mod_click('av-c1')
        self.mod_click('av-c2')
        self.press('close')
        before = self.ask_text()
        self.assertNotIn('שלא קראת', before)
        # an agent writes in av-c2 while the question is open; the live refresh brings it to the page
        self.ok('say', 'av-c2', '--from', 'fork', 'חשוב: אל תסגור, יש באג פתוח', '--state', 'on-owner', '--note', 'באג')
        self.browser.wait('JSON.stringify(thread("av-c2").messages.length===1)', what='the new message on the page')
        time.sleep(0.5)
        after = self.ask_text()
        self.press('ok')
        self.until(lambda: self.thread('av-c1')['status'] == 'closed', what='av-c1 closed')
        time.sleep(1.0)
        closed = self.thread('av-c2')['status'] == 'closed'
        self.assertFalse(closed and 'נושא av-c2' not in after,
                         'av-c2 was closed over a message he never saw, and the question never named it: %r' % after)

    def test_merge_does_not_swallow_a_message_that_landed_while_he_was_asked(self):
        self.needs('merge')
        self.fresh('av-m1', 'av-m2', 'av-m3')
        self.open_list()
        for tid in ('av-m1', 'av-m2', 'av-m3'):
            self.mod_click(tid)
        self.browser.click(HOST + ' [data-bulk=merge][data-into=av-m3]')
        self.ask_text()
        self.ok('say', 'av-m1', '--from', 'fork', 'שאלה: למחוק את הענף?', '--state', 'on-owner', '--note', 'שאלה')
        self.browser.wait('JSON.stringify(thread("av-m1").messages.length===1)', what='the new message on the page')
        time.sleep(0.5)
        after = self.ask_text()
        self.press('ok')
        self.until(lambda: self.thread('av-m2').get('merged_into') == 'av-m3', what='av-m2 merged')
        time.sleep(1.0)
        merged = self.thread('av-m1').get('merged_into') == 'av-m3'
        self.assertFalse(merged and 'נושא av-m1' not in after,
                         'av-m1 was merged over a message he never saw, and the question never named it: %r' % after)

    # ── Medium: the panel covers the conversation ──────────────────────────────

    def test_a_thread_opened_from_cmd_k_or_a_notice_while_choosing_is_shown(self):
        self.fresh('av-o1', 'av-o2', 'av-o3')
        self.open_list()
        self.mod_click('av-o1')
        self.mod_click('av-o2')
        self.browser.wait('JSON.stringify(%s.length>2)' % PICKED, what='two chosen')
        # what the palette's "go to" and a notification's link do
        self.browser.eval('(()=>{openChannel("av-o3");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="av-o3")', what='the thread opened')
        time.sleep(0.4)
        covered = self.browser.eval('JSON.stringify(!document.getElementById("bulk").hidden)')
        self.assertFalse(covered, 'the thread he asked for opened under the panel of the chosen ones: he cannot see it')

    def test_the_keys_never_go_to_a_reply_box_the_panel_covers(self):
        self.fresh('av-k1', 'av-k2', 'av-k3')
        self.open_thread(DESK, 'av-k3', 'נושא av-k3')
        self.mod_click('av-k1')
        self.mod_click('av-k2')
        self.browser.wait('JSON.stringify(!document.getElementById("bulk").hidden)', what='the panel')
        # Safari does not focus a clicked button: the keys are nowhere; a window focus or a refresh gives them back
        self.browser.eval('(()=>{document.activeElement&&document.activeElement.blur();keysToBox();return "ok";})()')
        time.sleep(0.2)
        where = self.browser.eval('JSON.stringify(document.activeElement===input)')
        self.assertFalse(where, 'the reply box of av-k3, hidden under the panel, took the keys: what he types goes there')

    # ── Medium: undo of a snooze ───────────────────────────────────────────────

    def test_the_undo_of_a_snooze_gives_back_a_sleep_he_had_set_before(self):
        self.fresh('av-z1', 'av-z2')
        self.ok('snooze', 'av-z1', '--until', '+30d')
        original = self.thread('av-z1')['snooze']['until']
        self.open_list()
        self.browser.eval('(()=>{setFold("snoozed",false);return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(row('av-z1')), what='the sleeping row')
        self.mod_click('av-z1')
        self.mod_click('av-z2')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["av-z1","av-z2"]))' % PICKED, what='both chosen')
        self.browser.click(HOST + ' [data-bulk=snooze]')
        self.until(lambda: self.thread('av-z2').get('snooze') and self.thread('av-z1')['snooze']['until'] != original, what='both snoozed')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast .text-btn")].some(x=>x.textContent.includes("בטל")))', what='the undo')
        self.browser.eval('(()=>{[...document.querySelectorAll(".toast .text-btn")].find(x=>x.textContent.includes("בטל")).click();return "ok";})()')
        self.until(lambda: not self.thread('av-z2').get('snooze'), what='av-z2 awake')
        time.sleep(0.5)
        now = self.thread('av-z1').get('snooze')
        self.assertTrue(now and now['until'] == original,
                        'undo woke av-z1 for good: the sleep he had set (30 days) is lost, snooze is now %r' % now)

    # ── Medium: a long press with no click after it (a real phone sends none) ──

    def test_after_a_long_press_the_next_tap_is_not_swallowed(self):
        self.fresh('av-p1', 'av-p2')
        self.open_list(PHONE)
        self.browser.pointer(row('av-p1'), 'pointerdown')
        time.sleep(0.9)
        self.browser.pointer(row('av-p1'), 'pointerup')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["av-p1"]))' % PICKED, what='chosen by the long press')
        self.browser.click(row('av-p2'))
        time.sleep(0.3)
        self.assertEqual(self.picked(), ['av-p1', 'av-p2'], 'the first tap after the long press was swallowed')

    # ── Low ────────────────────────────────────────────────────────────────────

    def test_android_back_lets_go_of_the_choice_and_stays_on_the_page(self):
        self.fresh('av-b1', 'av-b2')
        self.open_list(PHONE)
        before = self.browser.eval('JSON.stringify(history.length)')
        self.browser.pointer(row('av-b1'), 'pointerdown')
        time.sleep(0.9)
        self.browser.pointer(row('av-b1'), 'pointerup')
        self.browser.click(row('av-b1'))
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["av-b1"]))' % PICKED, what='chosen')
        after = self.browser.eval('JSON.stringify(history.length)')
        self.assertGreater(after, before, 'choosing pushed no history entry: Android Back leaves the list (or the app) with the choice still on')

    def test_markup_in_titles_stays_text_in_chips_question_and_notice(self):
        bad = '<img src=x onerror="window.__pwn=1">'
        for tid in ('av-x1', 'av-x2'):
            self.ok('new', tid, bad + tid, '--state', 'working', '--note', 'n', '--by', 'e2e')
        self.open_list()
        self.mod_click('av-x1')
        self.mod_click('av-x2')
        self.browser.click(HOST + ' [data-bulk=merge][data-into=av-x2]') if 'merge' in self.ops else self.press('close')
        self.ask_text()
        self.press('ok')
        time.sleep(1.5)
        self.assertFalse(self.browser.eval('JSON.stringify(!!window.__pwn||!!document.querySelector("#bulk img,.toast img,#bulk-sheet img"))'))

    def test_aria_selected_sits_on_a_role_that_has_it(self):
        self.fresh('av-a1', 'av-a2')
        self.open_list()
        self.mod_click('av-a1')
        self.browser.wait('JSON.stringify(%s.length>2)' % PICKED, what='one chosen')
        roles = self.browser.eval('JSON.stringify([...document.querySelectorAll("#channels [aria-selected]")].map(b=>b.getAttribute("role")||b.tagName.toLowerCase()))')
        self.assertTrue(roles)
        for r in roles:
            self.assertIn(r, ('option', 'row', 'gridcell', 'tab', 'treeitem', 'columnheader', 'rowheader'),
                          'aria-selected on a %s is not read by a screen reader' % r)

    def test_mark_read_while_a_batch_runs_does_not_act_on_the_running_choice(self):
        self.fresh('av-r1', 'av-r2', said=True)
        self.open_list()
        self.browser.eval('(()=>{READ_ALL_MS=60000;return "ok";})()')
        self.mod_click('av-r1')
        self.mod_click('av-r2')
        # a slow server: the batch is still running when he picks "mark read" from Cmd+K
        self.browser.eval('(()=>{const real=window.fetch.bind(window);window.fetch=async(u,o)=>{if(String(u).startsWith("/api/state")&&o&&/"op":"snooze"/.test(o.body))await new Promise(r=>setTimeout(r,1500));return real(u,o);};return "ok";})()')
        self.browser.click(HOST + ' [data-bulk=snooze]')
        self.browser.wait('JSON.stringify(bulkBusy)', what='the batch running')
        self.browser.eval('(()=>{bulkRead();return "ok";})()')
        pending = self.browser.eval('JSON.stringify(readPending.has("av-r1")||readPending.has("av-r2"))')
        self.assertFalse(pending, 'a second action started on threads the running batch is still working on')


for _name in dir(test_e2e_bulk.Bulk):
    if _name.startswith('test') and _name not in AdvBulk.__dict__:
        setattr(AdvBulk, _name, None)


if __name__ == '__main__':
    unittest.main()
