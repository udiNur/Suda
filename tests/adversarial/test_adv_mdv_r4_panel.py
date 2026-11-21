#!/usr/bin/env python3
"""Hostile review, round 4 (suda-fixes m190): the MD Viewer panel in a real browser, on test_e2e.py's harness (the
real board server on 127.0.0.1, a temporary board, notes folder and THREADS_MDV_DIR, the stand-in model).

- A viewer link inside the reader (a table opened on the whole screen keeps its links) opens the panel UNDER the
  reader: #mdv-panel comes before #reader in the page with the same z-index. The keys go to the panel first (Esc
  and Tab are routed to it), so Esc closes a panel he cannot see and Tab is held in it.
- Shift+Tab before the first control inside the viewer leaves its frame for Suda's page BEHIND the modal panel: Suda's own
  trap never sees that Tab (it was inside the frame), and the next Enter presses a button he cannot see.
Safe outcomes asserted below."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-mdpanel-adv'
TITLE = 'פאנל בבדיקה עוינת'
FRAME = 'document.querySelector("#mdv-panel iframe")'


class PanelAdv(test_e2e.Suda):
    def board_with_table(self):
        (self.notes / 'plan.md').write_text('# The plan\n\nWords.\n')
        if TID in self.state()['threads']:
            return
        link = '/mdv/?path=' + str(self.notes / 'plan.md')
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', 'טבלה:\n\n| קובץ | מה |\n|---|---|\n| [plan](%s) | התוכנית |\n' % link,
                '--state', 'working', '--note', 'בודקים', '--by', 'e2e')

    def test_a_panel_opened_from_the_reader_is_on_top(self):
        self.board_with_table()
        self.open_thread(SIZES[2], TID, TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .card.sheet"))', what='the table card')
        self.browser.eval('(()=>{const b=[...document.querySelectorAll("#log .card.sheet button")].find(x=>/מסך מלא/.test(x.title||x.textContent));b.click();return 1})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader a[href^=\\"/mdv/\\"]"))', what='the table in the reader')
        self.browser.eval('(()=>{document.querySelector("#reader a[href^=\\"/mdv/\\"]").click();return 1})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#mdv-panel").hidden)', what='the panel')
        top = self.browser.eval('JSON.stringify((()=>{const n=document.elementFromPoint(innerWidth/2,innerHeight/2);'
                                'return n&&n.closest("#mdv-panel")?"panel":n&&n.closest("#reader")?"reader":String(n&&n.id)})())')
        self.browser.eval('(()=>{closeMdv();closeReader();return 1})()')
        self.assertEqual(top, 'panel', 'the panel opened under the reader, while Esc and Tab go to the panel')

    def test_shift_tab_does_not_leave_the_panel_for_the_page_behind(self):
        self.board_with_table()
        self.open_thread(SIZES[2], TID, TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log a[href^=\\"/mdv/\\"]"))', what='the link')
        self.browser.click('#log a[href^="/mdv/"]')
        self.browser.wait('JSON.stringify(!!%s&&!!%s.contentDocument&&!!%s.contentDocument.querySelector("#b-close")&&'
                          '!%s.contentDocument.querySelector("#head-embed").hidden)' % (FRAME, FRAME, FRAME, FRAME), what='the viewer')
        self.browser.eval('(()=>{const d=%s.contentDocument,all=[...d.querySelectorAll("a[href],button,input,[tabindex]")].filter(n=>!n.disabled&&n.tabIndex>=0&&n.getClientRects().length);'
                          '%s.focus();all[0].focus();return all.length})()' % (FRAME, FRAME))
        where = []
        for _ in range(3):
            self.browser.press('Shift+Tab')
            where.append(self.browser.eval('JSON.stringify((()=>{const a=document.activeElement;'
                                           'return a&&(a.closest("#mdv-panel"))?"panel":(a.id||a.className||a.tagName)})())'))
        self.browser.eval('(()=>{closeMdv();return 1})()')
        self.assertEqual(where, ['panel'] * 3, 'Shift+Tab left the panel for the page behind it: %s' % where)


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in PanelAdv.__dict__:
        setattr(PanelAdv, _name, None)


if __name__ == '__main__':
    unittest.main()
