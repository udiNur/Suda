#!/usr/bin/env python3
"""Hostile review, round 3, of the Back hardening (suda.html: navigate/listUnder/hopTo/arrive/settle/sudaBack).

Back here is `history.back()` from the page (as test_e2e_back.py); the browser's own Back is in
test_adv_back3_ui.py. Every `test_hole_*` asserts the CORRECT outcome: a FAIL is a hole.

The class also loads an init script that hides the Navigation API on a page whose address has `nonav=1`
(Firefox, Safari before 26), so the fallbacks can be tried in the same browser.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import test_e2e
import test_e2e_back
import test_adv_back_e2e as base
from test_e2e import SIZES

COVER, INNER, DESKTOP = SIZES[0], SIZES[1], SIZES[2]
A, B = test_e2e_back.A, test_e2e_back.B
GONE = 'e2e-back-gone'
NONAV = "if(/[?&]nonav=1(&|$)/.test(location.search))Object.defineProperty(window,'navigation',{value:undefined,configurable:true});"


class Adv3(base.Adversary):

    @classmethod
    def setUpClass(cls):
        cls.init = tempfile.TemporaryDirectory(prefix='adv-back3-init-')
        path = Path(cls.init.name) / 'nonav.js'
        path.write_text(NONAV)
        os.environ['AGENT_BROWSER_INIT_SCRIPTS'] = str(path)
        try:
            super().setUpClass()
        finally:
            os.environ.pop('AGENT_BROWSER_INIT_SCRIPTS', None)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.init.cleanup()

    def leaves_or_where(self):
        try:
            return self.where()
        except RuntimeError as e:
            return {'suda': False, 'err': str(e)[:120]}

    # ── the address of a thread that does not exist arrives inside a thread ──

    def test_hole_a_link_to_a_thread_that_does_not_exist_arrives_inside_a_thread(self):
        """The 'navigate' listener cancels the browser's entry and arrive() replaces the conversation, without
        asking whether the thread exists and without settle() (the popstate that used to drop it never comes).
        settle() runs again only when the board changes (SSE), so an empty conversation of nothing stays."""
        self.from_the_list(A)
        self.js('location.hash="#%s"' % GONE)
        time.sleep(1.5)
        now = self.where()
        self.assertTrue(now['suda'], now)
        got = self.browser.eval('JSON.stringify({ch:view.ch,known:!!thread(view.ch),input:!!document.querySelector("#input").offsetParent})')
        self.assertTrue(got['ch'] is None or got['known'], 'a conversation of a thread that does not exist is on the screen: %s %s' % (got, now))

    # ── settle() trusts the entry's word that the list is under it ───────────

    def test_hole_a_gone_thread_whose_entry_says_the_list_is_under_it_with_nothing_there(self):
        """The top entry alone, built again (the case the start block and listUnder() guard against), names a thread
        that is gone meanwhile. settle() goes back on the entry's word: out of Suda. It used to show the list."""
        self.fresh(COVER)
        self.js('history.replaceState({ch:%s,under:"list"},"","#%s")' % (json.dumps(GONE), GONE))
        # this entry alone, nothing of Suda under it (history.length counts the whole tab, also the tests before)
        self.assertEqual(self.browser.eval('JSON.stringify(navigation.currentEntry.index)'), 0)
        self.js('location.reload()')
        time.sleep(0.5)
        try:
            self.synced(narrow=True)
        except (AssertionError, RuntimeError):
            pass
        time.sleep(1.5)
        now = self.leaves_or_where()
        self.assertTrue(now['suda'], 'a link to a thread that is gone took him out of Suda: %s' % now)
        self.assertEqual((now['ch'], now['list']), (None, True), now)

    # ── sudaBack's guard eats a real press ───────────────────────────────────

    def test_hole_sudaback_after_a_card_over_the_details_eats_the_next_press(self):
        """The details are their own entry (under 'self'); the help is a window that is not an entry. The first
        press closes the help and, because the view is 'self', sets the 1.5 s guard, which only a popstate clears;
        none comes. The second press (0.8 s later) answers true and does nothing."""
        self.fresh(COVER)
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        self.js('openDetails()')
        self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')
        self.js('showHelp()')
        self.assertIs(self.sudaBack(), True)
        self.assertEqual(self.browser.eval('JSON.stringify([help.hidden,view.details])'), [True, True], 'the first press closes only the help')
        took = self.sudaBack()
        self.assertEqual([took] + self.browser.eval('JSON.stringify([view.ch,view.details])'), [True, A, False],
                         'the second press, 0.8 s later, said it took the Back and did nothing')

    # ── a frame posts Escape twice (pre-existing, not of this change) ────────

    def test_held_an_agents_page_in_the_reader_posting_escape_twice(self):
        """window 'message' {kind:'suda-canvas',key:'Escape'} from a frame in the reader calls closeReader(), which on
        the phone is history.back(); the reader stays drawn until the popstate, so a second message goes back
        again: out of the conversation (or of Suda). A sandboxed agent page can do it with no key at all."""
        self.fresh(COVER)
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        self.js('openReader({title:"x",frame:"nothing-here.html"})')
        self.browser.wait('JSON.stringify(view.read&&!document.querySelector("#reader").hidden&&!!document.querySelector("#reader iframe"))', what='the reader with a frame')
        time.sleep(0.6)
        self.js('const f=document.querySelector("#reader iframe");f.srcdoc="<script>parent.postMessage({kind:\\"suda-canvas\\",key:\\"Escape\\"},\\"*\\");parent.postMessage({kind:\\"suda-canvas\\",key:\\"Escape\\"},\\"*\\");<\\/script>"')
        time.sleep(1.5)
        now = self.leaves_or_where()
        self.assertTrue(now['suda'], now)
        self.assertEqual((now['ch'], self.browser.eval('JSON.stringify(view.read)')), (A, False), 'two Escapes of a frame went back twice: %s' % now)

    # ── no Navigation API (Firefox, Safari before 26) ────────────────────────

    def open_nonav(self, hash=''):
        self.topics()
        self.browser.open('about:blank')
        self.browser.viewport(COVER[1], COVER[2])
        test_e2e.Suda.visits += 1
        self.browser.open(self.url + '?s=cover&n=%d&nonav=1' % test_e2e.Suda.visits + ('#' + hash if hash else ''))
        self.synced(narrow=True)
        self.assertEqual(self.browser.eval('JSON.stringify(window.navigation===undefined)'), True, 'the init script did not hide the Navigation API')

    def walk_back(self, steps=4):
        seen = []
        for _ in range(steps):
            now = self.press_back() if not seen or seen[-1].get('suda') else None
            if now is None:
                break
            try:
                seen.append({k: now.get(k) for k in ('suda', 'ch', 'list')})
            except AttributeError:
                seen.append({'suda': False})
            if not seen[-1]['suda']:
                break
        return seen

    def assert_list_then_out(self, seen, what):
        at = next((i for i, s in enumerate(seen) if s['suda'] and s['ch'] is None and s['list']), None)
        self.assertIsNotNone(at, '%s: Back never showed the list: %s' % (what, seen))
        after = seen[at + 1:]
        self.assertFalse(any(s['suda'] and s['ch'] for s in after), '%s: Back from the list opened a thread again: %s' % (what, seen))

    def test_hole_no_navigation_api_a_reload_under_the_menu_of_a_thread(self):
        """Without the API the start block cannot see what lies under a window entry it cannot draw (the menu), so
        it makes the entry the conversation's with nothing under it; settle() then writes a list over it and pushes
        the conversation once more: [list, A, list, A]. Back from the list opens A again."""
        self.open_nonav()
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        self.js('openSheet("snooze",view.ch,null)')
        self.browser.wait('JSON.stringify(view.menu&&view.under==="self")', what='the menu as its own entry')
        self.js('location.reload()'); time.sleep(0.5)
        self.synced(narrow=True); self.inside(A); time.sleep(0.8)
        length = self.browser.eval('JSON.stringify(history.length)')
        seen = self.walk_back()
        self.assert_list_then_out(seen, 'no Navigation API, reload under a menu (history.length %s)' % length)

    def test_hole_no_navigation_api_two_links_that_arrive_inside_a_thread(self):
        """Without the API no 'navigate' listener: every address that arrives in a conversation is the browser's
        entry, and listUnder() puts a list under each one."""
        self.open_nonav()
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        self.js('location.hash="#"+%s' % json.dumps(B)); self.inside(B); time.sleep(0.5)
        self.js('location.hash="#"+%s' % json.dumps(A)); self.inside(A); time.sleep(0.5)
        seen = self.walk_back(6)
        self.assert_list_then_out(seen, 'no Navigation API, two links inside a thread')

    # ── held / probes ────────────────────────────────────────────────────────

    def test_held_a_hash_link_that_names_no_thread_is_not_cancelled(self):
        """'#' (the secure link, the CSV button) and other hashes that are no thread are left to the browser."""
        self.from_the_list(A)
        before = self.browser.eval('JSON.stringify(history.length)')
        self.js('location.hash="#"')
        time.sleep(0.6)
        self.assertEqual(self.browser.eval('JSON.stringify([history.length,view.ch])'), [before + 1, None])

    def test_held_a_link_to_another_page_of_the_board_is_not_cancelled(self):
        self.from_the_list(A)
        self.js('location.href=location.pathname.replace(/suda\\.html$/,"state.json")')
        time.sleep(1.5)
        self.assertFalse(self.leaves_or_where()['suda'])

    def test_held_sudaback_from_a_frame_is_out_of_reach(self):
        self.fresh(COVER)
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        self.js('const f=document.createElement("iframe");f.setAttribute("sandbox","allow-scripts");f.srcdoc="<script>try{parent.sudaBack();parent.postMessage({kind:\\"adv\\",r:\\"reached\\"},\\"*\\")}catch(e){parent.postMessage({kind:\\"adv\\",r:String(e.name)},\\"*\\")}<\\/script>";'
                'window.__adv=null;addEventListener("message",e=>{if(e.data&&e.data.kind==="adv")window.__adv=e.data.r;});document.body.append(f)')
        got = self.browser.wait('JSON.stringify(window.__adv)', what='the frame\'s answer')
        self.assertEqual(got, 'SecurityError')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), A)

    def test_held_sudaback_before_the_threads_are_known_and_twice(self):
        self.topics()
        self.browser.open('about:blank')
        self.browser.viewport(COVER[1], COVER[2])
        test_e2e.Suda.visits += 1
        self.browser.open(self.url + '?s=cover&n=%d#%s' % (test_e2e.Suda.visits, A))
        took = self.browser.eval('JSON.stringify([typeof loaded!=="undefined"&&loaded,window.sudaBack(),window.sudaBack()])')
        time.sleep(1.0)
        self.synced(narrow=True); time.sleep(0.8)
        now = self.where()
        self.assertEqual((took[1], took[2], now['suda'], now['ch'], now['list']), (True, True, True, None, True), (took, now))


for _name in dir(base.Adversary):
    if _name.startswith('test') and _name not in Adv3.__dict__:
        setattr(Adv3, _name, None)

if __name__ == '__main__':
    unittest.main()
