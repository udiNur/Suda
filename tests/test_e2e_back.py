#!/usr/bin/env python3
"""End to end: on the phone, Back from a conversation always leads to the list (the owner, thread suda m407).

"I was inside one thread, pressed Back, and it told me I was already on the first page. That was wrong: Back
should have led me to the screen of all the threads. This must not happen." Inside Snap the phone's Back asks the
page's own history to go back; with nothing under the conversation there is nowhere to go. The page put the list
under a conversation only when it was opened from the list, or loaded on a narrow screen straight from a link.
The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board).

What is checked, for every way into a conversation: one Back shows the list, on the same page.
  - from the list; from a link straight to the thread, and to one message of it;
  - opened on the wide screen of the Fold, then the phone is folded to its narrow screen;
  - an address that names another thread arrives while the page is open (what a notification's link does);
  - a switch to another thread from inside a thread (the switcher, a link in a message, a notification's tap);
  - a reload inside a thread, also of an entry that was made on the wide screen;
  - a new topic opened from the phone.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER = SIZES[0], SIZES[1]
A, B = 'e2e-back-a', 'e2e-back-b'


class Back(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def topics(self):
        if A in self.state()['threads']:
            return
        self.ok('new', A, 'נושא ראשון', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', B, 'נושא שני', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for n in range(1, 4):
            self.ok('say', A, '--from', 'fork', 'הודעה %d בראשון' % n, '--state', 'working', '--note', 'בודקים')
            self.ok('say', B, '--from', 'fork', 'הודעה %d בשני' % n, '--state', 'working', '--note', 'בודקים')

    def fresh(self, size, hash=''):
        """A page with nothing under it in the tab's history but an empty page, as a link opened from outside has."""
        self.topics()
        self.browser.open('about:blank')
        self.open(size, hash)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', timeout=30, what='the state on the page')

    def inside(self, tid):
        self.browser.wait('JSON.stringify(view.ch===%s&&logFor===%s&&!!document.querySelector("#input").offsetParent)' % (json.dumps(tid), json.dumps(tid)), timeout=20, what='the conversation of ' + tid)

    def where(self):
        """Where the tab is now: still Suda? which thread is open? is the list on the screen?"""
        got = self.browser.eval('JSON.stringify({suda:/suda\\.html$/.test(location.pathname),href:location.href.slice(0,60)})')
        if not got['suda']:
            return {'suda': False, 'href': got['href']}
        return self.browser.eval('(()=>{const row=document.querySelector("#channels [data-id]");return JSON.stringify({suda:true,ch:view.ch,under:view.under,'
                                 'list:!!row&&!!row.offsetParent&&getComputedStyle(document.querySelector("#side")).visibility!=="hidden",hash:location.hash});})()')

    def back_shows_the_list(self, what):
        self.browser.eval('(()=>{history.back();return "ok";})()')
        time.sleep(0.8)
        now = self.where()
        self.assertTrue(now['suda'], '%s: Back left the page (%s)' % (what, now))
        self.assertEqual((now['ch'], now['list']), (None, True), '%s: Back did not lead to the list: %s' % (what, now))

    def test_from_the_list(self):
        self.fresh(COVER)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))
        self.inside(A)
        self.back_shows_the_list('opened from the list')

    def test_from_a_link_to_the_thread_and_to_one_message_of_it(self):
        for hash in (A, A + '/m2'):
            with self.subTest(link=hash):
                self.fresh(COVER, hash)
                self.inside(A)
                self.back_shows_the_list('a link to ' + hash)

    def test_opened_on_the_wide_screen_and_then_the_phone_was_folded(self):
        self.fresh(INNER, A)
        self.inside(A)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(B))        # on the wide screen a switch only replaces
        self.inside(B)
        self.browser.viewport(COVER[1], COVER[2])                                          # folded: the narrow screen shows the conversation alone
        self.browser.wait('JSON.stringify(phone.matches&&view.ch===%s)' % json.dumps(B), what='the narrow screen')
        time.sleep(0.4)
        self.back_shows_the_list('opened wide, then folded')

    def test_an_address_of_another_thread_arrives_while_the_page_is_open(self):
        for start in ('the list', 'a thread'):
            with self.subTest(start=start):
                self.fresh(COVER)
                if start == 'a thread':
                    self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))
                    self.inside(A)
                self.browser.eval('(()=>{location.hash="#"+%s;return "ok";})()' % json.dumps(B))     # what the link of a notification does to an open page
                self.inside(B)
                self.back_shows_the_list('an address that arrived from ' + start)

    def test_a_switch_to_another_thread_from_inside_a_thread(self):
        ways = (('the switcher', 'showSwitcher===undefined?0:(navigate({ch:view.ch,sw:true,under:"self"},true),leaveSwitcherTo(%s))'),
                ('a link in a message', 'openChannel(%s)'),
                ('a tap on a notification', 'navigator.serviceWorker&&0,openChannel(%s)'))
        for what, act in ways:
            with self.subTest(way=what):
                self.fresh(COVER)
                self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))
                self.inside(A)
                if what == 'the switcher':
                    # the switcher is its own entry over the thread on a phone; a choice in it goes back first, then opens
                    self.browser.eval('(()=>{navigate({ch:view.ch,sw:true,under:"self"},true);return "ok";})()')
                    self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the switcher')
                    self.browser.eval('(()=>{afterPop=()=>openChannel(%s);history.back();return "ok";})()' % json.dumps(B))
                else:
                    self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(B))
                self.inside(B)
                self.back_shows_the_list('a switch by ' + what)

    def test_a_switch_from_under_a_window_that_was_its_own_entry(self):
        """A thread chosen while a window over the conversation (its details, a picture on the whole screen) is the
        entry on top: the new thread takes that entry's place, and what lies under it is the old thread, not the list."""
        self.fresh(COVER)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))
        self.inside(A)
        self.browser.eval('(()=>{navigate({ch:view.ch,details:true,under:"self"},true);return "ok";})()')
        self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(B))
        self.inside(B)
        self.back_shows_the_list('a switch from under the details')

    def test_a_reload_inside_a_thread(self):
        self.fresh(COVER)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))
        self.inside(A)
        self.browser.eval('(()=>{location.reload();return "ok";})()')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', timeout=30, what='the page again')
        self.inside(A)
        self.back_shows_the_list('a reload inside a thread')

    def test_a_reload_on_the_narrow_screen_of_an_entry_made_on_the_wide_one(self):
        self.fresh(INNER, B)
        self.inside(B)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A))        # a switch on the wide screen: the entry now says what is on it
        self.inside(A)
        self.browser.viewport(COVER[1], COVER[2])
        self.browser.eval('(()=>{location.reload();return "ok";})()')        # Snap builds the page again after the screen was dark
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&phone.matches)', timeout=30, what='the page again, narrow')
        self.inside(A)
        self.back_shows_the_list('a reload of an entry made wide')

    def test_an_entry_that_says_the_list_is_under_it_when_nothing_is(self):
        """The page writes into each entry what lies under it. That word can be wrong: an app's browser that builds
        the page again may bring back the top entry alone. Where the browser itself can say what is under an entry
        (its Navigation API), the page asks it, and does not take its own word."""
        self.fresh(SIZES[2], A)
        self.inside(A)
        if not self.browser.eval('JSON.stringify(!!(window.navigation&&navigation.currentEntry&&typeof navigation.entries==="function"))'):
            self.skipTest('this browser does not say what is under an entry')
        # one entry, nothing of Suda under it, and a word that says "the list is under me"
        self.browser.eval('(()=>{view=stateOf({ch:%s,under:"list"});history.replaceState(view,"",address(%s));return "ok";})()' % (json.dumps(A), json.dumps(A)))
        self.browser.viewport(COVER[1], COVER[2])
        self.browser.eval('(()=>{location.reload();return "ok";})()')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&phone.matches)', timeout=30, what='the page again, narrow')
        self.inside(A)
        self.back_shows_the_list('an entry whose word about the list was wrong')

    def test_after_the_open_thread_was_merged_into_another(self):
        self.needs('merge')
        self.topics()
        src, dst = 'e2e-back-merge-src', 'e2e-back-merge-dst'
        self.ok('new', src, 'נושא שימוזג', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', dst, 'נושא היעד', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', src, '--from', 'fork', 'הודעה בנושא שימוזג', '--state', 'working', '--note', 'בודקים')
        self.fresh(COVER)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(src))
        self.inside(src)
        self.ok('merge', src, '--into', dst)
        self.browser.wait('JSON.stringify(!!thread(%s)&&thread(%s).status!=="open")' % (json.dumps(src), json.dumps(src)), timeout=20, what='the merge on the page')
        time.sleep(0.6)
        now = self.where()
        self.assertTrue(now['suda'] and now['ch'] in (src, dst), now)
        self.back_shows_the_list('after the open thread was merged')
        # and from the thread it was merged into, reached by the link the merge left
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(dst))
        self.inside(dst)
        self.back_shows_the_list('the thread it was merged into')

    def test_a_new_topic_opened_from_the_phone(self):
        self.needs('new')
        self.fresh(COVER)
        made = self.post({'op': 'new', 'title': 'נושא חדש מהטלפון', 'text': 'שלום', 'cid': 'back-new-1'})[2]
        tid = made['thread']
        self.browser.wait('JSON.stringify(!!thread(%s))' % json.dumps(tid), timeout=20, what='the new topic on the page')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.inside(tid)
        self.back_shows_the_list('a new topic')

    def test_on_a_wide_screen_nothing_is_put_under_a_conversation(self):
        """The list stands beside the conversation there: no entry is added, and Back leaves the page as it always did."""
        self.fresh(SIZES[2], A)
        self.inside(A)
        before = self.browser.eval('JSON.stringify(history.length)')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(B))
        self.inside(B)
        self.assertEqual(self.browser.eval('JSON.stringify([history.length,view.under])'), [before, None])

    def sudaBack(self):
        """What the app (Snap) runs before its own Back: evaluateJavascript("window.sudaBack?window.sudaBack():false")."""
        took = self.browser.eval('JSON.stringify(window.sudaBack?window.sudaBack():false)')
        time.sleep(0.8)
        return took

    def test_the_app_asks_the_page_before_its_own_back(self):
        """The browser's own Back (the app's canGoBack()/goBack()) passes over entries the page added with no touch,
        so Snap asks the page first: window.sudaBack() takes the Back (true) or leaves it to the app (false)."""
        with self.subTest('a thread opened from a link, nothing touched: to the list, and true'):
            self.fresh(COVER, A); self.inside(A)
            self.assertIs(self.sudaBack(), True)
            now = self.where()
            self.assertEqual((now['suda'], now['ch'], now['list'], now['hash']), (True, None, True, ''), now)
        with self.subTest('on the list: false, and nothing changes'):
            at = self.browser.eval('JSON.stringify([history.length,navigation.currentEntry.index,location.hash])')
            self.assertIs(self.sudaBack(), False)
            self.assertEqual(self.browser.eval('JSON.stringify([history.length,navigation.currentEntry.index,location.hash])'), at)
            self.assertEqual(self.where()['ch'], None)
        with self.subTest('the details over the conversation: only they close'):
            self.fresh(COVER)
            self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(A)); self.inside(A)
            self.browser.eval('(()=>{openDetails();return "ok";})()')
            self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')
            self.assertIs(self.sudaBack(), True)
            self.assertEqual(self.browser.eval('JSON.stringify([view.ch,view.details,view.under,navigation.currentEntry.index])'), [A, False, 'list', 1])
        with self.subTest('a menu over the conversation: only it closes'):
            self.browser.eval('(()=>{openSheet("snooze",view.ch,null);return "ok";})()')
            self.browser.wait('JSON.stringify(view.menu&&!document.querySelector("#sheet").hidden)', what='the menu')
            self.assertIs(self.sudaBack(), True)
            self.assertEqual(self.browser.eval('JSON.stringify([view.ch,view.menu,document.querySelector("#sheet").hidden])'), [A, False, True])
        with self.subTest('the search inside the thread: it closes, as Esc closes it, and the conversation stays'):
            self.browser.eval('(()=>{openFind();return "ok";})()')
            self.browser.wait('JSON.stringify(find.open)', what='the search')
            self.assertIs(self.sudaBack(), True)
            self.assertEqual(self.browser.eval('JSON.stringify([find.open,view.ch])'), [False, A])
        with self.subTest('two calls at once from the conversation: the list, still on the page'):
            self.assertEqual(self.browser.eval('JSON.stringify([window.sudaBack(),window.sudaBack()])'), [True, True])
            time.sleep(0.8)
            now = self.where()
            self.assertEqual((now['suda'], now['ch'], now['list']), (True, None, True), now)
        with self.subTest('the wide screen with nothing over the conversation: false, the app does its own Back'):
            self.fresh(SIZES[2], A); self.inside(A)
            self.assertIs(self.sudaBack(), False)
            self.assertEqual(self.where()['ch'], A)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Back.__dict__:
        setattr(Back, _name, None)


if __name__ == '__main__':
    unittest.main()
