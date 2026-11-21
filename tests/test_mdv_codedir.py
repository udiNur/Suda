"""Code direction in the MD Viewer (after suda-fixes 25): the same as in Suda. Every line of a
code block stays left to right (its indentation, its sideways scrolling, a file tree, a JSON line), and only the
words of a comment in Hebrew are an island that reads right to left (`hebrewComment()`, Suda's pure function, which
the viewer takes from suda.html). The four holes `unicode-bidi:plaintext` had in Suda (test_adv_codedir.py), measured
here on the viewer's page at the phone and the desktop, plus the island itself.

Skips when agent-browser is missing. "os error 35" from agent-browser is a known flake: rerun."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

import test_mdv_e2e
from test_mdv_e2e import AB, Browser, server

PHONE, DESK = (360, 840), (1280, 800)

# Every line of the n-th code block of the document: its visible characters (spaces left out) with their left and
# right edges, relative to the left of the block's content box; and the block's scroll and client widths.
GEO = r"""((n)=>{const code=document.querySelectorAll('#doc .md pre code')[n];if(!code)return JSON.stringify(null);
  const pre=code.closest('pre'),pr=pre.getBoundingClientRect(),cs=getComputedStyle(pre);
  const x0=pr.left+parseFloat(cs.borderLeftWidth)+parseFloat(cs.paddingLeft)-pre.scrollLeft;
  const lines=[{text:'',glyphs:[]}];const w=document.createTreeWalker(code,NodeFilter.SHOW_TEXT);let t;
  while((t=w.nextNode())){for(let i=0;i<t.textContent.length;i++){const c=t.textContent[i];
    if(c==='\n'){lines.push({text:'',glyphs:[]});continue;}
    const line=lines[lines.length-1];line.text+=c;if(!c.trim())continue;
    const r=document.createRange();r.setStart(t,i);r.setEnd(t,i+1);const b=r.getBoundingClientRect();
    line.glyphs.push([c,b.left-x0,b.right-x0]);}}
  return JSON.stringify({scrollWidth:pre.scrollWidth,clientWidth:pre.clientWidth,lines});})(%d)"""

LONG = '# ' + 'הערה ארוכה שלא נכנסת ברוחב של הטלפון ' * 3 + 'סוף ההערה'
NOTES = {
    'indent.md': '# a\n\n```python\ndef check():\n    # בודקים את החיבור לשרת\n    return 1\n```\n',
    'long.md': '# b\n\n```python\n' + LONG + '\nx = 1\n```\n',
    'tree.md': '# c\n\n```\nproject/\n├── src/\n│   └── קובץ.py\n└── הערות.md\n```\n',
    'json.md': '# d\n\n```json\n{\n  "שם": "דנה",\n  "עיר": "חיפה"\n}\n```\n',
    'island.md': '# e\n\n```python\n# הערה לבד בשורה\nx = 1  # הערה אחרי קוד\ny = 2  # an English comment\n```\n',
}


@unittest.skipUnless(AB, 'agent-browser is not installed')
class CodeDirection(unittest.TestCase):
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
        cls.b = Browser('mdv-codedir-%d' % os.getpid())
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
        # no line wrapping (the default): a long line scrolls sideways
        self.b.eval('(()=>{document.documentElement.classList.remove("wrap-code");return 1})()')
        return self.b.eval(GEO % 0)

    @staticmethod
    def line(geo, starts):
        found = [l for l in geo['lines'] if l['text'].startswith(starts)]
        assert found, 'no line starts with %r in %r' % (starts, [l['text'] for l in geo['lines']])
        return found[0]

    @staticmethod
    def left_of(line, ch):
        return next(g[1] for g in line['glyphs'] if g[0] == ch)

    def test_a_an_indented_hebrew_comment_keeps_its_indentation(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                geo = self.show('indent.md', size)
                comment, ret = self.line(geo, '    #'), self.line(geo, '    return')
                start = min(g[1] for g in comment['glyphs'])
                self.assertGreaterEqual(start, self.left_of(ret, 'r') - 1,
                                        'the comment starts at its indentation, as `return` does: %r vs %r'
                                        % (start, self.left_of(ret, 'r')))

    def test_b_a_long_hebrew_comment_is_not_cut_off_on_the_phone(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                geo = self.show('long.md', size)
                comment = self.line(geo, '# ')
                lo, hi = min(g[1] for g in comment['glyphs']), max(g[2] for g in comment['glyphs'])
                self.assertGreaterEqual(lo, -1, 'the long comment runs out of the left of the block, where it cannot '
                                                'be scrolled to (left edge %r)' % lo)
                self.assertLessEqual(hi, geo['scrollWidth'] + 1, 'every character of it is within the scroll %r' % geo)

    def test_c_a_file_tree_with_hebrew_names_keeps_its_branches_on_the_left(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                geo = self.show('tree.md', size)
                deep, last = self.line(geo, '│'), self.line(geo, '└──')
                self.assertLessEqual(self.left_of(deep, '│'), 1, 'the trunk stays at the left margin %r' % deep)
                self.assertLess(self.left_of(deep, '└'), self.left_of(deep, 'ק'), 'the branch is left of the name %r' % deep)
                self.assertLessEqual(self.left_of(last, '└'), 1, 'the last branch stays at the left margin %r' % last)
                self.assertLess(self.left_of(last, '└'), self.left_of(last, 'ה'), 'the branch is left of the name %r' % last)

    def test_d_a_json_line_that_starts_with_a_hebrew_key_stays_left_to_right(self):
        for size in (PHONE, DESK):
            with self.subTest(size=size[0]):
                geo = self.show('json.md', size)
                row, brace = self.line(geo, '  "שם"'), self.line(geo, '{')
                first = min(row['glyphs'], key=lambda g: g[1])
                self.assertEqual(first[0], '"', 'the line starts on the left with its opening quote %r' % row)
                self.assertGreater(first[1], self.left_of(brace, '{') + 1, 'and keeps its indentation %r' % row)
                self.assertEqual(max(row['glyphs'], key=lambda g: g[1])[0], ',', 'the comma ends it on the right %r' % row)

    def test_e_a_hebrew_comment_is_an_island_that_reads_right_to_left(self):
        geo = self.show('island.md', PHONE)
        islands = self.b.eval('JSON.stringify([...document.querySelectorAll("#doc .md pre code bdi")]'
                              '.map(b=>[b.dir,b.textContent,b.closest(".tk-c")?1:0]))')
        # alone on its line the # goes into the island (to the right of its words); after code it stays by the code;
        # an English comment is no island
        self.assertEqual(islands, [['rtl', '# הערה לבד בשורה', 1], ['rtl', 'הערה אחרי קוד', 1]])
        alone, after = self.line(geo, '#'), self.line(geo, 'x = 1')
        hash_x = self.left_of(alone, '#')
        self.assertGreater(hash_x, max(g[1] for g in alone['glyphs'] if g[0] != '#'), 'the # is right of its words %r' % alone)
        self.assertLess(self.left_of(after, '#'), min(g[1] for g in after['glyphs'] if '֐' <= g[0] <= '׿'),
                        'after code the # stays by the code, left of the words %r' % after)
        self.assertNotEqual(self.b.eval('getComputedStyle(document.querySelector("#doc .md pre code")).unicodeBidi'), 'plaintext',
                            'a line of code never takes the direction of its own letters')


if __name__ == '__main__':
    unittest.main()
