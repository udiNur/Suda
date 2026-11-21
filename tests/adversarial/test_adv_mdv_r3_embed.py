"""Hostile review, round 3: the viewer inside a host server (web.handle).

The viewer's own whole-request deadline (Handler.setup starts it) never starts in embedded mode: web.Request skips
__init__/setup. What is left is the host's per-read socket timeout, so a POST to /mdv/ whose body comes one byte at
a time (or a GET whose Content-Length the drain in send() then waits for) holds a host thread for as long as the
client likes. Safe outcome: the viewer's deadline also holds when embedded. The host here is shaped like the board
server (SimpleHTTPRequestHandler, timeout 1 s here instead of 30 s, so the test is quick)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import select
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import web  # noqa: E402
from mdv.testing import free_port, prepare  # noqa: E402
prepare()


class EmbeddedDeadline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        root = base / 'root'
        root.mkdir()
        cls.note = root / 'n.md'
        cls.note.write_text('# n\n\nwords\n')
        (base / 'site').mkdir()
        (base / 'roots.json').write_text('{"roots": []}')
        cfg = web.config(roots_json=base / 'roots.json', extra_roots=[root], home=base)
        site = str(base / 'site')

        class Host(SimpleHTTPRequestHandler):
            timeout = 1

            def __init__(self, *a, **k):
                super().__init__(*a, directory=site, **k)

            def log_message(self, *a):
                pass

            def do_GET(self):
                if web.owns(urlparse(self.path).path):
                    return web.handle(self, cfg)
                return super().do_GET()

            def do_POST(self):
                if web.owns(urlparse(self.path).path):
                    return web.handle(self, cfg)
                self.send_error(404)

        cls.port = free_port()
        cls.srv = ThreadingHTTPServer(('127.0.0.1', cls.port), Host)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def drip(self, head, seconds=6):
        s = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        s.sendall(head)
        start = time.time()
        try:
            while time.time() - start < seconds:
                r, _, _ = select.select([s], [], [], 0.5)
                if r:
                    return time.time() - start
                s.sendall(b' ')
        except OSError:
            return time.time() - start
        finally:
            s.close()
        return None

    def test_a_dripped_post_body_is_cut_off(self):
        head = (b'POST /mdv/api/summary HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n'
                b'Content-Length: 4000\r\n\r\n')
        at = self.drip(head)
        self.assertIsNotNone(at, 'a POST body dripped a byte every 0.5 s held the host thread for 6 s (host per-read '
                                 'timeout 1 s; the viewer deadline is not running when embedded)')
        self.assertLess(at, 4)

    def test_a_get_whose_body_never_ends_is_cut_off(self):
        head = b'GET /mdv/api/doc?path=x HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 4000\r\n\r\n'
        at = self.drip(head)
        self.assertIsNotNone(at, 'the drain in send() waited 6 s on a dripped GET body')
        self.assertLess(at, 4)


if __name__ == '__main__':
    unittest.main()
