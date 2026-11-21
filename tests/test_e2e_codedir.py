#!/usr/bin/env python3
"""End to end: each line of a code block in the direction of its own words (suda-fixes task 25; the owner's yes to
md-viewer m4: "a Hebrew comment does not flip", as the MD viewer already shows code).

A line that starts in Hebrew (a comment, a line of text in a fenced block) reads right to left, its '#' on its right;
a line of code reads left to right, also when a Hebrew comment ends it. Measured by where the characters stand on the
screen (Range rects), at the cover and the desktop. The same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
TID = 'e2e-codedir'
TITLE = 'כיוון שורות בקוד'
CODE = '```python\n# בודקים את החיבור לשרת\nconst_x = 1\nretries = 3  # עד שלוש פעמים\n```'

# where character `ch` of the first text node holding `needle` stands: its left edge
WHERE = r"""(needle,ch)=>{
  const w=document.createTreeWalker(document.querySelector('#log .md pre code'),NodeFilter.SHOW_TEXT);let n;
  const all=[];while((n=w.nextNode()))all.push(n);
  // the text of the whole line can be split by the colouring: find the node that holds the char of this line
  for(const t of all){const at=t.textContent.indexOf(ch);if(at<0)continue;
    const line=t.parentElement.closest('pre').textContent.split('\n').find(l=>l.includes(needle));
    if(!line||!t.textContent.trim()||!line.includes(t.textContent.trim().slice(0,3)))continue;
    const r=document.createRange();r.setStart(t,at);r.setEnd(t,at+ch.length);return r.getBoundingClientRect().left;}
  return null;}"""


class CodeDirection(test_e2e.Suda):

    def positions(self):
        js = '(()=>{const at=%s;return JSON.stringify({hash:at("בודקים","#"),heb:at("בודקים","בודקים"),c:at("const_x","const_x"),one:at("const_x","1"),' \
             'r:at("retries","retries"),rhash:at("retries","#")})})()' % WHERE
        return self.browser.eval(js)

    def test_a_hebrew_line_in_code_reads_right_to_left_and_code_left_to_right(self):
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', '-', input='הנה הקוד:\n\n' + CODE + '\n')
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                self.open_thread(size, TID, TITLE)
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .md pre code"))', what='the code block')
                got = self.positions()
                self.assertTrue(all(v is not None for v in got.values()), got)
                self.assertGreater(got['hash'], got['heb'], 'a Hebrew comment line reads right to left: its # on its right %s' % got)
                self.assertLess(got['c'], got['one'], 'a line of code reads left to right %s' % got)
                self.assertLess(got['r'], got['rhash'], 'code with a Hebrew comment after it stays left to right %s' % got)


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(CodeDirection(name) for name in sorted(vars(CodeDirection)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
