#!/usr/bin/env python3
"""End to end: where the conversation stands in Suda while it changes (the owner, thread suda m227).

"When I'm at the bottom of the conversation and send a message, sometimes it doesn't continue down, and
sometimes there are annoying jumps." The same harness as test_e2e.py: headless Chrome, the real board server on
loopback, the CLI behind its hook, a temporary board. What is checked:

  - his own send ends at the end of the log, also once the server's copy has replaced the page's own;
  - at the end of the log he stays there while an agent's message arrives and while something in the log
    grows by itself (a picture, an agent's page);
  - further up he is not moved, and the pill says there is news; also when he moved there this very moment
    and the browser has not told the page of the scroll yet;
  - a row whose message did not change is the very same element afterwards: nothing above him is rebuilt;
  - a thread he left while standing further up opens there again (his place is kept), with the pill to the end.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e import SIZES, png


class Scroll(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-scroll'
    TITLE = 'נושא ארוך לבדיקת גלילה'
    GAP = ('JSON.stringify(Math.round(document.querySelector("#scroll").scrollHeight-document.querySelector("#scroll").clientHeight'
           '-document.querySelector("#scroll").scrollTop))')

    AT_END = ('JSON.stringify(document.querySelector("#scroll").scrollHeight-document.querySelector("#scroll").clientHeight'
              '-document.querySelector("#scroll").scrollTop<=2)')

    def gap(self):
        return int(self.browser.eval(self.GAP))

    def settled(self, what):
        """Nothing of his is on its way any more: the page shows the server's own copies."""
        self.browser.wait('JSON.stringify(![...document.querySelectorAll("#log .msg")].some(r=>/שולח|נשלח בעוד רגע/.test(r.innerText)))', what=what)

    def long_thread(self):
        if self.TID in self.state()['threads']:
            return
        self.ok('new', self.TID, self.TITLE, '--summary', 'הרבה הודעות, תמונה ודף של סוכן', '--state', 'working', '--note', 'בודקים גלילה', '--by', 'e2e')
        root = self.board.parent.parent
        shot, page = root / 'scroll-shot.png', root / 'scroll-page.html'
        shot.write_bytes(png(640, 420))
        page.write_text('<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>טבלה קטנה</title>'
                        '<body style="font:15px system-ui;margin:12px"><p>שורה</p><p>שורה</p><p>שורה</p><p>שורה</p></body></html>', encoding='utf-8')
        for i in range(14):
            self.ok('say', self.TID, '--from', 'fork', 'הודעה מספר %d בשיחה, עם מספיק טקסט כדי שהשיחה תהיה ארוכה מהמסך.\n\n- פרט ראשון\n- פרט שני' % i,
                    '--state', 'working', '--note', 'בודקים גלילה')
        self.ok('say', self.TID, '--from', 'fork', 'תמונה ודף, כדי שמשהו בשיחה ישנה גובה אחרי שהיא מוצגת.', '--image', str(shot), '--caption', 'צילום לבדיקה',
                '--html', str(page), '--state', 'working', '--note', 'בודקים גלילה')

    def test_the_log_ends_where_he_sent_and_stays_where_he_reads(self):
        self.long_thread()
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open_thread(size, self.TID, self.TITLE)
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=15)', what='the long conversation')
                if size is SIZES[0]:
                    self.browser.wait(self.AT_END, what='the log at its end after it opened')
                elif 'place' in self.ops:
                    # The last time he left this thread he stood further up (the end of the round before): that is
                    # where it opens now, since his place is kept (thread suda m240), and the pill takes him to the end.
                    self.browser.wait('JSON.stringify(!document.querySelector("#jump").hidden&&placeNow().bottom===false)', what='the thread opened where he stood, with the pill')
                    self.browser.click('#jump')
                    self.browser.wait(self.AT_END, what='the end after the pill')
                else:
                    self.browser.wait(self.AT_END, what='the log at its end after it opened')
                # the first row is marked: if it is ever rebuilt, the mark is gone
                self.browser.eval('(()=>{document.querySelector("#log .msg").__kept=1;return "ok";})()')

                # 1. his own send ends at the end, through every stage of the message
                text = 'הודעה שלי מהתחתית, מסך ' + size[0]
                self.browser.fill('#input', text)
                self.browser.click('#send')
                self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes(%s))' % json.dumps(text), what='his message in the log')
                self.assertLessEqual(self.gap(), 2, 'right after his send')
                self.until(lambda: next((r for r in self.pending() if r['text'] == text), None), what='the reply on the server')
                self.settled('the server\'s copy of his message')
                self.assertLessEqual(self.gap(), 2, 'after the server\'s copy replaced the page\'s own')
                self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#log .msg").__kept||0)'), 1, 'the first row was rebuilt by his send')

                # 2. at the end: an agent's message arrives, and something in the log grows by itself
                news = 'תשובה של הסוכן שמגיעה כשהוא בתחתית, מסך ' + size[0]
                self.ok('say', self.TID, '--from', 'fork', news, '--state', 'working', '--note', 'בודקים גלילה')
                self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes(%s))' % json.dumps(news), what='the agent\'s message')
                self.assertLessEqual(self.gap(), 2, 'after an agent\'s message while he was at the end')
                self.browser.eval('(()=>{const f=document.querySelector("#log .canvas iframe");f.style.height=(f.getBoundingClientRect().height+180)+"px";return "ok";})()')
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .canvas iframe"))')
                self.browser.wait(self.AT_END, what='the end again after something in the log grew by itself')

                # the same when the growing comes between the page's own move to the end and the browser's word of
                # that scroll (it tells of a scroll with the next frame): the page goes on following the end
                self.browser.eval('(()=>{toBottom();const f=document.querySelector("#log .canvas iframe");f.style.height=(f.getBoundingClientRect().height+160)+"px";'
                                  'scroller.dispatchEvent(new Event("scroll"));return "ok";})()')
                self.browser.wait(self.AT_END, what='the end again after something grew right after the page\'s own move to the end')

                # 3. further up: he is not moved, and the pill says there is news
                self.browser.eval('(()=>{const s=document.querySelector("#scroll");s.scrollTop=Math.round(s.scrollHeight*0.3);return "ok";})()')
                self.browser.wait('JSON.stringify(document.querySelector("#scroll").scrollHeight-document.querySelector("#scroll").clientHeight-document.querySelector("#scroll").scrollTop>200)',
                                  what='the log scrolled up')
                seen = self.browser.eval('(()=>{const s=document.querySelector("#scroll"),rows=[...document.querySelectorAll("#log .msg")],r=rows.find(x=>x.getBoundingClientRect().top>s.getBoundingClientRect().top+20);'
                                         'r.__watched=1;return JSON.stringify({top:Math.round(r.getBoundingClientRect().top)});})()')
                later = 'הודעה שמגיעה בזמן שהוא קורא למעלה, מסך ' + size[0]
                self.ok('say', self.TID, '--from', 'fork', later, '--state', 'working', '--note', 'בודקים גלילה')
                self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes(%s))' % json.dumps(later), what='the message that arrived while he read')
                now = self.browser.eval('(()=>{const r=[...document.querySelectorAll("#log .msg")].find(x=>x.__watched);'
                                        'return JSON.stringify({kept:!!r,top:r?Math.round(r.getBoundingClientRect().top):null,pill:!document.querySelector("#jump").hidden});})()')
                self.assertTrue(now['kept'], 'the row he was reading was rebuilt')
                self.assertLessEqual(abs(now['top'] - seen['top']), 2, 'the row he was reading moved')
                self.assertTrue(now['pill'], 'no pill for the news below')

                # 4. he moved the log this very moment and the browser has not told the page yet (it tells of a
                #    scroll with the next frame): what lands in that moment does not pull him to the end, neither
                #    because the page still thinks he is at the end, nor because it still follows a send of his
                for was in ('pinned=true', 'pinned=true;followUntil=Date.now()+5000'):
                    got = self.browser.eval('(()=>{toBottom();%s;const want=Math.round(scroller.scrollHeight*0.3);scroller.scrollTop=want;'
                                            'thread(view.ch).messages.push({id:"m9"+Date.now(),from:"fork",text:"הודעה שנוחתת באותו רגע",ts:now()});render();'
                                            'return JSON.stringify({want,top:Math.round(scroller.scrollTop)});})()' % was)
                    self.assertLessEqual(abs(got['top'] - got['want']), 2, 'a scroll the page had not heard of yet was undone (%s): %r' % (was, got))
                self.browser.eval('(async()=>{await refresh();return "ok";})()')       # the board's own messages again


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Scroll.__dict__:
        setattr(Scroll, _name, None)


if __name__ == '__main__':
    unittest.main()
