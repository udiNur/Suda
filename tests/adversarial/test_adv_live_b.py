#!/usr/bin/env python3
"""Adversarial review (B) of the live dot: concurrency, lifecycle, wrong states. Each test asserts the CORRECT
outcome, so a FAIL is a real hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import test_live      # (puts suda/ on sys.path for live_hook)
import live_hook
from test_live import HOOK, OTHER, PANE


class Adv(test_live.Hook):

    def tuios_row(self, pane, state, ago, name='a1'):
        return {'window_id': pane, 'name': name, 'session': 'tools', 'state': state,
                'agent_state_at': int((time.time() - ago) * 1e9)}

    # ── wrong states that stick ──────────────────────────────────────────────

    def test_an_interrupted_turn_is_not_shown_working_while_tuios_says_idle(self):
        """Esc interrupts a turn: Claude Code fires no Stop. tuios knows (idle/done, newer) but merge only lets
        tuios correct working<->waiting, so the green 'working on this thread' stays for QUIET (30 min)."""
        self.agents([self.tuios_row(PANE, 'working', 200), self.tuios_row(OTHER, 'working', 1, 'b')])
        self.bash('threads say suda --from fork x', 'Post')
        rec = self.rec()
        rec['ts'] -= 120
        (self.dir / (PANE + '.json')).write_text(json.dumps(rec))
        self.agents([self.tuios_row(PANE, 'done', 60), self.tuios_row(OTHER, 'working', 1, 'b')])
        self.fire('UserPromptSubmit', pane=OTHER)
        self.assertEqual(self.agent()['state'], 'idle')

    def test_a_child_claude_in_the_same_pane_does_not_end_the_parent(self):
        """`claude -p ...` run from an agent's Bash inherits TUIOS_PANE_ID and the user hooks; its Stop and
        SessionEnd are taken as the parent's (the hook never looks at session_id)."""
        self.agents([self.tuios_row(PANE, 'working', 1)])
        self.fire('PreToolUse', session_id='parent', tool_name='Bash',
                  tool_input={'command': 'threads say suda --from fork x', 'description': 'Post'})
        self.fire('UserPromptSubmit', session_id='child', prompt='summarise')
        self.fire('Stop', session_id='child')
        self.assertEqual(self.agent()['state'], 'working', 'the child stopping made the parent look idle')
        self.fire('SessionEnd', session_id='child')
        self.fire('PostToolUse', session_id='parent', tool_name='Bash', tool_input={})
        self.assertEqual(self.agent()['thread'], 'suda', 'the child ending wiped the parent thread')

    def test_a_pane_tuios_does_not_list_keeps_its_thread_through_a_long_tool(self):
        """Any tuios answer that misses a pane (an empty list while it restarts, a pane it is not sure is an
        agent) deletes that pane's file after 60 s of quiet: one long tool call (tests, a build) and the thread
        it works on is gone for good."""
        self.agents([self.tuios_row(OTHER, 'working', 1, 'b')])       # PANE missing from this answer
        self.bash('threads say suda --from fork x', 'Run the tests')
        rec = self.rec()
        rec['ts'] -= 120            # the tool runs for two minutes
        (self.dir / (PANE + '.json')).write_text(json.dumps(rec))
        self.fire('UserPromptSubmit', pane=OTHER)
        self.agents([self.tuios_row(PANE, 'working', 1), self.tuios_row(OTHER, 'working', 1, 'b')])
        self.fire('PostToolUse', tool_name='Bash', tool_input={})
        self.assertEqual(self.agent()['thread'], 'suda')

    def test_a_test_board_or_a_quoted_command_is_not_his_thread(self):
        self.assertEqual(live_hook.thread_of('export THREADS_SLUG=e2e; threads say demo-1 --from fork x'), (None, None))
        self.assertEqual(live_hook.thread_of('git commit -m "fix: threads say suda was slow"'), (None, None))

    # ── concurrency ──────────────────────────────────────────────────────────

    def test_two_events_of_one_pane_at_once_do_not_lose_the_thread(self):
        """record() reads, changes and writes the pane file: two hooks of one pane must never interleave there.
        The hook holds its lock around record(); a second taker of the lock is refused while record() runs."""
        import fcntl
        import io
        import contextlib
        live_hook.LIVE_DIR = str(self.dir)
        live_hook.OUT = str(self.out)
        live_hook.TUIOS = 'none'
        self.dir.mkdir(exist_ok=True)
        original, held = live_hook.record, []

        def probe(*args, **kw):
            with open(self.dir / '.lock', 'a') as other:
                try:
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(False)
                    fcntl.flock(other, fcntl.LOCK_UN)
                except OSError:
                    held.append(True)
            return original(*args, **kw)
        live_hook.record = probe
        stdin, os.environ['TUIOS_PANE_ID'] = sys.stdin, PANE
        try:
            sys.stdin = io.StringIO(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'threads say suda --from fork x'}}))
            with contextlib.suppress(SystemExit):
                live_hook.main()
        finally:
            live_hook.record, sys.stdin = original, stdin
            os.environ.pop('TUIOS_PANE_ID', None)
        self.assertEqual(held, [True], 'record() ran without the lock')
        self.assertEqual(self.rec()['thread'], 'suda')

    def test_a_burst_of_hooks_with_a_slow_tuios_each_lands_in_live_json(self):
        """Every forced event (Stop, UserPromptSubmit, Notification) reads tuios inside the lock; a waiter gives up
        after 2 s and its change never reaches live.json until some other hook fires."""
        slow = Path(self.tmp.name) / 'slow.py'
        slow.write_text('import time,sys\ntime.sleep(0.6)\nprint(open(sys.argv[1]).read())\n')
        panes = ['%08x-1111-2222-3333-444444444444' % i for i in range(8)]
        self.agents([self.tuios_row(p, 'done', 1, 'n%d' % i) for i, p in enumerate(panes)])
        self.env['THREADS_LIVE_TUIOS_CMD'] = '%s %s %s' % (sys.executable, slow, self.tuios_file)
        for p in panes:
            self.fire('UserPromptSubmit', pane=p)
        times = []

        def stop(p):
            start = time.monotonic()
            self.fire('Stop', pane=p)
            times.append(time.monotonic() - start)
        workers = [threading.Thread(target=stop, args=(p,)) for p in panes]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        states = {a['pane']: a['state'] for a in self.live()['agents']}
        print('\n  burst of 8 Stops, tuios 0.6 s: max hook %.2f s, median %.2f s' % (max(times), statistics.median(times)), file=sys.stderr)
        self.assertEqual({p: states.get(p) for p in panes}, {p: 'idle' for p in panes})

    def test_hook_cost_per_tool_call(self):
        """Measure only (always passes unless absurd): 50 PreToolUse with 25 pane files, tuios a plain cat."""
        self.env['THREADS_LIVE_TUIOS_CMD'] = '/bin/cat %s' % self.tuios_file
        panes = ['%08x-1111-2222-3333-444444444444' % i for i in range(25)]
        self.agents([self.tuios_row(p, 'working', 1, 'n%d' % i) for i, p in enumerate(panes)])
        for p in panes:
            self.fire('UserPromptSubmit', pane=p)
        cost = {}
        for event in ('PreToolUse', 'PostToolUse', 'Stop'):
            runs = []
            for i in range(50):
                body = json.dumps({'hook_event_name': event, 'tool_name': 'Bash', 'tool_input': {'command': 'ls', 'description': 'List %d' % i}})
                start = time.monotonic()
                subprocess.run([sys.executable, '-I', '-S', str(HOOK)], input=body, env=self.env, capture_output=True, text=True)
                runs.append(time.monotonic() - start)
            cost[event] = (statistics.median(runs) * 1000, max(runs) * 1000)
        print('\n  hook cost ms (median, max): ' + ', '.join('%s %.0f/%.0f' % (k, *v) for k, v in cost.items()), file=sys.stderr)
        self.assertLess(cost['PreToolUse'][0], 150)


for _name in dir(test_live.Hook):
    if _name.startswith('test') and _name not in Adv.__dict__:
        setattr(Adv, _name, None)


if __name__ == '__main__':
    unittest.main()
