#!/usr/bin/env python3
"""Adversarial review (B) of the live dot, the page side: the live card while live.json changes under it and
while the thread changes. Same harness as test_e2e_live.py. Each test asserts the CORRECT outcome."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e_live
from test_e2e import SIZES
from test_e2e_live import P1, P2, P3, P4

FOCUS_IN_CARD = 'JSON.stringify((()=>{const a=document.activeElement;return !!(a&&a.closest&&a.closest("#live-card")&&a.dataset.act)})())'


class AdvLive(test_e2e_live.Live):

    def agents_now(self, what):
        return [
            {'pane': P1, 'name': 'alpha', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'lv-one', 'by': '', 'what': 'מריץ בדיקות', 'ts': time.time() - 30},
            {'pane': P2, 'name': 'beta', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'lv-one', 'by': '', 'what': what, 'ts': time.time()},
            {'pane': P3, 'name': 'gamma', 'session': 'orbit', 'state': 'stuck', 'why': 'limit', 'thread': 'lv-three', 'by': '', 'what': '', 'ts': time.time() - 600, 'resets': '3am'},
            {'pane': P4, 'name': 'delta', 'session': 'tools', 'state': 'idle', 'why': '', 'thread': '', 'by': '', 'what': '', 'ts': time.time() - 3600},
        ]

    def open_card(self, tid, title):
        self.open_thread(SIZES[0], tid, title)
        self.browser.wait('JSON.stringify((()=>{const c=document.querySelector("#h-live");return c&&!c.hidden})())', what='the live chip')
        self.browser.eval('(()=>{document.querySelector("#h-live").click();return "ok"})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#live-card:not([hidden]) [data-act=open]"))', what='the live card')

    def test_the_keyboard_stays_on_the_live_card_while_agents_work(self):
        """Every tool call of any agent rewrites live.json; each 5 s poll then rebuilds the whole card
        (replaceChildren), and the button the keyboard (or a screen reader) stood on is thrown away."""
        self.needs('nudge')
        self.open_card('lv-one', 'נקודה אחת')
        self.browser.eval('(()=>{document.querySelector("#live-card [data-act=open]").focus();return "ok"})()')
        self.assertTrue(self.browser.eval(FOCUS_IN_CARD))
        self.write_live(self.agents_now('עורך threads.py'))            # beta moved on to its next tool
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").innerText.includes("עורך threads.py"))', timeout=12, what='the card to follow')
        self.assertTrue(self.browser.eval(FOCUS_IN_CARD), 'focus fell out of the live card on a repaint')

    def test_a_button_pressed_stays_disabled_through_a_repaint(self):
        """nudgeAgent disables the pressed button for 0.8 s / 4 s; a repaint in between draws a fresh, enabled one."""
        self.needs('nudge')
        self.open_card('lv-one', 'נקודה אחת')
        self.browser.eval('(()=>{const b=document.querySelector("#live-card [data-pane=\'%s\'] [data-act=open]");b.disabled=true;return "ok"})()' % P1)
        self.browser.eval('(()=>{liveText=null;pullLive();return "ok"})()')        # as a change of live.json does
        self.write_live(self.agents_now('עורך x.py'))
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").innerText.includes("עורך x.py"))', timeout=12, what='the card to follow')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#live-card [data-pane=\'%s\'] [data-act=open]").disabled)' % P1),
                        'the repaint gave back a pressable button while the press is still in flight')

    def test_the_card_follows_the_thread_on_the_screen(self):
        """The card stays open when the thread changes without a pointer (keyboard, switcher, a link); its rows
        are those of the old thread until live.json changes, and a press nudges with the new thread's id."""
        self.needs('nudge')
        self.open_card('lv-one', 'נקודה אחת')
        self.browser.eval('(()=>{openChannel("lv-three");return "ok"})()')
        self.browser.wait('JSON.stringify(view.ch==="lv-three")', what='the other thread')
        time.sleep(0.5)
        card = self.browser.eval('JSON.stringify(document.querySelector("#live-card").hidden?"":document.querySelector("#live-card").innerText)')
        self.assertNotIn('alpha', card, 'the card still shows the agents of the thread he left')

    def test_esc_closes_the_topmost_overlay_first(self):
        """The switcher opened by the keyboard over an open live card: Esc closes the card underneath first."""
        self.needs('nudge')
        self.open_card('lv-one', 'נקודה אחת')
        self.browser.eval('(()=>{openSwitcher();return "ok"})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the switcher')
        self.browser.press('Escape')
        time.sleep(0.3)
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#switcher").hidden)'),
                        'Esc closed the live card under the switcher, not the switcher')


for _name in dir(test_e2e_live.Live):
    if _name.startswith('test') and _name not in AdvLive.__dict__:
        setattr(AdvLive, _name, None)


if __name__ == '__main__':
    unittest.main()
