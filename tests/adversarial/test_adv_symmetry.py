#!/usr/bin/env python3
"""Hostile review of the symmetry polish (suda-fixes 26, m85; commit cd73f23): what still breaks around a chosen row
and its check, and where the page still writes a check mark from a font while SKILL.md now says it never does.

- A chosen row is said to a screen reader as chosen (", נבחר" in its aria-label, from rowNode). paintLive, which
  repaints the live dots in place when live.json changes, rebuilds the label without it: every live refresh takes
  "chosen" away from every chosen row, also rows whose dot did not change.
- The ring around a live dot is drawn in the row's own colour so the dot looks cut out of the row (var(--side), and
  var(--side-active) / var(--side-hover) for an open or hovered row). A chosen row has its own colour and no ring of
  its own: the dot wears the plain list colour, a dark halo on the chosen row.
- SKILL.md (this commit): "A check mark is the drawn i-tick icon, never a font's ✓". The box of a done task is
  still a font's ✓.

The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import time
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
# how a chosen row is said, in the language the harness installs (test_e2e: SUDA_E2E_LANG, Hebrew by default)
CHOSEN = ', ' + (json.loads((_paths.APP / 'locales/he.json').read_text(encoding='utf-8'))['chosen']
                 if os.environ.get('SUDA_E2E_LANG', 'he') == 'he' else 'chosen')


class AdvSymmetry(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for tid, title in (('as-a', 'ראשון'), ('as-b', 'שני'), ('as-c', 'שלישי')):
            cls.ok('new', tid, title, '--state', 'on-owner', '--note', 'הערה קצרה', '--by', 'e2e')
            cls.ok('say', tid, '--from', 'fork', 'דוח: ' + tid)
        cls.ok('task', 'add', 'as-c', 'משימה שהושלמה', '--owner', 'owner')
        cls.ok('task', 'set', 'as-c', '1', 'done')

    def tearDown(self):
        live = self.board / 'live.json'
        if live.exists():
            live.unlink()

    def write_live(self, agents):
        body = json.dumps({'version': 1, 'ts': time.time(), 'agents': agents}, ensure_ascii=False)
        tmp = self.board / '.live.tmp'
        tmp.write_text(body, encoding='utf-8')
        tmp.replace(self.board / 'live.json')

    def show(self, size, hash=''):
        self.open(size, hash)
        self.browser.wait('JSON.stringify(synced)', what='the page in sync')

    def choose(self, *ids):
        self.browser.eval('(()=>{bulkSet(%s);return "ok"})()' % json.dumps(list(ids)))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#channels .ch.picked").length===%d)' % len(ids), what='the rows chosen')

    def agent_on(self, tid):
        """An agent at work on `tid` in live.json; back once the page has read this very file (paintLive ran)."""
        mark = 'עורך %d' % time.time_ns()
        self.write_live([{'pane': 'aaaaaaaa-1111-2222-3333-444444444444', 'name': 'e2e-agent', 'session': 'tools', 'state': 'working',
                          'why': '', 'thread': tid, 'by': '', 'what': mark, 'ts': time.time()}])
        self.browser.wait('JSON.stringify(typeof liveText==="string"&&liveText.includes(%s)&&!!document.querySelector("#channels .ch[data-id=%s] .live-dot"))'
                          % (json.dumps(mark), tid), timeout=20, what='the page to read live.json')

    def test_a_live_refresh_keeps_a_chosen_row_said_as_chosen(self):
        for size in (DESK, COVER):
            with self.subTest(size=size[0]):
                self.show(size)
                self.choose('as-a', 'as-b')
                first = self.browser.eval('JSON.stringify([...document.querySelectorAll("#channels .ch.picked")].map(b=>b.getAttribute("aria-label")))')
                self.assertEqual(len(first), 2)
                for label in first:
                    self.assertTrue(label.endswith(CHOSEN), 'drawn by rowNode, a chosen row says so: %r' % label[-30:])
                self.agent_on('as-a')               # live.json changes: paintLive repaints the dots in place
                got = self.browser.eval('JSON.stringify([...document.querySelectorAll("#channels .ch.picked")].map(b=>({id:b.dataset.id,label:b.getAttribute("aria-label")})))')
                self.assertEqual(sorted(g['id'] for g in got), ['as-a', 'as-b'], 'the rows stay chosen')
                for g in got:
                    self.assertIn(CHOSEN.strip(', '), g['label'], '%s: after a live refresh a screen reader no longer hears it is chosen: %r' % (g['id'], g['label'][-40:]))
                live = next(g for g in got if g['id'] == 'as-a')
                self.assertIn('e2e-agent', live['label'], 'and the agent at work is said too')
                self.tearDown()

    def test_the_ring_of_a_live_dot_on_a_chosen_row_is_the_colour_of_that_row(self):
        for size in (DESK, COVER):
            for theme in ('dark', 'light'):
                with self.subTest(size=size[0], theme=theme):
                    self.show(size)
                    self.browser.eval('(()=>{document.documentElement.dataset.theme=%s;return "ok"})()' % json.dumps(theme))
                    self.choose('as-a')
                    self.agent_on('as-a')
                    got = self.browser.eval('JSON.stringify((()=>{const b=document.querySelector("#channels .ch.picked[data-id=as-a]"),d=b.querySelector(".slot .live-dot");'
                                            'const c=document.createElement("canvas").getContext("2d",{willReadFrequently:true});'
                                            'const rgb=x=>{c.clearRect(0,0,1,1);c.fillStyle="#000";c.fillStyle=x;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data];};'
                                            'const shadow=getComputedStyle(d).boxShadow,bg=getComputedStyle(b).backgroundColor;'
                                            'return {row:rgb(bg),ring:rgb(shadow.replace(/\\)\\s.*$/,")")),shadow,bg}})())')
                    self.assertEqual(got['row'][3], 255, 'a chosen row has a colour of its own: %s' % got)
                    off = max(abs(a - b) for a, b in zip(got['ring'][:3], got['row'][:3]))
                    self.assertLessEqual(off, 2, 'the dot of a chosen row is ringed in the list colour, not the chosen row colour: %s' % got)
                    self.tearDown()

    def test_a_done_task_has_a_drawn_check_as_skill_md_says(self):
        """SKILL.md (cd73f23): "A check mark is the drawn i-tick icon, never a font's ✓". The box of a done task is the
        same thing as the check of a chosen row (a check in a box) and is still a ✓ of the font."""
        for size in (DESK, COVER):
            with self.subTest(size=size[0]):
                self.show(size, 'as-c')
                self.browser.wait('JSON.stringify(view.ch==="as-c"&&!$("tasks").hidden)', what='the tasks bar')
                self.browser.eval('(()=>{if($("tasks-toggle").getAttribute("aria-expanded")!=="true")$("tasks-toggle").click();return "ok"})()')
                self.browser.wait('JSON.stringify(!!document.querySelector(".task.is-done .task-box"))', what='the done task')
                got = self.browser.eval('JSON.stringify((()=>{const b=document.querySelector(".task.is-done .task-box");'
                                        'return {text:b.textContent,svg:!!b.querySelector("svg use[href=\\"#i-tick\\"]"),after:getComputedStyle(b,"::after").content}})())')
                self.assertNotIn('✓', got['text'], 'a font check mark in the box of a done task')
                self.assertNotIn('✓', got['after'])
                self.assertTrue(got['svg'], 'the drawn i-tick')
                at = self.browser.eval('JSON.stringify((()=>{const b=document.querySelector(".task.is-done .task-box"),u=b.querySelector("use").getBoundingClientRect(),r=b.getBoundingClientRect();'
                                       'return [(u.left+u.right-r.left-r.right)/2,(u.top+u.bottom-r.top-r.bottom)/2]})())')
                self.assertLessEqual(max(abs(v) for v in at), 1, 'the check in the middle of the box of a done task: %s' % at)


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e.Suda run there."""
    return unittest.TestSuite(AdvSymmetry(name) for name in sorted(vars(AdvSymmetry)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
