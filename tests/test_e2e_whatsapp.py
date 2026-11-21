#!/usr/bin/env python3
"""End to end: on a phone used by finger alone the reply box behaves as in WhatsApp (the owner, thread suda m540:
"like WhatsApp", his answer to m539). Entering a thread raises no keyboard; a tap on the box raises it (the
browser's own); a tap on Send leaves it up (the box never lets go of the keys, so the keyboard does not drop and
jump back); leaving the thread for the list, or another thread opened over it, puts it down. The same harness as
test_e2e.py, with Chrome's touch emulation and real taps (CDP).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e_gallery import Cdp
from test_e2e import SIZES

IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'


class LikeWhatsApp(test_e2e.Suda):
    def threads_(self):
        for tid, title in (('e2e-wa', 'נושא ראשון כמו בוואטסאפ'), ('e2e-wb', 'נושא שני כמו בוואטסאפ')):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', 'working', '--note', 'בונה', '--by', 'e2e')

    def on_a_phone(self, tid, title):
        self.threads_()
        self.open_thread(SIZES[0], tid, title)          # (a page of Suda for the browser's own controls to find)
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
        self.addCleanup(lambda: cdp.call('Emulation.setTouchEmulationEnabled', {'enabled': False}))
        self.open_thread(SIZES[0], tid, title)
        self.assertTrue(self.browser.eval('JSON.stringify(matchMedia("(pointer:coarse)").matches)'), 'no touch screen to test on')
        self.browser.eval('(()=>{document.documentElement.classList.remove("keyed");document.activeElement.blur();return "ok";})()')
        return cdp

    def centre(self, sel):
        box = self.browser.eval('JSON.stringify((()=>{const r=document.querySelector(%r).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})())' % sel)
        return box[0], box[1]

    def tap_box(self, cdp):
        cdp.tap(*self.centre('#input'))
        self.browser.wait(IN_BOX, what='the box after a tap on it (the keyboard up)')

    def test_entering_a_thread_by_finger_raises_no_keyboard(self):
        self.on_a_phone('e2e-wa', 'נושא ראשון כמו בוואטסאפ')
        self.browser.eval('(()=>{openChannel("e2e-wb");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-wb")', what='a thread opened by finger')
        time.sleep(0.5)
        self.assertFalse(self.browser.eval(IN_BOX), 'entering a thread took the keys: the phone keyboard would cover the conversation')

    def test_a_tap_on_send_keeps_the_keyboard_up(self):
        cdp = self.on_a_phone('e2e-wa', 'נושא ראשון כמו בוואטסאפ')
        self.tap_box(cdp)
        self.browser.eval('(()=>{window.__drops=0;document.querySelector("#input").addEventListener("blur",()=>window.__drops++);return "ok";})()')
        text = 'נשלח בנגיעה, המקלדת נשארת'
        self.browser.eval('(()=>{const i=document.querySelector("#input");i.value=%r;i.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()' % text)
        self.browser.wait('JSON.stringify(!document.querySelector("#send").disabled&&!document.querySelector("#send").hidden)', what='the send button')
        cdp.tap(*self.centre('#send'))
        self.until(lambda: next((r for r in self.pending() if r['text'] == text), None), what='the reply sent by a tap')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval(IN_BOX), 'after Send the box no longer has the keys: the keyboard went down')
        self.assertEqual(self.browser.eval('JSON.stringify(window.__drops)'), 0,
                         'the tap on Send took the keys from the box for a moment: the keyboard drops and jumps back')

    def test_back_to_the_list_puts_the_keyboard_down(self):
        cdp = self.on_a_phone('e2e-wa', 'נושא ראשון כמו בוואטסאפ')
        self.tap_box(cdp)
        self.assertTrue(self.browser.eval('JSON.stringify(window.sudaBack())'), 'Back did nothing in a thread on the phone')
        self.browser.wait('JSON.stringify(!view.ch)', what='the list after Back')
        time.sleep(0.3)
        self.assertFalse(self.browser.eval(IN_BOX), 'the list is on the screen and the hidden box still has the keys: the keyboard stays up over the list')

    def test_another_thread_opened_over_it_puts_the_keyboard_down(self):
        cdp = self.on_a_phone('e2e-wa', 'נושא ראשון כמו בוואטסאפ')
        self.tap_box(cdp)
        self.browser.eval('(()=>{openChannel("e2e-wb");return "ok";})()')        # (a notification, a link)
        self.browser.wait('JSON.stringify(view.ch==="e2e-wb")', what='the other thread')
        time.sleep(0.3)
        self.assertFalse(self.browser.eval(IN_BOX), 'another thread opened and the box kept the keys: the keyboard stays up over it')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in LikeWhatsApp.__dict__:
        setattr(LikeWhatsApp, _name, None)


if __name__ == '__main__':
    unittest.main()
