#!/usr/bin/env python3
"""Hostile review of the slash commands (server 05d37cd, page 560272d): each test asserts the SAFE outcome, so a
FAIL is a real hole. Server tests drive `threads.py ingest` as the page does (test_threads harness); page tests run
the pure part under node (test_slack harness) or the real page headless (test_e2e harness)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import json
import time
import unittest

import test_threads
import test_slack
import test_e2e
from test_e2e import SIZES

TT = test_threads.ThreadsTests


class ServerAdv(unittest.TestCase):
    T0 = TT.T0
    setUp, run_cli, at, thread, post = TT.setUp, TT.run_cli, TT.at, TT.thread, TT.post

    def tower_block(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', '```\n! echo hi\n```', env=e(0))
        return {'msg_id': 'm1', 'block_index': 0, 'sha256': hashlib.sha256(b'! echo hi').hexdigest()}

    def test_slash_run_exactly_as_the_page_sends_it_is_accepted(self):
        """HIGH. sendRun() (suda.html) sends text '▶ הרץ את הפקודה מהודעה m1' with command {run}; agent_command()
        demands text starting with '/'. So /הרץ through the dialog is always refused."""
        ask = self.tower_block()
        page = {'op': 'reply', 'thread': 'topic', 'cid': 'r1', 'text': '▶ הרץ את הפקודה מהודעה m1', 'under': None,
                'run': ask, 'last': 'm1', 'command': {'name': 'run', 'args': ''}}
        got = self.post(page, ok=None, env=self.at(1))
        self.assertTrue(got['ok'], got)

    def test_slash_run_cannot_reach_a_block_of_another_thread(self):
        ask = self.tower_block()
        self.run_cli('new', 'other', 'אחר', env=self.at(0))
        self.run_cli('say', 'other', '--from', 'fork', 'x', env=self.at(0))
        got = self.post({'op': 'reply', 'thread': 'other', 'cid': 'x1', 'text': '/run', 'under': None, 'run': ask, 'last': 'm1',
                         'command': {'name': 'run', 'args': ''}}, ok=False, env=self.at(1))
        self.assertFalse(got['ok'])

    def test_a_command_name_of_the_wrong_type_is_a_plain_refusal(self):
        self.run_cli('new', 'topic', 'כותרת', env=self.at(0))
        for name in ([], {}, None, 1, 'STATUS', 'status\n', '__class__'):
            with self.subTest(name=name):
                got = self.post({'op': 'reply', 'thread': 'topic', 'cid': 'n-' + repr(name), 'text': '/x', 'under': None,
                                 'command': {'name': name, 'args': ''}}, ok=False, env=self.at(1))
                self.assertFalse(got['ok'])
                self.assertNotIn('again', got)          # not "try again": the page must not resend it forever
        self.assertEqual(self.thread(env=self.at(1))['messages'], [])

    def test_a_retried_command_is_stored_once(self):
        self.run_cli('new', 'topic', 'כותרת', env=self.at(0))
        body = {'op': 'reply', 'thread': 'topic', 'cid': 'same', 'text': '/מצב', 'under': None, 'command': {'name': 'status', 'args': ''}}
        self.assertTrue(self.post(body, env=self.at(1))['ok'])
        self.assertTrue(self.post(body, env=self.at(2))['dup'])
        self.assertEqual(len(self.thread(env=self.at(2))['messages']), 1)

    def test_task_ops_refused_on_a_merged_thread_and_not_by_an_agent_name(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('new', 'into', 'יעד', env=e(0))
        self.assertTrue(self.post({'op': 'merge', 'thread': 'topic', 'into': 'into'}, env=e(1))['ok'])
        self.assertFalse(self.post({'op': 'task-add', 'thread': 'topic', 'text': 'x'}, ok=False, env=e(2))['ok'])
        # author fields in the request are ignored: the task is his, whatever the page claims
        self.assertTrue(self.post({'op': 'task-add', 'thread': 'into', 'text': 'y', 'by': 'tower', 'owner': 'fork', 'from': 'm1'}, env=e(3))['ok'])
        task = self.thread('into', env=e(3))['tasks'][-1]
        self.assertEqual((task['by'], task['owner'], task['from']), ('owner', '', None))

    def test_task_add_sent_twice_after_a_lost_answer_adds_one_task(self):
        """LOW. slashPost() has no cid and the server keeps none for task-add: an answer lost on the way (the page says
        'not done') and his second /task adds the task twice. Safe outcome: a cid makes it idempotent."""
        self.run_cli('new', 'topic', 'כותרת', env=self.at(0))
        body = {'op': 'task-add', 'thread': 'topic', 'text': 'לכתוב תיעוד', 'cid': 'k1'}
        self.post(body, env=self.at(1))
        self.post(body, ok=None, env=self.at(2))
        self.assertEqual(len(self.thread(env=self.at(2))['tasks']), 1)


# run_cli(ok=None) means "either": the harness asserts only on True/False
_orig_run_cli = TT.run_cli


def _run_cli(self, *args, ok=True, input=None, env=None):
    if ok is None:
        import subprocess, sys
        return subprocess.run([sys.executable, str(test_threads.CLI), *args], env=env or self.env, input=input, capture_output=True, text=True)
    return _orig_run_cli(self, *args, ok=ok, input=input, env=env)


ServerAdv.run_cli = _run_cli


class PageAdv(unittest.TestCase):
    page, node, pure_js = test_slack.SlackPageTests.page, test_slack.SlackPageTests.node, test_slack.SlackPageTests.pure_js

    def test_last_run_block_is_not_one_the_tower_spoke_past(self):
        """LOW. lastRunBlock() takes the newest tower message that HAS a block, even when the tower wrote after it
        (e.g. 'do not run that'). The dialog shows the command, but /הרץ reaches further back than the newest word
        of the tower. Safe outcome: only a block of the tower's newest message."""
        self.pure_js(r"""
        const t={messages:[{id:'m1',from:'tower',text:'```\n! rm -rf build\n```'},{id:'m2',from:'tower',text:'אל תריץ את זה, זה שגוי'}]};
        assert.strictEqual(lastRunBlock(t),null);
        """)

    def test_a_path_or_unknown_word_with_words_is_a_message(self):
        self.pure_js(r"""
        for(const s of ['/usr/bin/env python','/Users/someone x','/ hello','/me is here','/tmp/x'])assert.strictEqual(parseSlash(s,{now:0}),null,s);
        """)


