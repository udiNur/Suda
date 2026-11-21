"""The model call out of process (suda-fixes m149): the board server's Python (Homebrew python3) has no anthropic SDK
and may not get one (PEP 668), so the viewer inside it calls the model through a worker, `uv run --with anthropic
python -m mdv.worker`, that streams the reply back as JSON lines. The board process gains no dependency and never
holds the key. Checked with the stand-in model inside the worker."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import sys
import time
import unittest
from pathlib import Path

MDV = _paths.APP / 'mdv'
sys.path.insert(0, str(MDV))
from mdv import core, model  # noqa: E402
from mdv.testing import prepare  # noqa: E402
prepare()

WORKER = json.dumps([sys.executable, '-m', 'mdv.worker'])


class Worker(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        os.environ.update(MDV_FAKE_MODEL='1', MDV_WORKER='1', MDV_WORKER_CMD=WORKER, PYTHONPATH=str(MDV))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def test_a_translation_runs_through_the_worker(self):
        out = core.translate_blocks(['# Title', 'Hello there', '```\ncode\n```'], 'en', 'he', None, 'm', model.stream)
        self.assertEqual(out['blocks'], ['# Title [HE]', 'Hello there [HE]', '```\ncode\n```'])
        self.assertEqual(out['failed'], [])

    def test_the_worker_is_used_when_the_sdk_is_missing(self):
        os.environ.pop('MDV_WORKER')
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c', 'import sys; print(\'{"t": "from the worker"}\'); print(\'{"end": true}\')'])
        real = model.sdk_here
        model.sdk_here = lambda: False
        os.environ.pop('MDV_FAKE_MODEL')
        try:
            self.assertEqual(''.join(model.stream('s', [{'role': 'user', 'content': 'x'}])), 'from the worker')
        finally:
            model.sdk_here = real

    def test_a_failing_worker_is_an_error_without_the_key(self):
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c', 'import sys; sys.stderr.write("boom sk-ant-api03-SECRET\\n"); sys.exit(3)'])
        with self.assertRaises(RuntimeError) as c:
            ''.join(model.stream('s', [{'role': 'user', 'content': 'x'}]))
        self.assertIn('boom', str(c.exception))
        self.assertNotIn('SECRET', model.clean_error(c.exception))
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c', 'print(\'{"error": "the model declined"}\')'])
        with self.assertRaises(RuntimeError) as c:
            ''.join(model.stream('s', [{'role': 'user', 'content': 'x'}]))
        self.assertIn('declined', str(c.exception))

    def test_a_reply_cut_short_is_an_error(self):
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c', 'print(\'{"t": "half"}\')'])
        with self.assertRaises(RuntimeError):
            ''.join(model.stream('s', [{'role': 'user', 'content': 'x'}]))

    def test_a_stream_closed_early_stops_its_worker(self):
        mark = Path(self.env.get('TMPDIR', '/tmp')) / ('mdv-worker-%d.pid' % os.getpid())
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c',
            'import os, time; open(%r, "w").write(str(os.getpid())); print(\'{"t": "one"}\', flush=True); time.sleep(60)' % str(mark)])
        it = model.stream('s', [{'role': 'user', 'content': 'x'}])
        self.assertEqual(next(it), 'one')
        it.close()
        pid = int(mark.read_text())
        mark.unlink()
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_the_request_goes_on_stdin_not_the_command_line(self):
        os.environ['MDV_WORKER_CMD'] = json.dumps([sys.executable, '-c',
            'import sys, json, os; r = json.load(sys.stdin); print(json.dumps({"t": r["system"] + "|" + r["messages"][0]["content"] + "|" + str(r["max_tokens"]) + "|" + str(len(sys.argv))})); print(\'{"end": true}\')'])
        self.assertEqual(''.join(model.stream('SYS', [{'role': 'user', 'content': 'secret note text'}], 99)), 'SYS|secret note text|99|1')


if __name__ == '__main__':
    unittest.main()
