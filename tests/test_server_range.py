#!/usr/bin/env python3
"""HTTP Range for the board's files in Suda's own server (server.py).

A video plays from the middle only when the server answers a byte range: without it the browser cannot seek, and
iPhone Safari will not play an mp4 at all. The page also reads the first 64 bytes of summary.json with a range.
One range: 206 with Content-Range; a range past the end: 416 with `bytes */size`; several ranges, a malformed one,
or an If-Range that no longer matches: the whole file, 200. Every file answer says `Accept-Ranges: bytes`. The
no-store header and the server's guards (Host, the board folder only) stay.

Run: python3 test_server_range.py. Loopback only, a temp BOARDS_DIR.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import email.utils
import importlib.util
import os
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = _paths.APP


def load_server(name, boards, slug='threads'):
    """server.py as a module of its own, with its own view of the boards folder (nothing shared with other tests)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / 'server.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.bl = types.SimpleNamespace(**{k: v for k, v in vars(mod.bl).items() if not k.startswith('__')})
    mod.bl.BOARDS_DIR = Path(boards)
    mod.SLUG = slug
    return mod


class Start(unittest.TestCase):
    def test_the_server_starts_without_asking_dns_for_its_own_name(self):
        """http.server's HTTPServer names itself by socket.getfqdn(host), a reverse DNS lookup: on a machine whose
        resolver is slow (GitHub's macOS runners) the server took more than 10 s to start. It needs no name."""
        import socket
        with tempfile.TemporaryDirectory(prefix='.start-test-') as tmp:
            mod = load_server('server_start', tmp)
            asked = []
            real = socket.getfqdn
            socket.getfqdn = lambda *a, **k: asked.append(a) or real(*a, **k)
            try:
                server = mod.Server(('127.0.0.1', 0), mod.Handler)
                server.server_close()
            finally:
                socket.getfqdn = real
            self.assertEqual(asked, [], 'the server asked DNS for its own name')
            self.assertEqual(server.server_name, '127.0.0.1')


