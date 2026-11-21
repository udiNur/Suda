"""The service over HTTP, on a free 127.0.0.1 port, with a stand-in model (no network, no key)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, server  # noqa: E402
from mdv.testing import SAMPLES, free_port, prepare  # noqa: E402
prepare()




class Service(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        (base / 'outside').mkdir()
        (base / 'outside' / 'secret.md').write_text('# secret\n')
        cfg = base / 'roots.json'
        cfg.write_text('{"roots": []}')
        cls.cfg = server.Config(cfg, [cls.root], base, {'192.0.2.10'})
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, cls.cfg)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.note = self.root / ('n%d.md' % id(self))
        self.note.write_text('# Title\n\nHello there\n\n```\ncode\n```\n')

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': '127.0.0.1:%d' % self.port}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if isinstance(body, dict) else body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def doc(self, path):
        st, _, data = self.req('GET', '/mdv/api/doc?path=' + quote(str(path)))
        return st, json.loads(data)

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], '127.0.0.1')

    def test_page_and_static(self):
        st, h, data = self.req('GET', '/mdv/?path=x')
        self.assertEqual(st, 200)
        self.assertIn("script-src 'self'", h['Content-Security-Policy'])
        self.assertIn(b'id="i-copy"', data)           # Suda's icons, inlined
        self.assertNotIn(b'@@ICONS@@', data)
        for name in server.STATIC_FILES:
            self.assertEqual(self.req('GET', '/mdv/static/' + name)[0], 200, name)
        self.assertEqual(self.req('GET', '/mdv/static/../server.py')[0], 404)
        self.assertEqual(self.req('GET', '/mdv/static/index.html')[0], 404)
        st, h, _ = self.req('GET', '/')
        self.assertEqual((st, h['Location']), (302, '/mdv/'))

    def test_static_is_compressed_and_a_slow_reader_is_not_cut(self):
        import gzip as gz
        st, h, data = self.req('GET', '/mdv/static/vendor/mermaid.min.js', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual((st, h.get('Content-Encoding')), (200, 'gzip'))
        self.assertEqual(gz.decompress(data), (server.STATIC / 'vendor/mermaid.min.js').read_bytes())
        # an answer that takes longer than the request deadline to read still arrives whole
        old = server.Handler.timeout
        self.srv.RequestHandlerClass.timeout = 1
        try:
            s = socket.create_connection(('127.0.0.1', self.port))
            s.sendall(b'GET /mdv/static/vendor/mermaid.min.js HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
            got = b''
            while True:
                time.sleep(0.02)                 # 85 reads: well past the 1 s deadline
                b = s.recv(65536)
                if not b:
                    break
                got += b
            s.close()
        finally:
            self.srv.RequestHandlerClass.timeout = old
        self.assertGreater(len(got), 5_000_000)

    def test_doc(self):
        st, j = self.doc(self.note)
        self.assertEqual(st, 200)
        self.assertEqual(j['blocks'], ['# Title', 'Hello there', '```\ncode\n```'])
        self.assertEqual((j['lang'], j['tr_lang']), ('en', 'he'))
        self.assertEqual(j['translation'], {'exists': False})
        self.assertTrue(j['path'].startswith('~/root/'))
        self.assertTrue(j['can_translate'])

    def test_doc_shows_the_path_as_asked(self):
        alias = self.base / 'alias'
        if not alias.exists():
            alias.symlink_to(self.root)
        st, j = self.doc('~/alias/' + self.note.name)
        self.assertEqual((st, j['path'], j['dir']), (200, '~/alias/' + self.note.name, '~/alias'))

    def test_doc_by_home_path(self):
        st, j = self.doc('~/root/' + self.note.name)
        self.assertEqual((st, j['name']), (200, self.note.name))

    def test_refusals(self):
        self.assertEqual(self.doc(self.base / 'outside/secret.md')[0], 403)
        self.assertEqual(self.doc(str(self.root) + '/../outside/secret.md')[0], 403)
        self.assertEqual(self.doc(self.root / 'none.md')[0], 404)
        self.assertEqual(self.doc('/etc/passwd')[0], 400)
        self.assertEqual(self.doc('')[0], 404)
        link = self.root / 'link.md'
        if not link.exists():
            link.symlink_to(self.base / 'outside/secret.md')
        st, j = self.doc(link)
        self.assertEqual((st, j['error']), (403, 'outside'))
        self.assertNotIn('secret', json.dumps(j))

    def test_host_guard(self):
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'evil.example.com'})[0], 403)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'evil.example.com:%d' % self.port})[0], 403)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': '192.0.2.10:8767'})[0], 200)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'localhost:%d' % self.port})[0], 200)

    def test_write_guard(self):
        body = {'path': str(self.note)}
        self.assertEqual(self.req('POST', '/mdv/api/translate', body, {'Origin': 'http://evil.example.com'})[0], 403)
        self.assertEqual(self.req('POST', '/mdv/api/translate', body, {'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.req('POST', '/mdv/api/summary', body, {'Sec-Fetch-Site': 'same-site'})[0], 403)
        # a form post (no JSON type) is refused: only a script on the same page can send JSON
        st = self.req('POST', '/mdv/api/summary', json.dumps(body), {'Content-Type': 'text/plain'})[0]
        self.assertEqual(st, 403)
        self.assertFalse(core.sibling_path(self.note, 'he').exists())
        self.assertFalse(core.summary_path(self.note).exists())

    def test_translate_streams_saves_and_is_incremental(self):
        st, h, data = self.req('POST', '/mdv/api/translate', {'path': str(self.note)},
                               {'Origin': 'http://127.0.0.1:%d' % self.port})
        self.assertEqual(st, 200)
        lines = [json.loads(x) for x in data.decode().splitlines()]
        self.assertEqual(lines[0]['start'], True)
        self.assertEqual(lines[-1], {'done': True, 'sent': 2, 'reused': 0, 'failed': []})
        sib = core.sibling_path(self.note, 'he')
        self.assertIn('Hello there [HE]', sib.read_text())
        st, j = self.doc(self.note)
        self.assertTrue(j['translation']['aligned'])
        self.assertEqual(j['translation']['stale'], 0)
        self.note.write_text('# Title\n\nHello again\n\n```\ncode\n```\n')
        st, j = self.doc(self.note)
        self.assertEqual(j['translation']['stale'], 1)
        self.assertTrue(j['translation']['blocks'][1]['stale'])
        data = self.req('POST', '/mdv/api/translate', {'path': str(self.note)})[2]
        last = json.loads(data.decode().splitlines()[-1])
        self.assertEqual((last['sent'], last['reused']), (1, 2))   # the heading and the code block

    def test_opening_a_translation_opens_its_original(self):
        self.req('POST', '/mdv/api/translate', {'path': str(self.note)})
        st, j = self.doc(core.sibling_path(self.note, 'he'))
        self.assertEqual(j, {'ok': True, 'original': '~/root/' + self.note.name})
        st, _, data = self.req('POST', '/mdv/api/translate', {'path': str(core.sibling_path(self.note, 'he'))})
        self.assertEqual(st, 400)

    def test_summary_is_saved_and_reused(self):
        st, _, data = self.req('POST', '/mdv/api/summary', {'path': str(self.note)})
        j = json.loads(data)
        self.assertEqual((st, j['cached']), (200, False))
        self.assertTrue(core.summary_path(self.note).is_file())
        j = json.loads(self.req('POST', '/mdv/api/summary', {'path': str(self.note)})[2])
        self.assertTrue(j['cached'])
        st, d = self.doc(self.note)
        self.assertEqual(d['summary']['stale'], False)
        self.note.write_text('# Other\n')
        self.assertTrue(self.doc(self.note)[1]['summary']['stale'])

    def test_events_say_change(self):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('GET', '/mdv/api/events?path=' + quote(str(self.note)), headers={'Host': '127.0.0.1'})
        r = c.getresponse()
        self.assertEqual(r.getheader('Content-Type'), 'text/event-stream; charset=utf-8')
        self.assertEqual(r.fp.readline(), b'retry: 2000\n')
        r.fp.readline()
        time.sleep(0.5)
        self.note.write_text('# changed\n')
        self.assertEqual(r.fp.readline(), b'event: change\n')
        c.close()

    def test_follow_without_job(self):
        st, _, data = self.req('GET', '/mdv/api/translate?path=' + quote(str(self.note)))
        self.assertEqual(st, 404)

    def test_body_limits(self):
        st = self.req('POST', '/mdv/api/summary', '{"path": "' + 'x' * 70000 + '"}')[0]
        self.assertEqual(st, 413)
        self.assertEqual(self.req('POST', '/mdv/api/summary', 'not json')[0], 400)
        self.assertEqual(self.req('POST', '/mdv/api/summary', '[1]')[0], 400)


if __name__ == '__main__':
    unittest.main()