class PageE2E(test_e2e.Suda):
    def test_slash_run_through_the_dialog_reaches_the_server(self):
        """HIGH (end to end): /הרץ, Enter, the dialog's run button: the request must land on the server."""
        self.needs('command')
        tid = 'adv-run'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'הרצה בפקודה', '--state', 'working', '--note', 'x', '--by', 'e2e')
            self.ok('say', tid, '--from', 'tower', '```\n! echo hi\n```')
        self.open_thread(SIZES[2], tid, 'הרצה בפקודה')
        self.browser.fill('#input', '/הרץ')
        self.browser.eval('(()=>{const b=document.querySelector("#input");b.focus();return "ok";})()')
        self.browser.press('Escape')        # close the list, the line stays
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the run dialog')
        self.browser.click('#run-ok')
        try:
            self.until(lambda: any(isinstance(m.get('run'), dict) for m in self.thread(tid)['messages']), timeout=10, what='the run request on the server')
        finally:
            print('page outbox:', self.browser.eval('JSON.stringify([...optimistic.values()].flat().map(m=>[m.delivery,m.error||""]))'))

    def test_task_typed_while_the_server_cannot_be_reached_is_not_lost(self):
        """MEDIUM. slashSubmit() clears the box as soon as slashAct() starts the post; slashPost() only toasts on a
        failure. A /משימה typed offline is gone. Safe outcome: the line is back in the box (or queued)."""
        self.needs('task-add')
        tid = 'adv-offline'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'בלי רשת', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, 'בלי רשת')
        self.browser.eval('(()=>{const f=window.fetch;window.fetch=(u,o)=>o&&o.method==="POST"?Promise.reject(new TypeError("offline")):f(u,o);return "ok";})()')
        line = '/משימה לכתוב את הוראות ההגירה המלאות'
        self.browser.fill('#input', line)
        self.browser.press('Enter')
        time.sleep(1.5)
        box = self.browser.eval('JSON.stringify(document.querySelector("#input").value)')
        self.assertEqual(self.thread(tid)['tasks'], [])
        self.assertEqual(box, line)


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in PageE2E.__dict__:
        setattr(PageE2E, _name, None)


del TT          # (a module name that is a TestCase would run the whole ThreadsTests here again)

if __name__ == '__main__':
    unittest.main()
