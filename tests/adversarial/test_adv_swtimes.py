#!/usr/bin/env python3
"""Hostile review of swtimes152: the palette's clock never leaks, whatever way it is opened or closed; rows stay
laid out at 360 with every mark on them."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
import test_e2e_swtimes
from test_e2e import SIZES

TRACK = r'''(()=>{
  if(!window.__iv){window.__iv=new Set();const si=window.setInterval,ci=window.clearInterval;
    window.setInterval=function(f,ms,...a){const id=si.call(window,f,ms,...a);if(f===tickSwitcher)__iv.add(id);return id;};
    window.clearInterval=function(id){__iv.delete(id);return ci.call(window,id);};}
  return "ok";})()'''
LIVE = 'JSON.stringify({live:window.__iv.size,open:!switcher.hidden,tick:swTick})'


class AdvSwTimes(test_e2e_swtimes.SwitcherTimes):
    def check(self, what):
        s = self.browser.eval(LIVE)
        self.assertEqual(s['live'], 1 if s['open'] else 0, (what, s))
        if not s['open']:
            self.assertEqual(s['tick'], 0, (what, s))

    def opened(self):
        self.browser.wait('JSON.stringify(!switcher.hidden&&!!document.querySelector("#sw-results .sw-row"))', what='the palette')

    def closed(self):
        self.browser.wait('JSON.stringify(switcher.hidden)', what='closed')

    def test_adv_no_leak_desktop(self):
        self.open(SIZES[2], 'e2e-swt-min')
        self.browser.eval(TRACK)
        for _ in range(3):
            self.browser.press('Control+k'); time.sleep(0.2)
        self.check('Ctrl+K three times')
        self.browser.eval('(()=>{showSwitcher();showSwitcher();openSwitcher();return "ok";})()')
        self.check('show twice')
        if self.browser.eval('JSON.stringify(switcher.hidden)'):
            self.browser.press('Control+k'); self.opened()
        self.browser.press('Escape'); self.closed(); self.check('Esc')
        self.browser.press('Control+k'); self.opened()
        self.browser.fill('#sw-query', 'נושא של שעות'); time.sleep(0.2)
        self.browser.press('Enter'); self.closed(); self.check('a thread picked')
        self.browser.press('Control+k'); self.opened()
        self.browser.eval('(()=>{startMerge("e2e-swt-days");return "ok";})()'); self.opened(); self.check('merge from an open palette')
        self.browser.eval('(()=>{choose(switchRows.find(r=>r.t&&r.t.id==="e2e-swt-min"));return "ok";})()'); self.check('merge asked')
        self.browser.press('Escape'); time.sleep(0.3)
        if not self.browser.eval('JSON.stringify(switcher.hidden)'):
            self.browser.press('Escape'); self.closed()
        self.check('merge left')
        self.browser.press('Control+k'); self.opened()
        self.browser.fill('#sw-query', 'settings'); time.sleep(0.2)
        self.browser.eval('(()=>{choose(switchRows.find(r=>r.act));return "ok";})()'); time.sleep(0.5)
        self.check('a command picked')

    def test_adv_no_leak_phone_back(self):
        self.open(SIZES[0], '')
        self.browser.eval(TRACK)
        for _ in range(3):
            self.browser.eval('(()=>{openSwitcher();return "ok";})()'); self.opened(); self.check('phone open')
            self.browser.eval('(()=>{history.back();return "ok";})()'); self.closed(); time.sleep(0.2); self.check('phone Back')
        self.browser.eval('(()=>{openSwitcher();return "ok";})()'); self.opened()
        self.browser.eval('(()=>{history.back();history.forward();return "ok";})()'); time.sleep(1); self.check('Back then Forward')
        self.browser.eval('(()=>{if(!switcher.hidden)closeSwitcher();return "ok";})()'); time.sleep(0.5); self.check('closed')
        self.browser.eval('(()=>{openSwitcher();return "ok";})()'); self.opened()
        self.browser.eval('(()=>{choose(switchRows.find(r=>r.t&&r.t.id==="e2e-swt-hour"));return "ok";})()'); time.sleep(0.6); self.check('phone pick')

    def test_adv_typing_while_ticking_keeps_the_choice(self):
        self.open(SIZES[2], 'e2e-swt-min')
        self.browser.eval('(()=>{swTickMs=50;return "ok";})()')
        try:
            self.palette('')
            self.browser.eval('(()=>{const real=Date.now;window.__realNow=real;Date.now=()=>real.call(Date)+3*3600e3;return "ok";})()')
            for ch in 'נושא':
                self.browser.press('ArrowDown'); time.sleep(0.07)
            self.browser.fill('#sw-query', 'נושא של'); time.sleep(0.3)
            self.browser.press('ArrowDown'); time.sleep(0.2)
            s = self.browser.eval('JSON.stringify({i:switchIndex,q:query.value,act:document.querySelector("#sw-results .sw-row.active").id,focus:document.activeElement===query})')
            self.assertEqual(s['act'], 'sw-option-%d' % s['i'], s)
            self.assertTrue(s['focus'], s)
            self.assertEqual(s['q'], 'נושא של')
        finally:
            self.browser.eval('(()=>{if(window.__realNow)Date.now=window.__realNow;swTickMs=30000;return "ok";})()')

    def test_adv_360_unread_badge_space_and_mixed_title(self):
        tid = 'e2e-swt-mixed'
        if tid not in self.state()['threads']:
            self.at(3 * 3600, 'new', tid, 'Deploy של ה-gateway ל-Tailscale עם Caddy וכל השאר שלא נגמר אף פעם RTL/LTR 12/11',
                    '--state', 'on-owner', '--note', 'mixed note Caddy ו-Tailscale', '--by', 'e2e')
            for i in range(3):
                self.at(60 * (5 - i), 'say', tid, '--from', 'fork', 'הודעה %d' % i, '--state', 'on-owner', '--note', 'n')
        self.open(SIZES[0], 'e2e-swt-min')
        self.palette('Deploy')
        bad = self.browser.eval(test_e2e_swtimes.LAYOUT)
        info = self.browser.eval('JSON.stringify((()=>{const r=document.querySelector(\'#sw-results .sw-row[data-id="e2e-swt-mixed"]\');return {html:[...r.children].map(c=>c.className+":"+Math.round(c.getBoundingClientRect().width)),time:(r.querySelector(".sw-time")||{}).textContent};})())')
        self.assertEqual(bad, [], info)
        self.assertEqual(info['time'], '3 דק׳', info)


for _name in dir(test_e2e_swtimes.SwitcherTimes):
    if _name.startswith('test') and _name not in AdvSwTimes.__dict__:
        setattr(AdvSwTimes, _name, None)

if __name__ == '__main__':
    unittest.main()
