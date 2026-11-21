#!/usr/bin/env python3
"""Hostile review of the ⌘K command center (suda m507). Each test asserts the CORRECT outcome: a failure is a hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
import test_slack
from test_e2e import SIZES

ROWS = test_e2e  # namespace only


class PalUnit(test_slack.SlackPageTests):
    def test_new_space_is_found_by_new_space(self):
        """'מרחב חדש…' has no 'new' in its words: "new space" finds nothing, "new" finds only 'נושא חדש'."""
        self.pure_js(r"""
        const hay=l=>l+' '+cmdWords(l);
        assert.ok(cmdScore(hay('מרחב חדש…'),'new space')>0,'new space');
        """)

    def test_a_bad_recent_list_in_storage_is_harmless(self):
        self.pure_js(r"""
        const acts=[{id:'a'},{id:'b'}];
        for(const ids of [null,5,'x',{},[1,2],[null],[{}],Array(10000).fill('a'),['b','b','a']]){
          const r=recentFirst(acts,ids,4);assert.ok(Array.isArray(r.recent)&&Array.isArray(r.rest));
          assert.strictEqual(r.recent.length+r.rest.length,2);
        }
        """)


class PalE2E(test_e2e.Suda):
    def test_the_highlighted_thread_stays_when_a_recent_command_goes_away_in_a_live_update(self):
        """Empty ⌘K: recents on top, the highlight on the first waiting thread (index = number of recents).
        A live update that removes a recent command (the open thread was closed elsewhere: 'urgent', 'mute' no
        longer apply) keeps switchIndex as a number, so the highlight and Enter move to another row."""
        if 'tower' not in self.state()['threads']:
            self.ok('new', 'tower', 'מגדל: תפעול', '--state', 'working', '--note', 'שקט', '--by', 'e2e')
        for tid, title, state in (('adv-pa1', 'נושא פתוח', 'working'), ('adv-pa2', 'מחכה לך ראשון', 'on-owner'), ('adv-pa3', 'נושא שלישי', 'working')):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', state, '--note', 'בונה', '--by', 'e2e')
        self.open_thread(SIZES[2], 'adv-pa1', 'נושא פתוח')
        self.browser.eval('(()=>{store.set("palette-recent",JSON.stringify(["urgent","mute","details","settings"]));return "ok";})()')
        self.browser.press('Control+k')
        self.browser.wait('JSON.stringify(!switcher.hidden)', what='the palette')
        before = self.browser.eval('JSON.stringify({i:switchIndex,id:switchRows[switchIndex].t&&switchRows[switchIndex].t.id,recent:switchRows.filter(r=>r.recent).length})')
        self.assertEqual(before['recent'], 4, before)
        chosen = before['id']
        self.assertTrue(chosen, before)
        # (`threads resolve` leaves the thread open until it closes by itself: the thread is closed in the page, and
        # the page drawn again through render(), the way a live update draws it)
        self.browser.eval('(()=>{const t=thread("adv-pa1");t.status="closed";t.closed_ts=Math.floor(Date.now()/1000);render();return "ok";})()')
        self.browser.wait('JSON.stringify(switchRows.filter(r=>r.recent).length<4)', what='the live update')
        after = self.browser.eval('JSON.stringify({i:switchIndex,id:switchRows[switchIndex].t?switchRows[switchIndex].t.id:switchRows[switchIndex].act.label,recent:switchRows.filter(r=>r.recent).length})')
        self.assertEqual(after['id'], chosen, (before, after))


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in PalE2E.__dict__:
        setattr(PalE2E, _name, None)
for _name in dir(test_slack.SlackPageTests):
    if _name.startswith('test') and _name not in PalUnit.__dict__:
        setattr(PalUnit, _name, None)

if __name__ == '__main__':
    unittest.main()
