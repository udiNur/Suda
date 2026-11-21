"""Hostile review: what the translation and the summary write beside a note.

- foo.he.md that he wrote himself (no MDS marker) is overwritten by translating foo.md.
- foo.md and foo.markdown share foo.he.md, .foo.he.trans.json and .foo.summary.json: translating one wipes the other.
- A private note (0600) gets a world-readable translation and summary (0644).
- The folder of the note is swapped for a symlink while the model works: the files land outside the root.
Safe outcomes asserted below."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, model, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class Writes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.base = base
        cls.root = base / 'root'
        cls.root.mkdir()
        (base / 'roots.json').write_text('{"roots": []}')
        cls.cfg = server.Config(base / 'roots.json', [cls.root], base, set())
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, cls.cfg)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def post(self, what, path, force=False):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        c.request('POST', '/mdv/api/' + what, body=json.dumps({'path': str(path), 'force': force}),
                  headers={'Host': '127.0.0.1:%d' % self.port, 'Content-Type': 'application/json'})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_hand_written_sibling_is_not_overwritten(self):
        src = self.root / 'plan.md'
        src.write_text('# Plan\n\nAn English note about the plan.\n')
        mine = self.root / 'plan.he.md'
        own = '# התוכנית שלי\n\nפתק שכתבתי בעצמי, לא תרגום.\n'
        mine.write_text(own)
        self.post('translate', src)
        self.assertEqual(mine.read_text(), own, 'translating plan.md overwrote his own plan.he.md (no MDS marker)')

    def test_md_and_markdown_twins_do_not_share_a_translation(self):
        a = self.root / 'twin.md'
        b = self.root / 'twin.markdown'
        a.write_text('# Twin A\n\nThe first twin.\n')
        b.write_text('# Twin B\n\nThe second twin.\n')
        self.post('translate', a)
        self.post('translate', b)
        tr_a = core.sibling_path(a, 'he')
        self.assertIn('The first twin', tr_a.read_text(),
                      'translating twin.markdown replaced the translation of twin.md')

    def test_private_note_gets_private_sidecars(self):
        src = self.root / 'private.md'
        src.write_text('# Private\n\nSalary numbers and other secrets.\n')
        os.chmod(src, 0o600)
        self.post('translate', src)
        self.post('summary', src)
        for p in (core.sibling_path(src, 'he'), core.state_path(src, 'he'), core.summary_path(src)):
            mode = stat.S_IMODE(os.stat(p).st_mode)
            self.assertEqual(mode & 0o077, 0, '%s of a 0600 note is %o (readable by others)' % (p.name, mode))

    def test_parent_swapped_for_symlink_during_translation_writes_nothing_outside(self):
        sub = self.root / 'swap'
        sub.mkdir()
        note = sub / 'n.md'
        note.write_text('# Swap\n\nA note that will move.\n')
        outside = self.base / 'outside-target'
        outside.mkdir()
        entered, go = threading.Event(), threading.Event()
        real_stream = model.stream

        def gated(system, messages, *a, **k):
            entered.set()
            go.wait(10)
            yield from real_stream(system, messages, *a, **k)

        model.stream = gated
        try:
            t = threading.Thread(target=self.post, args=('translate', note))
            t.start()
            self.assertTrue(entered.wait(10), 'the model was never called')
            sub.rename(self.root / 'swap-old')
            sub.symlink_to(outside, target_is_directory=True)
            go.set()
            t.join(20)
        finally:
            go.set()
            model.stream = real_stream
        written = sorted(p.name for p in outside.iterdir())
        self.assertEqual(written, [], 'the translation was written outside the root, in %s: %s' % (outside, written))

    def test_summary_parent_swapped_for_symlink_writes_nothing_outside(self):
        sub = self.root / 'swap2'
        sub.mkdir()
        note = sub / 'n.md'
        note.write_text('# Swap\n\nA note that will move.\n')
        outside = self.base / 'outside-target2'
        outside.mkdir()
        entered, go = threading.Event(), threading.Event()
        real_stream = model.stream

        def gated(system, messages, *a, **k):
            entered.set()
            go.wait(10)
            yield from real_stream(system, messages, *a, **k)

        model.stream = gated
        try:
            t = threading.Thread(target=self.post, args=('summary', note))
            t.start()
            self.assertTrue(entered.wait(10), 'the model was never called')
            sub.rename(self.root / 'swap2-old')
            sub.symlink_to(outside, target_is_directory=True)
            go.set()
            t.join(20)
        finally:
            go.set()
            model.stream = real_stream
        written = sorted(p.name for p in outside.iterdir())
        self.assertEqual(written, [], 'the summary was written outside the root: %s' % written)


if __name__ == '__main__':
    unittest.main()
