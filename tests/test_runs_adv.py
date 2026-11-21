#!/usr/bin/env python3
"""Hostile review of task 123 (run-status). Each test asserts the CORRECT outcome: a FAIL is a real hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_runs
import test_slack

ROOT = _paths.APP
LIVE = 'מריץ:\n```sh\n! echo hello\n```\n'
LIVE2 = 'מריץ:\n```sh\n! rm -rf ~/build\n```\nואז:\n```sh\n! echo hello\n```\n'


class CliHoles(test_runs.Runs):
    def test_update_of_a_live_tower_message_does_not_keep_the_old_mark_on_a_new_command(self):
        # m3: a live status card of the tower with one block; the tower says block 0 went ok
        self.cli('say', 'ops', '--from', 'tower', LIVE, '--live', '--state', 'on-owner', '--note', 'z')
        import re as _re
        self.ask('m3', 0, _re.search(r'^(! .*)$', LIVE, _re.M).group(1))
        self.cli('run-status', 'ops', 'm3', '0', 'ok')
        # then rewrites the card: block 0 is now ANOTHER command, never run
        self.cli('update', 'ops', 'm3', '--from', 'tower', LIVE2)
        mark = (self.msg('m3').get('runs') or {}).get('0')
        self.assertIsNone(mark, f'block 0 is now "! rm -rf ~/build" but still carries {mark}: the page shows ✓ בוצע on it')

    def test_run_status_names_a_block_he_asked_for(self):
        # nobody ever asked to run block 1; the page would show "✓ בוצע" on a button he never pressed
        r = self.cli('run-status', 'ops', 'm1', '1', 'ok', ok=None)
        self.assertNotEqual(r.returncode, 0, 'a run status for a block he never asked to run was stored')

    def cli(self, *args, ok=True):
        if ok is None:
            return subprocess.run([sys.executable, str(test_runs.CLI), *args], env=self.env, capture_output=True, text=True)
        return super().cli(*args, ok=ok)


class PageHoles(test_slack.SlackPageTests):
    def test_runs_adv_page(self):
        self.pure_js(r"""
        const tower={id:'m1',from:'tower',text:'```sh\n! echo hello\n```\n',ts:1000};
        const ask=o=>({id:'m2',from:'owner',ts:1010,run:{msg_id:'m1',block_index:0,sha256:sha256('! echo hello')},...o});
        const T=(msgs)=>({id:'x',status:'open',messages:msgs});
        const fails=[];const check=(name,got,want)=>{if(got!==want)fails.push(name+': got '+got+', want '+want);};

        // 1. the tower acked (it read a row with run.error, or an older tower that knows no run-status): an hour later
        //    the button must not still be a disabled "⏳ רץ" (before this change it was pressable again after the ack)
        {const m={...tower};const old=Date.now()/1000-3600;const a=ask({ts:old-5,status:'acked',acked_ts:old});
         const k=runState(T([m,a]),m,0).kind;check('acked an hour ago, the tower never said a word',k==='running'?'running (disabled for good)':'not stuck','not stuck');}

        // 2. page clock 30 s behind the server: the tower said ok at 1100 (server time); he presses again at 1110 real
        //    time, the page stamps 1080. His request is on its way / pending on the server: the button must say waiting.
        {const m={...tower,runs:{'0':{state:'ok',ts:1100}}};
         for(const d of [{delivery:'sending'},{delivery:'received',status:'pending'},{delivery:'waiting'}])
           check('skewed local ask '+JSON.stringify(d),runState(T([m,ask({ts:1080,...d,id:undefined})]),m,0).kind,'waiting');}

        // 3. a late run-status for his FIRST request arrives after his SECOND is pending: the second still waits
        {const m={...tower,runs:{'0':{state:'ok',ts:1200}}};
         const a1=ask({id:'m2',ts:1010,status:'acked',acked_ts:1020}),a2=ask({id:'m3',ts:1150,status:'pending'});
         check('late status of the first request over a pending second',runState(T([m,a1,a2]),m,0).kind,'waiting');}

        // 4. the tower edited its message (threads update): block 0 is another command. His acked request named the
        //    OLD command (its sha256): the new command was never asked for, so the button must be idle.
        {const m={...tower,text:'```sh\n! rm -rf ~/build\n```\n',edited:1030};const a=ask({status:'acked',acked_ts:1020});
         check('request for the old text of an edited block',runState(T([m,a]),m,0).kind,'idle');}

        // 5. a page in another tab sent a second request that the server refused (failed, newest); the first is still
        //    pending on the server. The button must still say waiting (and be disabled), not offer ▶ again.
        {const m={...tower};const a1=ask({status:'pending'}),a2=ask({id:undefined,ts:1030,delivery:'failed',final:true});
         check('failed newest ask over a pending older one',runState(T([m,a1,a2]),m,0).kind,'waiting');}

        if(fails.length)throw new Error('\n'+fails.join('\n'));
        """)


# only the tests of this file
for _cls, _base in ((CliHoles, test_runs.Runs), (PageHoles, test_slack.SlackPageTests)):
    for _name in dir(_base):
        if _name.startswith('test') and _name not in _cls.__dict__:
            setattr(_cls, _name, None)


if __name__ == '__main__':
    unittest.main()
