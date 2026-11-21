#!/usr/bin/env python3
"""Hostile review of spaces (task 114): page holes. Each test asserts the CORRECT outcome; FAIL = hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e_spaces import Spaces as Base
from test_e2e import SIZES



class Adv(Base):
    def test_adv_a_phone_switches_space_from_a_thread(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open_thread(SIZES[0], 'sp-main', 'נושא ראשי')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-head").offsetParent)', what='the square in the head')
        self.browser.click('#space-head')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-menu:not([hidden]) [data-space=support]"))', what='menu')
        self.browser.click('#space-menu [data-space=support]')
        try:
            self.browser.wait('JSON.stringify(!view.ch&&currentSpace()==="support"&&!!document.querySelector("#channels .ch[data-id=sup-a]"))',
                              timeout=6, what='the support list on the phone')
        finally:
            print('\nPHONE AFTER SWITCH:', self.browser.eval('JSON.stringify({ch:view.ch,space:currentSpace(),ids:[...document.querySelectorAll("#channels .ch")].map(b=>b.dataset.id)})'))

    def test_adv_b_new_topic_opened_in_a_space_stays_in_it(self):
        self.needs('new')
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(!!view.ch)', what='a thread open')
        self.browser.eval('(()=>{switchSpace("support");return "ok"})()')
        self.browser.wait('JSON.stringify(currentSpace()==="support")', what='support')
        self.browser.click('#new-topic')
        self.browser.wait('JSON.stringify(!!document.querySelector("#topic-text").offsetParent)', what='the form')
        self.browser.fill('#topic-title', 'טיקט חדש מהמרחב')
        self.browser.fill('#topic-text', 'גוף')
        before = set(self.state()['threads'])
        self.browser.click('#topic-ok')
        tid = self.until(lambda: next((k for k in self.state()['threads'] if k not in before), None), what='new thread')
        self.browser.wait('JSON.stringify(view.ch===%s)' % json.dumps(tid), what='landed')
        got = self.browser.eval('JSON.stringify([spaceOfThread(thread(%s)),currentSpace()])' % json.dumps(tid))
        self.cli('rm', tid, '--yes')
        self.assertEqual(got, ['support', 'support'], 'a topic opened while in support lands in main and the list jumps there')

    def test_adv_c_moving_the_open_thread_away_keeps_the_list(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open_thread(SIZES[2], 'sp-main', 'נושא ראשי')
        self.browser.click('#info')
        self.browser.wait('JSON.stringify(!!document.querySelector("#details [data-act=space-move]"))', what='move')
        self.browser.click('#details [data-act=space-move]')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-menu [data-move=support]"))', what='where')
        self.browser.click('#space-menu [data-move=support]')
        self.until(lambda: self.thread('sp-main').get('space') == 'support', what='the move')
        self.browser.wait('JSON.stringify(spaceOfThread(thread("sp-main"))==="support")', what='the page heard it')
        self.assertEqual(self.browser.eval('JSON.stringify(currentSpace())'), 'main', 'moving a thread out took him to the other space')

    def test_adv_d_next_waiting_reaches_other_spaces(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')       # sup-b is on him, in support
        self.open_thread(SIZES[2], 'sp-main', 'נושא ראשי')
        self.browser.eval('(()=>{step(1,true);return "ok"})()')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), 'sup-b', 'the only thread waiting on him is unreachable by Alt+Shift+Down')

    def test_adv_e_phone_head_has_room(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.ok('rename', 'sp-main', 'נושא ראשי עם שם ארוך מאוד שלא נגמר בכלל בשורה אחת')
        try:
            self.open_thread(SIZES[0], 'sp-main', 'נושא ראשי עם שם ארוך')
            geo = self.browser.eval('JSON.stringify(["space-head","snooze","info","h-title"].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return [id,Math.round(r.left),Math.round(r.right),Math.round(r.top),Math.round(r.bottom)]}).concat([[".back",...(()=>{const r=document.querySelector(".head .back").getBoundingClientRect();return [Math.round(r.left),Math.round(r.right),Math.round(r.top),Math.round(r.bottom)]})()]]))')
            print('\nPHONE HEAD:', geo)
            boxes = {g[0]: g[1:] for g in geo}
            names = list(boxes)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    A, B = boxes[a], boxes[b]
                    overlap = min(A[1], B[1]) - max(A[0], B[0]) > 1 and min(A[3], B[3]) - max(A[2], B[2]) > 1
                    self.assertFalse(overlap, f'{a} overlaps {b}')
            self.assertGreaterEqual(boxes['h-title'][1] - boxes['h-title'][0], 120)
        finally:
            self.ok('rename', 'sp-main', 'נושא ראשי')


for _name in dir(Base):
    if _name.startswith('test') and _name not in Adv.__dict__:
        setattr(Adv, _name, None)


if __name__ == '__main__':
    unittest.main()
