#!/usr/bin/env python3
"""Adversarial review of "on the phone, Back from a conversation always leads to the list" (suda.html: navigate,
listUnder, entryBelow, the popstate and phone listeners, the start block).

The same harness as test_e2e_back.py. Back here is `history.back()` from the page, as there; the browser's own
Back (what the phone presses) is in test_adv_back_ui.py.

`test_hole_*` assert the CORRECT behaviour and FAIL on this build: each is a hole. `test_held_*` are attacks
that the change withstood.

ADV_BACK_PAGE=<git revision> runs the same scenarios against the suda.html of that revision (written into the
temporary board of the run, nowhere else): what the change brought, apart from what was there before it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
import test_e2e_back
from test_adv_back_ui import page_of_another_revision
from test_e2e import SIZES

COVER, INNER, DESKTOP = SIZES[0], SIZES[1], SIZES[2]
A, B = test_e2e_back.A, test_e2e_back.B
ENTRIES = 'JSON.stringify(navigation.entries().map(e=>{const u=new URL(e.url);return u.pathname.split("/").pop()+u.hash}))'
THROW = '()=>{throw new DOMException("not here","SecurityError")}'


class Adversary(test_e2e_back.Back):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        page_of_another_revision(cls)

    def js(self, code):
        return self.browser.eval('(()=>{%s;return "ok";})()' % code)

    def press_back(self):
        """One Back; where the tab is afterwards. (Leaving the page breaks the script that pressed: that is an answer.)"""
        try:
            self.js('history.back()')
        except RuntimeError:
            pass
        time.sleep(0.8)
        return self.where()

    def entries(self):
        return self.browser.eval(ENTRIES)

    def nav(self):
        return self.browser.eval('JSON.stringify({ch:view.ch,under:view.under,hash:location.hash,len:history.length,at:navigation.currentEntry.index,'
                                 'held:history.state&&{ch:history.state.ch,under:history.state.under}})')

    def synced(self, narrow=False):
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced%s)' % ('&&phone.matches' if narrow else ''), timeout=30, what='the page again')

    def turn(self, size, narrow):
        """Another width, once the page's own listeners of the change have run (this one is added after them:
        `phone.matches` alone is true before they are called)."""
        self.browser.eval('(()=>{window.__turned=0;if(!window.__turns){window.__turns=1;phone.addEventListener("change",()=>{window.__turned=1;});}return "ok";})()')
        self.browser.viewport(size[1], size[2])
        self.browser.wait('JSON.stringify(phone.matches===%s&&window.__turned===1)' % ('true' if narrow else 'false'), what='the narrow screen' if narrow else 'the wide screen')
        time.sleep(0.3)

    def fold(self):
        self.turn(COVER, True)

    def unfold(self, size=INNER):
        self.turn(size, False)

    def from_the_list(self, tid):
        self.fresh(COVER)
        self.js('openChannel(%s)' % json.dumps(tid))
        self.inside(tid)

    def choose_in_the_switcher(self, tid):
        """The real way: the switcher is opened and a row of it is pressed (choose(), suda.html:6702)."""
        self.js('openSwitcher()')
        self.browser.wait('JSON.stringify(!switcher.hidden&&view.sw&&view.under==="self")', what='the switcher as its own entry')
        self.browser.click('#sw-results [data-id="%s"]' % tid)
        self.inside(tid)

    # ── holes ────────────────────────────────────────────────────────────────

    def test_hole_every_choice_in_the_switcher_piles_a_list_and_a_thread(self):
        """test_e2e_back's "the switcher" does not press a row: it goes back and calls openChannel, which choose()
        never does. The real choice turns the switcher's entry into the thread, and listUnder then makes it a list
        and pushes the thread: two entries more for every switch, with the older threads left between the lists."""
        self.from_the_list(A)
        self.choose_in_the_switcher(B)
        one = self.entries()
        self.choose_in_the_switcher(A)
        self.choose_in_the_switcher(B)
        three = self.entries()
        self.back_shows_the_list('a thread chosen in the switcher')
        again = self.press_back()
        with self.subTest('Back from the list does not open a thread he left before'):
            self.assertFalse(again['suda'] and again['ch'], 'Back from the list opened %s again; the history is %s' % (again.get('ch'), three))
        with self.subTest('the history does not grow with every switch'):
            self.assertEqual(len(three), len(one), 'after one switch %s, after three %s' % (one, three))

    def test_hole_every_link_that_arrives_piles_a_list_and_a_thread(self):
        """An address that arrives while he is inside a thread (a notification's link), also one that names a
        message of the thread that is already open."""
        self.from_the_list(A)
        self.js('location.hash="#"+%s' % json.dumps(B)); self.inside(B)
        one = self.entries()
        for mid in ('m1', 'm2'):
            self.js('location.hash="#"+%s' % json.dumps(B + '/' + mid))
            self.browser.wait('JSON.stringify(!!document.querySelector("#log .msg.flash")&&location.hash==="#"+%s)' % json.dumps(B), what='the message ' + mid)
            time.sleep(0.3)
        three = self.entries()
        self.back_shows_the_list('a link to a message of the open thread')
        again = self.press_back()
        with self.subTest('Back from the list does not open the thread he has just left'):
            self.assertFalse(again['suda'] and again['ch'], 'Back from the list opened %s again; the history is %s' % (again.get('ch'), three))
        with self.subTest('a link to a message of the open thread adds no list and no second copy of the thread'):
            self.assertLessEqual(len(three), len(one) + 2, 'after the link to the thread %s, after two links to its messages %s' % (one, three))

    def test_hole_a_thread_opened_while_the_switcher_stands_over_the_list(self):
        """The switcher opened from the list is its own entry, and its address is the list's. A thread opened from
        outside it (a tapped notification: sw.js posts 'open-thread'; the "on you" toast's button) is pushed on top
        of it, and entryBelow() takes the switcher's entry for the list."""
        self.fresh(COVER)
        self.js('openSwitcher()')
        self.browser.wait('JSON.stringify(!switcher.hidden&&view.sw&&view.under==="self")', what='the switcher over the list')
        self.js('openChannel(%s)' % json.dumps(B)); self.inside(B)
        self.assertEqual(self.browser.eval('JSON.stringify(view.under)'), 'list')
        self.back_shows_the_list('a thread opened over the switcher')
        self.assertTrue(self.browser.eval('JSON.stringify(switcher.hidden)'), 'Back led to the switcher, which covers the list: %s' % self.nav())

    def test_hole_a_reload_under_the_menu_of_a_thread(self):
        """A menu on the phone is its own entry. The page that is built again does not draw it (menuFor is gone;
        the same for a picture or a text on the whole screen, and for the answer form: the start block shows only
        the switcher, the new-topic form and the snippet form), but keeps its entry: the first Back changes nothing."""
        self.from_the_list(A)
        self.js('openSheet("snooze",view.ch,null)')
        self.browser.wait('JSON.stringify(view.menu&&view.under==="self"&&!document.querySelector("#sheet").hidden)', what='the menu as its own entry')
        self.js('location.reload()'); time.sleep(0.5)
        self.synced(); self.inside(A)
        if self.browser.eval('JSON.stringify(!document.querySelector("#sheet").hidden)'):
            self.press_back()                                   # a build that draws the menu again: Back closes it first
        self.back_shows_the_list('a reload under a menu: the conversation alone is on the screen')

    def test_hole_a_window_entry_alone_after_the_page_was_built_again(self):
        """listUnder() asks the browser what is under an entry that says 'list', and takes the word of an entry that
        says 'self'. The same browser that brings back the top entry alone (the case of
        test_an_entry_that_says_the_list_is_under_it_when_nothing_is) brings back the details' entry alone."""
        for way in ('Back', 'the close button of the details'):
            with self.subTest(way=way):
                self.fresh(DESKTOP, A); self.inside(A)
                self.js('view=stateOf({ch:%s,details:true,under:"self"});history.replaceState(view,"",address(%s))' % (json.dumps(A), json.dumps(A)))
                # the premise, before the page is built again (once built, the page may rightly put the list under it)
                self.assertEqual(self.entries(), ['suda.html#' + A], 'the scenario: one entry of Suda, nothing of it underneath')
                self.browser.viewport(COVER[1], COVER[2])
                self.js('location.reload()'); time.sleep(0.5)
                self.synced(narrow=True); self.inside(A)
                if way == 'Back':
                    now = self.press_back()
                else:
                    try:
                        self.js('closeDetails()')
                    except RuntimeError:
                        pass
                    time.sleep(0.8)
                    now = self.where()
                self.assertTrue(now['suda'], '%s left the page: %s' % (way, now))

    def test_hole_pushstate_that_throws(self):
        """navigate() and listUnder() catch what pushState/replaceState throw; the page is then to go on working."""
        with self.subTest('the back button of the conversation'):
            self.fresh(COVER)
            self.js('history.pushState=%s' % THROW)
            self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
            try:
                self.js('backToList()')
            except RuntimeError:
                pass
            time.sleep(0.8)
            now = self.where()
            self.assertTrue(now['suda'], 'the back button left the page: %s' % now)
            self.assertEqual((now['ch'], now['list']), (None, True), now)
        with self.subTest('the entry of a conversation that was folded'):
            self.fresh(INNER, A); self.inside(A)
            self.js('history.pushState=%s' % THROW)
            self.fold()
            now = self.nav()
            self.assertEqual((now['ch'], now['hash'], now['held'] and now['held']['ch']), (A, '#' + A, A),
                             'the conversation is on the screen and its entry became the list: %s' % now)

    def test_hole_two_presses_on_the_back_button(self):
        """backToList() goes back a step whenever view.under is 'list'; until that step lands it still is."""
        self.from_the_list(A)
        try:
            self.js('backToList();backToList()')
        except RuntimeError:
            pass
        time.sleep(1)
        now = self.where()
        self.assertTrue(now['suda'], 'two presses on the back button left the page: %s' % now)
        self.assertEqual((now['ch'], now['list']), (None, True), now)

    def test_hole_the_open_thread_was_removed(self):
        """settle() turns the conversation's entry into a list: a second list on top of the one under it."""
        self.topics()
        for over, dead in (('', 1), ('details', 2)):
            with self.subTest(open=over or 'the conversation'):
                tid = 'e2e-adv-gone-' + (over or 'plain')
                self.ok('new', tid, 'נושא שיימחק', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
                self.from_the_list(tid)
                if over:
                    self.js('openDetails()')
                    self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')
                self.ok('rm', tid, '--yes')
                self.browser.wait('JSON.stringify(!thread(%s)&&!view.ch)' % json.dumps(tid), timeout=25, what='the removal on the page')
                time.sleep(0.5)
                now = self.press_back()
                self.assertFalse(now['suda'] and now['ch'] is None and now['list'],
                                 'he is on the list, and Back shows the same list again (%d such presses): %s' % (dead, now))

    def test_hole_a_link_to_a_thread_that_is_gone(self):
        self.fresh(COVER, 'no-such-thread')
        self.browser.wait('JSON.stringify(!view.ch)', what='the list')
        time.sleep(0.4)
        self.assertEqual(self.entries(), ['suda.html'], 'one list is enough')
        now = self.press_back()
        self.assertFalse(now['suda'], 'Back from the list showed the same list again: %s' % now)

    def test_hole_a_list_entry_with_an_address_that_names_nothing(self):
        self.fresh(COVER)
        self.js('location.hash="#Not_A_Thread!"'); time.sleep(0.6)
        now = self.nav()
        self.assertEqual((now['ch'], now['hash']), (None, ''), 'a list entry has no hash: %s' % now)

    def test_hole_a_link_to_a_message_of_the_thread_he_has_just_left(self):
        """He goes back to the list and a link to one message of the same thread arrives. apply() forgets that
        the log is drawn (logFor=null) and renderLog() returns at once, because nothing in the thread changed
        (signature===logSignature, suda.html:5369): logFor stays null, so neither renderLog nor the popstate
        listener (logFor===view.ch) ever goes to the message, and `wanted` is left standing."""
        self.from_the_list(B)
        self.back_shows_the_list('the thread')
        self.js('location.hash="#"+%s' % json.dumps(B + '/m1'))
        self.browser.wait('JSON.stringify(view.ch===%s&&!!document.querySelector("#input").offsetParent)' % json.dumps(B), what='the thread again')
        time.sleep(1.5)
        got = self.browser.eval('JSON.stringify({flash:[...document.querySelectorAll("#log .msg.flash")].map(n=>n.dataset.mid),wanted,logFor})')
        self.assertEqual((got['flash'], got['wanted']), (['m1'], None), 'the link did not land on its message: %s' % got)

    def test_hole_the_address_of_the_open_thread_loaded_again_piles_a_list_and_a_second_copy(self):
        """A notification about the thread that is already on the screen: the browser is given the very same address."""
        self.from_the_list(B)
        before = self.entries()
        self.browser.open(self.browser.eval('JSON.stringify(location.href)'))
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&view.ch===%s&&!!document.querySelector("#input").offsetParent)' % json.dumps(B), timeout=30, what='the thread, still')
        time.sleep(0.5)
        now = self.nav()
        self.assertEqual((now['ch'], now['under'], now['hash']), (B, 'list', '#' + B))
        after = self.entries()
        self.back_shows_the_list('the same address loaded again')
        again = self.press_back()
        with self.subTest('Back from the list does not open the thread he has just left'):
            self.assertFalse(again['suda'] and again['ch'], 'Back from the list opened %s again; the history is %s' % (again.get('ch'), after))
        with self.subTest('no list and no second copy of the thread are added'):
            self.assertEqual(after, before)

    def test_hole_back_on_the_wide_screen_after_a_fold_changes_nothing(self):
        """"On a wide screen nothing changes": the list that a fold put under the conversation stays there when the
        phone is opened again, and on the wide screen a list entry is turned into a conversation by settle()."""
        self.fresh(INNER, A); self.inside(A)
        self.assertEqual(self.entries(), ['suda.html#' + A])
        self.fold(); self.unfold()
        now = self.press_back()
        self.assertFalse(now['suda'] and now['ch'] == A, 'Back on the wide screen left him where he was (before the fold it left the page): %s, %s' % (now, self.entries() if now['suda'] else ''))

    # ── held ─────────────────────────────────────────────────────────────────

    def test_held_folding_and_unfolding_does_not_grow_the_history(self):
        self.fresh(INNER, A); self.inside(A)
        self.fold()
        once = self.nav()['len']
        for _ in range(5):
            self.unfold(); self.fold()
        self.assertEqual(self.nav()['len'], once)
        self.assertEqual(self.entries(), ['suda.html', 'suda.html#' + A])
        self.back_shows_the_list('folded six times')
        for _ in range(3):                                   # the list, opened and folded again
            self.unfold(); self.fold()
            self.assertEqual(self.nav()['len'], once)
            self.back_shows_the_list('the list, unfolded and folded')

    def test_held_back_forward_back_from_a_link(self):
        self.fresh(COVER, A); self.inside(A)
        self.back_shows_the_list('a link')
        self.assertEqual(self.nav()['hash'], '')
        self.js('history.forward()')
        self.browser.wait('JSON.stringify(view.ch===%s&&!!document.querySelector("#input").offsetParent)' % json.dumps(A), what='the conversation again')
        now = self.nav()
        self.assertEqual((now['ch'], now['under'], now['hash']), (A, 'list', '#' + A))
        self.assertEqual(self.entries(), ['suda.html', 'suda.html#' + A])
        self.back_shows_the_list('forward and back again')
        self.assertFalse(self.press_back()['suda'], 'the list is the bottom')

    def test_held_a_window_closed_on_the_phone_closes_only_itself(self):
        self.from_the_list(A)
        before = self.entries()
        self.js('openDetails()')
        self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details')
        self.js('closeDetails()'); time.sleep(0.8)
        now = self.nav()
        self.assertEqual((now['ch'], now['under'], now['at']), (A, 'list', 1))
        self.js('openSheet("snooze",view.ch,null)')
        self.browser.wait('JSON.stringify(view.menu&&view.under==="self")', what='the menu')
        self.js('window.__ran=[];leaveSheet(()=>window.__ran.push([view.ch,view.under,view.menu,navigation.currentEntry.index]))'); time.sleep(0.8)
        self.assertEqual(self.browser.eval('JSON.stringify(window.__ran)'), [[A, 'list', False, 1]], 'the follow-up runs once, on the conversation')
        self.assertEqual(self.entries()[:2], before)
        self.back_shows_the_list('after two windows')

    def test_held_details_opened_between_the_sizes_then_folded_and_closed(self):
        for follow in (False, True):
            with self.subTest(follow_up=follow):
                self.fresh(INNER, A); self.inside(A)
                self.js('openDetails()')
                self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')
                self.fold()
                self.assertEqual(self.nav()['under'], 'self')
                if follow:
                    self.js('afterPop=()=>openChannel(%s);history.back()' % json.dumps(B)); self.inside(B)
                    self.assertEqual(self.entries(), ['suda.html', 'suda.html#' + B])
                else:
                    self.js('closeDetails()'); time.sleep(0.8)
                    self.assertEqual(self.entries(), ['suda.html', 'suda.html#' + A])
                self.back_shows_the_list('details closed over a base that had no list')

    def test_held_the_details_panel_of_the_desktop_then_a_narrow_window(self):
        self.fresh(DESKTOP, A); self.inside(A)
        self.js('openDetails()')
        self.browser.wait('JSON.stringify(view.details)', what='the details panel')
        self.assertEqual(self.nav()['under'], None)
        self.fold()
        self.assertEqual(self.nav()['under'], 'list')
        self.js('closeDetails()'); time.sleep(0.5)
        now = self.nav()
        self.assertEqual((now['ch'], now['under'], self.browser.eval('JSON.stringify(view.details)')), (A, 'list', False))
        self.back_shows_the_list('the details panel, narrowed and closed')

    def test_held_on_the_wide_screen_an_address_adds_only_the_browsers_own_entry(self):
        self.fresh(DESKTOP, A); self.inside(A)
        before = self.nav()['len']
        self.js('location.hash="#"+%s' % json.dumps(B)); self.inside(B)
        now = self.nav()
        self.assertEqual((now['len'], now['under'], now['hash']), (before + 1, None, '#' + B))
        self.js('openChannel(%s)' % json.dumps(A)); self.inside(A)
        now = self.nav()
        self.assertEqual((now['len'], now['under'], now['hash']), (before + 1, None, '#' + A))

    def test_held_a_link_to_a_message_lands_on_the_message(self):
        flashed = 'JSON.stringify([[...document.querySelectorAll("#log .msg.flash")].map(n=>n.dataset.mid),wanted,location.hash])'
        self.fresh(COVER, A + '/m2'); self.inside(A); time.sleep(0.6)
        self.assertEqual(self.browser.eval(flashed), [['m2'], None, '#' + A])
        self.js('location.hash="#"+%s' % json.dumps(B + '/m3')); self.inside(B); time.sleep(0.6)
        self.assertEqual(self.browser.eval(flashed), [['m3'], None, '#' + B])
        self.back_shows_the_list('a link to a message')

    def test_held_a_browser_that_says_nothing_or_nonsense_about_its_entries(self):
        stubs = ('undefined', '{get currentEntry(){throw Error("x")}}', '{currentEntry:{index:5},entries:()=>[{url:"nonsense"},{url:"http://[bad"},null,null,null,null]}',
                 '{currentEntry:{index:1},entries:()=>[{url:"https://elsewhere.example/suda.html"},{}]}', '{currentEntry:{index:-1},entries:()=>[]}',
                 '{currentEntry:{index:1},entries:()=>{throw Error("x")}}')
        for stub in stubs:
            with self.subTest(navigation=stub):
                self.fresh(INNER, A); self.inside(A)
                self.js('Object.defineProperty(window,"navigation",{value:%s,configurable:true})' % stub)
                self.fold()
                now = self.browser.eval('JSON.stringify([view.ch,view.under,location.hash])')
                self.assertEqual(now, [A, 'list', '#' + A])
                self.back_shows_the_list('a browser that says ' + stub)

    def other_page(self):
        """Another page in the board's folder, not Suda (the old board.html was one; it is gone, suda m620)."""
        (self.board / 'under.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>under</title></head>'
                                               '<body><p>another page of the board</p></body></html>', encoding='utf-8')
        return self.origin + '/' + test_e2e.SLUG + '/under.html'

    def test_held_what_lies_under_is_another_page_of_the_board(self):
        self.topics()
        self.browser.open('about:blank')
        self.browser.viewport(COVER[1], COVER[2])
        self.browser.open(self.other_page())
        time.sleep(1.5)
        self.js('location.href="suda.html?from=under#"+%s' % json.dumps(A)); time.sleep(1)
        self.synced(); self.inside(A)
        self.assertEqual(self.entries(), ['under.html', 'suda.html', 'suda.html#' + A])
        self.back_shows_the_list('from another page of the board')
        now = self.press_back()
        self.assertTrue(not now['suda'] and now['href'].endswith('/under.html'), now)

    def test_held_what_lies_under_is_the_list_of_another_load_of_the_page(self):
        self.fresh(COVER)
        self.js('location.href=location.pathname+"?zz=1#"+%s' % json.dumps(A)); time.sleep(1)
        self.synced(); self.inside(A)
        self.assertEqual(self.entries(), ['suda.html', 'suda.html#' + A])
        try:
            self.js('history.back()')
        except RuntimeError:
            pass
        time.sleep(1.5)
        self.synced()
        now = self.where()
        self.assertEqual((now['suda'], now['ch'], now['list']), (True, None, True), now)

    def test_held_the_page_inside_a_frame(self):
        """The frame is as narrow as the phone; its entries are the frame's own."""
        self.topics()
        self.browser.open('about:blank')
        self.browser.viewport(DESKTOP[1], DESKTOP[2])
        self.browser.open(self.other_page())
        time.sleep(1.5)
        self.js('const f=document.createElement("iframe");f.id="adv-frame";f.style.cssText="position:fixed;inset:0 auto 0 0;width:360px;height:760px;border:0;background:#fff;z-index:99999";f.src="suda.html?framed=1#"+%s;document.body.append(f)' % json.dumps(A))

        def framed(code):
            """`code` run inside the frame (an expression that gives something JSON can carry)."""
            return self.browser.eval('(()=>{try{return JSON.stringify(document.querySelector("#adv-frame").contentWindow.eval(%s))}catch(e){return JSON.stringify(null)}})()' % json.dumps(code))

        end = time.monotonic() + 30
        while not framed('typeof synced!=="undefined"&&synced&&phone.matches&&view.ch===%s&&logFor===view.ch' % json.dumps(A)):
            self.assertLess(time.monotonic(), end, 'the page inside the frame did not come up')
            time.sleep(0.3)
        self.assertEqual(framed('[view.under,location.hash]'), ['list', '#' + A])
        self.js('history.back()'); time.sleep(1)
        self.assertEqual(self.browser.eval('JSON.stringify(location.pathname.split("/").pop())'), 'under.html', 'Back stayed in the window')
        self.assertEqual(framed('[view.ch,location.hash,!!document.querySelector("#channels [data-id]")]'), [None, '', True], 'and showed the list inside the frame')

    def test_held_the_back_button_of_the_conversation_and_back_agree(self):
        for hash in (A, A + '/m2'):
            with self.subTest(link=hash):
                self.fresh(COVER, hash); self.inside(A)
                self.js('backToList()'); time.sleep(0.8)
                now = self.where()
                self.assertEqual((now['suda'], now['ch'], now['list'], now['hash']), (True, None, True, ''), now)
                self.assertEqual(self.nav()['at'], 0, 'the button went back to the list under the conversation')

    def test_held_an_entry_of_an_older_build_built_again_on_the_phone(self):
        for held in ('{ch:%s}' % json.dumps(A), '{ch:%s,under:"nonsense",details:1}' % json.dumps(A)):
            with self.subTest(state=held):
                self.fresh(DESKTOP, A); self.inside(A)
                self.js('history.replaceState(%s,"",address(%s))' % (held, json.dumps(A)))
                self.browser.viewport(COVER[1], COVER[2])
                self.js('location.reload()'); time.sleep(0.5)
                self.synced(narrow=True); self.inside(A)
                self.js('if(view.details)closeDetails()'); time.sleep(0.3)
                self.back_shows_the_list('an entry of an older build')


for _name in dir(test_e2e_back.Back):
    if _name.startswith('test') and _name not in Adversary.__dict__:
        setattr(Adversary, _name, None)

if __name__ == '__main__':
    unittest.main()
