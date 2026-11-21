"""Hostile review B: the version 1 → 2 upgrade, and the contract between a page and the CLI.

Every test asserts the CORRECT / SAFE outcome, so a FAILING test is a hole.
Tests named test_held_* are attacks that did not get through.

Nothing here touches the live board: every CLI run gets a BOARDS_DIR inside
this repository, notifications are switched off.

(Part 2 ran the old board page, board.html, under node against a small DOM of its own; the page is gone, suda m620,
and its scenarios with it. suda.html is tested in test_slack.py and the browser suites.)
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import concurrent.futures
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
LIVE = ROOT / 'live-v1-state.json'
OLD_REV = 'fe8c6c3'
V2_KEYS = ('slot', 'summary', 'links', 'state', 'note', 'state_ts', 'state_by', 'auto', 'question',
           'resolved', 'touched', 'soon_at', 'archive_at')


def v1_thread(tid, created=100.0, status='open', messages=(), **extra):
    messages = list(messages)
    t = {'id': tid, 'title': 'T ' + tid, 'context': 'רקע ' + tid, 'status': status, 'created': created,
         'updated': max([created] + [m.get('ts', 0) for m in messages if isinstance(m, dict)]),
         'next': len(messages) + 1, 'messages': messages}
    t.update(extra)
    return t


def msg(n, sender, ts, text=None, **extra):
    m = {'id': f'm{n}', 'from': sender, 'text': text or f'{sender} {n}', 'ts': ts}
    if sender == 'owner':
        m['status'] = 'pending'
    m.update(extra)
    return m


class Base(unittest.TestCase):
    maxDiff = 2000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.adv-b-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.state = self.board / 'state.json'
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), THREADS_NOTIFY='0',
                        THREADS_NOTIFY_CMD='/usr/bin/true', PYTHONDONTWRITEBYTECODE='1')
        for key in ('THREADS_SLUG', 'THREADS_NOW', 'TUIOS_PANE_ID', 'PYTHONPATH', 'THREADS_CONFIG_DIR'):
            self.env.pop(key, None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (self.root / '.threads-config/threads').mkdir(parents=True)
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')

    # ── the CLI, always fenced into the temp board ──
    def cli(self, *args, env=None, script=CLI, input=None):
        env = env or self.env
        boards = Path(env['BOARDS_DIR']).resolve()
        assert ROOT in boards.parents, 'refusing to run the CLI outside the worktree'
        assert env.get('THREADS_NOTIFY') == '0'
        return subprocess.run([sys.executable, str(script), *args], env=env, input=input,
                              capture_output=True, text=True, timeout=120)

    def ok(self, *args, **kw):
        r = self.cli(*args, **kw)
        self.assertEqual(r.returncode, 0, f'{args}: {r.stderr}{r.stdout}')
        return r

    def js(self, *args, **kw):
        return json.loads(self.ok(*args, **kw).stdout)

    def at(self, seconds):
        return dict(self.env, THREADS_NOW=repr(float(seconds)))

    def put(self, content):
        self.board.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, indent=2) + '\n'
        if isinstance(content, str):
            content = content.encode('utf-8')
        self.state.write_bytes(content)
        return content

    def put_v1(self, *threads, **top):
        return self.put({'version': 1, 'threads': {t['id']: t for t in threads}, **top})

    def disk(self):
        return json.loads(self.state.read_text(encoding='utf-8'))

    def backups(self):
        return sorted((self.board.parent.parent / '.threads-config' / self.board.name / 'backups').glob('state.json.v*'))       # private, never beside the served state

    def reset(self):
        """A fresh board: the folder, and the backups of its state in the private folder."""
        shutil.rmtree(self.board, ignore_errors=True)
        shutil.rmtree((self.board.parent.parent / '.threads-config' / self.board.name / 'backups'), ignore_errors=True)

    def post(self, payload, env=None):
        """What the page does: the server stores the body, then runs the hook."""
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        r = self.cli('ingest', env=env)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {'ok': False, 'stderr': r.stderr}

    def old_cli(self):
        path = self.root / 'old_threads.py'
        if not path.exists():
            r = subprocess.run(['git', 'show', f'{OLD_REV}:threads.py'], cwd=ROOT, capture_output=True, text=True)
            if r.returncode:
                self.skipTest('the old revision is not available')
            path.write_text(r.stdout)
        return path

    def assert_sound(self, expect_ids=None):
        """state.json is a usable version 2 file: nothing lost, one slot per open thread."""
        data = self.disk()
        self.assertEqual(data['version'], 3)
        if expect_ids is not None:
            self.assertEqual(set(data['threads']), set(expect_ids))
        slots = [t['slot'] for t in data['threads'].values() if t['status'] == 'open']
        self.assertTrue(all(type(s) is int and s > 0 for s in slots), slots)
        self.assertEqual(len(slots), len(set(slots)), slots)
        return data


# ════════════════════════════════════════════════════════════════════════════
# Part 1: the upgrade
# ════════════════════════════════════════════════════════════════════════════

class LiveUpgrade(Base):
    """The copy of the real version 1 file."""

    def setUp(self):
        super().setUp()
        if not LIVE.exists():
            self.skipTest('live-v1-state.json is not here')
        self.raw = LIVE.read_bytes()
        self.v1 = json.loads(self.raw)
        self.ids = list(self.v1['threads'])

    def test_held_live_every_thread_and_message_survives_unchanged(self):
        self.put(self.raw)
        self.ok('list')
        v2 = self.assert_sound(self.ids)
        self.assertEqual(list(v2['threads']), self.ids)                      # file order kept too
        for tid, old in self.v1['threads'].items():
            new = v2['threads'][tid]
            for key, value in old.items():                                   # id title context status created updated next messages
                self.assertEqual(new[key], value, f'{tid}.{key}')
            self.assertEqual(list(new)[:len(old)], list(old), tid)           # old keys first, in their order
            self.assertEqual(json.dumps(new['messages'], ensure_ascii=False, indent=2),
                             json.dumps(old['messages'], ensure_ascii=False, indent=2), tid)
            self.assertEqual(set(new) - set(old), set(V2_KEYS), tid)
        # line by line: the only lines of the old file that are gone are punctuation and the version
        old_lines, new_lines = self.raw.decode().splitlines(), self.state.read_text().splitlines()
        gone = [line[2:].strip() for line in difflib.ndiff(old_lines, new_lines) if line.startswith('- ')]
        self.assertLessEqual(set(gone), {'"version": 1,', ']', '}'}, 'lines removed by the upgrade')

    def test_held_live_slots_states_and_no_archive_clock(self):
        self.put(self.raw)
        rows = {t['id']: t for t in self.js('list', '--json')}
        order = sorted(self.v1['threads'].values(), key=lambda t: (t['created'], t['id']))
        self.assertEqual([rows[t['id']]['slot'] for t in order], list(range(1, len(order) + 1)))
        for tid, old in self.v1['threads'].items():
            new, last = rows[tid], old['messages'][-1]
            pending = any(m['from'] == 'owner' and m.get('status') == 'pending' for m in old['messages'])
            self.assertEqual(new['status'], 'open', tid)
            self.assertIsNone(new['archive_at'], tid)
            self.assertIsNone(new['soon_at'], tid)
            self.assertNotEqual(new['state'], 'done', tid)
            if last['from'] == 'owner' or pending:
                self.assertEqual(new['state'], 'working', tid)
            else:
                self.assertEqual((new['state'], new['state_by'], new['auto']), ('on-owner', last['from'], True), tid)
                self.assertTrue(new['note'], tid)
            self.assertLessEqual(len(new['note']), 200, tid)
            self.assertEqual(new['state_ts'], last['ts'], tid)
        # a year later nothing has closed itself either
        late = {t['id']: t['status'] for t in self.js('list', '--json', env=self.at(time.time() + 365 * 86400))}
        self.assertEqual(set(late.values()), {'open'})
        self.assertEqual(self.js('pending'), [])

    def first_commands(self):
        tid = self.ids[0]
        yield 'list', lambda: self.ok('list')
        yield 'list --json', lambda: self.ok('list', '--json')
        yield 'list --open', lambda: self.ok('list', '--open')
        yield 'pending', lambda: self.ok('pending')
        yield 'show', lambda: self.ok('show', tid)
        yield 'show --json', lambda: self.ok('show', tid, '--json')
        yield 'say', lambda: self.ok('say', tid, '--from', 'fork', 'x')
        yield 'say owner', lambda: self.ok('say', tid, '--from', 'owner', 'x')
        yield 'state', lambda: self.ok('state', tid, 'working', '--note', 'x')
        yield 'ask', lambda: self.ok('ask', tid, 'q?', '--options', 'a,b')
        yield 'set', lambda: self.ok('set', tid, '--summary', 'x')
        yield 'link', lambda: self.ok('link', tid, 'l', 'https://example.com/')
        yield 'close', lambda: self.ok('close', tid)
        yield 'new', lambda: self.ok('new', 'fresh', 'title')
        yield 'rm', lambda: self.ok('rm', tid, '--yes')
        yield 'sweep', lambda: self.ok('sweep')
        yield 'policy', lambda: self.ok('policy')
        yield 'policy set', lambda: self.ok('policy', '--idle-hours', '5')
        yield 'install', lambda: self.ok('install')
        for op in ('sweep', 'keep', 'close', 'done'):
            # "read it" names the last message that was on his screen
            last = json.loads(self.raw)['threads'][tid]['messages'][-1]['id']
            yield 'ingest ' + op, lambda op=op: self.assertTrue(self.post({'op': op, 'thread': tid, **({'last': last} if op == 'done' else {})})['ok'], op)
        yield 'ingest reply', lambda: self.assertTrue(self.post({'op': 'reply', 'thread': tid, 'text': 'x', 'cid': 'c1'})['ok'])

    def test_held_backup_after_the_first_command_of_any_kind(self):
        for name, run in self.first_commands():
            with self.subTest(first=name):
                self.reset()
                self.put(self.raw)
                run()
                self.assertEqual(self.disk()['version'], 3)
                found = self.backups()
                self.assertEqual(len(found), 1, [p.name for p in found])
                self.assertTrue(found[0].name.startswith('state.json.v1-'))
                self.assertEqual(found[0].read_bytes(), self.raw)

    def test_held_backup_is_made_exactly_once(self):
        self.put(self.raw)
        self.ok('list')
        first = self.backups()
        time.sleep(1.2)                                                       # past the second in the backup's name
        tid = self.ids[0]
        for args in (('list',), ('pending',), ('show', tid), ('say', tid, '--from', 'fork', 'x'), ('install',),
                     ('close', tid), ('reopen', tid), ('sweep',), ('policy', '--idle-hours', '3')):
            self.ok(*args)
        self.post({'op': 'reply', 'thread': tid, 'text': 'x', 'cid': 'c1'})
        self.assertEqual(self.backups(), first)
        self.assertEqual(first[0].read_bytes(), self.raw)

    def test_held_no_backup_for_a_fresh_board(self):
        self.ok('install')
        self.ok('new', 'a', 'A')
        self.ok('list')
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.disk()['version'], 3)

    def test_held_a_failing_first_command_leaves_the_file_alone(self):
        tid = self.ids[0]
        failing = [('show', 'nope'), ('show', 'nope', '--json'), ('say', 'nope', '--from', 'fork', 'x'), ('ack', tid, 'm999'),
                   ('state', tid, 'on-owner'), ('state', 'nope', 'done'), ('link', tid, 'x', 'javascript:alert(1)'),
                   ('new', 'Bad', 'x'), ('new', tid, 'again'), ('reopen', 'nope'), ('close', 'nope'), ('set', tid),
                   ('ask', tid, 'q', '--options', 'one'), ('rm', 'nope', '--yes'), ('policy', '--idle-hours', '-1'),
                   ('say', tid, '--from', 'fork', '  '), ('nonsense',), ('list', '--bogus')]
        for args in failing:
            with self.subTest(args=args):
                self.reset()
                self.put(self.raw)
                r = self.cli(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('Traceback', r.stderr)
                # untouched, or upgraded WITH its backup; never a half state
                if self.state.read_bytes() != self.raw:
                    self.assertEqual([p.read_bytes() for p in self.backups()], [self.raw])
                else:
                    self.assertEqual(self.backups(), [])
        for payload in ({'op': 'reply', 'thread': 'nope', 'text': 'x', 'cid': 'c'}, {'op': 'bogus', 'thread': tid},
                        {'op': 'reply', 'thread': tid, 'text': '', 'cid': 'c'}, {'op': 'reply', 'thread': tid, 'text': 'x', 'cid': 'c', 'q': 'm1'},
                        {'op': 'reopen', 'thread': 'nope'}, ['not', 'a', 'dict']):
            with self.subTest(payload=str(payload)[:60]):
                self.reset()
                self.put(self.raw)
                self.assertFalse(self.post(payload)['ok'])
                if self.state.read_bytes() != self.raw:
                    self.assertEqual([p.read_bytes() for p in self.backups()], [self.raw])
        # the next good command still upgrades and keeps the backup
        self.ok('list')
        self.assertEqual([p.read_bytes() for p in self.backups()], [self.raw])

    def patched(self, **extra):
        """Environment whose python pins the backup's timestamp (and can make the copy fail half way)."""
        hook = self.root / 'hook'
        hook.mkdir(exist_ok=True)
        (hook / 'sitecustomize.py').write_text(
            "import os, shutil, time\n"
            "_strftime = time.strftime\n"
            "time.strftime = lambda fmt, *a: '20990101-000000' if not a and fmt == '%Y%m%d-%H%M%S' else _strftime(fmt, *a)\n"
            "if os.environ.get('ADV_COPY_FAILS'):\n"
            "    def copy2(src, dst, **kw):\n"
            "        with open(src, 'rb') as f, open(dst, 'wb') as g:\n"
            "            g.write(f.read()[:100])\n"
            "        raise OSError(28, 'No space left on device')\n"
            "    shutil.copy2 = copy2\n")
        return dict(self.env, PYTHONPATH=str(hook), **extra)

    def test_held_a_failed_backup_copy_never_overwrites_the_original(self):
        self.put(self.raw)
        r = self.cli('list', env=self.patched(ADV_COPY_FAILS='1'))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(self.state.read_bytes(), self.raw)

    def test_backup_interrupted_then_retried_keeps_a_true_copy(self):
        # The copy dies half way (disk full, kill -9) and leaves a truncated file under the backup's name.
        # Another command arrives within the same second (ten agents queue on the lock).
        self.put(self.raw)
        self.cli('list', env=self.patched(ADV_COPY_FAILS='1'))
        self.assertEqual(self.state.read_bytes(), self.raw)
        self.cli('list', env=self.patched())
        copies = [p for p in [self.state, *self.backups()] if p.read_bytes() == self.raw]
        self.assertTrue(copies, 'the version 1 file was overwritten and the only "backup" is truncated: '
                        + str({p.name: p.stat().st_size for p in [self.state, *self.backups()]}))

    def test_backup_name_already_taken_keeps_a_true_copy(self):
        # Something else already sits under the name the backup would get.
        self.put(self.raw)
        (self.board.parent.parent / '.threads-config' / self.board.name / 'backups').mkdir(parents=True, exist_ok=True)
        ((self.board.parent.parent / '.threads-config' / self.board.name / 'backups') / 'state.json.v1-20990101-000000').write_text('not the backup')
        self.cli('list', env=self.patched())
        copies = [p for p in [self.state, *self.backups()] if p.read_bytes() == self.raw]
        self.assertTrue(copies, 'state.json was upgraded although no real backup exists')

    def test_held_read_only_folder_refuses_and_touches_nothing(self):
        self.put(self.raw)
        (self.board / '.state.json.lock').touch()
        os.chmod(self.board, 0o555)
        self.addCleanup(os.chmod, self.board, 0o755)
        for args in (('list',), ('pending',), ('say', self.ids[0], '--from', 'fork', 'x')):
            r = self.cli(*args)
            self.assertNotIn('Traceback', r.stderr, args)
            self.assertNotEqual(r.returncode, 0, args)                           # it could not keep a backup: it says so
        self.assertEqual(self.state.read_bytes(), self.raw)
        self.assertEqual(self.backups(), [])

    def test_held_second_command_changes_nothing(self):
        self.put(self.raw)
        self.ok('list')
        after, pulse = self.state.read_bytes(), self.board / '.pulse'
        os.utime(pulse, (1, 1))
        for args in (('list',), ('list', '--json'), ('list', '--open'), ('pending',), ('show', self.ids[0]),
                     ('show', self.ids[0], '--json'), ('policy',), ('sweep',)):
            self.ok(*args)
            self.assertEqual(self.state.read_bytes(), after, args)
            self.assertEqual(pulse.stat().st_mtime, 1, args)
        self.assertTrue(self.post({'op': 'sweep'})['ok'])
        self.assertEqual(self.state.read_bytes(), after)
        self.assertEqual(pulse.stat().st_mtime, 1)

    def test_held_restoring_the_backup_and_upgrading_again_gives_the_same_file(self):
        self.put(self.raw)
        self.ok('pending')
        first, backup = self.state.read_bytes(), self.backups()[0]
        shutil.copyfile(backup, self.state)
        backup.unlink()
        self.ok('show', self.ids[-1], env=self.at(time.time() + 86400 * 30))
        self.assertEqual(self.state.read_bytes(), first)
        self.assertEqual([p.read_bytes() for p in self.backups()], [self.raw])

    def test_held_ten_first_commands_at_once(self):
        self.put(self.raw)
        jobs = [('list',), ('pending',), ('list', '--json'), ('show', self.ids[0], '--json'), ('install',)]
        jobs += [('say', tid, '--from', 'fork', f'concurrent {i}') for i, tid in enumerate(self.ids)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            results = list(pool.map(lambda args: self.cli(*args), jobs))
        for args, r in zip(jobs, results):
            self.assertEqual(r.returncode, 0, f'{args}: {r.stderr}')
        self.assertEqual([p.read_bytes() for p in self.backups()], [self.raw])
        data = self.assert_sound(self.ids)
        self.assertEqual(sorted(t['slot'] for t in data['threads'].values()), list(range(1, len(self.ids) + 1)))
        for i, tid in enumerate(self.ids):
            old, new = self.v1['threads'][tid]['messages'], data['threads'][tid]['messages']
            self.assertEqual(new[:len(old)], old, tid)
            self.assertEqual([m['text'] for m in new[len(old):]], [f'concurrent {i}'], tid)


class NastyV1(Base):
    """Synthetic version 1 files. The upgrade either succeeds with a usable file, or refuses and touches nothing."""

    def survive(self, raw, first=(('list',), ('pending',))):
        """Run the first commands; return True when the file was upgraded."""
        raw = self.put(raw)
        ids = []
        for args in first:
            r = self.cli(*args)
            self.assertNotIn('Traceback', r.stderr, f'{args}: traceback')
            if r.returncode:
                continue
        if self.state.read_bytes() == raw:
            self.assertEqual(self.backups(), [], 'refused, yet left a backup')
            return False
        self.assertEqual([p.read_bytes() for p in self.backups()], [raw])
        data = self.assert_sound()
        ids = list(data['threads'])
        # an upgraded file must be usable: every read works, every open thread takes a message
        for args in [('list',), ('list', '--json'), ('pending',)] + [('show', tid) for tid in ids]:
            r = self.cli(*args)
            self.assertEqual(r.returncode, 0, f'after the upgrade `{" ".join(args)}` fails: {r.stderr.strip()[-200:]}')
        for tid, t in data['threads'].items():
            if t['status'] == 'open':
                r = self.cli('say', tid, '--from', 'fork', 'still alive')
                self.assertEqual(r.returncode, 0, f'after the upgrade `say {tid}` fails: {r.stderr.strip()[-200:]}')
        return True

    def test_held_no_version_key(self):
        raw = {'threads': {'a': v1_thread('a', messages=[msg(1, 'fork', 110.0)])}}
        self.assertTrue(self.survive(raw))
        self.assertTrue(self.backups()[0].name.startswith('state.json.v1-'))
        self.assertEqual(self.disk()['threads']['a']['slot'], 1)

    def test_held_empty_or_missing_threads(self):
        self.assertTrue(self.survive({'version': 1, 'threads': {}}))
        self.reset()
        self.assertFalse(self.survive({'version': 1}))

    def test_held_not_json_or_empty_file(self):
        for raw in ('', '   \n', '{"version": 1, "threads": {', 'hello', '\x00\x01\x02'):
            with self.subTest(raw=raw[:20]):
                self.reset()
                self.assertFalse(self.survive(raw))
                r = self.cli('list')
                self.assertNotEqual(r.returncode, 0)

    def test_held_newer_version_is_refused(self):
        for version in (4, 2.5, 99):
            with self.subTest(version=version):
                self.reset()
                self.assertFalse(self.survive({'version': version, 'threads': {'a': v1_thread('a')}}))
                self.assertNotEqual(self.cli('say', 'a', '--from', 'fork', 'x').returncode, 0)

    def test_held_first_command_that_changes_nothing_writes_nothing(self):
        # A second tap on "close", or a reply the server already has: answered from memory, file left as it is.
        raw = self.put_v1(v1_thread('a', messages=[msg(1, 'owner', 110.0, cid='seen-before')]), v1_thread('z', 50.0, status='closed'))
        self.assertTrue(self.post({'op': 'close', 'thread': 'z'})['ok'])
        self.assertTrue(self.post({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'seen-before'})['dup'])
        self.assertEqual((self.state.read_bytes(), self.backups()), (raw, []))
        self.ok('pending')                                                       # the next command upgrades, with the backup
        self.assertEqual([p.read_bytes() for p in self.backups()], [raw])
        self.assert_sound('az')

    def test_held_equal_created_unknown_senders_odd_status(self):
        threads = [v1_thread('b', 100.0), v1_thread('a', 100.0), v1_thread('c', 100.0, messages=[msg(1, 'robot', 120.0), msg(2, 'intruder', 130.0)]),
                   v1_thread('z', 50.0, status='archived', messages=[msg(1, 'owner', 60.0)]), v1_thread('y', 60.0, status='closed')]
        raw = {'version': 1, 'threads': {t['id']: t for t in threads}}
        self.assertTrue(self.survive(raw))
        data = self.disk()
        slots = {tid: t['slot'] for tid, t in data['threads'].items() if t['status'] == 'open'}
        self.assertEqual({k: slots[k] for k in 'abc'}, {'a': 1, 'b': 2, 'c': 3})           # a tie goes by id
        self.assertEqual(data['threads']['z']['status'], 'archived')                       # not dropped, not forced open
        self.assertEqual(data['threads']['c']['state'], 'on-owner')
        self.assertTrue(all(t['archive_at'] is None for t in data['threads'].values()))
        self.assertEqual(len(self.js('pending')), 1)                                       # the reply in the odd thread still waits

    def test_held_pending_reply_before_an_agent_message_is_still_working(self):
        raw = {'version': 1, 'threads': {
            'a': v1_thread('a', messages=[msg(1, 'owner', 110.0), msg(2, 'tower', 120.0)]),
            'b': v1_thread('b', 101.0, messages=[msg(1, 'fork', 110.0), msg(2, 'owner', 120.0, status='acked', acked_ts=125.0)]),
            'c': v1_thread('c', 102.0, messages=[msg(1, 'owner', 110.0, status='acked', acked_ts=111.0), msg(2, 'fork', 120.0)])}}
        self.put(raw)
        self.ok('list')
        t = self.assert_sound('abc')['threads']
        self.assertEqual((t['a']['state'], t['a']['state_by']), ('working', 'tower'))
        self.assertEqual(t['b']['state'], 'working')
        self.assertEqual(t['c']['state'], 'on-owner')

    def test_held_records_without_messages_or_status_are_refused(self):
        for drop in ('messages', 'status', 'id'):
            with self.subTest(drop=drop):
                self.reset()
                bad = v1_thread('a', messages=[msg(1, 'fork', 110.0)])
                del bad[drop]
                self.assertFalse(self.survive({'version': 1, 'threads': {'a': bad, 'b': v1_thread('b', 200.0)}}))

    def test_valid_json_of_the_wrong_shape_gives_an_error_line_not_a_traceback(self):
        good = v1_thread('a', messages=[msg(1, 'fork', 110.0)])
        shapes = {
            'file is a JSON array': [1, 2],
            'file is a JSON string': '"hello"',
            'file is null': 'null',
            'threads is a list': {'version': 1, 'threads': [good]},
            'threads is null': {'version': 1, 'threads': None},
            'version is the string "1"': {'version': '1', 'threads': {'a': good}},
            'version is null': {'version': None, 'threads': {'a': good}},
            'a thread record is null': {'version': 1, 'threads': {'a': good, 'b': None}},
            'a thread record is a string': {'version': 1, 'threads': {'a': good, 'b': 'x'}},
            'messages is null': {'version': 1, 'threads': {'a': {**good, 'messages': None}}},
            'a message is a string': {'version': 1, 'threads': {'a': {**good, 'messages': ['hi']}}},
            'created is a string in one record': {'version': 1, 'threads': {'a': good, 'b': v1_thread('b', created='yesterday')}},
            'policy is a list (version 2 file)': {'version': 2, 'policy': [1], 'threads': {}},
        }
        trace = []
        for name, raw in shapes.items():
            self.reset()
            raw = self.put(raw)
            r = self.cli('list')
            if 'Traceback' in r.stderr:
                trace.append(f'{name}: {r.stderr.strip().splitlines()[-1]}')
            self.assertEqual(self.state.read_bytes(), raw, name)               # at least nothing was written
            self.assertEqual(self.backups(), [], name)
        self.assertEqual(trace, [], '`threads list` printed a traceback for:\n  ' + '\n  '.join(trace))

    def test_record_without_created_does_not_break_list_for_ever(self):
        bad = v1_thread('a', messages=[msg(1, 'fork', 110.0)])
        del bad['created']
        self.survive({'version': 1, 'threads': {'a': bad, 'b': v1_thread('b', 200.0)}})

    def test_record_without_context_does_not_break_show_and_pending(self):
        bad = v1_thread('a', messages=[msg(1, 'owner', 110.0)])
        del bad['context']
        self.survive({'version': 1, 'threads': {'a': bad, 'b': v1_thread('b', 200.0)}})

    def test_record_without_next_still_takes_a_message(self):
        bad = v1_thread('a', messages=[msg(1, 'fork', 110.0)])
        del bad['next']
        self.survive({'version': 1, 'threads': {'a': bad}})

    def test_closed_record_without_updated_does_not_break_list(self):
        bad = v1_thread('a', status='closed')
        del bad['updated']
        self.survive({'version': 1, 'threads': {'a': bad, 'b': v1_thread('b', 200.0)}})

    def test_message_without_ts_does_not_block_done_for_ever(self):
        # An old message with no time. The upgrade takes it; later the thread can never be set done.
        messages = [msg(1, 'fork', 110.0), msg(2, 'fork', 120.0)]
        del messages[0]['ts']
        if not self.survive({'version': 1, 'threads': {'a': v1_thread('a', messages=messages)}}):
            return                                                               # a refusal would be fine
        r = self.cli('state', 'a', 'done')
        self.assertEqual(r.returncode, 0, 'the upgraded thread cannot be set done: ' + r.stderr.strip()[-200:])


class OldClient(Base):
    """The previous command-line client writing into a version 2 file."""

    def setUp(self):
        super().setUp()
        self.old = self.old_cli()
        self.now = time.time()
        # The old client knows him by the id it had for him; this installation names that id an alias of his, so
        # what the old client writes (a rollback) is read, and mended on the next load, as his.
        self.his = re.search(r"choices=\['tower', 'fork', '([^']+)'\]", self.old.read_text(encoding='utf-8'))[1]
        private = self.board.parent.parent / '.threads-config' / self.board.name
        private.mkdir(parents=True, exist_ok=True)
        (private / 'config.json').write_text(json.dumps({'lang': 'he', 'owner_aliases': [self.his]}), encoding='utf-8')

    def old_ok(self, *args):
        r = self.cli(*args, script=self.old)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_held_old_client_keeps_every_version_2_field(self):
        self.ok('new', 'a', 'A', '--summary', 's', '--link', 'PR=https://example.com/1')
        self.ok('new', 'b', 'B', '--state', 'working', '--note', 'בונה', '--by', 'lx')
        self.ok('new', 'c', 'C')
        self.ok('ask', 'c', 'A או B?', '--options', 'A,B')
        self.ok('policy', '--idle-hours', '5')
        before = self.disk()
        self.old_ok('say', 'b', '--from', 'fork', 'from the old client')
        self.old_ok('list')
        self.old_ok('pending')
        self.old_ok('show', 'c')
        after = self.disk()
        self.assertEqual((after['version'], after['policy']), (3, before['policy']))
        for tid in 'abc':
            for key in V2_KEYS:
                self.assertEqual(after['threads'][tid][key], before['threads'][tid][key], f'{tid}.{key}')
        self.assertEqual(self.backups(), [])
        self.ok('list')
        self.assertEqual(self.backups(), [])                                     # and the new client does not "upgrade" again
        self.assert_sound('abc')

    def test_held_thread_made_by_the_old_client_gets_its_own_slot(self):
        self.ok('new', 'a', 'A')
        self.ok('new', 'b', 'B')
        self.old_ok('new', 'c', 'C')
        self.old_ok('new', 'd', 'D')
        self.old_ok('say', 'c', '--from', self.his, 'hello')
        rows = {t['id']: t for t in self.js('list', '--json')}
        self.assertEqual({k: rows[k]['slot'] for k in 'abcd'}, {'a': 1, 'b': 2, 'c': 3, 'd': 4})
        data = self.assert_sound('abcd')
        self.assertEqual(data['threads']['c']['slot'], 3)                        # mended on disk
        self.assertTrue(all(key in data['threads']['d'] for key in V2_KEYS))
        self.assertEqual(len(self.js('pending')), 1)
        self.assertTrue(self.post({'op': 'reply', 'thread': 'd', 'text': 'x', 'cid': 'c1'})['ok'])

    def test_old_client_reopen_is_not_undone_by_the_next_command(self):
        past = self.now - 10 * 3600
        self.ok('new', 'a', 'A', env=self.at(past))
        self.ok('resolve', 'a', '--note', 'done', env=self.at(past))
        self.ok('list', env=self.at(past + 3 * 3600))                           # the two hours passed: archived
        self.assertEqual(self.disk()['threads']['a']['closed_by'], 'auto')
        self.old_ok('reopen', 'a')                                              # an agent on the old client brings it back
        self.assertEqual(self.disk()['threads']['a']['status'], 'open')
        rows = {t['id']: t for t in self.js('list', '--json')}
        self.assertEqual(rows['a']['status'], 'open', 'reopened by the old client, archived again by the next read')

    def test_old_client_reopen_does_not_evict_the_thread_sitting_in_the_slot(self):
        past = self.now - 20 * 3600
        self.ok('new', 'a', 'A', env=self.at(past))
        self.ok('new', 'b', 'B', env=self.at(past))
        self.ok('close', 'a', env=self.at(past + 3600))
        self.ok('new', 'c', 'C', env=self.at(past + 10 * 3600))                 # after the cooldown: takes the freed slot 1
        self.assertEqual(self.disk()['threads']['c']['slot'], 1)
        self.old_ok('reopen', 'a')                                              # comes back still carrying slot 1
        rows = {t['id']: t['slot'] for t in self.js('list', '--json')}
        self.assertEqual(len(set(rows.values())), 3)                            # (this part holds)
        self.assertEqual(rows['c'], 1, f'the thread that has been sitting in slot 1 was moved: {rows}')

    def test_old_client_reply_does_not_leave_the_thread_on_owner(self):
        self.ok('new', 'a', 'A')
        self.ok('say', 'a', '--from', 'fork', 'update')
        self.assertEqual(self.disk()['threads']['a']['state'], 'on-owner')
        self.old_ok('say', 'a', '--from', self.his, 'my answer')               # written with no state change, under his old id
        rows = {t['id']: t for t in self.js('list', '--json')}
        self.assertEqual(len(self.js('pending')), 1)
        self.assertNotEqual(rows['a']['state'], 'on-owner', 'his reply is pending, yet the thread still says it waits on him')


# ════════════════════════════════════════════════════════════════════════════
# The contract between the page and the CLI (what a stale or retried page sends)
# ════════════════════════════════════════════════════════════════════════════

class PageContract(Base):
    T0 = 1_800_000_000.0

    def hours(self, h):
        return self.at(self.T0 + h * 3600)

    def test_held_quick_answer_to_a_replaced_question_is_refused(self):
        e = self.hours
        self.ok('new', 'a', 'A', env=e(0))
        self.ok('ask', 'a', 'למזג?', '--options', 'כן,לא', env=e(1))
        self.ok('ask', 'a', 'למחוק את הגיבוי?', '--options', 'כן,לא', '--replace', 'm1', env=e(2))     # suda m508: only --replace takes one back
        self.assertFalse(self.post({'op': 'reply', 'thread': 'a', 'text': 'כן', 'cid': 'c1', 'q': 'm1'}, env=e(3))['ok'])
        self.assertEqual(len(self.disk()['threads']['a']['messages']), 2)

    def test_typed_reply_is_not_filed_as_the_answer_to_a_question_it_never_saw(self):
        # He types under question 1; the send fails and waits in the outbox (or the tab is stale).
        # An agent replaces the question. "Try again" posts exactly what the page posts for a typed reply.
        e = self.hours
        self.ok('new', 'a', 'A', env=e(0))
        self.ok('ask', 'a', 'למזג את PR 7?', '--options', 'כן,לא', env=e(1))
        typed = {'op': 'reply', 'thread': 'a', 'text': 'כן, קדימה', 'cid': 'c-typed'}     # composed now, delivery fails
        self.ok('ask', 'a', 'למחוק את גיבוי הפרודקשן?', '--options', 'כן,לא', env=e(2))
        self.assertTrue(self.post(typed, env=e(3))['ok'])
        t = self.disk()['threads']['a']
        reply = t['messages'][-1]
        self.assertNotEqual(reply.get('re', {}).get('q'), 'm2',
                            f"the reply written under m1 is recorded as the answer to m2: {reply.get('re')}")

    def test_stale_read_it_does_not_dismiss_a_message_the_page_never_showed(self):
        e = self.hours
        self.ok('new', 'a', 'A', env=e(0))
        self.ok('say', 'a', '--from', 'fork', 'דוח ראשון', env=e(1))            # the page shows this, with "read it, nothing to do"
        self.ok('say', 'a', '--from', 'fork', 'דוח שני: צריך החלטה שלך', env=e(2))   # arrives; the tab has not refreshed yet
        self.assertTrue(self.disk()['threads']['a']['auto'])
        result = self.post({'op': 'done', 'thread': 'a'}, env=e(2.001))          # the tap on the stale card
        t = self.disk()['threads']['a']
        self.assertEqual((result['ok'], t['state']), (False, 'on-owner'),
                         'a tap on a stale card marked an unseen message as read and started the archive clock')

    def test_answer_kept_in_the_outbox_does_not_land_on_a_recreated_thread(self):
        e = self.hours
        self.ok('new', 'deploy', 'Deploy', env=e(0))
        self.ok('ask', 'deploy', 'לפרוס לסטייג׳ינג?', '--options', 'כן,לא', env=e(1))
        kept = {'op': 'reply', 'thread': 'deploy', 'text': 'כן', 'cid': 'c-kept', 'q': 'm1'}     # failed to send; sits in localStorage
        self.ok('rm', 'deploy', '--yes', env=e(2))
        self.ok('new', 'deploy', 'Deploy', env=e(3))
        self.ok('ask', 'deploy', 'לפרוס לפרודקשן?', '--options', 'כן,לא', env=e(4))
        result = self.post(kept, env=e(5))                                       # "try again"
        self.assertFalse(result['ok'], 'an answer to the old question was accepted as the answer to a different one')


if __name__ == '__main__':
    unittest.main()
