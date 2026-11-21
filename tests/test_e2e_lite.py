#!/usr/bin/env python3
"""End to end: Suda opens from a small summary, and from what the device kept (the owner, thread suda m313/m317).

"Every opening of Suda's screen sometimes takes a few seconds to update." The state was read whole at every
opening and at every change (1.3 MB, every conversation of every thread). Now the server writes a summary beside
it and each thread's conversation in a file of its own; the page reads the summary, and one conversation only for
the thread that is open; what it read is kept on the device and shown at once the next time. The same harness as
test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). What is checked:

  - the page opens from summary.json and one thread's file, never from state.json, and shows the whole conversation;
  - a message that arrives is shown without the conversation being read again; a change to an old message is
    seen, and the conversation is read again for it;
  - a thread that is not open counts its unread messages rightly, also more of them than the summary carries whole;
  - with the server out of reach the page shows what the device kept, says nothing to the server meanwhile, and
    takes the server's answer in when it comes;
  - a server from before the summary is read as it always was.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

# what the page asked the server for, by name (without the board's folder and the query)
ASKED = ('JSON.stringify(performance.getEntriesByType("resource").map(e=>new URL(e.name).pathname.split("/").slice(2).join("/"))'
         '.filter(n=>/^(summary|state)\\.json$|^full\\/|^api\\/state$/.test(n)))')


class Lite(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-lite'
    TITLE = 'שיחה ארוכה לטעינה מהירה'

    def board_with_a_long_thread(self):
        if self.TID in self.state()['threads']:
            return
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', self.TID, '--from', 'fork', 'הודעה 1, לפני שלו', '--state', 'working', '--note', 'בודקים')
        self.ok('say', self.TID, '--from', 'owner', 'הודעה שלי, השנייה בשיחה')
        for n in range(3, 31):
            self.ok('say', self.TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork', input='הודעה מספר %d\n\nשורה נוספת\n' % n)
        self.ok('new', 'e2e-lite-other', 'נושא שלא פתוח', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', 'e2e-lite-other', '--from', 'fork', 'הודעה ראשונה', '--state', 'working', '--note', 'בודקים')

    def asked(self):
        return self.browser.eval(ASKED)

    def open_thread(self, size, tid, title):
        """These scenarios count what the page asks the server for: it reads nothing ahead of his asking (that is test_e2e_nav's)."""
        super().open_thread(size, tid, title)
        self.browser.eval('(()=>{ahead=false;return "ok";})()')

    def whole_thread(self, n):
        self.browser.wait('JSON.stringify(!!thread(%s)&&!thread(%s).partial&&document.querySelectorAll("#log .msg").length>=%d)' % (json.dumps(self.TID), json.dumps(self.TID), n),
                          timeout=20, what='the whole conversation on the page (%d messages)' % n)

    def test_the_page_opens_from_the_summary_and_reads_one_conversation(self):
        self.board_with_a_long_thread()
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        n = len(summary['threads'][self.TID]['stamps'])          # 30, and one more for every scenario of this file that ran before
        self.assertGreaterEqual(n, 30)
        self.assertEqual(len(summary['threads'][self.TID]['messages']), 4)
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.whole_thread(n)
        asked = self.asked()
        # the summary; or (sse153) what the device kept, with the changes since its number (none, when it is current)
        self.assertTrue('summary.json' in asked or self.browser.eval('JSON.stringify(base.seq)') >= summary['seq'], asked)
        self.assertNotIn('state.json', asked, 'the whole state was read although the server has a summary')
        self.assertLessEqual(asked.count('full/%s.json' % self.TID), 1, asked)          # none when the device kept it from an earlier scenario
        self.assertFalse(any(name.startswith('full/') and name != 'full/%s.json' % self.TID for name in asked), 'a conversation of a thread that is not open was read: %r' % asked)
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#log .older"))'), 'the line that says the rest is loading is still there')
        fulls = self.asked().count('full/%s.json' % self.TID)
        # 1. a message arrives: it is shown from the summary's own tail, and the conversation is not read again
        self.ok('say', self.TID, '--from', 'fork', 'הודעה שמגיעה כשהדף פתוח', '--state', 'working', '--note', 'בודקים')
        self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה שמגיעה כשהדף פתוח"))', what='the new message')
        self.whole_thread(n + 1)
        self.assertEqual(self.asked().count('full/%s.json' % self.TID), fulls, 'the whole conversation was read again for one new message')
        # 2. an old message changes (an agent picks his message up): the page sees it, and reads the conversation again for it
        self.ok('ack', self.TID, 'm2')
        self.browser.wait('JSON.stringify((thread(%s).messages.find(m=>m.id==="m2")||{}).status==="acked")' % json.dumps(self.TID), timeout=20, what='the change to an old message')
        self.assertEqual(self.asked().count('full/%s.json' % self.TID), fulls + 1)
        self.assertFalse(self.browser.eval('JSON.stringify(thread(%s).partial)' % json.dumps(self.TID)))
        # 3. a thread that is not open: while no page is open six messages arrive, more than the summary carries
        #    whole; the page that opens next counts all six, without reading that thread's conversation
        self.browser.open('about:blank')
        was = len(self.thread('e2e-lite-other')['messages'])
        for k in range(6):
            self.ok('say', 'e2e-lite-other', '--from', 'fork', 'חדשה %d' % k, '--state', 'working', '--note', 'בודקים')
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(synced&&!!thread("e2e-lite-other")&&thread("e2e-lite-other").messages.length===%d)' % (was + 6), timeout=20, what='the server\'s state with the six messages')
        other = self.browser.eval('JSON.stringify({unread:unreadOf(thread("e2e-lite-other")),partial:thread("e2e-lite-other").partial,whole:thread("e2e-lite-other").messages.filter(m=>!m.light).length,'
                                  'badge:(document.querySelector(\'.ch[data-id="e2e-lite-other"] .badge\')||{}).textContent})')
        # the summary's four, and at most the one the device still held from before: not all of them, yet all six are counted
        self.assertIn(other.pop('whole'), (4, 5))
        self.assertEqual(other, {'unread': 6, 'partial': True, 'badge': '6'})
        self.assertNotIn('full/e2e-lite-other.json', self.asked())
        # he opens it: now its conversation is read, and it is whole
        self.browser.eval('(()=>{openChannel("e2e-lite-other");return "ok";})()')
        self.browser.wait('JSON.stringify(!thread("e2e-lite-other").partial&&document.querySelectorAll("#log .msg").length===%d)' % (was + 6), timeout=20, what='the other thread\'s whole conversation')
        self.assertIn('full/e2e-lite-other.json', self.asked())
        self.assertNotIn('state.json', self.asked())

    def test_what_the_device_kept_is_shown_while_the_server_is_out_of_reach(self):
        self.board_with_a_long_thread()
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(!!thread(%s)&&!thread(%s).partial)' % (json.dumps(self.TID), json.dumps(self.TID)), timeout=20, what='the whole conversation')
        rows = self.browser.eval('JSON.stringify(document.querySelectorAll("#log .msg").length)')
        self.assertGreaterEqual(rows, 30)
        # the device keeps the summary at once and the open conversation a moment later
        self.browser.wait('(async()=>{const s=await keptStore.get("summary"),f=await keptStore.get("full:%s"),rev=thread(%s).rev;'
                          'return JSON.stringify(!!s&&!!f&&s.threads[%s].rev===rev&&f.rev===rev&&f.messages.length===%d);})()' % (self.TID, json.dumps(self.TID), json.dumps(self.TID), rows),
                          timeout=20, what='the device\'s copy of the state and of the conversation, as they stand now')
        # the server goes out of reach for everything the page reads and says
        for pattern in ('**/summary.json*', '**/state.json*', '**/changes*', '**/full/*', '**/api/state*', '**/events*'):
            self.browser.run('network', 'route', pattern, '--abort')
        self.addCleanup(self.browser.run, 'network', 'unroute', check=False)
        try:
            self.open(SIZES[2], self.TID)
            self.browser.wait('JSON.stringify(typeof loaded!=="undefined"&&loaded&&document.querySelectorAll("#log .msg").length>=%d)' % rows, timeout=20, what='the kept conversation on the page')
            shown = self.browser.eval('JSON.stringify({synced,partial:thread(%s).partial,title:document.querySelector("#h-title").textContent,list:document.querySelectorAll("#channels .ch").length,'
                                      'empty:!document.querySelector("#empty").hidden})' % json.dumps(self.TID))
            self.assertEqual((shown['synced'], shown['partial'], shown['title'], shown['empty']), (False, False, self.TITLE, False), shown)
            self.assertGreaterEqual(shown['list'], 2)
            # he can read and write; the page itself says nothing to the server before it has answered
            time.sleep(3)
            self.assertEqual([name for name in self.asked() if name == 'api/state'], [], 'the page spoke to the server on its own account before the server answered')
            self.assertFalse(self.browser.eval('JSON.stringify(synced)'))
            self.browser.eval('(()=>{for(const row of document.querySelectorAll("#log .msg"))row.__kept=1;window.__page=1;return "ok";})()')
        finally:
            self.browser.run('network', 'unroute', check=False)
        # the server is back, with something new: the page takes it in on top of what it showed
        self.ok('say', self.TID, '--from', 'fork', 'הודעה שנכתבה כשהשרת לא היה בהישג יד', '--state', 'working', '--note', 'בודקים')
        self.browser.wait('JSON.stringify(synced&&document.querySelector("#log").innerText.includes("הודעה שנכתבה כשהשרת לא היה בהישג יד"))', timeout=30, what='the server\'s answer on top of the kept copy')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll("#log .msg").length)'), rows + 1)
        self.assertNotIn('state.json', self.asked())
        # nothing he was looking at was drawn again, and the page was not loaded again: only the new message came in
        after = self.browser.eval('JSON.stringify({page:window.__page||0,kept:[...document.querySelectorAll("#log .msg")].filter(row=>row.__kept).length})')
        self.assertEqual(after, {'page': 1, 'kept': rows})

    def test_a_thread_newer_than_the_kept_copy_is_the_one_that_opens(self):
        """What the device kept does not know a thread that was opened since: the address that names it wins."""
        self.board_with_a_long_thread()
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('(async()=>JSON.stringify(synced&&!!(await keptStore.get("summary"))))()', timeout=20, what='the device\'s copy of the state')
        self.browser.open('about:blank')
        self.ok('new', 'e2e-lite-newer', 'נושא שנפתח אחרי שהעותק נשמר', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', 'e2e-lite-newer', '--from', 'fork', 'הודעה בנושא החדש', '--state', 'working', '--note', 'בודקים')
        self.open(SIZES[2], 'e2e-lite-newer')
        self.browser.wait('JSON.stringify(synced&&view.ch==="e2e-lite-newer"&&document.querySelector("#h-title").textContent==="נושא שנפתח אחרי שהעותק נשמר"'
                          '&&document.querySelector("#log").innerText.includes("הודעה בנושא החדש"))', timeout=20, what='the new thread, as the address names it')
        self.assertEqual(self.browser.eval('JSON.stringify(location.hash)'), '#e2e-lite-newer')

    def test_a_server_without_the_summary_is_read_as_it_always_was(self):
        self.board_with_a_long_thread()
        self.open(SIZES[2])                                  # any page of the board, to clear what the device kept
        self.browser.eval('(async()=>{for(const key of await keptStore.keys())await keptStore.drop(key);return "ok";})()')
        (self.board / 'summary.json').unlink()               # as a server from before the summary leaves the board
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=30)', timeout=20, what='the conversation from the whole state')
        asked = self.asked()
        self.assertIn('state.json', asked)
        self.assertFalse(any(name.startswith('full/') for name in asked), asked)
        state = self.browser.eval('JSON.stringify({partial:thread(%s).partial,stamps:Array.isArray(thread(%s).stamps),off:liteOff>Date.now()})' % (json.dumps(self.TID), json.dumps(self.TID)))
        self.assertEqual(state, {'partial': False, 'stamps': False, 'off': True})
        # and it goes on working: a message arrives and is shown
        self.ok('say', self.TID, '--from', 'fork', 'הודעה לדף שקורא את המצב השלם', '--state', 'working', '--note', 'בודקים')
        self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה לדף שקורא את המצב השלם"))', what='the new message on a page that reads the whole state')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Lite.__dict__:
        setattr(Lite, _name, None)


if __name__ == '__main__':
    unittest.main()
