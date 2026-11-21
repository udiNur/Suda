"""Hostile review, round 5 (suda-fixes task 45): GET /mdv/api/asset.

- Any site the reader visits can show his pictures in its own page: `<img src="http://127.0.0.1:PORT/mdv/api/asset?
  path=~/Documents/mds/...png">` passes the Host check (the Host is the viewer's own) and the answer carries no
  Cross-Origin-Resource-Policy, so it loads. The page learns which pictures exist and their sizes (onload,
  naturalWidth), path by guessed path, and can draw them. Before this, every GET answered JSON or a stream, which a
  foreign page cannot use. Safe outcome: a cross-site picture request is refused, or the answer says CORP
  same-origin.
- Each request reads the whole picture (up to 25 MB) into memory, with no limit on how many at once: a page with
  100 <img> to one big picture (any site can write that, see above) holds 2.5 GB. Safe outcome: reads at once are
  capped (the test allows 4).
Stand-in model, temp folders, 127.0.0.1."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
MDV = _paths.APP / 'mdv'
sys.path.insert(0, str(MDV))
from mdv import core, server  # noqa: E402
from mdv.testing import free_port, prepare  # noqa: E402
prepare()

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82')


class Asset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        cls.pic = cls.root / 'shot.png'
        cls.pic.write_bytes(PNG)
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

    def get(self, path, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': '127.0.0.1:%d' % self.port}
        h.update(headers or {})
        c.request('GET', '/mdv/api/asset?path=' + quote(str(path)), headers=h)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}

    def test_a_foreign_page_cannot_load_his_pictures(self):
        st, h = self.get(self.pic, {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors',
                                    'Sec-Fetch-Dest': 'image', 'Referer': 'https://evil.example/'})
        self.assertFalse(st == 200 and h.get('cross-origin-resource-policy') not in ('same-origin', 'same-site'),
                         'a cross-site <img> gets his picture: %s, CORP %r' % (st, h.get('cross-origin-resource-policy')))

    def test_picture_reads_at_once_are_capped(self):
        peak, now, lock, go = [0], [0], threading.Lock(), threading.Event()
        real = core.read_bytes_capped

        def held(path, cap):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            go.wait(5)
            try:
                return real(path, cap)
            finally:
                with lock:
                    now[0] -= 1

        core.read_bytes_capped = held
        try:
            ths = [threading.Thread(target=self.get, args=(self.pic,)) for _ in range(10)]
            for t in ths:
                t.start()
            time.sleep(1.5)
            seen = peak[0]
            go.set()
            for t in ths:
                t.join(20)
        finally:
            go.set()
            core.read_bytes_capped = real
        self.assertLessEqual(seen, 4, '%d whole-picture reads (up to 25 MB each) ran at once' % seen)


if __name__ == '__main__':
    unittest.main()
