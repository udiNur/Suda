#!/usr/bin/env python3
"""Hostile review of the context-full detection (live_hook.context_of). Each test asserts the CORRECT outcome."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import test_live
from test_live import PANE, HOOK, live_hook

FILL = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'x' * 2000}})


def used(n, text='ok', **extra):
    return json.dumps(dict({'type': 'assistant', 'message': {'model': 'claude-opus-5-5', 'role': 'assistant',
                       'content': [{'type': 'text', 'text': text}],
                       'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 1000, 'cache_read_input_tokens': n - 1002}}}, **extra),
                      ensure_ascii=False)


def err(text, **extra):
    return json.dumps(dict({'type': 'assistant', 'isApiErrorMessage': True, 'error': 'invalid_request',
                            'message': {'model': '<synthetic>', 'role': 'assistant', 'content': [{'type': 'text', 'text': text}],
                                        'usage': {'input_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}}}, **extra))


def user(text):
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text}})


BOUNDARY = json.dumps({'type': 'system', 'subtype': 'compact_boundary', 'content': 'Conversation compacted',
                       'compactMetadata': {'trigger': 'manual', 'preTokens': 950000}})
SUMMARY = json.dumps({'type': 'user', 'isCompactSummary': True, 'message': {'role': 'user', 'content': 'This session is being continued...'}})


class Adv(test_live.Hook):
    def write(self, *lines, filler=300, name='s.jsonl', sep='\n'):
        path = Path(self.tmp.name) / name
        path.write_text(sep.join([FILL] * filler + list(lines)) + sep, encoding='utf-8')
        return str(path)

    def idle_agent(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle'}])

    # ── false red ──
    def test_a_subagents_prompt_too_long_is_not_the_main_agent_stuck(self):
        self.idle_agent()
        self.fire('Stop', transcript_path=self.write(used(200_000), err('Prompt is too long', isSidechain=True)))
        self.assertEqual(self.agent()['state'], 'idle')

    def test_a_subagents_small_usage_does_not_hide_a_full_main_context(self):
        self.idle_agent()
        self.fire('Stop', transcript_path=self.write(used(950_000), used(30_000, isSidechain=True)))
        self.assertEqual(self.agent().get('tokens'), 950_000)

    def test_after_compact_an_overloaded_error_is_not_context(self):
        """too long -> /compact -> a new request ends on 529: the old error is from before the compaction."""
        self.idle_agent()
        path = self.write(err('Prompt is too long'), BOUNDARY, SUMMARY, user('go on'), err('API Error: 529 Overloaded'))
        self.fire('StopFailure', error='overloaded', transcript_path=path)
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'limit'))

    def test_after_compact_a_500_is_not_context(self):
        self.idle_agent()
        path = self.write(used(950_000), BOUNDARY, SUMMARY, user('go on'), err('API Error: 500 Internal server error'))
        self.fire('StopFailure', error='server_error', transcript_path=path)
        self.assertEqual(self.agent()['why'], 'error')

    def test_red_clears_once_he_compacted_and_it_idles(self):
        """/compact fires no UserPromptSubmit; idle_prompt then keeps 'stuck' forever, tuios's idle never corrects it."""
        self.idle_agent()
        path = self.write(err('Prompt is too long'))
        self.fire('StopFailure', error='invalid_request', transcript_path=path)
        self.assertEqual(self.agent()['why'], 'context')
        with open(path, 'a') as f:
            f.write(BOUNDARY + '\n' + SUMMARY + '\n')
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle', 'agent_state_at': int((time.time() + 5) * 1e9)}])
        self.fire('Notification', notification_type='idle_prompt', transcript_path=path)
        self.assertEqual(self.agent()['state'], 'idle')

    def test_a_raw_line_separator_in_the_last_reply_does_not_fall_back_to_an_old_one(self):
        """JSON.stringify leaves U+2028 / U+0085 raw; str.splitlines() splits on them."""
        self.idle_agent()
        for ch in (' ', '\x85'):
            self.fire('Stop', transcript_path=self.write(used(950_000), BOUNDARY, SUMMARY, user('hi'), used(60_000, text='a' + ch + 'b')))
            self.assertEqual(self.agent()['state'], 'idle', repr(ch))

    def test_a_short_transcripts_first_line_is_read(self):
        self.idle_agent()
        self.fire('Stop', transcript_path=self.write(used(950_000), json.dumps({'type': 'system', 'subtype': 'stop_hook_summary'}), filler=0))
        self.assertEqual(self.agent()['why'], 'near')       # 900K+: near (red, continue allowed); only 'Prompt is too long' is full

    def test_tuios_near_is_not_published_as_full(self):
        """tuios near=true (not full) is published as why=context, which the page now calls 'full, needs /compact'
        and the server refuses continue for: an agent merely near its end loses continue."""
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle', 'context': {'near': True}}])
        self.fire('Stop', transcript_path=self.write(used(150_000)))
        self.assertNotEqual(self.agent()['why'], 'context')

    # ── cost / hangs ──
    def test_a_fifo_transcript_does_not_hang_the_hook(self):
        self.idle_agent()
        fifo = Path(self.tmp.name) / 'f.jsonl'
        os.mkfifo(fifo)
        env = dict(self.env)
        t = time.monotonic()
        try:
            subprocess.run([sys.executable, '-I', '-S', str(HOOK)], input=json.dumps({'hook_event_name': 'Stop', 'transcript_path': str(fifo)}),
                           env=env, capture_output=True, text=True, timeout=4)
        except subprocess.TimeoutExpired:
            self.fail('hook blocked on a FIFO transcript for > 4 s')
        self.assertLess(time.monotonic() - t, 4)

    def test_never_reads_more_than_the_tail(self):
        """A device (symlink x.jsonl -> /dev/zero) or a file appended while read: f.read() is unbounded."""
        class Endless(io.RawIOBase):
            served = 0

            def readable(self):
                return True

            def seekable(self):
                return True

            def seek(self, off, whence=0):
                return 0          # a character device reports size 0

            def tell(self):
                return 0

            def readinto(self, b):
                if Endless.served > 8 * 1024 * 1024:
                    return 0       # stop the test (a real /dev/zero never does)
                n = len(b)
                b[:n] = b'\0' * n
                Endless.served += n
                return n
        with mock.patch.object(live_hook, 'open', create=True, side_effect=lambda *a, **k: io.BufferedReader(Endless())):
            live_hook.context_of('/tmp/zero.jsonl')
        self.assertLessEqual(Endless.served, live_hook.TRANSCRIPT_TAIL + 65536)

    # ── should hold ──
    def test_crlf_and_casing_still_red(self):
        self.idle_agent()
        self.fire('StopFailure', error='invalid_request',
                  transcript_path=self.write(err('API Error: 400 prompt is too long: 1012345 tokens > 1000000 maximum'), sep='\r\n'))
        self.assertEqual(self.agent()['why'], 'context')

    def test_directory_and_unreadable_are_quiet(self):
        self.idle_agent()
        d = Path(self.tmp.name) / 'd.jsonl'
        d.mkdir()
        self.fire('Stop', transcript_path=str(d))
        p = Path(self.write(err('Prompt is too long'), name='p.jsonl'))
        p.chmod(0)
        self.fire('Stop', transcript_path=str(p))
        self.assertEqual(self.agent()['state'], 'idle')

    def test_old_too_long_then_user_lines_only(self):
        self.idle_agent()
        self.fire('Stop', transcript_path=self.write(err('Prompt is too long'), BOUNDARY, SUMMARY, user('a'), user('b')))
        self.assertEqual(self.agent()['state'], 'idle')


if __name__ == '__main__':
    unittest.main()
