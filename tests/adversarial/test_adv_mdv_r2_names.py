"""Hostile review, round 2: sidecar names after "only .md is stripped".

- foo.markdown is translated to foo.markdown.he.md, which original_of does not know as a translation (it looks for
  foo.markdown.md): opening it does not lead to its original, and it can itself be translated and summarized.
- foo.markdown and foo.markdown.md share foo.markdown.he.md and both state files: one wipes the other's translation.
Safe outcomes asserted below."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
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

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Host': '127.0.0.1:%d' % self.port}
        if body is not None:
            h['Content-Type'] = 'application/json'
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_translation_of_a_markdown_file_is_known_as_one(self):
        src = self.root / 'guide.markdown'
        src.write_text('# Guide\n\nAn English guide.\n')
        self.req('POST', '/mdv/api/translate', {'path': str(src)})
        sib = core.sibling_path(src, 'he')
        self.assertTrue(sib.is_file(), sib)
        st, data = self.req('GET', '/mdv/api/doc?path=' + quote(str(sib)))
        self.assertIn('original', json.loads(data), 'opening %s does not lead to %s' % (sib.name, src.name))
        st, _ = self.req('POST', '/mdv/api/translate', {'path': str(sib)})
        self.assertEqual(st, 400, 'the translation %s was itself sent to the model' % sib.name)

    def test_markdown_and_markdown_md_do_not_share_a_translation(self):
        a = self.root / 'pair.markdown'
        b = self.root / 'pair.markdown.md'
        a.write_text('# Pair A\n\nThe first one.\n')
        b.write_text('# Pair B\n\nThe second one.\n')
        self.req('POST', '/mdv/api/translate', {'path': str(a)})
        self.req('POST', '/mdv/api/translate', {'path': str(b)})
        self.assertIn('The first one', core.sibling_path(a, 'he').read_text(),
                      'translating pair.markdown.md replaced the translation of pair.markdown')


if __name__ == '__main__':
    unittest.main()
