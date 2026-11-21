"""Hostile review: resources.

- The live-reload stream re-reads the note through its path every 0.4 s, with no size cap and following symlinks.
  A note replaced by a symlink after it was opened (a git pull in a repo root, say) to a FIFO hangs the thread for
  good; to /dev/zero or a huge file it reads without end. Only the open was checked.
- No socket timeout: a client that opens a connection and sends nothing (or a POST that never sends its body)
  holds a thread for ever, and ThreadingHTTPServer makes threads without a limit.
- Translation jobs have no global limit: every file gets its own job, all calling the model at once.
Safe outcomes asserted below."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, model, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class WatchKey(unittest.TestCase):
    def test_watch_key_does_not_follow_a_symlink_planted_after_open(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(os.path.realpath(t))
            root = base / 'root'
            root.mkdir()
            note = root / 'w.md'
            note.write_text('# hi\n')
            real, _ = core.resolve(str(note), [root], base)
            fifo = base / 'pipe'
            os.mkfifo(fifo)
            note.unlink()
            note.symlink_to(fifo)
            th = threading.Thread(target=server.watch_key, args=(real,), daemon=True)
            th.start()
            th.join(3)
            hung = th.is_alive()
            if hung:   # let it go: a writer that closes at once gives the reader its end of file
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                    os.close(fd)
                except OSError:
                    pass
                th.join(3)
            self.assertFalse(hung, 'watch_key blocked on a FIFO that a symlink put in place of the note')

    def test_watch_key_reads_a_bounded_amount(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(os.path.realpath(t))
            note = base / 'grown.md'
            note.write_text('# hi\n')
            real = note
            with open(note, 'r+b') as f:               # grows past MAX_DOC_BYTES after it was opened
                f.truncate(core.MAX_DOC_BYTES * 20)
            read = []
            orig = Path.read_text

            def spy(self, *a, **k):
                s = orig(self, *a, **k)
                read.append(len(s))
                return s

            Path.read_text = spy
            try:
                server.watch_key(real)
            finally:
                Path.read_text = orig
            self.assertLessEqual(max(read or [0]), core.MAX_DOC_BYTES,
                                 'one tick of the live stream read %d chars' % max(read or [0]))


class Limits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        (base / 'roots.json').write_text('{"roots": []}')
        cls.cfg = server.Config(base / 'roots.json', [cls.root], base, set())
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, cls.cfg)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def test_idle_connections_time_out(self):
        # stdlib StreamRequestHandler applies `timeout` to the socket; None means a silent client holds a thread
        t = getattr(self.srv.RequestHandlerClass, 'timeout', None)
        self.assertIsNotNone(t, 'no socket timeout: slowloris and a POST that never sends its body hold threads')
        self.assertLessEqual(t, 120)

    def test_model_calls_are_capped_across_files(self):
        peak, now, lock = [0], [0], threading.Lock()
        real_stream = model.stream

        def counting(system, messages, *a, **k):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            try:
                time.sleep(0.5)
                yield from real_stream(system, messages, *a, **k)
            finally:
                with lock:
                    now[0] -= 1

        notes = []
        for i in range(10):
            p = self.root / ('many%d.md' % i)
            p.write_text('# Note %d\n\nSome text %d.\n' % (i, i))
            notes.append(p)

        def post(p):
            c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=60)
            c.request('POST', '/mdv/api/translate', body=json.dumps({'path': str(p)}),
                      headers={'Host': '127.0.0.1:%d' % self.port, 'Content-Type': 'application/json'})
            c.getresponse().read()
            c.close()

        model.stream = counting
        try:
            ths = [threading.Thread(target=post, args=(p,)) for p in notes]
            for th in ths:
                th.start()
            for th in ths:
                th.join(60)
        finally:
            model.stream = real_stream
        self.assertLessEqual(peak[0], 4, '%d model calls ran at once, one per file, with no cap' % peak[0])


if __name__ == '__main__':
    unittest.main()
