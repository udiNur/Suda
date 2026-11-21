#!/usr/bin/env python3
"""End to end: the list of topics at the side (the owner, thread suda m295).

"I want to be able to change and drag the size of the toolbar on the right, kept per browser. And I want to be
able to minimise a category, the done one for example." The same harness as test_e2e.py (headless Chrome, the real
board server on loopback, a temporary board). The edge is dragged with the browser's own mouse, not with events
made up in the page. What is checked:

  - dragging the list's edge makes it wider and narrower, within its limits, and the width is still there after
    the page is loaded again; a double click gives the page's own width back;
  - with the keys on the edge the side arrows move it, Home and End go to the limits, Enter gives the width back;
  - a section's head folds it and opens it again; folded it keeps the topic that is open now, says how many
    topics have something new, is skipped by the step to the next topic, and stays folded after a reload;
  - on a phone the list is the whole screen: no edge to drag, and the sections still fold.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

SIDE = 'JSON.stringify(Math.round(document.querySelector("#side").getBoundingClientRect().width))'
ROWS = ('JSON.stringify(Object.fromEntries([...document.querySelectorAll("#channels .sec")].map(sec=>[sec.className.replace("sec sec-",""),'
        '[...sec.querySelectorAll(".ch")].map(row=>row.dataset.id)])))')


class Side(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def width(self):
        return self.browser.eval(SIDE)

    def kept(self):
        return self.browser.eval('JSON.stringify(localStorage.getItem("suda-side-w"))')

    def edge(self):
        """The middle of the list's edge, where a mouse takes it."""
        return self.browser.eval('(()=>{const box=document.querySelector("#side-size").getBoundingClientRect();return JSON.stringify([Math.round(box.left+box.width/2),Math.round(box.top+box.height/2)]);})()')

    def drag(self, dx):
        x, y = self.edge()
        self.browser.run('mouse', 'move', str(x), str(y))
        self.browser.run('mouse', 'down')
        for step in (dx // 3, 2 * dx // 3, dx):
            self.browser.run('mouse', 'move', str(x + step), str(y + 3))
        self.browser.run('mouse', 'up')

    def board_with_topics(self):
        if 'e2e-side-a' in self.state()['threads']:
            return
        for tid, title, state in (('e2e-side-a', 'נושא בעבודה א', 'working'), ('e2e-side-b', 'נושא בעבודה ב', 'working'), ('e2e-side-c', 'נושא עליו', 'on-owner'), ('e2e-side-d', 'נושא שהושלם', 'done')):
            self.ok('new', tid, title, '--state', state, '--note', 'בודקים', '--by', 'e2e')

    def test_the_edge_of_the_list_is_dragged_and_the_width_is_kept(self):
        self.board_with_topics()
        self.open_thread(SIZES[2], 'e2e-side-a', 'נושא בעבודה א')
        self.browser.eval('(()=>{localStorage.removeItem("suda-side-w");setSide(0,false);return "ok";})()')
        start = self.width()
        self.assertEqual(start, 300)
        edge = self.browser.eval('(()=>{const e=document.querySelector("#side-size");return JSON.stringify({role:e.getAttribute("role"),tab:e.tabIndex,now:e.getAttribute("aria-valuenow"),cursor:getComputedStyle(e).cursor});})()')
        self.assertEqual(edge, {'role': 'separator', 'tab': 0, 'now': '300', 'cursor': 'col-resize'})
        # 1. the list is on the right: its edge pulled to the left makes it wider, by as much as the mouse went
        self.drag(-120)
        self.assertLessEqual(abs(self.width() - 420), 2, self.width())
        self.assertEqual(int(self.kept()), self.width())
        self.assertFalse(self.browser.eval('JSON.stringify(document.documentElement.classList.contains("sizing"))'), 'the drag did not end')
        # 2. loaded again: the width is still his (and it is there before the first paint: the page sets it from the head of the body)
        self.open_thread(SIZES[2], 'e2e-side-a', 'נושא בעבודה א')
        self.assertLessEqual(abs(self.width() - 420), 2, self.width())
        # 3. back to the right it gets narrower, and stops where its rows can still be read
        self.drag(90)
        self.assertLessEqual(abs(self.width() - 330), 2, self.width())
        self.drag(400)
        self.assertEqual(self.width(), 200)
        # and to the left it stops at its widest
        self.drag(-700)
        self.assertEqual(self.width(), 560)
        self.assertEqual(self.kept(), '560')
        # 4. a double click gives the page's own width back, and forgets his
        x, y = self.edge()
        self.browser.eval('(()=>{document.querySelector("#side-size").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}));return "ok";})()')
        self.assertEqual((self.width(), self.kept()), (300, None))
        # 5. a narrower window never gives the list more than half of itself
        self.browser.eval('(()=>{setSide(540,true);return "ok";})()')
        self.browser.viewport(900, 800)
        self.browser.wait('JSON.stringify(Math.round(document.querySelector("#side").getBoundingClientRect().width)<=450)', what='the list within half of a narrower window')
        self.browser.viewport(SIZES[2][1], SIZES[2][2])
        self.browser.wait('JSON.stringify(Math.round(document.querySelector("#side").getBoundingClientRect().width)===540)', what='his width again in the wide window')
        self.browser.eval('(()=>{setSide(0,true);return "ok";})()')

    def test_the_keys_move_the_edge(self):
        self.board_with_topics()
        self.open_thread(SIZES[2], 'e2e-side-a', 'נושא בעבודה א')
        self.browser.eval('(()=>{setSide(0,true);document.querySelector("#side-size").focus();return "ok";})()')
        self.assertTrue(self.browser.eval('JSON.stringify(document.activeElement.id==="side-size")'))
        top = self.browser.eval('JSON.stringify(scroller.scrollTop)')
        self.browser.press('ArrowLeft')                 # the edge is the list's left side: left is wider
        self.assertEqual((self.width(), self.kept()), (316, '316'))
        self.browser.press('ArrowRight', 2)
        self.assertEqual(self.width(), 284)
        self.browser.press('Shift+ArrowLeft')
        self.assertEqual(self.width(), 348)
        self.browser.press('Home')
        self.assertEqual(self.width(), 200)
        self.browser.press('End')
        self.assertEqual(self.width(), 560)
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#side-size").getAttribute("aria-valuenow"))'), '560')
        self.browser.press('Enter')
        self.assertEqual((self.width(), self.kept()), (300, None))
        # the keys stayed on the edge, and did nothing else on the page (Home and End did not move the conversation)
        self.assertTrue(self.browser.eval('JSON.stringify(document.activeElement.id==="side-size")'))
        self.assertEqual(self.browser.eval('JSON.stringify(scroller.scrollTop)'), top)

    def test_a_section_folds_and_stays_folded(self):
        self.board_with_topics()
        self.open_thread(SIZES[2], 'e2e-side-a', 'נושא בעבודה א')
        self.browser.eval('(()=>{for(const key of ["on-owner","working","done"])if(folds[key])setFold(key,false);return "ok";})()')
        rows = self.browser.eval(ROWS)
        # inside a section the newest first (the default order, 'recent'): b was opened after a, to the fraction of a second
        self.assertEqual(self.browser.eval('JSON.stringify(listOrder())'), 'recent')
        self.assertEqual((rows['working'], rows['done'], rows['on-owner']), (['e2e-side-b', 'e2e-side-a'], ['e2e-side-d'], ['e2e-side-c']))
        head = lambda key: self.browser.eval('(()=>{const b=document.querySelector("#fold-%s");return JSON.stringify({open:b.getAttribute("aria-expanded"),text:b.innerText.replace(/\\s+/g," ").trim(),tag:b.tagName,inHeading:!!b.closest("h2")});})()' % key)
        self.assertEqual(head('done'), {'open': 'true', 'text': 'הושלם 1 אין המשך פתוח', 'tag': 'BUTTON', 'inHeading': True})
        # 1. a press on the head of "done" folds it: its topics leave the list, the head stays with their number
        self.browser.click('#fold-done')
        rows = self.browser.eval(ROWS)
        self.assertEqual(rows['done'], [])
        self.assertEqual(head('done')['open'], 'false')
        self.assertIn('הושלם 1', head('done')['text'])
        # 2. "working" folded keeps the topic that is open now, and only it
        self.browser.click('#fold-working')
        self.assertEqual(self.browser.eval(ROWS)['working'], ['e2e-side-a'])
        # 3. something new in a folded topic: the head says so
        self.ok('say', 'e2e-side-b', '--from', 'fork', 'הודעה חדשה בנושא מקופל', '--state', 'working', '--note', 'בודקים')
        self.browser.wait('JSON.stringify(!!document.querySelector("#fold-working .sec-new"))', what='the mark of something new on the folded head')
        self.assertEqual(str(self.browser.eval('JSON.stringify(document.querySelector("#fold-working .sec-new").textContent)')), '1')
        # 4. the step to the next topic goes over what is on the screen, never into a folded section
        self.browser.eval('(()=>{if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();return "ok";})()')
        self.browser.press('Alt+ArrowUp')
        self.browser.wait('JSON.stringify(view.ch==="e2e-side-c")', what='the step up to the topic above, in "on him"')
        self.assertEqual(self.browser.eval(ROWS)['working'], [], 'the folded section still shows a topic that is no longer the open one')
        self.browser.press('Alt+ArrowDown')             # nothing else is on the screen: both other sections are folded
        time.sleep(0.5)
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), 'e2e-side-c', 'the step went into a folded section')
        self.browser.click('#fold-done')                # "done" open again: now the step reaches it, over the folded "working"
        self.browser.press('Alt+ArrowDown')
        self.browser.wait('JSON.stringify(view.ch==="e2e-side-d")', what='the step down to the topic in "done", over the folded section')
        self.browser.click('#fold-done')
        self.assertEqual(self.browser.eval(ROWS)['done'], ['e2e-side-d'], 'folded, "done" lost the topic that is open now')
        # the step to "what needs me" reaches a folded topic too: the one with something new
        self.browser.press('Alt+Shift+ArrowDown')
        self.browser.wait('JSON.stringify(view.ch==="e2e-side-c"||view.ch==="e2e-side-b")', what='the step to a topic that needs him')
        # 5. loaded again: still folded
        self.open_thread(SIZES[2], 'e2e-side-a', 'נושא בעבודה א')
        self.assertEqual((head('done')['open'], head('working')['open'], head('on-owner')['open']), ('false', 'false', 'true'))
        self.assertEqual((self.browser.eval(ROWS)['done'], self.browser.eval(ROWS)['working']), ([], ['e2e-side-a']))
        # 6. with the keys: the head is a button, Enter opens it again and the keys stay on it
        self.browser.eval('(()=>{document.querySelector("#fold-done").focus();return "ok";})()')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(document.querySelector("#fold-done").getAttribute("aria-expanded")==="true")', what='"done" open again')
        self.assertEqual(self.browser.eval(ROWS)['done'], ['e2e-side-d'])
        self.assertTrue(self.browser.eval('JSON.stringify(document.activeElement.id==="fold-done")'), 'the keys left the head it opened')
        self.browser.click('#fold-working')
        self.assertEqual(self.browser.eval(ROWS)['working'], ['e2e-side-b', 'e2e-side-a'], 'b, with the newest message, on top')

    def test_on_a_phone_there_is_no_edge_to_drag_and_the_sections_fold(self):
        self.board_with_topics()
        self.open(SIZES[0])
        self.browser.wait('JSON.stringify(!!document.querySelector("#fold-done"))', what='the list on the phone')
        self.assertEqual(self.browser.eval('JSON.stringify(getComputedStyle(document.querySelector("#side-size")).display)'), 'none')
        self.assertEqual(self.width(), SIZES[0][1])
        self.browser.eval('(()=>{if(folds.done)setFold("done",false);return "ok";})()')
        self.assertIn('e2e-side-d', self.browser.eval(ROWS)['done'])
        self.browser.click('#fold-done')
        self.assertEqual(self.browser.eval(ROWS)['done'], [])
        self.assertGreaterEqual(self.browser.eval('JSON.stringify(Math.round(document.querySelector("#fold-done").getBoundingClientRect().height))'), 44)
        self.browser.click('#fold-done')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Side.__dict__:
        setattr(Side, _name, None)


if __name__ == '__main__':
    unittest.main()
