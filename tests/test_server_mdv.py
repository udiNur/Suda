#!/usr/bin/env python3
"""The MD Viewer's door in Suda's own server (server.py).

/mdv/* is handed to Suda's viewer (mdv_web, put by `threads install` in THREADS_MDV_DIR, else beside the boards folder
when BOARDS_DIR is set, else ~/.local/share/threads/mdv: the same place threads.py's mdv_dir() names); everything
else is the board server's as before. Each case runs the real server (server.py's main(), on a free 127.0.0.1 port)
in a process of its own, with a stand-in mdv_web, so nothing leaks into the other test files. What must hold:
  - only /mdv/ and below go to the viewer (/mdv, /mdvx, /md-viewer/ stay the board's), GET, HEAD and POST;
  - the viewer gets the server's own Host allowlist (loopback and SUDA_ALLOWED_HOSTS);
  - every request passes the server's own guards first (Host on all, Origin on a POST): a refused one never reaches
    the viewer;
  - a viewer that is missing, does not import, or raises answers 503 on /mdv/ only, the connection closed, and the
    board goes on;
  - a viewer that failed to import is tried again after SUDA_MDV_RETRY seconds (a new install, no restart), with
    none of the failed install's modules left behind;
  - the viewer is loaded from its installed file, never another mdv_web found on sys.path;
  - a body dripped to a 503 is not waited for;
  - with the real viewer, its page, its guard and its path allowlist come through (skipped when there is none).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = _paths.APP

GOOD = '''
import os
LOG = os.path.join(os.path.dirname(__file__), "calls.log")
def config(allow_hosts=None):
    return {"hosts": sorted(allow_hosts or [])}
def handle(h, cfg):
    with open(LOG, "a") as f:
        f.write(h.command + " " + h.path + "\\n")
    body = ("viewer " + h.command + " " + h.path + " " + ",".join(cfg["hosts"])).encode()
    h.send_response(200)
    h.send_header("Content-Type", "text/plain")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(body)
    h.close_connection = True
'''

# server.py's own main(), with the socket timeout a case asks for (the server has no knob for it)
LAUNCH = '''
import sys
sys.path.insert(0, sys.argv[1])
import server
server.Handler.timeout = float(sys.argv[2])
sys.argv = ["server.py", "--port", sys.argv[3]]
server.main()
'''


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Board(unittest.TestCase):
    """A board server of its own for each case."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.mdv-door-test-')
        self.base = Path(os.path.realpath(self.tmp.name))
        boards = self.base / 'boards'
        (boards / 'threads').mkdir(parents=True)
        (boards / 'threads' / 'suda.html').write_text('<p>the board</p>')
        (self.base / 'no-boardlib').mkdir()
        self.viewer_dir = self.base / 'viewer'
        (self.viewer_dir / 'mdv').mkdir(parents=True)
        (self.viewer_dir / 'mdv' / '__init__.py').write_text('')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, viewer=None, mdv_dir='default', retry='0.5', cwd=None, timeout=30, **extra):
        if viewer is not None:
            (self.viewer_dir / 'mdv_web.py').write_text(viewer)
        self.port = free_port()
        env = dict(os.environ, BOARDS_DIR=str(self.base / 'boards'), SUDA_MDV_RETRY=retry,
                   SUDA_ALLOWED_HOSTS='suda.example.net', THREADS_BOARDLIB_DIR=str(self.base / 'no-boardlib'),
                   PYTHONDONTWRITEBYTECODE='1', **extra)
        for key in ('PYTHONPATH', 'THREADS_SLUG', 'THREADS_MDV_DIR'):
            env.pop(key, None)
        if mdv_dir == 'default':
            env['THREADS_MDV_DIR'] = str(self.viewer_dir)
        elif mdv_dir is not None:
            env['THREADS_MDV_DIR'] = str(mdv_dir)
        proc = subprocess.Popen([sys.executable, '-c', LAUNCH, str(ROOT), str(timeout), str(self.port)],
                                env=env, cwd=str(cwd or self.base), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(10), proc.stderr.close()))
        end = time.monotonic() + 10
        while time.monotonic() < end:
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close()
                return proc
            except OSError:
                time.sleep(0.05)
        proc.terminate()
        try:
            said = proc.communicate(timeout=5)[1].decode('utf-8', 'replace')[-2000:]
        except subprocess.TimeoutExpired:
            said = '(no answer)'
        self.fail('the board server did not start: ' + said)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': '127.0.0.1:%d' % self.port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data, dict(r.getheaders())

    def origin(self):
        return {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:%d' % self.port}

    def calls(self):
        log = self.viewer_dir / 'calls.log'
        return log.read_text().splitlines() if log.exists() else []


class Routes(Board):
    def test_only_mdv_and_below_go_to_the_viewer(self):
        self.start(GOOD)
        st, data, _ = self.req('GET', '/mdv/?path=x')
        self.assertEqual(st, 200)
        self.assertTrue(data.startswith(b'viewer GET /mdv/?path=x '), data)
        self.assertIn(b'suda.example.net', data)       # the server's own Host allowlist is the viewer's
        self.assertIn(b'127.0.0.1', data)
        self.assertEqual(self.req('HEAD', '/mdv/?path=x')[0], 200)
        self.assertEqual(self.req('GET', '/mdv/api/doc?path=y')[0], 200)
        for path in ('/mdv', '/mdvx/', '/md-viewer/', '/threads/suda.html', '/', '/threads/mdv/', '/MDV/'):
            self.req('GET', path)
        self.assertEqual(self.calls(), ['GET /mdv/?path=x', 'HEAD /mdv/?path=x', 'GET /mdv/api/doc?path=y'])
        self.assertEqual(self.req('GET', '/threads/suda.html')[:2], (200, b'<p>the board</p>'))
        self.assertEqual(self.req('GET', '/mdv')[0], 404)

    def test_a_refused_request_never_reaches_the_viewer(self):
        self.start(GOOD)
        body = json.dumps({'path': '/x.md'})
        js = {'Content-Type': 'application/json'}
        self.assertEqual(self.req('POST', '/mdv/api/summary', body, dict(js, Origin='http://evil.example.com'))[0], 403)
        self.assertEqual(self.req('POST', '/mdv/api/translate', body, dict(self.origin(), Host='evil.example.com'))[0], 403)
        self.assertEqual(self.req('POST', '/mdv/api/summary', body, js)[0], 403)     # a write with no Origin: server.py's rule
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'evil.example.com'})[0], 403)
        self.assertEqual(self.req('HEAD', '/mdv/', headers={'Host': '127.0.0.1.evil.example.com'})[0], 403)
        self.assertEqual(self.calls(), [])
        st, data, _ = self.req('POST', '/mdv/api/summary', body, self.origin())
        self.assertEqual(st, 200)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'suda.example.net'})[0], 200)
        self.assertEqual(self.calls(), ['POST /mdv/api/summary', 'GET /mdv/'])

    def test_a_missing_viewer_is_503_and_the_board_goes_on(self):
        self.start(None)
        st, data, h = self.req('GET', '/mdv/?path=x')
        self.assertEqual((st, json.loads(data)['error'], h.get('Connection')), (503, 'unavailable', 'close'))
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)
        st, data, _ = self.req('POST', '/mdv/api/summary', '{"path": "x"}', self.origin())
        self.assertEqual(st, 503)
        st, data, _ = self.req('HEAD', '/mdv/')
        self.assertEqual((st, data), (503, b''))

    def test_a_viewer_that_does_not_import_is_503_then_tried_again(self):
        self.start('raise RuntimeError("broken viewer")\n')
        self.assertEqual(self.req('GET', '/mdv/')[0], 503)
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)
        (self.viewer_dir / 'mdv_web.py').write_text(GOOD)      # a new install, no restart
        time.sleep(0.8)
        self.assertEqual(self.req('GET', '/mdv/')[0], 200)

    def test_a_failed_import_is_not_tried_again_on_every_request(self):
        self.start('import os\nopen(os.path.join(os.path.dirname(__file__), "tries.log"), "a").write("x")\n'
                   'raise RuntimeError("broken viewer")\n', retry='30')
        for _ in range(5):
            self.assertEqual(self.req('GET', '/mdv/')[0], 503)
        self.assertEqual((self.viewer_dir / 'tries.log').read_text(), 'x')

    def test_a_viewer_that_raises_is_503_and_the_board_goes_on(self):
        self.start(GOOD + '\ndef handle(h, cfg):\n    raise ValueError("viewer bug")\n')
        st, _, h = self.req('GET', '/mdv/?path=x')
        self.assertEqual((st, h.get('Connection')), (503, 'close'))
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)

    def test_a_viewer_that_raises_after_it_began_closes_and_the_board_goes_on(self):
        self.start(GOOD + '\ndef handle(h, cfg):\n    h.send_response(200)\n    h.send_header("Content-Length", "100")\n'
                   '    h.end_headers()\n    h.wfile.write(b"half")\n    raise ValueError("viewer bug")\n')
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        s.sendall(b'GET /mdv/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        got = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            got += chunk
        s.close()
        self.assertTrue(got.startswith(b'HTTP/1.0 200') or got.startswith(b'HTTP/1.1 200'), got)
        self.assertNotIn(b' 503 ', got, 'no second answer after one began')
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)

    def test_a_viewer_whose_config_fails_is_503(self):
        self.start(GOOD + '\ndef config(allow_hosts=None):\n    raise ValueError("bad config")\n')
        self.assertEqual(self.req('GET', '/mdv/?path=x')[0], 503)
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)

    def test_only_the_installed_file_is_loaded(self):
        # another mdv_web where Python would look first (the server's working folder) is not the viewer
        stray = self.base / 'stray'
        stray.mkdir()
        (stray / 'mdv_web.py').write_text(GOOD.replace('"viewer "', '"STRAY "'))
        self.start(GOOD, cwd=stray)
        st, data, _ = self.req('GET', '/mdv/')
        self.assertTrue(data.startswith(b'viewer GET'), data)

    def test_without_threads_mdv_dir_the_viewer_is_beside_the_boards_folder(self):
        """Where threads.py's mdv_dir() puts it when BOARDS_DIR is set: <BOARDS_DIR>/../threads-mdv."""
        beside = self.base / 'threads-mdv'
        beside.mkdir()
        (beside / 'mdv_web.py').write_text(GOOD.replace('"viewer "', '"BESIDE "'))
        self.start(None, mdv_dir=None)
        st, data, _ = self.req('GET', '/mdv/')
        self.assertEqual(st, 200)
        self.assertTrue(data.startswith(b'BESIDE GET'), data)


