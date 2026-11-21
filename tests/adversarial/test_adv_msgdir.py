#!/usr/bin/env python3
"""The hostile review of c78fcfb (suda-fixes 71, m363): a Hebrew line of steps joined by U+2190 reads right to left,
and rtlArrows() puts U+200F on both sides of each arrow of a right to left block. Each test here is a hole the review
found; it asserts the safe outcome and fails on c78fcfb.

- node: the rule of the arrow is a rule of one line, not of a whole quote whose arrow and Hebrew are on different
  lines (suda m414: an English mail quoted in a Hebrew message keeps its order).
- node: the marks go only where the block is drawn right to left; a list item with no words of its own stands in the
  list's direction (or its parent item's), not in the place's.
- e2e: in such a list item the numbers keep their order around the arrow.
- e2e: find in the thread still finds 'Settings ← Pages' as he reads it.
- e2e: what he copies by hand from the question strip (outside #log) carries no mark either.

Unit: `uv run --no-project python test_adv_msgdir.py Pure`; e2e: the same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import test_e2e
from test_e2e import SIZES

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'
COVER, INNER, DESK = SIZES
RLM = '‏'


class Pure(unittest.TestCase):
    """The page's pure section under node, as test_slack.py runs it."""

    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_quoted_english_mail_with_an_arrow_on_one_line_and_a_hebrew_name_on_another_stays_english(self):
        """blockDir(body, true) reads a whole quote: its arrow and its Hebrew letter need not be on one line. An
        English mail whose steps use the arrow and whose signature is Hebrew turned right to left (it was ltr before
        c78fcfb), against suda m414."""
        self.pure_js(r"""
        const mail='Hi team, the release went out today.\nSteps were Login ← Home ← Save.\nThanks,\nדנה לוי';
        assert.strictEqual(blockDir(mail,true),'ltr');
        const html=markdown(mail.split('\n').map(l=>'> '+l).join('\n'));
        assert.ok(/^<blockquote(?: dir="ltr")?>/.test(html),html);      // (on a page left to right, a quote in its way needs no dir)
        // the rule itself still holds on one line of a quote
        assert.strictEqual(blockDir('github.com/x ← Settings ← Pages ← שומרים',true),'rtl');
        """)

    def test_the_marks_go_only_into_an_item_drawn_right_to_left(self):
        """An item with no words of its own ('3.1 ← 3.2', '1 ← 2': blockDir gives '') is drawn in its list's way, or
        under its parent item's side, but rtlArrows() was given the place's way (rtl): an item drawn left to right
        got the marks, and in it the bidi algorithm puts the arrow after both numbers ('3.1 3.2 ←')."""
        self.pure_js(r"""
        const R='‏';
        // an English list in a Hebrew message: the list is ltr, so is its item of numbers
        let html=markdown('- First English item\n- Second English item\n- 3.1 ← 3.2');
        assert.ok(/^<ul(?: dir="ltr")?>/.test(html),html);
        assert.ok(!html.includes(R),html);
        // a nested item under an English item stands left to right too
        html=markdown('- פריט ראשון בעברית\n- English parent item here\n  - 1 ← 2');
        assert.ok(/<li class="l2"(?: dir="ltr")?>1 ← 2<\/li>/.test(html),html);
        // and where the item is drawn right to left it keeps them
        html=markdown('- פריט ראשון\n- 1 ← 2');
        assert.ok(html.includes('1 '+R+'←'+R+' 2'),html);
        """)


VERSIONS = 'הנה הגרסאות:\n\n- First English item\n- Second English item\n- 3.1 ← 3.2\n'
STEPS = ('להפעיל: github.com/udiNur/Suda ← Settings ← Pages ← Save.\n\n'
         'רשומות DNS (dash.cloudflare.com ← getsuda.dev ← DNS).\n')
QUESTION = 'לפתוח github.com/udiNur/Suda ← Settings ← Pages ← Save?'

# [top, left] of the first `word` in the first block (p, li) of the log that holds `key`
AT = r"""(key,word)=>{
  const b=[...document.querySelectorAll('#log .msg .body.md p, #log .msg .body.md li')].find(b=>b.textContent.includes(key));
  if(!b)return null;
  const w=document.createTreeWalker(b,NodeFilter.SHOW_TEXT);let n,text='',nodes=[];
  while((n=w.nextNode())){nodes.push([n,text.length]);text+=n.nodeValue;}
  const at=text.indexOf(word);if(at<0)return null;
  for(const [node,start] of nodes){if(at>=start&&at<start+node.nodeValue.length){const r=document.createRange();r.setStart(node,at-start);r.setEnd(node,at-start+1);const q=r.getBoundingClientRect();return [q.top,q.left];}}
  return null;}"""


