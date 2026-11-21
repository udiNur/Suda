#!/usr/bin/env python3
"""Suda's own board server (server.py): what it serves, what it refuses, and the page's request through it."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = _paths.APP
CLI = ROOT / 'threads.py'


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-srv-', dir=ROOT)
        cls.root = Path(cls.tmp.name)
        cls.boards = cls.root / 'boards'
        cls.boards.mkdir()
        (cls.root / 'secret.txt').write_text('outside the boards')
        cls.env = dict(os.environ, BOARDS_DIR=str(cls.boards), THREADS_NOTIFY='0', THREADS_CONFIG_DIR=str(cls.root / 'config'))
        for key in ('THREADS_SLUG', 'THREADS_NOTIFY_CMD', 'TUIOS_PANE_ID'):
            cls.env.pop(key, None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (cls.root / 'config/threads').mkdir(parents=True)
        (cls.root / 'config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')
        r = subprocess.run([sys.executable, str(CLI), 'install'], env=cls.env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([sys.executable, str(CLI), 'new', 'topic', 'נושא', '--state', 'working', '--note', 'x', '--by', 'test'],
                           env=cls.env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        sys.path.insert(0, str(ROOT))
        cls.mod = importlib.import_module('server')
        cls.mod.bl.BOARDS_DIR = cls.boards
        os.environ['BOARDS_DIR'] = str(cls.boards)          # the hook the server runs inherits it
        os.environ['THREADS_NOTIFY'] = '0'
        os.environ['THREADS_CONFIG_DIR'] = str(cls.root / 'config')
        cls.server = cls.mod.Server(('127.0.0.1', 0), cls.mod.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Host': f'127.0.0.1:{self.port}', **(headers or {})}
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            if v is not None:
                c.putheader(k, v)
        data = body.encode('utf-8') if isinstance(body, str) else body
        if data is not None:
            c.putheader('Content-Length', str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        out = r.status, r.read(), dict(r.getheaders())
        c.close()
        return out

    def post(self, payload, **headers):
        h = {'Origin': f'http://127.0.0.1:{self.port}', 'Content-Type': 'application/json', **headers}
        return self.request('POST', '/api/state', json.dumps(payload), h)

    def test_it_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn("'0.0.0.0'", source)
        self.assertNotIn("('', ", source)

    def test_the_page_and_its_files_are_served(self):
        status, body, head = self.request('GET', '/threads/suda.html')
        self.assertEqual(status, 200)
        self.assertIn(b'<html', body[:200])
        self.assertIn('text/html', head['Content-Type'])
        status, body, head = self.request('GET', '/threads/summary.json')
        self.assertEqual((status, head['Content-Type']), (200, 'application/json; charset=utf-8'))
        self.assertEqual(self.request('HEAD', '/threads/suda.html')[1], b'')

    def test_nothing_outside_the_boards_and_no_dot_files_or_listings(self):
        (self.boards / 'threads' / 'link').symlink_to(self.root / 'secret.txt')
        for path in ('/../secret.txt', '/threads/../../secret.txt', '/%2e%2e/secret.txt', '/threads/%2e%2e/%2e%2e/secret.txt',
                     '/threads/.pulse', '/threads/.state.json.lock', '/threads/', '/threads', '/', '/threads/link',
                     '/threads/state\\..\\..\\secret.txt', '/threads/%00', '//etc/passwd', '/threads/nope.html'):
            with self.subTest(path=path):
                status, body, _ = self.request('GET', path)
                self.assertIn(status, (403, 404), path)
                self.assertNotIn(b'outside the boards', body)

    def test_the_board_store_is_never_served(self):
        """The board's truth is SQLite (suda.db, sqlite177): the store, its journal, its backups and its locks are the
        board's data, never a file the page reads."""
        board = self.boards / 'threads'
        self.assertTrue((board / 'suda.db').is_file(), 'the board has its store')
        for name in ('suda.db-wal', 'suda.db-shm', 'suda.db-journal', 'suda.db.bak-1763740000', 'store.lock'):
            if not (board / name).exists():             # (never over the store's own files: the other tests use it)
                (board / name).write_bytes(b'SQLite format 3\x00 the store')
        for path in ('/threads/suda.db', '/threads/suda.db-wal', '/threads/suda.db-shm', '/threads/suda.db-journal',
                     '/threads/suda.db.bak-1763740000', '/threads/store.lock', '/threads/SUDA.DB', '/threads/suda%2Edb'):
            with self.subTest(path=path):
                status, body, _ = self.request('GET', path)
                self.assertIn(status, (403, 404), path)
                self.assertNotIn(b'the store', body)
                self.assertNotIn(b'SQLite format 3', body)

    def test_another_host_name_is_refused(self):
        """DNS rebinding: a name that resolves to 127.0.0.1 is not this board."""
        for host in ('evil.example', 'evil.example:%d' % self.port, '127.0.0.1.evil.example'):
            with self.subTest(host=host):
                self.assertEqual(self.request('GET', '/threads/suda.html', headers={'Host': host})[0], 403)
                self.assertEqual(self.post({'board': 'threads', 'state': {'op': 'sweep'}}, Host=host)[0], 403)
        self.assertEqual(self.request('GET', '/threads/suda.html', headers={'Host': 'localhost:%d' % self.port})[0], 200)
        os.environ['SUDA_ALLOWED_HOSTS'] = 'suda.example.com'
        try:
            self.assertEqual(self.request('GET', '/threads/suda.html', headers={'Host': 'suda.example.com'})[0], 200)
        finally:
            del os.environ['SUDA_ALLOWED_HOSTS']

    def test_a_write_comes_only_from_the_same_address(self):
        """CSRF: another site's page (or none) cannot post."""
        for origin in (None, 'http://evil.example', 'null', f'http://127.0.0.1:{self.port + 1}', f'http://localhost:{self.port}'):
            with self.subTest(origin=origin):
                self.assertEqual(self.post({'board': 'threads', 'state': {'op': 'sweep'}}, Origin=origin)[0], 403)

    def test_the_page_request_reaches_the_cli_and_answers(self):
        status, body, _ = self.post({'board': 'threads', 'state': {'op': 'reply', 'thread': 'topic', 'text': 'שלום \ud83d', 'cid': 'c1', 'under': None}})
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertTrue(answer['ok'], answer)
        receipt = json.loads(answer['out'][-1])
        self.assertEqual((receipt['thread'], receipt['msg_id']), ('topic', 'm1'))
        state = json.loads((self.boards / 'threads/state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['threads']['topic']['messages'][0]['text'], 'שלום �')     # a lone half became U+FFFD

    def test_bad_requests(self):
        self.assertEqual(self.post({'board': '../x', 'state': {}})[0], 400)
        self.assertEqual(self.post({'board': '.hidden', 'state': {}})[0], 400)
        self.assertEqual(self.post({'board': 'nope', 'state': {}})[0], 400)      # only this server's one board
        self.assertEqual(self.post({'board': 'threads', 'state': []})[0], 400)
        self.assertEqual(self.request('POST', '/api/state', 'not json', {'Origin': f'http://127.0.0.1:{self.port}'})[0], 400)
        self.assertEqual(self.request('POST', '/api/other', '{}', {'Origin': f'http://127.0.0.1:{self.port}'})[0], 404)
        # too big: refused on its Content-Length, before a byte of the body is read
        import socket
        with socket.create_connection(('127.0.0.1', self.port), timeout=10) as sock:
            sock.sendall(('POST /api/state HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\n'
                          'Content-Length: 4000001\r\n\r\n{}' % (self.port, self.port)).encode())
            self.assertIn(b' 413 ', sock.recv(200).split(b'\r\n')[0] + b' ')


if __name__ == '__main__':
    unittest.main()
