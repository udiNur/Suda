#!/usr/bin/env python3
"""Adversarial review of "on the phone, Back from a conversation always leads to the list": the BROWSER'S OWN Back.

test_e2e_back.py presses Back with `history.back()` from the page's script. The phone does not: Snap's Back calls
`WebView.canGoBack()` / `WebView.goBack()` (Snap: WebAppActivity.java:145, WebPopupService.java:663), which is
Chromium's `NavigationController::CanGoBack()` / `GoBack()`. Those pass over every history entry that a page made
without a user activation ("history manipulation intervention", chromium docs/history_manipulation_intervention.md;
all same-document entries share the mark; after a Back of the browser an older touch no longer counts). The page's
own `history.back()` is exempt, so the scenarios of test_e2e_back.py cannot see any of it.

Here Back is pressed the way the browser's button presses it: a helper extension, loaded into the headless
browser of this class only (written to a temporary folder at run time, nothing is installed), calls
`chrome.tabs.goBack()`, which is the same `NavigationController::CanGoBack()` + `GoBack()`. A tap is a real
pointer press (`agent-browser click`), which gives the page a user activation; a script run by the harness and a
turn of the wheel give none.

Every scenario asserts the CORRECT outcome (the list, on the same page): a FAIL is a hole. The `test_0_*`
are the controls: they show that the helper presses Back, that an entry made under a finger is honoured, and
that an entry the browser itself made (an address it loaded) is honoured with no touch at all.

ADV_BACK_PAGE=<git revision> runs the same scenarios against the suda.html of that revision (written into the
temporary board of the run, nowhere else): what the change brought, apart from what was there before it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import test_e2e
import test_e2e_back
from test_e2e import SIZES

COVER, INNER, DESKTOP = SIZES[0], SIZES[1], SIZES[2]
A, B = test_e2e_back.A, test_e2e_back.B

MANIFEST = {'manifest_version': 3, 'name': 'adv-back: the browser\'s own Back', 'version': '1',
            'background': {'service_worker': 'bg.js'},
            'content_scripts': [{'matches': ['http://127.0.0.1/*'], 'js': ['cs.js'], 'run_at': 'document_start'}]}
BG = """chrome.runtime.onMessage.addListener((m,sender,reply)=>{
  if(!m||m.op!=='back'||!sender.tab)return;
  chrome.tabs.goBack(sender.tab.id).then(()=>reply({ok:true}),e=>reply({ok:false,err:String(e&&e.message||e)}));
  return true;
});"""
CS = """document.documentElement.dataset.advExt='1';
window.addEventListener('message',e=>{
  if(e.source!==window||!e.data||e.data.advBack!=='back')return;
  chrome.runtime.sendMessage({op:'back'},r=>{document.documentElement.dataset.advBack=JSON.stringify(r||{ok:false,err:String(chrome.runtime.lastError&&chrome.runtime.lastError.message)});});
});"""


def page_of_another_revision(cls):
    """ADV_BACK_PAGE: the page of that revision takes the place of the installed one, in the temporary board only."""
    rev = os.environ.get('ADV_BACK_PAGE')
    if not rev:
        return
    old = subprocess.run(['git', '-C', str(test_e2e.ROOT), 'show', rev + ':suda.html'], capture_output=True)
    assert old.returncode == 0, old.stderr
    assert cls.board.parent == cls.boards and str(cls.boards).startswith(cls.tmp.name), 'only ever the temporary board'
    (cls.board / 'suda.html').write_bytes(old.stdout)


class UiBack(test_e2e_back.Back):
    """Back as the browser's own button presses it."""

    @classmethod
    def setUpClass(cls):
        cls.ext = tempfile.TemporaryDirectory(prefix='adv-back-ext-')
        root = Path(cls.ext.name)
        (root / 'manifest.json').write_text(json.dumps(MANIFEST))
        (root / 'bg.js').write_text(BG)
        (root / 'cs.js').write_text(CS)
        os.environ['AGENT_BROWSER_EXTENSIONS'] = str(root)
        try:
            super().setUpClass()
        finally:
            os.environ.pop('AGENT_BROWSER_EXTENSIONS', None)
        page_of_another_revision(cls)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.ext.cleanup()

    def js(self, code):
        return self.browser.eval('(()=>{%s;return "ok";})()' % code)

    def helper(self):
        if not self.browser.eval('JSON.stringify(document.documentElement.dataset.advExt==="1")'):
            self.skipTest('the helper extension did not load into this browser: its own Back cannot be pressed')

    def touched(self):
        return self.browser.eval('JSON.stringify(navigator.userActivation.hasBeenActive)')

    def tap(self, selector):
        """A real pointer press: the page gets a user activation, as from a finger."""
        self.browser.run('click', selector)

    def ui_back(self):
        """The browser's own Back. Gives where the tab is, and what the browser answered (it refuses when it
        finds nothing to go back to: that is `canGoBack()==false`, Snap's "already on the first page")."""
        self.browser.eval('(()=>{delete document.documentElement.dataset.advBack;window.postMessage({advBack:"back"},"*");return "ok";})()')
        time.sleep(1.2)
        now = self.where()
        if now['suda']:
            now['browser'] = self.browser.eval('JSON.stringify(document.documentElement.dataset.advBack||"")')
        return now

    def ui_back_shows_the_list(self, what):
        now = self.ui_back()
        self.assertTrue(now['suda'], '%s: the browser\'s Back left the page (%s)' % (what, now))
        self.assertEqual((now['ch'], now['list']), (None, True), '%s: the browser\'s Back did not lead to the list: %s' % (what, now))

    def details_as_their_own_entry(self):
        self.tap('#info')
        self.browser.wait('JSON.stringify(view.details&&view.under==="self")', what='the details as their own entry')

    def fold(self):
        """The narrow screen, once the page's own listeners of the change have run (this one is added after them:
        `phone.matches` alone is true before they are called)."""
        self.browser.eval('(()=>{window.__turned=0;if(!window.__turns){window.__turns=1;phone.addEventListener("change",()=>{window.__turned=1;});}return "ok";})()')
        self.browser.viewport(COVER[1], COVER[2])
        self.browser.wait('JSON.stringify(phone.matches&&window.__turned===1)', what='the narrow screen')
        time.sleep(0.3)

    # ── the controls: an entry made under a finger is honoured ───────────────

    def test_0_control_a_thread_opened_by_a_tap_on_the_list(self):
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.assertTrue(self.touched(), 'the tap gave no user activation: the harness cannot tell the two cases apart')
        self.ui_back_shows_the_list('opened by a tap on the list')
        self.tap('#channels .ch[data-id="%s"]' % B)          # a touch after a Back counts again
        self.inside(B)
        self.ui_back_shows_the_list('opened by a tap on the list, after a Back')

    def test_0_control_a_link_and_then_a_tap_in_the_conversation(self):
        """Once he touched the page, the entries it made before are honoured too."""
        self.fresh(COVER, A); self.helper()
        self.inside(A)
        self.tap('#scroll')
        self.assertTrue(self.touched())
        self.ui_back_shows_the_list('a link, then a tap in the conversation')

    def test_0_control_a_link_that_arrives_right_after_a_tap(self):
        """He opened a thread with his finger; the address of another arrives from the browser (a notification's
        link loaded into the open page). His touch is the newest thing: the list put under it is honoured."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.browser.open(self.browser.eval('JSON.stringify(location.href.split("#")[0])') + '#' + B)
        self.inside(B)
        self.ui_back_shows_the_list('a link that arrived right after a tap')

    def test_0_control_the_list_first_and_then_the_thread_by_the_browser_with_no_touch(self):
        """The way out that needs no finger: the list is loaded, and the BROWSER (not the page) then goes to the
        thread's address. Both entries are the browser's own, so its Back sees the list. (What an app can do with
        two loadUrl calls; the page cannot do it for itself.)"""
        self.fresh(COVER); self.helper()
        self.browser.open(self.browser.eval('JSON.stringify(location.href.split("#")[0])') + '#' + A)
        self.inside(A)
        self.assertFalse(self.touched())
        self.ui_back_shows_the_list('the list, then the thread by the browser, nothing touched')

    # ── the holes ────────────────────────────────────────────────────────────

    # C1: the page alone cannot make the browser's own Back see a list it put there with no touch.
    @unittest.expectedFailure  # needs the app to call window.sudaBack() first; Snap change pending (see test_6_*)
    def test_1_a_link_straight_to_a_thread_and_back_without_touching_the_page(self):
        """A notification's link opens the thread; he reads it (scrolls) and presses Back. The page itself put the
        list under the conversation with nobody touching it, so the browser's Back passes over it."""
        self.fresh(COVER, A); self.helper()
        self.inside(A)
        self.browser.run('mouse', 'wheel', '200', check=False)          # reading: a scroll is not a touch
        self.assertFalse(self.touched())
        self.assertEqual(self.browser.eval('JSON.stringify(navigation.entries().map(e=>new URL(e.url).hash))'), ['', '#' + A],
                         'the list is there, under the conversation: only the browser\'s Back does not see it')
        self.ui_back_shows_the_list('a link to a thread, nothing touched')

    # C1: the page alone cannot make the browser's own Back see a list it put there with no touch.
    @unittest.expectedFailure  # needs the app to call window.sudaBack() first; Snap change pending (see test_6_*)
    def test_1_the_same_when_the_thread_is_the_first_page_of_its_tab(self):
        """As a window that a notification opened: nothing of another page under Suda. The browser then finds
        nothing at all to go back to. This is "already on the first page"."""
        self.topics()
        test_e2e.Suda.visits += 1
        self.browser.run('tab', 'new', self.url + '?s=cover&n=%d#%s' % (test_e2e.Suda.visits, A))
        try:
            self.browser.viewport(COVER[1], COVER[2])
            self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&phone.matches)', timeout=30, what='the page in its own tab')
            self.helper()
            self.inside(A)
            self.assertEqual(self.browser.eval('JSON.stringify([history.length,view.under])'), [2, 'list'])
            self.ui_back_shows_the_list('a thread that is the first page of its tab')
        finally:
            self.browser.run('tab', 'close', check=False)

    def test_2_a_thread_opened_for_him_after_he_went_back_to_the_list(self):
        """He is on the list after a Back. A thread is opened without his finger on the page (sw.js:106 posts
        'open-thread' for a tapped notification; suda.html announce() opens from a notification's click): a new
        entry with no touch since the Back."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.ui_back_shows_the_list('the first way out')
        self.js('openChannel(%s)' % json.dumps(B))
        self.inside(B)
        self.ui_back_shows_the_list('a thread opened for him from the list')

    def test_3_details_closed_by_back_over_a_thread_that_had_no_list_under_it(self):
        """At the inner screen's width the details are their own entry. Folded, Back closes them, and the page
        then puts the list under the conversation: inside the Back itself, with no touch (listUnder() in the
        popstate listener). The next Back passes over all of it."""
        self.fresh(INNER, A); self.helper()
        self.inside(A)
        self.details_as_their_own_entry()
        self.fold()
        now = self.ui_back()
        self.assertTrue(now['suda'] and now['ch'] == A and not self.browser.eval('JSON.stringify(view.details)'), 'Back did not close the details: %s' % now)
        self.assertEqual(self.browser.eval('JSON.stringify([view.under,navigation.entries().map(e=>new URL(e.url).hash)])'), ['list', ['', '#' + A]])
        self.ui_back_shows_the_list('after the details were closed by Back')

    def test_4_folded_after_a_back_with_no_touch_since(self):
        """On the inner screen he closes the details with Back, then folds the phone: the list is put under the
        conversation at the fold (listUnder() in the phone listener), and his last touch was before that Back."""
        self.fresh(INNER, A); self.helper()
        self.inside(A)
        self.details_as_their_own_entry()
        now = self.ui_back()
        self.assertTrue(now['suda'] and now['ch'] == A, now)
        self.fold()
        self.ui_back_shows_the_list('folded after a Back')

    def test_5_a_link_that_arrives_after_he_closed_a_window_with_back(self):
        """He opened the thread with his finger, opened its details and closed them with Back. The address of
        another thread arrives: the page puts a list and the thread on top (listUnder() in the popstate listener),
        and with that every entry of Suda, the ones his finger made too, is passed over."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.details_as_their_own_entry()
        now = self.ui_back()
        self.assertTrue(now['suda'] and now['ch'] == A, now)
        self.browser.open(self.browser.eval('JSON.stringify(location.href.split("#")[0])') + '#' + B)
        self.inside(B)
        self.ui_back_shows_the_list('a link that arrived after a Back')

    # ── the app asks the page first (window.sudaBack), as Snap is to do before its canGoBack()/goBack() ──────

    def app_back(self):
        """Snap's Back once it asks the page first: evaluateJavascript("window.sudaBack?window.sudaBack():false"),
        and its own Back (the browser's) only where the page answers false."""
        took = self.browser.eval('JSON.stringify(window.sudaBack?window.sudaBack():false)')
        if took is not True:
            return self.ui_back()
        time.sleep(1.2)
        return self.where()

    def test_6_the_app_asks_the_page_first_a_link_straight_to_a_thread(self):
        """C1 with the app's half done: the thread a notification's link opened, nothing touched, leads to the list;
        from the list the page says false and the browser's Back leaves, as it always did."""
        self.fresh(COVER, A); self.helper()
        self.inside(A)
        self.browser.run('mouse', 'wheel', '200', check=False)
        self.assertFalse(self.touched())
        now = self.app_back()
        self.assertEqual((now['suda'], now['ch'], now['list']), (True, None, True), 'the app\'s Back did not lead to the list: %s' % now)
        now = self.app_back()
        self.assertFalse(now['suda'], 'from the list the app\'s Back leaves the page: %s' % now)

    def test_6_the_app_asks_the_page_first_the_thread_is_the_first_page_of_its_tab(self):
        self.topics()
        test_e2e.Suda.visits += 1
        self.browser.run('tab', 'new', self.url + '?s=cover&n=%d#%s' % (test_e2e.Suda.visits, A))
        try:
            self.browser.viewport(COVER[1], COVER[2])
            self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&phone.matches)', timeout=30, what='the page in its own tab')
            self.helper()
            self.inside(A)
            now = self.app_back()
            self.assertEqual((now['suda'], now['ch'], now['list']), (True, None, True), 'the app\'s Back did not lead to the list: %s' % now)
        finally:
            self.browser.run('tab', 'close', check=False)


for _name in dir(test_e2e_back.Back):
    if _name.startswith('test') and _name not in UiBack.__dict__:
        setattr(UiBack, _name, None)

if __name__ == '__main__':
    unittest.main()
