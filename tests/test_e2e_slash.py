#!/usr/bin/env python3
"""End to end: slash commands typed in the reply box (the owner, thread suda m555, m633, m635, m637, m640).

A line that is a command is done instead of sent: /done, /s 2h, /urgent on, /task Write docs, /task 1 done (and
their Hebrew names) change the thread on the server; /status goes to the tower as his reply with `command` beside it;
the start of a name and Enter only completes it; a word that names no command, and a path, are messages.
The list he picks from while typing is test_e2e_slashui.py. The same harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import time
import unittest

import test_e2e
from test_e2e import SIZES


class Slash(test_e2e.Suda):
    def type_line(self, text, enter=True):
        """He types a line in the reply box and sends it (Enter, or the send button)."""
        self.browser.fill('#input', text)
        if enter:
            self.browser.press('Enter')
        else:
            self.browser.click('#send')

    def box(self):
        return self.browser.eval('JSON.stringify(document.querySelector("#input").value)')

    def test_commands_typed_in_the_reply_box_change_the_thread(self):
        self.needs('task-add')
        self.needs('command')
        tid = 'e2e-slash'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'פקודות בתיבה', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, 'פקודות בתיבה')
        # the page marks a plain report as read by itself after a moment on screen: here /done must be the one that does
        self.browser.eval('(()=>{readIt=function(){};clearTimeout(readTimer);readFor=null;return "ok";})()')
        self.ok('say', tid, '--from', 'fork', 'דוח בלבד')
        self.until(lambda: self.thread(tid)['state'] == 'on-owner', what='the report on him')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("דוח בלבד"))', what='the report on the page')

        # /done: read, nothing to do on his side
        self.type_line('/done')
        self.until(lambda: self.thread(tid)['state'] == 'done', what='/done on the server')
        self.assertEqual(self.box(), '')

        # /s 2h: asleep for two hours
        before = time.time()
        self.type_line('/s 2h')
        snooze = self.until(lambda: self.thread(tid).get('snooze'), what='/s on the server')
        self.assertAlmostEqual(snooze['until'], before + 7200, delta=90)
        self.ok('unsnooze', tid)

        # /urgent on, then his Hebrew word for off
        self.type_line('/urgent on', enter=False)
        self.until(lambda: self.thread(tid).get('urgent'), what='/urgent on the server')
        self.type_line('/דחוף לא')
        self.until(lambda: 'urgent' not in self.thread(tid), what='/דחוף לא on the server')

        # /task <text>, /task <n> <state>, /משימה <n> = <text>
        self.type_line('/task Write docs')
        tasks = self.until(lambda: self.thread(tid)['tasks'], what='/task on the server')
        self.assertEqual([(k['n'], k['text'], k['status'], k.get('by')) for k in tasks], [(1, 'Write docs', 'todo', 'owner')])
        self.browser.wait('JSON.stringify(document.body.innerText.includes("Write docs"))', what='the task on the page')
        self.type_line('/task 1 done')
        self.until(lambda: self.thread(tid)['tasks'][0]['status'] == 'done', what='/task 1 done on the server')
        self.type_line('/משימה 1 = Write the docs')
        self.until(lambda: self.thread(tid)['tasks'][0]['text'] == 'Write the docs', what='/משימה 1 = … on the server')

        # nothing above was sent as a message
        self.assertEqual([m['text'] for m in self.thread(tid)['messages']], ['דוח בלבד'])

        # a request to the agents: his reply, with the command beside it, for the tower
        self.type_line('/מצב')
        row = self.until(lambda: next((r for r in self.pending() if r['thread'] == tid), None), what='/מצב in `threads pending`')
        self.assertEqual((row['text'], row['command']), ('/מצב', {'name': 'status', 'args': ''}))
        self.ok('ack', tid, row['msg_id'])

        # the start of a command's name and Enter: completed in the box, nothing runs (/c never closes the topic)
        count = len(self.thread(tid)['messages'])
        self.type_line('/c')
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="/close")', what='/c completed to /close')
        self.type_line('/stat')
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="/status ")', what='/stat completed to /status')
        time.sleep(0.5)
        self.assertEqual((self.thread(tid)['status'], len(self.thread(tid)['messages'])), ('open', count))
        # as the approved mockup: a lone word that names no command is a message (a mistyped one too), and so is a path
        self.type_line('/stauts')
        self.until(lambda: len(self.thread(tid)['messages']) == count + 1, what='/stauts as a message')
        self.assertEqual(self.thread(tid)['messages'][-1]['text'], '/stauts')
        self.type_line('/Users/x/notes.txt is the file')
        self.until(lambda: len(self.thread(tid)['messages']) == count + 2, what='the message with a path')
        self.assertEqual(self.thread(tid)['messages'][-1]['text'], '/Users/x/notes.txt is the file')
        self.assertNotIn('command', self.thread(tid)['messages'][-1])

        # /close last: the thread is closed (the page names the last message it holds: wait until it holds that one)
        self.browser.wait('JSON.stringify(thread(%r).messages.at(-1).text==="/Users/x/notes.txt is the file")' % tid, what='the message in the page\'s state')
        self.type_line('/סגור')
        self.until(lambda: self.thread(tid)['status'] == 'closed', what='/סגור on the server')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Slash.__dict__:
        setattr(Slash, _name, None)


if __name__ == '__main__':
    unittest.main()
