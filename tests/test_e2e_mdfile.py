#!/usr/bin/env python3
"""End to end: a .md file an agent names by its full path opens in the MD Viewer (thread md-viewer, m6).

"I want to be able to view the MDs you write for me." An agent writes the path in inline code; the page shows a
file chip with the file's name, whose address is the viewer on this server (/mdv/?path=...) with the whole path.
The same harness as test_e2e.py. Checked on the phone and the desktop: the chip, its name, its address, and that
a path that is not a .md stays code.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest
from urllib.parse import quote

import test_e2e
from test_e2e import SIZES

TID = 'e2e-mdfile'
TITLE = 'קובץ md של סוכן'
PATH = '~/Documents/mds/todo/plan-2026-11-20.md'


class MdFile(test_e2e.Suda):
    def test_a_md_path_is_a_chip_that_opens_the_viewer(self):
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', 'התוכנית מוכנה: `%s` והלוג ב-`~/x/run.log`' % PATH,
                '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for size in (SIZES[0], SIZES[2]):
            self.open_thread(size, TID, TITLE)
            got = self.browser.wait('JSON.stringify((()=>{const a=document.querySelector("#log a.chip-link[data-kind=file]");if(!a)return null;'
                                    'return {href:a.getAttribute("href"),name:a.querySelector(".chip-text").textContent,title:a.title,'
                                    'code:[...document.querySelectorAll("#log .md code")].map(c=>c.textContent)};})())', what='the file chip')
            self.assertEqual(got['href'], '/mdv/?path=' + quote(PATH, safe=''))
            self.assertEqual(got['name'], 'plan-2026-11-20.md')
            self.assertEqual(got['title'], PATH)
            self.assertIn('~/x/run.log', got['code'])


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in MdFile.__dict__:
        setattr(MdFile, _name, None)


if __name__ == '__main__':
    unittest.main()
