#!/usr/bin/env python3
"""Hostile review of task 123 at 360 px: the run button's words change in place; nothing around it may move."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_e2e
import test_e2e_runs
from test_e2e import SIZES

TOWER_MSG = 'להריץ:\n```sh\n! ls\n```\n'
GEOM = 'JSON.stringify((()=>{const b=document.querySelector("#log .code-bar button.run");if(!b)return null;const r=b.getBoundingClientRect(),bar=b.closest(".code-bar").getBoundingClientRect(),row=b.closest(".msg,.row,[data-key]")||b.closest("pre")?.parentElement;const t=bar.top;return {state:b.dataset.runState,text:b.textContent,h:Math.round(r.height),bh:Math.round(bar.height),left:Math.round(r.left-bar.left),right:Math.round(bar.right-r.right),sw:document.documentElement.scrollWidth,vw:innerWidth,code:Math.round(b.closest(".code-bar").nextElementSibling?.getBoundingClientRect().top-t)}})())'


class RunsAdv(test_e2e.Suda):
    def geom(self):
        import json
        v = self.browser.eval(GEOM)
        return v if isinstance(v, dict) else json.loads(v)

    def test_360_waiting_does_not_move_anything(self):
        self.needs('run')
        tid = 'rn-adv'
        self.ok('new', tid, 'הרצה', '--state', 'working', '--note', 'x')
        self.ok('say', tid, '--from', 'tower', TOWER_MSG, '--state', 'on-owner', '--note', 'להריץ?')
        self.open_thread(SIZES[0], tid, 'הרצה')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .code-bar button.run"))', what='the run button')
        idle = self.geom()
        self.browser.click('#log .code-bar button.run')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the run dialog')
        self.browser.click('#run-ok')
        self.browser.wait('JSON.stringify(document.querySelector("#log .code-bar button.run")?.dataset.runState==="waiting")', timeout=15, what='waiting')
        waiting = self.geom()
        self.browser.run('screenshot', '/tmp/suda-run-adv-waiting-sh.png')
        print('\nidle', idle, '\nwaiting', waiting)
        for k in ('h', 'bh', 'code'):
            self.assertEqual(idle[k], waiting[k], f'{k} moved: {idle} -> {waiting}')
        self.assertGreaterEqual(waiting['left'], 0, 'the button spills out of its bar')
        self.assertLessEqual(waiting['sw'], waiting['vw'], 'the page scrolls sideways')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in RunsAdv.__dict__:
        setattr(RunsAdv, _name, None)

if __name__ == '__main__':
    unittest.main()
