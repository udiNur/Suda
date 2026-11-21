"""Hostile review: a refused POST leaves its body unread on a kept-alive connection, so the body is parsed as the
next request. A cross-site page can send any body with fetch(url, {method: 'POST', mode: 'no-cors', body}); if
that body is itself a JSON POST with no Origin and no Sec-Fetch-Site, the write guard is bypassed and a model call
runs and writes beside the note. Safe outcome: a refused request never lets its body run as a request."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class Smuggling(unittest.TestCase):
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

    def note(self, name):
        p = self.root / name
        p.write_text('# Title\n\nHello there\n')
        return p

    def inner(self, what, note):
        body = json.dumps({'path': str(note), 'force': True}).encode()
        return (b'POST /mdv/api/%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n'
                b'Content-Length: %d\r\n\r\n' % (what.encode(), self.port, len(body))) + body

    def send_raw(self, data, wait=3.0):
        s = socket.create_connection(('127.0.0.1', self.port), timeout=wait)
        s.sendall(data)
        got = b''
        end = time.time() + wait
        try:
            while time.time() < end:
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            pass
        s.close()
        return got

    def outer(self, smuggled, extra=b'', length=None):
        return (b'POST /mdv/api/summary HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n'
                b'Content-Type: text/plain;charset=UTF-8\r\n' % self.port + extra
                + b'Content-Length: %d\r\n\r\n' % (len(smuggled) if length is None else length)) + smuggled

    def test_cross_site_post_body_does_not_run_a_summary(self):
        note = self.note('cs-sum.md')
        raw = self.send_raw(self.outer(self.inner('summary', note),
                                       b'Origin: https://evil.example\r\nSec-Fetch-Site: cross-site\r\n'))
        self.assertIn(b'403', raw.split(b'\r\n', 1)[0])
        self.assertFalse(core.summary_path(note).exists(),
                         'the body of a refused cross-site POST ran as a second request: ' + repr(raw[-300:]))

    def test_cross_site_post_body_does_not_start_a_translation(self):
        note = self.note('cs-tr.md')
        self.send_raw(self.outer(self.inner('translate', note),
                                 b'Origin: https://evil.example\r\nSec-Fetch-Site: cross-site\r\n'))
        time.sleep(0.5)
        self.assertFalse(core.sibling_path(note, 'he').exists(),
                         'a cross-site page started a translation (model call and a file written)')

    def test_wrong_content_type_body_does_not_run(self):
        # a same-origin-looking form post, refused for its type only
        note = self.note('ct.md')
        self.send_raw(self.outer(self.inner('summary', note)))
        self.assertFalse(core.summary_path(note).exists())

    def test_oversized_body_does_not_run(self):
        note = self.note('big.md')
        smuggled = self.inner('summary', note)
        pad = b'X' * (server.MAX_BODY + 10 - len(smuggled))
        data = (b'POST /mdv/api/summary HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n'
                b'Content-Length: %d\r\n\r\n' % (self.port, len(smuggled) + len(pad))) + smuggled + pad
        self.send_raw(data)
        self.assertFalse(core.summary_path(note).exists(), 'the start of a refused 413 body ran as a request')

    def test_get_body_does_not_run(self):
        note = self.note('get.md')
        smuggled = self.inner('summary', note)
        data = (b'GET /mdv/api/doc?path=x HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Length: %d\r\n\r\n'
                % (self.port, len(smuggled))) + smuggled
        self.send_raw(data)
        self.assertFalse(core.summary_path(note).exists(), 'the body of a GET ran as a request')


if __name__ == '__main__':
    unittest.main()