class Range(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.range-test-')
        root = Path(cls.tmp.name)
        (root / 'threads' / 'uploads').mkdir(parents=True)
        (root / 'secret.txt').write_text('root: outside the boards')
        cls.body = bytes(range(256)) * 40                      # 10240 bytes
        cls.file = root / 'threads' / 'uploads' / 'clip.mp4'
        cls.file.write_bytes(cls.body)
        (root / 'threads' / 'summary.json').write_text('{"seq":12,"mark":"abc","threads":{}}\n')
        cls.mod = load_server('server_range', root)
        cls.server = cls.mod.Server(('127.0.0.1', 0), cls.mod.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path='/threads/uploads/clip.mp4', method='GET', **headers):
        req = urllib.request.Request(self.base + path, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_a_whole_file_says_it_takes_ranges(self):
        status, headers, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.body)
        self.assertEqual(headers.get('Accept-Ranges'), 'bytes')
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(headers.get('Content-Length'), str(len(self.body)))

    def test_one_range_is_206_with_exactly_those_bytes(self):
        status, headers, body = self.get(Range='bytes=0-99')
        self.assertEqual(status, 206)
        self.assertEqual(body, self.body[:100])
        self.assertEqual(headers.get('Content-Range'), 'bytes 0-99/10240')
        self.assertEqual(headers.get('Content-Length'), '100')
        self.assertEqual(headers.get('Accept-Ranges'), 'bytes')
        self.assertEqual(headers.get('Content-Type'), 'video/mp4')
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(headers.get('X-Content-Type-Options'), 'nosniff')

    def test_the_summary_head_the_page_reads(self):
        status, headers, body = self.get('/threads/summary.json', Range='bytes=0-63')
        self.assertEqual((status, body), (206, b'{"seq":12,"mark":"abc","threads":{}}\n'))
        self.assertEqual(headers.get('Content-Type'), 'application/json; charset=utf-8')
        self.assertEqual(headers.get('Content-Range'), 'bytes 0-36/37')
        status, _, body = self.get('/threads/summary.json', Range='bytes=0-0')
        self.assertEqual((status, body), (206, b'{'))

    def test_an_open_range_and_a_suffix(self):
        status, headers, body = self.get(Range='bytes=10000-')
        self.assertEqual((status, body, headers.get('Content-Range')), (206, self.body[10000:], 'bytes 10000-10239/10240'))
        status, headers, body = self.get(Range='bytes=-40')
        self.assertEqual((status, body, headers.get('Content-Range')), (206, self.body[-40:], 'bytes 10200-10239/10240'))
        status, headers, body = self.get(Range='bytes=-99999')
        self.assertEqual((status, body, headers.get('Content-Range')), (206, self.body, 'bytes 0-10239/10240'))

    def test_an_end_past_the_file_is_cut_to_the_file(self):
        status, headers, body = self.get(Range='bytes=10200-99999999')
        self.assertEqual((status, body, headers.get('Content-Range')), (206, self.body[10200:], 'bytes 10200-10239/10240'))

    def test_a_start_past_the_end_is_416(self):
        status, headers, body = self.get(Range='bytes=10240-')
        self.assertEqual(status, 416)
        self.assertEqual(headers.get('Content-Range'), 'bytes */10240')
        self.assertEqual(body, b'')
        status, headers, _ = self.get(Range='bytes=-0')
        self.assertEqual(status, 416)
        status, headers, _ = self.get(Range='bytes=99999999999999999999-')
        self.assertEqual(status, 416)

    def test_several_ranges_or_a_malformed_one_give_the_whole_file(self):
        for value in ('bytes=0-1,5-9', 'bytes=abc', 'items=0-1', 'bytes=9-3', 'bytes=', 'bytes=1-2-3', 'bytes=-',
                      'bytes=²-3', 'bytes=-²', 'bytes=0-²', 'bytes=+1-2', 'bytes=0x1-2'):
            with self.subTest(value=ascii(value)):
                status, headers, body = self.get(Range=value)
                self.assertEqual((status, len(body)), (200, len(self.body)))
                self.assertNotIn('Content-Range', headers)

    def test_head_with_a_range_sends_the_headers_and_no_body(self):
        status, headers, body = self.get(method='HEAD', Range='bytes=0-9')
        self.assertEqual((status, headers.get('Content-Length'), headers.get('Content-Range'), body), (206, '10', 'bytes 0-9/10240', b''))

    def test_an_if_range_that_no_longer_matches_gives_the_whole_file(self):
        old = email.utils.formatdate(os.path.getmtime(self.file) - 3600, usegmt=True)
        status, _, body = self.get(Range='bytes=0-9', **{'If-Range': old})
        self.assertEqual((status, len(body)), (200, len(self.body)))
        _, headers, _ = self.get()
        status, _, body = self.get(Range='bytes=0-9', **{'If-Range': headers['Last-Modified']})
        self.assertEqual((status, body), (206, self.body[:10]))
        status, _, body = self.get(Range='bytes=0-9', **{'If-Range': '"an-etag"'})
        self.assertEqual((status, len(body)), (200, len(self.body)))

    def test_a_missing_file_or_a_folder_is_not_a_range(self):
        status, _, _ = self.get('/threads/uploads/none.mp4', Range='bytes=0-9')
        self.assertEqual(status, 404)
        status, headers, _ = self.get('/threads/uploads/', Range='bytes=0-9')
        self.assertNotEqual(status, 206)
        self.assertNotIn('Content-Range', headers)

    def test_a_range_cannot_climb_out_of_the_boards_or_reach_what_is_never_served(self):
        for path in ('/../secret.txt', '/threads/../secret.txt', '/threads/%2e%2e/secret.txt', '/threads/.pulse',
                     '/threads/state/state.json', '/threads/on-state.sh', '/other/summary.json'):
            with self.subTest(path=path):
                status, headers, body = self.get(path, Range='bytes=0-9')
                self.assertIn(status, (400, 403, 404))
                self.assertNotIn('Content-Range', headers)
                self.assertNotIn(b'outside', body)

    def test_another_host_name_gets_no_range(self):
        status, headers, body = self.get(Range='bytes=0-9', Host='evil.example')
        self.assertEqual(status, 403)
        self.assertNotIn('Content-Range', headers)
        self.assertEqual(body, b'')

    def test_a_file_not_written_since_is_a_304(self):
        """The page asks "changed since?" (If-Modified-Since) of its own file and of the files beside the board: a
        304 without a body when not, as the live server answers."""
        _, headers, _ = self.get()
        stamp = headers['Last-Modified']
        status, headers, body = self.get(**{'If-Modified-Since': stamp})
        self.assertEqual((status, body), (304, b''))
        self.assertEqual(headers.get('Last-Modified'), stamp)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertIn('Date', headers)
        status, _, body = self.get(Range='bytes=0-9', **{'If-Modified-Since': stamp})
        self.assertEqual((status, body), (304, b''))
        older = email.utils.formatdate(os.path.getmtime(self.file) - 3600, usegmt=True)
        for value in (older, 'yesterday', '', 'Mon, 99 Foo 2026 99:99:99 GMT', 'Thu, 01 Jan 1970 00:00:00 -0000'):
            with self.subTest(since=value):
                status, _, body = self.get(**{'If-Modified-Since': value})
                self.assertEqual((status, len(body)), (200, len(self.body)))
        status, _, body = self.get(**{'If-Modified-Since': stamp, 'If-None-Match': '"x"'})     # (that one decides)
        self.assertEqual((status, len(body)), (200, len(self.body)))

    def test_a_big_file_is_not_read_whole_for_a_small_range(self):
        """A range of a long video is read from where it starts: the server never holds the whole file for it."""
        big = Path(self.tmp.name) / 'threads' / 'uploads' / 'big.mp4'
        with open(big, 'wb') as f:
            f.truncate(64 * 1024 * 1024)
        reads = []
        real = Path.read_bytes

        def spy(path):
            reads.append(str(path))
            return real(path)
        Path.read_bytes = spy
        try:
            status, headers, body = self.get('/threads/uploads/big.mp4', Range='bytes=1000-1009')
        finally:
            Path.read_bytes = real
        self.assertEqual((status, body, headers.get('Content-Range')), (206, b'\0' * 10, 'bytes 1000-1009/67108864'))
        self.assertFalse([p for p in reads if p.endswith('big.mp4')], 'the whole file was read for ten bytes')


if __name__ == '__main__':
    unittest.main()
