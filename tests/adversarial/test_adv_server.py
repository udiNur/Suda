#!/usr/bin/env python3
"""Hostile review of server.py: each test asserts the SECURE outcome (a FAIL is a real hole)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import importlib
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = _paths.APP
CLI = ROOT / 'threads.py'


class AdvServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.threads-adv-srv-', dir=ROOT)
        cls.root = Path(cls.tmp.name)
        cls.boards = cls.root / 'boards'
        cls.boards.mkdir()
        (cls.root / 'secret.txt').write_text('outside the boards')
        cls.env = dict(os.environ, BOARDS_DIR=str(cls.boards), THREADS_NOTIFY='0', THREADS_CONFIG_DIR=str(cls.root / 'config'))
        for key in ('THREADS_SLUG', 'THREADS_NOTIFY_CMD', 'TUIOS_PANE_ID', 'SUDA_ALLOWED_HOSTS'):
            cls.env.pop(key, None)
        r = subprocess.run([sys.executable, str(CLI), 'install'], env=cls.env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([sys.executable, str(CLI), 'new', 'topic', 'x', '--state', 'working', '--note', 'x', '--by', 'test'],
                           env=cls.env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # another (non-Suda) board in the same boards folder: an agent's HTML page and its own hook
        other = cls.boards / 'other'
        (other / 'assets').mkdir(parents=True)
        (other / 'assets' / 'proto.html').write_text('<script>fetch("/api/state",{method:"POST"})</script>')
        (other / 'on-state.sh').write_text(f'#!/bin/sh\ntouch {cls.root}/OTHER_HOOK_RAN\n')
        (other / 'on-state.sh').chmod(0o755)
        sys.path.insert(0, str(ROOT))
        cls.mod = importlib.import_module('server')
        cls.mod.bl.BOARDS_DIR = cls.boards
        os.environ['BOARDS_DIR'] = str(cls.boards)
        os.environ['THREADS_NOTIFY'] = '0'
        os.environ['THREADS_CONFIG_DIR'] = str(cls.root / 'config')
        os.environ.pop('SUDA_ALLOWED_HOSTS', None)
        cls.server = cls.mod.Server(('127.0.0.1', 0), cls.mod.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def raw(self, data, wait=10):
        with socket.create_connection(('127.0.0.1', self.port), timeout=wait) as s:
            s.sendall(data)
            out = b''
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    out += chunk
            except socket.timeout:
                pass
            return out

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
        return self.request('POST', '/api/state', json.dumps(payload) if not isinstance(payload, (str, bytes)) else payload, h)

    # ── resource exhaustion ──────────────────────────────────────────────────

    def test_r1_a_half_sent_body_does_not_pin_a_thread_forever(self):
        """Content-Length says 1000, 10 bytes come: the server must give up (answer_server has timeout=30)."""
        head = (f'POST /api/state HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://127.0.0.1:{self.port}\r\n'
                f'Content-Length: 1000\r\n\r\n{{"board":').encode()
        start = time.monotonic()
        self.raw(head, wait=40)
        self.assertLess(time.monotonic() - start, 39, 'the connection was still open after 40 s (Handler.timeout = %r)'
                        % getattr(self.mod.Handler, 'timeout', None))

    def test_r2_idle_sockets_cannot_take_the_server_down(self):
        """Launchd's soft fd limit is 256. 300 idle sockets (a scanner, preconnects, a slowloris) and the
        owner's next GET must still be answered."""
        env = dict(os.environ, BOARDS_DIR=str(self.boards), SUDA_PORT='0')
        p = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', '0'], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True,
                             preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (256, resource.getrlimit(resource.RLIMIT_NOFILE)[1])))   # launchd: a soft 256, the hard limit as it is
        socks = []
        try:
            line = p.stdout.readline()
            port = int(line.split('127.0.0.1:')[1].split('/')[0])
            for _ in range(300):
                try:
                    socks.append(socket.create_connection(('127.0.0.1', port), timeout=2))
                except OSError:
                    break
            time.sleep(1)
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            try:
                c.request('GET', '/threads/suda.html', headers={'Host': f'127.0.0.1:{port}'})
                status = c.getresponse().status
            except OSError as e:
                status = repr(e)
            self.assertEqual(status, 200, f'with {len(socks)} idle sockets open the page is not served: {status}')
        finally:
            for s in socks:
                s.close()
            p.kill()
            p.wait()

    # ── what POST can make a hook do ─────────────────────────────────────────

    def test_p1_post_does_not_run_another_boards_hook(self):
        """server.py is Suda's server, but it runs ANY board's on-state.sh and overwrites its state.json."""
        marker = self.root / 'OTHER_HOOK_RAN'
        status, body, _ = self.post({'board': 'other', 'state': {'op': 'x'}})
        self.assertFalse(marker.exists(), f'another board\'s on-state.sh ran ({status} {body[:120]!r})')
        self.assertFalse((self.boards / 'other/state/state.json').exists(), 'another board\'s state.json was overwritten')

    def test_p2_a_nested_path_is_not_a_board(self):
        status, _, _ = self.post({'board': 'threads/uploads', 'state': {'op': 'x'}})
        (self.boards / 'threads/uploads').mkdir(exist_ok=True)
        status, _, _ = self.post({'board': 'threads/uploads', 'state': {'op': 'x'}})
        self.assertIn(status, (400, 404))
        self.assertFalse((self.boards / 'threads/uploads/state').exists(), 'a state folder was made inside uploads/')

    # ── same-origin content ──────────────────────────────────────────────────

    def test_x1_other_boards_html_does_not_share_sudas_origin(self):
        """An agent's prototype page in another board, served on Suda's origin, can POST /api/state."""
        status, _, head = self.request('GET', '/other/assets/proto.html')
        sandboxed = 'sandbox' in head.get('Content-Security-Policy', '')
        self.assertTrue(status == 404 or sandboxed, f'served as {head.get("Content-Type")} on the board origin')

    def test_x2_board_cannot_be_framed(self):
        _, _, head = self.request('GET', '/threads/suda.html')
        csp = head.get('Content-Security-Policy', '')
        self.assertTrue(head.get('X-Frame-Options') or 'frame-ancestors' in csp, 'suda.html can be framed by any site (clickjacking)')

    def test_x3_snippet_and_upload_kinds_never_render(self):
        snip = self.boards / 'threads/snippets/topic'
        snip.mkdir(parents=True, exist_ok=True)
        up = self.boards / 'threads/uploads/topic'
        up.mkdir(parents=True, exist_ok=True)
        for f in (snip / 'm1.txt', snip / 'm2.md', snip / 'm3.log', up / 'm4.html.txt'):
            f.write_text('<html><script>alert(1)</script>')
            status, _, head = self.request('GET', '/' + str(f.relative_to(self.boards)))
            with self.subTest(f=f.name):
                self.assertEqual(status, 200)
                self.assertNotIn('html', head['Content-Type'])
                self.assertNotIn('svg', head['Content-Type'])
                self.assertEqual(head.get('X-Content-Type-Options'), 'nosniff')

    # ── host / origin variants ───────────────────────────────────────────────

    def test_h1_host_variants_are_refused(self):
        bad = ('localhost.', '127.0.0.1.', 'LOCALHOST.EVIL', 'evil@127.0.0.1', '[::ffff:127.0.0.1]', '::1', '',
               '127.0.0.1@evil.example', 'evil.example#127.0.0.1')
        for host in bad:
            with self.subTest(host=host):
                self.assertEqual(self.request('GET', '/threads/suda.html', headers={'Host': host})[0], 403)
        # no Host at all (HTTP/1.0)
        self.assertIn(b' 403 ', self.raw(b'GET /threads/suda.html HTTP/1.0\r\n\r\n').split(b'\r\n')[0] + b' ')
        # two Host headers, the evil one first
        r = self.raw(f'GET /threads/suda.html HTTP/1.1\r\nHost: evil.example\r\nHost: 127.0.0.1:{self.port}\r\n\r\n'.encode())
        self.assertIn(b' 403 ', r.split(b'\r\n')[0] + b' ')

    def test_h2_origin_scheme_is_checked(self):
        """The Origin's host:port is compared, but not its scheme (answer_server requires http/https)."""
        for origin in (f'ftp://127.0.0.1:{self.port}', f'chrome-extension://127.0.0.1:{self.port}', f'//127.0.0.1:{self.port}'):
            with self.subTest(origin=origin):
                self.assertEqual(self.post({'board': 'threads', 'state': {'op': 'sweep'}}, Origin=origin)[0], 403)

    def test_h3_cross_origin_variants_are_refused(self):
        for origin in ('null', f'http://127.0.0.1:{self.port}.evil.example', f'http://evil@127.0.0.1:{self.port}',
                       f'http://localhost:{self.port}', f'https://127.0.0.1:{self.port + 1}', ''):
            with self.subTest(origin=origin):
                self.assertEqual(self.post({'board': 'threads', 'state': {'op': 'sweep'}}, Origin=origin)[0], 403)
        # Referer only, no Origin
        self.assertEqual(self.post({'board': 'threads', 'state': {'op': 'sweep'}}, Origin=None,
                                   Referer=f'http://127.0.0.1:{self.port}/threads/suda.html')[0], 403)

    # ── traversal and robustness ─────────────────────────────────────────────

    def test_t1_traversal_variants(self):
        (self.boards / 'threads' / 'hl').unlink(missing_ok=True)
        for path in ('/%252e%252e/secret.txt', '/threads/%2e%2e%2f%2e%2e%2fsecret.txt', '/threads/..%5c..%5csecret.txt',
                     '/threads/%c0%ae%c0%ae/secret.txt', '/threads/%ef%bc%8e%ef%bc%8e/secret.txt',
                     f'/{self.root}/secret.txt', '/threads/state.json%00.txt', '/THREADS/.PULSE', '/threads/./suda.html'):
            with self.subTest(path=path):
                try:
                    status, body, _ = self.request('GET', path)
                except Exception as e:
                    self.fail(f'{path}: {e!r}')
                self.assertIn(status, (400, 403, 404))
                self.assertNotIn(b'outside the boards', body)

    def test_t1b_raw_non_ascii_path(self):
        r = self.raw(f'GET /threads/\uff0e\uff0e/\uff0e\uff0e/secret.txt HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n'.encode('utf-8'))
        self.assertNotIn(b'outside the boards', r)
        self.assertNotIn(b' 200 ', r.split(b'\r\n')[0] + b' ')

    def test_t2_odd_input_gets_an_answer_not_a_reset(self):
        """A crash in the handler drops the connection and prints a traceback (paths) to the server's stderr."""
        cases = [('GET', '/threads/' + 'a' * 300, None), ('GET', '/events?board=' + 'a' * 300, None),
                 ('GET', '/threads/' + '/'.join(['a'] * 600), None),
                 ('POST', '/api/state', '{"board":"threads","state":' + '[' * 100000 + ']' * 100000 + '}'),
                 ('POST', '/api/state', '{"board":"threads","state":{"a":' + '[' * 990 + ']' * 990 + '}}')]
        for method, path, body in cases:
            with self.subTest(path=path[:40], body=(body or '')[:40]):
                h = {'Origin': f'http://127.0.0.1:{self.port}'} if method == 'POST' else {}
                try:
                    status = self.request(method, path, body, h)[0]
                except (http.client.HTTPException, OSError) as e:
                    self.fail(f'no answer: {e!r}')
                self.assertLess(status, 500)

    def test_t3_hook_source_is_not_served(self):
        """on-state.sh is served as a plain file: absolute paths of the repo and interpreter."""
        status, body, _ = self.request('GET', '/threads/on-state.sh')
        self.assertEqual(status, 404, body[:200])

    def test_i1_no_version_banner(self):
        _, _, head = self.request('GET', '/threads/suda.html')
        self.assertNotRegex(head.get('Server', ''), r'Python|BaseHTTP|\d')
        status, body, _ = self.request('GET', '/nope/' + str(self.root).strip('/'))
        self.assertNotIn(str(self.root).encode(), body)


if __name__ == '__main__':
    unittest.main()
