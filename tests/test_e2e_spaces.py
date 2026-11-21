#!/usr/bin/env python3
"""End to end: spaces (task 114; the design the owner approved in thread suda m418/m425: a small square at the
top-left, like Slack's workspaces).

- One space only: nothing new anywhere; Suda is as it was.
- With a second space: a square at the top-left (in the list's head on the phone, beside the snooze in a thread's
  head), with the letter of the space he is in and a red count of what waits for him in the other spaces. A press
  opens the spaces; choosing one shows only its threads. The choice stays on this device.
- From a thread: "העבר את הנושא הזה למרחב…" moves it; "מרחב חדש…" adds one.
- ⌘K finds threads of every space (each says its space), and opening one goes to its space.
Same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES

IDS = 'JSON.stringify([...document.querySelectorAll("#channels .ch")].map(b=>b.dataset.id))'
SQ_OF = '(()=>{const v=[...document.querySelectorAll(".space-sq")].filter(x=>{if(!x.offsetParent)return false;const r=x.getBoundingClientRect();if(!(r.width>0&&r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight))return false;const at=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!at&&x.contains(at);});return v.length===1?[v[0].id,v[0].textContent]:v.length?["two"]:null})()'
SQ = 'JSON.stringify(' + SQ_OF + ')'


class Spaces(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for tid, title, state in (('sp-main', 'נושא ראשי', 'working'), ('sup-a', 'טיקט אלפא', 'working'), ('sup-b', 'טיקט בטא', 'on-owner')):
            cls.ok('new', tid, title, '--state', state, '--note', 'x')

    def setUp(self):
        self.browser.eval('(()=>{try{localStorage.clear()}catch(e){};return "ok"})()')

    def tearDown(self):
        for sp in self.state().get('spaces', []):        # a scenario that failed half-way leaves nothing behind
            self.cli('space', 'rm', sp['id'])
        for tid in ('sp-main', 'sup-a', 'sup-b'):
            if self.thread(tid).get('space'):
                self.cli('move', tid, '--space', 'main')

    def ids(self):
        return self.browser.eval(IDS)

    def test_a_with_one_space_nothing_new_shows(self):
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open(size)
                self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=sup-a]"))', what='the list')
                self.assertIsNone(self.browser.eval(SQ), 'a square with one space only')
                self.assertIn('sp-main', self.ids())
                self.assertIn('sup-a', self.ids())

    def test_b_the_square_switches_spaces_and_counts_what_waits_elsewhere(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open(SIZES[0])
        sq = self.browser.wait(SQ, what='the square')
        self.assertEqual(sq[0], 'space-side')                       # the phone's list: in the list's head
        self.assertTrue(sq[1].startswith('S'))
        self.assertIn('1', sq[1], 'the count of what waits for him in the support space')
        ids = self.ids()
        self.assertIn('sp-main', ids)
        self.assertNotIn('sup-a', ids)
        self.browser.click('#space-side')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-menu:not([hidden]) [data-space=support]"))', what='the menu of spaces')
        self.browser.run('screenshot', '/tmp/suda-spaces-menu.png')
        self.browser.click('#space-menu [data-space=support]')
        self.browser.wait('JSON.stringify(!document.querySelector("#channels .ch[data-id=sp-main]")&&!!document.querySelector("#channels .ch[data-id=sup-a]"))',
                          what='only the support threads')
        self.assertTrue(self.browser.eval(SQ)[1].startswith('ת'))
        # the choice stays on this device
        self.open(SIZES[0])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=sup-a]")&&!document.querySelector("#channels .ch[data-id=sp-main]"))',
                          what='the same space after a reload')
        # in a thread on the phone: the square is beside the snooze
        self.open_thread(SIZES[0], 'sup-a', 'טיקט אלפא')
        self.browser.wait('JSON.stringify((%s)?.[0]==="space-head")' % SQ_OF, what='the one square, in the thread head')
        # on the desktop (m429, m433): no square; a slim rail beside the list, a tile per space, the count on the others
        self.open_thread(SIZES[2], 'sup-a', 'טיקט אלפא')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-rail [data-space=main]")?.offsetParent)', what='the rail')
        self.assertIsNone(self.browser.eval(SQ), 'a square on the desktop')
        rail = self.browser.eval('JSON.stringify((()=>{const r=document.getElementById("space-rail").getBoundingClientRect(),s=document.getElementById("side").getBoundingClientRect();return [Math.round(r.left-s.right),Math.round(r.width)]})())')
        self.assertTrue(-2 <= rail[0] <= 2 and rail[1] < 80, rail)          # beside the list, on its right, slim
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#space-rail [aria-current=true]").dataset.space)'), 'support')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#space-rail [data-space=main]").textContent)'), 'S')     # nothing waits there
        self.browser.click('#space-rail [data-space=main]')
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=sp-main]")&&!document.querySelector("#channels .ch[data-id=sup-a]"))',
                          what='the main space from the rail')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#space-rail [data-space=support]").textContent)'), 'ת1')   # sup-b waits for him
        self.browser.run('screenshot', '/tmp/suda-spaces-desk.png')
        self.ok('space', 'rm', 'support')

    def test_c_a_thread_moves_and_a_space_is_added_from_the_menu(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open_thread(SIZES[2], 'sp-main', 'נושא ראשי')
        self.browser.click('#info')                     # the desktop moves a thread from its details (and ⌘K)
        self.browser.wait('JSON.stringify(!!document.querySelector("#details [data-act=space-move]"))', what='move in the details')
        self.browser.click('#details [data-act=space-move]')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-menu [data-move=support]"))', what='where to move')
        self.browser.click('#space-menu [data-move=support]')
        self.until(lambda: self.thread('sp-main').get('space') == 'support', what='the move')
        self.ok('move', 'sp-main', '--space', 'main')
        # a new space, from the rail's +
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-rail [data-act=new]")?.offsetParent)', what='the rail +')
        self.browser.click('#space-rail [data-act=new]')
        self.browser.wait('JSON.stringify(!!document.querySelector("#space-menu input"))', what='the name field')
        self.browser.fill('#space-menu input', 'לקוחות')
        self.browser.press('Enter')
        self.until(lambda: any(s['name'] == 'לקוחות' for s in self.state().get('spaces', [])), what='the new space')
        for sp in self.state().get('spaces', []):
            self.ok('space', 'rm', sp['id'])

    def test_d_the_palette_finds_every_space_and_opening_goes_there(self):
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.open(SIZES[2], 'sp-main')          # a thread of the main space on the screen (the desktop opens the last one otherwise)
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=sp-main]"))', what='the main space')
        self.browser.eval('(()=>{openSwitcher();return "ok"})()')
        self.browser.fill('#sw-query', 'בטא')
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row")?.dataset.id==="sup-b")', what='the ticket found')
        self.assertIn('תמיכה', self.browser.eval('JSON.stringify(document.querySelector("#sw-results .sw-row").innerText)'))
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(view.ch==="sup-b"&&!!document.querySelector("#channels .ch[data-id=sup-a]")&&!document.querySelector("#channels .ch[data-id=sp-main]"))',
                          what='the ticket open, in its space')
        self.ok('space', 'rm', 'support')

    def test_e_the_tower_is_reached_from_every_space(self):
        """The owner, suda m492: "the tower must be reachable from all the spaces". Its thread stays in the main
        space; in every other space it stands where it does in the main one (pinned at the top while something in
        it waits for him, else its icon beside the search), opening it keeps him in the space he is in, and it
        is not counted again as "waiting in another space"."""
        if 'tower' not in self.state()['threads']:
            self.ok('new', 'tower', 'מגדל \u2014 תפעול', '--state', 'on-owner', '--note', 'צריך אותך')
        self.ok('state', 'tower', 'on-owner', '--note', 'צריך אותך', '--by', 'e2e')
        self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.browser.eval('(()=>{try{localStorage.clear()}catch(e){};return "ok"})()')
                self.open(size)
                self.browser.wait('JSON.stringify(spacesAll().length===2)', what='two spaces')
                self.browser.eval('(()=>{switchSpace("support");return "ok"})()')
                self.browser.wait('JSON.stringify(currentSpace()==="support"&&!!document.querySelector("#channels .ch[data-id=sup-a]"))', what='the support space')
                self.assertNotIn('sp-main', self.ids())
                self.assertIn('tower', self.ids(), 'the tower is not in the support space')
                import os
                if os.environ.get('SPACES_SHOTS'):
                    self.browser.run('screenshot', os.path.join(os.environ['SPACES_SHOTS'], 'tower-%s.png' % size[0]))
                # what waits elsewhere: sp-main is working, the tower is here already: nothing
                self.assertEqual(self.browser.eval('JSON.stringify(onHimIn("main"))'), 0)
                # opening it keeps him in his space
                self.browser.eval('(()=>{openChannel("tower");return "ok"})()')
                self.browser.wait('JSON.stringify(view.ch==="tower")', what='the tower open')
                time.sleep(0.5)
                self.assertEqual(self.browser.eval('JSON.stringify(currentSpace())'), 'support')
                self.assertIn('sup-a', self.ids())
        # quiet: its icon beside the search, in the other space too
        self.ok('state', 'tower', 'working', '--note', 'שקט', '--by', 'e2e')
        self.browser.eval('(()=>{try{localStorage.clear()}catch(e){};return "ok"})()')
        self.open(SIZES[2], 'sup-a')
        self.browser.wait('JSON.stringify(currentSpace()==="support"&&!!document.querySelector("#channels .ch[data-id=sup-a]"))', what='the support space')
        self.browser.wait('JSON.stringify(!$("tower-go").hidden||!!document.querySelector("#channels .ch[data-id=tower]"))', what='the tower from the support space')
        self.ok('space', 'rm', 'support')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Spaces.__dict__:
        setattr(Spaces, _name, None)


if __name__ == '__main__':
    unittest.main()
