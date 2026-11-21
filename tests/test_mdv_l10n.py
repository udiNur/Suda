"""The MD Viewer in the installation's language (the English release): its code says everything in English, through
Suda's tr(); an installation in Hebrew gets the words it had before, from locales/ (Suda's locales/he.json for the
words the two share, locales/mdv/he.json for the viewer's own), written beside the viewer by `threads install`
(sync.localize) and read by mdv/l10n.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, l10n, model, server, sync  # noqa: E402
from mdv.testing import REPO, free_port, prepare  # noqa: E402
prepare()

HEBREW = re.compile('[֐-׿]')
MDV = REPO / 'mdv'
SUDA_HE = json.loads((REPO / 'locales' / 'he.json').read_text(encoding='utf-8'))
MDV_HE = json.loads((REPO / 'locales' / 'mdv' / 'he.json').read_text(encoding='utf-8'))
# master's summary instructions, before the English release (its sha256): a Hebrew installation sends the same
MASTER_PROMPT_SHA = '5dc14813da5ac2958f561911700931054d03ad940819e1493ac6a4f965783064'


def keys_of(js: str) -> set:
    return {m.group(1).replace("\\'", "'") for m in re.finditer(r"\btr(?:Nodes)?\('((?:[^'\\]|\\.)*)'", js)}


class Source(unittest.TestCase):
    def test_the_viewer_holds_no_hebrew(self):
        """Every word a person reads is English in the code (the Hebrew keyboard's keys and the Hebrew letters'
        range are written as escapes); the samples are English too."""
        files = [p for p in MDV.rglob('*') if p.is_file() and 'vendor' not in p.parts and p.suffix in ('.py', '.js', '.html', '.css', '.md')
                 and p.name not in sync.NAMES]
        self.assertTrue(any(p.name == 'app.js' for p in files))
        hits = ['%s:%d' % (p.relative_to(REPO), n) for p in files
                for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) if HEBREW.search(line)]
        self.assertEqual(hits, [])

    def test_the_page_starts_english_and_left_to_right(self):
        page = (MDV / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<html lang="en" dir="ltr">', page)
        self.assertLess(page.index('static/l10n.js'), page.index('static/suda-pure.js'), 'the language is named before Suda\'s tr() reads it')

    def test_every_word_has_its_hebrew(self):
        app = (MDV / 'static' / 'app.js').read_text(encoding='utf-8')
        page = (MDV / 'static' / 'index.html').read_text(encoding='utf-8')
        words = keys_of(app)
        for m in re.finditer(r'<[^>]*data-t-attrs="([^"]+)"[^>]*>', page):
            for attr in m.group(1).split():
                words.add(re.search(r'\b%s="([^"]*)"' % re.escape(attr), m.group(0)).group(1))
        self.assertGreater(len(words), 60)
        missing = sorted(w for w in words if w not in SUDA_HE and w not in MDV_HE and w != 'English')
        self.assertEqual(missing, [])
        self.assertIn(core.SUMMARY_SYSTEM, MDV_HE)

    def test_a_word_both_tables_hold_says_the_same(self):
        self.assertEqual({k: (SUDA_HE[k], v) for k, v in MDV_HE.items() if k in SUDA_HE and SUDA_HE[k] != v}, {})

    def test_hebrew_as_before(self):
        """A few of the viewer's words, and the summary's instructions, exactly as master said them."""
        for en, he in (('One under the other', 'זה מתחת לזה'), ('Summary (S)', 'סיכום בעברית (S)'),
                       ('The original changed: {n} blocks to translate', 'המקור השתנה: {n} בלוקים לתרגום'),
                       ('Only .md files open here', 'אפשר לפתוח כאן רק קובצי ‎.md'), ('HE', 'עב'),
                       ('Translate into English', 'תרגם לאנגלית')):
            self.assertEqual(MDV_HE.get(en, SUDA_HE.get(en)), he, en)
        self.assertEqual(hashlib.sha256(MDV_HE[core.SUMMARY_SYSTEM].encode('utf-8')).hexdigest(), MASTER_PROMPT_SHA)


class Installed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.viewer = Path(self.tmp.name) / 'mdv'
        (self.viewer / 'static').mkdir(parents=True)
        sync.write(self.viewer / 'static', REPO / 'suda.html')
        for name in ('app.js', 'mdv-pure.js', 'index.html'):
            shutil.copyfile(MDV / 'static' / name, self.viewer / 'static' / name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.environ.pop, 'MDV_L10N', None)

    def test_english_writes_nothing(self):
        (self.viewer / sync.L10N_NAME).write_text('{"lang": "he"}')
        sync.localize(self.viewer, 'en', REPO / 'locales')
        self.assertFalse((self.viewer / sync.L10N_NAME).exists(), 'an installation back in English forgets the old table')
        os.environ['MDV_L10N'] = str(self.viewer / sync.L10N_NAME)
        self.assertEqual(l10n.settings(), l10n.ENGLISH)
        self.assertEqual(l10n.tr(core.SUMMARY_SYSTEM), core.SUMMARY_SYSTEM)

    def test_hebrew(self):
        sync.localize(self.viewer, 'he', REPO / 'locales')
        got = json.loads((self.viewer / sync.L10N_NAME).read_text(encoding='utf-8'))
        self.assertEqual((got['lang'], got['dir']), ('he', 'rtl'))
        self.assertEqual(got['table']['Copy'], SUDA_HE['Copy'], "Suda's own word the viewer uses")
        self.assertEqual(got['table']['Exit full screen'], 'יציאה ממסך מלא')
        unused = next(k for k in SUDA_HE if not k.startswith('_') and len(k) > 40 and k not in json.dumps(got) and
                      k not in ''.join(p.read_text(encoding='utf-8') for p in (self.viewer / 'static').glob('*.js')))
        self.assertNotIn(unused, got['table'], 'only the words the viewer says')
        os.environ['MDV_L10N'] = str(self.viewer / sync.L10N_NAME)
        self.assertEqual(l10n.html_tag(), '<html lang="he" dir="rtl">')
        self.assertTrue(l10n.script().startswith(b'var MDV_LANG="he",MDV_DIR="rtl",MDV_L10N={'))
        self.assertNotIn(b'<', l10n.script())
        self.assertEqual(hashlib.sha256(l10n.tr(core.SUMMARY_SYSTEM).encode('utf-8')).hexdigest(), MASTER_PROMPT_SHA)

    def test_a_broken_file_is_english(self):
        os.environ['MDV_L10N'] = str(self.viewer / 'nothing.json')
        self.assertEqual(l10n.settings(), l10n.ENGLISH)
        (self.viewer / 'bad.json').write_text('{"lang": "../x", "table": {"Copy": "x"}}')
        os.environ['MDV_L10N'] = str(self.viewer / 'bad.json')
        self.assertEqual(l10n.settings(), l10n.ENGLISH)

    @unittest.skipUnless(shutil.which('node'), 'node')
    def test_suda_tr_speaks_the_installation_language_in_the_viewer(self):
        """suda-pure.js as the viewer gets it reads the language l10n.js names; without l10n.js it is English."""
        pure = (self.viewer / 'static' / 'suda-pure.js').read_text(encoding='utf-8')
        self.assertIn(sync.VIEWER_LANG, pure, "suda.html's pure section names its language as sync.PURE_LANG says")
        sync.localize(self.viewer, 'he', REPO / 'locales')
        os.environ['MDV_L10N'] = str(self.viewer / sync.L10N_NAME)
        probe = "console.log(JSON.stringify([LANG,tr('Copy'),tr('Exit full screen')]));"
        he = subprocess.run(['node', '-e', l10n.script().decode('utf-8') + pure + probe], capture_output=True, text=True)
        self.assertEqual(json.loads(he.stdout), ['he', 'העתק', 'יציאה ממסך מלא'], he.stderr[-600:])
        en = subprocess.run(['node', '-e', pure + probe], capture_output=True, text=True)
        self.assertEqual(json.loads(en.stdout), ['en', 'Copy', 'Exit full screen'], en.stderr[-600:])


class Served(unittest.TestCase):
    """The page, l10n.js and the summary, over HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        (cls.root / 'a.md').write_text('# A note\n\nShort.\n')
        (base / 'roots.json').write_text('{"roots": []}')
        viewer = base / 'mdv'
        (viewer / 'static').mkdir(parents=True)
        sync.write(viewer / 'static', REPO / 'suda.html')
        for name in ('app.js', 'mdv-pure.js', 'index.html'):
            shutil.copyfile(MDV / 'static' / name, viewer / 'static' / name)
        sync.localize(viewer, 'he', REPO / 'locales')
        cls.he = str(viewer / sync.L10N_NAME)
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, server.Config(base / 'roots.json', [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def tearDown(self):
        os.environ.pop('MDV_L10N', None)

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:%d' % self.port} if body is not None else {})
        r = c.getresponse()
        return r.status, r.read()

    def test_english_by_default(self):
        st, page = self.req('GET', '/mdv/?path=x')
        self.assertEqual(st, 200)
        self.assertIn(b'<html lang="en" dir="ltr">', page)
        st, js = self.req('GET', '/mdv/static/l10n.js')
        self.assertEqual((st, js), (200, b'var MDV_LANG="en",MDV_DIR="ltr",MDV_L10N={};\n'))

    def test_hebrew_installation(self):
        os.environ['MDV_L10N'] = self.he
        st, page = self.req('GET', '/mdv/?path=x')
        self.assertIn(b'<html lang="he" dir="rtl">', page)
        st, js = self.req('GET', '/mdv/static/l10n.js')
        self.assertIn('"One under the other":"זה מתחת לזה"', js.decode('utf-8'))

    def test_the_summary_is_asked_in_the_installation_language(self):
        seen = []
        real = model.stream

        def spy(system, messages, max_tokens=None):
            seen.append(system)
            return real(system, messages, max_tokens) if max_tokens is not None else real(system, messages)
        model.stream = spy
        try:
            for lang in ('en', 'he'):
                if lang == 'he':
                    os.environ['MDV_L10N'] = self.he
                st, out = self.req('POST', '/mdv/api/summary', {'path': str(self.root / 'a.md'), 'force': True})
                self.assertEqual(st, 200, out)
        finally:
            model.stream = real
        self.assertEqual(seen[0], core.SUMMARY_SYSTEM)
        self.assertEqual(hashlib.sha256(seen[1].encode('utf-8')).hexdigest(), MASTER_PROMPT_SHA)


if __name__ == '__main__':
    unittest.main()
