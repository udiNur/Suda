#!/usr/bin/env python3
"""End to end: a .md opens in the MD Viewer INSIDE Suda, as a large panel over the thread (suda-fixes m190, as the
approved mockup showed), not as a page of its own.

"It opens as if in another page instead of opening it like inside a big file, that I can maybe enlarge a lot or
open in a new page, as it was in the mockup." The same harness as test_e2e.py (the real board server, which
serves the viewer under /mdv/, a temporary board and notes folder, the stand-in model). What is checked:
  - on a wide screen: a press on a .md chip opens the panel over the thread with the viewer in it; its own head
    has "open in a new page" (the viewer's page, not embedded), full screen (kept for the next time) and close;
    Esc inside the viewer closes it, and the thread is still there;
  - on a phone: the panel fills the screen, has no full-screen button, and Back closes it, back to the thread;
  - a link inside the viewer to another note opens in the panel's place, as a step in the history (task 73): Back
    returns to the note before, the next Back closes the panel; the panel's ← does the same; on the wide screen
    (where the panel is not in the history) its ← steps back and its close closes all at once;
  - Ctrl (or ⌘) and a press still open the viewer's own page, not the panel;
  - until the viewer says it is ready (one that does not load) the panel has its own close.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-mdpanel'
TITLE = 'קובץ md בפאנל'
FRAME = 'document.querySelector("#mdv-panel iframe")'
INSIDE = FRAME + '&&' + FRAME + '.contentDocument'


SHOTS = os.environ.get('MDPANEL_SHOTS')       # a folder: screenshots of the panel are written there (to look at)


class MdPanel(test_e2e.Suda):
    def shot(self, name):
        if SHOTS:
            time.sleep(0.8)                          # the diagram draws
            self.browser.run('screenshot', os.path.join(SHOTS, name + '.png'))
    def board_with_note(self):
        if TID in self.state()['threads']:
            return
        (self.notes / 'plan.md').write_text('# The plan\n\nSee [the other note](./other.md).\n\n```mermaid\nflowchart LR\n  A --> B\n```\n')
        (self.notes / 'other.md').write_text('# The other note\n\nShort.\n')
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', 'התוכנית: `%s`' % (self.notes / 'plan.md'),
                '--state', 'working', '--note', 'בודקים', '--by', 'e2e')

    def open_panel(self, size):
        self.board_with_note()
        self.open_thread(size, TID, TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log a.chip-link[data-kind=file]"))', what='the file chip')
        before = self.browser.eval('history.length')
        self.browser.click('#log a.chip-link[data-kind=file]')
        self.browser.wait('JSON.stringify(!document.querySelector("#mdv-panel").hidden&&!!(%s)&&!!%s.contentDocument.querySelector("#h-title")'
                          '&&%s.contentDocument.querySelector("#h-title").textContent==="The plan")' % (INSIDE, FRAME, FRAME), what='the viewer in the panel')
        return before

    def test_wide_screen_panel(self):
        self.browser.eval('(()=>{localStorage.removeItem("suda-mdv-full");return 1})()')
        self.open_panel(SIZES[2])
        got = self.browser.eval('JSON.stringify((()=>{const f=%s,d=f.contentDocument;return {src:f.getAttribute("src"),full:document.querySelector("#mdv-panel").classList.contains("full"),'
                                'ownClose:!document.querySelector("#mdv-close").hidden,newpage:d.querySelector("#b-newpage").getAttribute("href"),'
                                'size:!d.querySelector("#b-size").hidden,close:!d.querySelector("#b-close").hidden,thread:!!document.querySelector("#log .msg")};})())' % FRAME)
        self.assertIn('embed=1', got['src'])
        self.assertNotIn('embed', got['newpage'])
        self.assertTrue(got['newpage'].startswith('/mdv/?path='))
        self.assertFalse(got['full'])
        self.assertFalse(got['ownClose'], 'the panel kept its own close after the viewer said it was ready')
        self.assertTrue(got['size'] and got['close'] and got['thread'])
        self.shot('desktop-panel')
        # full screen, at the viewer's own button; kept for the next time
        self.browser.eval('(()=>{%s.contentDocument.querySelector("#b-size").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").classList.contains("full"))', what='full screen')
        self.browser.wait('JSON.stringify(%s.contentDocument.querySelector("#b-size").getAttribute("aria-pressed")==="true")' % FRAME, what='the button says so')
        self.shot('desktop-full')
        # Esc inside the viewer closes the panel; the thread is still there
        self.browser.eval('(()=>{const w=%s.contentWindow;w.document.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Escape",bubbles:true}));return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").hidden&&!document.querySelector("#mdv-panel iframe"))', what='the panel to close')
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector("#log .msg"))'))
        self.open_panel(SIZES[2])
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#mdv-panel").classList.contains("full"))'))
        self.browser.eval('(()=>{localStorage.removeItem("suda-mdv-full");closeMdv();return 1})()')

    def test_phone_panel_and_back(self):
        before = self.open_panel(SIZES[0])
        got = self.browser.eval('JSON.stringify({full:document.querySelector("#mdv-panel").classList.contains("full"),'
                                'size:!%s.contentDocument.querySelector("#b-size").hidden,len:history.length,'
                                'w:Math.round(%s.getBoundingClientRect().width)})' % (FRAME, FRAME))
        self.assertTrue(got['full'])
        self.assertFalse(got['size'], 'a phone has no full-screen button: the panel is the whole screen')
        self.assertGreaterEqual(got['w'], 350)
        self.shot('phone-panel')
        # a link inside the viewer opens the other note in the panel's place, as a step in the history (task 73)
        self.browser.eval('(()=>{%s.contentDocument.querySelector("a.md-link").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The other note")'
                          % (INSIDE, FRAME, FRAME), what='the other note in the panel')
        self.assertEqual(self.browser.eval('history.length'), got['len'] + 1)
        self.assertIn('embed=1', self.browser.eval('%s.contentWindow.location.search' % FRAME))
        self.browser.wait('JSON.stringify(!%s.contentDocument.querySelector("#b-back").hidden)' % FRAME, what='the panel\'s back button')
        # Back returns to the note before, in the panel
        self.browser.eval('(()=>{history.back();return 1})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#mdv-panel").hidden&&!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The plan")'
                          % (INSIDE, FRAME, FRAME), what='Back to the first note, the panel still open')
        self.assertTrue(self.browser.eval('JSON.stringify(%s.contentDocument.querySelector("#b-back").hidden)' % FRAME), 'the first note has no back button')
        # again forward by the link, then the panel's own ← steps back too
        self.browser.eval('(()=>{%s.contentDocument.querySelector("a.md-link").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The other note")'
                          % (INSIDE, FRAME, FRAME), what='the other note again')
        self.browser.wait('JSON.stringify(!%s.contentDocument.querySelector("#b-back").hidden)' % FRAME, what='the back button again')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("#b-back").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The plan")'
                          % (INSIDE, FRAME, FRAME), what='the panel\'s ← to the first note')
        # Back from the first note closes the panel, and the thread is where it was
        self.browser.eval('(()=>{history.back();return 1})()')
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").hidden)', what='Back to close the panel')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), TID)
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector("#log .msg"))'))

    def test_wide_screen_back_button_and_close_all(self):
        self.open_panel(SIZES[2])
        before = self.browser.eval('history.length')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("a.md-link").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The other note")'
                          % (INSIDE, FRAME, FRAME), what='the other note in the panel')
        self.assertEqual(self.browser.eval('history.length'), before, 'on the wide screen the panel is not in the history')
        self.browser.wait('JSON.stringify(!%s.contentDocument.querySelector("#b-back").hidden)' % FRAME, what='the back button')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("#b-back").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The plan")'
                          % (INSIDE, FRAME, FRAME), what='back to the first note')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("a.md-link").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The other note")'
                          % (INSIDE, FRAME, FRAME), what='the other note again')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("#b-close").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").hidden&&!document.querySelector("#mdv-panel iframe"))', what='close, from the second note')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), TID)

    def test_phone_close_from_the_second_note_closes_all(self):
        self.open_panel(SIZES[0])
        self.browser.eval('(()=>{%s.contentDocument.querySelector("a.md-link").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(!!(%s)&&!!%s.contentDocument.querySelector("#h-title")&&%s.contentDocument.querySelector("#h-title").textContent==="The other note")'
                          % (INSIDE, FRAME, FRAME), what='the other note in the panel')
        self.browser.eval('(()=>{%s.contentDocument.querySelector("#b-close").click();return 1})()' % FRAME)
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").hidden&&!document.querySelector("#mdv-panel iframe"))', what='close, from the second note')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), TID)
        self.assertEqual(self.browser.eval('JSON.stringify(!!view.mdv)'), False)

    def test_fold_inner_panel(self):
        self.open_panel(SIZES[1])
        got = self.browser.eval('JSON.stringify({full:document.querySelector("#mdv-panel").classList.contains("full"),'
                                'size:!%s.contentDocument.querySelector("#b-size").hidden})' % FRAME)
        self.assertEqual(got, {'full': False, 'size': True})   # the Fold's inner screen is wide: a large panel, full screen at a press
        self.shot('fold-inner-panel')
        self.browser.eval('(()=>{closeMdv();return 1})()')

    def test_ctrl_press_opens_the_page_not_the_panel(self):
        self.board_with_note()
        self.open_thread(SIZES[2], TID, TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log a.chip-link[data-kind=file]"))', what='the file chip')
        opened = self.browser.eval('''JSON.stringify((()=>{const a=document.querySelector("#log a.chip-link[data-kind=file]");let stopped=false;
          const stop=e=>{stopped=e.defaultPrevented;e.preventDefault();};addEventListener("click",stop);
          a.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,ctrlKey:true,metaKey:true,button:0}));
          removeEventListener("click",stop);return {stopped,panel:!document.querySelector("#mdv-panel").hidden};})())''')
        self.assertFalse(opened['panel'])
        self.assertFalse(opened['stopped'], 'Suda took a Ctrl press for the panel')

    def test_the_panel_has_its_own_close_until_the_viewer_is_ready(self):
        self.board_with_note()
        self.open_thread(SIZES[2], TID, TITLE)
        early = self.browser.eval('JSON.stringify((()=>{openMdv("%s","");return !document.querySelector("#mdv-close").hidden;})())' % (self.notes / 'plan.md'))
        self.assertTrue(early)
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-close").hidden)', what='the viewer to say it is ready')
        self.browser.eval('(()=>{closeMdv();return 1})()')
        self.browser.wait('JSON.stringify(document.querySelector("#mdv-panel").hidden)', what='the panel to close')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in MdPanel.__dict__:
        setattr(MdPanel, _name, None)


if __name__ == '__main__':
    unittest.main()
