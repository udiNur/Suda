#!/usr/bin/env python3
"""Hostile review of server.py's port of the skill server's features (ranges, 304, the numbered /events line, the
inline delta, the /mdv/ door).

Each HOLE case asserts the safe outcome and fails on the reviewed commit. The "pinned" cases held up under attack
and are kept so they stay that way.

Run: python3 test_adv_srvport.py. Loopback only, temp folders.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_server_range import load_server
from test_server_sse import SseResume, write_pulse


def raw_get(port, path, extra=(), timeout=5):
    """One request on a raw socket: everything the server sent before it closed (b'' when it sent nothing)."""
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    head = ''.join('%s: %s\r\n' % h for h in extra)
    s.sendall(('GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n%s\r\n' % (path, port, head)).encode())
    out = b''
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    s.close()
    return out


class Files(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.srvport-adv-')
        root = Path(cls.tmp.name)
        b = root / 'threads'
        (b / 'state').mkdir(parents=True)
        (b / 'on-state.sh').write_text('#!/bin/sh\necho HOOK-SOURCE\n')
        (b / 'tool.py').write_text('CODE-SOURCE = 1\n')
        (b / 'state' / 'state.json').write_text('{"STATE-SECRET": 1}')
        (b / 'clip.mp4').write_bytes(bytes(range(256)) * 8)
        cls.board = b
        cls.mod = load_server('server_srvport_files', root)
        cls.server = cls.mod.Server(('127.0.0.1', 0), cls.mod.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    # HOLE: byte_range() calls int() on any run of ASCII digits; past 4300 digits Python raises ValueError, which leaks
    # out of do_GET: the handler thread dies with a traceback and the client gets no answer at all.
    def test_a_range_with_thousands_of_digits_still_gets_an_answer(self):
        for spec in ('bytes=0-' + '9' * 5000, 'bytes=-' + '9' * 5000, 'bytes=' + '1' * 5000 + '-'):
            with self.subTest(spec=spec[:12]):
                got = raw_get(self.port, '/threads/clip.mp4', [('Range', spec)])
                self.assertTrue(got.startswith(b'HTTP/1.'), 'the request died without an answer: %r' % got[:40])
                status = got.split(b' ', 2)[1]
                self.assertIn(status, (b'200', b'206', b'416'))

    # HOLE (in of_board, older than this change, now also behind a range): the ".sh"/".py" and "state" checks look at
    # the raw URL, inside() at the percent-decoded one, so an encoded letter walks past them.
    def test_the_hook_and_the_code_are_never_served_under_an_encoded_name(self):
        for path, secret in (('/threads/on-state.s%68', b'HOOK-SOURCE'), ('/threads/on-state%2Esh', b'HOOK-SOURCE'),
                             ('/threads/tool.p%79', b'CODE-SOURCE'), ('/threads/tool%2epy', b'CODE-SOURCE')):
            for extra in ((), (('Range', 'bytes=0-'),)):
                with self.subTest(path=path, ranged=bool(extra)):
                    got = raw_get(self.port, path, extra)
                    self.assertNotIn(secret, got)
                    self.assertTrue(got.startswith(b'HTTP/1.0 404'), got[:40])

    def test_the_state_folder_is_never_served_under_another_spelling(self):
        for path in ('/threads/%73tate/state.json', '/threads/state%2Fstate.json'):
            with self.subTest(path=path):
                got = raw_get(self.port, path)
                self.assertNotIn(b'STATE-SECRET', got)
                self.assertTrue(got.startswith(b'HTTP/1.0 404'), got[:40])

    def test_the_state_folder_is_never_served_in_other_letter_case(self):
        if not (self.board / 'STATE').exists():
            self.skipTest('a case-sensitive file system: STATE is another folder')
        got = raw_get(self.port, '/threads/State/state.json')
        self.assertNotIn(b'STATE-SECRET', got)
        self.assertTrue(got.startswith(b'HTTP/1.0 404'), got[:40])

    # pinned: malformed or extreme If-Modified-Since / If-Range never break a request
    def test_pinned_odd_conditional_headers_never_break_a_request(self):
        values = ('Mon, 01 Jan 0000 00:00:00 GMT', 'Mon, 01 Jan 99999 00:00:00 GMT', 'Mon, 01 Jan 2020 00:00:00 +9999',
                  'Thu, 01 Jan 0001 00:00:00 +2359', '9' * 5000, 'x', ',,,')
        for v in values:
            for name in ('If-Modified-Since', 'If-Range'):
                with self.subTest(header=name, value=v[:20]):
                    got = raw_get(self.port, '/threads/clip.mp4', [(name, v), ('Range', 'bytes=0-9')])
                    self.assertTrue(got.startswith(b'HTTP/1.0 '), got[:40])

    # pinned: a file cut while it is sent ends the connection short, it never hangs or pads
    def test_pinned_a_file_cut_while_sent_ends_short(self):
        big = self.board / 'big.bin'
        big.write_bytes(b'z' * (8 << 20))
        self.addCleanup(big.unlink)
        s = socket.create_connection(('127.0.0.1', self.port), timeout=10)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        s.sendall(b'GET /threads/big.bin HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        got = s.recv(4096)
        time.sleep(0.3)
        os.truncate(big, 1000)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            chunk = s.recv(1 << 20)
            if not chunk:
                break
            got += chunk
        s.close()
        body = got.split(b'\r\n\r\n', 1)[1]
        self.assertLess(len(body), 8 << 20)
        self.assertEqual(set(body), {ord('z')})


def write_head(board, seq):
    (board / 'summary.json').write_text('{"seq":%d,"mark":"m%d","threads":{}}\n' % (seq, seq), encoding='utf-8')


def strict(text):
    """JSON as a browser's JSON.parse reads it: no NaN, Infinity or -Infinity."""
    def refuse(name):
        raise ValueError('not JSON for a browser: ' + name)
    return json.loads(text, parse_constant=refuse)


