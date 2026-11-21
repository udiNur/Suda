#!/usr/bin/env python3
"""Hostile review of d475256 (each line of a code block in the direction of its own words, suda-fixes task 25).

`.md pre code{unicode-bidi:plaintext}` makes every line whose first strong letter is Hebrew a right to left paragraph
inside a left to right, left aligned, sideways scrolling block. What that breaks, measured on the screen (Range rects
of every visible character, relative to the block's content box), at the cover and the desktop:

- an indented Hebrew comment loses its indentation: its leading spaces go to its right, the comment jumps to the
  left margin, out of the function it belongs to;
- a long Hebrew comment on the phone (no line wrapping, the default) overflows to the LEFT of the block, where a left
  to right scroller cannot scroll: the end of the comment is cut off and cannot be read;
- a file tree with Hebrew names: the branches (box drawing) of a line move to the right of the name;
- a line of JSON that starts with a Hebrew key turns right to left as a whole: its comma jumps to the left and its
  indentation to the right (SKILL.md itself promises that a line of code reads left to right).

Each test asserts the safe outcome (what the old code showed for these lines, and what a Hebrew comment that does
not flip still allows). The same harness as test_e2e.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import re
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES

# Every line of the n-th code block of the log: its visible characters (spaces left out) with their left and right
# edges, relative to the left of the block's content box; and the block's scroll and client widths.
GEO = r"""((n)=>{const code=document.querySelectorAll('#log .md pre code')[n];if(!code)return JSON.stringify(null);
  const pre=code.closest('pre'),pr=pre.getBoundingClientRect(),cs=getComputedStyle(pre);
  const x0=pr.left+parseFloat(cs.borderLeftWidth)+parseFloat(cs.paddingLeft)-pre.scrollLeft;
  const lines=[{text:'',glyphs:[]}];const w=document.createTreeWalker(code,NodeFilter.SHOW_TEXT);let t;
  while((t=w.nextNode())){for(let i=0;i<t.textContent.length;i++){const c=t.textContent[i];
    if(c==='\n'){lines.push({text:'',glyphs:[]});continue;}
    const line=lines[lines.length-1];line.text+=c;if(!c.trim())continue;
    const r=document.createRange();r.setStart(t,i);r.setEnd(t,i+1);const b=r.getBoundingClientRect();
    line.glyphs.push([c,b.left-x0,b.right-x0]);}}
  return JSON.stringify({scrollWidth:pre.scrollWidth,clientWidth:pre.clientWidth,lines});})(%d)"""


class CodeDirectionHoles(test_e2e.Suda):

    def post(self, tid, title, block):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', '-', input='הנה הקוד:\n\n' + block + '\n')

    def show(self, size, tid, title, wrap=False):
        self.open_thread(size, tid, title)
        # line wrapping of code is his choice kept in the browser: set it, then open the thread again so it holds
        self.browser.eval('(()=>{localStorage.setItem("suda-wrap-code",%s);return 1})()' % json.dumps('1' if wrap else '0'))
        self.open_thread(size, tid, title)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .md pre code"))', what='the code block')
        self.assertEqual(self.browser.eval('JSON.stringify(document.documentElement.classList.contains("wrap-code"))'), wrap)
        return self.browser.eval(GEO % 0)

    @staticmethod
    def line(geo, starts):
        found = [l for l in geo['lines'] if l['text'].startswith(starts)]
        assert found, 'no line starts with %r in %r' % (starts, [l['text'] for l in geo['lines']])
        return found[0]

    @staticmethod
    def left_of(line, ch):
        return next(g[1] for g in line['glyphs'] if g[0] == ch)

    def test_a_an_indented_hebrew_comment_keeps_its_indentation(self):
        tid, title = 'adv-cd-indent', 'הערה מוזחת בקוד'
        self.post(tid, title, '```python\ndef check():\n    # בודקים את החיבור לשרת\n    return 1\n```')
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                geo = self.show(size, tid, title)
                comment, ret = self.line(geo, '    #'), self.line(geo, '    return')
                start = min(g[1] for g in comment['glyphs'])
                self.assertGreaterEqual(start, self.left_of(ret, 'r') - 1,
                                        'the comment inside the function starts at its indentation, as `return` does, '
                                        'not at the left margin: %r vs %r' % (start, self.left_of(ret, 'r')))

    def test_b_a_long_hebrew_comment_is_not_cut_off_on_the_phone(self):
        tid, title = 'adv-cd-long', 'הערה ארוכה בקוד'
        long = '# ' + 'הערה ארוכה שלא נכנסת ברוחב של הטלפון ' * 3 + 'סוף ההערה'
        self.post(tid, title, '```python\n' + long + '\nx = 1\n```')
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                geo = self.show(size, tid, title, wrap=False)
                comment = self.line(geo, '# ')
                lo, hi = min(g[1] for g in comment['glyphs']), max(g[2] for g in comment['glyphs'])
                # a left to right block scrolls from 0 to scrollWidth: what stands left of 0 can never be seen
                self.assertGreaterEqual(lo, -1, 'the long comment runs out of the left of the block, where it cannot be '
                                                'scrolled to: its end is lost (left edge %r)' % lo)
                self.assertLessEqual(hi, geo['scrollWidth'] + 1, 'every character of it is within the scroll %r' % geo)

    def test_c_a_file_tree_with_hebrew_names_keeps_its_branches_on_the_left(self):
        tid, title = 'adv-cd-tree', 'עץ קבצים בקוד'
        self.post(tid, title, '```\nproject/\n├── src/\n│   └── קובץ.py\n└── הערות.md\n```')
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                geo = self.show(size, tid, title)
                deep, last = self.line(geo, '│'), self.line(geo, '└──')
                self.assertLessEqual(self.left_of(deep, '│'), 1, 'the trunk of the tree stays at the left margin %r' % deep)
                self.assertLess(self.left_of(deep, '└'), self.left_of(deep, 'ק'), 'the branch stands left of the name %r' % deep)
                self.assertLessEqual(self.left_of(last, '└'), 1, 'the last branch stays at the left margin %r' % last)
                self.assertLess(self.left_of(last, '└'), self.left_of(last, 'ה'), 'the branch stands left of the name %r' % last)

    def test_d_a_json_line_that_starts_with_a_hebrew_key_stays_left_to_right(self):
        tid, title = 'adv-cd-json', 'מפתח בעברית בקוד'
        self.post(tid, title, '```json\n{\n  "שם": "דנה",\n  "עיר": "חיפה"\n}\n```')
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                geo = self.show(size, tid, title)
                row, brace = self.line(geo, '  "שם"'), self.line(geo, '{')
                # (the key and the value were already swapped before d475256: neutral `": "` between two Hebrew
                # words joins them into one right to left run; that needs each string isolated, a separate matter)
                first = min(row['glyphs'], key=lambda g: g[1])
                self.assertEqual(first[0], '"', 'the line of code starts on the left with its opening quote %r' % row)
                self.assertGreater(first[1], self.left_of(brace, '{') + 1, 'and keeps its two spaces of indentation %r' % row)
                self.assertEqual(max(row['glyphs'], key=lambda g: g[1])[0], ',', 'the comma ends the line on its right %r' % row)


# every character of each line (spaces too), with its left and right edge on the screen
GLYPHS = r"""((n)=>{const code=document.querySelectorAll('#log .md pre code')[n];const lines=[{text:'',glyphs:[]}];
  const w=document.createTreeWalker(code,NodeFilter.SHOW_TEXT);let t;
  while((t=w.nextNode())){for(let i=0;i<t.textContent.length;i++){const c=t.textContent[i];
    if(c==='\n'){lines.push({text:'',glyphs:[]});continue;}const line=lines[lines.length-1];line.text+=c;
    const r=document.createRange();r.setStart(t,i);r.setEnd(t,i+1);const b=r.getBoundingClientRect();line.glyphs.push([c,b.left,b.right]);}}
  return JSON.stringify(lines);})(%d)"""
HEB = re.compile('[\u0590-\u05ff]')
ROUND6 = {'block': '```js\nx = 1; /* הערה */ y = 2;\n```', 'bracket': '```python\nx = 1  #(הערה)\n```',
          'url': '```sh\ncurl https://example.com/page#top # מוריד את הדף\n```',
          'mixed': '```js\n// Returns the user name (שם) or null\n/**\n * @param {string} name שם המשתמש\n */\n```',
          'strings': '```js\nconst a = ["שלום", "עולם"];\n```'}


class CodeOrderHoles(test_e2e.Suda):
    """The holes md-viewer's review round 6 found in the island (suda-fixes 51), on Suda's own page."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name, block in ROUND6.items():
            cls.ok('new', 'co-' + name, 'סדר בקוד ' + name, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            cls.ok('say', 'co-' + name, '--from', 'fork', '-', input='הנה:\n\n' + block + '\n')

    def show(self, name, size):
        self.open_thread(size, 'co-' + name, 'סדר בקוד ' + name)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .md pre code"))', what='the code block')
        self.browser.eval('(()=>{document.documentElement.classList.remove("wrap-code");return 1})()')
        return self.browser.eval(GLYPHS % 0)

    @staticmethod
    def line(lines, starts):
        found = [l for l in lines if l['text'].startswith(starts)]
        assert found, 'no line starts with %r in %r' % (starts, [l['text'] for l in lines])
        return found[0]

    @staticmethod
    def x(line, i):
        g = line['glyphs'][i]
        return (g[1] + g[2]) / 2

    @staticmethod
    def seen(line):
        return ''.join(g[0] for g in sorted(line['glyphs'], key=lambda g: g[1]) if g[0].strip())

    def word_x(self, line, word):
        at = line['text'].index(word)
        xs = [self.x(line, i) for i in range(at, at + len(word))]
        return min(xs), max(xs)

    def test_a_a_block_comment_after_code_keeps_its_closing_marker(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('block', size), 'x = 1;')
                self.assertRegex(re.sub(HEB, 'ה', self.seen(row)), r'^x=1;/\*ה+\*/y=2;$', 'drawn %r' % self.seen(row))

    def test_a2_a_bracket_right_after_the_marker_still_closes_after_the_words(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('bracket', size), 'x = 1')
                lo, hi = self.word_x(row, 'הערה')
                o, c = self.x(row, row['text'].index('(')), self.x(row, row['text'].index(')'))
                self.assertTrue(min(o, c) < lo and hi < max(o, c), 'brackets around the words: %r %r %r %r' % (o, c, lo, hi))

    def test_b_code_after_a_hash_inside_a_word_is_not_pulled_into_the_island(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('url', size), 'curl')
                self.assertTrue(self.seen(row).startswith('curlhttps://example.com/page#top'), 'drawn %r' % self.seen(row))
                self.assertLess(self.x(row, row['text'].index('top')), self.word_x(row, 'מוריד')[0])

    def test_c_an_english_comment_with_one_hebrew_word_keeps_its_english_in_order(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                lines = self.show('mixed', size)
                row = self.line(lines, '// Returns')
                t = row['text']
                self.assertLess(self.x(row, t.index('Returns')), self.x(row, t.index('null')), 'drawn %r' % self.seen(row))
                self.assertLess(self.x(row, t.index('//')), self.x(row, t.index('Returns')), 'drawn %r' % self.seen(row))
                doc = self.line(lines, ' * @param')
                self.assertLess(self.x(doc, doc['text'].index('@param')), self.x(doc, doc['text'].index('name')), 'drawn %r' % self.seen(doc))

    def test_d_two_hebrew_strings_in_a_line_keep_their_order(self):
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('strings', size), 'const')
                first, second = self.word_x(row, 'שלום'), self.word_x(row, 'עולם')
                self.assertLess(first[1], second[0], 'drawn %r' % self.seen(row))


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(cls(name) for cls in (CodeDirectionHoles, CodeOrderHoles) for name in sorted(vars(cls)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