class AdvDoor(Board):
    """The hostile review's cases (each asserts the safe outcome)."""

    def test_a_fixed_install_loads_after_a_failed_one(self):
        """A failed load must not keep the viewer package's modules: the retry would get the old ones back."""
        (self.viewer_dir / 'mdv' / 'part.py').write_text('V = 1\n')
        (self.viewer_dir / 'mdv_web.py').write_text('''
from mdv import part
if part.V != 2:
    raise ImportError("an install with a broken part")
def config(allow_hosts=None):
    return {}
def handle(h, cfg):
    body = b"viewer v2"
    h.send_response(200)
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
    h.close_connection = True
''')
        self.start(retry='0.2')
        self.assertEqual(self.req('GET', '/mdv/x')[0], 503)
        (self.viewer_dir / 'mdv' / 'part.py').write_text('V = 2\n')     # the next `threads install`
        time.sleep(0.5)
        st, data, _ = self.req('GET', '/mdv/x')
        self.assertEqual((st, data), (200, b'viewer v2'),
                         'after a failed load the retry keeps the old mdv.* modules: the fixed install never loads')

    def test_a_dripped_body_on_the_503_path_is_cut_off(self):
        self.start(None, timeout=1)                 # no mdv_web.py: every /mdv/ request is a 503
        s = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        s.sendall(b'POST /mdv/api/summary HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\n'
                  b'Content-Type: application/json\r\nContent-Length: 4000\r\n\r\n' % (self.port, self.port))
        start, at = time.time(), None
        try:
            while time.time() - start < 6:
                r, _, _ = select.select([s], [], [], 0.5)
                if r:
                    at = time.time() - start
                    break
                s.sendall(b' ')
        except OSError:
            at = time.time() - start
        finally:
            s.close()
        self.assertIsNotNone(at, 'a body dripped a byte every 0.5 s held a board thread for 6 s (per-read timeout 1 s)')
        self.assertLess(at, 4)

    def test_a_viewer_module_named_like_the_server_does_not_replace_it(self):
        """Pinned: the viewer's folder goes first on sys.path for its package; a stray server.py or suda_boardlib.py there
        must not stand in for the board server's own modules."""
        (self.viewer_dir / 'suda_boardlib.py').write_text('raise SystemExit("the stray boardlib was imported")\n')
        (self.viewer_dir / 'server.py').write_text('raise SystemExit("the stray server was imported")\n')
        self.start(GOOD)
        self.assertEqual(self.req('GET', '/mdv/')[0], 200)
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)
        self.assertEqual(self.req('POST', '/api/state', '{"board": "threads", "state": {}}', self.origin())[0], 200)


