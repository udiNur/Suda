#!/usr/bin/env python3
"""Hostile review of a9b8304..e40e44e ("a message that did not get through goes again by itself"): the server
side (threads.py: the reply branch of ingest, `taking`, the receipt's `again`, the lines in notify.log), the
worker (sw.js: the rule that sends everything but the page's own file past it), and the board server between
the page and the hook, as the page's postFault() reads it.

One test per attack. A test named `test_held_...` is an attack the code withstood. Any other test asserts the
correct or safe outcome of a suspected hole, so a FAILING test is a real hole.

Nothing here leaves this machine or touches the live board: every board is a temp folder inside this worktree,
HOME is a fake one inside it, the tower's mail, the push service and the phone are recorder scripts, and the one
server is the e2e harness's own (test_e2e.Suda.start_server: answer_server on 127.0.0.1, a free port, a temp
BOARDS_DIR). No browser is needed. Run:

    THREADS_NOTIFY=0 python3 -m unittest test_adv_send_server -v
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zlib

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
BOARDLIB = Path(os.environ.get('THREADS_BOARDLIB_DIR') or Path.home() / '.claude/skills/html-interview-board')
T0 = 1_800_000_000.0
GENERIC = 'לא ניתן לקרוא או לשמור את ההודעה'
MAIL = ("import json, os, sys\nfrom pathlib import Path\n"
        "with Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args': sys.argv[1:]}) + '\\n')\n")
TOLD = ("import json, os, sys\nwith open(os.environ['TOLD_RECORD'], 'a') as f:\n f.write(json.dumps([%r] + sys.argv[1:]) + '\\n')\n%s\n")
# Stands in for the transcription service: the words come only once the test says so (or after 40 seconds).
EAR = ("import os, sys, time\nend = time.time() + 40\nwhile not os.path.exists(os.environ['EAR_GO']) and time.time() < end:\n time.sleep(0.1)\nprint('words')\n")
UNSET = ('THREADS_NOTIFY', 'THREADS_SLUG', 'THREADS_NOW', 'THREADS_CONFIG_DIR', 'BOARD_LOCK_TIMEOUT', 'THREADS_SONIOX_MODEL',
         'THREADS_SONIOX_CMD', 'THREADS_GH_CMD')


def png(shade=0):
    """A small valid PNG (2x2), so the picture path runs on real image bytes."""
    rows = b''.join(b'\x00' + bytes([shade, 120, 200] * 2) for _ in range(2))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


PNG = base64.b64encode(png()).decode()



def unreadable(board, mode):
    """The board's state cannot be read just now (mode 0), or can again: state.json and the store (sqlite177)."""
    for name in ('state.json', 'suda.db'):
        if (board / name).exists():
            (board / name).chmod(mode)

