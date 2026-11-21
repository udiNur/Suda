"""Hostile review: the doc API tells whether a .md file exists anywhere on disk, outside the roots too
(404 "missing" for an absent one, 403 "outside" for a present one). Safe outcome: the same answer for both."""
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
from mdv import server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class Oracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.base = base
        root = base / 'root'
        root.mkdir()
        (base / 'elsewhere').mkdir()
        (base / 'elsewhere' / 'secret-project.md').write_text('# x\n')
        (base / 'roots.json').write_text('{"roots": []}')
        cls.cfg = server.Config(base / 'roots.json', [root], base, set())
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, cls.cfg)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def doc(self, path):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('GET', '/mdv/api/doc?path=' + quote(str(path)), headers={'Host': '127.0.0.1:%d' % self.port})
        r = c.getresponse()
        j = json.loads(r.read())
        c.close()
        return r.status, j.get('error')

    def test_outside_existing_and_absent_look_the_same(self):
        there = self.doc(self.base / 'elsewhere' / 'secret-project.md')
        absent = self.doc(self.base / 'elsewhere' / 'no-such-project.md')
        self.assertEqual(there, absent, 'existence of a file outside the roots leaks: %s vs %s' % (there, absent))


if __name__ == '__main__':
    unittest.main()
