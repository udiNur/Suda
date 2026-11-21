"""Hostile review, round 2: the 30 s socket timeout is per read, so a client that sends one header line (or one
body byte for the drain in send()) a little faster than that holds its thread for as long as it likes, and
ThreadingHTTPServer still makes threads without a limit. Safe outcome: a request has an overall deadline. The
test shortens the per-read timeout to 1 s and drips a header line every 0.5 s."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import select
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class Drip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        (base / 'root').mkdir()
        (base / 'roots.json').write_text('{"roots": []}')
        cls.cfg = server.Config(base / 'roots.json', [base / 'root'], base, set())
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, cls.cfg)
        cls.srv.RequestHandlerClass.timeout = 1
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def drip(self, head):
        s = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        s.sendall(head)
        start = time.time()
        closed_at = None
        try:
            while time.time() - start < 6:
                r, _, _ = select.select([s], [], [], 0.5)
                if r and not s.recv(4096):
                    closed_at = time.time() - start
                    break
                if r:                      # an answer came: the server gave up on the request
                    closed_at = time.time() - start
                    break
                s.sendall(b'X-Drip: 1\r\n')
        except OSError:
            closed_at = time.time() - start
        finally:
            s.close()
        return closed_at

    def test_dripped_headers_are_cut_off(self):
        at = self.drip(b'GET /mdv/ HTTP/1.1\r\nHost: 127.0.0.1\r\n')
        self.assertIsNotNone(at, 'a client dripping one header line every 0.5 s held its thread for 6 s '
                                 '(per-read timeout 1 s, no overall deadline)')
        self.assertLess(at, 4)


if __name__ == '__main__':
    unittest.main()
