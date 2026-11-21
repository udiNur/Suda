"""Hostile review 6 of the viewer's code direction (92efd2a, codeNodes() + Suda's hebrewComment()): the order in which
the characters of a line of code are DRAWN, measured glyph by glyph on the viewer's page.

The change keeps every line left to right and puts the words of a Hebrew comment in a <bdi dir=rtl> island. Four ways
that island (or the left to right line around it) draws code in an order it does not have:

  a  a block comment after code, `x = 1; /* הערה */ y = 2;`: the opening `/* ` stays outside the island, the closing
     ` */` goes into it and is drawn on the far side of the words, as `/*`. The line reads `x = 1; /* /* הערה y = 2;`.
     The same split moves the closing bracket of `#(הערה)`.
  b  a `#` in the middle of a word in sh (a URL with a #fragment) starts a comment token, so the code after it is
     pulled into the right to left island: `curl https://example.com/page#top # מוריד` is drawn
     `curl https://example.com/page#מוריד # top`.
  c  an English comment that mentions one Hebrew word is an island that reads right to left, so its English words are
     drawn backwards: `// Returns the user name (שם) or null` reads `or null (שם) Returns the user name //`.
  d  (older than 92efd2a, still there) two Hebrew strings in one line of code swap places:
     `const a = ["שלום", "עולם"];` is drawn with "עולם" first.

Each test asserts the safe outcome. All fail on 92efd2a. Skips when agent-browser is missing; "os error 35" or
ERR_ABORTED from agent-browser are flakes: rerun."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

import test_mdv_e2e
from test_mdv_e2e import AB, Browser, server

PHONE, DESK = (360, 840), (1280, 800)

# Every line of the first code block: each of its characters (spaces too, so an index in the line's text is an index
# here) with its left and right edge on the screen.
GLYPHS = r"""(()=>{const code=document.querySelector('#doc .md pre code');if(!code)return JSON.stringify(null);
  const lines=[{text:'',glyphs:[]}];const w=document.createTreeWalker(code,NodeFilter.SHOW_TEXT);let t;
  while((t=w.nextNode())){for(let i=0;i<t.textContent.length;i++){const c=t.textContent[i];
    if(c==='\n'){lines.push({text:'',glyphs:[]});continue;}
    const line=lines[lines.length-1];line.text+=c;
    const r=document.createRange();r.setStart(t,i);r.setEnd(t,i+1);const b=r.getBoundingClientRect();
    line.glyphs.push([c,b.left,b.right]);}}
  return JSON.stringify(lines);})()"""

NOTES = {
    'block.md': '# a\n\n```js\nx = 1; /* הערה */ y = 2;\n```\n',
    'bracket.md': '# a\n\n```python\nx = 1  #(הערה)\n```\n',
    'url.md': '# a\n\n```sh\ncurl https://example.com/page#top # מוריד את הדף\n```\n',
    'mixed.md': '# a\n\n```js\n// Returns the user name (שם) or null\n/**\n * @param {string} name שם המשתמש\n */\n```\n',
    'strings.md': '# a\n\n```js\nconst a = ["שלום", "עולם"];\n```\n',
}
HEB = re.compile('[֐-׿]')


@unittest.skipUnless(AB, 'agent-browser is not installed')
class CodeOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        for name, text in NOTES.items():
            (cls.root / name).write_text(text)
        (base / 'roots.json').write_text('{"roots": []}')
        cls.port = test_mdv_e2e.free_port()
        cls.srv = server.make_server(cls.port, server.Config(base / 'roots.json', [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.b = Browser('mdv-adv-r6-order-%d' % os.getpid())
        try:
            cls.b.run('open', 'about:blank', timeout=120)
        except Exception as e:
            cls.srv.shutdown()
            raise unittest.SkipTest('agent-browser could not open a browser: ' + str(e)[:200])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.b.run('close', timeout=60)
        except Exception:
            pass
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def show(self, name, size):
        self.b.run('set', 'viewport', str(size[0]), str(size[1]))
        self.b.run('open', 'http://127.0.0.1:%d/mdv/?path=%s' % (self.port, quote(str(self.root / name), safe='')))
        self.b.wait('!!document.querySelector("#doc .md pre code")', what='the code block')
        self.b.eval('(()=>{document.documentElement.classList.remove("wrap-code");return 1})()')
        return self.b.eval(GLYPHS)

    @staticmethod
    def line(lines, starts):
        found = [l for l in lines if l['text'].startswith(starts)]
        assert found, 'no line starts with %r in %r' % (starts, [l['text'] for l in lines])
        return found[0]

    @staticmethod
    def x(line, i):
        """The middle of the i-th character of the line, on the screen."""
        g = line['glyphs'][i]
        return (g[1] + g[2]) / 2

    @staticmethod
    def seen(line):
        """The visible characters of the line in the order they are drawn, left to right."""
        return ''.join(g[0] for g in sorted(line['glyphs'], key=lambda g: g[1]) if g[0].strip())

    def word_x(self, line, word):
        at = line['text'].index(word)
        xs = [self.x(line, i) for i in range(at, at + len(word))]
        return min(xs), max(xs)

    def test_a_a_block_comment_after_code_keeps_its_closing_marker(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('block.md', size), 'x = 1;')
                drawn = re.sub(HEB, 'ה', self.seen(row))
                self.assertRegex(drawn, r'^x=1;/\*ה+\*/y=2;$',
                                 'the comment is drawn /* words */, its closing marker after its words: drawn %r'
                                 % self.seen(row))

    def test_a2_a_bracket_right_after_the_marker_still_closes_after_the_words(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('bracket.md', size), 'x = 1')
                lo, hi = self.word_x(row, 'הערה')
                o, c = self.x(row, row['text'].index('(')), self.x(row, row['text'].index(')'))
                self.assertTrue(min(o, c) < lo and hi < max(o, c),
                                'the two brackets stand on the two sides of the words (open %r, close %r, words %r..%r)'
                                % (o, c, lo, hi))

    def test_b_code_after_a_hash_inside_a_word_is_not_pulled_into_the_island(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('url.md', size), 'curl')
                self.assertTrue(self.seen(row).startswith('curlhttps://example.com/page#top'),
                                'the URL is drawn whole, its #top in place: drawn %r' % self.seen(row))
                self.assertLess(self.x(row, row['text'].index('top')), self.word_x(row, 'מוריד')[0],
                                'the code `top` stays left of the Hebrew comment')

    def test_c_an_english_comment_with_one_hebrew_word_keeps_its_english_in_order(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                lines = self.show('mixed.md', size)
                row = self.line(lines, '// Returns')
                t = row['text']
                self.assertLess(self.x(row, t.index('Returns')), self.x(row, t.index('null')),
                                '"Returns ... or null" reads left to right: drawn %r' % self.seen(row))
                self.assertLess(self.x(row, t.index('//')), self.x(row, t.index('Returns')),
                                'the // stays before the words it starts: drawn %r' % self.seen(row))
                doc = self.line(lines, ' * @param')
                t = doc['text']
                self.assertLess(self.x(doc, t.index('@param')), self.x(doc, t.index('name')),
                                'a JSDoc tag reads `@param {string} name`: drawn %r' % self.seen(doc))

    def test_d_two_hebrew_strings_in_a_line_keep_their_order(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                row = self.line(self.show('strings.md', size), 'const')
                first, second = self.word_x(row, 'שלום'), self.word_x(row, 'עולם')
                self.assertLess(first[1], second[0],
                                'the first string is drawn left of the second, as the array holds them: drawn %r'
                                % self.seen(row))


if __name__ == '__main__':
    unittest.main()
