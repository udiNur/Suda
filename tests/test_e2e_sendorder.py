#!/usr/bin/env python3
"""End to end: what he sent arrives in the order he sent it (suda-fixes 54, the owner's guarantee).

Two ways a later message went first:
  (a) an answer he tapped is held four seconds, so he can take it back; a reply he wrote inside those seconds left
      at once, before the answer;
  (b) a message that failed (the server refused it, did not answer it, or the page gave up on it) held nothing, so
      every later one of the thread went past it in silence.
Now (a) the later one waits behind the held answer and says so; it goes right after it, or alone if he takes the
answer back. And (b) the later ones wait behind the failed one and say why; the failed one keeps its "נסה שוב" and
"מחק": once it lands or he deletes it, the queue moves. Deterministic: the server of test_adv_send_page refuses a
message by its words, and the hold is the page's own.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_adv_send_page
from test_adv_send_page import ROW


class SendOrder(test_adv_send_page.AdvSend):
    """Only the scenarios of this file: the ones of the harness run in their own files."""

    def ask(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', tid, 'לאשר את המיזוג?', '--options', 'כן למזג,לא עכשיו')
        self.show(tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&quickAnswers().length===2)', what='the two answers')

    def tap_answer(self):
        """One press on the first answer: it is held four seconds (heldAnswer), and can be taken back."""
        return self.browser.eval('(()=>{quickAnswers()[0].click();const m=heldAnswer();return m?m.text:"";})()')

    def test_a_reply_written_inside_an_answers_undo_goes_after_it(self):
        tid = 'order-held'
        self.ask(tid, 'תשובה ואחריה הודעה')
        answer = self.tap_answer()
        self.assertTrue(answer)
        text = 'כתבתי אחרי שבחרתי'
        self.write(text)
        self.row_says(text, 'ממתין לתשובה שבחרת', timeout=3)
        self.never(lambda: self.his(tid) if answer not in self.his(tid) and self.his(tid) else None, 3, 'the reply is on the server before the answer')
        self.arrived(tid, text)
        self.assertEqual(self.his(tid), [answer, text])

    def test_an_answer_taken_back_lets_the_reply_behind_it_go_alone(self):
        tid = 'order-undo'
        self.ask(tid, 'תשובה שבוטלה')
        answer = self.tap_answer()
        text = 'כתבתי ואז ביטלתי את הבחירה'
        self.write(text)
        self.row_says(text, 'ממתין לתשובה שבחרת', timeout=3)
        self.browser.eval('(()=>{heldAnswer().undo();return "ok";})()')
        self.arrived(tid, text)
        time.sleep(5)
        self.assertEqual(self.his(tid), [text], 'the answer he took back was sent')
        self.assertNotIn(answer, self.his(tid))

    def test_a_failed_reply_holds_the_ones_after_it_until_he_deletes_it(self):
        tid = 'order-failed-delete'
        self.topic(tid, 'הודעה שנכשלה ומחיקה')
        first, second = 'זו נדחית על ידי השרת', 'זו נכתבה אחריה'
        self.rule('refuse', text=first, reason='השרת לא קיבל את זה')
        self.write(first)
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(first) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()', what='the first one failed')
        self.write(second)
        self.row_says(second, 'ההודעה שלפניה לא נשלחה')
        self.never(lambda: self.his(tid), 8, 'a later message went past one that failed')
        self.press(first, 'מחק')
        self.arrived(tid, second)
        self.assertEqual(self.his(tid), [second])

    def test_a_failed_reply_sent_again_lands_first_and_the_queue_moves(self):
        tid = 'order-failed-again'
        self.topic(tid, 'הודעה שנכשלה ונשלחה שוב')
        first, second = 'נדחית פעם אחת', 'נכתבה אחריה ומחכה'
        self.rule('refuse', text=first, reason='לא עכשיו', left=1)
        self.write(first)
        self.browser.wait('(()=>{const row=' + ROW % json.dumps(first) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()', what='the first one failed')
        self.write(second)
        self.row_says(second, 'ההודעה שלפניה לא נשלחה')
        self.never(lambda: self.his(tid), 5, 'a later message went past one that failed')
        self.press(first, 'נסה שוב')
        self.arrived(tid, first)
        self.arrived(tid, second)
        self.assertEqual(self.his(tid), [first, second])


for _name in dir(test_adv_send_page.AdvSend):
    if _name.startswith('test') and _name not in SendOrder.__dict__:
        setattr(SendOrder, _name, None)


if __name__ == '__main__':
    unittest.main()
