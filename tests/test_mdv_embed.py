"""The viewer inside another server (Suda's board server, suda-fixes m149): a host handler shaped like
answer_server.py's (SimpleHTTPRequestHandler serving its own files) hands /mdv/* to web.handle and serves the
rest itself. What must hold: the viewer works there with its guards, and a viewer that raises answers 503 on
/mdv/ only while the host goes on serving its own pages. (A module that does not import is the host's own
fallback, tested in the board server's repo.)"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, web  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Embedded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        (base / 'site').mkdir()
        (base / 'site' / 'index.html').write_text('<p>host home</p>')
        (base / 'roots.json').write_text('{"roots": []}')
        cfg = web.config(roots_json=base / 'roots.json', extra_roots=[cls.root], home=base,
                         allow_hosts={'192.0.2.10'})
        site = str(base / 'site')

        class Host(SimpleHTTPRequestHandler):
            timeout = 30

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

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': '127.0.0.1:%d' % self.port}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_owns_only_its_prefix(self):
        self.assertTrue(web.owns('/mdv/'))
        self.assertTrue(web.owns('/mdv/api/doc'))
        self.assertFalse(web.owns('/mdv'))
        self.assertFalse(web.owns('/mdvx/'))
        self.assertFalse(web.owns('/md-viewer/assets/mockup.html'))
        self.assertFalse(web.owns('/threads/suda.html'))

    def test_the_viewer_works_inside_the_host(self):
        note = self.root / 'a.md'
        note.write_text('# Title\n\nHello\n')
        self.assertEqual(self.req('GET', '/mdv/?path=x')[0], 200)
        st, data = self.req('GET', '/mdv/api/doc?path=' + quote(str(note)))
        self.assertEqual((st, json.loads(data)['blocks']), (200, ['# Title', 'Hello']))
        st, data = self.req('POST', '/mdv/api/translate', {'path': str(note)})
        self.assertEqual(json.loads(data.decode().splitlines()[-1])['sent'], 2)
        self.assertTrue(core.sibling_path(note, 'he').is_file())
        self.assertEqual(self.req('GET', '/index.html')[0], 200)       # and the host's own pages

    def test_the_guards_hold_inside_the_host(self):
        note = self.root / 'g.md'
        note.write_text('# g\n')
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'evil.example.com'})[0], 403)
        st, _ = self.req('POST', '/mdv/api/summary', {'path': str(note)}, {'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(st, 403)
        self.assertFalse(core.summary_path(note).exists())

    def test_a_viewer_that_breaks_answers_503_and_the_host_goes_on(self):
        real = web.Request.do_GET

        def boom(self):
            raise RuntimeError('viewer bug')
        web.Request.do_GET = boom
        try:
            self.assertEqual(self.req('GET', '/mdv/api/doc?path=x')[0], 503)
        finally:
            web.Request.do_GET = real
        self.assertEqual(self.req('GET', '/index.html')[0], 200)
        self.assertEqual(self.req('GET', '/mdv/?path=x')[0], 200)


if __name__ == '__main__':
    unittest.main()