class AdvMessageDirection(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ok('new', 'adv-dir', 'כיוון הודעה בבדיקה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('say', 'adv-dir', '--from', 'fork', '-', input=STEPS)
        cls.ok('say', 'adv-dir', '--from', 'fork', '-', input=VERSIONS)
        cls.ok('ask', 'adv-dir', QUESTION, '--options', 'כן,לא')

    def ready(self, size=DESK):
        self.open_thread(size, 'adv-dir', 'כיוון הודעה בבדיקה')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#log .msg .body.md li")].some(li=>li.textContent.includes("3.2")))',
                          what='the messages')

    def x(self, key, word):
        return self.browser.eval('(()=>{const at=%s;return JSON.stringify(at(%s,%s))})()' % (AT, json.dumps(key), json.dumps(word)))

    def test_numbers_joined_by_an_arrow_in_an_english_list_keep_their_order(self):
        self.ready()
        way = self.browser.eval('JSON.stringify(getComputedStyle([...document.querySelectorAll("#log .msg .body.md li")].find(li=>li.textContent.includes("3.2"))).direction)')
        self.assertEqual(way, 'ltr', 'the item stands in its English list')
        first, arrow, last = (self.x('3.2', w) for w in ('3.1', '←', '3.2'))
        self.assertTrue(first and arrow and last, (first, arrow, last))
        self.assertTrue(abs(first[0] - last[0]) <= 4, 'one line: %s %s' % (first, last))
        self.assertLess(first[1], arrow[1], 'left to right: 3.1, then the arrow (%s %s %s)' % (first, arrow, last))
        self.assertLess(arrow[1], last[1], 'left to right: the arrow, then 3.2 (%s %s %s)' % (first, arrow, last))

    def test_find_in_the_thread_finds_steps_joined_by_arrows(self):
        """He searches what he reads: 'Settings ← Pages'. The text of the page has U+200F on both sides of the arrow."""
        self.ready()
        for q in ('Settings ← Pages', 'getsuda.dev ← DNS', 'Pages ←'):
            with self.subTest(q=q):
                got = self.browser.eval('(()=>{openFind();const i=document.querySelector("#find-q");i.value=%s;'
                                        'i.dispatchEvent(new Event("input",{bubbles:true}));'
                                        'return JSON.stringify(document.querySelectorAll("#log mark.hl:not(.part)").length)})()' % json.dumps(q))
                self.assertGreaterEqual(got, 1, 'find in the thread finds %r' % q)
        self.browser.eval('(()=>{closeFind();return 1})()')

    def test_what_he_copies_by_hand_from_the_question_strip_has_no_marks(self):
        """The copy listener that cleans a hand copy is on #log only; the question strip (#pin) is drawn with the same
        markdown(), so its arrows carry U+200F, and Cmd+C there gives them to the clipboard. What the copy gives: the
        page's own text when a listener takes the event, else the browser's (the selection as it is)."""
        self.ready()
        self.browser.wait('JSON.stringify(!!document.querySelector("#pin .pin-text")&&document.querySelector("#pin .pin-text").textContent.includes("Settings"))',
                          what='the question strip')
        got = self.browser.eval('(()=>{const b=document.querySelector("#pin .pin-text");'
                                'const r=document.createRange();r.selectNodeContents(b);const s=getSelection();s.removeAllRanges();s.addRange(r);'
                                'const e=new ClipboardEvent("copy",{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});'
                                'b.dispatchEvent(e);const out=e.defaultPrevented?e.clipboardData.getData("text/plain"):String(getSelection());'
                                's.removeAllRanges();return JSON.stringify(out)})()')
        self.assertNotIn(RLM, got, 'a hand copy from the question strip carries no mark of direction')
        self.assertIn('Settings ← Pages', got)


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    suite = unittest.TestSuite(Pure(name) for name in sorted(vars(Pure)) if name.startswith('test_'))
    suite.addTests(AdvMessageDirection(name) for name in sorted(vars(AdvMessageDirection)) if name.startswith('test_'))
    return suite


if __name__ == '__main__':
    unittest.main()
