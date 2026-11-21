#!/usr/bin/env python3
"""End to end: the history of a task (suda-fixes task 34, owner in m151 and m153).

"Each task shows when its last thing happened, and an arrow on the task opens its own history: created, started,
every status change and by whom, its words changed, moved in a merge, archived." The same harness as test_e2e.py
(headless Chrome, the real board server on loopback, a temporary board). What is checked, at the three sizes:

  - every task row says when its last thing happened, in the words the list rows use;
  - the arrow is reached by the keyboard and opens the task's own events, oldest first, with who did each, in
    the page's right-to-left, inside the width of the list;
  - the page that opened from the summary (which carries only the last event of each task) reads the whole
    history from the thread's own file;
  - a change made while the history is open shows up in it by itself.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e import SIZES

TITLE = 'היסטוריה של משימה'


def js(value):
    return json.dumps(value, ensure_ascii=False)


class TaskHistory(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def with_history(self, tid):
        self.tid = tid
        self.ok('new', self.tid, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('task', 'add', self.tid, 'לכתוב בדיקות', '--owner', 'a2')
        self.ok('task', 'set', self.tid, '1', 'building', '--note', 'בדרך')
        self.ok('task', 'set', self.tid, '1', '--text', 'לכתוב בדיקות קודם', '--by', 'a3')
        self.ok('task', 'set', self.tid, '1', 'done')
        self.ok('task', 'add', self.tid, 'משימה שנייה', '--owner', 'owner')

    def open_tasks(self, size):
        self.open_thread(size, self.tid, TITLE)
        self.browser.eval('(()=>{store.set("tasks-open:"+%s,"1");tasksSignature="";renderTasks(thread(%s));return "ok";})()' % (js(self.tid), js(self.tid)))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tasks-list .task .task-when").length===2)', what='the time on every task row')

    def history_rows(self):
        return self.browser.eval('JSON.stringify([...document.querySelectorAll("#tasks-list .task-events .task-ev")].map(li=>li.innerText.replace(/\\s+/g," ").trim()))')

    def test_each_task_says_when_and_opens_its_own_history_at_every_size(self):
        self.with_history('e2e-taskhist-sizes')
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open_tasks(size)
                whens = self.browser.eval('JSON.stringify([...document.querySelectorAll("#tasks-list .task-when")].map(x=>x.textContent))')
                self.assertTrue(all(w in ('עכשיו',) or w.endswith('דק׳') for w in whens), whens)
                # the page opened from the summary: it holds only the last event of each task
                self.assertEqual(self.browser.eval('JSON.stringify([thread(%s).tasks[0].events===undefined,thread(%s).tasks[0].last.to])' % (js(self.tid), js(self.tid))),
                                 [True, 'done'])
                # the arrow by the keyboard
                self.browser.eval('(()=>{document.querySelector(\'#tasks-list [data-k="hist:1"]\').focus();return "ok";})()')
                self.browser.press('Enter')
                self.browser.wait('JSON.stringify(document.querySelector(\'#tasks-list [data-k="hist:1"]\').getAttribute("aria-expanded")==="true"'
                                  '&&document.querySelectorAll("#tasks-list .task-events .task-ev time").length===4)', what='the history of task 1')
                rows = self.history_rows()
                self.assertEqual(len(rows), 4, rows)
                self.assertIn('נוצרה', rows[0])
                self.assertIn('a2', rows[0])
                self.assertIn('לביצוע ← בבנייה', rows[1])
                self.assertIn('הנוסח תוקן', rows[2])
                self.assertIn('a3', rows[2])
                self.assertIn('בבנייה ← הושלם', rows[3])
                # the keys stay on the arrow after the list is drawn again
                self.assertEqual(self.browser.eval('JSON.stringify(document.activeElement&&document.activeElement.dataset.k)'), 'hist:1')
                # right to left, and inside the width of the list
                look = self.browser.eval('''JSON.stringify((()=>{const box=document.querySelector("#tasks-list .task-events"),list=document.querySelector("#tasks-list");
                  return {dir:getComputedStyle(box).direction,inside:box.getBoundingClientRect().right<=list.getBoundingClientRect().right+1&&box.getBoundingClientRect().left>=list.getBoundingClientRect().left-1,
                          overflow:list.scrollWidth>list.clientWidth+1};})())''')
                self.assertEqual(look, {'dir': 'rtl', 'inside': True, 'overflow': False})
                # opened, it is brought into view inside the list (on the phone the list is short and scrolls)
                shown = self.browser.eval('''JSON.stringify((()=>{const box=document.querySelector("#tasks-list .task-events").getBoundingClientRect(),list=document.querySelector("#tasks-list").getBoundingClientRect();
                  return box.bottom<=list.bottom+1&&box.top>=list.top-1;})())''')
                self.assertTrue(shown, 'the opened history is out of sight')
                # closed again with the same press
                self.browser.press('Enter')
                self.browser.wait('JSON.stringify(!document.querySelector("#tasks-list .task-events"))', what='the history closed')

    def test_a_change_while_the_history_is_open_shows_up_in_it(self):
        self.with_history('e2e-taskhist-live')
        self.open_tasks(SIZES[0])
        self.browser.eval('(()=>{document.querySelector(\'#tasks-list [data-k="hist:2"]\').click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tasks-list .task-events .task-ev time").length===1)', what='the history of task 2')
        self.ok('task', 'set', self.tid, '2', 'working', '--by', 'a2')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tasks-list .task-events .task-ev time").length===2)', timeout=30, what='the new event')
        rows = self.history_rows()
        self.assertIn('לביצוע ← בעבודה', rows[1])
        self.assertIn('a2', rows[1])


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in TaskHistory.__dict__:
        setattr(TaskHistory, _name, None)


if __name__ == '__main__':
    unittest.main()
