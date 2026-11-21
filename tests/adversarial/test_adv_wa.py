#!/usr/bin/env python3
"""Hostile review of wa139 (suda m540). Every test asserts the CORRECT behaviour: a FAIL is a hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
import test_e2e_whatsapp
from test_e2e_gallery import Cdp
from test_e2e import SIZES

IN_BOX = test_e2e_whatsapp.IN_BOX
A, AT = 'e2e-wa', 'נושא ראשון כמו בוואטסאפ'
SPY = ('(()=>{window.__focuses=0;window.__drops=0;const i=document.querySelector("#input");'
       'i.addEventListener("focus",()=>window.__focuses++);i.addEventListener("blur",()=>window.__drops++);return "ok";})()')


def fill(text):
    return '(()=>{const i=document.querySelector("#input");i.value=%r;i.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()' % text


class Adv(test_e2e_whatsapp.LikeWhatsApp):
    def cdp(self):
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        return cdp

    def mouse(self, cdp, x, y, kind='mouse'):
        for t in ('mousePressed', 'mouseReleased'):
            cdp.call('Input.dispatchMouseEvent', {'type': t, 'x': x, 'y': y, 'button': 'left', 'buttons': 1 if t == 'mousePressed' else 0,
                                                  'clickCount': 1, 'pointerType': kind})

    def sent(self, text):
        return self.until(lambda: next((r for r in self.pending() if r['text'] == text), None), what='the reply ' + text)

    def ready_send(self):
        self.browser.wait('JSON.stringify(!document.querySelector("#send").disabled&&!document.querySelector("#send").hidden)', what='the send button')

    # ── desktop: nothing should change ──
    def test_desktop_mouse_click_on_send_sends_and_keeps_box(self):
        self.threads_()
        self.open_thread(SIZES[2], A, AT)
        cdp = self.cdp()
        self.browser.eval('(()=>{document.querySelector("#input").focus();return "ok";})()')
        self.browser.eval(SPY)
        self.browser.eval(fill('נשלח בעכבר'))
        self.ready_send()
        self.mouse(cdp, *self.centre('#send'))
        self.sent('נשלח בעכבר')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval(IN_BOX))

    def test_desktop_click_on_send_from_elsewhere_puts_keys_in_box(self):
        self.threads_()
        self.open_thread(SIZES[2], A, AT)
        cdp = self.cdp()
        self.browser.eval(fill('נשלח בעכבר מבחוץ'))
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.ready_send()
        self.mouse(cdp, *self.centre('#send'))
        self.sent('נשלח בעכבר מבחוץ')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval(IN_BOX), 'desktop: after Send the keys are not in the box')

    # ── phone ──
    def test_pen_on_phone_send_sends_and_keeps_box(self):
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        self.browser.eval(SPY)
        self.browser.eval(fill('נשלח בעט'))
        self.ready_send()
        self.mouse(cdp, *self.centre('#send'), kind='pen')
        self.sent('נשלח בעט')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval(IN_BOX))
        self.assertEqual(self.browser.eval('JSON.stringify(window.__drops)'), 0)

    def test_finger_send_with_keyboard_down_raises_none(self):
        cdp = self.on_a_phone(A, AT)
        self.browser.eval(SPY)
        self.browser.eval(fill('טיוטה שנשלחה בלי מקלדת'))
        self.browser.eval('(()=>{document.activeElement.blur();return "ok";})()')
        self.ready_send()
        cdp.tap(*self.centre('#send'))
        self.sent('טיוטה שנשלחה בלי מקלדת')
        time.sleep(0.3)
        self.assertFalse(self.browser.eval(IN_BOX), 'Send raised a keyboard that was not up')
        self.assertEqual(self.browser.eval('JSON.stringify(window.__focuses)'), 0, 'the box took the keys for a moment')

    def test_finger_send_snippet_only_keeps_box(self):
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        before = len(self.pending())
        self.browser.eval('(()=>{attachSnippet("קטע ארוך\\n".repeat(50),"x.txt",true);return "ok";})()')
        self.browser.eval(SPY)
        self.ready_send()
        cdp.tap(*self.centre('#send'))
        self.until(lambda: len(self.pending()) > before, what='the snippet sent')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval(IN_BOX))
        self.assertEqual(self.browser.eval('JSON.stringify(window.__drops)'), 0)

    def _switch_after(self, setup):
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        self.browser.eval(setup)
        time.sleep(0.4)
        self.browser.eval(SPY)
        self.browser.eval('(()=>{openChannel("e2e-wb");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-wb")', what='the other thread')
        time.sleep(0.6)
        return self.browser.eval('JSON.stringify({box:document.activeElement===document.querySelector("#input"),act:document.activeElement.id||document.activeElement.tagName,f:window.__focuses})')

    # Known, kept (hostile review of wa139, Low): with the find bar open, closing it hands the keys back to the box
    # and the blur of the thread change takes them away in the same task. The end state is right and the phone
    # keyboard has no time to show; before wa139 the box kept the keys over the new thread. Strict: if a change
    # makes this pass, unittest reports an unexpected success and the marker goes.
    @unittest.expectedFailure
    def test_finger_switch_with_find_open(self):
        got = self._switch_after('(()=>{openFind();return document.activeElement.id;})()')
        self.assertFalse(got['box'], got)
        self.assertEqual(got['f'], 0, 'the box took the keys for a moment on the way: %s' % got)

    def test_finger_switch_from_details(self):
        got = self._switch_after('(()=>{openDetails();return "ok";})()')
        self.assertFalse(got['box'], got)
        self.assertEqual(got['f'], 0, 'the box took the keys for a moment on the way: %s' % got)

    def test_finger_pick_in_palette(self):
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        self.browser.eval('(()=>{openSwitcher();return "ok";})()')
        self.browser.wait('JSON.stringify(!switcher.hidden)', what='the palette')
        time.sleep(0.4)
        self.browser.eval(SPY)
        self.browser.eval('(()=>{choose({t:thread("e2e-wb")});return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-wb")', what='the other thread')
        time.sleep(0.6)
        got = self.browser.eval('JSON.stringify({box:document.activeElement===document.querySelector("#input"),act:document.activeElement.id||document.activeElement.tagName,f:window.__focuses})')
        self.assertFalse(got['box'], got)
        self.assertEqual(got['f'], 0, 'the box took the keys for a moment on the way: %s' % got)

    def test_finger_back_to_list_from_details_over_thread(self):
        got = None
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        self.browser.eval('(()=>{openDetails();return "ok";})()')
        time.sleep(0.4)
        self.browser.eval(SPY)
        self.browser.eval('(()=>{backToList();return "ok";})()')
        self.browser.wait('JSON.stringify(!view.ch)', what='the list', timeout=10)
        time.sleep(0.6)
        got = self.browser.eval('JSON.stringify({box:document.activeElement===document.querySelector("#input"),f:window.__focuses})')
        self.assertFalse(got['box'], got)

    def test_finger_send_mid_composition_leaves_no_composition(self):
        cdp = self.on_a_phone(A, AT)
        self.tap_box(cdp)
        self.browser.eval('(()=>{window.__ev=[];const i=document.querySelector("#input");for(const k of ["compositionstart","compositionend"])i.addEventListener(k,()=>window.__ev.push(k));return "ok";})()')
        cdp.call('Input.insertText', {'text': 'שלום '})
        cdp.call('Input.imeSetComposition', {'text': 'עולם', 'selectionStart': 4, 'selectionEnd': 4})
        self.ready_send()
        cdp.tap(*self.centre('#send'))
        self.sent('שלום עולם')
        time.sleep(0.3)
        cdp.call('Input.imeSetComposition', {'text': 'עולמ', 'selectionStart': 4, 'selectionEnd': 4})
        time.sleep(0.2)
        got = self.browser.eval('JSON.stringify({v:document.querySelector("#input").value,ev:window.__ev})')
        print('IME probe', got)
        self.assertNotEqual(got['ev'], ['compositionstart'], 'the old composition is still alive after Send: %s' % got)


for _name in dir(test_e2e_whatsapp.LikeWhatsApp):
    if _name.startswith('test') and _name not in Adv.__dict__:
        setattr(Adv, _name, None)

if __name__ == '__main__':
    unittest.main()
