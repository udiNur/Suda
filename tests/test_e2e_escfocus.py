#!/usr/bin/env python3
"""End to end: Esc closes a window and the keys go back to where they were (the owner, suda m624: "I open Cmd+K
and close it with Esc, and the focus does not come back to the message box"). From the reply box of an open thread:
Cmd+K, the shortcuts help, the settings, a run block's confirm dialog; each closed with Esc leaves the keys in the
reply box. At the desktop size and the foldable's inner screen (with a hardware keyboard).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'
WHERE = 'JSON.stringify((document.activeElement&&(document.activeElement.id||document.activeElement.tagName))||null)'


class EscFocus(test_e2e.Suda):
    def thread_(self):
        if 'e2e-esc' not in self.state()['threads']:
            self.ok('new', 'e2e-esc', 'חזרה לתיבה אחרי Esc', '--state', 'working', '--note', 'בודק', '--by', 'e2e')
            self.ok('say', 'e2e-esc', '--from', 'tower', '-', '--state', 'working', '--note', 'בודק', '--by', 'e2e',
                    input='פקודה:\n\n```sh\n! echo hello\n```')

    def round(self, opener, shown, what):
        self.browser.eval('(()=>{const i=document.querySelector("#input");i.focus();return "ok"})()')
        self.browser.wait(IN_BOX, what='the box with the keys before ' + what)
        opener()
        self.browser.wait(shown, what=what + ' open', timeout=5)
        time.sleep(0.3)
        self.browser.press('Escape')
        time.sleep(0.5)
        self.assertTrue(self.browser.eval(IN_BOX), '%s closed with Esc, and the keys are on %s, not in the reply box' % (what, self.browser.eval(WHERE)))

    def test_esc_gives_the_keys_back_to_the_reply_box(self):
        self.thread_()
        for size in (SIZES[2], ('inner', 750, 835)):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-esc', 'חזרה לתיבה אחרי Esc')
                self.browser.press('Shift')         # a hardware keyboard is in use
                self.round(lambda: self.browser.press('Meta+KeyK'), 'JSON.stringify(!document.querySelector("#switcher").hidden)', 'Cmd+K')
                self.round(lambda: self.browser.eval('(()=>{document.querySelector("#help-open").click();return "ok"})()'),
                           'JSON.stringify(!document.querySelector("#help").hidden)', 'the shortcuts help')
                self.round(lambda: self.browser.eval('(()=>{document.querySelector("#bell").click();return "ok"})()'),
                           'JSON.stringify(!document.querySelector("#notify").hidden)', 'the settings')
                self.round(lambda: self.browser.eval('(()=>{document.querySelector("#log button.run").click();return "ok"})()'),
                           'JSON.stringify(!document.querySelector("#run").hidden)', 'the run dialog')
                # the case he hit: a click on the thread's row in the list (the thread already open) left the keys on
                # nothing, and Cmd+K closed with Esc gave them back to nothing
                self.browser.eval('(()=>{document.activeElement.blur();document.querySelector("#channels .ch[data-id=e2e-esc]").click();return "ok"})()')
                time.sleep(0.4)
                self.assertTrue(self.browser.eval(IN_BOX), 'a click on the open thread left the keys on %s' % self.browser.eval(WHERE))
                self.browser.eval('(()=>{document.activeElement.blur();return "ok"})()')
                self.browser.press('Meta+KeyK')
                self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='Cmd+K from nothing')
                self.browser.press('Escape')
                time.sleep(0.5)
                self.assertTrue(self.browser.eval(IN_BOX), 'Cmd+K opened from nothing and closed with Esc: the keys are on %s' % self.browser.eval(WHERE))


    def test_the_reply_box_is_his_line_after_every_interruption(self):
        """The owner, suda m626: "in the end this is my work line I need to come back to": after sending, after an
        answer button (and its undo), after switching threads by keys, after a run block's confirm, after the
        window comes back, after the data refreshes, the keys are in the reply box; never taken from where he types."""
        for tid, title in (('e2e-w1', 'קו עבודה ראשון'), ('e2e-w2', 'קו עבודה שני')):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', 'working', '--note', 'בודק', '--by', 'e2e')
        self.ok('say', 'e2e-w1', '--from', 'tower', '-', '--state', 'working', '--note', 'בודק', '--by', 'e2e', input='פקודה:\n\n```sh\n! echo hi\n```')
        self.ok('ask', 'e2e-w1', 'איזה?', '--options', 'אחת,שתיים', '--from', 'fork')
        self.open_thread(SIZES[2], 'e2e-w1', 'קו עבודה ראשון')
        b = self.browser
        b.press('Shift')
        box = lambda: b.eval('(()=>{document.querySelector("#input").focus();return "ok"})()')
        def check(what):
            time.sleep(0.6)
            self.assertTrue(b.eval(IN_BOX), '%s: the keys are on %s, not in the reply box' % (what, b.eval(WHERE)))
        # sending, by Enter and by the button
        box(); b.run('type', '#input', 'שלום'); b.press('Enter'); check('after Enter sent a message')
        box(); b.run('type', '#input', 'שוב'); b.click('#send'); check('after the send button')
        # an answer button pressed with the mouse, then its undo in the notice
        b.eval('(()=>{[...document.querySelectorAll("#log .opts button, #pinned button")].find(x=>x.textContent.includes("שתיים")).click();return "ok"})()')
        check('after an answer button')
        b.eval('(()=>{const u=[...document.querySelectorAll(".toast button")].pop();if(u)u.click();return String(!!u)})()')
        check('after the undo of an answer')
        # a run block, confirmed
        b.eval('(()=>{document.querySelector("#log button.run").click();return "ok"})()')
        b.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the run dialog')
        b.eval('(()=>{document.querySelector("#run-ok").click();return "ok"})()')
        check('after the run was confirmed')
        # the next thread by keys
        box(); b.press('Alt+ArrowDown'); b.wait('JSON.stringify(view.ch!=="e2e-w1")', what='the next thread'); check('after Alt+Down')
        # the window comes back, the data refreshes: keys that were nowhere go home
        b.eval('(()=>{document.activeElement.blur();document.dispatchEvent(new Event("visibilitychange"));return "ok"})()'); check('after the tab came back')
        b.eval('(()=>{document.activeElement.blur();refresh();return "ok"})()'); check('after the data refreshed')
        # never taken from where he types: the palette's search keeps them through a refresh
        b.press('Meta+KeyK'); b.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        b.eval('(()=>{refresh();return "ok"})()'); time.sleep(0.6)
        self.assertEqual(b.eval(WHERE), 'sw-query', 'a refresh took the keys from the palette search')
        b.press('Escape'); check('after the palette closed')
        # the picture picker closed without a choice (the browser's own window: its cancel event)
        b.eval('(()=>{document.querySelector("#attach").focus();document.querySelector("#pic-file").dispatchEvent(new Event("cancel"));return "ok"})()')
        check('after the picture picker was cancelled')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in EscFocus.__dict__:
        setattr(EscFocus, _name, None)


if __name__ == '__main__':
    unittest.main()
