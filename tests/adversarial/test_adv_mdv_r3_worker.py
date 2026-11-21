"""Hostile review, round 3: the model worker (`uv run --with anthropic python -m mdv.worker`).

- stderr is a pipe nobody reads while the reply streams: a worker (or uv, or the SDK's warnings) that writes more
  than the pipe holds (64 KB) blocks on stderr, while the viewer waits on stdout. Both wait for ever: the job never
  ends, it holds one of MAX_JOBS (or a summary holds one of MAX_SUMMARIES and a board thread).
- No deadline at all on the worker: a uv that hangs (its cache lock, the network) or a model that never answers
  holds the job the same way. The test asks for an idle limit (model.WORKER_IDLE, seconds without a line); a fix
  may name it differently, the outcome asserted is that a silent worker is stopped.
- Closing the stream kills `uv`, not the python it started: under the real command the worker itself (the one with
  the key and the open model call) lives on.
Stand-in model only (MDV_FAKE_MODEL=1); the workers here are short python one-liners."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

MDV = _paths.APP / 'mdv'
sys.path.insert(0, str(MDV))
from mdv import model  # noqa: E402

UV = shutil.which('uv')


def run_with_deadline(fn, seconds):
    out = {}

    def go():
        try:
            out['value'] = fn()
        except BaseException as e:  # noqa: BLE001
            out['error'] = e

    th = threading.Thread(target=go, daemon=True)
    th.start()
    th.join(seconds)
    return th.is_alive(), out


class Worker(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        os.environ.update(MDV_FAKE_MODEL='1', MDV_WORKER='1', PYTHONPATH=str(MDV))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def test_a_chatty_stderr_does_not_deadlock_the_reply(self):
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c',
            'import sys; sys.stdin.read(); sys.stderr.write("w" * 200000); sys.stderr.flush(); '
            'print(\'{"t": "done"}\', flush=True); print(\'{"end": true}\', flush=True)'])
        hung, out = run_with_deadline(lambda: ''.join(model.stream('s', [{'role': 'user', 'content': 'x'}])), 10)
        self.assertFalse(hung, 'a worker that wrote 200 KB to stderr and the viewer wait on each other for ever')
        self.assertEqual(out.get('value'), 'done')

    def test_a_silent_worker_is_stopped(self):
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c', 'import time; time.sleep(120)'])
        limit = getattr(model, 'WORKER_IDLE', None)
        self.assertIsNotNone(limit, 'no deadline on the worker: a hung uv or model holds its job for ever')
        model.WORKER_IDLE = 1
        try:
            hung, out = run_with_deadline(lambda: ''.join(model.stream('s', [{'role': 'user', 'content': 'x'}])), 8)
        finally:
            model.WORKER_IDLE = limit
        self.assertFalse(hung)
        self.assertIn('error', out)

    @unittest.skipUnless(UV, 'uv is not installed')
    def test_closing_the_stream_stops_the_python_under_uv(self):
        with tempfile.TemporaryDirectory() as t:
            mark = Path(t) / 'pid'
            os.environ['MDV_WORKER_CMD'] = json.dumps([UV, 'run', '--quiet', '--no-project', 'python', '-c',
                'import os, time; open(%r, "w").write(str(os.getpid())); print(\'{"t": "one"}\', flush=True); '
                'time.sleep(60)' % str(mark)])
            it = model.stream('s', [{'role': 'user', 'content': 'x'}])
            self.assertEqual(next(it), 'one')
            it.close()
            pid = int(mark.read_text())
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            if alive:
                os.kill(pid, 9)
            self.assertFalse(alive, 'the worker python under uv outlived its stream (uv was killed, not its child)')


if __name__ == '__main__':
    unittest.main()