class Box:
    """One temp board with stand-ins for everything that leaves this machine."""

    def __init__(self, case):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-adv-send-', dir=ROOT)
        case.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        assert ROOT in self.root.resolve().parents, 'a test board must live inside the worktree'
        self.board = self.root / 'boards/threads'
        self.mail, self.told = self.root / 'mail.jsonl', self.root / 'told.jsonl'
        (self.root / 'home').mkdir()
        # the owner's installation is in Hebrew (the words these tests expect): its private config beside the boards
        (self.root / '.threads-config/threads').mkdir(parents=True)
        (self.root / '.threads-config/threads/config.json').write_text(json.dumps({'lang': 'he'}), encoding='utf-8')
        for name, body in (('mail.py', MAIL), ('push.py', TOLD % ('push', "print('201')")), ('snap.py', TOLD % ('snap', ''))):
            (self.root / name).write_text(body)
        run = lambda name: shlex.join([sys.executable, str(self.root / name)])
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), TZ='UTC', HOME=str(self.root / 'home'),
                        THREADS_BOARDLIB_DIR=str(BOARDLIB), THREADS_NOTIFY_CMD=run('mail.py'), NOTIFY_RECORD=str(self.mail),
                        THREADS_PUSH_CMD=run('push.py'), THREADS_SNAP_CMD=run('snap.py'), TOLD_RECORD=str(self.told),
                        TUIOS_PANE_ID='must-be-removed')
        for key in UNSET:       # the tower's mail is the recorder: a repeat that mails anyone is seen there
            self.env.pop(key, None)

    def safe(self, env):
        assert env['BOARDS_DIR'] == str(self.root / 'boards') and env['HOME'] == str(self.root / 'home'), 'never the live board'
        assert all(env.get(k) for k in ('THREADS_NOTIFY_CMD', 'THREADS_PUSH_CMD', 'THREADS_SNAP_CMD')), 'never a real service'
        assert not env.get('THREADS_SLUG') and not env.get('THREADS_CONFIG_DIR'), 'never a real board or a real key folder'
        return env

    def at(self, hours):
        return dict(self.env, THREADS_NOW=str(T0 + hours * 3600))

    def cli(self, *args, env=None, input=None):
        return subprocess.run([sys.executable, str(CLI), *args], env=self.safe(env or self.env), input=input, capture_output=True, text=True)

    def ok(self, *args, env=None):
        r = self.cli(*args, env=env)
        assert r.returncode == 0, (args, r.stdout, r.stderr)
        return r.stdout.strip()

    def post(self, payload, env=None):
        """What the board server does for the page: it stores the body, then runs the hook's command.
        (exit code, the receipt or None, stdout, stderr)."""
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding='utf-8')
        r = self.cli('ingest', env=env)
        lines = r.stdout.strip().splitlines()
        try:
            receipt = json.loads(lines[-1]) if lines else None
        except ValueError:
            receipt = None
        return r.returncode, receipt, r.stdout, r.stderr

    def reply(self, tid, text, cid, env=None, **more):
        return self.post({'op': 'reply', 'thread': tid, 'text': text, 'cid': cid, **more}, env=env)

    def state(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def thread(self, tid):
        return self.state()['threads'][tid]

    def log(self):
        path = self.board / 'notify.log'
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    def mails(self):
        return [json.loads(line)['args'] for line in self.mail.read_text().splitlines()] if self.mail.exists() else []

    def snapshot(self):
        """Everything a command could have changed: every file of the board and of its private folder (bytes and
        time of writing; `.pulse`, whose touch wakes the pages, among them), the tower's mail, the pushes and the
        phone alerts. Left out: the log, the request body the server stores, and the locks."""
        seen = {}
        for base in (self.board, self.root / '.threads-config'):
            for path in sorted(base.rglob('*')) if base.exists() else ():
                rel = str(path.relative_to(self.root))
                if not path.is_file() or path.name == 'notify.log' or rel.endswith('state/state.json') or path.name.endswith('.lock'):
                    continue
                seen[rel] = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for record in (self.mail, self.told):
            seen[record.name] = record.read_text() if record.exists() else ''
        return seen


class Repeats(unittest.TestCase):
    """The same message, sent again: stored once, answered as the first time, and nothing else moves."""

    DUP = {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': True}

    def start(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא ראשון', '--context', 'רקע')
        self.assertEqual(box.reply('a', 'שלום', 'c1')[:2], (0, {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': False}))
        return box

    def again(self, box, what, env=None, **more):
        """Send c1 again; it must be answered as the first time, and the board must stand exactly as it stood."""
        before = box.snapshot()
        code, receipt, _, err = box.reply('a', more.pop('text', 'שלום'), 'c1', env=env, **more)
        self.assertEqual((code, receipt, err), (0, self.DUP, ''), what)
        self.assertEqual(box.snapshot(), before, what + ': a repeat changed something')

    def test_held_a_repeat_is_answered_as_the_first_time_whatever_happened_to_the_thread(self):
        box = self.start()
        self.assertEqual(box.post({'op': 'draft', 'thread': 'a', 'text': 'מה שהתחיל לכתוב אחר כך'})[0], 0)
        steps = (('closed by the tower', lambda: box.ok('close', 'a')), ('re-opened', lambda: box.ok('reopen', 'a')),
                 ('renamed', lambda: box.ok('rename', 'a', 'שם אחר לגמרי')), ('asleep', lambda: box.ok('snooze', 'a', '--until', '+2h')),
                 ('muted', lambda: box.ok('mute', 'a')), ('closed by him', lambda: self.assertEqual(box.post({'op': 'close', 'thread': 'a'})[0], 0)))
        for what, change in steps:
            change()
            self.again(box, what)
        self.assertEqual(box.thread('a')['status'], 'closed')
        self.assertEqual([m['id'] for m in box.thread('a')['messages']], ['m1'])
        self.assertEqual(json.loads((box.board / 'drafts.json').read_text())['drafts']['a']['text'], 'מה שהתחיל לכתוב אחר כך')
        # Decided after this review: nothing is written for a refusal or for a message that arrives a second time
        # (the earlier reviews' rule, "a refused request writes nothing"); only a failure nobody foresaw leaves its kind.
        self.assertEqual(box.log(), '')

    def test_held_a_repeat_does_not_bring_back_a_thread_that_archived_itself(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא', env=box.at(0))
        self.assertEqual(box.reply('a', 'שלום', 'c1', env=box.at(0))[1]['msg_id'], 'm1')
        box.ok('ack', 'a', 'm1', env=box.at(0))
        box.ok('say', 'a', '--from', 'fork', 'בוצע', '--state', 'done', '--note', 'סגור', env=box.at(0))
        box.ok('sweep', env=box.at(30))
        self.assertEqual((box.thread('a')['status'], box.thread('a')['closed_by']), ('closed', 'auto'))
        self.again(box, 'archived by the timer', env=box.at(31))
        self.assertEqual(box.thread('a')['status'], 'closed')

    def test_held_a_repeat_in_a_thread_whose_sleep_just_ended_wakes_nothing_and_loses_nothing(self):
        """The sweep that runs before the repeat is found wakes the thread in memory (mail to the tower, a new
        thing on him). The repeat returns before anything is saved: none of it may leak out half done, and the
        next command must still do all of it."""
        box = Box(self)
        box.ok('new', 'a', 'נושא', env=box.at(0))
        self.assertEqual(box.reply('a', 'שלום', 'c1', env=box.at(0))[1]['msg_id'], 'm1')
        box.ok('snooze', 'a', '--until', '+1h', env=box.at(0))
        mails = len(box.mails())
        self.again(box, 'its sleep is over', env=box.at(2))
        self.assertIn('snooze', box.thread('a'))                    # not half woken
        self.assertEqual(len(box.mails()), mails)
        box.ok('sweep', env=box.at(2))
        self.assertNotIn('snooze', box.thread('a'))
        self.assertEqual(sum('snooze woke a' in ' '.join(args) for args in box.mails()), 1)

    def test_held_a_repeat_that_carries_other_things_applies_none_of_them(self):
        box = self.start()
        box.ok('say', 'a', '--from', 'tower', 'הרץ:\n```\n! echo hi\n```')
        box.ok('ask', 'a', 'מה לבחור?', '--options', 'כן,לא')
        question = box.thread('a')['question']['id']
        for what, more in (('other words', {'text': 'משהו אחר לגמרי'}), ('a picture', {'text': '', 'images': [{'name': 'a.png', 'data': PNG, 'caption': 'כיתוב'}]}),
                           ('a long text', {'snippet': {'name': 'x.txt', 'text': 'ארוך ' * 50}}), ('a message that is not there', {'reply_to': 'm999'}),
                           ('a quote', {'reply_to': 'm2', 'quote': 'echo'}), ('the open question', {'q': question}), ('a question that is gone', {'q': 'm999'}),
                           ('under the question', {'under': question}), ('a command to run', {'run': {'msg_id': 'm2', 'block_index': 0, 'sha256': hashlib.sha256(b'! echo hi').hexdigest()}}),
                           ('ticks', {'answer': {'': ['כן']}, 'q': question})):
            self.again(box, what, **more)
        t = box.thread('a')
        self.assertEqual((t['question']['id'], t['state'], [m['id'] for m in t['messages']]), (question, 'on-owner', ['m1', 'm2', 'm3']))
        self.assertFalse((box.board / 'uploads').exists() or (box.board / 'snippets').exists())

    def test_held_a_repeat_of_a_message_with_a_picture_writes_no_second_copy(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        picture = {'images': [{'name': 'a.png', 'data': PNG}]}
        self.assertEqual(box.reply('a', 'עם תמונה', 'c1', **picture)[1], {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': False})
        self.assertEqual(sorted(p.name for p in (box.board / 'uploads/a').iterdir()), ['m1-1.png'])
        box.ok('close', 'a')
        self.again(box, 'a picture message, in a closed thread', text='עם תמונה', **picture)
        self.assertEqual(sorted(p.name for p in (box.board / 'uploads/a').iterdir()), ['m1-1.png'])
        self.assertEqual((box.board / 'state/state.json').read_text(), '{}\n')       # the picture as his phone made it does not stay in the served folder

    def test_held_an_id_stored_in_one_thread_opens_no_door_in_another(self):
        box = self.start()
        box.ok('new', 'b', 'נושא שני')
        box.ok('close', 'b')
        code, receipt, _, _ = box.reply('b', 'שלום', 'c1')
        self.assertEqual((code, receipt), (1, {'ok': False, 'error': 'השרשור סגור'}))
        box.ok('reopen', 'b')
        box.ok('ask', 'b', 'מה לבחור?', '--options', 'כן,לא')
        code, receipt, _, _ = box.reply('b', 'כן', 'c1', q='m999')
        self.assertEqual((code, receipt), (1, {'ok': False, 'error': 'השאלה הזאת כבר לא פתוחה'}))
        self.assertEqual([m.get('cid') for m in box.thread('b')['messages'] if m['from'] == 'owner'], [])

    def test_held_a_repeated_new_topic_is_the_same_topic_also_after_it_was_renamed_and_closed(self):
        box = Box(self)
        topic = {'op': 'new', 'title': 'נושא מהדף', 'text': 'שלום', 'cid': 'n1'}
        code, first, _, _ = box.post(topic)
        self.assertEqual((code, first['dup']), (0, False))
        tid = first['thread']
        box.ok('rename', tid, 'שם אחר')
        box.ok('close', tid)
        self.assertEqual(box.post({'op': 'draft', 'thread': '_new', 'text': 'הנושא הבא'})[0], 0)
        before = box.snapshot()
        code, second, _, err = box.post(topic)
        self.assertEqual((code, second, err), (0, {**first, 'dup': True}, ''))
        self.assertEqual(box.snapshot(), before)
        self.assertEqual(list(box.state()['threads']), [tid])

    def test_a_repeated_new_topic_writes_nothing_like_a_repeated_reply(self):
        """A new topic is a message of his too (its first), and the same page sends it: its second arrival is
        answered as the first, and leaves nothing behind."""
        box = Box(self)
        topic = {'op': 'new', 'title': 'נושא מהדף', 'text': 'שלום', 'cid': 'n1'}
        tid = box.post(topic)[1]['thread']
        self.assertEqual(box.post(topic)[1]['dup'], True)
        self.assertTrue(tid)
        self.assertEqual(box.log(), '')


class Again(unittest.TestCase):
    """`again` in the receipt: only for what the next try may get through."""

    def test_held_no_refusal_says_again(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        box.ok('new', 'shut', 'נושא סגור')
        box.ok('close', 'shut')
        box.ok('ask', 'a', 'מה לבחור?', '--options', 'כן,לא')
        refusals = (({'op': 'reply', 'thread': 'shut', 'text': 'x', 'cid': 'r1'}, 'השרשור סגור'),
                    ({'op': 'reply', 'thread': 'nowhere', 'text': 'x', 'cid': 'r2'}, 'השרשור לא נמצא'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'r3', 'q': 'm999'}, 'השאלה הזאת כבר לא פתוחה'),
                    ({'op': 'reply', 'thread': 'a', 'text': '', 'cid': 'r4'}, 'יש לכתוב הודעה באורך עד 8000 תווים'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x'}, 'מזהה הודעה לא תקין'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'r5', 'reply_to': 'm999'}, 'ההודעה לא נמצאה'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x\ud800', 'cid': 'r6'}, 'הטקסט כולל תו שאי אפשר לשמור'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'r7', 'images': [{'data': '!!'}]}, 'תמונה לא תקינה'),
                    ({'op': 'reply', 'thread': 'a', 'text': '', 'cid': 'r8', 'voice': {'data': base64.b64encode(b'\x1a\x45\xdf\xa3' + b'x' * 40).decode(), 'seconds': 2}}, 'השרת הזה לא מתמלל הקלטות'),
                    ({'op': 'reply', 'thread': 'a', 'cid': 'r9', 'answer': {'א': ['x']}, 'q': 'm1'}, 'זו לא שאלת בחירה מרובה, או שהתשובה לא תקינה'),
                    ({'op': 'reply', 'thread': 'a', 'text': 'x', 'cid': 'r10', 'run': {'msg_id': 'm1', 'block_index': 0, 'sha256': 'x'}}, 'אין בהודעה הזאת פקודה של המגדל שאפשר לבקש להריץ'),
                    ({'op': 'reply', 'thread': ['a'], 'text': 'x', 'cid': 'r11'}, 'שרשור לא תקין'),
                    ({'op': 'new', 'title': 'נושא', 'text': 'x', 'cid': 'r12'}, 'כבר יש נושא פתוח בשם הזה'),
                    ({'op': 'new', 'title': '', 'text': '', 'cid': 'r13'}, 'נושא חדש צריך כותרת או הודעה'),
                    ({'op': 'no-such-op'}, 'בקשה לא תקינה'), ([], 'בקשה לא תקינה'))
        state = (box.board / 'state.json').read_bytes()
        for request, reason in refusals:
            code, receipt, out, err = box.post(request)
            self.assertEqual((code, receipt['ok'], receipt['error'], err, len(out.strip().splitlines())), (1, False, reason, '', 1), request)
            self.assertNotIn('again', receipt, request)
        self.assertEqual((box.board / 'state.json').read_bytes(), state)

    def stored(self, box):
        return [m.get('cid') for m in box.thread('a')['messages']]

    def test_held_what_may_pass_by_the_next_try_says_again_and_the_next_try_stores_it_once(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        state, body = box.board / 'state.json', box.board / 'state/state.json'
        maybe = {'ok': False, 'error': GENERIC, 'again': True}
        # 1. the lock of the state is held by another command for longer than this one may wait
        holder = subprocess.Popen([sys.executable, '-c', "import sys, time\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\nimport boardlib as bl\n"
                                   "with bl.file_lock(sys.argv[2]):\n print('held', flush=True)\n time.sleep(60)\n", str(BOARDLIB), str(state)],
                                  env=box.safe(box.env), stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'held')
            code, receipt, _, err = box.reply('a', 'בזמן נעילה', 'c1', env=dict(box.env, BOARD_LOCK_TIMEOUT='0.4'))
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        self.assertEqual((code, receipt, err), (1, maybe, ''))
        self.assertEqual(box.reply('a', 'בזמן נעילה', 'c1')[1], {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': False})
        # 2. the state cannot be read just now
        unreadable(box.board, 0)
        try:
            code, receipt, _, err = box.reply('a', 'אין הרשאה', 'c2')
        finally:
            unreadable(box.board, 0o644)
        self.assertEqual((code, receipt, err), (1, maybe, ''))
        self.assertEqual(box.reply('a', 'אין הרשאה', 'c2')[1], {'ok': True, 'thread': 'a', 'msg_id': 'm2', 'dup': False})
        # 3. nothing can be written into the board just now
        box.board.chmod(0o555)
        try:
            code, receipt, _, err = box.reply('a', 'אין מקום', 'c3')
        finally:
            box.board.chmod(0o755)
        self.assertEqual((code, receipt, err), (1, maybe, ''))
        self.assertEqual(box.reply('a', 'אין מקום', 'c3')[1], {'ok': True, 'thread': 'a', 'msg_id': 'm3', 'dup': False})
        # 4. the request itself cannot be read (the server's file is gone)
        body.unlink()
        r = box.cli('ingest')
        self.assertEqual((r.returncode, json.loads(r.stdout), r.stderr), (1, maybe, ''))
        self.assertEqual(self.stored(box), ['c1', 'c2', 'c3'])
        # Decided after this review: nothing is written for a refusal or for a message that arrives a second time
        # (the earlier reviews' rule, "a refused request writes nothing"); only a failure nobody foresaw leaves its kind.
        self.assertEqual(box.log(), '')

    def test_held_a_failure_after_the_message_was_stored_ends_as_stored_once(self):
        """The state is written, and the step after it fails (the mark that wakes the pages cannot be touched). The
        message is stored, so the receipt says so (sse153: a step after the save fails nothing; a receipt of "again"
        made an agent's retry, which has no cid, post twice). The pages are not left behind: the server's line finds
        no number in the mark and says a plain "changed", and they read. Sent again by its cid, it is found."""
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        pulse = box.board / '.pulse'
        pulse.unlink()
        pulse.symlink_to(box.root / 'no-such-folder/pulse')
        code, receipt, _, err = box.reply('a', 'נשמר ואז נכשל', 'c1')
        pulse.unlink()
        self.assertEqual((code, receipt, err), (0, {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': False}, ''))
        self.assertEqual(box.reply('a', 'נשמר ואז נכשל', 'c1')[1], {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': True})
        self.assertEqual(self.stored(box), ['c1'])

    def test_a_new_topic_whose_link_cannot_be_stored_is_refused_and_not_marked_for_another_try(self):
        """Half a character pair (a lone surrogate) in the words of a message is refused with its reason, before
        anything is written. In the label or the address of a link of a new topic nobody checks it: the state then
        cannot be written, every time, and the receipt calls that a failure "that may pass by the next try"."""
        box = Box(self)
        for links in ([{'label': 'תווית \ud83d', 'url': '/x'}], [{'label': 'תווית', 'url': '/x\ud83d'}]):
            code, receipt, _, err = box.post({'op': 'new', 'title': 'נושא עם קישור', 'text': 'שלום', 'cid': 'n1', 'links': links})
            self.assertEqual((code, receipt.get('ok'), err), (1, False, ''))
            self.assertNotIn('again', receipt, 'a request that can never be stored is reported as one to send again')
            self.assertNotEqual(receipt['error'], GENERIC)

    def test_a_refusal_that_itself_says_try_again_in_a_moment_is_marked_for_another_try(self):
        """Three recordings may be transcribed at one time; a fourth is refused with "… נסה שוב בעוד רגע". That is,
        in the server's own words, a failure that passes by itself within seconds, and the receipt marks it as a
        refusal: the page shows "not sent" and waits for his finger, which is what this change set out to end."""
        box = Box(self)
        go = box.root / 'ear-go'
        (box.root / 'ear.py').write_text(EAR)
        env = dict(box.env, THREADS_SONIOX_CMD=shlex.join([sys.executable, str(box.root / 'ear.py')]), EAR_GO=str(go))
        box.ok('new', 'a', 'נושא')

        def settle():           # the workers that transcribe end before the board is taken away
            go.write_text('')
            end = time.time() + 50
            while time.time() < end and any(m.get('status') == 'transcribing' for m in box.thread('a')['messages']):
                time.sleep(0.3)
        self.addCleanup(settle)
        voice = lambda n: {'op': 'reply', 'thread': 'a', 'text': '', 'cid': f'v{n}', 'voice': {'data': base64.b64encode(b'\x1a\x45\xdf\xa3' + bytes([n]) * 60).decode(), 'seconds': 2}}
        for n in (1, 2, 3):
            code, receipt, _, err = box.post(voice(n), env=env)
            self.assertEqual((code, receipt.get('dup'), err), (0, False, ''), receipt)
        code, receipt, _, _ = box.post(voice(4), env=env)
        self.assertEqual((code, receipt['ok']), (1, False))
        self.assertIn('נסה שוב בעוד רגע', receipt['error'])
        self.assertEqual([m.get('cid') for m in box.thread('a')['messages']], ['v1', 'v2', 'v3'])
        self.assertEqual(receipt.get('again'), True, 'the server says "try again in a moment", and tells the page not to')

    JUNK = '{"op":"presence","page":"junkpage","focused":true,"idle":1' + '0' * 400 + '}'       # a whole number that no float can hold

    def test_whatever_goes_wrong_the_page_gets_a_receipt(self):
        """main() answers the page only for the kinds of failure it lists. Any other kind ends the hook with a
        traceback and no receipt, and the page's postFault() reads "no receipt" as a refusal: `no`, never sent
        again by itself. One such kind can be had on demand (OUTSIDE this change: the `presence` op): with phone
        alerts on, a page that reports an idle time of 10^400 seconds makes every command that decides whom to
        ring fail with OverflowError for the next 45 seconds, and a reply is such a command."""
        box = Box(self)
        box.ok('notify', '--snap', 'on')
        box.ok('new', 'a', 'נושא')
        box.ok('new', 'b', 'נושא אחר, שמחכה לו')            # something is on him and his phone has not rung for it yet
        box.post(self.JUNK)
        code, receipt, out, err = box.reply('a', 'שלום', 'c1')
        self.assertFalse('Traceback' in err, 'the hook printed %r and ended with a traceback: … %s' % (out, ' / '.join(err.strip().splitlines()[-3:])))
        self.assertIsNotNone(receipt, 'no receipt at all')
        self.assertTrue(receipt.get('ok') is True or receipt.get('again') is True, receipt)

    def test_a_junk_report_of_presence_stops_no_message_and_no_alert(self):
        """Outside this change, found on the way (see the test above): nobody proves who posts a page action, and
        one of them every 45 seconds must not stop his replies, the agents' messages and the timer."""
        box = Box(self)
        box.ok('notify', '--snap', 'on')
        box.ok('new', 'a', 'נושא')
        box.post(self.JUNK)
        said = box.cli('say', 'a', '--from', 'fork', 'משהו בשבילך')
        self.assertEqual((said.returncode, said.stdout.strip()), (0, 'm1'), said.stderr[-300:])
        self.assertEqual(box.reply('a', 'שלום', 'c1')[1], {'ok': True, 'thread': 'a', 'msg_id': 'm2', 'dup': False})
        swept = box.cli('sweep')
        self.assertEqual(swept.returncode, 0, swept.stderr[-300:])

    def test_held_two_commands_in_one_process_do_not_hand_the_action_on(self):
        """A second command in the same process (the tests and the fuzzer call main() again and again) must not be
        answered under the action of the one before it, and none of them leaves a line."""
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        script = textwrap.dedent('''
            import contextlib, io, json, os, sys
            sys.dont_write_bytecode = True
            sys.path.insert(0, sys.argv[1])
            import threads
            body = threads.BOARD / 'state/state.json'
            def call(request):
                if request is None:
                    body.unlink()
                else:
                    body.parent.mkdir(parents=True, exist_ok=True)
                    body.write_text(json.dumps(request), encoding='utf-8')
                sys.argv, out = ['threads.py', 'ingest'], io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = threads.main()
                return [code, json.loads(out.getvalue().strip().splitlines()[-1])]
            print(json.dumps([call({'op': 'reply', 'thread': 'nowhere', 'text': 'x', 'cid': 'c'}),     # refused: a line in the log
                              call(None),                                                              # no request at all: nobody's message
                              call({'op': 'rename', 'thread': 'nowhere', 'title': 'x'}),               # refused, and not a message
                              call({'op': 'sweep'})]))
        ''')
        r = subprocess.run([sys.executable, '-c', script, str(ROOT)], env=box.safe(box.env), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second, third, fourth = json.loads(r.stdout)
        self.assertEqual(first, [1, {'ok': False, 'error': 'השרשור לא נמצא'}])
        self.assertEqual(second, [1, {'ok': False, 'error': GENERIC, 'again': True}])
        self.assertEqual(third, [1, {'ok': False, 'error': 'השרשור לא נמצא'}])
        self.assertEqual(fourth[:2], [0, {'ok': True, 'op': 'sweep', 'archived': []}])
        self.assertEqual(box.log(), '')


class Log(unittest.TestCase):
    """notify.log sits in the served folder: anyone on the private network reads it, and anyone there can post."""

    LINE = re.compile(r'\d{10}\.\d{3} (ingest|dup): [^\x00-\x1f\x7f]{1,330}')

    def test_held_the_log_holds_nothing_he_wrote_and_no_line_of_anyone_elses_making(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        box.ok('new', 'shut', 'סגור')
        box.ok('close', 'shut')
        fake = '\n1800000000.000 dup: a m1\r\n\x1b[31mSECRET'
        requests = ({'op': 'reply', 'thread': 'shut', 'text': 'SECRET words', 'cid': 'SECRET-cid', 'reply_to': 'SECRET-msg', 'quote': 'SECRET quote',
                     'images': [{'name': 'SECRET.png', 'data': PNG, 'caption': 'SECRET caption'}]},
                    {'op': 'reply', 'thread': 'shut', 'text': 'SECRET', 'cid': 'c', 'snippet': {'name': 'SECRET.txt', 'text': 'SECRET ' * 400}},
                    {'op': 'reply', 'thread': 'shut', 'text': 'SECRET', 'cid': 'c' + fake},
                    {'op': 'reply', 'thread': 'a' + fake, 'text': 'SECRET', 'cid': 'c'},
                    {'op': 'reply', 'thread': 'SECRET' * 60, 'text': 'SECRET', 'cid': 'c'},
                    {'op': 'reply', 'thread': 'a', 'text': 'SECRET' + fake, 'cid': 'c', 'q': 'SECRET-q' + fake},
                    {'op': 'reply', 'thread': 'a', 'text': 'SECRET', 'cid': 'c', 'reply_to': 'SECRET' + fake},
                    {'op': 'reply', 'thread': 'a', 'cid': 'c', 'q': 'm1', 'answer': {'SECRET' + fake: ['SECRET']}, 'note': 'SECRET'},
                    {'op': 'reply', 'thread': 'a', 'text': 'SECRET', 'cid': 'c', 'run': {'msg_id': 'SECRET', 'block_index': 0, 'sha256': 'SECRET'}},
                    {'op': 'new', 'title': 'סגור' + fake, 'text': 'SECRET', 'cid': 'SECRET', 'context': 'SECRET', 'links': [{'label': 'SECRET', 'url': 'javascript:SECRET'}]},
                    {'op': 'new', 'title': 'x', 'text': 'SECRET', 'cid': 'c', 'split': {'thread': 'SECRET' + fake, 'msg': 'SECRET'}},
                    {'op': 'new', 'title': 'x', 'text': 'SECRET', 'cid': 'c', 'thread': 'SECRET' + fake, 'images': []})
        for request in requests:
            code, receipt, _, _ = box.post(request)
            self.assertEqual((code, receipt['ok']), (1, False), request)
        unreadable(box.board, 0)
        try:        # and the failures that are not refusals
            self.assertEqual(box.post(requests[5])[1].get('again'), True)
        finally:
            unreadable(box.board, 0o644)
        # Decided after this review: nothing is written for a refusal or for a message that arrives a second time
        # (the earlier reviews' rule, "a refused request writes nothing"); only a failure nobody foresaw leaves its kind.
        self.assertEqual(box.log(), '')

    def test_held_a_log_that_cannot_be_written_fails_no_request(self):
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        self.assertEqual(box.reply('a', 'שלום', 'c1')[1]['msg_id'], 'm1')
        log = box.board / 'notify.log'
        for what, spoil, mend in (('a folder', lambda: log.mkdir(), lambda: log.rmdir()),
                                  ('read only', lambda: (log.write_text(''), log.chmod(0o444)), lambda: log.unlink()),
                                  ('a link to nowhere', lambda: log.symlink_to(box.root / 'no-such-folder/log'), lambda: log.unlink())):
            if log.exists():
                log.unlink()
            spoil()
            try:
                self.assertEqual(box.reply('a', 'שלום', 'c1')[:2], (0, {'ok': True, 'thread': 'a', 'msg_id': 'm1', 'dup': True}), what)
                self.assertEqual(box.reply('nowhere', 'שלום', 'c2')[:2], (1, {'ok': False, 'error': 'השרשור לא נמצא'}), what)
                self.assertEqual(box.reply('a', 'חדש ' + what, 'new ' + what)[1]['dup'], False, what)
            finally:
                mend()

    def test_the_log_names_no_folder_of_this_machine(self):
        """The line of a failure carries the text of the exception. For anything the disk refuses that text holds
        the full path of the file (so: his user name and where his boards live), in a file anyone on the private
        network can read."""
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        unreadable(box.board, 0)
        try:
            self.assertEqual(box.reply('a', 'שלום', 'c1')[1].get('again'), True)
        finally:
            unreadable(box.board, 0o644)
        self.assertNotIn(str(box.root), box.log(), 'the served log names the folders of this machine')
        self.assertNotIn(os.sep + 'boards' + os.sep, box.log())
        self.assertEqual(box.log(), '')                 # a failure the hook knows (the disk refused) writes nothing either

    def test_the_log_cannot_be_made_to_grow_without_end_by_requests_that_cost_nothing(self):
        """Nobody proves who posts. A request of forty bytes that stores nothing ({"op":"reply"}) now adds a line
        to a file that is never cut. A log that is already far past any size a person reads must not go on growing
        with every such request."""
        box = Box(self)
        box.ok('new', 'a', 'נושא')
        log = box.board / 'notify.log'
        old = '1700000000.000 ingest: reply -: ValueError: שרשור לא תקין\n'
        log.write_text(old * (8_000_000 // len(old.encode('utf-8'))), encoding='utf-8')
        size = log.stat().st_size
        for n in range(5):
            self.assertEqual(box.post({'op': 'reply'})[1], {'ok': False, 'error': 'שרשור לא תקין'})
        self.assertLessEqual(log.stat().st_size, size, 'an 8 MB log still grows by a line for every request that was refused')


class Wire(unittest.TestCase):
    """Through the real board server (the e2e harness's own: 127.0.0.1, a free port, a temp board), as the page's
    postFault() reads what comes back."""

    SLUG = 'adv-send'

    @classmethod
    def setUpClass(cls):
        import test_e2e
        if not (test_e2e.SKILL / 'answer_server.py').is_file():
            raise unittest.SkipTest('the board server is not at ' + str(test_e2e.SKILL))
        cls.tmp = tempfile.TemporaryDirectory(prefix='.threads-adv-send-wire-', dir=ROOT)
        root = Path(cls.tmp.name)
        cls.boards = root / 'boards'
        cls.boards.mkdir()
        (root / 'home').mkdir()
        cls.board = cls.boards / cls.SLUG
        (root / '.threads-config' / cls.SLUG).mkdir(parents=True)     # the owner's installation speaks Hebrew (these tests' words)
        (root / '.threads-config' / cls.SLUG / 'config.json').write_text(json.dumps({'lang': 'he'}), encoding='utf-8')
        cls.environ = dict(os.environ)
        for key in UNSET + ('TUIOS_PANE_ID',):
            os.environ.pop(key, None)
        # the hook runs with the server's environment: the temp board, a fake HOME, and nobody is told anything
        os.environ.update(BOARDS_DIR=str(cls.boards), TZ='UTC', HOME=str(root / 'home'), THREADS_BOARDLIB_DIR=str(test_e2e.SKILL), THREADS_NOTIFY='0')
        cls.env = dict(os.environ, THREADS_SLUG=cls.SLUG)
        cls.server = None
        test_e2e.Suda.start_server.__func__(cls)                # answer_server on 127.0.0.1 and a free port, over cls.boards
        assert cls.server.server_address[0] == '127.0.0.1'
        r = cls.cli('install')
        assert r.returncode == 0, r.stderr
        assert (cls.board / 'on-state.sh').is_file()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()
        os.environ.clear()
        os.environ.update(cls.environ)
        cls.tmp.cleanup()

    @classmethod
    def cli(cls, *args):
        assert cls.env['BOARDS_DIR'] == str(cls.boards) and cls.env['THREADS_NOTIFY'] == '0'
        return subprocess.run([sys.executable, str(CLI), *args], env=cls.env, capture_output=True, text=True)

    def send(self, state, raw=None):
        """POST one page action as the page does. (status, the server's answer, the receipt); status 0 and None
        when the server closed the line without answering."""
        body = raw if raw is not None else json.dumps({'board': self.SLUG, 'state': state}).encode()
        line = http.client.HTTPConnection('127.0.0.1', self.port, timeout=60)
        try:
            line.request('POST', '/api/state', body=body, headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:%d' % self.port})   # (as the page: a browser always names its origin)
            answer = line.getresponse()
            text = answer.read().decode('utf-8', 'replace')
        except (http.client.HTTPException, OSError):
            return 0, None, {}
        finally:
            line.close()
        try:
            result = json.loads(text)
        except ValueError:
            return answer.status, None, {}
        out = result.get('out') if isinstance(result, dict) else None
        out = out if isinstance(out, list) else str(out or '').strip().split('\n')
        try:
            receipt = json.loads(out[-1]) or {}
        except (ValueError, IndexError):
            receipt = {}
        return answer.status, result, receipt

    def fault(self, status, result, receipt):
        """The page's own postFault(), run under node on what the server answered."""
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = (ROOT / 'suda.html').read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\n" + pure + '\nconst [status,result,receipt]=JSON.parse(process.argv[1]);'
                            'process.stdout.write(JSON.stringify(postFault(status,result,receipt)));', json.dumps([status, result, receipt])],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def new(self, tid):
        r = self.cli('new', tid, 'נושא ' + tid)
        self.assertEqual(r.returncode, 0, r.stderr)

    def messages(self, tid):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))['threads'][tid]['messages']

    def test_held_what_the_hook_prints_reaches_the_page_as_it_should_read_it(self):
        self.new('wire')
        reply = {'op': 'reply', 'thread': 'wire', 'text': 'שלום', 'cid': 'w1'}
        status, result, receipt = self.send(reply)
        self.assertEqual((status, result['ok'], result['applied'], receipt), (200, True, True, {'ok': True, 'thread': 'wire', 'msg_id': 'm1', 'dup': False}))
        self.assertEqual(self.fault(status, result, receipt), '')
        self.assertEqual(self.cli('close', 'wire').returncode, 0)
        # the same message again, after the thread was closed: taken, as the first time
        status, result, receipt = self.send(reply)
        self.assertEqual((status, receipt), (200, {'ok': True, 'thread': 'wire', 'msg_id': 'm1', 'dup': True}))
        self.assertEqual(self.fault(status, result, receipt), '')
        # another message into the closed thread: refused, his to send again
        status, result, receipt = self.send({**reply, 'cid': 'w2'})
        self.assertEqual((status, result['ok'], receipt), (200, False, {'ok': False, 'error': 'השרשור סגור'}))
        self.assertEqual(self.fault(status, result, receipt), 'no')
        # the state cannot be read just now: the page tries again by itself, and the next try is stored once
        self.assertEqual(self.cli('reopen', 'wire').returncode, 0)
        unreadable(self.board, 0)
        try:
            status, result, receipt = self.send({**reply, 'cid': 'w3'})
        finally:
            unreadable(self.board, 0o644)
        self.assertEqual((status, result['ok'], receipt), (200, False, {'ok': False, 'error': GENERIC, 'again': True}))
        self.assertEqual(self.fault(status, result, receipt), 'again')
        status, result, receipt = self.send({**reply, 'cid': 'w3'})
        self.assertEqual(receipt, {'ok': True, 'thread': 'wire', 'msg_id': 'm2', 'dup': False})
        self.assertEqual([m.get('cid') for m in self.messages('wire')], ['w1', 'w3'])

    def half_pair(self, tid, cid, **more):
        """A reply as JSON.stringify writes it when one of its strings ends in half a character pair (what
        `kept.slice(0,EXCERPT_MAX-1)` / `.slice(0,CAPTION_MAX)` leave when the cut falls inside an emoji)."""
        state = {'op': 'reply', 'thread': tid, 'text': 'מילים שלו', 'cid': cid, **more}
        return json.dumps({'board': self.SLUG, 'state': state}).replace('HALF', '\\ud83d').encode()

    def test_a_reply_that_can_never_be_stored_gets_an_answer_and_is_not_sent_for_half_a_day(self):
        """Half a character pair in a reply (a cut that fell inside an emoji). The board server could not write
        such a request down and closed the line without a word: to the page that is "no answer", and it went on
        sending by itself. The board server was mended after this review (its owner, 2026-11-17): it now puts the
        sign for "unknown" where half a pair stood, so the reply gets its answer and is stored once."""
        self.new('pair')
        tries = []
        for _ in range(3):
            status, result, receipt = self.send(None, raw=self.half_pair('pair', 'p1', reply_to='m0', quote='ציטוט שנחתך HALF'))
            tries.append((status, self.fault(status, result, receipt)))
        self.assertNotIn((0, 'again'), tries, 'no answer at all, every time: the page goes on sending by itself')
        self.assertEqual({status for status, _ in tries}, {200}, tries)
        self.assertNotIn('again', {fault for _, fault in tries}, tries)             # an answer every time: stored, or refused with a reason
        stored = [m for m in self.messages('pair') if m.get('cid') == 'p1']
        self.assertLessEqual(len(stored), 1)
        for m in stored:                                                            # what was stored can be written and read again
            json.dumps(m, ensure_ascii=False).encode('utf-8')

    def test_a_request_the_server_dropped_leaves_nothing_of_his_in_the_served_folder(self):
        """The hook empties the stored request when it carries a picture ("as his phone made it"). A request the
        server drops while writing it down never gets there: what was written until then stays in state/ as
        .state-*.json, one more file for every try, and the page now tries again by itself."""
        self.new('left')
        marker = base64.b64encode(png(77)).decode()
        before = {p.name for p in (self.board / 'state').iterdir()} if (self.board / 'state').is_dir() else set()
        for _ in range(3):
            self.send(None, raw=self.half_pair('left', 'l1', images=[{'name': 'a.png', 'type': 'image/png', 'data': marker, 'caption': 'כיתוב שנחתך HALF'}]))
        left = [p for p in (self.board / 'state').iterdir() if p.name not in before and p.name != 'state.json']
        holding = [p.name for p in (self.board / 'state').iterdir() if marker.encode() in p.read_bytes()]
        self.assertEqual(holding, [], 'his picture, as the page sent it, stays in the served folder')
        self.assertEqual([p.name for p in left], [])


class Cut(unittest.TestCase):
    """Where the half pairs of Wire come from: the page's own cutting by length (pure functions, under node)."""

    def test_what_the_page_cuts_by_length_is_still_whole_characters(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = (ROOT / 'suda.html').read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        script = r"""
        const face='\u{1F600}',cut={
          'the excerpt of a reply (excerptOf)':excerptOf('a'.repeat(EXCERPT_MAX-2)+face+' and the words after the cut'),
          'the caption of a picture (captionOf)':captionOf('b'.repeat(CAPTION_MAX-1)+face+' tail'),
          'the stand-in title of a new topic (tempTitle)':tempTitle('c'.repeat(59)+face+face)};
        const broken=Object.keys(cut).filter(name=>!cut[name].isWellFormed());
        if(broken.length){console.error('ends in half a character pair: '+broken.join('; '));process.exit(1);}
        """
        r = subprocess.run([node, '-e', "'use strict';\n" + pure + '\n' + textwrap.dedent(script)], capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])


class Worker(unittest.TestCase):
    """sw.js under node: the rule, the install with every kind of browser, and what the worker still answers."""

    HARNESS = r"""
    'use strict';
    const assert=require('assert'),vm=require('vm'),fs=require('fs');
    const source=fs.readFileSync(process.argv[1],'utf8');
    // One worker, as a browser would run it: `kind` says what the browser's install event can do.
    function boot(scope,kind,served){
      const handlers={},waits=[],routes=[],posted=[],fetched=[],store=new Map();
      let skipped=0,claimed=0;
      const cache={match:async key=>store.has(key)?store.get(key).clone():undefined,put:async(key,value)=>{store.set(key,value);}};
      const self={addEventListener:(name,run)=>{handlers[name]=run;},registration:{scope,showNotification:async()=>{}},skipWaiting:()=>{skipped++;},
        clients:{matchAll:async()=>[{url:scope+'suda.html',postMessage:what=>posted.push(what),focus:async()=>{}}],claim:async()=>{claimed++;},openWindow:async()=>{}}};
      const box={self,URL,Response,console,caches:{open:async()=>cache,keys:async()=>['suda-shell-0','suda-shell-1','other'],delete:async()=>true},
        fetch:async(url,options)=>{fetched.push([String(url),options||{}]);return new Response(served.body,{status:served.status||200});}};
      vm.runInNewContext(source,box);
      const install={waitUntil:p=>waits.push(Promise.resolve(p))};
      if(kind==='rules')install.addRoutes=async rules=>{routes.push(rules);};
      if(kind==='throws')install.addRoutes=rules=>{routes.push(rules);throw new TypeError('no such condition: not');};
      if(kind==='rejects')install.addRoutes=async rules=>{routes.push(rules);throw new TypeError('no such condition: not');};
      if(kind==='nothing')install.addRoutes=rules=>{routes.push(rules);};
      if(kind==='not a function')install.addRoutes=true;
      return {handlers,install,waits,routes,posted,fetched,store,served,get skipped(){return skipped;},get claimed(){return claimed;},
        // one request of a page: what the worker answered with, or null when it let the request go on as it is
        async ask(url,init){
          let answer=null;const later=[];
          // (a request as a browser makes it: its headers too, which the worker reads since it keeps the page, cache30)
        handlers.fetch({request:{url,method:(init&&init.method)||'GET',mode:(init&&init.mode)||'cors',headers:new Headers((init&&init.headers)||{})},respondWith:p=>{answer=p;},waitUntil:p=>later.push(Promise.resolve(p))});
          const got=answer?await answer:null;await Promise.all(later);
          return got?await got.text():null;
        }};
    }
    const fails=[];
    process.on('unhandledRejection',e=>fails.push(e));
    """

    def node(self, script, *args):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        r = subprocess.run([node, '-e', textwrap.dedent(self.HARNESS) + textwrap.dedent(script), str(ROOT / 'sw.js'), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        return r.stdout

    def test_held_the_install_ends_well_in_every_kind_of_browser_and_the_worker_answers_as_before(self):
        self.node(r"""
        (async()=>{
          for(const scope of ['https://suda.example/threads/','http://127.0.0.1:8767/staging/','http://100.64.0.1:8767/a/b/']){
            const path=new URL('suda.html',scope).pathname;
            for(const kind of ['no rules','rules','throws','rejects','nothing','not a function']){
              const w=boot(scope,kind,{body:'<html>build 1</html>'});
              w.handlers.install(w.install);
              const ends=await Promise.allSettled(w.waits);
              assert.ok(ends.every(e=>e.status==='fulfilled'),kind+': the install would fail, and with it the worker');
              assert.strictEqual(w.skipped,1,kind);
              assert.strictEqual(w.waits.length,kind==='no rules'||kind==='not a function'||kind==='throws'?1:2,kind);
              // the rule, when the browser has rules: everything but the page's own file, past the worker
              if(kind!=='no rules'&&kind!=='not a function')assert.deepStrictEqual(JSON.parse(JSON.stringify(w.routes)),[[{condition:{not:{urlPattern:path}},source:'network'}]],kind);
              // the page is kept from the first moment, whatever the browser can do
              assert.deepStrictEqual(w.fetched.map(f=>f[0]),[path],kind);assert.strictEqual(w.fetched[0][1].cache,'no-store');
              assert.strictEqual(await (await w.store.get(path)).clone().text(),'<html>build 1</html>',kind);
              await w.handlers.activate({waitUntil:p=>w.waits.push(p)});await Promise.all(w.waits);
              assert.strictEqual(w.claimed,1,kind);
              // an opening: the kept copy at once, and the server's copy read behind it; another build is told to the pages
              w.served.body='<html>build 2</html>';
              assert.strictEqual(await w.ask(scope+'suda.html?s=1#a/m3',{mode:'navigate'}),'<html>build 1</html>',kind);
              assert.strictEqual(JSON.stringify(w.posted),JSON.stringify([{kind:'shell-updated'}]),kind);
              assert.strictEqual(await w.ask(scope+'suda.html',{mode:'navigate'}),'<html>build 2</html>',kind);
              assert.strictEqual(JSON.stringify(w.posted),JSON.stringify([{kind:'shell-updated'}]),kind+': the same build again is no news');
              // the page's own reading of its file (the build check) goes to the server and is kept
              w.served.body='<html>build 3</html>';
              assert.strictEqual(await w.ask(scope+'suda.html'),'<html>build 3</html>',kind);
              assert.strictEqual(await (await w.store.get(path)).clone().text(),'<html>build 3</html>',kind);
              // everything else is let go as it is, also by a browser that asks the worker (no rules)
              const before=w.fetched.length;
              for(const [url,init] of [[scope+'summary.json'],[scope+'state.json?t=1'],[scope+'full/a.json'],[scope+'uploads/a/m1-1.png'],[scope+'sw.js'],[scope+'x/suda.html'],
                [new URL('/api/state',scope).href,{method:'POST'}],[new URL('/events?board=threads',scope).href],[scope+'suda.html',{method:'HEAD'}],[scope+'suda.html',{method:'POST'}],
                ['https://evil.example'+path]])
                assert.strictEqual(await w.ask(url,init),null,kind+' '+url);
              assert.strictEqual(w.fetched.length,before,kind);
              // a server that cannot give the page just now: the kept copy stays
              w.served.status=503;
              assert.strictEqual(await w.ask(scope+'suda.html',{mode:'navigate'}),'<html>build 3</html>',kind);
              assert.strictEqual(await (await w.store.get(path)).clone().text(),'<html>build 3</html>',kind);
            }
          }
          await new Promise(done=>setTimeout(done,50));
          assert.deepStrictEqual(fails,[],'a promise nobody handled');
        })().catch(e=>{console.error(e);process.exit(1);});
        """)

    def test_held_the_rule_leaves_to_the_worker_exactly_what_the_worker_calls_the_page(self):
        """The browser decides by the rule (a URL pattern, read against the worker's own address); the worker
        decides by shellPath(). Wherever the two disagree, an opening would skip the kept copy, or a request would
        wait for the worker after all."""
        out = self.node(r"""
        if(typeof URLPattern==='undefined'){console.log('SKIP');process.exit(0);}
        const pure=source.split('// <pure>')[1].split('// </pure>')[0];
        const {shellPath,pastWorker}=vm.runInNewContext(pure+'\n({shellPath,pastWorker})',{URL});
        for(const scope of ['https://suda.example/threads/','http://127.0.0.1:8767/staging/','http://100.64.0.1:8767/a/b/','http://127.0.0.1:8767/Threads-2/','http://127.0.0.1:8767/a.b_c~d/']){
          const at=new URL(scope),path=new URL('suda.html',scope).pathname,rule=pastWorker(path)[0];
          assert.deepStrictEqual(Object.keys(rule).sort(),['condition','source']);assert.strictEqual(rule.source,'network');
          const own=new URLPattern(rule.condition.not.urlPattern,scope+'sw.js');
          assert.strictEqual(own.hasRegExpGroups,false);
          const other=at.protocol==='https:'?'http:':'https:';
          const urls=[scope+'suda.html',scope+'suda.html?s=1&n=2',scope+'suda.html#a/m1',scope+'suda.html?x#y',scope+'./suda.html',scope+'x/../suda.html',
            at.protocol+'//user:pass@'+at.host+path,scope+'Suda.html',scope+'SUDA.HTML',scope+'suda%2Ehtml',scope+'suda.htm',scope+'suda.html/',scope+'suda.html/x',scope+'x/suda.html',
            scope+'/suda.html',scope.slice(0,-1)+'suda.html',at.origin+'/suda.html',at.origin+'/other'+path,at.origin+path.toUpperCase(),scope+'board.html',scope+'slack.html',scope,
            scope+'sw.js',scope+'manifest.json',scope+'state.json?t=1',scope+'summary.json',scope+'full/a.json',scope+'uploads/a/m1-1.png',scope+'push.json?t=1',scope+'notify.log',
            at.origin+'/api/state',at.origin+'/events?board=threads',other+'//'+at.host+path,at.protocol+'//'+at.hostname+':1'+path,'https://evil.example'+path,
            'https://evil.example/?'+path,at.origin+'/x?'+path,at.origin+'/x#'+path];
          for(const url of urls)assert.strictEqual(own.test(url),shellPath(url,scope)!=='',scope+' and '+url+': the rule says '+own.test(url)+', the worker says "'+shellPath(url,scope)+'"');
          assert.strictEqual(own.test(scope+'suda.html?s=1'),true);assert.strictEqual(own.test(at.origin+'/api/state'),false);
        }
        console.log('OK');
        """)
        if out.strip() == 'SKIP':
            self.skipTest('this node has no URLPattern')
        self.assertEqual(out.strip(), 'OK')


if __name__ == '__main__':
    unittest.main()