def delta_data(raw):
    for block in raw.split(b'\n\n'):
        lines = block.split(b'\n')
        if b'event: delta' in lines:
            return b'\n'.join(l[6:] for l in lines if l.startswith(b'data: '))
    return None


class Line(SseResume):
    # HOLE: read_small() checks the name against the folder it is given, and the change file is read with
    # folder = <board>/changes: a "changes" folder that is a link out of the board is followed, so the line sends bytes
    # from outside the board ("the line reads only plain files inside the board folder").
    def test_a_changes_folder_that_links_out_of_the_board_is_not_read(self):
        d = self.board('outlink', '40')
        write_head(d, 41)
        outside = Path(tempfile.mkdtemp(prefix='.srvport-outside-'))
        self.addCleanup(lambda: [p.unlink() for p in outside.iterdir()] and None or outside.rmdir())
        (outside / '40.json').write_text('{"seq":41,"entries":[{"from":40,"seq":41,"note":"OUTSIDE-THE-BOARD"}]}\n')
        (d / 'changes').symlink_to(outside, target_is_directory=True)
        s = self.open('outlink', '&since=40')
        s.read_until(b'event: alive\ndata: 40\n\n')
        write_pulse(d, '41')
        got = s.read_until(b'id: 41\ndata: changed\n\n')
        self.assertIn(b'id: 41\ndata: changed\n\n', got)
        self.assertNotIn(b'OUTSIDE-THE-BOARD', got)

    # HOLE: run_of() accepts what Python's json accepts (NaN, Infinity), and run_from_changes() re-encodes a number
    # too big for a float (1e400, valid JSON) as Infinity: the delta's data is then not JSON for the page.
    def test_a_delta_is_always_json_a_browser_can_parse(self):
        cases = {
            'nan': ('changes/50.json', '{"seq":51,"entries":[{"from":50,"seq":51,"x":NaN}]}\n'),
            'big': ('changes.json', '{"entries":[{"from":50,"seq":51,"x":1e400}]}\n'),
        }
        for name, (where, text) in cases.items():
            with self.subTest(case=name):
                d = self.board('strict-' + name, '50')
                write_head(d, 51)
                (d / 'changes').mkdir()
                (d / where).write_text(text, encoding='utf-8')
                s = self.open('strict-' + name, '&since=50')
                s.read_until(b'event: alive\ndata: 50\n\n')
                write_pulse(d, '51')
                got = s.read_until(b'id: 51\ndata: changed\n\n')
                self.assertIn(b'id: 51\ndata: changed\n\n', got)
                data = delta_data(got)
                if data is not None:                    # no delta is safe; a delta must parse
                    try:
                        strict(data)
                    except ValueError as e:
                        self.fail('the delta is not JSON a page can read (%s): %r' % (e, data[:120]))

    # pinned: odd Last-Event-ID / since values never break the line, and nothing but digits becomes an id
    def test_pinned_odd_resume_numbers_never_break_the_line(self):
        d = self.board('odd', '7')
        for value in ('9' * 5000, '-1', '1e3', ' 7 ', '0x7', '٧'):
            with self.subTest(value=value[:10]):
                s = self.open('odd', '&since=' + value.replace(' ', '%20'), [('Last-Event-ID', value.encode('utf-8').decode('latin-1'))])
                got = s.read_until(b'event: alive\ndata: 7\n\n')
                self.assertIn(b'event: alive\ndata: 7\n\n', got)
                self.assertNotIn(b'\r', got)
        self.assertTrue(d.is_dir())


if __name__ == '__main__':
    unittest.main()
