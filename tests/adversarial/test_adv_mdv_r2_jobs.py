"""Hostile review, round 2: jobs keyed by (st_dev, st_ino), and a slot that is never given back.

- Editors (and MDS, and git) save a note by writing a new file and renaming it: a new inode. While a translation
  runs, a save makes the running job invisible (the page says nothing runs) and a second POST starts a second job
  on the same file: two bills, two writers of one translation.
- start_job registers the job and opens the folder before the thread starts; when the thread cannot start (out of
  threads) the job stays "running" for ever: it holds one of MAX_JOBS and that file can never be translated again,
  and the folder's descriptor leaks.
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
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, model, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402


class InodeKey(unittest.TestCase):
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

    def post(self, path):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        c.request('POST', '/mdv/api/translate', body=json.dumps({'path': str(path)}),
                  headers={'Host': '127.0.0.1:%d' % self.port, 'Content-Type': 'application/json'})
        r = c.getresponse()
        r.read()
        c.close()

    def doc(self, path):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('GET', '/mdv/api/doc?path=' + quote(str(path)), headers={'Host': '127.0.0.1:%d' % self.port})
        j = json.loads(c.getresponse().read())
        c.close()
        return j

    def test_a_save_during_a_translation_does_not_start_a_second_job(self):
        note = self.root / 'saved.md'
        note.write_text('# Saved\n\nFirst words.\n')
        calls, go = [], threading.Event()
        real_stream = model.stream

        def gated(system, messages, *a, **k):
            calls.append(1)
            go.wait(15)
            yield from real_stream(system, messages, *a, **k)

        model.stream = gated
        threads = []
        try:
            threads.append(threading.Thread(target=self.post, args=(note,)))
            threads[-1].start()
            for _ in range(100):
                if calls:
                    break
                time.sleep(0.05)
            tmp = self.root / '.saved.md.swp'
            tmp.write_text('# Saved\n\nFirst words, edited.\n')
            os.replace(tmp, note)                       # how an editor saves: a new inode
            translating = self.doc(note).get('translating')
            threads.append(threading.Thread(target=self.post, args=(note,)))
            threads[-1].start()
            time.sleep(1.0)
            started = len(calls)
        finally:
            go.set()
            for t in threads:
                t.join(20)
            model.stream = real_stream
        self.assertTrue(translating, 'after a save the page is told no translation runs')
        self.assertEqual(started, 1, 'a second job ran on the same file at once (%d model calls)' % started)


class StartFailure(unittest.TestCase):
    def test_a_thread_that_cannot_start_releases_its_job_and_folder(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(os.path.realpath(t))
            note = base / 'n.md'
            note.write_text('# n\n\nwords\n')
            key = server.job_key(note)
            self.addCleanup(server.JOBS.pop, key, None)
            fds = len(os.listdir('/dev/fd'))
            orig = server.threading.Thread

            class NoThread(orig):
                def start(self):
                    raise RuntimeError("can't start new thread")

            server.threading.Thread = NoThread
            try:
                with self.assertRaises(RuntimeError):
                    server.start_job(note, base, False)
            finally:
                server.threading.Thread = orig
            job = server.job_of(note)
            leaked = len(os.listdir('/dev/fd')) - fds
            self.assertTrue(job is None or job.done, 'the job stays running for ever and holds a MAX_JOBS slot')
            self.assertEqual(leaked, 0, 'the folder descriptor leaked')


if __name__ == '__main__':
    unittest.main()
