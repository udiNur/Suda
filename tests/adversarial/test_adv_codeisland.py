#!/usr/bin/env python3
"""Hostile review of e180156 (code islands in Suda as in the MD viewer, from one function: codeIsland() and
codePieces() in Suda's pure section, suda-fixes 51).

What breaks, each asserted as the safe outcome (every test here failed on e180156):

- codeIsland()'s pattern backtracks in square time over a run of spaces or tabs inside a Hebrew comment (the lazy
  words group against the optional `[ \\t]*\\*\\/` and the trailing `[ \\t]*`): one comment line with 55000 spaces
  holds the page for seconds, on every draw. Suda's old hebrewComment() was linear.
- In sh, after a `#` inside a word (page#top) the rest of the line becomes one plain piece, so a Hebrew string after
  it is no island any more: two Hebrew strings on that line swap places again (what the change set out to fix).
- Find in the thread searches each text node on its own. A Hebrew string is now its quote, a bdi and its quote, and a
  block comment after code keeps its `*/` out of the island: searching `"שלום"` or `הערה */` finds nothing, though
  both are in the message and were found before. (The MD viewer's find already searches a code block as one text.)

The unit tests run Suda's pure section under node, as test_slack does; the e2e test uses test_e2e's harness (a real
board server on loopback, a temp board, agent-browser)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'
COVER, INNER, DESK = SIZES


class CodeIslandPure(unittest.TestCase):

    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'}, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_a_long_run_of_spaces_in_a_hebrew_comment_does_not_hold_the_page(self):
        # A linear pattern takes about a millisecond here; on e180156 it takes seconds (square time in the spaces).
        self.pure_js(r"""
        for(const pad of [' ','\t',' \t']){
          const part='# שלום'+pad.repeat(Math.floor(55000/pad.length))+'x';
          let t=Date.now();const h=codeIsland(part,true);const island=Date.now()-t;
          assert.strictEqual(h.lead+h.rtl+h.tail,part);
          t=Date.now();codePieces('x = 1\n'+part,'py');const pieces=Date.now()-t;
          assert.ok(island<300,'codeIsland took '+island+' ms on one comment line with '+part.length+' characters');
          assert.ok(pieces<300,'codePieces took '+pieces+' ms on a two-line block');
        }
        // a block comment's middle line with a long gap before its closing marker
        const mid=' * הערה'+' '.repeat(55000)+'x */';
        const t=Date.now();codeIsland(mid,true);const ms=Date.now()-t;
        assert.ok(ms<300,'codeIsland took '+ms+' ms on a block comment line');
        """)

    def test_b_hebrew_strings_after_a_hash_inside_a_word_keep_their_islands(self):
        # The same two strings without the page#top before them are each an island (test_slack); after it they
        # must still be, or the bidi algorithm draws "עולם" before "שלום".
        self.pure_js(r"""
        const strings=ps=>ps.filter(p=>p.k==='s'&&p.q!==undefined).map(p=>p.q+p.rtl+p.q);
        assert.deepStrictEqual(strings(codePieces('echo "שלום" "עולם"','sh')),['"שלום"','"עולם"']);
        assert.deepStrictEqual(strings(codePieces('git checkout main#1 && echo "שלום" "עולם"','sh')),['"שלום"','"עולם"']);
        assert.deepStrictEqual(strings(codePieces('curl https://example.com/page#top -d "שלום" "עולם" # מוריד','sh')),['"שלום"','"עולם"']);
        assert.deepStrictEqual(strings(codePieces('url: page#top "שלום" "עולם"','yaml')),['"שלום"','"עולם"']);
        """)


class CodeIslandFind(test_e2e.Suda):
    """Find in the thread, inside code with islands."""

    BLOCK = '```js\nconst a = ["שלום", "עולם"];\nx = 1; /* הערה */ y = 2;\n```'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ok('new', 'ci-find', 'חיפוש בקוד', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('say', 'ci-find', '--from', 'fork', '-', input='הנה הקוד:\n\n' + cls.BLOCK + '\n')

    def search(self, q):
        self.browser.eval('(()=>{openFind();const q=document.querySelector("#find-q");q.value=%s;'
                          'q.dispatchEvent(new Event("input",{bubbles:true}));return 1;})()' % json.dumps(q))
        return self.browser.eval('JSON.stringify({count:document.querySelector("#find-count").textContent,'
                                 'marked:find.marks.map(m=>[m,...(m.parts||[])].map(x=>x.textContent).join("")).join(""),lit:[...document.querySelectorAll("mark.hl.cur")].map(x=>x.textContent).join("")})')

    def test_a_find_in_the_thread_finds_a_quoted_hebrew_string_and_a_comment_s_closing_marker(self):
        self.open_thread(DESK, 'ci-find', 'חיפוש בקוד')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .md pre code bdi"))', what='the code block')
        for q in ('"שלום"', 'הערה */'):
            with self.subTest(q=q):
                got = self.search(q)
                self.assertNotEqual(got['count'], 'אין תוצאות', 'the code holds %r but find says there is none' % q)
                self.assertEqual(got['marked'], q, 'what find marks is the query, counted once')
                self.assertEqual(got['lit'], q, 'the current match is lit whole, in all its pieces')


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(cls(name) for cls in (CodeIslandPure, CodeIslandFind) for name in sorted(vars(cls)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
