#!/usr/bin/env python3
"""Hostile review, round 3, of the Back hardening: the BROWSER'S OWN Back (what Snap's canGoBack()/goBack() is),
pressed through the helper extension of test_adv_back_ui.py. Every `test_hole_*` asserts the CORRECT outcome.

The attack here is on `touched`, the page's idea of "a touch since the browser's last navigation", which decides
whether it may push an entry (an entry pushed with no user activation since the browser's last navigation makes
the browser's Back pass over the entry under it, and over all of the page's entries with it). It is set by any
trusted key, pointerup or touchend while `navigator.userActivation.isActive`, which is the TRANSIENT activation
(about 5 s after any tap), not "a gesture since the last navigation": a key that gives no activation (Escape), or
the end of a finger's scroll, a moment after the browser's Back counts as a touch (test_hole_*). The page's own
history.back() and replaceState do not reset the browser's mark (test_held_*: those held).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e_back
import test_adv_back_ui as base
from test_e2e import SIZES

COVER, INNER, DESKTOP = SIZES[0], SIZES[1], SIZES[2]
A, B = test_e2e_back.A, test_e2e_back.B


class Ui3(base.UiBack):

    def page_touched(self):
        return self.browser.eval('JSON.stringify(touched)')

    def test_held_a_thread_tapped_on_the_wide_screen_and_then_the_phone_is_folded(self):
        """On the inner screen of the Fold he taps another thread in the list beside the conversation: openChannel()
        REPLACES the entry, `touched` stays true. He folds the phone: listUnder() sees a touch, writes the list over
        the entry and pushes the conversation, though no touch came after the browser's last navigation."""
        self.fresh(INNER, A); self.helper()
        self.inside(A)
        self.tap('#channels .ch[data-id="%s"]' % B)
        self.inside(B)
        self.assertTrue(self.page_touched(), 'the tap did not count as a touch')
        self.fold()
        self.assertEqual(self.browser.eval('JSON.stringify(view.under)'), 'list')
        self.ui_back_shows_the_list('a thread tapped on the wide screen, then folded')

    def test_held_a_key_a_moment_after_his_back_is_taken_for_a_touch(self):
        """He taps the conversation's back arrow (to the list), then a key that gives no activation (Escape: Esc on a
        keyboard, or the end of a scroll) within the 5 s of the tap's transient activation: `touched` becomes true.
        A thread is then opened for him (a notification: sw.js 'open-thread' -> openChannel) and is PUSHED."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.tap('#back')
        self.browser.wait('JSON.stringify(view.ch===null)', what='the list')
        self.browser.press('Escape')
        # the attack's premise: the tap's few seconds of activation are still on (what the page used to take for a touch)
        self.assertTrue(self.browser.eval('JSON.stringify(navigator.userActivation.isActive)'), 'the tap\'s activation is over: the attack does not apply, too slow?')
        self.js('openChannel(%s)' % json.dumps(B))
        self.inside(B)
        self.ui_back_shows_the_list('a thread opened for him after a key that gave no activation')

    def test_held_an_address_that_arrived_after_a_tap_then_the_details_closed_and_folded(self):
        """A tap in the thread (touched), the address of another arrives and takes its place (replaceState), he
        unfolds to the inner screen, opens nothing, folds again: every push the page makes now leans on the old tap."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.tap('#scroll')
        self.browser.open(self.browser.eval('JSON.stringify(location.href.split("#")[0])') + '#' + B)
        self.inside(B)
        self.browser.viewport(INNER[1], INNER[2]); time.sleep(0.8)
        self.fold()
        self.ui_back_shows_the_list('an address after a tap, unfolded and folded')

    def test_hole_a_key_a_moment_after_the_browsers_back_is_taken_for_a_touch(self):
        """As above, but the way out is the BROWSER'S Back (his phone's Back, which resets the browser's "a gesture
        since the last navigation"), within 5 s of his tap on the thread. The key (or the end of a finger's scroll
        of the list) finds `navigator.userActivation.isActive` still true from that older tap: `touched`. The
        thread opened for him then is PUSHED with no gesture since the Back: the list under it is passed over."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.ui_back_shows_the_list('the first way out')
        self.browser.press('Escape')
        state = self.browser.eval('JSON.stringify([touched,navigator.userActivation.isActive])')
        # the attack's premise: the older tap's few seconds of activation are still on (the page used to take the key for a touch)
        self.assertEqual(state[1], True, 'the tap\'s activation is over (%s): the attack did not apply, too slow?' % state)
        self.js('openChannel(%s)' % json.dumps(B))
        self.inside(B)
        self.ui_back_shows_the_list('a thread opened for him after a key that gave no activation, after the browser\'s Back')

    def test_held_a_thread_tapped_in_the_list_after_his_back(self):
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.ui_back_shows_the_list('the first way out')
        self.tap('#channels .ch[data-id="%s"]' % B)
        self.inside(B)
        self.ui_back_shows_the_list('a thread tapped after a Back')

    def test_held_two_notifications_opened_from_the_list_one_after_another(self):
        """Two hops on the same entry at once (openChannel twice from the list with no touch)."""
        self.fresh(COVER); self.helper()
        self.tap('#channels .ch[data-id="%s"]' % A)
        self.inside(A)
        self.ui_back_shows_the_list('the first way out')
        self.js('openChannel(%s);openChannel(%s)' % (json.dumps(A), json.dumps(B)))
        time.sleep(1.0)
        ch = self.browser.eval('JSON.stringify(view.ch)')
        self.assertIn(ch, (A, B))
        self.ui_back_shows_the_list('two threads opened for him at once')


for _name in dir(base.UiBack):
    if _name.startswith('test') and _name not in Ui3.__dict__:
        setattr(Ui3, _name, None)

if __name__ == '__main__':
    unittest.main()
