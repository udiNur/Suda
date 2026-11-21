#!/usr/bin/env python3
"""The public product is English, left to right (the owner, suda m612, m617): Hebrew lives in locales/he.json (and
locales/he.cli.json), which an installation in Hebrew loads. Two guards:

1. The source: the product's files hold Hebrew only where it is Hebrew-support logic (detecting right-to-left
   text, the Hebrew keyboard layout, Hebrew words accepted on input, Hebrew answer marks, the transliteration of a
   Hebrew title into an id, the palette's Hebrew synonyms): those lines, and no more of them. A new Hebrew string in
   the code fails here; it belongs in locales/.
2. The page as an English installation draws it, in a browser: no Hebrew in any text, placeholder, label or title,
   on the conversation, the palette, the help and the settings.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
from pathlib import Path
import re
import subprocess
import time
import unittest

os.environ.setdefault('SUDA_E2E_LANG', 'en')      # (read by the harness when the class starts)
import test_e2e
from test_e2e import SIZES

ROOT = _paths.REPO
HEBREW = re.compile('[֐-׿]')
# file: (the most lines with Hebrew, what each such line must hold)
ALLOWED = {
    'suda/suda.html': (33, ('const HEBREW=', 'HE_KEYS', "/[א-ת]/.test(ch)", 'HE_PREFIX', "hebrew|עברית",
                       "בקשה לא תקינה|invalid request", "tag=' הגדרות settings'", "['")),
    'suda/threads.py': (5, ('today|tomorrow|', "('tomorrow', '", 'ORDERS = (', '[א-ת]', 'LATIN = dict(')),
    'README.md': (1, ('<a href="README.he.md">',)),          # the language row names each language in itself
}
PRODUCT = re.compile(r'^(?!tests/|suda/locales/|suda/vendor/|docs/assets/|suda/icons/|README\.[a-z]{2}(?:-[A-Z]{2})?\.md$).*\.(html|js|json|py|md|css)$')   # (README.<lang>.md: a translation, kept in step by test_readme.py)


class Source(unittest.TestCase):
    def test_the_product_holds_hebrew_only_as_hebrew_support(self):
        files = [f for f in subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split() if PRODUCT.match(f)]
        self.assertIn('suda/suda.html', files)
        for name in files:
            lines = [line for line in (ROOT / name).read_text(encoding='utf-8', errors='replace').splitlines() if HEBREW.search(line)]
            most, marks = ALLOWED.get(name, (0, ()))
            with self.subTest(file=name):
                self.assertLessEqual(len(lines), most, '%s: Hebrew on %d lines (at most %d); a string the user reads goes to locales/: %s'
                                     % (name, len(lines), most, [l.strip()[:80] for l in lines][:5]))
                for line in lines:
                    self.assertTrue(any(mark in line for mark in marks), '%s: Hebrew outside the Hebrew-support logic: %s' % (name, line.strip()[:120]))

    def test_no_personal_name_in_the_tree(self):
        """The public tree names no person (the release scan found one left in a test's sample data)."""
        names = re.compile('aduhey'[::-1] + '|\u05d9\u05d4\u05d5\u05d3\u05d4', re.I)     # (spelled so this file does not hold it)
        files = [f for f in subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
                 if not f.startswith(('suda/vendor/', 'docs/assets/', 'suda/icons/')) and not f.endswith(('.png', '.gif', '.ico'))]
        hits = [f for f in files if names.search((ROOT / f).read_text(encoding='utf-8', errors='replace'))]
        self.assertEqual(hits, [])

    def test_no_em_dash_or_en_dash_in_the_tree(self):
        """No em dash or en dash in any tracked text file (the owner's standing rule): a comma, a colon, a period or
        parentheses instead. A test that feeds one to the code writes it as an escape (\\u2014, \\u2013)."""
        dashes = re.compile('[\u2013\u2014]')
        files = [f for f in subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
                 if not f.startswith(('suda/vendor/', 'docs/assets/', 'suda/icons/')) and not f.endswith(('.png', '.gif', '.ico', '.mp4', '.webm'))]
        hits = []
        for name in files:
            for n, line in enumerate((ROOT / name).read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if dashes.search(line):
                    hits.append('%s:%d' % (name, n))
        self.assertEqual(hits, [], '%d lines with an em dash or en dash' % len(hits))

    def test_the_repo_page_is_english_and_left_to_right(self):
        page = (_paths.APP / 'suda.html').read_text(encoding='utf-8')
        self.assertIn('<html lang="en" dir="ltr">', page)
        self.assertIn("var LANG='en',L10N={};", page)


SCAN = r'''JSON.stringify((()=>{const he=/[֐-׿]/,out=[];
  const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  for(let n;(n=walk.nextNode());){const e=n.parentElement;if(!e||e.closest('#log .body,.msg .body,[hidden],script,style'))continue;
    if(he.test(n.textContent)&&e.offsetParent!==null)out.push(n.textContent.trim().slice(0,60));}
  for(const e of document.querySelectorAll('[placeholder],[aria-label],[title],[alt]')){if(e.closest('[hidden]'))continue;
    for(const a of ['placeholder','aria-label','title','alt'])if(he.test(e.getAttribute(a)||''))out.push(a+': '+e.getAttribute(a).slice(0,60));}
  if(he.test(document.title))out.push('title: '+document.title);
  return out.slice(0,12);})())'''


class EnglishPage(test_e2e.Suda):
    def test_an_english_installation_shows_no_hebrew(self):
        if 'e2e-en' not in self.state()['threads']:
            self.ok('new', 'e2e-en', 'An English thread', '--state', 'on-owner', '--note', 'Pick one', '--by', 'e2e')
            self.ok('say', 'e2e-en', '--from', 'fork', '-', '--state', 'working', '--note', 'Building', '--by', 'e2e', input='Hello **world**')
            self.ok('task', 'add', 'e2e-en', 'Write the tests', '--owner', 'fork')
            self.ok('ask', 'e2e-en', 'Ship it?', '--options', 'Yes,No', '--from', 'fork')
        page = (self.board / 'suda.html').read_text(encoding='utf-8')
        self.assertIn('<html lang="en" dir="ltr">', page)
        for size in (SIZES[2], SIZES[0]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-en', 'An English thread')
                time.sleep(0.5)
                self.assertEqual(self.browser.eval(SCAN), [], 'Hebrew in the English page (%s)' % size[0])
                for opener, shown in (('(()=>{openSwitcher();return "ok"})()', '#switcher'), ('(()=>{showHelp();return "ok"})()', '#help'),
                                      ('(()=>{openNotify();return "ok"})()', '#notify')):
                    self.browser.eval(opener)
                    self.browser.wait('JSON.stringify(!document.querySelector(%r).hidden)' % shown, what=shown)
                    time.sleep(0.4)
                    self.assertEqual(self.browser.eval(SCAN), [], 'Hebrew in %s of the English page (%s)' % (shown, size[0]))
                    self.browser.press('Escape')
                    time.sleep(0.3)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in EnglishPage.__dict__:
        setattr(EnglishPage, _name, None)


if __name__ == '__main__':
    unittest.main()
