#!/usr/bin/env python3
"""End to end: outside the thread, a message of his that failed is said (suda-fixes 55).

Since suda-fixes 54 a message that failed holds the later ones of its thread until he sends it again or deletes
it. Inside the thread each one says so; outside it nothing did, so a reply written there could wait unseen while he
read another thread. Now the thread's row in the list (the same row on the phone's list) carries a red "לא נשלח"
with the words in its title and in what a screen reader hears, and the tab's title starts with ⚠️. Both go as soon
as nothing of his there is failed. The harness of test_adv_send_page (a server that refuses a message by its words).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_adv_send_page
from test_e2e import SIZES

MARK = ('(()=>{const row=document.querySelector("#channels .ch[data-id=%s]");const m=row&&row.querySelector(".stuck-mark");'
        'return JSON.stringify({row:!!row,mark:m?m.textContent:"",title:m?m.title:"",label:row?row.getAttribute("aria-label")||"":"",'
        'shown:!!(row&&row.offsetParent),tab:document.title});})()')


class StuckMark(test_adv_send_page.AdvSend):
    """Only the scenarios of this file: the ones of the harness run in their own files."""

    def fail_two(self, tid, title, size):
        """In thread `tid`: a reply the server refuses, and one written after it, which waits behind it."""
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', tid + '-b', title + ', אחר', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.show(tid, title, size)
        first, second = 'נדחית: ' + tid, 'מחכה אחריה: ' + tid
        self.rule('refuse', text=first, reason='לא עכשיו')
        self.write(first)
        self.browser.wait('(()=>{const row=' + test_adv_send_page.ROW % json.dumps(first) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()',
                          what='the first one failed')
        self.write(second)
        self.row_says(second, 'ההודעה שלפניה לא נשלחה')
        return first, second

    def mark(self, tid):
        return self.browser.eval(MARK % tid)

    def test_the_list_and_the_tab_say_that_a_message_of_his_did_not_go(self):
        tid = 'stuck-wide'
        first, second = self.fail_two(tid, 'נושא עם הודעה שנכשלה', SIZES[2])
        # he reads another thread: the row of this one says it, and the tab too
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid + '-b'))
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.mark?JSON.stringify(s):"";})()' % (MARK % tid), timeout=10, what='the mark on the row')
        self.assertEqual(got['mark'], 'לא נשלח')
        self.assertIn('הודעה שלך לא נשלחה, והודעה אחת מחכה אחריה', got['title'])
        self.assertIn('הודעה שלך לא נשלחה, והודעה אחת מחכה אחריה', got['label'], 'a screen reader hears it')
        self.assertTrue(got['tab'].startswith('⚠️'), got['tab'])
        # the other thread has none
        self.assertEqual(self.mark(tid + '-b')['mark'], '')
        # he deletes the failed one: the reply behind it goes, the mark and the warning go
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.press(first, 'מחק')
        self.arrived(tid, second)
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return !s.mark&&!s.tab.startsWith("⚠️")?JSON.stringify(s):"";})()' % (MARK % tid),
                                timeout=10, what='the mark gone')
        self.assertEqual(got['mark'], '')

    def test_the_phones_list_says_it_too(self):
        tid = 'stuck-phone'
        first, second = self.fail_two(tid, 'בטלפון, הודעה שנכשלה', SIZES[0])
        self.browser.eval('(()=>{history.back();return "ok";})()')       # back to the list, as his finger does
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.shown&&s.mark?JSON.stringify(s):"";})()' % (MARK % tid), timeout=15,
                                what='the mark on the row of the phone\'s list')
        self.assertEqual(got['mark'], 'לא נשלח')
        self.assertTrue(got['tab'].startswith('⚠️'), got['tab'])
        # the mark fits the row: it does not push the time out of it
        fits = self.browser.eval('(()=>{const row=document.querySelector("#channels .ch[data-id=%s]"),r=row.getBoundingClientRect(),m=row.querySelector(".stuck-mark").getBoundingClientRect(),'
                                 't=row.querySelector(".ch-time").getBoundingClientRect();return JSON.stringify(m.left>=r.left-1&&m.right<=r.right+1&&t.left>=r.left-1&&t.right<=r.right+1);})()' % tid)
        self.assertTrue(fits, 'the mark or the time falls out of the row on the phone')


for _name in dir(test_adv_send_page.AdvSend):
    if _name.startswith('test') and _name not in StuckMark.__dict__:
        setattr(StuckMark, _name, None)


if __name__ == '__main__':
    unittest.main()
