#!/usr/bin/env python3
"""Hostile review of the 'urgent' mark and the order inside a section (suda m501/m505).
Every test asserts the CORRECT outcome: a failure is a real hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import unittest

import test_e2e
import test_threads
from test_e2e import SIZES


class UrgentServer(test_threads.ThreadsTests):
    def st(self, tid='topic'):
        return json.loads((self.board / 'state.json').read_text())['threads'][tid]

    def test_page_op_on_closed_thread_does_not_claim_success(self):
        """The CLI refuses a closed thread; the page op says ok (and the page toasts 'marked') while nothing is set."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'x', env=e(0))
        self.run_cli('close', 'topic', env=e(1))
        r = self.post({'op': 'urgent', 'thread': 'topic', 'on': True}, ok=None, env=e(2))
        self.assertNotIn('urgent', self.st())
        self.assertFalse(r.get('ok') and r.get('on') is not False, 'ok for a mark that was not set: %r' % r)

    def test_missing_thread_refused(self):
        r = self.post({'op': 'urgent', 'thread': 'nope', 'on': True}, ok=None, env=self.at(0))
        self.assertFalse(r.get('ok'))

    def test_merge_and_reopen_leave_no_stale_mark(self):
        e = self.at
        self.run_cli('new', 'src', 'מקור', '--state', 'working', '--note', 'x', env=e(0))
        self.run_cli('new', 'dst', 'יעד', '--state', 'working', '--note', 'x', env=e(0))
        self.run_cli('urgent', 'src', env=e(1))
        self.post({'op': 'merge', 'thread': 'src', 'into': 'dst'}, env=e(2))
        self.assertNotIn('urgent', self.st('src'))
        self.assertNotIn('urgent', self.st('dst'))
        self.run_cli('reopen', 'src', env=e(3))
        self.assertNotIn('urgent', self.st('src'))

    def test_mark_moves_no_turn_and_tells_nobody(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'on-owner', '--note', 'x', env=e(0))
        before = self.st()
        sent = len(self.record.read_text().splitlines()) if self.record.exists() else 0
        self.post({'op': 'urgent', 'thread': 'topic', 'on': True}, env=e(1))
        self.run_cli('urgent', 'topic', '--off', env=e(2))
        self.run_cli('urgent', 'topic', env=e(3))
        after = self.st()
        for k in ('state', 'state_ts', 'note', 'updated', 'alert', 'question'):
            self.assertEqual(before.get(k), after.get(k), k)
        self.assertEqual(sent, len(self.record.read_text().splitlines()) if self.record.exists() else 0)

    def test_auto_archive_drops_the_mark(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'x', env=e(0))
        self.run_cli('urgent', 'topic', env=e(1))
        self.run_cli('resolve', 'topic', '--note', 'done', env=e(2))
        self.run_cli('sweep', env=e(24 * 30))
        if self.st()['status'] != 'open':
            self.assertNotIn('urgent', self.st())

    def test_hand_edited_true_mark_can_be_set_again(self):
        """A non-number mark (true) shows nothing on the page, and the CLI says 'already' and does nothing."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'x', env=e(0))
        p = self.board / 'state.json'
        d = json.loads(p.read_text())
        d['threads']['topic']['urgent'] = True
        p.write_text(json.dumps(d))
        self.run_cli('urgent', 'topic', env=e(1))
        self.assertIsInstance(self.st().get('urgent'), (int, float))
        self.assertNotIsInstance(self.st().get('urgent'), bool)


for _n in dir(test_threads.ThreadsTests):
    if _n.startswith('test') and _n not in UrgentServer.__dict__:
        setattr(UrgentServer, _n, None)


MINE = '[...document.querySelectorAll("#channels .sec-working .ch")].map(b=>b.dataset.id).filter(i=>i.startsWith("e2e-s")).join()'


class UrgentPage(test_e2e.Suda):
    def make(self, *ids):
        for tid in ids:
            if tid not in self.state()['threads']:
                self.ok('new', tid, 'נושא ' + tid, '--state', 'working', '--note', 'בונה', '--by', 'e2e')

    def test_optimistic_mark_survives_a_refresh_on_its_way(self):
        """He presses 'mark urgent'; a board refresh (an agent wrote) lands before the server stored the press:
        the mark must not vanish and come back (the flicker fixed elsewhere with an overlay)."""
        self.make('e2e-s1', 'e2e-s2')
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(synced&&!!thread("e2e-s2"))', what='the list')
        self.browser.eval('(()=>{const orig=post;window.__gate=new Promise(r=>window.__go=r);'
                          'post=async(s,...a)=>{if(s&&s.op==="urgent")await window.__gate;return orig(s,...a);};return "ok";})()')
        self.browser.eval('(()=>{setUrgent("e2e-s2",true);return "ok";})()')
        seen = self.browser.eval('(async()=>{await refresh();render();return JSON.stringify({u:thread("e2e-s2").urgent||null,'
                                 'mark:!!document.querySelector("#channels .ch[data-id=e2e-s2] .urgent-mark")});})()')
        self.browser.eval('(()=>{window.__go();return "ok";})()')
        self.until(lambda: self.thread('e2e-s2').get('urgent'), what='the mark on the server')
        self.ok('urgent', 'e2e-s2', '--off')
        self.assertTrue(seen['u'] and seen['mark'], 'the mark vanished under a refresh while the press was on its way: %r' % seen)

    def test_recent_order_does_not_jump_under_his_pointer(self):
        """'recent': an agent writes in a lower row while his pointer is on the list: the row under the pointer must
        not change (a click lands on the row he aimed at)."""
        self.make('e2e-s3', 'e2e-s4', 'e2e-s5')
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(synced&&document.querySelectorAll("#channels .sec-working .ch").length>=3)', what='the list')
        self.browser.eval('(()=>{setListOrder("recent");return "ok";})()')
        self.ok('say', 'e2e-s3', '--from', 'fork', 'א', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.browser.wait('JSON.stringify((%s).startsWith("e2e-s3"))' % MINE, what='s3 on top')
        self.browser.run('hover', '#channels .ch[data-id=e2e-s3]')
        before = self.browser.eval('JSON.stringify(document.elementFromPoint(...(r=>[r.left+r.width/2,r.top+r.height/2])('
                                   'document.querySelector("#channels .ch[data-id=e2e-s3]").getBoundingClientRect())).closest(".ch").dataset.id)')
        self.ok('say', 'e2e-s5', '--from', 'fork', 'ב', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.browser.wait('JSON.stringify(thread("e2e-s5").messages.some(m=>m.text==="ב"))', what='the new message')
        self.browser.eval('(()=>{render();return "ok";})()')
        order = self.browser.eval('JSON.stringify(%s)' % MINE)
        self.browser.eval('(()=>{setListOrder("slot");return "ok";})()')
        self.assertTrue(order.startswith(before), 'the row under his pointer changed from %s: %s' % (before, order))

    def test_phone_mark_and_long_title(self):
        if 'e2e-s6' not in self.state()['threads']:
            self.ok('new', 'e2e-s6', 'כותרת ארוכה מאוד מאוד מאוד שלא נגמרת אף פעם וממשיכה וממשיכה עוד ועוד ועוד', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('urgent', 'e2e-s6')
        self.open(SIZES[0])
        self.browser.wait('JSON.stringify(synced)', what='synced')
        got = self.browser.eval('(()=>{const b=document.querySelector("#channels .ch[data-id=e2e-s6]");if(!b)return JSON.stringify(null);'
                                'const m=b.querySelector(".urgent-mark"),t=b.querySelector(".ch-title"),r=m.getBoundingClientRect(),q=t.getBoundingClientRect();'
                                'return JSON.stringify({w:r.width,inside:r.left>=q.left-1&&r.right<=q.right+1,ell:getComputedStyle(t).textOverflow});})()')
        if os.environ.get('URGENT_SHOTS'):
            self.browser.run('screenshot', os.path.join(os.environ['URGENT_SHOTS'], 'adv-360.png'))
        self.ok('urgent', 'e2e-s6', '--off')
        if got is not None:
            self.assertGreater(got['w'], 10)
            self.assertTrue(got['inside'], got)


for _n in dir(test_e2e.Suda):
    if _n.startswith('test') and _n not in UrgentPage.__dict__:
        setattr(UrgentPage, _n, None)


if __name__ == '__main__':
    unittest.main()
