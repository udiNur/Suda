#!/usr/bin/env python3
"""The README and its translations stay in step (the owner, suda m684: "translated versions, always").

README.md is the source. Every README.<lang>.md beside it must hold the same skeleton: the same pictures in the same
order, the same code blocks byte for byte (a `text` chat or a `mermaid` diagram may be translated, line for line),
the same sections with the same anchors, the same links, the same badges, and the language row as one identical
line in every file. A change to the English that is not carried into a translation fails here.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
from pathlib import Path
import re
import unittest

ROOT = _paths.REPO
SOURCE = ROOT / 'README.md'
FENCE = re.compile(r'^```([^\n`]*)\n(.*?)^```', re.M | re.S)


def translations():
    return sorted(p for p in ROOT.glob('README.*.md') if re.fullmatch(r'README\.[a-z]{2}(?:-[A-Z]{2})?\.md', p.name))


def skeleton(text):
    blocks = [(lang.strip(), body if lang.strip() not in ('text', 'mermaid') else body.count('\n')) for lang, body in FENCE.findall(text)]
    prose = FENCE.sub('', text)
    return {
        'pictures': re.findall(r'<img[^>]*\ssrc="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)', prose),
        'code blocks': blocks,
        'sections': [len(m) for m in re.findall(r'^(#{2,3}) ', prose, re.M)],
        'anchors': re.findall(r'<a name="([^"]+)"', prose),
        'links': [h for h in re.findall(r'href="([^"]+)"|\]\(([^)\s]+)\)', prose)],
        'language rows': [line for line in prose.splitlines() if 'href="README.md"' in line and 'href="README.he.md"' in line],
    }


class Readmes(unittest.TestCase):
    def test_the_languages_the_owner_chose_are_there(self):
        """English, Hebrew, and every language of herdr's README (suda m697: Simplified Chinese; Japanese), and Korean, Brazilian Portuguese and Spanish (suda m798)."""
        self.assertEqual([p.name for p in translations()], ['README.es.md', 'README.he.md', 'README.ja.md', 'README.ko.md', 'README.pt-BR.md', 'README.zh-CN.md'])

    def test_every_translation_has_the_skeleton_of_the_english(self):
        english = skeleton(SOURCE.read_text(encoding='utf-8'))
        self.assertTrue(english['pictures'] and english['code blocks'] and english['anchors'])
        self.assertEqual(len(english['language rows']), 1, 'README.md: one language row')
        for path in translations():
            other = skeleton(path.read_text(encoding='utf-8'))
            for part, want in english.items():
                with self.subTest(file=path.name, part=part):
                    got = other[part]
                    if part == 'links':      # a translation adds one link back to the English it was made from
                        got = [x for x in got if x != ('README.md', '') and x != ('', 'README.md')]
                        want = [x for x in want if x != ('README.md', '') and x != ('', 'README.md')]
                    self.assertEqual(got, want, '%s: its %s differ from README.md' % (path.name, part))

    def test_the_site_is_one_english_page_that_asks_nothing_from_elsewhere(self):
        """docs/index.html (GitHub Pages): no script, style, font or picture from another server, no tracking; links
        out are allowed (GitHub). English, with the translations linked."""
        page = (ROOT / 'docs/index.html').read_text(encoding='utf-8')
        loads = re.findall(r'<(?:script|img|iframe|source|video|audio)\b[^>]*\ssrc="(https?:)?//', page, re.I)
        loads += re.findall(r'<link\b(?=[^>]*\srel="(?:stylesheet|icon|preload|modulepreload|manifest|apple-touch-icon)")[^>]*\shref="(https?:)?//', page, re.I)   # (a canonical link loads nothing)
        self.assertEqual(loads, [], 'the site loads something from another server')
        self.assertNotRegex(page, r'url\(\s*["\']?(?:https?:)?//', 'a CSS url() to another server')
        self.assertNotRegex(page, r'@import|googletagmanager|analytics|gtag\(')
        self.assertNotRegex(page, '[\u0590-\u05ff]', 'the site is English (the translations are linked)')
        for name in ('README.he.md', 'README.zh-CN.md', 'README.ja.md', 'README.ko.md', 'README.pt-BR.md', 'README.es.md'):
            self.assertIn(name, page)
        for src in re.findall(r'<img[^>]*\ssrc="([^"]+)"', page):
            if not src.startswith('data:'):
                self.assertTrue((ROOT / 'docs' / src).is_file(), 'a picture the site names is missing: ' + src)

    def test_the_language_row_names_every_file(self):
        row = skeleton(SOURCE.read_text(encoding='utf-8'))['language rows'][0]
        for path in [SOURCE, *translations()]:
            self.assertIn('href="%s"' % path.name, row)


if __name__ == '__main__':
    unittest.main()
