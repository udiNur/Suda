"""Hostile review, batch 2 (snippets, rename, tasks, reply-to, reactions, snooze, drafts).

One test per attack. A test named `test_held_...` is an attack the code withstood; any other
test asserts the correct / safe outcome of a suspected hole, so a FAILING test is a real hole.
Every CLI call runs against a temp board inside this repository, with a mail recorder."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import zoneinfo

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
TZ = 'Asia/Jerusalem'
RECORDER = ("import json, os, sys\nfrom pathlib import Path\n"
            "with Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args': sys.argv[1:]}) + '\\n')\n")


class Box:
    """One temp board with its own mail recorder."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        assert ROOT in self.root.resolve().parents, 'a test board must live inside the worktree'
        self.board = self.root / 'boards/threads'
        self.record = self.root / 'notifications.jsonl'
        recorder = self.root / 'record.py'
        recorder.write_text(RECORDER)
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), TZ=TZ,
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]),
                        NOTIFY_RECORD=str(self.record), TUIOS_PANE_ID='must-be-removed')
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'THREADS_NOW', 'THREADS_BOARDLIB_DIR', 'BOARD_LOCK_TIMEOUT'):
            self.env.pop(key, None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (self.root / '.threads-config/threads').mkdir(parents=True, exist_ok=True)
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')

    def cli(self, *args, env=None, input=None, text=True):
        env = env or self.env
        assert env['BOARDS_DIR'] == str(self.root / 'boards') and env.get('THREADS_NOTIFY_CMD'), 'never the live board'
        return subprocess.run([sys.executable, str(CLI), *args], env=env, input=input, capture_output=True, text=text)

    def body(self, payload):
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.body-{os.getpid()}-{time.monotonic_ns()}')
        tmp.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        os.replace(tmp, path)

    def post(self, payload, env=None):
        self.body(payload)
        return self.cli('ingest', env=env)

    def mails(self):
        return [json.loads(line)['args'][0] for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def files(self):
        """Everything on the board that a command could have written (not the request body, not lock files)."""
        found = {}
        for p in sorted(self.board.rglob('*')):
            rel = p.relative_to(self.board).as_posix()
            if rel == 'state' or rel.startswith('state/') or p.name.endswith('.lock') or p.name == '.pulse':
                continue
            found[rel] = os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else '<dir>'
        return found


class AdvC(unittest.TestCase):
    T0 = 1_800_000_000.0    # 2027-01-15 10:00 in Jerusalem
    H = 3600

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-advc-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.box = Box(Path(self.tmp.name) / 'main')
        self.root, self.board, self.env = self.box.root, self.box.board, self.box.env

    # ── helpers ─────────────────────────────────────────────────────────────

    def at(self, hours, **extra):
        return dict(self.env, THREADS_NOW=repr(self.T0 + hours * self.H), **extra)

    def run_cli(self, *args, ok=True, input=None, env=None, box=None):
        r = (box or self.box).cli(*args, env=env, input=input)
        self.assertNotIn('Traceback', r.stderr, f'{args}: a traceback instead of an answer')
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def post(self, payload, ok=True, env=None, box=None):
        """What the page does. Always exactly one JSON line; exit 0 exactly when ok."""
        r = (box or self.box).post(payload, env=env)
        self.assertNotIn('Traceback', r.stderr, f'{str(payload)[:80]}: a traceback instead of an answer')
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, f'{str(payload)[:80]}: {r.stdout!r} {r.stderr!r}')
        answer = json.loads(lines[0])
        self.assertIsInstance(answer.get('ok'), bool)
        self.assertEqual(answer['ok'], r.returncode == 0, f'{str(payload)[:80]}: exit {r.returncode} with {answer}')
        if ok is not None:
            self.assertEqual(answer['ok'], ok, f'{str(payload)[:80]}: {answer}')
        return answer

    def refused(self, payload, env=None, box=None):
        """A refusal: one JSON line, non-zero exit, and NOTHING written, woken or mailed."""
        box = box or self.box
        before, mails, pulse = box.files(), box.mails(), box.board / '.pulse'
        if pulse.exists():
            os.utime(pulse, (1, 1))
        answer = self.post(payload, ok=False, env=env, box=box)
        self.assertEqual(box.files(), before, f'{str(payload)[:80]}: a refused request wrote something')
        self.assertEqual(box.mails(), mails, f'{str(payload)[:80]}: a refused request mailed someone')
        if pulse.exists():
            self.assertEqual(pulse.stat().st_mtime, 1, f'{str(payload)[:80]}: a refused request woke the pages')
        return answer

    def new(self, tid='topic', env=None):
        self.run_cli('new', tid, 'כותרת ' + tid, '--context', 'רקע', env=env)

    def thread(self, tid='topic', env=None):
        return json.loads(self.run_cli('show', tid, '--json', env=env).stdout)

    def state(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def put_state(self, data):
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def mails(self):
        return self.box.mails()

    def drafts(self):
        return json.loads((self.board / 'drafts.json').read_text(encoding='utf-8'))['drafts']

    def snippet_files(self):
        base = self.board / 'snippets'
        return sorted(p.relative_to(self.board).as_posix() for p in base.rglob('*') if not p.is_dir()) if base.exists() else []

    def reply(self, text='שלום', cid='c1', ok=True, env=None, **extra):
        return self.post({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': cid, **extra}, ok=ok, env=env)

    # ════════════════════════════════════════════════════════════════════════
    # SUSPECTED HOLES: each test states the safe outcome
    # ════════════════════════════════════════════════════════════════════════

    # ── snippets: orphans ───────────────────────────────────────────────────

    def test_refused_reply_leaves_no_snippet_file(self):
        """The snippet is written before the state is saved. When the save fails the reply is
        refused, but its file stays on disk (and is served over HTTP) under the next message id."""
        self.new()
        # the message text cannot be stored (a lone surrogate): the save fails after the file was written
        answer = self.post({'op': 'reply', 'thread': 'topic', 'text': 'ראה לוג \ud83d', 'cid': 'c1',
                            'snippet': {'text': 'SECRET-OF-A-REFUSED-REPLY', 'name': 'a.log'}}, ok=False)
        self.assertFalse(answer['ok'])
        self.assertEqual(self.thread()['messages'], [])
        self.assertEqual(self.snippet_files(), [], 'a refused reply left its snippet behind')

    def test_orphan_snippet_does_not_sit_under_the_next_message_id(self):
        self.new()
        self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'bad \udc80',
                   'snippet': {'text': 'SECRET-OF-A-REFUSED-REPLY', 'name': 'a.log'}}, ok=False)
        self.reply('הודעה רגילה, בלי קטע', cid='c2')                          # becomes m1
        m = self.thread()['messages'][0]
        self.assertEqual((m['id'], 'snippet' in m), ('m1', False))
        self.assertFalse((self.board / 'snippets/topic/m1.log').exists(),
                         'the file of the refused reply now sits beside m1, a message that has no snippet')

    def test_cli_snippet_is_not_left_behind_when_the_state_cannot_be_saved(self):
        self.new()
        log = self.root / 'run.log'
        log.write_text('SECRET-OF-A-FAILED-SAY\n' * 10)
        (self.board / 'snippets/topic').mkdir(parents=True)
        os.chmod(self.board, 0o555)                      # the state cannot be replaced; the snippets folder can be written
        try:
            r = self.run_cli('say', 'topic', '--from', 'fork', 'הלוג', '--snippet', str(log), ok=False)
        finally:
            os.chmod(self.board, 0o755)
        self.assertEqual(self.thread()['messages'], [], r.stderr)
        self.assertEqual(self.snippet_files(), [], 'a message that was never saved left its snippet behind')

    # ── snippets: a state file is trusted as a path ─────────────────────────

    def crafted(self, tid):
        """A state file whose thread id was never checked by `threads new`."""
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'x' * 60_000)         # snippets/topic/m1.txt exists
        data = self.state()
        evil = json.loads(json.dumps(data['threads']['topic']))
        evil.update(id=tid, slot=2)
        data['threads'][tid] = evil
        self.put_state(data)
        return data

    def test_rm_of_a_crafted_thread_id_deletes_nothing_outside_its_folder(self):
        """`rm` runs shutil.rmtree(BOARD/'snippets'/<id>) on an id that only `new` ever checked."""
        self.crafted('..')                                                    # BOARD/snippets/.. is the board itself
        (self.board / 'suda.html').write_text('<html>')
        self.box.cli('rm', '..', '--yes')
        survivors = sorted(p.name for p in self.board.iterdir()) if self.board.exists() else []
        self.assertIn('state.json', survivors, f'rm of thread ".." wiped the board folder; left: {survivors}')
        self.assertIn('suda.html', survivors)
        self.assertTrue((self.board / 'snippets/topic/m1.txt').exists(), 'the snippets of another thread were deleted')

    def test_crafted_thread_id_cannot_read_outside_its_snippet_folder(self):
        data = self.crafted('..')
        (self.board / 'private.txt').write_text('NOT-A-SNIPPET')
        data['threads']['..']['messages'][0]['snippet']['file'] = 'private.txt'
        self.put_state(data)
        r = self.box.cli('snippet', '..', 'm1')
        self.assertNotIn('NOT-A-SNIPPET', r.stdout + r.stderr, '`threads snippet` printed a file that is not a snippet')
        self.assertNotEqual(r.returncode, 0)

    def test_crafted_thread_id_cannot_write_outside_the_snippets_folder(self):
        self.crafted('../../escaped')
        self.box.cli('say', '../../escaped', '--from', 'fork', 'y' * 60_000)
        # (one file stands beside the board folder on purpose: its highest number, '.<slug>.seq', so that a folder put
        # back from a backup never gives a number again; that name, and nothing else)
        high = self.board.parent / ('.' + self.board.name + '.seq')
        outside = sorted(p.relative_to(self.root).as_posix() for p in (self.root / 'boards').rglob('*')
                         if p.is_file() and self.board not in p.parents and p != high and not re.fullmatch(r'\.[^/]+\.seq', p.name))   # (the board's own change number lives beside it)
        self.assertEqual(outside, [], 'a snippet was written outside the board folder')

    def test_symlinked_thread_folder_is_not_written_or_read_through(self):
        """snippet_path() resolves BOTH sides, so a link at snippets/<thread> moves the "inside"."""
        self.new()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.board / 'snippets').mkdir()
        os.symlink(outside, self.board / 'snippets/topic')
        self.box.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c1', 'snippet': {'text': 'גוף הקטע'}})
        self.assertEqual(sorted(p.name for p in outside.iterdir()), [], 'a snippet was written through a link, outside the board')
        (outside / 'm1.txt').write_text('NOT-A-SNIPPET')
        r = self.box.cli('snippet', 'topic', 'm1')
        self.assertNotIn('NOT-A-SNIPPET', r.stdout, '`threads snippet` read through a link, outside the board')

    def test_show_survives_a_snippet_record_of_the_wrong_type(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'הודעה')
        for bad in ('x', ['x'], 5, True):
            with self.subTest(snippet=bad):
                data = self.state()
                data['threads']['topic']['messages'][0]['snippet'] = bad
                self.put_state(data)
                self.assertIn('הודעה', self.run_cli('show', 'topic').stdout)
                self.run_cli('show', 'topic', '--json')
                self.run_cli('pending')

    def test_snippet_text_comes_back_exactly_as_it_was_sent(self):
        """Text mode translates line ends: CRLF and CR are rewritten on the way out and on the way in."""
        self.new()
        sent = 'שורה א\r\nשורה ב\rשורה ג\n\nסוף'
        self.reply('', snippet={'text': sent, 'name': 'win.log'})
        self.assertEqual((self.board / 'snippets/topic/m1.log').read_bytes(), sent.encode('utf-8'))      # on disk: exact
        with self.subTest('threads snippet'):
            r = self.box.cli('snippet', 'topic', 'm1', text=False)
            self.assertEqual(r.stdout, (sent + '\n').encode('utf-8'))
        with self.subTest('say --snippet'):
            src = self.root / 'win.log'
            src.write_bytes(sent.encode('utf-8'))
            self.run_cli('say', 'topic', '--from', 'fork', 'מצורף', '--snippet', str(src))
            self.assertEqual((self.board / 'snippets/topic/m2.log').read_bytes(), sent.encode('utf-8'))

    def test_long_plain_reply_still_reaches_the_fork_whole(self):
        """Before: a reply of up to 8000 characters arrived whole in `pending[].text`. Now anything over
        4000 arrives as a 160-character preview, and a consumer that reads `text` loses the rest."""
        self.new()
        long = '\n'.join(f'{i}. בקשה מספר {i} שחייבים לבצע' for i in range(1, 160))
        self.assertTrue(4000 < len(long) <= 8000)
        self.reply(long)                                                      # exactly what an old page posts
        row = json.loads(self.run_cli('pending').stdout)[0]
        self.assertEqual(row['text'], long, f"pending[].text is {len(row['text'])} of {len(long)} characters")

    # ── reactions ───────────────────────────────────────────────────────────

    def test_question_mark_that_is_already_on_mails_nobody(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה')
        react = {'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': True}
        self.post(react)
        self.assertEqual(len(self.mails()), 1)
        for _ in range(3):                                                    # a retry, a second device, a double tap
            self.post(react)
        self.assertEqual(len(self.mails()), 1, 'the same ❓ mailed the tower again though nothing was switched on')

    def test_reaction_that_changes_nothing_does_not_rewrite_the_state(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה', env=self.at(0))
        before = (self.board / 'state.json').read_bytes()
        os.utime(self.board / '.pulse', (1, 1))
        self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '👍', 'on': False}, env=self.at(5))     # nothing to take off
        self.assertEqual((self.board / '.pulse').stat().st_mtime, 1, 'a no-op reaction woke every page')
        self.assertEqual((self.board / 'state.json').read_bytes(), before, 'a no-op reaction rewrote the state')

    def test_question_mark_toggle_cannot_mail_bomb_the_tower(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה', env=self.at(0))
        for i in range(6):                                                    # off, on, off, on … inside one second
            self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': i % 2 == 0}, env=self.at(1))
        self.assertLessEqual(len(self.mails()), 1, 'every off→on of the same ❓ mails the tower again, with no limit')

    # ── snooze: mail for a wake nobody can act on ───────────────────────────

    def sleeping(self):
        self.new(env=self.at(0))
        self.run_cli('state', 'topic', 'working', '--note', 'בונה', env=self.at(0))
        self.run_cli('snooze', 'topic', '--until', '+1h', env=self.at(0))
        self.assertEqual(self.mails(), [])

    def test_removing_a_thread_whose_snooze_passed_mails_nobody(self):
        self.sleeping()
        self.run_cli('rm', 'topic', '--yes', env=self.at(2))
        self.assertEqual(self.mails(), [], 'the tower is told to `threads show` a thread that no longer exists')

    def test_closing_a_thread_whose_snooze_passed_mails_nobody(self):
        self.sleeping()
        self.post({'op': 'close', 'thread': 'topic'}, env=self.at(2))
        self.assertEqual(self.thread(env=self.at(2))['status'], 'closed')
        self.assertEqual(self.mails(), [], 'a "snooze woke" mail for a thread he closed in the same tap')

    def test_snoozing_again_after_the_time_passed_mails_nobody(self):
        self.sleeping()
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 9 * self.H}, env=self.at(2))
        t = self.thread(env=self.at(2))
        self.assertEqual(t['snooze']['until'], self.T0 + 9 * self.H)
        self.assertEqual(self.mails(), [], 'going back to sleep mailed "snooze woke"; the thread is asleep')

    def test_wake_mail_is_not_lost_when_the_output_cannot_be_written(self):
        """Mails are sent after flush(); a closed pipe makes flush() raise and the saved wake is never mailed."""
        self.sleeping()
        r, w = os.pipe()
        os.close(r)
        try:
            subprocess.run([sys.executable, str(CLI), 'list'], env=self.at(2), stdout=w, stderr=subprocess.PIPE)
        finally:
            os.close(w)
        self.assertNotIn('snooze', self.thread(env=self.at(2)))               # the wake was saved …
        self.assertEqual(len(self.mails()), 1, '… but its one mail was dropped, and nothing will send it again')

    def test_reminder_on_a_finished_thread_can_be_marked_read(self):
        """A thread that was `done` wakes as an open ask (auto=False): the page's "read it" is refused,
        dismissing the reminder leaves it on him for ever, and it never archives again."""
        self.new(env=self.at(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח: הכול עבר', env=self.at(0))
        self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=self.at(1))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 5 * self.H}, env=self.at(1))
        self.run_cli('list', env=self.at(6))                                  # wakes
        self.assertEqual(self.thread(env=self.at(6))['state'], 'on-owner')
        self.post({'op': 'unsnooze', 'thread': 'topic'}, env=self.at(7))       # he dismisses the reminder
        self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=self.at(7))
        self.assertEqual(self.thread(env=self.at(7))['state'], 'done')

    def test_reminder_ends_when_he_settles_the_thread(self):
        """`reminder` is cleared by a reply, a new snooze and unsnooze only: "read it" and close + reopen keep it."""
        for name, settle in (('done', lambda env: self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=env)),
                             ('close and reopen', lambda env: (self.post({'op': 'close', 'thread': 'topic'}, env=env),
                                                               self.post({'op': 'reopen', 'thread': 'topic'}, env=env)))):
            with self.subTest(settled_by=name):
                self.box = Box(Path(self.tmp.name) / name.replace(' ', '-'))
                env = lambda h: dict(self.box.env, THREADS_NOW=repr(self.T0 + h * self.H))
                self.new(env=env(0))
                self.run_cli('say', 'topic', '--from', 'fork', 'דוח: הכול עבר', env=env(0))      # on him, "read this"
                self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 5 * self.H}, env=env(1))
                self.run_cli('list', env=env(6))
                self.assertIn('reminder', self.thread(env=env(6)))
                settle(env(7))
                self.assertNotIn('reminder', self.thread(env=env(7)))

    def test_show_displays_what_the_mail_points_at(self):
        """Both new mails end with "run: threads show <id>", and the plain `show` prints neither the ❓ nor the reminder."""
        self.new(env=self.at(0))                                              # on him from the start: a wake changes no note
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה', env=self.at(0))
        self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': True}, env=self.at(1))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 5 * self.H}, env=self.at(1))
        self.run_cli('list', env=self.at(6))
        mails = self.mails()
        self.assertTrue(len(mails) == 2 and all(m.endswith('run: threads show topic') for m in mails), mails)
        shown = self.run_cli('show', 'topic', env=self.at(6)).stdout
        with self.subTest('the ❓ he put on m1'):
            self.assertIn('❓', shown)
        with self.subTest('the reminder'):
            self.assertRegex(shown, 'תזכורת|reminder|snooze')

    # ── snooze: the time he typed ───────────────────────────────────────────

    def test_snooze_refuses_a_time_that_does_not_exist(self):
        """mktime() normalises: 31.02 becomes 3 March, 25:99 becomes 02:39 the day after."""
        self.new(env=self.at(0))
        for when in ('31.02 09:00', 'tomorrow 25:99', '2027-02-30 10:00', '00.00 00:00', 'today 24:60', '2027-13-01 09:00'):
            with self.subTest(until=when):
                r = self.box.cli('snooze', 'topic', '--until', when, env=self.at(0))
                got = self.thread(env=self.at(0)).get('snooze')
                self.box.cli('unsnooze', 'topic', env=self.at(0))
                self.assertIsNone(got, f'accepted as {got and time.strftime("%Y-%m-%d %H:%M", time.gmtime(got["until"] + 7200))} (Jerusalem)')
                self.assertNotEqual(r.returncode, 0)

    def test_snooze_time_out_of_range_is_refused_without_a_traceback(self):
        self.new(env=self.at(0))
        for when in ('0000-01-01 00:00', '0001-12-31 23:59'):
            with self.subTest(until=when):
                r = self.box.cli('snooze', 'topic', '--until', when, env=self.at(0))
                self.assertNotIn('Traceback', r.stderr, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '')
                self.assertNotEqual(r.returncode, 0)

    # ── tasks / snooze against the archive clock ────────────────────────────

    def test_finishing_the_last_task_does_not_archive_the_thread_at_once(self):
        """The unfinished task held the thread for days; its last tap leaves `archive_at` in the past."""
        self.new(env=self.at(0))
        self.run_cli('task', 'add', 'topic', 'לבנות', env=self.at(0))
        self.run_cli('state', 'topic', 'done', '--force', env=self.at(0))      # over open tasks: only with --force
        self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'done'}, env=self.at(100))
        left = (self.state()['threads']['topic']['archive_at'] - (self.T0 + 100 * self.H)) / self.H
        self.assertEqual(json.loads(self.run_cli('sweep', env=self.at(100.01)).stdout), [],
                         f'archived by the next command; his tap saved archive_at {left:+.0f} h from now')
        self.assertEqual(self.thread(env=self.at(100.01))['status'], 'open')

    def test_cancelling_a_snooze_does_not_archive_the_thread_at_once(self):
        self.new(env=self.at(0))
        self.run_cli('state', 'topic', 'done', env=self.at(0))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 200 * self.H}, env=self.at(1))
        self.post({'op': 'unsnooze', 'thread': 'topic'}, env=self.at(100))     # "show it to me now"
        self.assertEqual(json.loads(self.run_cli('sweep', env=self.at(100.01)).stdout), [])
        self.assertEqual(self.thread(env=self.at(100.01))['status'], 'open')

    def test_task_numbers_of_a_removed_thread_are_not_reused(self):
        """Message ids continue after rm + new so that a tap kept by a page cannot land on the new thread.
        Task numbers restart at 1: a stale {op:'task', n:1} changes a task of another topic."""
        self.new()
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'משימה של הנושא הישן').stdout.strip(), '1')
        self.run_cli('rm', 'topic', '--yes')
        self.new()
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'משימה של נושא אחר').stdout.strip(), '2')

    # ── drafts ──────────────────────────────────────────────────────────────

    def test_reply_is_ok_and_mailed_when_the_draft_marker_cannot_be_written(self):
        """The reply is committed, then save_draft() runs unguarded BEFORE notify(): its failure turns a saved
        reply into `ok:false` and drops the mail; the page's retry is a duplicate, which mails nobody either."""
        self.new()
        (self.board / 'drafts.json').mkdir()                                  # any reason the drafts file cannot be replaced
        first = self.box.post({'op': 'reply', 'thread': 'topic', 'text': 'תבנה את זה', 'cid': 'c1'})
        self.assertEqual(len(self.thread()['messages']), 1)                   # the reply IS saved
        retry = self.box.post({'op': 'reply', 'thread': 'topic', 'text': 'תבנה את זה', 'cid': 'c1'})
        with self.subTest('the tower is mailed'):
            self.assertEqual(len(self.mails()), 1, f'saved reply, no mail. first: {first.stdout.strip()} retry: {retry.stdout.strip()}')
        with self.subTest('the page is told the truth'):
            self.assertEqual((first.returncode, json.loads(first.stdout)['ok']), (0, True), first.stdout)

    def test_draft_does_not_come_back_in_a_recreated_thread(self):
        self.new()
        self.post({'op': 'draft', 'thread': 'topic', 'text': 'טיוטה של הנושא הישן'})
        self.run_cli('rm', 'topic', '--yes')
        self.run_cli('new', 'topic', 'נושא אחר לגמרי')
        self.assertFalse(self.drafts().get('topic', {}).get('text'), 'the draft of a removed thread opens in the composer of a new one')

    # ════════════════════════════════════════════════════════════════════════
    # HELD: attacks the code withstood
    # ════════════════════════════════════════════════════════════════════════

    def test_held_snippet_names_never_become_paths(self):
        self.new()
        outside = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if self.board not in p.parents and p != self.board)
        names = ['../../etc/passwd', '/abs/x.md', 'a\x00b.md', 'x.txt/../../y', '..\\..\\win.log', 'A.TXT', 'ａ.ｍｄ', 'e\u0301.MD',
                 'x' * 5000 + '.md', '.md', '..', '.', 'con.log ', 'a.md\n', '\u202egol.exe', 'x.html', 'x.svg', 'x.md.html',
                 'm1.txt', '~/.ssh/id_rsa', 'x.md/', 'x.Md\x00.html', '\ud800.md', '']
        for i, name in enumerate(names, 1):
            with self.subTest(name=name[:30]):
                self.reply('', cid=f'c{i}', snippet={'text': f'body {i}', 'name': name})
                s = self.thread()['messages'][-1]['snippet']
                self.assertRegex(s['file'], rf'^snippets/topic/m{i}\.(txt|md|log)$')
                self.assertEqual((self.board / s['file']).read_text(), f'body {i}')
                self.assertFalse(s['name'] and ('/' in s['name'] or '\\' in s['name'] or '\x00' in s['name'] or len(s['name']) > 120), s['name'])
        self.assertEqual(len(self.snippet_files()), len(names))
        self.assertTrue(all(f.startswith('snippets/topic/m') for f in self.snippet_files()))
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*')
                                if self.board not in p.parents and p != self.board and p.name != 'notifications.jsonl'),
                         [p for p in outside if not p.endswith('notifications.jsonl')])

    def test_held_snippet_file_links_are_not_followed(self):
        self.new()
        secret = self.root / 'secret.txt'
        secret.write_text('DO-NOT-TOUCH')
        (self.board / 'snippets/topic').mkdir(parents=True)
        os.symlink(secret, self.board / 'snippets/topic/m1.txt')              # planted where the next snippet goes
        self.reply('', snippet={'text': 'גוף'})
        self.assertEqual(secret.read_text(), 'DO-NOT-TOUCH')                  # the link was replaced, not written through
        self.assertFalse((self.board / 'snippets/topic/m1.txt').is_symlink())
        os.remove(self.board / 'snippets/topic/m1.txt')
        os.symlink(secret, self.board / 'snippets/topic/m1.txt')              # … and planted over an existing snippet
        for args in (('snippet', 'topic', 'm1'), ('show', 'topic'), ('show', 'topic', '--json'), ('pending',)):
            r = self.box.cli(*args)
            self.assertNotIn('DO-NOT-TOUCH', r.stdout + r.stderr, args)
        self.assertNotEqual(self.box.cli('snippet', 'topic', 'm1').returncode, 0)
        os.mkdir(self.root / 'far')
        (self.root / 'far/keep.txt').write_text('keep')
        self.new('other')
        os.symlink(self.root / 'far', self.board / 'snippets/other')
        self.run_cli('rm', 'other', '--yes')                                  # rmtree refuses a link
        self.assertEqual((self.root / 'far/keep.txt').read_text(), 'keep')

    def test_held_snippet_refusals_write_nothing(self):
        self.new()
        self.new('shut')
        self.run_cli('close', 'shut')
        self.run_cli('ask', 'topic', 'לפרוס?', '--options', 'כן,לא')          # m1, the open question
        self.new('else')
        self.run_cli('say', 'else', '--from', 'fork', 'x')
        self.run_cli('say', 'else', '--from', 'fork', 'y')                    # else/m2 exists; topic/m2 does not
        body = {'text': 'גוף הקטע', 'name': 'a.md'}
        for extra in ({'text': 'x' * 8001, 'snippet': body}, {'snippet': {'text': '😀' * 5_000_001}}, {'snippet': {'text': 'a \ud800 b'}},
                      {'snippet': {'text': '\u200b\u200f \n'}}, {'snippet': None}, {'snippet': 7}, {'snippet': {'name': 'a.md'}},
                      {'snippet': {'text': ['x']}}, {'snippet': {'text': 'x', 'name': ['a']}}, {'snippet': {'text': 'x', 'name': 0}},
                      {'snippet': body, 'thread': 'shut'}, {'snippet': body, 'thread': 'ghost'}, {'snippet': body, 'q': 'm9'},
                      {'snippet': body, 'reply_to': 'm2'}, {'snippet': body, 'reply_to': 'm3'}, {'snippet': body, 'cid': ''},
                      {'snippet': body, 'cid': 'c' * 81}, {'snippet': body, 'text': None}, {'snippet': body, 'under': 5}):
            with self.subTest(extra=str(extra)[:70]):
                self.refused({'op': 'reply', 'thread': 'topic', 'text': 'שלום', 'cid': 'c1', **extra})
        self.assertEqual(self.snippet_files(), [])
        # the largest 4-byte text that fits, then a retry of the same cid carrying a different snippet
        self.reply('', snippet={'text': '😀' * 500_000}, q='m1')
        stamp = (self.board / 'snippets/topic/m2.txt').stat().st_mtime_ns
        before, mails = self.box.files(), self.mails()
        again = self.reply('אחר', snippet={'text': 'קטע אחר לגמרי', 'name': 'b.log'})
        self.assertEqual((again['dup'], again['msg_id']), (True, 'm2'))
        self.assertEqual((self.box.files(), self.mails(), (self.board / 'snippets/topic/m2.txt').stat().st_mtime_ns), (before, mails, stamp))

    def test_held_unfinished_task_blocks_every_road_to_the_archive(self):
        e = self.at
        self.new(env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבנות', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבדוק', env=e(0))
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(0))
        roads = (lambda h: self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=e(h)),
                 lambda h: self.run_cli('state', 'topic', 'done', '--force', env=e(h)),
                 lambda h: self.run_cli('resolve', 'topic', '--force', env=e(h)),
                 lambda h: (self.run_cli('close', 'topic', env=e(h)), self.run_cli('reopen', 'topic', env=e(h))),
                 lambda h: (self.post({'op': 'close', 'thread': 'topic'}, env=e(h)), self.post({'op': 'reopen', 'thread': 'topic'}, env=e(h))),
                 lambda h: self.run_cli('policy', '--idle-hours', '0', '--grace-hours', '0', '--resolved-hours', '0', env=e(h)),
                 lambda h: self.run_cli('task', 'set', 'topic', '2', 'blocked', env=e(h)),
                 lambda h: self.post({'op': 'task', 'thread': 'topic', 'n': 2, 'status': 'on-owner'}, env=e(h)))
        for i, road in enumerate(roads):
            hour = 1 + i * 500
            road(hour)
            for later in (hour, hour + 499):
                with self.subTest(road=i, hours=later):
                    self.assertEqual(json.loads(self.run_cli('sweep', env=e(later)).stdout), [])
                    self.assertEqual(self.post({'op': 'sweep'}, env=e(later))['archived'], [])
                    t = self.thread(env=e(later))
                    self.assertEqual((t['status'], t['archive_at'], t['soon_at']), ('open', None, None))
        self.assertEqual([k['n'] for k in self.thread(env=e(5000))['tasks']], [1, 2])     # survived close / reopen
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'שלישית', env=e(5000)).stdout.strip(), '3')
        # all done, but asleep: it does not archive; awake again it is on him, not in the archive
        self.run_cli('task', 'set', 'topic', '2', 'done', env=e(5001))
        self.run_cli('task', 'set', 'topic', '3', 'done', env=e(5001))
        self.run_cli('state', 'topic', 'done', env=e(5001))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 5100 * self.H}, env=e(5001))
        self.assertEqual(json.loads(self.run_cli('sweep', env=e(5099)).stdout), [])
        self.assertEqual(json.loads(self.run_cli('sweep', env=e(5101)).stdout), [])
        self.assertEqual(self.thread(env=e(5101))['state'], 'on-owner')

    def test_held_task_op_refusals_and_a_closed_thread(self):
        self.new()
        self.run_cli('task', 'add', 'topic', 'לבנות')
        for bad in ({'n': True}, {'n': 1.0}, {'n': '1'}, {'n': -1}, {'n': 0}, {'n': 10 ** 30}, {'n': None}, {'n': [1]}, {'n': {'a': 1}},
                    {'status': 'Done'}, {'status': ''}, {'status': None}, {'status': ['done']}, {'status': {'done': 1}}, {'status': 1},
                    {'thread': 'ghost'}, {'thread': None}, {'thread': ['topic']}, {'thread': '../topic'}):
            with self.subTest(bad=bad):
                self.refused({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'done', **bad})
        for args in (('task', 'set', 'topic', '-1', 'done'), ('task', 'set', 'topic', '2', 'done'), ('task', 'set', 'topic', '1', 'gone'),
                     ('task', 'set', 'topic', str(10 ** 40), 'done'), ('task', 'add', 'topic', 'x' * 301), ('task', 'add', 'ghost', 'x'),
                     ('task', 'set', 'topic', '1', 'done', '--note', 'n' * 201), ('task', 'set', 'topic', '1', 'done', '--owner', 'o' * 61)):
            with self.subTest(args=args[:5]):
                before = (self.board / 'state.json').read_bytes()
                self.run_cli(*args, ok=False)
                self.assertEqual((self.board / 'state.json').read_bytes(), before)
        self.run_cli('close', 'topic')
        self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'working'})       # a tap from a stale tab
        t = self.thread()
        self.assertEqual((t['status'], t['tasks'][0]['status']), ('closed', 'working'))  # it reopens nothing
        self.assertEqual(self.mails(), [])

    def test_held_reply_to_and_reactions_change_nobody_s_turn(self):
        e = self.at
        self.new(env=e(0))
        self.new('else', env=e(0))
        for i in range(3):
            self.run_cli('say', 'else', '--from', 'fork', f'else {i}', env=e(0))          # else/m1..m3
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=e(0))                   # topic/m1
        for bad in ('m3', 'm2', 'M1', ' m1', 'm1 ', 'm01', 'else/m1', '', None, 1, ['m1'], {'id': 'm1'}):
            with self.subTest(reply_to=bad):                                           # another thread's id, its own id, wrong types
                self.refused({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c1', 'reply_to': bad}, env=e(1))
        self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=e(1))             # done: the archive clock runs
        keys = ('state', 'note', 'state_ts', 'state_by', 'auto', 'question', 'resolved', 'touched', 'soon_at', 'archive_at', 'status', 'slot', 'next')
        before = {k: self.thread(env=e(1))[k] for k in keys}
        self.assertIsNotNone(before['archive_at'])
        for i, (emoji, on) in enumerate((('👍', True), ('✅', True), ('👍', False), ('❓', True), ('❓', False), ('✅', False))):
            self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': emoji, 'on': on}, env=e(2 + i))
        t = self.thread(env=e(8))
        self.assertEqual({k: t[k] for k in keys}, before)
        self.assertNotIn('reactions', t['messages'][0])
        self.assertEqual(len(self.mails()), 1)                                         # only the ❓ that was switched on
        for bad in ({'emoji': '👍🏽'}, {'emoji': '❓\ufe0f'}, {'emoji': '❔'}, {'emoji': ''}, {'emoji': None}, {'emoji': ['👍']},
                    {'on': 1}, {'on': 0}, {'on': 'true'}, {'on': None}, {'msg': 'm9'}, {'msg': None}, {'msg': ['m1']}, {'msg': ''},
                    {'thread': 'ghost'}, {'reply_to': 5}):
            with self.subTest(bad=bad):
                self.refused({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': True, **bad}, env=e(9))
        # a ❓ whose save fails mails nobody; the retry mails once
        os.chmod(self.board, 0o555)
        try:
            self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': True}, ok=False, env=e(9))
        finally:
            os.chmod(self.board, 0o755)
        self.assertEqual(len(self.mails()), 1)
        self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '❓', 'on': True}, env=e(9))
        self.assertEqual(len(self.mails()), 2)

    def test_held_snooze_refusals(self):
        e = self.at
        self.new(env=e(0))
        self.new('shut', env=e(0))
        self.run_cli('close', 'shut', env=e(0))
        for bad in ('NaN', 'Infinity', '-Infinity', '1e999', str(self.T0), str(self.T0 - 1), str(self.T0 + 367 * 86400), '"tomorrow"',
                    'true', 'false', 'null', '[1900000000]', '{"until": 1900000000}', '"1800003600"', '1' + '0' * 300):
            with self.subTest(until=bad[:20]):
                self.refused('{"op": "snooze", "thread": "topic", "until": %s}' % bad, env=e(0))
        self.refused({'op': 'snooze', 'thread': 'topic'}, env=e(0))
        self.refused({'op': 'snooze', 'thread': 'shut', 'until': self.T0 + 3600}, env=e(0))
        self.refused({'op': 'snooze', 'thread': 'ghost', 'until': self.T0 + 3600}, env=e(0))
        self.refused({'op': 'unsnooze', 'thread': 'ghost'}, env=e(0))
        for when in ('', ' ', '+', '+h', '+-1h', '+1w', '+1.h', 'tomorrow', 'מחר 9', '2027-01-16', '16.01', 'now', '1e5', '+0m', '+367d',
                     'tomorrow 09:00; rm -rf /', 'today 09:00', '14.01.2027 09:00', '+' + '9' * 400 + 'd', '9999-12-31 23:59', '+1h\n+2h'):
            with self.subTest(until=when[:20]):
                before = (self.board / 'state.json').read_bytes()
                self.run_cli('snooze', 'topic', '--until', when, ok=False, env=e(0))
                self.assertEqual((self.board / 'state.json').read_bytes(), before)
        self.run_cli('snooze', 'shut', '--until', '+1h', ok=False, env=e(0))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 366 * 86400}, env=e(0))      # the far edge is allowed
        self.assertEqual(self.mails(), [])

    def test_held_snooze_times_by_the_local_clock(self):
        zone = zoneinfo.ZoneInfo(TZ)
        stamp = lambda *a: datetime.datetime(*a, tzinfo=zone).timestamp()
        self.new(env=self.at(0))
        cases = ((stamp(2027, 1, 15, 23, 59, 30), 'tomorrow 09:00', stamp(2027, 1, 16, 9, 0)),      # a breath before midnight
                 (stamp(2027, 1, 16, 0, 0, 30), 'tomorrow 09:00', stamp(2027, 1, 17, 9, 0)),        # a breath after
                 (stamp(2027, 1, 31, 12, 0), 'מחר 07:30', stamp(2027, 2, 1, 7, 30)),               # end of a month
                 (stamp(2026, 12, 31, 12, 0), 'tomorrow 00:00', stamp(2027, 1, 1, 0, 0)),          # end of a year
                 (stamp(2027, 1, 15, 8, 0), 'today 09:00', stamp(2027, 1, 15, 9, 0)),
                 (stamp(2027, 3, 25, 12, 0), 'tomorrow 09:00', stamp(2027, 3, 26, 9, 0)),          # the night the clock jumps (02:00 → 03:00)
                 (stamp(2027, 10, 30, 12, 0), 'tomorrow 09:00', stamp(2027, 10, 31, 9, 0)),        # the night it falls back
                 (stamp(2027, 1, 15, 8, 0), '14.01 09:00', stamp(2028, 1, 14, 9, 0)),              # a date that passed is next year's
                 (stamp(2027, 1, 15, 8, 0), '2027-06-01T08:05:09', stamp(2027, 6, 1, 8, 5, 9)),
                 (stamp(2027, 1, 15, 8, 0), '+90m', stamp(2027, 1, 15, 9, 30)), (stamp(2027, 1, 15, 8, 0), '+1.5d', stamp(2027, 1, 16, 20, 0)))
        for clock, when, expect in cases:
            with self.subTest(when=when, clock=clock):
                env = dict(self.env, THREADS_NOW=repr(clock))
                self.run_cli('snooze', 'topic', '--until', when, env=env)
                self.assertEqual(self.thread(env=env)['snooze']['until'], expect)
        env = dict(self.env, THREADS_NOW=repr(stamp(2027, 3, 25, 12, 0)))                # 02:30 does not exist that night: no crash, a time near it
        self.run_cli('snooze', 'topic', '--until', '2027-03-26 02:30', env=env)
        self.assertLessEqual(abs(self.thread(env=env)['snooze']['until'] - stamp(2027, 3, 26, 3, 0)), 3600)

    def test_held_a_wake_is_mailed_exactly_once(self):
        e = self.at
        self.new(env=e(0))
        self.new('shut', env=e(0))
        self.run_cli('close', 'shut', env=e(0))
        self.reply('תבנה', cid='c1', env=e(0))
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 5 * self.H}, env=e(1))
        self.assertEqual(len(self.mails()), 1)                                         # his reply; going to sleep mailed nobody
        asleep = (self.board / 'state.json').read_bytes()
        # the time passed. Commands that are refused or save nothing must neither mail nor lose the wake
        self.assertTrue(self.reply('תבנה', cid='c1', env=e(6))['dup'])
        self.refused({'op': 'react', 'thread': 'topic', 'msg': 'm9', 'emoji': '❓', 'on': True}, env=e(6))
        self.refused({'op': 'reply', 'thread': 'shut', 'text': 'x', 'cid': 'c7'}, env=e(6))
        self.refused({'op': 'snooze', 'thread': 'topic', 'until': 'x'}, env=e(6))
        self.run_cli('task', 'set', 'topic', '9', 'done', ok=False, env=e(6))
        self.run_cli('show', 'ghost', ok=False, env=e(6))
        self.run_cli('snippet', 'topic', 'm1', ok=False, env=e(6))
        self.assertEqual(((self.board / 'state.json').read_bytes(), len(self.mails())), (asleep, 1))
        # an idempotent close of another thread: nothing of its own to save, yet the wake is saved and mailed
        self.post({'op': 'close', 'thread': 'shut'}, env=e(6))
        woke = [m for m in self.mails() if 'snooze woke topic' in m]
        self.assertEqual((len(woke), len(self.mails())), (1, 2))
        t = self.thread(env=e(6))
        self.assertEqual(('snooze' in t, t['reminder']['until'], t['state']), (False, self.T0 + 5 * self.H, 'on-owner'))
        for args in (('list',), ('pending',), ('sweep',), ('show', 'topic')):
            self.run_cli(*args, env=e(7))
        self.post({'op': 'sweep'}, env=e(7))
        self.assertEqual(len(self.mails()), 2)
        # the reminder flag ends with his reply, with a new sleep and with "dismiss"
        self.reply('ראיתי', cid='c2', env=e(8))
        self.assertNotIn('reminder', self.thread(env=e(8)))
        # asleep: an ack and an agent's message wake nothing and mail nobody
        self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 20 * self.H}, env=e(9))
        count = len(self.mails())
        self.run_cli('ack', 'topic', 'm2', env=e(10))
        self.run_cli('say', 'topic', '--from', 'fork', 'בוצע', env=e(10))
        self.assertIn('snooze', self.thread(env=e(10)))
        self.run_cli('close', 'topic', env=e(11))                                      # closed asleep: it never wakes
        self.run_cli('reopen', 'topic', env=e(12))
        self.run_cli('list', env=e(30))
        t = self.thread(env=e(30))
        self.assertEqual(('snooze' in t, 'reminder' in t, len(self.mails())), (False, False, count))

    def test_held_wake_with_a_silent_a_broken_and_a_hanging_notifier(self):
        for name, extra, seconds in (('off', {'THREADS_NOTIFY': '0'}, 3), ('broken', {'THREADS_NOTIFY_CMD': '/nonexistent/tuios'}, 3),
                                     ('failing', {'THREADS_NOTIFY_CMD': 'false'}, 3),
                                     # killed after 5 s, though its child keeps the pipes open
                                     ('hanging', {'THREADS_NOTIFY_CMD': "sh -c 'sleep 12; true'"}, 9)):
            with self.subTest(notifier=name):
                box = Box(Path(self.tmp.name) / name)
                env = lambda h: dict(box.env, THREADS_NOW=repr(self.T0 + h * self.H), **extra)
                self.run_cli('new', 'topic', 'כותרת', env=env(0), box=box)
                self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=env(0), box=box)
                self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 3600}, env=env(0), box=box)
                started = time.monotonic()
                self.post({'op': 'sweep'}, env=env(2), box=box)                        # wakes: exit 0 whatever the notifier does
                self.assertLess(time.monotonic() - started, seconds)
                t = json.loads(self.run_cli('show', 'topic', '--json', env=env(2), box=box).stdout)
                self.assertTrue('snooze' not in t and 'reminder' in t)
                self.post({'op': 'react', 'thread': 'topic', 'msg': 'm1', 'emoji': '👍', 'on': True}, env=env(2), box=box)
                self.assertEqual(box.mails(), [])
                log = box.board / 'notify.log'
                self.assertEqual(log.exists() and len(log.read_text().splitlines()), False if name == 'off' else 1)

    def test_held_drafts_touch_only_the_drafts_file(self):
        e = self.at
        # a v1 state file: a draft must not even upgrade it
        v1 = {'version': 1, 'threads': {'topic': {'id': 'topic', 'title': 'ישן', 'context': '', 'status': 'open', 'created': 90.0,
                                                  'updated': 95.0, 'next': 1, 'messages': []}}}
        self.board.mkdir(parents=True)
        raw = json.dumps(v1, ensure_ascii=False) + '\n'
        (self.board / 'state.json').write_text(raw, encoding='utf-8')
        self.post({'op': 'draft', 'thread': 'topic', 'text': '😀' * 20_000}, env=e(0))      # the cap counts characters, not bytes
        self.post({'op': 'draft', 'thread': '_new', 'text': 'נושא חדש'}, env=e(0))
        self.assertEqual((self.board / 'state.json').read_text(encoding='utf-8'), raw)
        self.assertEqual(sorted(self.box.files()), ['drafts.json', 'state.json'])
        self.assertFalse((self.board / '.pulse').exists())
        for bad in ({'text': '😀' * 20_001}, {'text': None}, {'text': ['x']}, {'text': {'a': 1}}, {'text': 5}, {'text': True},
                    {'text': 'a \ud800'}, {'thread': 'ghost'}, {'thread': '_New'}, {'thread': '_new '}, {'thread': ''}, {'thread': None},
                    {'thread': ['topic']}, {'thread': '../topic'}, {'thread': 'threads'}, {'thread': '__proto__'}):
            with self.subTest(bad=str(bad)[:40]):
                self.refused({'op': 'draft', 'thread': 'topic', 'text': 'x', **bad}, env=e(0))
        self.assertEqual((self.drafts()['topic']['text'], self.drafts()['_new']['text']), ('😀' * 20_000, 'נושא חדש'))
        self.assertEqual(self.mails(), [])
        # no state file at all: only the new-topic form has a draft
        empty = Box(Path(self.tmp.name) / 'empty')
        self.post({'op': 'draft', 'thread': '_new', 'text': 'x'}, box=empty)
        self.post({'op': 'draft', 'thread': 'topic', 'text': 'x'}, ok=False, box=empty)
        self.assertEqual(sorted(empty.files()), ['drafts.json'])

    def test_held_damaged_drafts_file_loses_no_other_draft(self):
        e = self.at
        self.new(env=e(0))
        self.new('else', env=e(0))
        old = self.T0 - 100 * 86400
        good = {'else': {'text': 'טיוטה ישנה מאוד', 'ts': old}, 'gone': {'text': '', 'ts': old}, 'fresh': {'text': '', 'ts': self.T0 - 60},
                'n': 5, 's': 'x', 'l': [1], 'z': None, 'no-ts': {'text': 'בלי זמן'}, 'bad-ts': {'text': '', 'ts': 'x'}}
        self.board.joinpath('drafts.json').write_text(json.dumps({'version': 1, 'drafts': good}))
        self.post({'op': 'draft', 'thread': 'topic', 'text': 'חדש'}, env=e(0))
        d = self.drafts()
        self.assertEqual(sorted(d), ['else', 'fresh', 'no-ts', 'topic'])              # old markers and junk go; every text stays
        self.assertEqual((d['else']['text'], d['no-ts']['text'], d['topic']['text']), ('טיוטה ישנה מאוד', 'בלי זמן', 'חדש'))
        for junk in ('not json', '', '[]', '"x"', '5', 'null', '{"drafts": []}', '{"drafts": "x"}', '{"version": 9}', '\ud800'.encode('utf-8', 'surrogatepass')):
            with self.subTest(junk=junk[:20]):
                path = self.board / 'drafts.json'
                path.write_bytes(junk) if isinstance(junk, bytes) else path.write_text(junk)
                self.post({'op': 'draft', 'thread': 'topic', 'text': 'אחרי נזק'}, env=e(0))
                self.assertEqual(self.drafts(), {'topic': {'text': 'אחרי נזק', 'ts': self.T0}})
        # a reply clears the draft of its own thread only, and a refused or repeated reply clears nothing
        self.post({'op': 'draft', 'thread': 'else', 'text': 'של השני'}, env=e(1))
        self.post({'op': 'draft', 'thread': '_new', 'text': 'נושא'}, env=e(1))
        self.refused({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c1'}, env=e(2))
        self.reply('שלחתי', cid='c1', env=e(3))
        self.post({'op': 'draft', 'thread': 'topic', 'text': 'כבר כותב את הבא'}, env=e(4))
        self.assertTrue(self.reply('שלחתי', cid='c1', env=e(5))['dup'])
        d = self.drafts()
        self.assertEqual((d['topic']['text'], d['else']['text'], d['_new']['text']), ('כבר כותב את הבא', 'של השני', 'נושא'))
        self.reply('והבא', cid='c2', env=e(6))
        self.assertEqual(self.drafts()['topic'], {'text': '', 'ts': self.T0 + 6 * self.H})

    def test_held_concurrent_drafts_lose_nothing(self):
        """The server runs one hook at a time; here many run at once. Every draft that was answered `ok` is in the file."""
        ids = [f't{i}' for i in range(12)]
        for tid in ids:
            self.new(tid)
        state = (self.board / 'state.json').read_bytes()

        def one(tid):
            self.box.body({'op': 'draft', 'thread': tid, 'text': 'טיוטה של ' + tid})    # the body is shared: whoever runs may read a neighbour's
            r = self.box.cli('ingest')
            return json.loads(r.stdout).get('thread') if r.returncode == 0 else None
        with concurrent.futures.ThreadPoolExecutor(12) as pool:
            saved = {tid for tid in pool.map(one, ids * 3) if tid}
        self.assertTrue(saved)
        d = self.drafts()
        self.assertEqual(saved - set(d), set())
        self.assertTrue(all(d[tid]['text'] == 'טיוטה של ' + tid for tid in saved))
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.assertEqual(self.mails(), [])

    def test_held_old_pages_and_old_state_files(self):
        e = self.at
        # a state written before tasks, snooze, reactions: the new keys are absent
        self.new(env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=e(0))
        data = self.state()
        for key in ('tasks', 'snooze', 'reminder'):
            data['threads']['topic'].pop(key, None)
        data.pop('ops', None)
        self.put_state(data)
        self.assertEqual(self.reply('שלום', cid='old-1', env=e(1)), {'ok': True, 'thread': 'topic', 'msg_id': 'm2', 'dup': False})   # an old page: op, thread, text, cid
        row = json.loads(self.run_cli('pending', env=e(1)).stdout)[0]
        self.assertEqual(set(row), {'thread', 'title', 'context', 'msg_id', 'text', 'ts', 'history', 'slot', 'state', 'note', 'summary', 'links'})
        self.assertEqual(set(row['history'][0]), {'id', 'from', 'text', 'ts'})
        t = self.thread(env=e(1))
        self.assertEqual((t['tasks'], 'snooze' in t), ([], False))
        ops = self.state()['ops']    # the ops an old page knew come first and unchanged; a newer server may list more after them
        self.assertEqual(ops[:12], ['reply', 'close', 'reopen', 'keep', 'done', 'sweep', 'rename', 'task', 'react', 'snooze', 'unsnooze', 'draft'])
        self.assertTrue(all(isinstance(op, str) and re.fullmatch(r'[a-z][a-z-]{0,30}', op) for op in ops[12:]), ops)
        self.run_cli('ack', 'topic', 'm2', env=e(1))
        self.run_cli('state', 'topic', 'done', env=e(2))
        self.assertEqual(json.loads(self.run_cli('sweep', env=e(30)).stdout), ['topic'])              # and it still archives itself
        # a v1 file: the first NEW op upgrades it once, keeps a backup, and works
        v1 = {'version': 1, 'threads': {'a': {'id': 'a', 'title': 'A', 'context': '', 'status': 'open', 'created': 100.0, 'updated': 150.0, 'next': 2,
                                              'messages': [{'id': 'm1', 'from': 'owner', 'text': 'תעשה', 'ts': 150.0, 'status': 'pending', 'cid': 'x'}]}}}
        box = Box(Path(self.tmp.name) / 'v1')
        box.board.mkdir(parents=True)
        raw = json.dumps(v1, ensure_ascii=False, indent=2) + '\n'
        (box.board / 'state.json').write_text(raw, encoding='utf-8')
        env = dict(box.env, THREADS_NOW=repr(self.T0))
        self.post({'op': 'react', 'thread': 'a', 'msg': 'm1', 'emoji': '✅', 'on': True}, env=env, box=box)
        self.post({'op': 'snooze', 'thread': 'a', 'until': self.T0 + 3600}, env=env, box=box)
        self.post({'op': 'rename', 'thread': 'a', 'title': 'שם חדש'}, env=env, box=box)
        self.run_cli('task', 'add', 'a', 'משימה', env=env, box=box)
        t = json.loads(self.run_cli('show', 'a', '--json', env=env, box=box).stdout)
        self.assertEqual((t['title'], t['state'], t['tasks'][0]['n'], t['messages'][0]['reactions']['✅']['by'], t['snooze']['until']),
                         ('שם חדש', 'working', 1, 'owner', self.T0 + 3600))
        backups = list((box.board.parent.parent / '.threads-config' / box.board.name / 'backups').glob('state.json.v1-*'))
        self.assertEqual((len(backups), backups[0].read_text(encoding='utf-8')), (1, raw))
        self.assertEqual(box.mails(), [])

    def test_held_new_ops_as_untrusted_input(self):
        """Wrong types, missing keys, extra keys, odd thread ids: always one JSON line, exit 0 exactly when ok,
        never a traceback, and a refusal writes nothing. Spread over several boards to keep it short."""
        junk = [None, True, 1.5, -1, 10 ** 25, '', 'x' * 300, '\x00', '../../x', 'm1\n', [], ['m1'], {}, {'op': 'reply'}, '\ud800']
        base = {'rename': {'title': 'שם'}, 'task': {'n': 1, 'status': 'done'}, 'react': {'msg': 'm1', 'emoji': '👍', 'on': True},
                'snooze': {'until': self.T0 + 3600}, 'unsnooze': {}, 'draft': {'text': 'טיוטה'},
                'reply': {'text': 'שלום', 'cid': 'c1', 'reply_to': 'm1', 'q': None, 'under': None}}
        snippet = {'text': 'גוף', 'name': 'a.md'}
        payloads = [5, 'x', None, [], {}, {'op': None}, {'op': ['draft']}, {'op': {'a': 1}}, {'op': 'Draft'}, {'op': 'tasks'},
                    '{"op": "task", "thread": "topic", "n": 1e400, "status": "done"}', '{"op": "snooze", "thread": "topic"',
                    '[' * 100_000, '{"op": "task", "thread": "topic", "n": ' + '9' * 5000 + ', "status": "done"}']
        for op, fields in base.items():
            full = {'op': op, 'thread': 'topic', **fields}
            payloads.append({**full, 'extra': {'deep': [1, 2]}, 'board': 'x', 'last': 'm1'})   # extra keys
            for key in ['thread', *fields]:
                payloads.append({k: v for k, v in full.items() if k != key})                   # a missing key
                payloads.extend({**full, key: bad} for bad in junk)
            if op == 'reply':
                payloads.extend({**full, 'snippet': bad} for bad in junk)
                payloads.append({**full, 'snippet': {**snippet, 'extra': [1]}, 'cid': 'with-snippet'})
                for key in ('text', 'name'):
                    payloads.extend({**full, 'cid': f'c-{key}-{n}', 'snippet': {**snippet, key: bad}} for n, bad in enumerate(junk))
        boxes = [Box(Path(self.tmp.name) / f'fuzz{i}') for i in range(8)]

        def work(i):
            box, problems = boxes[i], []
            env = dict(box.env, THREADS_NOW=repr(self.T0))
            for args in (('new', 'topic', 'כותרת'), ('say', 'topic', '--from', 'fork', 'דוח'), ('task', 'add', 'topic', 'לבנות')):
                box.cli(*args, env=env)
            for n, payload in enumerate(payloads[i::8]):
                before, mails = box.files(), box.mails()
                r = box.post(payload, env=dict(env, THREADS_NOW=repr(self.T0 + n + 1)))
                what = str(payload)[:90]
                lines = r.stdout.strip().splitlines()
                if 'Traceback' in r.stderr or len(lines) != 1:
                    problems.append(f'{what}: stdout {r.stdout[:200]!r} stderr {r.stderr[-300:]!r}')
                    continue
                answer = json.loads(lines[0])
                if not isinstance(answer.get('ok'), bool) or answer['ok'] != (r.returncode == 0):
                    problems.append(f'{what}: exit {r.returncode} with {answer}')
                elif not answer['ok'] and (box.files() != before or box.mails() != mails):
                    problems.append(f'{what}: refused, yet something was written or mailed')
            return problems
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            problems = [p for found in pool.map(work, range(8)) for p in found]
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()
