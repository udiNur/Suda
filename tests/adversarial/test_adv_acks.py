#!/usr/bin/env python3
"""Hostile review of task 118 (threads react + the ack line under his messages). Every test states the CORRECT
outcome: a FAIL is a hole. Server tests run on a temp board (BOARDS_DIR); page tests run ackOf/reactionsOf under node."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test_acks import Acks as Base, CLI

ROOT = _paths.APP
PAGE = (ROOT / 'suda.html').read_text(encoding='utf-8')


def js_fn(name):
    start = PAGE.index('function ' + name + '(')
    return PAGE[start:PAGE.index('\n}\n', start) + 2]


class AdvServer(Base):
    def test_an_agents_mark_does_not_swallow_his_own_press(self):
        """An agent put ❓ (or 👍) on a message. He presses the same quick mark: the page sends on=true (the chip is
        not his). His mark must be stored as his, and his ❓ must still ask the tower to explain."""
        for emoji in ('❓', '👍'):
            with self.subTest(emoji=emoji):
                self.cli('react', 'job', 'm2', emoji, '--by', 'a1')
                r = self.ingest({'op': 'react', 'thread': 'job', 'msg': 'm2', 'emoji': emoji, 'on': True})
                self.assertTrue(r.get('ok'), r)
                self.assertEqual(self.msg('m2')['reactions'][emoji].get('by'), 'owner',
                                 f"his {emoji} press was swallowed by an agent's {emoji}")

    def test_an_agent_cannot_write_under_a_name_that_reads_as_his(self):
        for name in ('owner​', 'Оwnеr', 'ｏｗｎｅｒ', 'me‏', 'Human'):
            with self.subTest(name=ascii(name)):
                self.cli('react', 'job', 'm1', '✅', '--by', name, ok=False)

    def test_a_mark_rings_nobody_and_moves_no_turn_on_a_thread_waiting_for_him(self):
        self.cli('say', 'job', '--from', 'fork', 'שאלה?', '--state', 'on-owner', '--note', 'תחליט')
        before = self.t()
        for e in ('✅', '👍', '❓'):
            self.cli('react', 'job', 'm1', e, '--by', 'a1')
            self.cli('react', 'job', 'm3', e, '--by', 'a1')
        after = self.t()
        self.assertEqual({k: after.get(k) for k in ('state', 'note', 'state_by', 'state_ts', 'alert', 'question')},
                         {k: before.get(k) for k in ('state', 'note', 'state_by', 'state_ts', 'alert', 'question')})
        self.assertFalse(self.record.exists() and self.record.read_text().strip(), 'a mark sent something')
        # an agent's ✅ on his message also picks it up (it leaves pending, so no second fork is sent for it)
        self.assertNotIn('m1', self.cli('pending').stdout)


class AdvPage(unittest.TestCase):
    def run_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        from test_slack import he_table         # tr() as a Hebrew installation draws it (the words these tests expect)
        src = ("'use strict';const assert=require('assert');const whoName=x=>String(x);const moment=()=>'';const now=()=>0;\n"
               + 'const L10N=' + json.dumps(he_table(), ensure_ascii=False) + ';'
               + "function tr(t,v){let o=Object.prototype.hasOwnProperty.call(L10N,t)?L10N[t]:t;if(v)o=String(o).replace(/\\{(\\w+)\\}/g,(m,k)=>Object.prototype.hasOwnProperty.call(v,k)?String(v[k]):m);return o;}\n"
               + re.search(r"const REACTIONS=.*\n", PAGE)[0] + re.search(r"const ACK_WORDS=.*\n", PAGE)[0]
               + js_fn('agentMark') + js_fn('ackOf') + js_fn('reactionsOf') + script)
        r = subprocess.run([node, '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-1200:])

    def test_tasks_moved_away_by_a_merge_are_not_done(self):
        """merge_threads marks a moved task status='done' + moved_to in the source. Nothing was done: the source's
        message must not say ✅ בוצע."""
        self.run_js(r"""
        const m={id:'m1',from:'owner',status:'acked'};
        const t={tasks:[{n:1,from:'m1',status:'done',moved_to:{thread:'big',n:4}}]};
        assert.notStrictEqual(ackOf(m,t).kind,'done','moved (not done) task shown as done');
        """)

    def test_a_task_opened_again_from_his_message_takes_back_the_agents_done(self):
        """An agent marked ✅; later a task from that very message is open (re-opened or newly added --from-msg)."""
        self.run_js(r"""
        const m={id:'m1',from:'owner',status:'acked',reactions:{'✅':{by:'a1',ts:1}}};
        const t={tasks:[{n:1,from:'m1',status:'todo'}]};
        assert.notStrictEqual(ackOf(m,t).kind,'done','open task, line says done');
        """)

    def test_odd_shapes_of_a_check_mark_agree_between_chip_and_line(self):
        """A ✅ that the chips hide (not his) must be the line's done, or else the chip must stay: never both gone."""
        self.run_js(r"""
        const bad=[];
        for(const v of ['x',1,[],{by:'Owner'},{}]){
          const m={id:'m1',from:'owner',status:'acked',reactions:{'✅':v}};
          const chip=reactionsOf(m).filter(r=>!(r.emoji==='✅'&&!r.mine)).some(r=>r.emoji==='✅');
          if(!chip&&ackOf(m,{tasks:[]}).kind!=='done')bad.push(JSON.stringify(v));
        }
        assert.deepStrictEqual(bad,[],'✅ vanished entirely for '+bad.join(' '));
        """)


if __name__ == '__main__':
    unittest.main()
