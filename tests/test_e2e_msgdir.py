#!/usr/bin/env python3
"""End to end: a Hebrew message whose lines start in English reads right to left (suda-fixes 71; the owner's picture
m363 of the tower's message m360 on the Fold's inner screen: 'github.com/udiNur/Suda ← Settings ← Pages ← ...' was laid
left to right, so its arrows pointed back and the steps read in reverse, and in '(dash.cloudflare.com ← getsuda.dev ←
DNS)' the brackets closed on the wrong sides).

The tower's own text, verbatim. Measured by where the characters stand (Range rects): each step of a chain stands to
the left of the one before it, the brackets around a chain open on its right and close on its left; an English
paragraph in a Hebrew message, a code block and an all-English message stay left to right. The same harness as
test_e2e.py."""
import json
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
M360 = (
    "**(m359) מעולה! getsuda.dev רשום, ב-Cloudflare** (ה-nameservers כבר שם). הנה מה שנשאר, בסדר הזה:\n\n"
    "**1. להפעיל את GitHub Pages** (עוד לא פעיל: udinur.github.io/Suda מחזיר 404):\n"
    "github.com/udiNur/Suda ← Settings ← Pages ← Source: **Deploy from a branch** ← Branch **main**, תיקייה **/docs** ← Save.\n\n"
    "**2. לאמת את הדומיין ב-GitHub, נגד השתלטות** (מומלץ):\n"
    "github.com/settings/pages ← **Add a domain** ← getsuda.dev. GitHub ייתן רשומת TXT. מוסיפים אותה ב-Cloudflare (שלב 3), וחוזרים ל-**Verify**.\n\n"
    "**3. רשומות DNS ב-Cloudflare** (dash.cloudflare.com ← getsuda.dev ← DNS). **הכל ב-DNS only** (ענן אפור, לא כתום), כדי ש-GitHub יוכל להוציא תעודה:\n"
    "```\nA     @    185.199.108.153\nCNAME www  udinur.github.io\n```\n"
    "Please keep this English paragraph in its own order.\n"
)
ENGLISH = 'All of this message is English: open Settings, then Pages, then Save.'

# the left edge of the first occurrence of `word` in the line (block) of the message that holds `key`
AT = r"""(key,word)=>{
  const blocks=[...document.querySelectorAll('#log .msg .body.md p, #log .msg .body.md li')].filter(b=>b.textContent.includes(key));
  if(!blocks.length)return null;const b=blocks[0];
  const w=document.createTreeWalker(b,NodeFilter.SHOW_TEXT);let n,text='',nodes=[];
  while((n=w.nextNode())){nodes.push([n,text.length]);text+=n.nodeValue;}
  const at=text.indexOf(word);if(at<0)return null;
  for(const [node,start] of nodes){if(at>=start&&at<start+node.nodeValue.length){const r=document.createRange();r.setStart(node,at-start);r.setEnd(node,at-start+1);const q=r.getBoundingClientRect();return [q.top,q.left];}}
  return null;}"""


class MessageDirection(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ok('new', 'md-dir', 'כיוון הודעה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('say', 'md-dir', '--from', 'fork', '-', input=M360)
        cls.ok('say', 'md-dir', '--from', 'fork', '-', input=ENGLISH + '\n')

    def x(self, key, word):
        return self.browser.eval('(()=>{const at=%s;return JSON.stringify(at(%s,%s))})()' % (AT, json.dumps(key), json.dumps(word)))

    @staticmethod
    def before(a, b):
        """Right to left reading: a comes first when it is on an earlier line, or on the same line to the right of b."""
        return a[0] < b[0] - 4 or (abs(a[0] - b[0]) <= 4 and a[1] > b[1])

    def block_dir(self, key):
        return self.browser.eval('JSON.stringify((b=>b?getComputedStyle(b).direction:null)([...document.querySelectorAll("#log .msg .body.md p, #log .msg .body.md li")].find(b=>b.textContent.includes(%s))))' % json.dumps(key))

    def test_steps_joined_by_arrows_read_right_to_left_in_a_hebrew_message(self):
        for size in (INNER, COVER, DESK):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'md-dir', 'כיוון הודעה')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=2)', what='the messages')
                self.browser.eval('(()=>{[...document.querySelectorAll("#log .msg")].at(-2).scrollIntoView({block:"start"});return 1})()')
                self.assertEqual(self.block_dir('github.com/udiNur/Suda'), 'rtl', 'the line of steps reads right to left')
                steps = [self.x('github.com/udiNur/Suda', w) for w in ('github.com', 'Settings', 'Pages', 'Source', 'Branch', 'Save')]
                self.assertTrue(all(v is not None for v in steps), steps)
                for a, b in zip(steps, steps[1:]):
                    self.assertTrue(self.before(a, b), 'each step is read after the one before it (right to left): %s' % steps)
                chain = [self.x('dash.cloudflare.com', w) for w in ('(dash', 'dash.cloudflare.com', 'getsuda.dev', 'DNS)', ')')]
                self.assertTrue(all(v is not None for v in chain), chain)
                for a, b in zip(chain, chain[1:]):
                    self.assertTrue(self.before(a, b), 'the bracket opens on the right of the chain, its steps right to left, and it closes on its left: %s' % chain)
                self.assertEqual(self.block_dir('Please keep this English'), 'ltr', 'an English paragraph keeps its order')
                self.assertEqual(self.block_dir('All of this message is English'), 'ltr', 'an English message stays left to right')
                self.assertNotRegex(self.browser.eval('JSON.stringify(document.querySelector("#log .md pre").textContent)'), '[\u200e\u200f]', 'code is never touched')

    def test_what_he_copies_has_no_marks_of_direction(self):
        self.open_thread(DESK, 'md-dir', 'כיוון הודעה')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=2)', what='the messages')
        got = self.browser.eval('(()=>{const b=[...document.querySelectorAll("#log .msg .body.md p")].find(p=>p.textContent.includes("github.com/udiNur/Suda"));'
                                'const r=document.createRange();r.selectNodeContents(b);const s=getSelection();s.removeAllRanges();s.addRange(r);'
                                'let out="";const e=new ClipboardEvent("copy",{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});'
                                'b.dispatchEvent(e);out=e.clipboardData.getData("text/plain");return JSON.stringify(out)})()')
        self.assertIn('github.com/udiNur/Suda ← Settings ← Pages', got)
        self.assertNotRegex(got, '[‎‏]')


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(MessageDirection(name) for name in sorted(vars(MessageDirection)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
