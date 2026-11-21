#!/usr/bin/env python3
"""End to end: his /done always works (the owner, suda-fixes m426: "/done must always work, even if something is
open; it is always my right to finish").

- Over an open ask and an open task: the thread goes to done, the ask says "סגרת בלי לענות" and its buttons are
  gone, the task stays as it was, and the toast says both.
- A message that came while he typed /done is not put away in silence: the toast shows it, and a press goes to it.
The same harness as test_e2e.py."""
import json
import unittest

import _paths  # noqa: F401  (the test folders on sys.path)
import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
TOASTS = '[...document.querySelectorAll(".toast")].map(n=>n.innerText).join("\\n")'


class Done(test_e2e.Suda):
    def type_line(self, text):
        self.browser.fill('#input', text)
        self.browser.press('Enter')

    def toasts(self):
        return self.browser.eval('JSON.stringify(%s)' % TOASTS)

    def test_his_done_ends_his_turn_over_an_open_ask_and_open_tasks(self):
        for size in (DESK, COVER):
            tid = 'e2e-done-' + size[0]
            with self.subTest(size=size[0]):
                self.ok('new', tid, 'סיום ' + size[0], '--state', 'working', '--note', 'בונה', '--by', 'e2e')
                self.ok('say', tid, '--from', 'fork', 'דוח')
                self.ok('ask', tid, 'לפרוס עכשיו?', '--options', 'כן,לא', '--from', 'fork')
                self.ok('task', 'add', tid, 'לבנות את א')
                self.open_thread(size, tid, 'סיום ' + size[0])
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .opts .opt:not(:disabled)"))', what='the ask, open')
                self.type_line('/done')
                t = self.until(lambda: (lambda t: t if t['state'] == 'done' else None)(self.thread(tid)), what='/done on the server')
                self.assertEqual((t['questions'], [k['status'] for k in t['tasks']]), ([], ['todo']))
                self.browser.wait('JSON.stringify(%s.includes("השאלה הפתוחה נסגרה בלי תשובה"))' % TOASTS, what='the toast')
                self.assertIn('משימה פתוחה אחת נשארה', self.toasts())
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .q-closed"))', what='"סגרת בלי לענות" under the ask')
                self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll("#log .opts .opt:not(:disabled)").length)'), 0)
                self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#input").value)'), '')

    def test_a_message_that_came_while_he_typed_done_is_shown_not_lost(self):
        tid = 'e2e-done-late'
        self.ok('new', tid, 'סיום מאוחר', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', 'דוח')
        self.open_thread(DESK, tid, 'סיום מאוחר')
        self.browser.eval('(()=>{readIt=function(){};clearTimeout(readTimer);readFor=null;return "ok";})()')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("דוח"))', what='the report')
        # a message comes while he types: his /done goes naming the last one he had on the screen (m1)
        self.ok('say', tid, '--from', 'fork', 'עוד דבר חשוב', '--state', 'on-owner', '--note', 'להחליט')
        self.browser.eval('(()=>{slashDone(%s,"m1");return "ok";})()' % json.dumps(tid))
        self.until(lambda: self.thread(tid)['state'] == 'done', what='/done on the server')
        self.browser.wait('JSON.stringify(%s.includes("עוד דבר חשוב"))' % TOASTS, what='the message he had not seen, in the toast')
        self.browser.eval('(()=>{const b=[...document.querySelectorAll(".toast .text-btn")].find(x=>x.textContent.includes("הצג"));if(!b)throw Error("no button");b.click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("עוד דבר חשוב"))', what='the message on the page')


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(Done(name) for name in sorted(vars(Done)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
