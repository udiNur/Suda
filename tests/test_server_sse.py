#!/usr/bin/env python3
"""/events in Suda's own server (server.py) on a board whose .pulse holds a number: ids, resume, a heartbeat.

threads.py writes the number of the board's last change into .pulse. The SSE standard then: every "data: changed"
carries `id: <number>`, the stream says `retry: 2000` once, and a client that comes back says where it was (the
Last-Event-ID header the browser sends by itself, or ?since=N from a page that opened a new EventSource; the header
wins). When that is the board's number, nothing is sent but a named heartbeat; otherwise one "changed". The
heartbeat (`event: alive`, `data: <number>`) goes at once and every SSE_ALIVE_S seconds, in place of the ping. A
board whose pulse is only touched (an older threads.py) gets exactly the bytes it always got.

The hostile cases of the live server's review are here too: a pulse that goes away, digits of other scripts, a
board that goes back to a lower number.

Run: python3 test_server_sse.py. Loopback only, a temp BOARDS_DIR.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from test_server_range import load_server


class Stream:
    """One raw SSE connection: what came after the headers."""

    def __init__(self, port, path, headers=(), raw=None):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        if raw is None:
            extra = ''.join('%s: %s\r\n' % h for h in headers)
            raw = ('GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n%s\r\n' % (path, port, extra)).encode()
        self.sock.sendall(raw)
        self.buf = b''
        self.head = None

    def _pull(self, deadline):
        self.sock.settimeout(max(0.01, min(0.2, deadline - time.monotonic())))
        try:
            chunk = self.sock.recv(4096)
        except (socket.timeout, BlockingIOError):
            return
        if not chunk:
            raise EOFError('the server closed the stream')
        self.buf += chunk
        if self.head is None and b'\r\n\r\n' in self.buf:
            self.head, self.buf = self.buf.split(b'\r\n\r\n', 1)

    def read_for(self, seconds):
        """Everything the body brought within `seconds` (from the last read on)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._pull(deadline)
        out, self.buf = (self.buf, b'') if self.head is not None else (b'', self.buf)
        return out

    def read_until(self, needle, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.head is not None and needle in self.buf:
                break
            self._pull(deadline)
        out, self.buf = (self.buf, b'') if self.head is not None else (b'', self.buf)
        return out

    def close(self):
        self.sock.close()


def write_pulse(board, text):
    tmp = board / '.pulse.tmp'
    tmp.write_text(text)
    os.replace(tmp, board / '.pulse')


class SseResume(unittest.TestCase):
    """A server of its own; each case has a board of its own (the server serves the one board named last)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.sse-server-test-')
        cls.root = Path(cls.tmp.name)
        cls.mod = load_server('server_sse_' + cls.__name__, cls.root)
        cls.server = cls.mod.Server(('127.0.0.1', 0), cls.mod.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        # fast clocks for the test; the shape of what is sent does not depend on them
        cls.mod.SSE_POLL_S = 0.1
        cls.mod.SSE_ALIVE_S = 0.8
        cls.mod.SSE_PING_S = 1.5

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.streams = []

    def tearDown(self):
        for s in self.streams:
            s.close()

    def board(self, slug, pulse):
        d = self.root / slug
        d.mkdir(exist_ok=True)
        if pulse is None:
            (d / '.pulse').touch()
        else:
            write_pulse(d, pulse)
        self.mod.SLUG = slug
        return d

    def open(self, slug, query='', headers=(), raw=None):
        s = Stream(self.port, '/events?board=%s%s' % (slug, query), headers, raw)
        self.streams.append(s)
        return s


class Resume(SseResume):
    def test_a_numbered_board_says_retry_once_then_changed_with_its_id_and_alive(self):
        d = self.board('numbered', '7')
        s = self.open('numbered')
        first = s.read_until(b'event: alive\ndata: 7\n\n')
        self.assertIn(b'200', s.head)
        self.assertIn(b'text/event-stream', s.head)
        self.assertEqual(first, b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')
        write_pulse(d, '8')
        got = s.read_until(b'id: 8\ndata: changed\n\n', timeout=3)
        self.assertTrue(got.endswith(b'id: 8\ndata: changed\n\n'), got)
        self.assertNotIn(b'retry:', got)
        self.assertNotIn(b': ping', got)

    def test_last_event_id_equal_to_the_number_sends_no_changed(self):
        self.board('resume-h', '7')
        s = self.open('resume-h', headers=[('Last-Event-ID', '7')])
        self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 7\n\n')

    def test_since_in_the_address_equal_to_the_number_sends_no_changed(self):
        self.board('resume-q', '7')
        s = self.open('resume-q', '&since=7')
        self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 7\n\n')

    def test_a_client_behind_or_ahead_gets_one_changed(self):
        self.board('behind', '7')
        for since in ('&since=5', '&since=9', '&since=0'):
            with self.subTest(since=since):
                s = self.open('behind', since)
                self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')
        s = self.open('behind', headers=[('Last-Event-ID', '6')])
        self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')

    def test_the_header_is_newer_than_the_address(self):
        """A browser that reconnects by itself keeps the address it opened with (?since= of then) and sends the id it
        heard last in the header: the header wins."""
        self.board('both', '7')
        s = self.open('both', '&since=3', headers=[('Last-Event-ID', '7')])
        self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 7\n\n')

    def test_a_number_that_is_not_one_is_ignored(self):
        self.board('junk', '7')
        for query, headers in (('&since=abc', ()), ('&since=-1', ()), ('&since=1e3', ()), ('&since=' + '9' * 30, ()),
                               ('&since=%207', ()), ('', [('Last-Event-ID', 'x7')]), ('&since=7', [('Last-Event-ID', ' ')])):
            with self.subTest(query=query, headers=headers):
                s = self.open('junk', query, headers)
                got = s.read_for(0.6)
                if query == '&since=7':        # an empty header is no header: the address decides
                    self.assertEqual(got, b'retry: 2000\n\nevent: alive\ndata: 7\n\n')
                elif query == '&since=%207':   # (spaces around a number are let be, as in the live server)
                    self.assertEqual(got, b'retry: 2000\n\nevent: alive\ndata: 7\n\n')
                else:
                    self.assertEqual(got, b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')

    def test_alive_repeats_and_replaces_the_ping(self):
        self.board('alive', '11')
        s = self.open('alive', '&since=11')
        got = s.read_for(2.9)
        self.assertGreaterEqual(got.count(b'event: alive\ndata: 11\n\n'), 3, got)
        self.assertNotIn(b': ping', got)
        self.assertNotIn(b'changed', got)

    def test_every_change_of_the_pulse_is_one_changed_with_the_new_id(self):
        d = self.board('moves', '20')
        s = self.open('moves', '&since=20')
        s.read_for(0.4)
        for n in (21, 22, 23):
            write_pulse(d, str(n))
            got = s.read_until(b'id: %d\ndata: changed\n\n' % n, timeout=3)
            self.assertIn(b'id: %d\ndata: changed\n\n' % n, got)
        # the same number again (a pull request's chip moved, the pulse touched): still "changed", with that id
        os.utime(d / '.pulse', (time.time() + 5, time.time() + 5))
        got = s.read_until(b'id: 23\ndata: changed\n\n', timeout=3)
        self.assertIn(b'id: 23\ndata: changed\n\n', got)

    def test_a_new_page_build_is_changed_with_the_number(self):
        """`threads install` writes a new suda.html: the open pages hear "changed" (they look for the new build)."""
        d = self.board('build', '30')
        s = self.open('build', '&since=30')
        s.read_for(0.4)
        (d / 'suda.html').write_text('<html>new build</html>')
        got = s.read_until(b'id: 30\ndata: changed\n\n', timeout=3)
        self.assertIn(b'id: 30\ndata: changed\n\n', got)

    def test_two_clients_with_different_numbers(self):
        d = self.board('two', '40')
        a = self.open('two', '&since=40')
        b = self.open('two', '&since=37')
        self.assertEqual(a.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 40\n\n')
        self.assertEqual(b.read_for(0.1), b'retry: 2000\n\nid: 40\ndata: changed\n\nevent: alive\ndata: 40\n\n')
        write_pulse(d, '41')
        for s in (a, b):
            got = s.read_until(b'id: 41\ndata: changed\n\n', timeout=3)
            self.assertIn(b'id: 41\ndata: changed\n\n', got)
        # each one is its own: a third one at 41 hears no changed
        c = self.open('two', '&since=41')
        self.assertEqual(c.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 41\n\n')

    def test_a_board_without_a_number_gets_what_it_always_got(self):
        """The old stream of server.py, byte for byte: "data: changed" at once and on every change, ": ping" when quiet."""
        d = self.board('plain', None)
        (d / 'suda.html').write_text('<html>1</html>')
        for query, headers in (('', ()), ('&since=7', ()), ('', [('Last-Event-ID', '7')])):
            with self.subTest(query=query, headers=headers):
                s = self.open('plain', query, headers)
                self.assertEqual(s.read_for(0.5), b'data: changed\n\n')
                (d / 'suda.html').write_text('<html>2</html>')
                os.utime(d / 'suda.html', (time.time() + 3, time.time() + 3))
                self.assertEqual(s.read_until(b'data: changed\n\n', timeout=3), b'data: changed\n\n')
                self.assertEqual(s.read_for(1.8), b': ping\n\n')
        # pulse text that is not a number is no number
        write_pulse(d, '12abc')
        s = self.open('plain')
        self.assertEqual(s.read_for(0.5), b'data: changed\n\n')

    def test_the_guards_of_the_stream_stay(self):
        self.board('guarded', '5')

        def status(raw):
            with socket.create_connection(('127.0.0.1', self.port), timeout=5) as sock:
                sock.sendall(raw)
                return sock.recv(200).split(b'\r\n')[0]
        self.assertIn(b' 404 ', status(b'GET /events?board=other HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'))     # not this server's board
        self.assertIn(b' 403 ', status(b'GET /events?board=guarded HTTP/1.1\r\nHost: evil.example\r\n\r\n'))
        self.assertIn(b' 405 ', status(b'HEAD /events?board=guarded HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'))


class AdvSse(SseResume):
    """The hostile review's cases (each asserts the safe outcome)."""

    def test_a_pulse_that_goes_away_is_never_said_as_still_standing(self):
        d = self.board('gone', '40')
        s = self.open('gone', '&since=40')
        s.read_for(0.4)
        (d / '.pulse').unlink()
        got = s.read_for(2.5)
        self.assertNotIn(b'data: 40\n', got, 'the heartbeat kept saying 40 after the pulse was gone: %r' % got)
        # an older threads.py touches it back, empty
        (d / '.pulse').touch()
        got = s.read_for(2.5)
        self.assertNotIn(b'data: 40\n', got, got)
        self.assertNotIn(b'id: 40', got, got)
        # a numbered save again: the new number at once, and the heartbeat with it
        write_pulse(d, '41')
        got = s.read_until(b'event: alive\ndata: 41\n\n', timeout=3)
        self.assertIn(b'id: 41\ndata: changed\n\n', got)
        self.assertIn(b'event: alive\ndata: 41\n\n', got)

    def test_last_event_id_in_other_digits_is_no_number(self):
        self.board('digits', '7')
        for value in ('٧', '７', '7٣', '²'):
            with self.subTest(value=ascii(value)):
                s = self.open('digits', raw=b'GET /events?board=digits HTTP/1.1\r\nHost: 127.0.0.1\r\nLast-Event-ID: '
                              + value.encode('utf-8') + b'\r\n\r\n')
                self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')
        for value in ('%D9%A7', '%C2%B2', '%EF%BC%97'):
            with self.subTest(since=value):
                s = self.open('digits', '&since=' + value)
                self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nid: 7\ndata: changed\n\nevent: alive\ndata: 7\n\n')

    def test_a_board_that_goes_back_says_the_lower_number_at_once(self):
        d = self.board('back', '900')
        s = self.open('back', '&since=900')
        s.read_for(0.4)
        write_pulse(d, '12')
        got = s.read_until(b'id: 12\ndata: changed\n\n', timeout=3)
        self.assertIn(b'id: 12\ndata: changed\n\n', got)
        got = s.read_for(1.2)
        self.assertNotIn(b'data: 900', got)

    def test_a_pulse_too_long_to_be_a_number_is_none(self):
        """Only the first bytes of the pulse are read; a long one (or one of 17 digits) is no number."""
        d = self.board('long', '1' * 17)
        s = self.open('long')
        self.assertEqual(s.read_for(0.5), b'data: changed\n\n')
        (d / '.pulse').write_bytes(b'7' * (1 << 20))
        got = s.read_until(b'data: changed\n\n', timeout=3)
        self.assertEqual(got, b'data: changed\n\n')

    def test_a_pulse_with_a_newline_is_still_its_number(self):
        self.board('nl', '7\n')
        s = self.open('nl', '&since=7')
        self.assertEqual(s.read_for(0.6), b'retry: 2000\n\nevent: alive\ndata: 7\n\n')


if __name__ == '__main__':
    unittest.main()
