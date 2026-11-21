#!/usr/bin/env python3
"""End to end: tasks he marks one after another stay as he marked them (the owner, thread suda m455).

"I approved a lot of tasks, and it was as if it finished them, then they jumped back, and jumped again." A press
on a task changed only the page's copy and sent the op; the board's copy that came back after the first press
(read before the others were saved) was taken whole, so the tasks he had just marked went back to their old
state until their own saves came round. The same harness as test_e2e.py (headless Chrome, the real board server
on loopback, a temporary board). What is checked:

  - several tasks marked done in quick succession never show their old state again, at any moment, while the
    board's copies come and go; each ends done on the server;
  - a press the server refuses is put back (with the message he already gets).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-tasks'
TITLE = 'משימות שמסמנים ברצף'

# Every 15 ms, the statuses the page holds for the thread's tasks: a task that was done and went back is a jump.
WATCH = r'''(()=>{window.__seen=[];const t0=performance.now();
  window.__watch=setInterval(()=>{const t=thread(%s);if(t)window.__seen.push([Math.round(performance.now()-t0),t.tasks.map(k=>k.n+':'+k.status).join(' ')]);},15);
  return "ok";})()'''


class Tasks(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def with_tasks(self, tid, count):
        self.ok('new', tid, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for i in range(1, count + 1):
            self.ok('task', 'add', tid, 'משימה %d' % i, '--owner', 'owner')
            self.ok('task', 'set', tid, str(i), 'on-owner', '--note', 'לבדוק')

    def jumps(self, seen, ns):
        """Each moment a task that the page had shown done showed something else again."""
        done, back = set(), []
        for at, line in seen:
            states = dict(part.split(':', 1) for part in line.split())
            for n in ns:
                if states.get(str(n)) == 'done':
                    done.add(n)
                elif n in done:
                    back.append((at, n, states.get(str(n))))
        return back

    def test_tasks_marked_one_after_another_never_jump_back(self):
        tid, ns = TID, [1, 2, 3, 4, 5]
        self.with_tasks(tid, len(ns))
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                if size is not SIZES[0]:
                    for n in ns:
                        self.ok('task', 'set', tid, str(n), 'on-owner', '--note', 'שוב')
                self.open_thread(size, tid, TITLE)
                self.browser.wait('JSON.stringify(synced&&thread(%s).tasks.length===5&&thread(%s).tasks.every(k=>k.status==="on-owner"))' % (json.dumps(tid), json.dumps(tid)), what='the tasks')
                self.browser.eval(WATCH % json.dumps(tid))
                # his presses, one after another as fast as a finger goes down a list (setTask is what a press calls)
                self.browser.eval('(()=>{let i=0;const ns=%s;const go=()=>{setTask(%s,ns[i],"done");if(++i<ns.length)setTimeout(go,120);};go();return "ok";})()' % (json.dumps(ns), json.dumps(tid)))
                self.until(lambda: all(k['status'] == 'done' for k in self.thread(tid)['tasks']), timeout=30, what='every press saved')
                time.sleep(2.5)                     # the board's copies that follow the saves come and go
                seen = self.browser.eval('(()=>{clearInterval(window.__watch);return JSON.stringify(window.__seen);})()')
                self.assertTrue(seen)
                self.assertEqual(self.jumps(seen, ns), [], 'tasks he had marked done showed their old state again')
                self.assertTrue(all(part.endswith(':done') for part in seen[-1][1].split()), seen[-1])

    def test_a_press_the_server_refuses_is_put_back(self):
        tid = TID + '-no'
        self.with_tasks(tid, 1)
        self.open_thread(SIZES[0], tid, TITLE)
        self.browser.wait('JSON.stringify(synced&&thread(%s).tasks.length===1)' % json.dumps(tid), what='the task')
        # the server refuses: the thread is gone by the time the press arrives
        self.browser.eval('(()=>{window.__post=post;post=async s=>{if(s.op==="task")throw Object.assign(Error("הנושא לא נמצא"),{heard:true});return window.__post(s);};return "ok";})()')
        self.browser.eval('(()=>{setTask(%s,1,"done");return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify(thread(%s).tasks[0].status==="on-owner")' % json.dumps(tid), what='the refused press put back')
        time.sleep(1.5)
        self.assertEqual(self.browser.eval('JSON.stringify(thread(%s).tasks[0].status)' % json.dumps(tid)), 'on-owner')
        self.browser.eval('(()=>{post=window.__post;return "ok";})()')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Tasks.__dict__:
        setattr(Tasks, _name, None)


if __name__ == '__main__':
    unittest.main()
