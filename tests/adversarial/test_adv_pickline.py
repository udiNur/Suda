#!/usr/bin/env python3
"""Hostile review of pickedNow (pickline141). Each test asserts the correct behaviour; FAIL = a real hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_e2e
from test_e2e import SIZES

CHIP = 'JSON.stringify(!document.querySelector("#pick-chip").hidden)'
TID = 'e2e-adv-pl'

SEL = '''(()=>{const bodies=[...document.querySelectorAll("#log .msg .body")];
const txt=(w)=>{for(const b of bodies){const t=document.createTreeWalker(b,NodeFilter.SHOW_TEXT);let n;while((n=t.nextNode()))if(n.data.includes(w))return n;}throw new Error("no "+w);};
const bodyOf=(w)=>txt(w).parentElement.closest(".body");
%s
getSelection().removeAllRanges();getSelection().addRange(r);picked=null;paintPick();
return JSON.stringify(picked);})()'''


class AdvPick(test_e2e.Suda):
    def thread_(self):
        if TID not in self.state()['threads']:
            self.ok('new', TID, 'בדיקת בחירה', '--state', 'working', '--note', 'בודק', '--by', 'e2e')
            for text in ('alpha one\n\nbeta two', 'gamma three', 'delta four\n\n```\nline_x = 1\nline_y = 2\n```\n\nepsilon five'):
                self.ok('say', TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודק', '--by', 'e2e', input=text)
        self.open_thread(SIZES[2], TID, 'בדיקת בחירה')

    def pick(self, js):
        import json
        out = self.browser.eval(SEL % js)
        return json.loads(out) if isinstance(out, str) and out != 'null' else out

    def mids(self):
        return [m['id'] for m in self.thread(TID)['messages']]

    def test_1_two_paragraphs_of_one_message_keep_their_line_break(self):
        self.thread_()
        p = self.pick('const r=document.createRange();r.setStart(txt("alpha one"),0);const e=txt("beta two");r.setEnd(e,e.length);')
        self.assertEqual(p and p['text'], 'alpha one\nbeta two')

    def test_2_whole_message_from_the_menu_keeps_lines_and_drops_button_words(self):
        self.thread_()
        p = self.pick('const r=document.createRange();r.selectNodeContents(bodyOf("delta four"));')
        self.assertIsNotNone(p)
        for junk in ('העתק', 'גלישת שורות'):
            self.assertNotIn(junk, p['text'])
        self.assertIn('\n', p['text'])

    def test_3_selection_inside_a_code_block_has_its_lines(self):
        self.thread_()
        p = self.pick('const r=document.createRange();r.setStart(txt("line_x"),0);const e=txt("line_y = 2");r.setEnd(e,e.data.indexOf("2")+1);')
        self.assertEqual(p and p['text'], 'line_x = 1\nline_y = 2')

    def test_4_from_one_body_into_another_code_block_clamps_without_button_words(self):
        self.thread_()
        p = self.pick('const r=document.createRange();r.setStart(txt("gamma three"),0);r.setEnd(txt("line_x"),3);')
        self.assertEqual(p and p['text'], 'gamma three')
        self.assertEqual(p['mid'], self.mids()[1])

    def test_5_across_three_messages_clamps_to_the_first(self):
        self.thread_()
        p = self.pick('const r=document.createRange();r.setStart(txt("beta two"),0);r.setEnd(txt("delta four"),5);')
        self.assertEqual((p['mid'], p['text']), (self.mids()[0], 'beta two'))

    def test_6_start_at_the_very_end_of_a_body_offers_the_next_message(self):
        self.thread_()
        p = self.pick('const r=document.createRange();const b=bodyOf("alpha one");r.setStart(b,b.childNodes.length);const e=txt("gamma three");r.setEnd(e,e.length);')
        self.assertIsNotNone(p, 'nothing of message A is selected, all of B is: B should be offered')
        self.assertEqual((p['mid'], p['text']), (self.mids()[1], 'gamma three'))

    def test_7_from_the_meta_row_into_the_body(self):
        self.thread_()
        p = self.pick('const b=bodyOf("gamma three"),row=b.closest(".msg"),meta=row.querySelector(".meta,.hover-time")||row;const r=document.createRange();r.setStart(meta,0);const e=txt("gamma three");r.setEnd(e,5);')
        self.assertEqual(p and p['text'], 'gamma')

    def test_8_backward_drag_keeps_the_message_it_began_in(self):
        self.thread_()
        out = self.browser.eval('''(()=>{const bodies=[...document.querySelectorAll("#log .msg .body")];
const txt=(w)=>{for(const b of bodies){const t=document.createTreeWalker(b,NodeFilter.SHOW_TEXT);let n;while((n=t.nextNode()))if(n.data.includes(w))return n;}};
const a=txt("gamma three"),b=txt("alpha one");getSelection().setBaseAndExtent(a,a.length,b,0);picked=null;paintPick();return JSON.stringify(picked);})()''')
        import json
        p = json.loads(out) if isinstance(out, str) else out
        self.assertEqual(p and p['mid'], self.mids()[1], 'he began the drag in gamma (message 2), the chip answers message 1')

    def test_9_from_the_sidebar_into_a_body(self):
        self.thread_()
        p = self.pick('const s=document.querySelector("#list,#sidebar,.side,aside")||document.body.firstElementChild;const r=document.createRange();r.setStart(s,0);const e=txt("gamma three");r.setEnd(e,5);')
        # judgement: a drag from outside the log is not an answer to words, but the clamp makes it one; report what happens
        print('\n[sidebar->body] picked:', p)


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvPick.__dict__:
        setattr(AdvPick, _name, None)

if __name__ == '__main__':
    unittest.main()