def real_viewer():
    if os.environ.get('MDV_REAL_DIR'):
        return Path(os.environ['MDV_REAL_DIR'])
    return ROOT / 'mdv'


@unittest.skipUnless((real_viewer() / 'mdv_web.py').is_file(), 'no viewer in this checkout (mdv/) and no MDV_REAL_DIR')
class RealViewer(Board):
    """The viewer of this checkout through server.py: its page, its guard and its path allowlist (read only)."""

    def installed(self):
        """The viewer as `threads install` puts it: a copy, with Suda's own pieces written from suda.html."""
        import importlib.util
        import shutil
        dest = self.base / 'installed-mdv'
        shutil.copytree(real_viewer(), dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'samples'))
        spec = importlib.util.spec_from_file_location('mdv_sync_test', dest / 'mdv' / 'sync.py')
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        if not all((dest / 'static' / name).is_file() for name in sync.NAMES):
            sync.write(dest / 'static', ROOT / 'suda.html')
        return dest

    def test_page_guard_and_path_allowlist(self):
        notes = self.base / 'notes'
        notes.mkdir()
        (notes / 'a.md').write_text('# A note\n\nhello\n')
        (self.base / 'private.md').write_text('# not a note\n')
        self.start(mdv_dir=self.installed(), MDV_ROOTS_JSON=str(self.base / 'no-roots.json'), MDV_EXTRA_ROOTS=str(notes),
                   MDV_FAKE_MODEL='1')
        st, data, h = self.req('GET', '/mdv/?path=x')
        self.assertEqual(st, 200)
        self.assertIn("script-src 'self'", h.get('Content-Security-Policy', ''))
        self.assertEqual(self.req('GET', '/mdv/static/app.js')[0], 200)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'evil.example.com'})[0], 403)
        self.assertEqual(self.req('GET', '/mdv/', headers={'Host': 'suda.example.net'})[0], 200)
        st, data, _ = self.req('GET', '/mdv/api/doc?path=' + str(notes / 'a.md'))
        self.assertEqual(st, 200, data[:200])
        self.assertIn(b'hello', data)
        for outside in ('/etc/hosts.md', str(self.base / 'private.md'), str(notes / '..' / 'private.md')):
            with self.subTest(path=outside):
                st, data, _ = self.req('GET', '/mdv/api/doc?path=' + outside)
                self.assertEqual(st, 403, data[:200])
                self.assertNotIn(b'not a note', data)
        self.assertEqual(self.req('GET', '/threads/suda.html')[0], 200)


if __name__ == '__main__':
    unittest.main()
