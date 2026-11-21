"""Hostile tests for threads.py (reviewer A).

Every test asserts the CORRECT / SAFE outcome, so a FAILING test is a real hole.
Tests named ``test_held_*`` are attacks that the code survived (they pass).

Nothing here touches the owner's live data: every CLI run gets BOARDS_DIR inside a
temp dir in this repository, and notifications go to a local recorder script.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import concurrent.futures
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
LIVE_V1 = ROOT / 'live-v1-state.json'
H = 3600.0


class Base(unittest.TestCase):
    T0 = 1_800_000_000.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.adv-a-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.state = self.board / 'state.json'
        self.request = self.board / 'state/state.json'
        self.pulse = self.board / '.pulse'
        self.record = self.root / 'notifications.jsonl'
        recorder = self.root / 'record.py'
        recorder.write_text("import json, os, sys\nfrom pathlib import Path\nwith Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args':sys.argv[1:]})+'\\n')\n")
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'),
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]),
                        NOTIFY_RECORD=str(self.record))
        self.env.pop('THREADS_CONFIG_DIR', None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (self.root / '.threads-config/threads').mkdir(parents=True)
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')
        for key in ('THREADS_NOTIFY', 'THREADS_NOW', 'THREADS_SLUG', 'BOARD_LOCK_TIMEOUT'):
            self.env.pop(key, None)

    # ── running the CLI, always against the temp board ──────────────────────
    def cli(self, *args, env=None, input=None):
        env = env or self.env
        assert env['BOARDS_DIR'].startswith(str(ROOT) + os.sep), 'refusing to run outside the worktree'
        assert env.get('THREADS_NOTIFY_CMD') or env.get('THREADS_NOTIFY') == '0'
        return subprocess.run([sys.executable, str(CLI), *args], env=env, input=input, capture_output=True, text=True)

    def ok(self, *args, env=None, input=None):
        r = self.cli(*args, env=env, input=input)
        self.assertEqual(r.returncode, 0, f'{args}: {r.stderr}{r.stdout}')
        self.assertNotIn('Traceback', r.stderr)
        return r

    def at(self, hours):
        return dict(self.env, THREADS_NOW=repr(self.T0 + hours * H))

    def data(self):
        return json.loads(self.state.read_text())

    def t(self, tid='topic'):
        return self.data()['threads'][tid]

    def snapshot(self):
        """Everything a refused or read-only command must leave alone."""
        files = {}
        if self.board.exists():
            for p in sorted(self.board.rglob('*')):
                if p.is_file() and not p.name.endswith('.lock') and p != self.request:
                    files[str(p.relative_to(self.board))] = (p.read_bytes(), p.stat().st_mtime_ns)
        return files

    def refused(self, *args, env=None, input=None):
        """The command must fail cleanly and leave every byte and the pulse as they were."""
        before = self.snapshot()
        r = self.cli(*args, env=env, input=input)
        label = str(args)[:110]
        self.assertNotEqual(r.returncode, 0, f'{label} was accepted: {r.stdout[:60]}')
        self.assertNotIn('Traceback', r.stderr, f'{label}: traceback')
        after = self.snapshot()
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(changed, [], f'{label}: a refused command wrote these files')
        return r

    def unchanged(self, *args, env=None):
        """A read: succeeds and writes nothing (no state rewrite, no pulse)."""
        before = self.snapshot()
        r = self.ok(*args, env=env)
        after = self.snapshot()
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(changed, [], f'{args}: a command that changes nothing wrote these files')
        return r

    # ── the page ────────────────────────────────────────────────────────────
    def put_request(self, body):
        self.request.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            self.request.write_bytes(body)
        elif isinstance(body, str):
            self.request.write_text(body, encoding='utf-8')
        else:
            self.request.write_text(json.dumps(body), encoding='utf-8')

    def post(self, body, env=None):
        """What the server does: store the body, run the hook. Returns the parsed single line."""
        self.put_request(body)
        r = self.cli('ingest', env=env)
        self.assertNotIn('Traceback', r.stderr, r.stderr[-400:])
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, f'not exactly one line: {r.stdout!r} / {r.stderr[-300:]!r}')
        out = json.loads(lines[0])
        self.assertEqual(r.returncode == 0, out.get('ok') is True, (r.returncode, out))
        return out

    def post_ok(self, body, env=None):
        out = self.post(body, env=env)
        self.assertTrue(out['ok'], out)
        return out

    def post_refused(self, body, env=None, again=False):
        """Hostile body: one {"ok": false, "error": …} line, non-zero exit, no traceback, nothing changed."""
        before = self.snapshot()
        notified = self.record.read_bytes() if self.record.exists() else b''
        self.put_request(body)
        r = self.cli('ingest', env=env)
        label = repr(body)[:120]
        self.assertNotIn('Traceback', r.stderr, f'{label}: traceback: {r.stderr[-300:]}')
        self.assertNotEqual(r.returncode, 0, f'{label}: accepted: {r.stdout}')
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, f'{label}: stdout {r.stdout!r}')
        out = json.loads(lines[0])
        # a failure that may pass by the next try (the lock was not free in time) says so, and the page sends again by itself
        self.assertEqual(set(out), {'ok', 'error', 'again'} if again else {'ok', 'error'}, label)
        self.assertIs(out['ok'], False, label)
        self.assertTrue(isinstance(out['error'], str) and out['error'].strip(), label)
        self.assertEqual(r.stderr, '', label)
        self.assertEqual(self.snapshot(), before, f'{label}: a refused request wrote something')
        self.assertEqual(self.record.read_bytes() if self.record.exists() else b'', notified, f'{label}: a refused request notified')
        return out

    def slots(self):
        return {t['id']: t['slot'] for t in self.data()['threads'].values() if t['status'] == 'open'}

    def write_state(self, data):
        self.board.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def assert_note_rule(self, t):
        if t['status'] == 'open' and t['state'] == 'on-owner':
            note = t['note']
            self.assertTrue(isinstance(note, str) and note.strip(), f"{t['id']}: on-owner with an empty note {note!r}")
            self.assertEqual(len(note.splitlines()), 1, f"{t['id']}: note is not one line: {note!r}")
            self.assertLessEqual(len(note), 200, t['id'])


# ═══ 5. ingest: the request file is untrusted ═══════════════════════════════

class IngestHostile(Base):
    def setUp(self):
        super().setUp()
        self.ok('new', 'topic', 'כותרת', '--context', 'רקע')
        self.ok('ask', 'topic', 'A או B?', '--options', 'A,B')

    def test_held_ingest_wrong_types_everywhere(self):
        junk = [None, True, False, 0, 1, -1, 1.5, [], ['reply'], {}, {'a': 1}, [[['x']]], '', ' ', 'nope']
        good = {'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c1', 'q': 'm1'}
        bodies = []
        for key in ('op', 'thread', 'text', 'cid', 'q'):
            for value in junk:
                if key == 'q' and value is None:
                    continue                                    # no q is the old page: allowed
                if key == 'text' and value == 'nope':
                    continue
                if key == 'cid' and value == 'nope':
                    continue
                bodies.append(dict(good, **{key: value}))
            bodies.append({k: v for k, v in good.items() if k != key} if key != 'q' else dict(good, q='m0'))
        for op in ('close', 'reopen', 'keep', 'done'):
            for value in junk[:-1] + ['ghost', '../topic', 'topic/', '/topic', 'topic\x00', 'TOPIC', 'טופיק', '..', '.', 'threads/topic']:
                bodies.append({'op': op, 'thread': value})
            bodies.append({'op': op})
        bodies += [{}, {'thread': 'topic'}, {'op': 'REPLY', 'thread': 'topic', 'text': 'x', 'cid': 'c'},
                   {'op': 'reply ', 'thread': 'topic', 'text': 'x', 'cid': 'c'},
                   {'op': 'rm', 'thread': 'topic'}, {'op': 'new', 'thread': 'x'}, {'op': 'policy', 'idle_hours': 0},
                   {'op': 'install'}, {'op': 'resolve', 'thread': 'topic'}, {'op': 'state', 'thread': 'topic', 'state': 'done'},
                   {'op': 'ask', 'thread': 'topic', 'question': 'x'}, {'op': 'ack', 'thread': 'topic', 'msg_id': 'm1'},
                   {'op': 'set', 'thread': 'topic', 'title': 'x'}, {'op': 'link', 'thread': 'topic', 'label': 'x', 'target': 'javascript:1'}]
        for body in bodies:
            with self.subTest(body=json.dumps(body, ensure_ascii=False)[:100]):
                self.post_refused(body)

    def test_held_ingest_raw_garbage_files(self):
        raws = [b'', b' ', b'\n', b'not json', b'{', b'{"op":', b'[]', b'[{"op":"sweep"}]', b'null', b'true', b'7', b'"sweep"',
                b'\xef\xbb\xbf{"op":"sweep"}', b'\xff\xfe{\x00', b'{"op":"reply","thread":"topic","text":"\xff","cid":"c"}',
                '{"op":"sweep"}'.encode('utf-16'), b'{"op":"sweep"} trailing', b'{"op":"sweep"}{"op":"sweep"}',
                b"{'op':'sweep'}", b'{"op":"reply","thread":"topic","text":"x","cid":"c","q":NaN}',
                b'{"op":"reply","thread":"topic","text":"x","cid":"c","q":Infinity}',
                b'{"op":"reply","thread":"topic","text":"x","cid":"c","q":1' + b'0' * 5000 + b'}',
                b'{"op":"reply","thread":"topic","text":"x","cid":1e400}', b'\x00' * 64]
        for raw in raws:
            with self.subTest(raw=raw[:60]):
                self.post_refused(raw)

    def test_held_ingest_missing_or_odd_request_file(self):
        before = self.snapshot()
        for case in ('missing', 'directory'):
            with self.subTest(case=case):
                if case == 'directory':
                    self.request.mkdir(parents=True)
                r = self.cli('ingest')
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stderr, '')
                self.assertIs(json.loads(r.stdout)['ok'], False)
                self.assertEqual(len(r.stdout.splitlines()), 1)
                self.assertEqual(self.snapshot(), before)

    def test_held_ingest_size_limits(self):
        for body in ({'op': 'reply', 'thread': 'topic', 'text': 'x' * 8001, 'cid': 'c'},
                     {'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c' * 81},
                     {'op': 'reply', 'thread': 't' * 3_000_000, 'text': 'x', 'cid': 'c'},
                     {'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c', 'q': 'm' * 3_000_000},
                     {'op': 'close', 'thread': 'x' * 3_000_000},
                     {'op': 'x' * 3_000_000, 'thread': 'topic'}):
            with self.subTest(body=str(body)[:60]):
                self.post_refused(body)
        self.assertEqual(self.post_ok({'op': 'reply', 'thread': 'topic', 'text': '🙂' * 8000, 'cid': 'c' * 80})['msg_id'], 'm2')

    def test_held_ingest_lone_surrogate_is_refused_cleanly(self):
        for key in ('text', 'cid'):
            with self.subTest(key=key):
                body = {'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c'}
                body[key] = 'a\ud800b'
                self.post_refused(json.dumps(body))            # json.dumps keeps it as the escape \ud800
        self.post_refused(json.dumps({'op': 'close', 'thread': 'top\udc00ic'}))

    def test_held_ingest_control_characters_are_stored_exactly(self):
        text = 'a\x00b\x01\x07\x08\x1b[31mred\x7f\u2028\u202e\ufeff\r\n\ttab'
        out = self.post_ok({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': 'c\x00\x1b'})
        self.assertEqual(out, {'ok': True, 'thread': 'topic', 'msg_id': 'm2', 'dup': False})
        self.assertEqual(self.t()['messages'][-1]['text'], text)
        self.assertTrue(self.post_ok({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': 'c\x00\x1b'})['dup'])
        self.assert_note_rule(self.t())
        self.unchanged('list')
        self.unchanged('pending')

    def test_held_ingest_extra_keys_are_ignored(self):
        out = self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c', 'under': 'm1', 'from': 'tower', 'status': 'acked',
                            'id': 'm99', 'ts': 1, 'state': 'done', 'slot': 7, 'by': 'auto', 're': {'q': 'zz'}, 'board': 'other',
                            '__proto__': {'x': 1}})
        msg = self.t()['messages'][-1]
        self.assertEqual((out['msg_id'], msg['id'], msg['from'], msg['status']), ('m2', 'm2', 'owner', 'pending'))
        self.assertEqual(set(msg), {'id', 'from', 'text', 'ts', 'status', 'cid', 're'})
        self.assertEqual(msg['re'], {'q': 'm1', 'text': 'A או B?'})
        self.assertEqual((self.t()['state'], self.t()['slot']), ('working', 1))

    def test_ingest_deeply_nested_json_prints_a_traceback(self):
        # RecursionError is not in the list main() catches.
        for raw in (b'[' * 100_000, b'{"op":"reply","thread":"topic","text":"x","cid":"c","q":' + b'[' * 100_000 + b']' * 100_000 + b'}'):
            with self.subTest(raw=raw[:40]):
                self.post_refused(raw)

    def test_held_ingest_error_line_in_a_bare_environment(self):
        # What a launchd-started server hands the hook: no LANG at all, or the C locale.
        for extra in ({}, {'LC_ALL': 'C'}, {'LANG': 'C'}, {'LC_ALL': 'POSIX'}):
            with self.subTest(extra=extra):
                env = {k: v for k, v in self.env.items() if k in ('PATH', 'HOME', 'BOARDS_DIR', 'THREADS_NOTIFY_CMD', 'NOTIFY_RECORD')}
                self.post_refused({'op': 'close', 'thread': 'ghost'}, env=dict(env, **extra))
                self.assertEqual(self.post_ok({'op': 'keep', 'thread': 'topic'}, env=dict(env, **extra))['ok'], True)

    def test_ingest_error_line_survives_a_non_utf8_stdout(self):
        # The hook inherits the server's environment; the refusal text is Hebrew.
        env = dict(self.env, PYTHONIOENCODING='ascii')
        self.post_refused({'op': 'close', 'thread': 'ghost'}, env=env)


# ═══ 6. replies: idempotent, question-bound, never into a closed thread ═════

class Replies(Base):
    def test_held_reply_is_idempotent_by_cid(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('new', 'other', 'T', env=e(0))
        first = self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'one', 'cid': 'c1'}, env=e(1))
        for hours, text in ((1.1, 'one'), (2, 'a different text, same cid'), (500, 'one')):
            again = self.post_ok({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': 'c1'}, env=e(hours))
            self.assertEqual(again, {'ok': True, 'thread': 'topic', 'msg_id': first['msg_id'], 'dup': True})
        t = self.t()
        self.assertEqual([m['text'] for m in t['messages']], ['one'])
        self.assertEqual(len(self.record.read_text().splitlines()), 1)             # one notification
        # a retry still dedupes after the agent acked and answered
        self.ok('ack', 'topic', 'm1', env=e(3))
        self.ok('say', 'topic', '--from', 'fork', 'answer', env=e(3))
        self.assertTrue(self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'one', 'cid': 'c1'}, env=e(4))['dup'])
        self.assertEqual((self.t()['state'], len(self.t()['messages'])), ('on-owner', 2))
        # the same cid in another thread is another message
        self.assertFalse(self.post_ok({'op': 'reply', 'thread': 'other', 'text': 'one', 'cid': 'c1'}, env=e(5))['dup'])
        # a duplicate writes nothing at all
        before = self.snapshot()
        self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'one', 'cid': 'c1'}, env=e(6))
        self.assertEqual(self.snapshot(), before)

    def test_held_reply_with_q_needs_the_open_question(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        reply = lambda cid, q, hours: {'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': cid, 'q': q}
        self.post_refused(reply('c0', 'm1', 0), env=e(0.1))                          # no question at all
        self.ok('ask', 'topic', 'Q1?', '--options', 'כן,לא', env=e(1))
        self.ok('ask', 'topic', 'Q2?', '--options', 'כן,לא', '--replace', 'm1', env=e(2))   # takes Q1 back (several stay open only without it, suda m508)
        for q in ('m1', 'm3', '', ' m2', 'm2 ', 'M2', 'm02', '2'):
            with self.subTest(q=q):
                self.post_refused(reply('cx', q, 0), env=e(2.5))
        self.assertEqual(self.post_ok(reply('c2', 'm2', 0), env=e(3))['msg_id'], 'm3')
        self.assertEqual(self.t()['messages'][-1]['re'], {'q': 'm2', 'text': 'Q2?'})
        self.assertIsNone(self.t()['question'])
        self.post_refused(reply('c3', 'm2', 0), env=e(3.1))                          # answered: no longer open
        # a question withdrawn by resolve or by a done is no longer answerable
        for i, closer in enumerate((('resolve', 'topic'), ('say', 'topic', '--from', 'fork', 'x', '--state', 'done'))):
            qid = self.ok('ask', 'topic', 'again?', env=e(4 + i)).stdout.strip()
            self.ok(*closer, env=e(4.1 + i))
            self.post_refused(reply(f'cw{i}', qid, 0), env=e(4.2 + i))
        # but an agent that only writes again does not withdraw it (he found 13 questions that had "expired" this way)
        qid = self.ok('ask', 'topic', 'still?', env=e(7)).stdout.strip()
        self.ok('state', 'topic', 'working', '--note', 'בינתיים עובד', env=e(7.1))
        self.assertEqual(self.t()['question']['id'], qid)
        self.post_ok(reply('cw9', qid, 0), env=e(7.2))

    def test_held_question_survives_close_and_reopen(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('ask', 'topic', 'A או B?', '--options', 'A,B', env=e(1))
        self.ok('close', 'topic', env=e(2))
        self.post_refused({'op': 'reply', 'thread': 'topic', 'text': 'A', 'cid': 'c1', 'q': 'm1'}, env=e(2.1))
        self.post_refused({'op': 'reply', 'thread': 'topic', 'text': 'A', 'cid': 'c1'}, env=e(2.1))
        self.ok('reopen', 'topic', env=e(3))
        self.assertEqual(self.t()['question']['id'], 'm1')
        self.assertEqual(self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'A', 'cid': 'c1', 'q': 'm1'}, env=e(3.1))['msg_id'], 'm2')
        t = self.t()
        self.assertEqual((t['state'], t['question'], t['messages'][-1]['re']['q']), ('working', None, 'm1'))

    def test_held_resolve_then_reply_reopens_the_turn(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('resolve', 'topic', '--note', 'מוזג', env=e(1))
        self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'רגע, לא', 'cid': 'c1'}, env=e(2))
        t = self.t()
        self.assertEqual((t['state'], t['resolved'], t['archive_at'], t['soon_at']), ('working', False, None, None))
        self.unchanged('list', env=e(90000))
        self.assertEqual(self.t()['status'], 'open')

    def test_stale_reply_answers_a_question_of_a_recreated_thread(self):
        # Message ids restart at m1 when an id is reused, so "q": "m1" from an old tab or
        # the page's persisted outbox passes the open-question check of another question.
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('ask', 'topic', 'למחוק את הענף הישן?', '--options', 'כן,לא', env=e(1))
        self.ok('rm', 'topic', '--yes', env=e(2))
        self.ok('new', 'topic', 'T2', env=e(3))
        self.ok('ask', 'topic', 'למחוק את בסיס הנתונים?', '--options', 'כן,לא', env=e(4))
        self.post_refused({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'old-tab', 'q': 'm1'}, env=e(5))


# ═══ page one-tap actions in every state ════════════════════════════════════

class PageOps(Base):
    def make_states(self, e):
        self.ok('new', 'auto', 'T', env=e(0))                                          # on-owner, automatic
        self.ok('new', 'explicit', 'T', '--note', 'להחליט', env=e(0))                   # on-owner, an explicit ask
        self.ok('new', 'asked', 'T', env=e(0))
        self.ok('ask', 'asked', 'A או B?', '--options', 'A,B', env=e(0))
        self.ok('new', 'working', 'T', '--state', 'working', '--note', 'בונה', env=e(0))
        self.ok('new', 'replied', 'T', env=e(0))
        self.ok('say', 'replied', '--from', 'owner', 'תעשה', env=e(0))                 # working, automatic, pending
        self.ok('new', 'done', 'T', '--state', 'done', '--note', 'נגמר', env=e(0))
        self.ok('new', 'resolved', 'T', env=e(0))
        self.ok('resolve', 'resolved', env=e(0))
        self.ok('new', 'closed', 'T', env=e(0))
        self.ok('close', 'closed', env=e(0))
        return ('auto', 'explicit', 'asked', 'working', 'replied', 'done', 'resolved', 'closed')

    def test_held_done_only_dismisses_an_automatic_on_owner(self):
        e = self.at
        for tid in self.make_states(e):
            with self.subTest(tid=tid):
                last = (self.t(tid)['messages'] or [{'id': ''}])[-1]['id']     # "read it" names the last message on his screen
                if tid == 'auto':
                    self.post_ok({'op': 'done', 'thread': tid, 'last': last}, env=e(1))
                    t = self.t(tid)
                    self.assertEqual((t['state'], t['question'], t['archive_at']), ('done', None, self.T0 + 25 * H))
                else:
                    self.post_refused({'op': 'done', 'thread': tid, 'last': last}, env=e(1))

    def test_held_keep_never_changes_the_turn(self):
        e = self.at
        for tid in self.make_states(e):
            with self.subTest(tid=tid):
                before = self.t(tid)
                if tid == 'closed':
                    self.post_refused({'op': 'keep', 'thread': tid}, env=e(1))
                    continue
                self.post_ok({'op': 'keep', 'thread': tid}, env=e(1))
                after = self.t(tid)
                for key in ('state', 'note', 'auto', 'question', 'slot', 'messages', 'state_by', 'state_ts', 'status'):
                    self.assertEqual(after[key], before[key], key)
                self.assertFalse(after['resolved'])
                expected = self.T0 + 25 * H if after['state'] == 'done' else None
                self.assertEqual(after['archive_at'], expected)

    def test_held_close_and_reopen_from_the_page_in_every_state(self):
        e = self.at
        tids = self.make_states(e)
        slots = self.slots()
        for tid in tids:
            with self.subTest(tid=tid):
                before = self.t(tid)
                self.post_ok({'op': 'close', 'thread': tid}, env=e(1))
                self.post_ok({'op': 'close', 'thread': tid}, env=e(1.1))
                self.post_ok({'op': 'reopen', 'thread': tid}, env=e(2))
                self.post_ok({'op': 'reopen', 'thread': tid}, env=e(2.1))
                after = self.t(tid)
                for key in ('state', 'note', 'auto', 'question', 'messages', 'state_by', 'state_ts'):
                    self.assertEqual(after[key], before[key], key)
                self.assertEqual(after['status'], 'open')
                if tid in slots:
                    self.assertEqual(after['slot'], slots[tid])
        self.assertEqual(len(set(self.slots().values())), len(tids))

    def test_held_sweep_op_ignores_everything_else_in_the_body(self):
        e = self.at
        self.make_states(e)
        out = self.post_ok({'op': 'sweep', 'thread': ['x'], 'text': 7, 'cid': None}, env=e(5000))
        self.assertEqual(sorted(out['archived']), ['done', 'resolved'])
        open_now = {t['id'] for t in self.data()['threads'].values() if t['status'] == 'open'}
        self.assertEqual(open_now, {'auto', 'explicit', 'asked', 'working', 'replied'})


# ═══ 1. slots ═══════════════════════════════════════════════════════════════

class Slots(Base):
    def test_held_parallel_new_gives_unique_slots(self):
        def new(i):
            return self.cli('new', f't{i}', f'T {i}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(new, range(20)))
        self.assertEqual([r.returncode for r in results], [0] * 20, [r.stderr for r in results if r.returncode])
        slots = self.slots()
        self.assertEqual(len(slots), 20)
        self.assertEqual(sorted(slots.values()), list(range(1, 21)))

    def test_held_parallel_new_same_id_creates_one(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda i: self.cli('new', 'same', f'T {i}'), range(12)))
        self.assertEqual(sorted(r.returncode for r in results), [0] + [1] * 11)
        self.assertEqual(self.slots(), {'same': 1})

    def test_held_close_and_reopen_cycles_never_move_anyone_else(self):
        e = self.at
        for tid in 'abcde':
            self.ok('new', tid, 'T', env=e(0))
        fixed = {k: v for k, v in self.slots().items() if k != 'c'}
        seen = set()
        for i in range(1, 13):
            self.ok('close', 'c', env=e(i))
            self.assertEqual(self.slots(), fixed)
            if i % 3 == 0:                                          # someone takes a slot while c is closed
                self.ok('new', f'n{i}', 'T', env=e(i + 0.2))
                fixed[f'n{i}'] = self.slots()[f'n{i}']
                self.assertNotEqual(fixed[f'n{i}'], 3)              # c's slot rests
            self.ok('reopen', 'c', env=e(i + 0.5))
            slots = self.slots()
            self.assertEqual({k: v for k, v in slots.items() if k != 'c'}, fixed)
            self.assertEqual(slots['c'], 3)
            seen.add(slots['c'])
            self.assertEqual(len(set(slots.values())), len(slots))

    def test_held_reopen_when_the_old_slot_was_taken(self):
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('close', 'b', env=e(1))
        self.ok('new', 'd', 'T', env=e(8))                           # cooldown over: d takes slot 2
        self.assertEqual(self.slots(), {'a': 1, 'd': 2, 'c': 3})
        self.ok('reopen', 'b', env=e(9))
        self.assertEqual(self.slots(), {'a': 1, 'd': 2, 'c': 3, 'b': 4})
        self.ok('close', 'b', env=e(10))
        self.ok('reopen', 'b', env=e(11))
        self.assertEqual(self.slots()['b'], 4)                       # its new place is now its place

    def test_held_auto_archived_thread_reopens_into_its_slot(self):
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('state', 'b', 'done', env=e(0))
        self.ok('list', env=e(30))
        self.assertEqual((self.t('b')['status'], self.t('b')['closed_by'], self.t('b')['slot']), ('closed', 'auto', 2))
        self.ok('new', 'd', 'T', env=e(31))
        self.assertEqual(self.slots()['d'], 4)                       # an archived slot rests too
        self.post_ok({'op': 'reopen', 'thread': 'b'}, env=e(32))
        t = self.t('b')
        self.assertEqual((t['status'], t['slot'], t['state'], t['archive_at']), ('open', 2, 'done', self.T0 + 56 * H))
        self.unchanged('list', env=e(55.9))
        self.assertEqual(self.t('b')['status'], 'open')

    def test_rm_gives_a_fresh_slot_to_another_thread_at_once(self):
        # Deleting a record deletes the only memory of when its slot was freed.
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('rm', 'b', '--yes', env=e(1))
        self.ok('new', 'd', 'T', env=e(1.01))                        # 36 seconds later, cooldown is 6 hours
        self.assertNotEqual(self.slots()['d'], 2, 'slot 2 was freed 36 s ago and went to a different thread')

    def test_rm_of_a_closed_thread_ends_its_slot_cooldown(self):
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('close', 'b', env=e(1))
        self.ok('rm', 'b', '--yes', env=e(1.5))
        self.ok('new', 'd', 'T', env=e(2))
        self.assertNotEqual(self.slots()['d'], 2, 'slot 2 was freed 1 h ago and went to a different thread')

    def test_reopen_takes_its_old_slot_while_it_rests_for_another_thread(self):
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('close', 'b', env=e(1))
        self.ok('new', 'd', 'T', env=e(8))                           # d owns slot 2 now
        self.ok('close', 'd', env=e(9))                              # d frees slot 2 at hour 9
        self.ok('reopen', 'b', env=e(9.1))                           # 6 minutes later
        self.assertNotEqual(self.slots()['b'], 2, 'slot 2 was freed by d 6 min ago and went to b')

    def test_held_hand_edited_slots_are_mended_once(self):
        for tid in 'abcdefgh':
            self.ok('new', tid, 'T')
        data = self.data()
        for tid, slot in zip('bcdefgh', (0, -3, 2.0, True, '3', 10 ** 9, None)):
            data['threads'][tid]['slot'] = slot
        self.write_state(data)
        self.ok('list')
        slots = self.slots()
        self.assertEqual(slots['a'], 1)
        self.assertTrue(all(type(s) is int and 0 < s < 1000 for s in slots.values()), slots)
        self.assertEqual(len(set(slots.values())), 8)
        self.unchanged('list')                                       # mended once, then quiet
        self.unchanged('pending')

    def test_read_commands_rewrite_the_state_for_ever_at_slot_1000(self):
        # free_slot() hands out 1000; mend_slots() calls 1000 invalid and "repairs" it on every load.
        threads = {}
        for i in range(1, 1001):
            tid = f't{i}'
            threads[tid] = {'id': tid, 'title': tid, 'context': '', 'status': 'open', 'created': self.T0 + i, 'updated': self.T0 + i,
                            'next': 1, 'messages': [], 'slot': i if i < 1000 else None, 'state': 'working', 'note': 'x', 'auto': False}
        self.write_state({'version': 2, 'threads': threads})
        self.ok('list', env=self.at(1))                              # the thousandth thread gets its slot
        self.assertEqual(len(set(self.slots().values())), 1000)
        self.unchanged('list', env=self.at(1))
        self.unchanged('pending', env=self.at(1))


# ═══ 2. nothing that waits on someone is archived ═══════════════════════════

class Archive(Base):
    def test_held_waiting_threads_survive_every_command_for_years(self):
        e = self.at
        self.ok('new', 'auto', 'T', env=e(0))
        self.ok('new', 'explicit', 'T', '--note', 'להחליט', env=e(0))
        self.ok('new', 'asked', 'T', env=e(0))
        self.ok('ask', 'asked', 'A או B?', '--options', 'A,B', env=e(0))
        self.ok('new', 'working', 'T', '--state', 'working', env=e(0))
        self.ok('new', 'replied', 'T', env=e(0))
        self.ok('say', 'replied', '--from', 'owner', 'תעשה', env=e(0))
        self.ok('new', 'done-pending', 'T', env=e(0))
        self.ok('say', 'done-pending', '--from', 'owner', 'תעשה', env=e(0))
        self.ok('resolve', 'done-pending', env=e(0))
        self.ok('new', 'bait', 'T', '--state', 'done', env=e(0))
        self.ok('policy', '--idle-hours', '0', '--grace-hours', '0', '--resolved-hours', '0', env=e(0))
        for i, args in enumerate((('list',), ('list', '--json'), ('pending',), ('show', 'auto'), ('policy',), ('sweep',),
                                  ('new', 'x', 'T'), ('say', 'x', '--from', 'tower', 'hi'), ('close', 'x'), ('link', 'auto', 'a', '/x'))):
            self.ok(*args, env=e(10 ** (i % 6)))
        self.post_ok({'op': 'sweep'}, env=e(99999))
        status = {t['id']: (t['status'], t.get('closed_by')) for t in self.data()['threads'].values()}
        for tid in ('auto', 'explicit', 'asked', 'working', 'replied', 'done-pending'):
            self.assertEqual(status[tid], ('open', None), tid)
        self.assertEqual(status['bait'], ('closed', 'auto'))

    def test_held_archive_deadline_is_exact(self):
        e = self.at
        self.ok('new', 'topic', 'T', '--state', 'done', env=e(0))
        self.unchanged('list', env=dict(self.env, THREADS_NOW=repr(self.T0 + 24 * H - 0.001)))
        self.assertEqual(self.t()['status'], 'open')
        self.ok('list', env=e(24))
        self.assertEqual((self.t()['status'], self.t()['closed_ts']), ('closed', self.T0 + 24 * H))

    def test_held_command_on_a_due_thread_wins_over_the_deadline(self):
        e = self.at
        for tid in ('s', 'k', 'r', 'y'):
            self.ok('new', tid, 'T', '--state', 'done', env=e(0))
        self.ok('say', 's', '--from', 'fork', 'עוד', '--state', 'done', env=e(30))
        self.assertEqual(self.t('s')['status'], 'open')
        for tid in ('k', 'r', 'y'):
            self.ok('reopen', tid, env=e(31))                          # the say above archived them
        self.ok('policy', '--idle-hours', '1', '--grace-hours', '1', env=e(31))
        self.post_ok({'op': 'keep', 'thread': 'k'}, env=e(40))
        self.assertEqual((self.t('k')['status'], self.t('k')['archive_at']), ('open', self.T0 + 42 * H))
        self.ok('reopen', 'r', env=e(40))
        self.ok('reopen', 'y', env=e(40))
        self.post_ok({'op': 'reply', 'thread': 'y', 'text': 'רגע', 'cid': 'c'}, env=e(45))
        self.assertEqual((self.t('y')['status'], self.t('y')['state']), ('open', 'working'))

    def test_held_clock_going_backwards_archives_nothing(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(100))
        self.ok('say', 'topic', '--from', 'fork', 'סיכום', '--state', 'done', env=e(100))
        for hours in (-50000, 0, 99, 100):
            self.unchanged('list', env=e(hours))
        self.ok('new', 'early', 'T', '--state', 'done', env=e(-10))
        self.assertEqual(self.slots(), {'topic': 1, 'early': 2})
        self.ok('close', 'topic', env=e(101))
        self.ok('new', 'past', 'T', env=e(-10))                        # "now" is before the close: the slot still rests
        self.assertEqual(self.slots()['past'], 3)
        self.ok('reopen', 'topic', env=e(-20))
        t = self.t()
        self.assertEqual((t['status'], t['slot'], t['archive_at']), ('open', 1, self.T0 + 124 * H))

    def test_held_policy_bounds(self):
        self.ok('new', 'topic', 'T', '--state', 'done', env=self.at(0))
        for flag in ('--idle-hours', '--grace-hours', '--resolved-hours', '--slot-cooldown-hours'):
            for bad in ('-1', '-0.0001', 'nan', 'inf', '-inf', '100000.01', '1e99', 'x', '', '1,5'):
                with self.subTest(flag=flag, bad=bad):
                    self.refused('policy', f'{flag}={bad}', env=self.at(0))
        self.ok('policy', '--idle-hours', '0.5', '--grace-hours', '0.25', '--resolved-hours', '100000', '--slot-cooldown-hours', '0', env=self.at(0))
        self.assertEqual(self.t()['archive_at'], self.T0 + 0.75 * H)
        self.assertEqual(json.loads(self.unchanged('policy', env=self.at(0)).stdout),
                         {'idle_hours': 0.5, 'grace_hours': 0.25, 'resolved_hours': 100000.0, 'slot_cooldown_hours': 0.0, 'task_archive_hours': 12.0})
        self.ok('resolve', 'topic', env=self.at(0.1))
        self.unchanged('list', env=self.at(99999))                      # resolved clock: 100000 hours
        self.ok('close', 'topic', env=self.at(1))
        self.ok('new', 'next', 'T', env=self.at(1))
        self.assertEqual(self.slots()['next'], 1)                       # cooldown 0: free at once

    def test_ack_on_a_done_thread_gets_it_archived_at_once(self):
        # His reply and an agent's `resolve` cross. While the reply is pending nothing archives.
        # The moment an agent picks it up (ack) the old clock applies: the thread is archived
        # under the agent's hands, and the answer it then writes lands in a closed thread.
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('say', 'topic', '--from', 'fork', 'מוכן למיזוג', env=e(0))
        self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'לפני המיזוג תוסיף בדיקה', 'cid': 'c1'}, env=e(1))
        self.ok('resolve', 'topic', '--note', 'מוזג', env=e(1.01))             # the agent had not seen the reply
        self.unchanged('list', env=e(40))                                        # pending reply: no clock
        row = json.loads(self.ok('pending', env=e(40)).stdout)[0]
        self.ok('ack', row['thread'], row['msg_id'], env=e(40))                  # an agent starts on his request
        self.ok('pending', env=e(40.01))                                         # 36 seconds later, any command
        t = self.t()
        self.assertEqual((t['status'], t.get('closed_by')), ('open', None), 'archived 36 s after an agent acked his request')

    def test_ack_does_not_restart_the_archive_clock(self):
        # The same hole without the crossing: `state done` over his pending reply (the "asked" thread of the shipped test).
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('say', 'topic', '--from', 'owner', 'תעשה גם את זה', env=e(0))
        self.ok('state', 'topic', 'done', '--note', 'נגמר', env=e(0))
        self.ok('ack', 'topic', 'm1', env=e(30))
        t = self.t()
        self.assertTrue(t['archive_at'] is None or t['archive_at'] > self.T0 + 30 * H,
                        f"acked at hour 30, archive deadline is {t['archive_at']} (T0 = {self.T0})")

    def test_agent_message_into_a_self_archived_thread_stays_buried(self):
        # v1 let `say` write into a closed thread with a warning; there, a human had closed it.
        # Now threads close themselves (2 hours after `resolve`), and what an agent writes afterwards
        # lands where nobody looks: exit 0, the thread stays archived, even an explicit "on you" is dropped.
        e = self.at
        cases = {'plain': (), 'explicit': ('--state', 'on-owner', '--note', 'צריך החלטה: לבטל את הפריסה?')}
        for tid, extra in cases.items():
            with self.subTest(say=tid):
                self.ok('new', tid, 'T', env=e(0))
                self.ok('say', tid, '--from', 'fork', 'מוזג', env=e(0))
                self.ok('resolve', tid, '--note', 'מוזג', env=e(0))
                self.ok('list', env=e(3))
                self.assertEqual(self.t(tid)['closed_by'], 'auto')
                r = self.cli('say', tid, '--from', 'fork', 'הפריסה של המיזוג נכשלה \u2014 צריך החלטה', *extra, env=e(26))
                t = self.t(tid)
                visible = t['status'] == 'open' and t['state'] == 'on-owner'
                self.assertTrue(r.returncode != 0 or visible,
                                f"exit {r.returncode}, thread {t['status']}/{t['state']} (closed_by={t.get('closed_by')}), note {t['note']!r}: invisible to him")


# ═══ 3 + 4. refused commands and reads write nothing ════════════════════════

class Writes(Base):
    def scene(self, e):
        self.ok('new', 'topic', 'כותרת', '--context', 'רקע', env=e(0))
        self.ok('say', 'topic', '--from', 'tower', 'intro', env=e(0))
        self.ok('say', 'topic', '--from', 'owner', 'reply', env=e(0))
        self.ok('new', 'shut', 'סגור', env=e(0))
        self.ok('ask', 'shut', 'A?', env=e(0))
        self.ok('close', 'shut', env=e(0))
        self.ok('new', 'due', 'T', '--state', 'done', env=e(0))          # past its deadline in every command below

    def test_held_refused_commands_change_nothing(self):
        e = self.at
        self.scene(e)
        long = 'x' * 201
        cases = [
            ('new', 'topic', 'dup'), ('new', 'Bad', 'x'), ('new', '', 'x'), ('new', 'a/b', 'x'), ('new', '../x', 'x'), ('new', 'a' * 49, 'x'),
            ('new', 'n1', 'x', '--state', 'on-owner'), ('new', 'n1', 'x', '--note', '   '), ('new', 'n1', 'x', '--note', long),
            ('new', 'n1', 'x', '--state', 'nope'), ('new', 'n1', 'x', '--link', 'nolabel'), ('new', 'n1', 'x', '--link', '=https://x'),
            ('new', 'n1', 'x', '--link', 'a=javascript:alert(1)'), ('new', 'n1', 'x', '--link', 'a='),
            ('new', 'n1', 'x') + tuple(arg for i in range(9) for arg in ('--link', f'l{i}=/x')),
            ('show', 'ghost'), ('say', 'ghost', '--from', 'tower', 'x'), ('say', 'topic', '--from', 'tower', ''), ('say', 'topic', '--from', 'tower', ' \n\t'),
            ('say', 'topic', '--from', 'nobody', 'x'), ('say', 'topic', 'x'), ('say', 'topic', '--from', 'owner', 'x', '--state', 'done'),
            ('say', 'topic', '--from', 'owner', 'x', '--note', 'n'), ('say', 'topic', '--from', 'owner', 'x', '--by', 'b'),
            ('say', 'topic', '--from', 'fork', 'x', '--note', 'n'), ('say', 'topic', '--from', 'fork', 'x', '--by', 'b'),
            ('say', 'topic', '--from', 'fork', 'x', '--state', 'on-owner'), ('say', 'topic', '--from', 'fork', 'x', '--state', 'on-owner', '--note', ' '),
            ('say', 'topic', '--from', 'fork', 'x', '--state', 'working', '--note', long), ('say', 'topic', '--from', 'fork', 'x', '--state', 'maybe'),
            ('state', 'topic', 'on-owner'), ('state', 'topic', 'on-owner', '--note', '\n'), ('state', 'topic', 'done', '--note', long),
            ('state', 'ghost', 'done'), ('state', 'shut', 'done'), ('state', 'topic', 'DONE'), ('state', 'topic'),
            ('ask', 'ghost', 'x?'), ('ask', 'shut', 'x?'), ('ask', 'topic', ''), ('ask', 'topic', ' \n '), ('ask', 'topic', 'x' * 2001),
            ('ask', 'topic', 'x?', '--options', ''), ('ask', 'topic', 'x?', '--options', 'a'), ('ask', 'topic', 'x?', '--options', 'a,a, a ,'),
            ('ask', 'topic', 'x?', '--options', 'a,b,c,d,e,f,g'), ('ask', 'topic', 'x?', '--options', 'a,' + 'b' * 41), ('ask', 'topic', 'x?', '--options', ',,,'),
            ('ask', 'topic', 'x?', '--from', 'owner'), ('resolve', 'ghost'), ('resolve', 'shut'), ('resolve', 'topic', '--note', long),
            ('set', 'topic'), ('set', 'ghost', '--title', 'x'), ('set', 'topic', '--title', ''), ('set', 'topic', '--title', '  \n'),
            ('link', 'topic', 'l'), ('link', 'topic', '', '/x'), ('link', 'topic', ' ', '/x'), ('link', 'topic', 'x' * 41, '/x'), ('link', 'topic', 'l', ''),
            ('link', 'topic', 'l', ' '), ('link', 'topic', 'l', 'x' * 501), ('link', 'topic', 'l', 'a\nb'), ('link', 'topic', 'l', 'a\tb'), ('link', 'topic', 'l', 'a\rb'),
            ('link', 'topic', 'l', 'javascript:alert(1)'), ('link', 'topic', 'l', 'JAVASCRIPT:alert(1)'), ('link', 'topic', 'l', ' javascript:alert(1)'),
            ('link', 'topic', 'l', '\tjavascript:alert(1)'), ('link', 'topic', 'l', 'java\tscript:alert(1)'), ('link', 'topic', 'l', 'data:text/html,x'),
            ('link', 'topic', 'l', 'vbscript:x'), ('link', 'topic', 'l', 'file:///etc/passwd'), ('link', 'topic', 'l', 'ftp://x/y'), ('link', 'topic', 'l', '//evil.example/x'),
            ('link', 'topic', 'l', 'blob:https://x/y'), ('link', 'topic', 'l', 'mailto:a@b'), ('link', 'topic', 'l', 'https:evil.example'), ('link', 'topic', 'l', 'http:/evil.example'),
            ('link', 'topic', 'l', 'https:\\\\evil.example'), ('link', 'topic', 'l', 'x-custom+a.b:foo'), ('link', 'topic', 'nolink', '--rm'), ('link', 'ghost', 'l', '/x'),
            ('close', 'ghost'), ('reopen', 'ghost'), ('rm', 'topic'), ('rm', 'ghost', '--yes'), ('ack', 'topic', 'm1'), ('ack', 'topic', 'm9'),
            ('ack', 'topic', ''), ('ack', 'ghost', 'm1'), ('ack', 'topic'), ('policy', '--idle-hours', '-1'), ('nonsense',), (),
        ]
        for args in cases:
            for hours in (1, 5000):                                  # also when a sweep is due inside the command
                with self.subTest(args=str(args)[:90], hours=hours):
                    self.refused(*args, env=e(hours))
        self.refused('say', 'topic', '--from', 'fork', '-', input='', env=e(1))
        self.refused('say', 'topic', '--from', 'fork', '-', input=' \n', env=e(1))
        self.assertEqual(self.t('due')['status'], 'open')            # no refused command archived it on the way

    def test_held_refused_commands_do_not_migrate_a_v1_file(self):
        v1 = {'version': 1, 'threads': {'a': {'id': 'a', 'title': 'A', 'context': '', 'status': 'open', 'created': 1.0, 'updated': 1.0, 'next': 1, 'messages': []}}}
        self.write_state(v1)
        for args in (('show', 'ghost'), ('new', 'a', 'dup'), ('ack', 'a', 'm1'), ('state', 'a', 'on-owner'), ('rm', 'ghost', '--yes')):
            with self.subTest(args=args):
                self.refused(*args)
        self.post_refused({'op': 'close', 'thread': 'ghost'})
        self.assertEqual(list(self.board.glob('state.json.bak*')), [])

    def test_held_reads_write_nothing(self):
        e = self.at
        self.scene(e)
        for args in (('list',), ('list', '--open'), ('list', '--json'), ('list', '--open', '--json'), ('show', 'topic'), ('show', 'topic', '--json'),
                     ('show', 'shut'), ('pending',), ('policy',), ('sweep',)):
            with self.subTest(args=args):
                self.unchanged(*args, env=e(23.9))
        # an already-acked ack is a no-op too
        self.ok('ack', 'topic', 'm2', env=e(23.9))
        self.unchanged('ack', 'topic', 'm2', env=e(23.95))
        # reads on a board that does not exist yet create no state
        fresh = dict(self.env, BOARDS_DIR=str(self.root / 'boards2'))
        for args in (('list',), ('pending',), ('policy',), ('sweep',)):
            self.ok(*args, env=fresh)
        self.assertFalse((self.root / 'boards2/threads/state.json').exists())
        self.assertFalse((self.root / 'boards2/threads/.pulse').exists())

    def test_held_no_command_rewrites_an_existing_message(self):
        e = self.at
        self.scene(e)
        self.post_ok({'op': 'reply', 'thread': 'topic', 'text': 'עוד', 'cid': 'c1'}, env=e(1))
        frozen = {tid: [dict(m) for m in t['messages']] for tid, t in self.data()['threads'].items()}
        steps = [('say', 'topic', '--from', 'fork', 'x'), ('state', 'topic', 'working', '--note', 'n'), ('ask', 'topic', 'q?', '--options', 'a,b'),
                 ('resolve', 'topic'), ('set', 'topic', '--title', 't2', '--summary', 's', '--context', 'c'), ('link', 'topic', 'l', '/x'),
                 ('link', 'topic', 'l', '--rm'), ('close', 'topic'), ('say', 'topic', '--from', 'owner', 'into closed'), ('reopen', 'topic'),
                 ('reopen', 'shut'), ('say', 'shut', '--from', 'tower', 'y'), ('policy', '--idle-hours', '3'), ('sweep',), ('list',), ('pending',),
                 ('new', 'fresh', 'T'), ('close', 'due'), ('reopen', 'due')]
        for i, args in enumerate(steps):
            self.ok(*args, env=e(2 + i))
            for op in ('keep', 'close', 'reopen', 'done', 'sweep'):
                self.put_request({'op': op, 'thread': 'topic'})
                self.cli('ingest', env=e(2 + i + 0.5))
            now = self.data()['threads']
            for tid, old in frozen.items():
                self.assertEqual(now[tid]['messages'][:len(old)], old, f'{args}: history of {tid} changed')
        # ack touches only the status of the acked message
        before = self.t()['messages']
        self.ok('ack', 'topic', 'm2', env=e(100))
        after = self.t()['messages']
        for old, new in zip(before, after):
            if old['id'] == 'm2':
                self.assertEqual({k: v for k, v in new.items() if k not in ('status', 'acked_ts')}, {k: v for k, v in old.items() if k != 'status'})
                self.assertEqual((new['status'], new['acked_ts']), ('acked', self.T0 + 100 * H))
            else:
                self.assertEqual(new, old)

    def test_held_lock_held_by_someone_else_is_a_clean_refusal(self):
        import fcntl
        self.ok('new', 'topic', 'T')
        env = dict(self.env, BOARD_LOCK_TIMEOUT='0.2')
        with open(self.board / '.state.json.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for args in (('list',), ('pending',), ('say', 'topic', '--from', 'fork', 'x'), ('new', 'z', 'Z'), ('close', 'topic'), ('sweep',)):
                with self.subTest(args=args):
                    self.refused(*args, env=env)
            self.post_refused({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c'}, env=env, again=True)
            self.post_refused({'op': 'sweep'}, env=env, again=True)
        self.ok('say', 'topic', '--from', 'fork', 'x', env=env)

    def test_held_stdin_that_is_not_utf8_is_refused(self):
        self.ok('new', 'topic', 'T')
        before = self.snapshot()
        r = subprocess.run([sys.executable, str(CLI), 'say', 'topic', '--from', 'fork', '-'], env=self.env, input=b'caf\xe9 \xff', capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(b'Traceback', r.stderr)
        self.assertEqual((r.stdout, self.snapshot()), (b'', before))

    def test_install_refused_by_a_newer_state_has_already_replaced_the_page_and_hook(self):
        # install() copies suda.html, puts the redirect in place of an old board.html and rewrites on-state.sh:
        # all of it only AFTER it read state.json, so a newer state stops it before anything is replaced.
        self.board.mkdir(parents=True)
        self.state.write_text('{"version": 4, "threads": {}}')
        (self.board / 'suda.html').write_text('<!-- the page of the newer version -->')
        (self.board / 'board.html').write_text('<!-- the old board page -->')
        (self.board / 'on-state.sh').write_text('#!/bin/sh\nexec newer-threads ingest\n')
        self.refused('install')

    def test_slow_reader_of_a_read_command_blocks_the_page(self):
        # "Read stdin before taking the lock: a slow pipe must not block the page", but list / show / pending
        # PRINT inside the lock. A pager nobody scrolls (`threads show x | less`) holds it. (v1 did the same.)
        self.ok('new', 'topic', 'T')
        for _ in range(8):                                              # 350 KB in all; one message is capped at 50 000 characters
            self.ok('say', 'topic', '--from', 'fork', '-', input='שורה ארוכה ' * 4_000)
        reader = subprocess.Popen([sys.executable, str(CLI), 'show', 'topic', '--json'], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            time.sleep(1.5)                                             # the reader now waits on a full pipe
            self.assertIsNone(reader.poll(), 'the reader finished: the scenario did not happen')
            out = self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c1'}, env=dict(self.env, BOARD_LOCK_TIMEOUT='2'))
            self.assertTrue(out['ok'], f'his reply was refused while someone only reads: {out}')
        finally:
            reader.stdout.read()
            reader.wait(timeout=10)
            reader.stdout.close()
            reader.stderr.close()

    def test_say_prints_a_message_id_for_a_message_it_did_not_store(self):
        # argv bytes that are not UTF-8 arrive as lone surrogates; the save refuses them after the id was printed.
        self.ok('new', 'topic', 'T')
        before = self.snapshot()
        r = subprocess.run([os.fsencode(sys.executable), os.fsencode(str(CLI)), b'say', b'topic', b'--from', b'fork', b'caf\xe9'],
                           env=self.env, capture_output=True)
        self.assertNotIn(b'Traceback', r.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), b'', 'a refused say printed a message id')


# ═══ 7. whose turn ══════════════════════════════════════════════════════════

class Turn(Base):
    def test_held_agent_message_without_state_hands_the_turn_to_owner(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        for i, setup in enumerate((('state', 'topic', 'working', '--note', 'בונה'), ('state', 'topic', 'done'), ('resolve', 'topic'),
                                   ('say', 'topic', '--from', 'owner', 'תעשה'), ('say', 'topic', '--from', 'fork', 'x', '--state', 'working'),
                                   ('say', 'topic', '--from', 'tower', 'x', '--state', 'done', '--note', 'נגמר'))):
            for sender in ('tower', 'fork'):
                with self.subTest(setup=setup, sender=sender):
                    self.ok(*setup, env=e(1 + i))
                    self.assertIn(self.t()['state'], ('working', 'done'))
                    self.ok('say', 'topic', '--from', sender, '**עדכון**\nשורה `שנייה`', env=e(1.5 + i))
                    t = self.t()
                    self.assertEqual((t['state'], t['auto'], t['note'], t['archive_at']), ('on-owner', True, 'לקרוא: עדכון שורה שנייה', None))
                    self.assert_note_rule(t)

    def test_held_explicit_ask_survives_plain_messages_and_everything_passive(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('say', 'topic', '--from', 'owner', 'קודם', env=e(0))
        self.ok('state', 'topic', 'on-owner', '--note', 'להחליט A או B', '--by', 'lead', env=e(1))
        passive = [('say', 'topic', '--from', 'tower', 'תזכורת'), ('say', 'topic', '--from', 'fork', 'עוד'), ('ack', 'topic', 'm1'),
                   ('link', 'topic', 'l', '/x'), ('set', 'topic', '--summary', 's'), ('close', 'topic'), ('reopen', 'topic'), ('list',), ('sweep',)]
        for i, args in enumerate(passive):
            self.ok(*args, env=e(2 + i))
            if self.t()['status'] == 'open':
                self.post_ok({'op': 'keep', 'thread': 'topic'}, env=e(2.5 + i))
            t = self.t()
            self.assertEqual((t['state'], t['note'], t['auto'], t['state_by']), ('on-owner', 'להחליט A או B', False, 'lead'), args)
        self.post_refused({'op': 'done', 'thread': 'topic'}, env=e(50))

    def test_held_owner_reply_moves_to_working_and_clears_the_question(self):
        e = self.at
        for via in ('page', 'cli'):
            for setup in (('ask', 'topic', 'A או B?', '--options', 'A,B'), ('state', 'topic', 'done'), ('resolve', 'topic'),
                          ('state', 'topic', 'on-owner', '--note', 'להחליט'), ('state', 'topic', 'working', '--note', 'בונה', '--by', 'lead')):
                with self.subTest(via=via, setup=setup):
                    tid = 'topic'
                    if self.state.exists() and tid in self.data()['threads']:
                        self.ok('rm', tid, '--yes', env=e(0))
                    self.ok('new', tid, 'T', env=e(0))
                    self.ok(*setup, env=e(1))
                    if via == 'page':
                        under = (self.t()['question'] or {}).get('id')      # a typed reply names the question on his screen
                        self.post_ok({'op': 'reply', 'thread': tid, 'text': 'תשובה **ארוכה**\n' + 'מאוד ' * 40, 'cid': 'c', 'under': under}, env=e(2))
                    else:
                        self.ok('say', tid, '--from', 'owner', 'תשובה **ארוכה**\n' + 'מאוד ' * 40, env=e(2))
                    t = self.t()
                    self.assertEqual((t['state'], t['auto'], t['question'], t['resolved'], t['state_by'], t['archive_at']),
                                     ('working', True, None, False, 'tower', None))
                    self.assertTrue(t['note'].startswith('ענית: «תשובה ארוכה מאוד'))
                    self.assertLessEqual(len(t['note']), 200)
                    self.assertEqual('re' in t['messages'][-1], setup[0] == 'ask')

    def test_held_on_owner_note_rule_on_the_normal_paths(self):
        e = self.at
        long = 'מילה ' * 500
        self.ok('new', 'a', 'T', env=e(0))
        self.ok('new', 'b', 'T', '--note', ' לבחור \n\t תאריך ', env=e(0))
        self.ok('new', 'c', 'T', '--state', 'on-owner', '--note', 'x' * 200, env=e(0))
        self.ok('new', 'd', 'T', '--by', 'lead', env=e(0))
        self.ok('new', 'e', 'T', env=e(0))
        self.ok('say', 'e', '--from', 'fork', long, env=e(1))
        self.ok('new', 'f', 'T', env=e(0))
        self.ok('ask', 'f', long.strip()[:2000], env=e(1))
        self.ok('new', 'g', 'T', env=e(0))
        self.ok('say', 'g', '--from', 'fork', 'x', '--state', 'on-owner', '--note', 'שורה\r\nשנייה\x0b\x0c\x1c\x85\u2028\u2029סוף', env=e(1))
        self.ok('new', 'h', 'T', env=e(0))
        self.ok('say', 'h', '--from', 'fork', '```\n**`', env=e(1))                 # nothing left after the markdown marks
        self.ok('new', 'i', 'T', env=e(0))
        self.ok('ask', 'i', 'שאלה\nבשתי שורות?', '--options', 'כן,לא', env=e(1))
        for t in self.data()['threads'].values():
            with self.subTest(tid=t['id']):
                self.assertEqual(t['state'], 'on-owner')
                self.assert_note_rule(t)
        self.assertEqual(self.t('g')['note'], 'שורה שנייה סוף')

    def test_ask_with_only_markdown_marks_stores_an_empty_note(self):
        # preview() strips ** ` and ```: nothing is left, and `ask` never calls clean_note().
        e = self.at
        for i, question in enumerate(('**', '`', '```', '****', '```python', '** `` **')):
            with self.subTest(question=question):
                tid = f'q{i}'
                self.ok('new', tid, 'T', env=e(0))
                r = self.cli('ask', tid, question, env=e(1))
                t = self.t(tid)
                if r.returncode == 0:
                    self.assertEqual(t['state'], 'on-owner')
                    self.assert_note_rule(t)

    def test_invisible_characters_count_as_a_note(self):
        # str.split() does not treat zero-width or C0 control characters as blank.
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        for note in ('\u200b', '\u200e\u200f', '\ufeff', '\u2060', '\x01', '\x1b', '\u00ad'):
            with self.subTest(note=repr(note)):
                self.refused('state', 'topic', 'on-owner', '--note', note, env=e(1))
                self.refused('new', 'n', 'T', '--note', note, env=e(1))

    def test_record_without_state_becomes_on_owner_with_an_empty_note(self):
        # fill() defaults: state on-owner, note ''. An older CLI's `new` on a v2 file, or a hand edit, lands here.
        self.ok('new', 'topic', 'T')
        data = self.data()
        data['threads']['old'] = {'id': 'old', 'title': 'מה-CLI הישן', 'context': '', 'status': 'open', 'created': self.T0, 'updated': self.T0,
                                  'next': 2, 'messages': [{'id': 'm1', 'from': 'fork', 'text': 'דוח', 'ts': self.T0}]}
        self.write_state(data)
        self.ok('say', 'topic', '--from', 'tower', 'x')                   # any write persists the defaults
        t = self.t('old')
        self.assertEqual(t['state'], 'on-owner')
        self.assert_note_rule(t)

    def test_say_with_state_on_a_closed_thread_drops_the_state_silently(self):
        e = self.at
        self.ok('new', 'topic', 'T', '--state', 'working', '--note', 'בונה', env=e(0))
        self.ok('close', 'topic', env=e(1))
        r = self.cli('say', 'topic', '--from', 'fork', 'סיימתי', '--state', 'done', '--note', 'נגמר', env=e(2))
        t = self.t()
        self.assertTrue(r.returncode != 0 or (t['state'], t['note']) == ('done', 'נגמר'),
                        f"exit 0 but the thread still says {t['state']!r} / {t['note']!r}")

    def test_agent_message_into_a_closed_working_thread_leaves_it_working(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('say', 'topic', '--from', 'owner', 'תעשה', env=e(0))
        self.ok('close', 'topic', env=e(1))
        self.ok('say', 'topic', '--from', 'fork', 'עשיתי, תסתכל', env=e(2))    # plain: no --state
        self.ok('reopen', 'topic', env=e(3))
        t = self.t()
        self.assertNotIn(t['state'], ('working', 'done'), f"the agent spoke last without --state, the thread says {t['state']!r}: {t['note']!r}")

    def test_owner_message_into_a_closed_thread_leaves_the_question_open(self):
        e = self.at
        self.ok('new', 'topic', 'T', env=e(0))
        self.ok('ask', 'topic', 'A או B?', '--options', 'A,B', env=e(0))
        self.ok('close', 'topic', env=e(1))
        self.ok('say', 'topic', '--from', 'owner', 'A', env=e(2))
        self.ok('reopen', 'topic', env=e(3))
        t = self.t()
        self.assertEqual((t['state'], t['question']), ('working', None), 'he answered, the thread still asks him')

    def test_close_by_can_claim_to_be_owner_or_the_archiver(self):
        # closed_by decides what the page tells him: "you closed it" / "closed by itself, no activity".
        self.ok('new', 'topic', 'T')
        for who in ('owner', 'auto'):
            with self.subTest(by=who):
                self.refused('close', 'topic', '--by', who)


# ═══ 9. damaged or old state files ══════════════════════════════════════════

class Damaged(Base):
    def good(self):
        self.ok('new', 'a', 'A', '--note', 'להחליט')
        self.ok('new', 'b', 'B', '--state', 'done')
        self.ok('new', 'c', 'C')
        self.ok('close', 'b')
        return self.data()

    def test_damaged_state_makes_the_cli_crash_with_a_traceback(self):
        base = self.good()
        damage = {
            'policy null': lambda d: d.update(policy=None),
            'policy list': lambda d: d.update(policy=[]),
            'policy string': lambda d: d.update(policy='x'),
            'policy value string': lambda d: (d['policy'].update(idle_hours='12'), d['threads']['c'].update(state='done')),
            'policy value null': lambda d: (d['policy'].update(slot_cooldown_hours=None)),
            'threads list': lambda d: d.update(threads=[]),
            'threads null': lambda d: d.update(threads=None),
            'threads string': lambda d: d.update(threads='x'),
            'thread null': lambda d: d['threads'].update(a=None),
            'thread list': lambda d: d['threads'].update(a=[]),
            'version string': lambda d: d.update(version='2'),
            'version null': lambda d: d.update(version=None),
            'version list': lambda d: d.update(version=[2]),
            'top level list': None,
            'top level string': None,
            'messages null': lambda d: d['threads']['a'].update(messages=None),
            'message null': lambda d: d['threads']['a'].update(messages=[None]),
            'state_ts string': lambda d: d['threads']['c'].update(state='done', state_ts='yesterday'),
            'question string': lambda d: d['threads']['a'].update(question='x'),
            'links null': lambda d: d['threads']['a'].update(links=None),
            'closed_ts string': lambda d: d['threads']['b'].update(closed_ts='x'),
        }
        commands = [('list',), ('list', '--json'), ('show', 'a'), ('pending',), ('policy',), ('sweep',), ('new', 'z', 'Z'),
                    ('say', 'a', '--from', 'fork', 'x'), ('ack', 'a', 'm1'), ('close', 'a'), ('reopen', 'b'), ('link', 'a', 'l', '/x')]
        bodies = [{'op': 'sweep'}, {'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'c1'}, {'op': 'close', 'thread': 'a'}]
        for name, harm in damage.items():
            data = json.loads(json.dumps(base))
            if harm:
                harm(data)
            else:
                data = [base] if 'list' in name else 'state'
            self.write_state(data)
            raw = self.state.read_bytes()
            crashes, wrote, silent = {}, [], []
            for args in commands + [('ingest', body) for body in bodies]:
                self.state.write_bytes(raw)
                if args[0] == 'ingest':
                    self.put_request(args[1])
                    r = self.cli('ingest')
                    label = 'ingest ' + args[1]['op']
                    if len(r.stdout.strip().splitlines()) != 1:
                        silent.append(label)
                else:
                    r = self.cli(*args)
                    label = ' '.join(args[:1])
                if 'Traceback' in r.stderr:
                    crashes.setdefault(r.stderr.strip().splitlines()[-1], []).append(label)
                if r.returncode != 0 and self.state.read_bytes() != raw:
                    wrote.append(label)
            with self.subTest(damage=name):
                self.assertEqual(wrote, [], 'a failed command rewrote the damaged file')
                self.assertEqual(crashes, {}, 'uncaught exception (traceback)')
                self.assertEqual(silent, [], 'ingest did not answer with one JSON line')

    def test_held_unreadable_state_is_refused_and_never_overwritten(self):
        self.good()
        for raw in (b'', b'{', b'not json', b'\xff\xfe', b'{"version": 4, "threads": {}}', b'{"version": 2.5, "threads": {}}',
                    b'{"version": 99999999999999999999, "threads": {}}', b'{}', b'{"version": 2}'):
            with self.subTest(raw=raw[:40]):
                self.state.write_bytes(raw)
                for args in (('list',), ('pending',), ('new', 'z', 'Z'), ('say', 'a', '--from', 'fork', 'x'), ('sweep',), ('rm', 'a', '--yes'),
                             ('policy', '--idle-hours', '1'), ('install',)):
                    r = self.cli(*args)
                    self.assertNotEqual(r.returncode, 0, args)
                    self.assertNotIn('Traceback', r.stderr)
                    self.assertEqual(self.state.read_bytes(), raw, args)
                self.put_request({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'c1'})
                r = self.cli('ingest')
                self.assertIs(json.loads(r.stdout)['ok'], False)
                self.assertEqual((r.stderr, self.state.read_bytes()), ('', raw))

    def test_held_missing_policy_and_unknown_keys_are_kept(self):
        data = self.good()
        del data['policy']
        data['extra'] = {'keep': 'me'}
        data['threads']['a']['custom'] = [1, 2]
        self.write_state(data)
        self.unchanged('list')
        self.ok('say', 'a', '--from', 'fork', 'x')
        after = self.data()
        self.assertEqual((after['extra'], after['threads']['a']['custom']), ({'keep': 'me'}, [1, 2]))
        self.assertEqual(after['policy'], {'idle_hours': 12.0, 'grace_hours': 12.0, 'resolved_hours': 2.0, 'slot_cooldown_hours': 6.0, 'task_archive_hours': 12.0})

    def test_low_version_number_runs_the_v1_migration_over_v2_data(self):
        # Only `version > 2` is refused. 0, -1, 1.5, true or a stray 1 re-derive every slot and state.
        e = self.at
        for tid in 'abc':
            self.ok('new', tid, 'T', env=e(0))
        self.ok('close', 'b', env=e(1))
        self.ok('state', 'a', 'on-owner', '--note', 'להחליט A או B', env=e(1))
        self.ok('state', 'c', 'done', '--note', 'נגמר', env=e(1))
        good = self.data()
        for version in (0, -1, 1.5, True, 1):
            with self.subTest(version=version):
                self.write_state(dict(good, version=version))
                r = self.cli('list', env=e(2))
                after = self.data()['threads']
                if r.returncode == 0:
                    self.assertEqual({k: (after[k]['slot'], after[k]['state'], after[k]['note']) for k in 'ac'},
                                     {k: (good['threads'][k]['slot'], good['threads'][k]['state'], good['threads'][k]['note']) for k in 'ac'})


# ═══ migration of the real v1 file ══════════════════════════════════════════

class Migration(Base):
    def test_held_migration_of_a_copy_of_the_live_v1_file(self):
        if not LIVE_V1.exists():
            self.skipTest('no live-v1-state.json in the worktree')
        raw = LIVE_V1.read_bytes()
        v1 = json.loads(raw)
        self.assertEqual(v1.get('version', 1), 1)
        self.board.mkdir(parents=True)
        self.state.write_bytes(raw)
        newest = max([t['updated'] for t in v1['threads'].values()] + [m['ts'] for t in v1['threads'].values() for m in t['messages']])
        env = dict(self.env, THREADS_NOW=repr(newest + 60))
        expected_pending = sorted(((t['id'], m['id']) for t in v1['threads'].values() for m in t['messages']
                                   if m['from'] == 'owner' and m.get('status') == 'pending'))
        pending = json.loads(self.ok('pending', env=env).stdout)
        self.assertEqual(sorted((r['thread'], r['msg_id']) for r in pending), expected_pending)
        backups = list((self.board.parent.parent / '.threads-config' / self.board.name / 'backups').glob('state.json.v1-*'))      # private, never beside the served state
        self.assertEqual([b.read_bytes() for b in backups], [raw])
        v2 = self.data()
        self.assertEqual((v2['version'], set(v2['threads'])), (3, set(v1['threads'])))
        opened = [t for t in v2['threads'].values() if t['status'] == 'open']
        self.assertEqual(sorted(t['slot'] for t in opened), list(range(1, len(opened) + 1)))
        by_age = sorted(opened, key=lambda t: (t['created'], t['id']))
        self.assertEqual([t['slot'] for t in by_age], list(range(1, len(opened) + 1)))
        for tid, old in v1['threads'].items():
            new = v2['threads'][tid]
            with self.subTest(tid=tid):
                for key, value in old.items():
                    self.assertEqual(new[key], value, key)                       # nothing of v1 was rewritten
                self.assertIn(new['state'], ('on-owner', 'working', 'done'))
                self.assertEqual(new['state'] == 'done', old['status'] != 'open')
                self.assertEqual((new['archive_at'], new['soon_at'], new['question']), (None, None, None))
                self.assert_note_rule(new)
                self.assertLessEqual(len(new['note']), 200)
                self.assertEqual(new['note'], ' '.join(new['note'].split()))
                waits = any(m['from'] == 'owner' and m.get('status') == 'pending' for m in old['messages']) or \
                    (old['messages'] and old['messages'][-1]['from'] == 'owner')
                if old['status'] == 'open':
                    self.assertEqual(new['state'], 'working' if waits else 'on-owner')
        # a second run migrates nothing, backs up nothing, and years later nothing was archived
        self.unchanged('list', env=env)
        far = dict(self.env, THREADS_NOW=repr(newest + 50000 * H))
        self.unchanged('list', env=far)
        self.unchanged('sweep', env=far)
        self.assertEqual(len(list((self.board.parent.parent / '.threads-config' / self.board.name / 'backups').glob('state.json.v1-*'))), 1)
        self.assertEqual({t['id'] for t in self.data()['threads'].values() if t['status'] == 'open'}, {t['id'] for t in v1['threads'].values() if t['status'] == 'open'})

    def test_held_migration_edge_shapes(self):
        m = lambda i, who, ts, **kw: dict({'id': f'm{i}', 'from': who, 'text': f'**טקסט** {i}\nשורה', 'ts': ts}, **kw)
        T = lambda tid, created, status, msgs: {'id': tid, 'title': tid, 'context': '', 'status': status, 'created': created,
                                                'updated': created, 'next': len(msgs) + 1, 'messages': msgs}
        v1 = {'threads': {                                             # no "version" key at all
            'empty': T('empty', 5.0, 'open', []),
            'same-age-b': T('same-age-b', 7.0, 'open', [m(1, 'tower', 8.0)]),
            'same-age-a': T('same-age-a', 7.0, 'open', [m(1, 'owner', 8.0, status='acked', acked_ts=9.0)]),
            'two-pending': T('two-pending', 1.0, 'open', [m(1, 'owner', 2.0, status='pending'), m(2, 'fork', 3.0), m(3, 'owner', 4.0, status='pending'), m(4, 'fork', 5.0)]),
            'closed-pending': T('closed-pending', 2.0, 'closed', [m(1, 'owner', 3.0, status='pending')]),
            'closed-empty': T('closed-empty', 3.0, 'closed', []),
            'marks-only': T('marks-only', 9.0, 'open', [dict(m(1, 'fork', 10.0), text='```\n**')]),
        }}
        self.write_state(v1)
        self.ok('list', env=self.at(0))
        d = self.data()['threads']
        self.assertEqual({k: v['slot'] for k, v in d.items()},
                         {'two-pending': 1, 'empty': 2, 'same-age-a': 3, 'same-age-b': 4, 'marks-only': 5, 'closed-pending': None, 'closed-empty': None})
        self.assertEqual({k: v['state'] for k, v in d.items()},
                         {'two-pending': 'working', 'empty': 'on-owner', 'same-age-a': 'working', 'same-age-b': 'on-owner', 'marks-only': 'on-owner',
                          'closed-pending': 'done', 'closed-empty': 'done'})
        self.assertIn('ממתין לאיסוף', d['two-pending']['note'])
        self.assertIn('סוכן עובד על זה', d['same-age-a']['note'])
        for t in d.values():
            self.assert_note_rule(t)
            self.assertIsNone(t['archive_at'])
        self.assertEqual(len(json.loads(self.ok('pending', env=self.at(0)).stdout)), 3)
        self.ok('reopen', 'closed-pending', env=self.at(1))
        self.unchanged('list', env=self.at(90000))                       # done + his pending reply: never archived
        self.assertEqual(self.t('closed-pending')['status'], 'open')


# ═══ 10. the v1 contract ════════════════════════════════════════════════════

class V1Contract(Base):
    def test_held_v1_commands_take_their_old_arguments(self):
        self.ok('new', 'topic', 'כותרת')
        self.ok('new', 'second', 'כותרת 2', '--context', 'רקע')
        self.assertEqual(self.ok('say', 'topic', '--from', 'tower', 'intro').stdout, 'm1\n')
        self.assertEqual(self.ok('say', 'topic', '--from', 'owner', 'first').stdout, 'm2\n')
        self.assertEqual(self.ok('say', 'topic', '--from', 'fork', '-', input='from stdin\n').stdout, 'm3\n')
        self.assertEqual(self.ok('say', 'topic', '--from', 'fork', '--', '-starts with a dash').stdout, 'm4\n')
        rows = json.loads(self.ok('pending').stdout)
        self.assertEqual(len(rows), 1)
        self.assertLessEqual({'thread', 'title', 'context', 'msg_id', 'text', 'ts', 'history'}, set(rows[0]))
        self.assertEqual([set(h) for h in rows[0]['history']], [{'id', 'from', 'text', 'ts'}])
        self.assertEqual((rows[0]['thread'], rows[0]['title'], rows[0]['context'], rows[0]['msg_id'], rows[0]['text']), ('topic', 'כותרת', '', 'm2', 'first'))
        self.assertEqual(self.ok('ack', 'topic', 'm2').stdout, '')
        self.assertEqual(self.ok('ack', 'topic', 'm2').stdout, '')
        self.assertEqual(json.loads(self.ok('pending').stdout), [])
        self.assertEqual(self.ok('close', 'topic').stdout, '')
        warn = self.ok('say', 'topic', '--from', 'owner', 'into closed')
        self.assertEqual((warn.stdout, bool(warn.stderr)), ('m5\n', True))
        self.assertEqual(len(json.loads(self.ok('pending').stdout)), 1)          # a reply into a closed thread still surfaces
        self.assertEqual([t['id'] for t in json.loads(self.ok('list', '--open', '--json').stdout)], ['second'])
        self.assertEqual({t['id']: t['status'] for t in json.loads(self.ok('list', '--json').stdout)}, {'second': 'open', 'topic': 'closed'})
        self.ok('reopen', 'topic')
        t = json.loads(self.ok('show', 'topic', '--json').stdout)
        for key in ('id', 'title', 'context', 'status', 'created', 'updated', 'next', 'messages'):
            self.assertIn(key, t)
        self.assertEqual((t['status'], t['next'], len(t['messages'])), ('open', 6, 5))
        self.assertNotEqual(self.cli('rm', 'topic').returncode, 0)
        self.ok('rm', 'topic', '--yes')
        self.assertEqual(self.ok('install').stdout.strip(), str(self.board))

    def test_held_old_page_reply_and_notification_text(self):
        self.ok('new', 'topic', 'כותרת')
        self.ok('ask', 'topic', 'A או B?', '--options', 'A,B')
        text = '  שלום\n\nעולם\t' + 'x' * 100
        out = self.post_ok({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': 'client-1'})
        self.assertEqual(out, {'ok': True, 'thread': 'topic', 'msg_id': 'm2', 'dup': False})
        self.assertEqual(self.post_ok({'op': 'reply', 'thread': 'topic', 'text': text, 'cid': 'client-1'}),
                         {'ok': True, 'thread': 'topic', 'msg_id': 'm2', 'dup': True})
        records = [json.loads(line) for line in self.record.read_text().splitlines()]
        # Since the second hostile review his words are not in the mail (they sat beside the tool's own instruction):
        # the tower reads them with `threads pending`. The start of the line, which the tower keys on, is unchanged.
        expected = "[threads] reply in topic (m2): run: threads pending"
        self.assertEqual([r['args'] for r in records], [[expected]])
        self.assertEqual(self.t()['messages'][-1]['text'], text)                # stored as typed
        # no notification for the other page actions
        for op in ('keep', 'close', 'reopen', 'sweep'):
            self.post_ok({'op': op, 'thread': 'topic'})
        self.assertEqual(len(self.record.read_text().splitlines()), 1)

    def test_list_table_moved_the_id_out_of_the_first_column(self):
        # v1: ID STATUS MESSAGES PENDING TITLE. A caller that cuts column 1 now gets the slot number.
        self.ok('new', 'topic', 'כותרת')
        rows = [line.split('\t') for line in self.ok('list').stdout.splitlines()]
        self.assertEqual(rows[0][:5], ['ID', 'STATUS', 'MESSAGES', 'PENDING', 'TITLE'])
        self.assertEqual(rows[1][:5], ['topic', 'open', '0', '0', 'כותרת'])


# ═══ 11. arguments ══════════════════════════════════════════════════════════

class Arguments(Base):
    def setUp(self):
        super().setUp()
        self.ok('new', 'topic', 'T')

    def test_held_awkward_but_legal_values_round_trip(self):
        self.ok('state', 'topic', 'working', '--note=-n starts with a dash, has = and , and "quotes"')
        self.assertEqual(self.t()['note'], '-n starts with a dash, has = and , and "quotes"')
        self.ok('ask', 'topic', '--options=-a, b=c ,d;e', '--', '-is this a flag?')
        self.assertEqual(self.t()['question']['options'], ['-a', 'b=c', 'd;e'])
        self.ok('ask', 'topic', 'q?', '--options', 'כן\n,\tלא\t, אולי  אחר ')
        self.assertEqual(self.t()['question']['options'], ['כן', 'לא', 'אולי אחר'])
        self.ok('link', 'topic', 'a=b', 'https://example.com/?a=b&c=d#e')
        self.ok('link', 'topic', 'path', '~/notes/a=b, c.md')
        self.ok('link', 'topic', 'UP', 'HTTPS://EXAMPLE.COM/x')
        self.ok('link', 'topic', ' two  words\n', ' /a/b ')
        self.assertEqual(self.t()['links'], [{'label': 'a=b', 'url': 'https://example.com/?a=b&c=d#e'}, {'label': 'path', 'url': '~/notes/a=b, c.md'},
                                             {'label': 'UP', 'url': 'HTTPS://EXAMPLE.COM/x'}, {'label': 'two words', 'url': '/a/b'}])
        self.ok('link', 'topic', 'two words', '--rm')
        for i in range(5):
            self.ok('link', 'topic', f'l{i}', '/x')
        self.refused('link', 'topic', 'ninth', '/x')
        self.ok('link', 'topic', 'l0', '/replaced')                       # replacing is not a ninth
        self.assertEqual(len(self.t()['links']), 8)
        self.ok('new', 'n', 'T', '--link', 'a=b=c', '--link', 'a=/second')
        self.assertEqual(self.t('n')['links'], [{'label': 'a', 'url': '/second'}])

    def test_link_target_with_a_leading_control_character_hides_its_scheme(self):
        # A browser drops leading C0 controls from a URL: "\x01javascript:alert(1)" IS javascript:alert(1) as an href.
        # str.strip() keeps \x01-\x08 and \x0e-\x1b, and the scheme test needs a letter first.
        for lead in ('\x01', '\x08', '\x0e', '\x1b', '\x01\x02 '):
            for scheme in ('javascript:alert(document.domain)', 'data:text/html,<script>alert(1)</script>', 'vbscript:x'):
                with self.subTest(target=repr(lead + scheme)):
                    self.refused('link', 'topic', 'l', lead + scheme)
                    self.refused('new', 'n', 'T', '--link', 'l=' + lead + scheme)

    def test_link_target_with_backslashes_is_another_host(self):
        # Browsers read "\" as "/" in http(s) URLs: /\evil.example and \\evil.example are //evil.example.
        for target in ('/\\evil.example/x', '\\\\evil.example/x', '\\/evil.example/x', '/\\/evil.example'):
            with self.subTest(target=target):
                self.refused('link', 'topic', 'l', target)

    def test_agent_text_and_header_fields_have_no_size_limit(self):
        # The page caps a reply at 8000 characters; nothing an agent writes is capped except the note.
        # One piped log file stays in state.json for good (no command edits or drops a message) and every page load fetches it.
        with self.subTest(field='say from stdin, over 20 MB'):
            self.refused('say', 'topic', '--from', 'fork', '-', input='x' * 20_000_001)
        for flag in ('--summary', '--title'):
            with self.subTest(field=f'set {flag}, 100 000 characters'):
                self.refused('set', 'topic', flag, 'y' * 100_000)
        with self.subTest(field='state --by, 100 000 characters'):
            self.refused('state', 'topic', 'working', '--by', 'b' * 100_000)
        with self.subTest(field='state --by with a line break'):
            self.ok('state', 'topic', 'working', '--by', 'lead\nsecond line')
            self.assertEqual(len(self.t()['state_by'].splitlines()), 1)

    def test_new_takes_titles_that_set_refuses_or_that_break_the_table(self):
        for title in ('', '   ', 'a\tb', 'a\nb\nc'):
            with self.subTest(title=repr(title)):
                r = self.cli('new', f'n{abs(hash(title)) % 10**6}', title)
                if r.returncode == 0:
                    rows = self.ok('list').stdout.splitlines()
                    self.assertEqual(len(rows), 1 + len(self.data()['threads']), 'a title broke the one-line-per-thread table')
                    self.assertTrue(all(len(row.split('\t')) == 8 for row in rows), 'a title added a column')
                    self.assertTrue(title.strip(), '`new` took an empty title that `set --title` refuses')


# ═══ 8. many processes at once ══════════════════════════════════════════════

class Concurrency(Base):
    def test_held_mixed_commands_and_page_actions_lose_nothing(self):
        e = self.at
        threads = [f't{i}' for i in range(6)]
        for tid in threads:
            self.ok('new', tid, 'T', env=e(0))
        self.ok('new', 'done-one', 'T', '--state', 'done', env=e(0))
        slots = self.slots()
        rng = random.Random(7)
        jobs = []
        for i in range(90):
            tid = rng.choice(threads)
            kind = rng.choice(('say', 'say', 'say-y', 'state', 'ask', 'ack', 'keepalive', 'list', 'pending', 'policy', 'link', 'set', 'sweep', 'new'))
            hours = 1 + i / 100
            if kind == 'say':
                jobs.append(('say', tid, ('say', tid, '--from', rng.choice(('tower', 'fork')), f'agent-{i}'), hours))
            elif kind == 'say-y':
                jobs.append(('say', tid, ('say', tid, '--from', 'owner', f'owner-{i}'), hours))
            elif kind == 'state':
                jobs.append((kind, tid, ('state', tid, 'working', '--note', f'n{i}'), hours))
            elif kind == 'ask':
                jobs.append(('say', tid, ('ask', tid, f'ask-{i}', '--options', 'a,b'), hours))
            elif kind == 'ack':
                jobs.append((kind, tid, ('ack', tid, f'm{rng.randint(1, 6)}'), hours))
            elif kind == 'keepalive':
                jobs.append((kind, tid, ('reopen', tid), hours))
            elif kind == 'policy':
                jobs.append((kind, tid, ('policy', '--idle-hours', str(12 + i % 3)), hours))
            elif kind == 'link':
                jobs.append((kind, tid, ('link', tid, f'l{i % 4}', f'/x/{i}'), hours))
            elif kind == 'set':
                jobs.append((kind, tid, ('set', tid, '--summary', f's{i}'), hours))
            elif kind == 'new':
                jobs.append((kind, f'n{i}', ('new', f'n{i}', 'T'), hours))
            else:
                jobs.append((kind, tid, (kind,), hours))
        replies = [(rng.choice(threads), f'page-{i}', f'cid-{i % 25}') for i in range(40)]     # 25 distinct cids, 15 retries

        def run(job):
            return job, self.cli(*job[2], env=e(job[3]))

        def page():
            results = []
            for i, (tid, text, cid) in enumerate(replies):                                     # the server runs one hook at a time
                self.put_request({'op': 'reply', 'thread': tid, 'text': text, 'cid': cid + tid})
                r = self.cli('ingest', env=e(1.2 + i / 100))
                results.append((tid, text, cid + tid, r))
            return results

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            page_future = pool.submit(page)
            done = list(pool.map(run, jobs))
            page_results = page_future.result()

        for job, r in done:
            self.assertNotIn('Traceback', r.stderr, job)
            if job[0] != 'ack':
                self.assertEqual(r.returncode, 0, (job, r.stderr))
        data = self.data()
        texts = {tid: [m['text'] for m in data['threads'][tid]['messages']] for tid in threads}
        for job, r in done:
            if job[0] == 'say':
                text = job[2][-1] if job[2][0] == 'say' else job[2][2]
                self.assertEqual(texts[job[1]].count(text), 1, f'{text} lost or doubled')
        accepted = {}
        for tid, text, cid, r in page_results:
            self.assertEqual(r.stderr, '')
            out = json.loads(r.stdout)
            self.assertTrue(out['ok'], out)
            accepted.setdefault(cid, (tid, text, out['msg_id']))
            self.assertEqual(out['msg_id'], accepted[cid][2])                                   # a retry names the first message
            self.assertEqual(out['dup'], accepted[cid][1] != text)
        for cid, (tid, text, msg_id) in accepted.items():
            stored = [m for m in data['threads'][tid]['messages'] if m.get('cid') == cid]
            self.assertEqual([(m['id'], m['text']) for m in stored], [(msg_id, text)])
        notified = [json.loads(line)['args'][0] for line in self.record.read_text().splitlines()]
        self.assertEqual(len(notified), len(accepted))
        for tid in threads:
            t = data['threads'][tid]
            ids = [m['id'] for m in t['messages']]
            self.assertEqual(ids, [f'm{i}' for i in range(1, len(ids) + 1)])                    # no id reused, none skipped
            self.assertEqual(t['next'], len(ids) + 1)
            self.assertEqual((t['status'], t['slot']), ('open', slots[tid]))
            self.assert_note_rule(t)
        open_slots = self.slots()
        self.assertEqual(len(set(open_slots.values())), len(open_slots))
        self.assertEqual(sum(1 for tid in data['threads'] if tid.startswith('n')), sum(1 for j in jobs if j[0] == 'new'))
        self.assertEqual(data['threads']['done-one']['status'], 'open')
        self.assertEqual([p.name for p in self.board.glob('.state.json.*.tmp')], [])           # no temp file left behind

    def test_held_parallel_close_reopen_new_keep_slots_unique(self):
        e = self.at
        for i in range(8):
            self.ok('new', f't{i}', 'T', env=e(0))
        rng = random.Random(3)
        jobs = []
        for i in range(80):
            tid = f't{rng.randrange(8)}'
            jobs.append(rng.choice((('close', tid), ('reopen', tid), ('new', f'x{i}', 'T'), ('rm', tid, '--yes'), ('state', tid, 'done'), ('sweep',))))
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda job: (job, self.cli(*job, env=e(1 + rng.random() * 40))), jobs))
        for job, r in results:
            self.assertNotIn('Traceback', r.stderr, job)
        slots = self.slots()
        self.assertEqual(len(set(slots.values())), len(slots), slots)
        self.assertTrue(all(type(s) is int and s > 0 for s in slots.values()))
        json.loads(self.ok('list', '--json', env=e(1)).stdout)


# ═══ everything else: a model-based random walk ═════════════════════════════

class Fuzz(Base):
    def test_held_random_walk_finds_no_other_violation(self):
        # adv_a_fuzz.py drives ~4500 random commands and page actions with a moving clock and checks,
        # after each one: unique stable slots, cooldown, archive only when idle+done+due, history intact,
        # refused = no write, reads = no write, the turn rules, the reply rules. The two slot holes that
        # have their own failing tests above are counted as "known", not as violations.
        for seed in (11, 12, 13):
            with self.subTest(seed=seed):
                env = dict(self.env, BOARDS_DIR=str(self.root / f'fuzz{seed}'), THREADS_NOTIFY='0')
                r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'adv_a_fuzz.py'), str(seed), '1500'], env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-800:])
                out = json.loads(r.stdout)
                self.assertEqual(out['steps'], 1500)
                self.assertGreater(sum(ok for ok, _ in out['coverage'].values()), 700)
                self.assertEqual(out['violations'], {}, json.dumps(out['violations'], ensure_ascii=False)[:1500])


if __name__ == '__main__':
    unittest.main()
