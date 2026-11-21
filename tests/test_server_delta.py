#!/usr/bin/env python3
"""/events in Suda's own server (server.py) carries the small change itself, before its "changed".

Before, every update came in two steps: "changed" on the line, then the page read changes/<its number>.json and the
head of summary.json: one more round trip. Now, before each "id: N / data: changed", the server sends a named event:

    event: delta
    data: {"head":"<the first 64 bytes of summary.json>","run":<changes/<the number it last told this line>.json>}

only when that file exists, leads exactly to N, is one JSON object on one line of at most SSE_INLINE_MAX bytes, and
the summary's head is at N. Else the run is built from changes.json (each entry names the number it starts from)
when it leads from the told number to N without a gap and fits. Anything else: no delta, and the page reads as
before. A page that knows nothing yet (no since) gets no delta; a board without numbers gets what it always got.

The hostile cases of the live server's review are here too.

Run: python3 test_server_delta.py. Loopback only, a temp BOARDS_DIR.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

from test_server_sse import SseResume, write_pulse


def write_change(board, start, seq, text=None):
    d = board / 'changes'
    d.mkdir(exist_ok=True)
    body = text if text is not None else '{"seq":%d,"entries":[{"from":%d,"seq":%d,"threads":{},"top":{"mark":"m%d"}}]}\n' % (seq, start, seq, seq)
    (d / ('%d.json' % start)).write_text(body, encoding='utf-8')
    return body.strip()


def write_head(board, seq):
    (board / 'summary.json').write_text('{"seq":%d,"mark":"m%d","threads":{}}\n' % (seq, seq), encoding='utf-8')


def deltas(raw):
    """The delta events in what the line brought, as dicts."""
    out = []
    for block in raw.split(b'\n\n'):
        lines = block.split(b'\n')
        if b'event: delta' in lines:
            data = b'\n'.join(l[6:] for l in lines if l.startswith(b'data: '))
            out.append(json.loads(data))
    return out


class Delta(SseResume):
    def test_the_change_rides_on_the_line_before_changed(self):
        d = self.board('delta', '7')
        write_head(d, 7)
        s = self.open('delta', '&since=7')
        s.read_until(b'event: alive\ndata: 7\n\n')
        run = write_change(d, 7, 9)
        write_head(d, 9)
        write_pulse(d, '9')
        got = s.read_until(b'id: 9\ndata: changed\n\n')
        self.assertLess(got.index(b'event: delta\n'), got.index(b'id: 9\ndata: changed\n\n'), 'the delta comes before "changed"')
        (one,) = deltas(got)
        self.assertEqual(one['run'], json.loads(run))
        self.assertTrue(one['head'].startswith('{"seq":9,"mark":"m9"'))
        # and the next one, from the number it told last
        run2 = write_change(d, 9, 12)
        write_head(d, 12)
        write_pulse(d, '12')
        got = s.read_until(b'id: 12\ndata: changed\n\n')
        self.assertEqual(deltas(got)[0]['run'], json.loads(run2))

    def test_a_page_coming_back_gets_the_change_from_where_it_was(self):
        d = self.board('back', '20')
        write_head(d, 20)
        run = write_change(d, 15, 20)
        s = self.open('back', '&since=15')
        got = s.read_until(b'id: 20\ndata: changed\n\n')
        self.assertEqual(deltas(got)[0]['run'], json.loads(run))
        # the browser's own reconnect says it in the header
        s = self.open('back', headers=[('Last-Event-ID', '15')])
        got = s.read_until(b'id: 20\ndata: changed\n\n')
        self.assertEqual(deltas(got)[0]['run'], json.loads(run))

    def test_no_delta_when_it_would_not_lead_to_the_number_or_is_not_safe(self):
        cases = {
            'nofile': None,                                                                      # no changes/<from>.json
            'stale': '{"seq":31,"entries":[{"from":30,"seq":31}]}\n',                           # leads to another number
            'big': '{"seq":32,"entries":[{"from":30,"seq":32,"x":"%s"}]}\n' % ('a' * 70000),    # too big for the line
            'lines': '{"seq":32,"entries":[\n{"from":30,"seq":32}]}\n',                         # two lines: not one SSE data line
            'nohead': '{"seq":32,"entries":[{"from":30,"seq":32}]}\n',                          # no summary head to give with it
            'oldhead': '{"seq":32,"entries":[{"from":30,"seq":32}]}\n',                         # a head of another number
            'noentries': '{"seq":32,"entries":{"from":30}}\n',                                  # entries not a list
            'notjson': '{"seq":32,"entries":[{"from":30,"seq":32}]\n',                          # cut
        }
        for name, text in cases.items():
            with self.subTest(name):
                d = self.board('no-' + name, '30')
                if name != 'nohead':
                    write_head(d, 31 if name == 'oldhead' else 32)
                if text is not None:
                    write_change(d, 30, 32, text)
                s = self.open('no-' + name, '&since=30')
                s.read_until(b'event: alive\ndata: 30\n\n')
                write_pulse(d, '32')
                got = s.read_until(b'id: 32\ndata: changed\n\n')
                self.assertIn(b'id: 32\ndata: changed\n\n', got)
                self.assertNotIn(b'event: delta', got, name)

    def test_a_burst_comes_in_one_delta_built_from_changes_json(self):
        """When the page is more numbers behind than changes/<told>.json covers, the server builds the run from
        changes.json (the last changes, each naming the number it starts from), as one delta."""
        d = self.board('burst', '100')
        write_head(d, 100)
        s = self.open('burst', '&since=100')
        s.read_until(b'event: alive\ndata: 100\n\n')
        entries = [{'from': 100 + i, 'seq': 101 + i, 'threads': {}, 'top': {'mark': 'x%d' % i}} for i in range(50)]
        write_change(d, 100, 101, '{"seq":101,"entries":[%s]}\n' % json.dumps(entries[0], separators=(',', ':')))   # only its own entry
        (d / 'changes.json').write_text(json.dumps({'seq': 150, 'mark': 'mm', 'entries': entries}, separators=(',', ':')) + '\n', encoding='utf-8')
        write_head(d, 150)
        write_pulse(d, '150')
        got = s.read_until(b'id: 150\ndata: changed\n\n')
        (one,) = deltas(got)
        self.assertEqual(one['run']['seq'], 150)
        self.assertEqual([e['seq'] for e in one['run']['entries']], list(range(101, 151)))

    def test_no_delta_from_changes_json_with_a_gap_or_too_big(self):
        for name, entries in (('gap', [{'from': 200, 'seq': 201}, {'from': 202, 'seq': 203}]),
                              ('huge', [{'from': 200 + i, 'seq': 201 + i, 'x': 'a' * 2000} for i in range(40)]),
                              ('past', [{'from': 200, 'seq': 205}]),
                              ('strs', [{'from': '200', 'seq': '203'}]),
                              ('bools', [{'from': 200, 'seq': True}])):
            with self.subTest(name):
                d = self.board('cj-' + name, '200')
                top = 203
                write_head(d, top)
                s = self.open('cj-' + name, '&since=200')
                s.read_until(b'event: alive\ndata: 200\n\n')
                if name == 'huge':
                    top = entries[-1]['seq']
                    write_head(d, top)
                (d / 'changes.json').write_text(json.dumps({'seq': top, 'mark': 'mm', 'entries': entries}) + '\n', encoding='utf-8')
                write_pulse(d, str(top))
                got = s.read_until(b'id: %d\ndata: changed\n\n' % top)
                self.assertIn(b'id: %d\ndata: changed\n\n' % top, got)
                self.assertNotIn(b'event: delta', got, name)

    def test_a_changes_json_too_big_to_read_gives_no_delta(self):
        d = self.board('cj-big', '300')
        write_head(d, 301)
        s = self.open('cj-big', '&since=300')
        s.read_until(b'event: alive\ndata: 300\n\n')
        (d / 'changes.json').write_text(json.dumps({'seq': 301, 'entries': [{'from': 300, 'seq': 301}], 'pad': 'a' * 400000}), encoding='utf-8')
        write_pulse(d, '301')
        got = s.read_until(b'id: 301\ndata: changed\n\n')
        self.assertNotIn(b'event: delta', got)

    def test_a_page_that_knows_nothing_yet_gets_no_delta(self):
        d = self.board('fresh', '40')
        write_head(d, 40)
        write_change(d, 39, 40)
        s = self.open('fresh')                                     # no since: a page that opened anew reads whole
        got = s.read_until(b'id: 40\ndata: changed\n\n')
        self.assertNotIn(b'event: delta', got)

    def test_a_board_without_numbers_gets_what_it_always_got(self):
        d = self.board('plain', None)
        write_change(d, 39, 40)
        s = self.open('plain', '&since=39')
        self.assertEqual(s.read_for(0.5), b'data: changed\n\n')


class AdvDelta(SseResume):
    """The hostile review's cases (each asserts the safe outcome)."""

    def test_a_change_file_that_is_not_json_on_its_own_never_chooses_the_head(self):
        """A file that is not one JSON value on its own could close the run early and add keys of its own to the
        event: a second "head" wins in JSON.parse. Safe: no delta unless the run is one JSON object."""
        d = self.board('notjson', '50')
        write_head(d, 52)                       # the summary's real head: mark m52
        forged = '{"seq":52,"entries":[{"from":50,"seq":52,"threads":{},"top":{"mark":"aaaaaaaa"}}]},"head":"{\\"seq\\":52,\\"mark\\":\\"aaaaaaaa\\"}"'
        write_change(d, 50, 52, forged + '\n')
        s = self.open('notjson', '&since=50')
        s.read_until(b'event: alive\ndata: 50\n\n')
        write_pulse(d, '52')
        got = s.read_until(b'id: 52\ndata: changed\n\n')
        self.assertIn(b'id: 52\ndata: changed\n\n', got)
        for one in deltas(got):
            self.assertTrue(one['head'].startswith('{"seq":52,"mark":"m52"'),
                            'the delta says the summary head is %r; the summary says {"seq":52,"mark":"m52"' % one['head'])

    def test_two_moves_in_one_poll_give_one_delta_from_the_number_told(self):
        """The pulse moves twice between two looks; the delta starts at the number the line told last (the page's),
        not at the middle one, and leads to the last."""
        d = self.board('twice', '60')
        write_head(d, 60)
        s = self.open('twice', '&since=60')
        s.read_until(b'event: alive\ndata: 60\n\n')
        self.mod.SSE_POLL_S = 0.6
        try:
            time.sleep(0.15)
            run = write_change(d, 60, 62, '{"seq":62,"entries":[{"from":60,"seq":61},{"from":61,"seq":62}]}\n')
            write_change(d, 61, 62, '{"seq":62,"entries":[{"from":61,"seq":62}]}\n')
            write_head(d, 61)
            write_pulse(d, '61')
            write_head(d, 62)
            write_pulse(d, '62')
            got = s.read_until(b'id: 62\ndata: changed\n\n', timeout=4)
        finally:
            self.mod.SSE_POLL_S = 0.1
        self.assertNotIn(b'id: 61\n', got)
        (one,) = deltas(got)
        self.assertEqual(one['run'], json.loads(run))

    def test_nothing_in_the_files_breaks_the_line(self):
        """A CR in the change file gives no delta; a head cut inside a character, a NUL or a quote in the head come
        out escaped, on one data line."""
        d = self.board('frame', '70')
        (d / 'summary.json').write_bytes(b'{"seq":72,"mark":"m72","threads":{"\x00\r\n\\"' + 'ש'.encode() * 20 + b'"}}')
        write_change(d, 70, 72, '{"seq":72,"entries":[{"from":70,"seq":72,"threads":{},"top":{"mark":"m72"}}]}\r\n')
        s = self.open('frame', '&since=70')
        s.read_until(b'event: alive\ndata: 70\n\n')
        write_pulse(d, '72')
        got = s.read_until(b'id: 72\ndata: changed\n\n')
        self.assertNotIn(b'event: delta', got, 'a CR before the newline: refused')
        write_change(d, 72, 74, '{"seq":74,"entries":[{"from":72,"seq":74,"threads":{},"top":{"mark":"m74"}}]}\n')
        (d / 'summary.json').write_bytes(b'{"seq":74,"mark":"m74","threads":{"\x00\r\n\\"' + 'ש'.encode() * 20 + b'"}}')
        write_pulse(d, '74')
        got = s.read_until(b'id: 74\ndata: changed\n\n')
        block = got.split(b'\n\n')[0]
        self.assertTrue(block.startswith(b'event: delta\ndata: '))
        self.assertEqual(block.count(b'\n'), 1, 'one data line')
        self.assertNotIn(b'\r', block)
        self.assertNotIn(b'\x00', block)
        (one,) = deltas(got)
        self.assertTrue(one['head'].startswith('{"seq":74,"mark":"m74"'))

    def test_a_change_file_that_is_a_link_out_of_the_board_is_not_sent(self):
        """changes/<n>.json is a symlink to a file outside the boards folder: its bytes never reach the line."""
        d = self.board('link', '80')
        write_head(d, 82)
        outside = self.root.parent / ('.outside-%s.json' % self.root.name)
        outside.write_text('{"seq":82,"entries":[{"from":80,"seq":82,"secret":"outside the board"}]}\n')
        self.addCleanup(outside.unlink)
        (d / 'changes').mkdir()
        (d / 'changes' / '80.json').symlink_to(outside)
        s = self.open('link', '&since=80')
        s.read_until(b'event: alive\ndata: 80\n\n')
        write_pulse(d, '82')
        got = s.read_until(b'id: 82\ndata: changed\n\n')
        self.assertIn(b'id: 82\ndata: changed\n\n', got)
        self.assertNotIn(b'outside the board', got)

    def test_a_change_file_that_is_a_fifo_does_not_hang_the_line(self):
        import os
        d = self.board('fifo', '90')
        write_head(d, 92)
        (d / 'changes').mkdir()
        os.mkfifo(d / 'changes' / '90.json')
        s = self.open('fifo', '&since=90')
        s.read_until(b'event: alive\ndata: 90\n\n')
        write_pulse(d, '92')
        got = s.read_until(b'id: 92\ndata: changed\n\n', timeout=3)
        self.assertIn(b'id: 92\ndata: changed\n\n', got, 'the line hung on a fifo')


if __name__ == '__main__':
    unittest.main()
