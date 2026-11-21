#!/usr/bin/env python3
"""The live hook (live_hook.py), run as Claude Code runs it: a JSON event on stdin, the pane in the environment.
tuios is stood in for by a script that prints what `tuios list-agents --all-sessions --json` would."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = _paths.APP
HOOK = ROOT / 'live_hook.py'
sys.path.insert(0, str(ROOT))
import live_hook  # noqa: E402

PANE = '11111111-2222-4333-8444-555555555555'      # (an invented pane id)
OTHER = '060529f9-1111-2222-3333-444455556666'
TUIOS = 'import json,sys\nprint(open(sys.argv[1]).read())\n'


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='threads-live-')
        root = Path(self.tmp.name)
        self.dir, self.board = root / 'live', root / 'boards' / 'threads'
        self.board.mkdir(parents=True)
        self.out = self.board / 'live.json'
        self.tuios_file = root / 'tuios.json'
        (root / 'tuios.py').write_text(TUIOS)
        self.agents([])
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('TUIOS_', 'THREADS_'))}
        self.env.update(THREADS_LIVE_DIR=str(self.dir), THREADS_LIVE_OUT=str(self.out), TUIOS_PANE_ID=PANE, TUIOS_SESSION='tools',
                        THREADS_LIVE_TUIOS_CMD=shlex.join([sys.executable, str(root / 'tuios.py'), str(self.tuios_file)]))
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it, in the hook's
        # process and in this one (what_of is also called here)
        (root / 'cfg/threads').mkdir(parents=True)
        (root / 'cfg/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')
        self.env['THREADS_CONFIG_DIR'] = str(root / 'cfg')
        from unittest import mock
        patched = mock.patch.dict(os.environ, THREADS_CONFIG_DIR=str(root / 'cfg'))
        patched.start()
        self.addCleanup(patched.stop)
        live_hook._TABLE = None
        self.addCleanup(setattr, live_hook, '_TABLE', None)

    def tearDown(self):
        self.tmp.cleanup()

    def agents(self, rows):
        self.tuios_file.write_text(json.dumps({'agents': rows}))
        snap = self.dir / '.tuios.json'
        if snap.exists():
            snap.unlink()       # the next hook reads tuios again

    def fire(self, event, pane=PANE, **data):
        env = dict(self.env, TUIOS_PANE_ID=pane)
        r = subprocess.run([sys.executable, '-I', '-S', str(HOOK)], input=json.dumps(dict(hook_event_name=event, **data)),
                           env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))
        return r

    def rec(self, pane=PANE):
        return json.loads((self.dir / (pane + '.json')).read_text())

    def live(self):
        return json.loads(self.out.read_text())

    def agent(self, pane=PANE):
        return next(a for a in self.live()['agents'] if a['pane'] == pane)

    def bash(self, command, description='', pane=PANE):
        return self.fire('PreToolUse', pane=pane, tool_name='Bash', tool_input={'command': command, 'description': description})

    # ── the thread an agent works on ─────────────────────────────────────────

    def test_the_thread_is_the_last_threads_command_that_writes_into_one(self):
        cases = {
            'threads say suda --from fork - --state working --note x': ('suda', None),
            'cd ~/Projects/threads && threads state shopflow working --note "x" --by worker-b': ('shopflow', 'worker-b'),
            'threads task set snap-linux 3 done --note ok': ('snap-linux', None),
            'threads task add sim-lab "x" --owner me': ('sim-lab', None),
            'threads show suda': (None, None),           # reading a thread is not working on it
            'threads tasks suda': (None, None),
            'threads pending': (None, None),
            'THREADS_SLUG=e2e threads say demo-1 --from fork hi': (None, None),     # another board
            'threads say a1 --from fork x; threads say b2 --from fork y --by=w1': ('b2', 'w1'),
            '~/.local/bin/threads ask simbase "q?" --options "a,b"': ('simbase', None),
            'python3 threads.py say e2e-x --from fork x': ('e2e-x', None),
            'echo mythreads say x': (None, None),
            'threads say Bad_ID x': (None, None),
            None: (None, None),
        }
        for command, want in cases.items():
            self.assertEqual(live_hook.thread_of(command), want, command)

    def test_what_he_does_is_a_few_words_never_the_command(self):
        self.assertEqual(live_hook.what_of('Bash', {'command': 'curl -H "Authorization: Bearer s3cret" x', 'description': 'Fetch the PR'}), 'Fetch the PR')
        self.assertEqual(live_hook.what_of('Bash', {'command': 'export TOKEN=s3cret'}), 'מריץ פקודה')
        self.assertEqual(live_hook.what_of('Read', {'file_path': '/Users/x/.ssh/config'}), 'קורא config')
        self.assertEqual(live_hook.what_of('Edit', {'file_path': '/a/b/suda.html'}), 'עורך suda.html')
        self.assertEqual(live_hook.what_of('mcp__codegraph__codegraph_explore', {}), 'כלי codegraph')
        self.assertLessEqual(len(live_hook.what_of('Bash', {'description': 'x' * 500})), live_hook.WHAT_MAX)

    # ── the states, through the events ───────────────────────────────────────

    def test_a_turn_working_on_a_thread_then_resting(self):
        self.agents([{'window_id': PANE, 'name': 'worker-b', 'session': 'tools', 'state': 'working'}])
        self.fire('UserPromptSubmit', prompt='go')
        self.assertEqual(self.agent()['state'], 'working')
        self.bash('threads say suda --from fork - --state working --note x', 'Post to the thread')
        a = self.agent()
        self.assertEqual((a['state'], a['thread'], a['what'], a['name'], a['session']), ('working', 'suda', 'Post to the thread', 'worker-b', 'tools'))
        self.bash('python3 test_e2e.py', 'Run the e2e tests')
        self.assertEqual((self.agent()['thread'], self.agent()['what']), ('suda', 'Run the e2e tests'))     # the thread stays
        self.fire('Stop')
        a = self.agent()
        self.assertEqual((a['state'], a['what'], a['thread']), ('idle', '', 'suda'))
        self.assertEqual(oct(os.stat(self.dir / (PANE + '.json')).st_mode & 0o777), '0o600')
        self.assertEqual(oct(os.stat(self.dir).st_mode & 0o777), '0o700')

    def test_waiting_for_approval_and_back_to_work(self):
        self.fire('PreToolUse', tool_name='Bash', tool_input={'command': 'rm -rf x', 'description': 'Remove x'})
        self.fire('Notification', notification_type='permission_prompt', message='Claude needs your permission to use Bash')
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('waiting', 'approval'))
        self.fire('Notification', notification_type='idle_prompt', message='Claude is waiting for your input')
        self.assertEqual(self.agent()['state'], 'waiting', 'the idle reminder undid the approval it waits for')
        self.fire('PostToolUse', tool_name='Bash', tool_input={})        # he approved: the tool ran
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('working', ''))

    def test_a_limit_or_an_api_error_is_stuck(self):
        self.fire('UserPromptSubmit')
        self.fire('StopFailure', error_type='rate_limit')
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'limit'))
        self.fire('UserPromptSubmit')
        self.fire('StopFailure', error='server_error')
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'error'))

    def test_tuios_tells_a_limit_and_a_full_context_the_hook_cannot_see(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle', 'limit_resets': '3am'},
                     {'window_id': OTHER, 'name': 'worker-a', 'session': 'tools', 'state': 'done', 'context': {'near': True}}])
        self.fire('Stop')
        a, b = self.agent(), self.agent(OTHER)
        self.assertEqual((a['state'], a['why'], a['resets']), ('stuck', 'limit', '3am'))
        self.assertEqual((b['state'], b['why'], b['name'], b['thread']), ('stuck', 'near', 'worker-a', ''))     # tuios knows near, never full     # no hook yet: tuios alone

    def test_an_agent_tuios_has_not_judged_yet_is_at_rest_and_never_corrects_a_hook(self):
        """Thread suda m381: dots that came and went made the list jump. An agent tuios calls 'unknown' is shown
        at rest (not dropped); an agent whose own hook says it works stays working."""
        self.agents([{'window_id': OTHER, 'name': 'b1', 'session': 'tools', 'state': 'unknown', 'agent_state_at': int((time.time() + 5) * 1e9)},
                     {'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'unknown', 'agent_state_at': int((time.time() + 5) * 1e9)}])
        self.bash('python3 test_e2e.py', 'Run the tests')
        self.assertEqual(self.agent(OTHER)['state'], 'idle')
        self.assertEqual(self.agent()['state'], 'working')

    def transcript(self, *entries):
        """A transcript as Claude Code writes it: one JSON object a line, the newest last."""
        path = Path(self.tmp.name) / 'session.jsonl'
        filler = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'x' * 2000}})
        lines = [filler] * 3000          # a long transcript: only its tail is read
        for kind, value in entries:
            if kind == 'used':
                lines.append(json.dumps({'type': 'assistant', 'message': {'model': 'claude-opus-5-5', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}],
                                                                       'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 1000, 'cache_read_input_tokens': value - 1002}}}))
            elif kind == 'too-long':
                lines.append(json.dumps({'type': 'assistant', 'isApiErrorMessage': True, 'error': 'invalid_request',
                                         'message': {'model': '<synthetic>', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'Prompt is too long'}],
                                                     'usage': {'input_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}}}))
            elif kind == 'user':
                lines.append(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': value}}))
        path.write_text('\n'.join(lines) + '\n')
        return str(path)

    def test_an_agent_whose_prompt_no_longer_fits_is_stuck_on_its_context(self):
        """Thread suda m419: worker-a sat with a full context ('Prompt is too long' to every request) and its
        dot was not red: tuios said context.near=false. The hook reads the agent's own transcript when it stops."""
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle', 'context': {'near': False}}])
        path = self.transcript(('used', 300_000), ('user', 'do it'), ('too-long', None))
        self.fire('UserPromptSubmit', transcript_path=path)
        self.fire('StopFailure', error='invalid_request', transcript_path=path)
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'context'))
        self.fire('Stop', transcript_path=path)
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'context'))
        # once it works again (after /compact), it is working
        self.fire('UserPromptSubmit', transcript_path=path)
        self.assertEqual(self.agent()['state'], 'working')

    def test_a_context_this_full_is_stuck_when_the_agent_stops(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle'}])
        self.fire('Stop', transcript_path=self.transcript(('used', 950_000)))
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('stuck', 'near'))      # red, with continue: auto-compact may still save it
        self.fire('Stop', transcript_path=self.transcript(('used', 400_000)))
        self.assertEqual((self.agent()['state'], self.agent()['why']), ('idle', ''))
        # an old error the agent got past (it compacted and answered since) is not the state now
        self.fire('Stop', transcript_path=self.transcript(('too-long', None), ('user', 'again'), ('used', 120_000)))
        self.assertEqual(self.agent()['state'], 'idle')

    def test_a_transcript_that_is_not_one_changes_nothing(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle'}])
        for path in ('/etc/passwd', str(Path(self.tmp.name) / 'nope.jsonl'), 123, '', '../x.jsonl'):
            self.fire('Stop', transcript_path=path)
            self.assertEqual(self.agent()['state'], 'idle', path)

    def test_tuios_corrects_an_approval_that_was_given(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'needs_input', 'agent_state_at': int((time.time() - 100) * 1e9)}])
        self.fire('Notification', notification_type='permission_prompt')
        self.assertEqual(self.agent()['state'], 'waiting')
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'working', 'agent_state_at': int((time.time() + 5) * 1e9)}])
        self.fire('UserPromptSubmit', pane=OTHER)       # any hook of any agent writes the picture again
        self.assertEqual(self.agent()['state'], 'working')

    def test_a_closed_pane_and_an_ended_session_are_forgotten(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'working'}])
        self.fire('UserPromptSubmit', pane=OTHER)
        self.fire('UserPromptSubmit')
        rec = self.rec(OTHER)
        rec['ts'] -= 700
        (self.dir / (OTHER + '.json')).write_text(json.dumps(rec))
        self.fire('Stop')       # tuios has not listed OTHER for ten minutes
        self.assertEqual([a['pane'] for a in self.live()['agents']], [PANE])
        self.assertFalse((self.dir / (OTHER + '.json')).exists())
        self.fire('SessionEnd')
        self.assertFalse((self.dir / (PANE + '.json')).exists())

    def test_working_that_went_quiet_long_ago_is_not_shown_as_working(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'idle'}])
        self.fire('UserPromptSubmit')
        rec = self.rec()
        rec['ts'] -= live_hook.QUIET + 5
        (self.dir / (PANE + '.json')).write_text(json.dumps(rec))
        self.fire('UserPromptSubmit', pane=OTHER)
        self.assertEqual(self.agent()['state'], 'idle')

    def test_nothing_happens_outside_a_tuios_pane_or_on_junk(self):
        env = dict(self.env)
        env.pop('TUIOS_PANE_ID')
        r = subprocess.run([sys.executable, '-I', '-S', str(HOOK)], input='{"hook_event_name":"UserPromptSubmit"}', env=env, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))
        self.assertFalse(self.dir.exists())
        for junk in ('', 'not json', '[1,2]', '{"hook_event_name":"Nope"}', '{"hook_event_name":"PreToolUse","tool_input":"x"}'):
            r = subprocess.run([sys.executable, '-I', '-S', str(HOOK)], input=junk, env=self.env, capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''), junk)
        for bad in ('../../etc/x', 'ZZZ', ''):
            self.fire('UserPromptSubmit', pane=bad) if bad else None
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if not p.name.startswith('.')), [PANE + '.json'])

    def test_no_board_folder_no_live_file_and_a_broken_tuios_is_harmless(self):
        self.env['THREADS_LIVE_OUT'] = str(Path(self.tmp.name) / 'nowhere' / 'live.json')
        self.env['THREADS_LIVE_TUIOS_CMD'] = '/nonexistent/tuios'
        self.fire('UserPromptSubmit')
        self.assertTrue((self.dir / (PANE + '.json')).exists())
        self.assertFalse((Path(self.tmp.name) / 'nowhere').exists())

    def test_the_file_is_not_rewritten_when_nothing_changed(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'working'}])
        self.bash('ls', 'List files')
        first = self.out.stat().st_mtime_ns
        time.sleep(0.05)
        self.bash('ls', 'List files')
        self.assertNotEqual(self.agent()['ts'], 0)
        # the record's ts moved, so the picture changed; but a PostToolUse while working says nothing new
        mid = self.out.stat().st_mtime_ns
        self.fire('PostToolUse', tool_name='Bash', tool_input={})
        self.assertEqual(self.out.stat().st_mtime_ns, mid)
        self.assertGreaterEqual(mid, first)

    def test_it_is_fast(self):
        self.agents([{'window_id': PANE, 'name': 'a1', 'session': 'tools', 'state': 'working'}])
        start = time.monotonic()
        for _ in range(5):
            self.bash('threads say suda --from fork x', 'x')
        self.assertLess((time.monotonic() - start) / 5, 0.25)


if __name__ == '__main__':
    unittest.main()
