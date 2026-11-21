#!/usr/bin/env python3
"""End to end: merging a thread into another from the page (task 113, the owner in thread suda m377).

- "מזג לתוך…" in the thread's details, and the same as a command of ⌘K: the switcher then lists only the open
  threads it may go into; choosing one asks once ("למזג את X לתוך Y?") and only "מזג" does it.
- The target shows a "מוזג לכאן" block with the source's story in numbers, its history on a press (read from the
  source's own conversation), and a way to the source; the moved tasks say where they came from.
- The source is under its own section of the list, "מוזגו", with where it went; its head says it was merged
  into the target and leads there.
The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

HAS = 'JSON.stringify(!!document.querySelector(%s))'


class Merge(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def fresh(self, src, dst):
        self.ok('new', dst, 'יעד ' + dst, '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('new', src, 'מקור ' + src, '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('say', src, '--from', 'fork', 'השורה הראשונה של המקור ' + src)
        self.ok('say', src, '--from', 'fork', 'השורה השנייה של המקור', '--state', 'working', '--note', 'y')
        self.ok('task', 'add', src, 'משימה שעוברת', '--owner', 'e2e')

    def q(self, selector):
        return self.browser.eval(HAS % json.dumps(selector))

    def test_merging_from_the_details_asks_once_and_lands_in_the_target(self):
        self.needs('merge')
        self.fresh('mg-src1', 'mg-dst1')
        self.open_thread(SIZES[0], 'mg-src1', 'מקור mg-src1')
        self.browser.click('#info')
        self.browser.wait(HAS % json.dumps('#details [data-act=merge]'), what='the merge button in the details')
        self.browser.click('#details [data-act=merge]')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the target picker')
        # only open threads it may go into: never itself, never a closed one, no commands
        rows = self.browser.eval('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row")].map(b=>b.dataset.id||"act"))')
        self.assertIn('mg-dst1', rows)
        self.assertNotIn('mg-src1', rows)
        self.assertNotIn('act', rows)
        self.assertIn('מקור mg-src1', self.browser.eval('JSON.stringify(document.querySelector("#sw-query").placeholder)'))
        self.browser.fill('#sw-query', 'mg-dst1')
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row")?.dataset.id==="mg-dst1")', what='the target found')
        self.browser.press('Enter')
        self.browser.wait(HAS % json.dumps('#merge-ok'), what='the question before the merge')
        ask = self.browser.eval('JSON.stringify(document.querySelector("#sw-results").innerText)')
        self.assertIn('מקור mg-src1', ask)
        self.assertIn('יעד mg-dst1', ask)
        self.assertFalse(self.thread('mg-src1').get('merged_into'), 'merged before he said so')
        self.browser.run('screenshot', '/tmp/suda-merge-ask.png')
        self.browser.click('#merge-ok')
        self.until(lambda: self.thread('mg-src1').get('merged_into') == 'mg-dst1', what='the merge')
        # he is taken to the target, which shows where its new part came from
        self.browser.wait('JSON.stringify(view.ch==="mg-dst1"&&!!document.querySelector("#log .merge-block"))', what='the target with its merge block')
        block = self.browser.eval('JSON.stringify(document.querySelector("#log .merge-block").innerText)')
        self.assertIn('מקור mg-src1', block)
        self.assertIn('2 הודעות', block)
        self.browser.click('#log .merge-block [data-act=history]')
        self.browser.wait('JSON.stringify(document.querySelector("#log .merge-block .mb-history")?.innerText.includes("השורה הראשונה של המקור"))',
                          what='the history of the source inside the target')
        self.browser.run('screenshot', '/tmp/suda-merge-block.png')
        # the moved task says where it came from
        self.browser.click('#tasks-toggle')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#tasks .task")].some(r=>r.innerText.includes("משימה שעוברת")&&r.innerText.includes("mg-src1")))',
                          what='the moved task with its origin')
        # and the way back to the source
        self.browser.click('#log .merge-block [data-act=open]')
        self.browser.wait('JSON.stringify(view.ch==="mg-src1")', what='the source')

    def test_the_merged_thread_stands_under_its_own_section_and_its_head_leads_to_the_target(self):
        self.fresh('mg-src2', 'mg-dst2')
        self.ok('merge', 'mg-src2', '--into', 'mg-dst2')
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open(size)
                self.browser.wait(HAS % json.dumps('#merged-toggle'), what='the section of merged threads')
                if self.browser.eval('JSON.stringify(document.querySelector("#merged-toggle").getAttribute("aria-expanded"))') != 'true':
                    self.browser.click('#merged-toggle')
                self.browser.wait(HAS % json.dumps('.sec-merged .ch[data-id=mg-src2]'), what='the merged thread in its section')
                row = self.browser.eval('JSON.stringify(document.querySelector(".sec-merged .ch[data-id=mg-src2]").innerText)')
                self.assertIn('יעד mg-dst2', row)
                self.assertFalse(self.q('.sec-closed .ch[data-id=mg-src2]'), 'also among the archive')
        self.browser.run('screenshot', '/tmp/suda-merge-list.png')
        self.open(SIZES[0], 'mg-src2')          # closed: no reply box to wait for
        self.browser.wait('JSON.stringify(view.ch==="mg-src2"&&document.body.innerText.includes("מקור mg-src2"))', what='the merged thread')
        note = self.browser.wait('JSON.stringify((()=>{const n=document.querySelector("#closed-note");return n&&!n.hidden&&n.innerText})())', what='the closed note')
        self.assertIn('מוזג', note)
        self.assertIn('יעד mg-dst2', note)
        self.browser.click('#merged-go')
        self.browser.wait('JSON.stringify(view.ch==="mg-dst2")', what='the target from the source head')

    def test_the_palette_merges_too_and_esc_leaves_without_merging(self):
        self.needs('merge')
        self.fresh('mg-src3', 'mg-dst3')
        self.open_thread(SIZES[2], 'mg-src3', 'מקור mg-src3')
        self.browser.eval('(()=>{openSwitcher();return "ok"})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the switcher')
        self.browser.fill('#sw-query', 'מיזוג')
        self.browser.wait('JSON.stringify(!!document.querySelector("#sw-results .sw-act"))', what='the merge command')
        self.assertIn('מיזוג הנושא', self.browser.eval('JSON.stringify(document.querySelector("#sw-results .sw-act").innerText)'))
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden&&document.querySelector("#sw-query").placeholder.includes("מקור mg-src3"))',
                          what='the picker from the palette')
        self.browser.fill('#sw-query', 'mg-dst3')
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row")?.dataset.id==="mg-dst3")', what='the target found')
        self.browser.press('Enter')
        self.browser.wait(HAS % json.dumps('#merge-ok'), what='the question')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#switcher").hidden)', what='Esc to leave')
        time.sleep(1)
        self.assertFalse(self.thread('mg-src3').get('merged_into'), 'Esc merged it')
        # the next ⌘K is the ordinary switcher again
        self.browser.eval('(()=>{openSwitcher();return "ok"})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the switcher again')
        self.assertNotIn('מקור', self.browser.eval('JSON.stringify(document.querySelector("#sw-query").placeholder)'))
        self.browser.press('Escape')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Merge.__dict__:
        setattr(Merge, _name, None)


if __name__ == '__main__':
    unittest.main()
