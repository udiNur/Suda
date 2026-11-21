#!/usr/bin/env python3
"""End to end: the microphone inside an app's own browser, and its clipboard (a diagnosis from another app).

Inside Snap ("open as app") the browser answers "ask" about the microphone for ever, also right after it handed
the microphone over. The page read that as "the browser has just asked him", closed the microphone and said
"allowed, now hold the button" on every press: nothing was ever recorded there. The same harness as test_e2e.py
(headless Chrome with a stand-in microphone, the real board server on loopback, a temporary board). What is checked:

  - where the permission always reads "ask" while the microphone opens, a held press records and its release sends;
  - where the browser really asked during the press (not allowed before, allowed after), that press records
    nothing and says so, and the next one records;
  - asking the clipboard for a picture is offered in a browser, and not inside an app's own browser.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

WEBVIEW = 'Mozilla/5.0 (Linux; Android 14; SM-F946B Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36'


class Mic(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    RECORDING = 'JSON.stringify(!document.querySelector("#rec").hidden)'

    def voices(self, tid):
        return [m for m in self.thread(tid)['messages'] if m.get('voice')]

    def thread_with_mic(self, tid, title):
        self.needs('voice')
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[0], tid, title)
        if not self.browser.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.skipTest('this browser has no microphone API on a loopback page')
        self.browser.wait('JSON.stringify(!!document.querySelector("#mic").offsetParent)', what='the record button')

    def test_where_the_permission_always_reads_ask_an_open_microphone_still_records(self):
        self.thread_with_mic('e2e-mic-wv', 'מיקרופון בתוך אפליקציה')
        # an app's own browser: "ask", before the microphone and after it
        self.browser.eval('(()=>{window.__asked=0;navigator.permissions.query=()=>{window.__asked++;return Promise.resolve({state:"prompt"});};return "ok";})()')
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait(self.RECORDING, timeout=10, what='the recording to start although the permission reads "ask"')
        self.assertGreaterEqual(self.browser.eval('JSON.stringify(window.__asked)'), 2, 'the page did not ask about the permission before and after')
        self.assertFalse(self.browser.eval('JSON.stringify(document.body.innerText.includes("המיקרופון מותר. עכשיו"))'), 'the page still says the press only answered the browser')
        time.sleep(2)
        self.browser.pointer('#mic', 'pointerup')           # held past a tap: release = send
        voice = self.until(lambda: next(iter(self.voices('e2e-mic-wv')), None), timeout=30, what='the voice message in state.json')['voice']
        self.assertTrue(voice['bytes'] > 0 and 1 <= voice['seconds'] <= 10, voice)
        self.assertFalse(self.browser.eval(self.RECORDING), 'the recording bar is still up after the release')
        # and in the settings the microphone is no longer described as closed
        self.assertEqual(self.browser.eval('(async()=>JSON.stringify(await micState()))()'), 'granted')

    def test_a_press_that_answered_the_browsers_question_records_nothing_and_the_next_one_records(self):
        self.thread_with_mic('e2e-mic-ask', 'מיקרופון: הדפדפן שואל')
        # a browser that asks: not allowed until the microphone was opened once, allowed from then on
        self.browser.eval('(()=>{const real=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);window.__allowed=false;'
                          'navigator.mediaDevices.getUserMedia=async(...a)=>{const s=await real(...a);window.__allowed=true;return s;};'
                          'navigator.permissions.query=()=>Promise.resolve({state:window.__allowed?"granted":"prompt"});return "ok";})()')
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("המיקרופון מותר. עכשיו"))', timeout=10, what='the line that says the press answered the browser')
        self.assertFalse(self.browser.eval(self.RECORDING), 'a press that answered the browser\'s question started a recording')
        self.browser.pointer('#mic', 'pointerup')
        time.sleep(0.5)
        self.assertEqual(self.voices('e2e-mic-ask'), [])
        # the next press records
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait(self.RECORDING, timeout=10, what='the recording on the second press')
        time.sleep(2)
        self.browser.pointer('#mic', 'pointerup')
        self.until(lambda: next(iter(self.voices('e2e-mic-ask')), None), timeout=30, what='the voice message of the second press')

    def test_asking_the_clipboard_is_offered_in_a_browser_and_not_inside_an_apps_own_browser(self):
        self.ok('new', 'e2e-clip', 'הדבקה מהלוח', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[0], 'e2e-clip', 'הדבקה מהלוח')
        if not self.browser.eval('JSON.stringify(typeof takesPictures==="function"&&takesPictures()&&window.isSecureContext&&!!(navigator.clipboard&&navigator.clipboard.read))'):
            self.skipTest('this browser, or this server, has no pictures or no clipboard to ask')
        items = '(()=>{document.querySelector("#attach").click();const all=[...document.querySelectorAll("#sheet .sheet-item")].map(n=>n.innerText.trim());closeSheet();return JSON.stringify(all);})()'
        in_browser = self.browser.eval(items)
        self.assertTrue(any('הדבקת תמונה מהלוח' in item for item in in_browser), in_browser)
        self.browser.eval('(()=>{Object.defineProperty(navigator,"userAgent",{get:()=>%s,configurable:true});return "ok";})()' % json.dumps(WEBVIEW))
        self.assertTrue(self.browser.eval('JSON.stringify(inWebView(navigator.userAgent))'))
        in_app = self.browser.eval(items)
        self.assertFalse(any('מהלוח' in item for item in in_app), in_app)
        self.assertTrue(any('תמונות מהמכשיר' in item for item in in_app), in_app)      # the rest of the menu is as it was
        # the words about pasting are the ones for an ordinary paste into the box
        self.browser.eval('(async()=>{await pastePictures([]);return "ok";})()')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("בהדבקה רגילה בתוך תיבת ההודעה"))', what='the line that sends him to an ordinary paste')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Mic.__dict__:
        setattr(Mic, _name, None)


if __name__ == '__main__':
    unittest.main()
