#!/usr/bin/env python3
"""End to end: what a change costs the page while he is in a conversation on his phone (the owner, suda m353).

"And without these lags." On the phone the list of topics is off the screen while a conversation is open, and
still every change anywhere (an agent writes in another topic, his own reply lands) drew the whole list again:
more than half of what a drawing costs, measured with the page slowed like a phone, for something he cannot see.

What is checked: with a conversation open on the phone the list is not drawn again; the moment the list is back
on the screen (he goes back, or the phone is unfolded to the wide screen) it shows what happened meanwhile; on a
wide screen, where the list is always there, it goes on following every change.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

MARK = '(()=>{const row=document.querySelector("#channels [data-id]");if(!row)return JSON.stringify(false);row.dataset.kept="1";return JSON.stringify(true);})()'
KEPT = 'JSON.stringify(!!document.querySelector("#channels [data-kept]"))'


class Lag(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def board_with_two(self, a, b):
        self.ok('new', a, 'שיחה פתוחה ' + a, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', b, 'נושא אחר ' + b, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', a, '--from', 'fork', 'שלום', '--state', 'working', '--note', 'בודקים')

    def other_writes(self, b, text):
        self.ok('say', b, '--from', 'fork', text, '--state', 'on-owner', '--note', 'מחכה לך', '--by', 'e2e')
        self.browser.wait('JSON.stringify(!!thread(%s)&&thread(%s).messages.some(m=>m.text===%s||m.light)&&thread(%s).state==="on-owner"&&thread(%s).messages.length>0&&thread(%s).note==="מחכה לך")'
                          % ((json.dumps(b),) * 2 + (json.dumps(text),) + (json.dumps(b),) * 3), timeout=20, what='the change on the page')

    def row_of(self, b):
        return self.browser.eval('(()=>{const row=document.querySelector(\'#channels [data-id="%s"]\');return JSON.stringify(row?{unread:row.classList.contains("unread"),text:row.innerText}:null);})()' % b)

    def test_on_the_phone_a_change_does_not_draw_the_list_he_cannot_see_and_the_list_is_whole_when_he_is_back(self):
        a, b = 'e2e-lag-a', 'e2e-lag-b'
        self.board_with_two(a, b)
        self.browser.open('about:blank')
        self.open(SIZES[0])                                      # the phone opens on the list
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!view.ch&&document.querySelectorAll("#channels [data-id]").length>=2)', what='the list on the screen')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(a))
        self.browser.wait('JSON.stringify(view.ch===%s&&!!document.querySelector("#input").offsetParent)' % json.dumps(a), what='the conversation on the screen')
        time.sleep(0.5)
        self.assertTrue(self.browser.eval(MARK))
        self.other_writes(b, 'עדכון ראשון בנושא האחר')
        time.sleep(0.5)
        self.assertTrue(self.browser.eval(KEPT), 'the list was drawn again while it is off the screen')
        # his own reply in the open conversation: the list is still not drawn
        self.browser.fill('#input', 'תשובה שלי')
        self.browser.click('#send')
        self.until(lambda: [m for m in self.thread(a)['messages'] if m['from'] == 'owner'], what='his reply on the server')
        self.browser.wait('JSON.stringify(!(optimistic.get(%s)||[]).length)' % json.dumps(a), timeout=20, what='the reply settled on the page')
        self.assertTrue(self.browser.eval(KEPT), 'the list was drawn again while it is off the screen')
        # back to the list: it shows what happened meanwhile
        self.browser.eval('(()=>{backToList();return "ok";})()')
        self.browser.wait('JSON.stringify(!view.ch)', what='the list on the screen')
        row = self.row_of(b)
        self.assertTrue(row and row['unread'], row)
        self.assertIn('מחכה לך', row['text'])
        self.assertFalse(self.browser.eval(KEPT))

    def test_unfolding_the_phone_in_a_conversation_shows_a_list_that_is_up_to_date(self):
        a, b = 'e2e-lag-c', 'e2e-lag-d'
        self.board_with_two(a, b)
        self.browser.open('about:blank')
        self.open_thread(SIZES[0], a, 'שיחה פתוחה ' + a)         # straight into a conversation: the list was never on the screen
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced)', what='the state on the page')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll("#channels [data-id]").length)'), 0)
        self.other_writes(b, 'עדכון בזמן שהטלפון סגור')
        self.browser.viewport(SIZES[1][1], SIZES[1][2])          # the wide screen: the list stands beside the conversation
        self.browser.wait('(()=>{const row=document.querySelector(\'#channels [data-id="%s"]\');return JSON.stringify(!!row&&row.classList.contains("unread")&&row.innerText.includes("מחכה לך")&&!!row.offsetParent);})()' % b,
                          timeout=15, what='the list up to date on the wide screen')

    def test_on_a_wide_screen_the_list_follows_every_change(self):
        a, b = 'e2e-lag-e', 'e2e-lag-f'
        self.board_with_two(a, b)
        self.browser.open('about:blank')
        self.open_thread(SIZES[2], a, 'שיחה פתוחה ' + a)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&document.querySelectorAll("#channels [data-id]").length>=2)', what='the list drawn once')
        self.other_writes(b, 'עדכון במסך רחב')
        self.browser.wait('(()=>{const row=document.querySelector(\'#channels [data-id="%s"]\');return JSON.stringify(!!row&&row.classList.contains("unread")&&row.innerText.includes("מחכה לך"));})()' % b,
                          timeout=15, what='the list following the change')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Lag.__dict__:
        setattr(Lag, _name, None)


if __name__ == '__main__':
    unittest.main()
