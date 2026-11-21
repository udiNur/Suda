#!/usr/bin/env python3
"""Hostile review of escfocus146: where keysToBox()/keysHome()/afterPicker/openChannel(same) may take keys they must not."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES
from test_e2e_whatsapp import Cdp

IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'
WHERE = 'JSON.stringify((document.activeElement&&(document.activeElement.id||document.activeElement.className||document.activeElement.tagName))||null)'
T, TITLE = 'e2e-adv', 'בדיקה עוינת של המקלדת'


class AdvEsc(test_e2e.Suda):
    def setup_(self, size=SIZES[2]):
        if T not in self.state()['threads']:
            self.ok('new', T, TITLE, '--state', 'working', '--note', 'בודק', '--by', 'e2e')
            for i in range(3):
                self.ok('say', T, '--from', 'tower', '-', input='הודעה מספר %d עם קצת טקסט לבחירה' % i)
        self.open_thread(size, T, TITLE)
        self.browser.press('Shift')

    def js(self, body):
        return self.browser.eval('(()=>{%s;return "ok"})()' % body)

    def new_message(self, n):
        self.ok('say', T, '--from', 'tower', '-', input='הודעה חדשה %s' % n)
        time.sleep(1.2)

    def not_box(self, what):
        self.assertFalse(self.browser.eval(IN_BOX), '%s: the reply box took the keys (were they elsewhere?)' % what)

    def test_row_cursor_survives_refresh_and_new_message(self):
        self.setup_()
        b = self.browser
        self.js('document.activeElement.blur()')
        b.press('ArrowUp'); b.press('ArrowUp')
        if not b.eval('JSON.stringify(!!cursor)'): self.js('moveCursor(-1);moveCursor(-1)')
        time.sleep(0.3)
        on_row = 'JSON.stringify(!!(document.activeElement&&document.activeElement.closest&&document.activeElement.closest("#log .msg")))'
        self.assertTrue(b.eval(on_row), 'arrow walk did not put keys on a row: %s' % b.eval(WHERE))
        self.js('refresh()'); time.sleep(0.6)
        self.assertTrue(b.eval(on_row), 'a refresh took the keys off the row: %s' % b.eval(WHERE))
        self.new_message('a')
        self.assertTrue(b.eval(on_row), 'a new message (refresh + redraw) took the keys off the row he walks: %s, cursor=%s'
                        % (b.eval(WHERE), b.eval('JSON.stringify(cursor)')))

    def test_selection_survives_new_message(self):
        self.setup_()
        b = self.browser
        self.js('document.activeElement.blur();const p=document.querySelector("#log .msg .body, #log .msg p, #log .msg");'
                'const r=document.createRange();r.selectNodeContents(p);getSelection().removeAllRanges();getSelection().addRange(r)')
        self.new_message('b')
        self.not_box('text selected, then a new message')

    def test_find_bar_rename_survive_new_message(self):
        self.setup_()
        b = self.browser
        self.js('openFind()'); time.sleep(0.3)
        b.run('type', '#find-q', 'הודעה')
        self.new_message('c')
        self.assertEqual(b.eval(WHERE), 'find-q', 'a new message took keys from the find bar')
        self.js('closeFind()')
        # the find bar open, the keys on its next button
        self.js('openFind();document.querySelector("#find-next").focus()')
        self.new_message('d')
        self.assertEqual(b.eval(WHERE), 'find-next', 'a new message took keys from the find bar button')
        self.js('closeFind()')
        b.press('F2'); time.sleep(0.3)
        if b.eval(WHERE) != 'rename':
            self.skipTest('F2 did not open rename: %s' % b.eval(WHERE))
        self.new_message('e')
        self.assertEqual(b.eval(WHERE), 'rename', 'a new message took keys from the rename box')
        b.press('Escape')

    def test_topic_dialog_and_notification_tap_on_open_thread(self):
        self.setup_()
        b = self.browser
        self.js('openTopic()'); time.sleep(0.5)
        self.assertFalse(b.eval('JSON.stringify(topicDialog.hidden)'), 'topic dialog did not open')
        self.js('refresh()'); time.sleep(0.6)
        self.not_box('new-topic dialog open, refresh')
        # a notification tap for the thread already open (service worker 'open-thread' -> openChannel(view.ch))
        self.js('openChannel(view.ch)'); time.sleep(0.3)
        self.not_box('new-topic dialog open, openChannel(same thread) (a notification tap)')
        self.js('hideTopic(true)')

    def test_open_same_thread_while_snippet_or_help_open(self):
        self.setup_()
        b = self.browser
        self.js('showHelp()'); time.sleep(0.3)
        self.js('openChannel(view.ch)'); time.sleep(0.3)
        hidden = b.eval('JSON.stringify(help.hidden)')
        self.assertTrue(hidden or not b.eval(IN_BOX), 'help open, openChannel(same): keys in the box behind the open help')
        self.js('closeHelp()')
        self.js('openSnip()'); time.sleep(0.3)
        if not b.eval('JSON.stringify(snipDialog.hidden)'):
            self.js('openChannel(view.ch)'); time.sleep(0.3)
            self.not_box('snippet dialog open, openChannel(same thread)')
            self.js('hideSnip(true)')

    def test_details_narrow_refresh(self):
        self.setup_(('inner', 750, 835))
        b = self.browser
        self.js('openDetails()'); time.sleep(0.5)
        self.assertTrue(b.eval('JSON.stringify(view.details)'), 'details did not open')
        self.js('document.activeElement.blur();refresh()'); time.sleep(0.6)
        self.not_box('details pane open on a narrow screen (covering the conversation), refresh')

    def test_closed_thread(self):
        tid='e2e-adv-closed'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'נושא סגור לבדיקה', '--state', 'working', '--note', 'בודק', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, 'נושא סגור לבדיקה')
        self.browser.press('Shift')
        self.ok('close', tid, '--by', 'e2e')
        time.sleep(1)
        self.js('document.activeElement.blur();refresh()'); time.sleep(0.6)
        self.not_box('closed thread, refresh')
        self.js('openChannel(view.ch)'); time.sleep(0.3)
        self.not_box('closed thread, press on its row')

    def test_touch_without_keyed(self):
        self.setup_(SIZES[0])
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
        self.addCleanup(lambda: cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': False}))
        self.open_thread(SIZES[0], T, TITLE)
        b = self.browser
        self.assertTrue(b.eval('JSON.stringify(matchMedia("(pointer:coarse)").matches)'), 'no touch')
        self.js('document.documentElement.classList.remove("keyed");document.activeElement.blur()')
        self.js('refresh()'); time.sleep(0.6); self.not_box('touch, refresh')
        self.new_message('f'); self.not_box('touch, new message')
        self.js('showHelp()'); time.sleep(0.2); self.js('closeHelp()'); time.sleep(0.3); self.not_box('touch, help closed')
        self.js('document.activeElement.blur();document.querySelector("#pic-file").dispatchEvent(new Event("cancel"))'); time.sleep(0.3)
        self.not_box('touch, picker cancelled')
        self.js('document.activeElement.blur();document.querySelector("#pic-file").dispatchEvent(new Event("change"))'); time.sleep(0.3)
        self.not_box('touch, picker change')
        self.js('openChannel(view.ch)'); time.sleep(0.3); self.not_box('touch, tap on open thread')
        self.js('document.activeElement.blur();document.dispatchEvent(new Event("visibilitychange"))'); time.sleep(0.3)
        self.not_box('touch, visibilitychange')

    def test_picker_from_topic_or_with_selection(self):
        self.setup_()
        b = self.browser
        # text selected when the picker closes: the picker's focus is unconditional
        self.js('openTopic()'); time.sleep(0.4)
        self.js('document.querySelector("#pic-file").dispatchEvent(new Event("cancel"))'); time.sleep(0.3)
        self.not_box('new-topic dialog open, a picker cancel event')
        self.js('hideTopic(true)')
        self.js('openFind()'); time.sleep(0.2)
        self.js('document.querySelector("#pic-file").dispatchEvent(new Event("cancel"))'); time.sleep(0.3)
        self.assertEqual(b.eval(WHERE), 'find-q', 'find bar focused, a picker cancel event took the keys')
        self.js('closeFind()')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvEsc.__dict__:
        setattr(AdvEsc, _name, None)


if __name__ == '__main__':
    unittest.main()
