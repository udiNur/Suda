#!/usr/bin/env python3
"""Second hostile review of sse153, the CLI side (threads.py): every writer of state.json, summary.json, changes*,
full/ and .pulse, crashes and failures in the middle, the clock, restores from a backup.

Each test asserts the SAFE outcome: a failure is a real hole. Temp boards only.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 -m unittest test_adv_sse2_cli -v
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_threads import apply_entry


ROOT = _paths.APP
CLI = ROOT / 'threads.py'
BOARDLIB = os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board'))

# Runs threads.main() in a process of its own with one thing patched (SSE2_PATCH): the clock (SSE2_CLOCK, seconds),
# a write that fails (SSE2_FAIL: a file name), or a log of every atomic write (SSE2_LOG).
INPROC = r'''
import importlib.util, json, os, sys, time
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('threads_inproc', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
if os.environ.get('SSE2_CLOCK'):
    fixed = float(os.environ['SSE2_CLOCK'])
    time.time = lambda: fixed
real = m.bl.atomic_write_text
def patched(path, text):
    if os.environ.get('SSE2_LOG'):
        with open(os.environ['SSE2_LOG'], 'a') as f:
            f.write(os.path.relpath(str(path), str(m.BOARD)) + '\n')
    if os.environ.get('SSE2_FAIL') and os.path.basename(str(path)) == os.environ['SSE2_FAIL']:
        raise OSError(28, 'No space left on device')
    return real(path, text)
m.bl.atomic_write_text = patched
sys.argv = ['threads.py', *sys.argv[2:]]
sys.exit(m.main())
'''


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.adv-sse2-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), THREADS_NOTIFY='0', THREADS_BOARDLIB_DIR=BOARDLIB)
        self.env.pop('TUIOS_PANE_ID', None)

    def run_cli(self, *args, script=CLI, **extra):
        env = dict(self.env, **extra)
        if extra:
            return subprocess.run([sys.executable, '-c', INPROC, str(script), *args], env=env, capture_output=True, text=True)
        return subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True)

    def cli(self, *args, **kw):
        r = self.run_cli(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def read(self, name):
        return json.loads((self.board / name).read_text(encoding='utf-8'))

    def pulse(self):
        return int((self.board / '.pulse').read_text())

    def two_threads(self):
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x')
        self.cli('say', 'a', '--from', 'fork', 'one')
        self.cli('new', 'b', 'second', '--state', 'working', '--note', 'x')


class Holes(Board):
    def test_a_partial_restore_never_leaves_a_conversation_from_the_lost_history(self):
        """`cp backup/*.json board/`: state.json and summary.json (and changes.json) come back, full/ and the pulse do
        not. write_lite trusts the revs of the summary on disk as a description of full/, so full/a.json (the lost
        history) is never rewritten while thread a stays as the backup has it: the page holds stamps that the
        conversation file cannot fill, and shows thread a partial for as long as a does not change."""
        self.two_threads()
        backup = self.root / 'backup'
        shutil.copytree(self.board, backup)
        self.cli('say', 'a', '--from', 'fork', 'lost with the restore')
        for f in backup.glob('*.json'):
            shutil.copyfile(f, self.board / f.name)
        self.cli('say', 'b', '--from', 'fork', 'after the restore, in another thread')
        summary, full = self.read('summary.json'), self.read('full/a.json')
        self.assertEqual(full['rev'], summary['threads']['a']['rev'],
                         'full/a.json is from the lost history (%d messages) under a summary of %d stamps'
                         % (len(full['messages']), len(summary['threads']['a']['stamps'])))

    def test_a_failed_pulse_write_does_not_fail_a_command_whose_state_is_saved(self):
        """save() writes the pulse with atomic_write_text now (a temp file and a rename, where it was a touch) and
        outside write_lite's guard: an OSError there (disk full, quota) fails the command AFTER state.json, the
        summary and changes.json are saved. The agent (or the page, told `again`) sends it once more: twice."""
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x')
        r = self.run_cli('say', 'a', '--from', 'fork', 'once', SSE2_FAIL='.pulse')
        texts = [m['text'] for m in self.read('state.json')['threads']['a']['messages']]
        self.assertTrue(r.returncode == 0 or 'once' not in texts,
                        'the command failed (%r) but its message is saved: a retry posts it twice' % r.stderr.strip())

    def test_a_malformed_changes_file_does_not_fail_a_saved_command(self):
        """numbered() trusts the entries of changes.json once its seq and mark match the summary; write_changes then
        does entry['from'] on each. One entry that is not an object (or has NaN, which json.loads accepts) raises
        TypeError/KeyError/ValueError, which write_lite does not catch (only OSError): the command fails after
        state.json is saved, the summary and the pulse stay at the old number (pages say "up to date")."""
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x')
        self.cli('say', 'a', '--from', 'fork', 'one')
        changes = self.read('changes.json')
        changes['entries'].append(42)
        (self.board / 'changes.json').write_text(json.dumps(changes), encoding='utf-8')
        r = self.run_cli('say', 'a', '--from', 'fork', 'two')
        state = self.read('state.json')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pulse(), state['seq'])
        self.assertEqual(self.read('summary.json')['seq'], state['seq'])

    def test_conversations_are_written_before_the_changes_that_name_them(self):
        """write_lite writes changes/<from>.json and changes.json first, then full/, then the summary. A page whose
        `heard` is older than changes.json catches up to changes.json's number (catchUp's target is undefined when
        goal <= changes.seq) during that window, and reads full/<id>.json of the number before: a partial thread
        (four retries), and for good when the process dies there."""
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x')
        self.cli('say', 'a', '--from', 'fork', 'one')
        log = self.root / 'writes.log'
        self.cli('say', 'a', '--from', 'fork', 'two', SSE2_LOG=str(log))
        order = log.read_text().split()
        full = order.index('full/a.json')
        named = [i for i, p in enumerate(order) if p == 'changes.json' or p.startswith('changes/')]
        self.assertTrue(named and all(full < i for i in named), order)

    def test_a_clock_that_went_back_and_a_restore_never_reuse_a_number(self):
        """Numbers are max(known + 1, clock). A Mac whose clock ran ahead (then set back by NTP), then a board put back
        from a backup: the lost numbers are ahead of the clock, and the new history walks through them. When a save
        falls on the millisecond a page holds, that number names other content and the page says "up to date"."""
        ahead = time.time() + 3600
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x', SSE2_CLOCK=str(ahead))
        backup = self.root / 'backup'
        shutil.copytree(self.board, backup)
        self.cli('say', 'a', '--from', 'fork', 'lost', SSE2_CLOCK=str(ahead + 5))
        held = self.read('summary.json')
        shutil.rmtree(self.board)
        shutil.copytree(backup, self.board)
        # the clock, set right, reaches that millisecond again
        self.cli('say', 'a', '--from', 'fork', 'other content', SSE2_CLOCK=str((held['seq'] + 0.5) / 1000))
        now = self.read('summary.json')
        self.assertTrue(now['seq'] != held['seq'] or now['mark'] == held['mark'],
                        'number %d names other content: a page holding it says "up to date"' % held['seq'])


    def test_the_install_path_numbers_state_json_too(self):
        """install() on a board whose state needs no save (lines near on-state.sh) calls numbered() and write_lite()
        but never writes state.json: the summary, changes.json and the pulse go to a new number, state.json keeps the
        old one. An older threads.py then loads that state and rewrites the summary under the OLD number while the
        pulse keeps the new one: a page that whole-reads that summary holds the old number, the server says the new
        one, and the page stays "behind", reading the whole summary at every "alive", until the next numbered save.
        (Calls install's else-branch, renumber(), in process; no `threads install` is run.)"""
        self.two_threads()
        (self.board / 'summary.json').unlink()      # e.g. a failed write_lite, or an older writer's summary
        script = r'''
import importlib.util, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('threads_inproc', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with m.locked():
    data = m.load()
    assert m.STATE.exists() and m.migrated_from is None and not m.mended
    m.renumber(data)            # what install does on a board whose state needs no save
'''
        r = subprocess.run([sys.executable, '-c', script, str(CLI)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read('state.json').get('seq'), self.pulse(),
                         'state.json says %s, the summary and the pulse %s' % (self.read('state.json').get('seq'), self.pulse()))


class Held(Board):
    def test_the_clock_going_back_never_lowers_the_number(self):
        t = time.time()
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x', SSE2_CLOCK=str(t))
        first = self.read('summary.json')
        for i, back in enumerate((3600, 7200, 7200)):
            self.cli('say', 'a', '--from', 'fork', 'm%d' % i, SSE2_CLOCK=str(t - back))
            s = self.read('summary.json')
            self.assertGreater(s['seq'], first['seq'])
            self.assertEqual(self.pulse(), s['seq'])
            self.assertEqual(self.read('state.json')['seq'], s['seq'])
            entries = self.read('changes.json')['entries']
            self.assertEqual(entries[-1]['from'], first['seq'])
            self.assertEqual(apply_entry(first, entries[-1]), s)
            first = s

    def test_saves_in_one_millisecond_chain_and_rebuild_the_summary(self):
        t = time.time()
        self.cli('new', 'a', 'first', '--state', 'working', '--note', 'x', SSE2_CLOCK=str(t))
        held = [self.read('summary.json')]
        for i in range(6):
            self.cli('say', 'a', '--from', 'fork', 'm%d' % i, SSE2_CLOCK=str(t))
            held.append(self.read('summary.json'))
        seqs = [s['seq'] for s in held]
        self.assertEqual(seqs, list(range(seqs[0], seqs[0] + 7)))
        entries = self.read('changes.json')['entries']
        for start in held[:-1]:
            at = start
            for e in entries:
                if e['seq'] > at['seq']:
                    self.assertEqual(e['from'], at['seq'])
                    at = apply_entry(at, e)
            self.assertEqual(at, held[-1])
            # (a run: every change from that number to the board's, for the last few numbers)
            one = self.read('changes/%d.json' % start['seq'])
            self.assertEqual((one['entries'][0]['from'], one['seq']), (start['seq'], held[-1]['seq']))

    def test_a_restore_laid_over_the_board_leaves_no_change_file_of_the_lost_history(self):
        """`cp -R backup/. board/`: the backup is laid over the board and nothing of the lost history is deleted, so
        changes/ still holds its files. After the next save each changes/<n>.json is the entry of changes.json that
        starts from n (the first of its run), and no other file is left."""
        self.two_threads()
        backup = self.root / 'backup'
        shutil.copytree(self.board, backup)
        for i in range(3):
            self.cli('say', 'a', '--from', 'fork', 'lost %d' % i)
        shutil.copytree(backup, self.board, dirs_exist_ok=True)
        self.cli('say', 'b', '--from', 'fork', 'after')
        entries = {e['from']: e for e in self.read('changes.json')['entries']}
        files = {int(p.stem): json.loads(p.read_text(encoding='utf-8')) for p in (self.board / 'changes').glob('*.json')}
        self.assertEqual(set(files), set(entries))
        for n, e in files.items():
            self.assertEqual(e['entries'][0], entries[n])

    def test_an_old_writer_between_numbered_saves_resets_the_changes(self):
        old = self.root / 'old_threads.py'       # (a threads.py of this line from before the numbers: state version 3, no seq)
        old.write_text(subprocess.run(['git', '-C', str(ROOT), 'show', '60586da:threads.py'], capture_output=True, text=True, check=True).stdout)
        self.two_threads()
        before = self.read('summary.json')
        self.cli('say', 'a', '--from', 'fork', 'unnumbered', script=old)
        head = (self.board / 'summary.json').read_text(encoding='utf-8')[:64]
        self.assertFalse(head.startswith('{"seq":%d,"mark":' % before['seq']), head)
        self.cli('say', 'b', '--from', 'fork', 'numbered')
        changes = self.read('changes.json')
        self.assertEqual(changes['entries'], [])
        self.assertEqual(list((self.board / 'changes').glob('*.json')), [])
        self.assertGreater(self.read('summary.json')['seq'], before['seq'])

    def test_an_integral_float_is_a_change_of_its_own(self):
        """1 and 1.0 are one number in JSON for a page, two for canon(): Python over-reports (a new number, an entry
        that sets the value), never under-reports. (A hand edit of state.json: the file store's case; the SQLite
        store takes such a file in whole, and its pages read the summary, tests/test_store.py.)"""
        self.env['THREADS_STORE'] = 'file'
        self.two_threads()
        state = self.read('state.json')
        state['threads']['a']['created'] = float(state['threads']['a']['created'])
        (self.board / 'state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        before = self.read('summary.json')
        self.cli('say', 'b', '--from', 'fork', 'x')
        after = self.read('summary.json')
        e = self.read('changes.json')['entries'][-1]
        self.assertEqual(e['from'], before['seq'])
        self.assertEqual(apply_entry(before, e), after)


if __name__ == '__main__':
    unittest.main()
