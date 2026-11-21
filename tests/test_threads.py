"""CLI integration tests; all generated artifacts stay inside the repository."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import concurrent.futures
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

ROOT = _paths.APP
CLI = ROOT / 'threads.py'


def base64_url_decode(text):
    import base64
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


# ── tiny videos, built by hand: the CLI reads their structure, not their pictures ──

def mp4_box(kind, payload):
    import struct
    return struct.pack('>I', 8 + len(payload)) + kind + payload


def tiny_mp4(brand=b'isom', handler=b'vide', w=320, h=180, moov_last=True, udta=b'', frames=b'FRAME-ONE|FRAME-TWO', wide=False, extra=b'',
             pad=b'', offset=None, timescale=1000, length=1500):
    """An ISO BMFF file as a camera or ffmpeg writes it: ftyp, mdat, moov (at the end unless asked), one track whose
    chunk offset points at the second frame inside mdat. 1.5 seconds long."""
    import struct
    ftyp = mp4_box(b'ftyp', brand + b'\0\0\2\0' + brand + b'iso2mp41')
    mvhd = mp4_box(b'mvhd', b'\0' * 12 + struct.pack('>II', timescale, length) + b'\0' * 80)
    tkhd = mp4_box(b'tkhd', b'\0' * 76 + struct.pack('>II', w << 16, h << 16))
    hdlr = mp4_box(b'hdlr', b'\0' * 8 + handler + b'\0' * 12 + b'VideoHandler\0')

    def moov(at):
        at = at if offset is None else offset
        stco = mp4_box(b'co64', b'\0' * 4 + struct.pack('>IQ', 1, at)) if wide else mp4_box(b'stco', b'\0' * 4 + struct.pack('>II', 1, at))
        stbl = mp4_box(b'stbl', stco)
        mdia = mp4_box(b'mdia', hdlr + mp4_box(b'minf', stbl))
        trak = mp4_box(b'trak', tkhd + mdia + (mp4_box(b'udta', udta) if udta else b''))
        return mp4_box(b'moov', mvhd + trak + (mp4_box(b'udta', udta) if udta else b'') + extra)
    mdat = mp4_box(b'mdat', frames)
    second = frames.index(b'|') + 1
    ftyp += pad
    if moov_last:
        return ftyp + mdat + moov(len(ftyp) + 8 + second)
    size = len(moov(0))
    return ftyp + moov(len(ftyp) + size + 8 + second) + mdat


def mp4_track(handler):
    """One more track, of another kind (a camera's GPS, a timecode)."""
    import struct
    hdlr = mp4_box(b'hdlr', b'\0' * 8 + handler + b'\0' * 12 + b'Other\0')
    return mp4_box(b'trak', mp4_box(b'tkhd', b'\0' * 76 + struct.pack('>II', 0, 0)) + mp4_box(b'mdia', hdlr))


def ebml(ident, payload):
    size = bytes([0x80 | len(payload)]) if len(payload) < 127 else b'\x01' + len(payload).to_bytes(7, 'big')
    return ident + size + payload


def tiny_webm(doctype=b'webm', track_type=1, w=320, h=180, scale=(1_000_000).to_bytes(3, 'big'), duration=1500.0, title=b'', date=b'', tags=b'',
              unknown_cluster=False):
    """A webm as ffmpeg or a browser writes it. `tags` are written after the frames (as ffmpeg does); with
    `unknown_cluster` the frames have no size (a live recording) and run up to the tags."""
    import struct
    head = ebml(b'\x1a\x45\xdf\xa3', ebml(b'\x42\x82', doctype))
    info = ebml(b'\x15\x49\xa9\x66', ebml(b'\x2a\xd7\xb1', scale) + ebml(b'\x44\x89', struct.pack('>d', duration))
                + (ebml(b'\x7b\xa9', title) if title else b'') + (ebml(b'\x44\x61', date) if date else b''))
    video = ebml(b'\xe0', ebml(b'\xb0', w.to_bytes(2, 'big')) + ebml(b'\xba', h.to_bytes(2, 'big')))
    tracks = ebml(b'\x16\x54\xae\x6b', ebml(b'\xae', ebml(b'\x83', bytes([track_type])) + (video if track_type == 1 else b'')))
    frames = ebml(b'\xe7', b'\x00') + ebml(b'\xa3', b'FRAME-BYTES-HERE')
    cluster = (b'\x1f\x43\xb6\x75\x01\xff\xff\xff\xff\xff\xff\xff' + frames) if unknown_cluster else ebml(b'\x1f\x43\xb6\x75', frames)
    if tags:
        tags = ebml(b'\x12\x54\xc3\x67', ebml(b'\x73\x73', ebml(b'\x67\xc8', ebml(b'\x45\xa3', b'LOCATION') + ebml(b'\x44\x87', tags))))
    return head + ebml(b'\x18\x53\x80\x67', info + tracks + cluster + tags)


def mp4_boxes(raw):
    """The top-level boxes of a file: [(kind, start, end)]."""
    import struct
    out, at = [], 0
    while at < len(raw):
        size, kind = struct.unpack('>I4s', raw[at:at + 8])
        out.append((kind, at, at + size))
        at += size
    return out


class ThreadsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.record = self.root / 'notifications.jsonl'
        recorder = self.root / 'record.py'
        recorder.write_text("import json, os, sys\nfrom pathlib import Path\nwith Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args':sys.argv[1:], 'pane':os.environ.get('TUIOS_PANE_ID'), 'path':os.environ.get('PATH')})+'\\n')\n")
        import shlex
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'),
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]),
                        NOTIFY_RECORD=str(self.record), TUIOS_PANE_ID='must-be-removed')
        self.env.pop('THREADS_NOTIFY', None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (self.root / '.threads-config/threads').mkdir(parents=True)
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')

    def run_cli(self, *args, ok=True, input=None, env=None):
        r = subprocess.run([sys.executable, str(CLI), *args], env=env or self.env,
                           input=input, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def js(self, *args):
        return json.loads(self.run_cli(*args).stdout)

    def test_a_message_saved_in_a_thread_closed_long_ago_stays_in_the_list(self):
        """saved179 meets the store (sqlite177): a thread closed long ago is cold, its row leaves summary.json, but its
        saved messages stay in the list the page shows (summary['saved']) and in `threads saved`; and he can still take
        one out of it."""
        read = lambda name: json.loads((self.board / name).read_text(encoding='utf-8'))
        e = self.at
        self.run_cli('new', 'old', 'נושא ישן', env=e(0))
        self.run_cli('say', 'old', '--from', 'tower', 'רשימת החומרים: הדף, הלוח והקבצים', env=e(0))
        self.run_cli('new', 'now', 'נושא פתוח', env=e(0))
        self.run_cli('say', 'now', '--from', 'fork', 'הודעה פתוחה', env=e(0))
        self.assertTrue(self.post({'op': 'save', 'thread': 'old', 'msg': 'm1', 'on': True}, env=e(1))['ok'])
        self.run_cli('close', 'old', env=e(2))
        later = e(2 + 24 * 9)                         # more than HOT_DAYS (7) after it was closed
        self.run_cli('say', 'now', '--from', 'fork', 'עוד הודעה', env=later)      # a write: the summary is made again
        summary = read('summary.json')
        self.assertNotIn('old', summary['threads'], 'closed long ago: its row is no longer in the summary')
        self.assertEqual([(r['thread'], r['msg']) for r in summary['saved']], [('old', 'm1')])
        self.assertTrue(summary['saved'][0]['text'].startswith('רשימת החומרים'))
        self.assertEqual([(r['thread'], r['msg']) for r in self.js('saved', '--json')], [('old', 'm1')])
        # saved in an open thread too: both, the last saved first
        self.assertTrue(self.post({'op': 'save', 'thread': 'now', 'msg': 'm1', 'on': True}, env=later)['ok'])
        self.assertEqual([r['thread'] for r in read('summary.json')['saved']], ['now', 'old'])
        # taken out of the cold thread: gone from the list
        self.assertTrue(self.post({'op': 'save', 'thread': 'old', 'msg': 'm1', 'on': False}, env=later)['ok'])
        self.assertEqual([r['thread'] for r in read('summary.json')['saved']], ['now'])
        self.assertEqual([r['thread'] for r in self.js('saved', '--json')], ['now'])

    def test_he_saves_a_message_and_finds_it_again_in_any_thread(self):
        """suda m787 (suda-fixes 77): a message he saves from the page stays saved in an open, closed or merged thread;
        the summary's stamp of a saved message carries when and the start of its words; `threads saved` lists them."""
        read = lambda name: json.loads((self.board / name).read_text(encoding='utf-8'))
        self.new('a')
        self.new('b')
        for i in range(1, 9):
            self.run_cli('say', 'a', '--from', 'fork', f'רשימת החומרים {i}: ' + 'מילה ' * 60)
        self.run_cli('say', 'b', '--from', 'fork', 'הודעה לשמור')
        got = self.post({'op': 'save', 'thread': 'a', 'msg': 'm2', 'on': True})
        self.assertTrue(got['ok'])
        self.assertTrue(isinstance(self.thread('a')['messages'][1].get('saved'), float))
        self.post({'op': 'save', 'thread': 'a', 'msg': 'm2', 'on': True})            # again: nothing changes
        self.post({'op': 'save', 'thread': 'b', 'msg': 'm1', 'on': True})
        # the stamp of a saved message: when it was saved, and the start of its words (an old one is left as it was)
        stamps = {s[0]: s for s in read('summary.json')['threads']['a']['stamps']}
        self.assertEqual(len(stamps['m1']), 4)
        self.assertEqual(len(stamps['m2']), 6)
        self.assertTrue(stamps['m2'][5].startswith('רשימת החומרים 2'))
        self.assertLessEqual(len(stamps['m2'][5]), 161)
        # closed, it stays saved, and can still be taken out
        self.run_cli('close', 'b')
        self.assertEqual([r['msg'] for r in self.js('saved', '--json') if r['thread'] == 'b'], ['m1'])
        rows = self.js('saved', '--json')
        self.assertEqual([(r['thread'], r['msg']) for r in rows], [('b', 'm1'), ('a', 'm2')], 'the last saved first')
        self.post({'op': 'save', 'thread': 'b', 'msg': 'm1', 'on': False})
        self.assertNotIn('saved', self.thread('b')['messages'][0])
        self.assertEqual([r['thread'] for r in self.js('saved', '--json')], ['a'])
        self.assertIn('m2', self.run_cli('saved').stdout)
        # a page that asks wrong is refused, and nothing is written
        for bad in ({'op': 'save', 'thread': 'a', 'msg': 'm2'}, {'op': 'save', 'thread': 'a', 'msg': 'm2', 'on': 1},
                    {'op': 'save', 'thread': 'a', 'msg': 'm99', 'on': True}):
            self.post(bad, ok=False)
        self.assertIn('save', read('state.json')['ops'])

    def test_a_summary_and_each_threads_conversation_are_written_beside_the_state(self):
        """The owner approved the speed plan (thread suda m317): a page opens from a small summary instead of every
        conversation. Beside state.json (which stays whole) each save writes summary.json (the state without the
        conversations: every message as a stamp, the last few of an open thread whole) and full/<id>.json."""
        read = lambda name: json.loads((self.board / name).read_text(encoding='utf-8'))
        self.new('a')
        self.new('b')
        for i in range(1, 7):
            self.run_cli('say', 'a', '--from', 'fork', f'הודעה {i}')
        self.run_cli('say', 'b', '--from', 'fork', 'אחת')
        state, summary, full = read('state.json'), read('summary.json'), read('full/a.json')
        # the summary is the state without the conversations (and the mark of its content, which the state never has)
        self.assertEqual(summary['lite'], 1)
        self.assertRegex(summary['mark'], r'^[0-9a-f]{8}$')
        self.assertEqual({k: v for k, v in summary.items() if k not in ('threads', 'lite', 'mark', 'cold')}, {k: v for k, v in state.items() if k != 'threads'})
        a = summary['threads']['a']
        # (trev: the mark of its tasks' events, which only the thread's file carries; suda-fixes task 34)
        self.assertEqual({k: v for k, v in a.items() if k not in ('messages', 'stamps', 'rev', 'trev')}, {k: v for k, v in state['threads']['a'].items() if k != 'messages'})
        # every message is there as a stamp [id, sender, time, mark]; only the last four are whole, each with its mark
        self.assertEqual([[s[0], s[1], s[2]] for s in a['stamps']], [[m['id'], m['from'], m['ts']] for m in state['threads']['a']['messages']])
        self.assertTrue(all(isinstance(s[3], str) and len(s[3]) == 8 for s in a['stamps']), a['stamps'])
        self.assertEqual([m['id'] for m in a['messages']], ['m3', 'm4', 'm5', 'm6'])
        marks = {s[0]: s[3] for s in a['stamps']}
        for m in a['messages']:
            self.assertEqual(m['v'], marks[m['id']])
            self.assertEqual({k: v for k, v in m.items() if k != 'v'}, next(x for x in state['threads']['a']['messages'] if x['id'] == m['id']))
        # the thread's own file: its whole conversation, with the same marks, under the summary's mark of the thread
        self.assertEqual((full['id'], full['rev']), ('a', a['rev']))
        self.assertEqual([{k: v for k, v in m.items() if k != 'v'} for m in full['messages']], state['threads']['a']['messages'])
        self.assertEqual([m['v'] for m in full['messages']], [s[3] for s in a['stamps']])
        # the state itself is as it was: no marks in it
        self.assertNotIn('lite', state)
        self.assertFalse(any('v' in m for t in state['threads'].values() for m in t['messages']))
        # only a conversation that changed is written again
        stamp = lambda name: (self.board / 'full' / name).stat().st_mtime_ns
        before = {name: stamp(name) for name in ('a.json', 'b.json')}
        time.sleep(0.05)
        self.run_cli('say', 'b', '--from', 'fork', 'שתיים')
        self.assertEqual(stamp('a.json'), before['a.json'])
        self.assertNotEqual(stamp('b.json'), before['b.json'])
        # a message that changes gets another mark, and no other message does
        self.run_cli('say', 'a', '--from', 'owner', 'תשובה שלי')
        was = {s[0]: s[3] for s in read('summary.json')['threads']['a']['stamps']}
        self.run_cli('ack', 'a', 'm7')
        now = {s[0]: s[3] for s in read('summary.json')['threads']['a']['stamps']}
        self.assertEqual([mid for mid in now if now[mid] != was[mid]], ['m7'])
        self.assertNotEqual(read('summary.json')['threads']['a']['rev'], a['rev'])
        self.assertEqual(read('full/a.json')['messages'][-1]['v'], now['m7'])
        # a closed thread is in the summary without whole messages; its stamps and its file stay
        self.run_cli('close', 'b')
        b = read('summary.json')['threads']['b']
        self.assertEqual((b['messages'], len(b['stamps']), len(read('full/b.json')['messages'])), ([], 2, 2))
        # a thread that is removed takes its file with it
        self.run_cli('rm', 'b', '--yes')
        self.assertFalse((self.board / 'full/b.json').exists())
        self.assertNotIn('b', read('summary.json')['threads'])
        # install gives these files to a board from before them; the state changes by its number only (the number is
        # in the state, the summary and the pulse alike: else an older writer saves the summary under the old one)
        import shutil
        (self.board / 'summary.json').unlink()
        shutil.rmtree(self.board / 'full')
        before = read('state.json')
        self.run_cli('install')
        after = read('state.json')
        self.assertEqual({k: v for k, v in after.items() if k != 'seq'}, {k: v for k, v in before.items() if k != 'seq'})
        self.assertGreater(after['seq'], before['seq'])
        self.assertEqual((after['seq'], read('summary.json')['seq']), (int((self.board / '.pulse').read_text()), after['seq']))
        self.assertEqual(read('summary.json')['threads']['a']['rev'], read('full/a.json')['rev'])
        # they are derived: when they cannot be written the command still succeeds, the state is saved, and the summary
        # is taken away so that a page reads state.json as it always did
        shutil.rmtree(self.board / 'full')
        (self.board / 'full').write_text('not a folder')
        self.run_cli('say', 'a', '--from', 'fork', 'אחרי תקלה')
        self.assertEqual(read('state.json')['threads']['a']['messages'][-1]['text'], 'אחרי תקלה')
        self.assertFalse((self.board / 'summary.json').exists())
        self.assertIn('lite', (self.board / 'notify.log').read_text(encoding='utf-8'))
        # and they come back with the next save once they can be written
        (self.board / 'full').unlink()
        self.run_cli('say', 'a', '--from', 'fork', 'אחרי התיקון')
        self.assertEqual(read('summary.json')['threads']['a']['stamps'][-1][0], read('full/a.json')['messages'][-1]['id'])

    def new(self, tid='topic'):
        self.run_cli('new', tid, 'כותרת ' + tid, '--context', 'רקע')

    def ingest(self, tid='topic', text='שלום\nעולם', cid='client-1', ok=True, env=None):
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'op':'reply', 'thread':tid, 'text':text, 'cid':cid}))
        r = self.run_cli('ingest', ok=ok, env=env)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertEqual(r.stderr, '')
        return json.loads(r.stdout)

    T0 = 1_800_000_000.0

    def at(self, hours):
        """Environment whose CLI clock stands `hours` after T0."""
        return dict(self.env, THREADS_NOW=str(self.T0 + hours*3600))

    def thread(self, tid='topic', env=None):
        return json.loads(self.run_cli('show', tid, '--json', env=env).stdout)

    def post(self, payload, ok=True, env=None):
        """What the page does: the server stores the body, then runs the hook."""
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        r = self.run_cli('ingest', ok=ok, env=env)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        return json.loads(r.stdout)

    def test_the_secure_address_is_configuration_not_code(self):
        """A public repo carries no address of its own (suda m567): the pages ship with none, and `threads install`
        writes this installation's (THREADS_SECURE_HOME, else secure_home in the private config.json)."""
        self.assertIn("const SECURE_HOME='';", (ROOT / 'suda.html').read_text(encoding='utf-8'))
        self.run_cli('install')
        self.assertIn("const SECURE_HOME='';", (self.board / 'suda.html').read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli('url', 'topic').stdout.strip(), 'http://127.0.0.1:8767/threads/suda.html#topic')
        config = self.root / '.threads-config/threads'
        config.mkdir(parents=True, exist_ok=True)       # (install made it: the push key lives there)
        (config / 'config.json').write_text('{"lang": "he", "secure_home": "https://suda.example.com"}')
        self.run_cli('install')
        self.assertIn('const SECURE_HOME="https://suda.example.com";', (self.board / 'suda.html').read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli('url').stdout.strip(), 'https://suda.example.com/threads/suda.html')
        for bad in ('http://x.example', 'https://x.example/path', 'https://x.example";alert(1)//', 'javascript:1'):
            with self.subTest(bad=bad):
                self.run_cli('install', ok=False, env=dict(self.env, THREADS_SECURE_HOME=bad))
                self.run_cli('url', ok=False, env=dict(self.env, THREADS_SECURE_HOME=bad))
        self.run_cli('url', '../x', ok=False)

    # ── the owner's id: 'owner' everywhere, his other names only from the installation's config ─────────────

    def configure(self, **settings):
        """This installation's private config.json (beside the test boards, never in the served folder)."""
        private = self.root / '.threads-config/threads'
        private.mkdir(parents=True, exist_ok=True)
        (private / 'config.json').write_text(json.dumps({'lang': 'he', **settings}, ensure_ascii=False), encoding='utf-8')
        return private

    def test_without_config_only_owner_human_and_me_name_him(self):
        """The public code names nobody: an id that only some installation used for him is an ordinary name here."""
        self.new()
        for args in (('say', 'topic', '--from', 'dana', 'x'), ('state', 'topic', 'on-dana', '--note', 'n'),
                     ('new', 'other', 'T', '--state', 'on-dana', '--note', 'n'), ('task', 'add', 'topic', 'x', '--owner', 'x'),
                     ('task', 'set', 'topic', '1', 'on-dana')):
            with self.subTest(args=args):
                r = self.run_cli(*args, ok=args[0] == 'task' and args[1] == 'add')
                self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'Me', 'שלום').stdout.strip(), 'm1')
        self.assertEqual(self.thread()['messages'][0]['from'], 'owner')
        self.run_cli('state', 'topic', 'on-human', '--note', 'לבחור')
        self.assertEqual(self.thread()['state'], 'on-owner')
        self.run_cli('task', 'add', 'topic', 'שלו', '--owner', 'HUMAN')
        self.run_cli('task', 'add', 'topic', 'של מישהו', '--owner', 'dana')
        self.assertEqual([k['owner'] for k in self.thread()['tasks']], ['x', 'owner', 'dana'])
        r = self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'on-dana'}, ok=False)
        self.assertFalse(r['ok'])
        self.assertTrue(self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'on-me'})['ok'])
        self.assertEqual((self.thread()['tasks'][0]['status'], self.thread()['tasks'][0]['by']), ('on-owner', 'owner'))
        for by in ('owner', 'Owner', 'me', 'auto'):
            with self.subTest(by=by):
                self.run_cli('close', 'topic', '--by', by, ok=False)
                self.run_cli('react', 'topic', 'm1', '✅', '--by', by, ok=False)
        self.run_cli('react', 'topic', 'm1', '✅', '--by', 'dana')        # not his name on this installation

    def test_the_installation_names_his_other_ids(self):
        """config.json "owner_aliases": running agents keep typing the id they know, and an older page keeps sending
        the old status of his tasks. Every input stores 'owner' / 'on-owner'; an agent still cannot write as him."""
        self.configure(owner_aliases=['dana', 'דנה', 'tower', 7], owner_name='דנה')
        self.new()
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'dana', 'שלום').stdout.strip(), 'm1')
        self.run_cli('say', 'topic', '--from', 'tower', 'מה תרצה?', '--state', 'on-dana', '--note', 'לענות')
        t = self.thread()
        self.assertEqual([m['from'] for m in t['messages']], ['owner', 'tower'])      # an alias that is an agent's name is ignored
        self.assertEqual((t['state'], t['state_by']), ('on-owner', 'tower'))
        self.run_cli('state', 'topic', 'on-דנה', '--note', 'לבחור', '--by', 'Dana')
        self.assertEqual((self.thread()['state'], self.thread()['state_by']), ('on-owner', 'owner'))
        self.run_cli('new', 'other', 'אחר', '--state', 'ON-DANA', '--note', 'n')
        self.assertEqual(self.thread('other')['state'], 'on-owner')
        self.run_cli('task', 'add', 'topic', 'שלו', '--owner', 'דנה')
        self.run_cli('task', 'add', 'topic', 'של סוכן', '--owner', 'fork-a')
        self.run_cli('task', 'set', 'topic', '2', 'on-dana', '--owner', 'Dana')
        self.assertEqual([(k['owner'], k['status']) for k in self.thread()['tasks']], [('owner', 'todo'), ('owner', 'on-owner')])
        self.assertTrue(self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'on-dana'})['ok'])      # an older page
        self.assertEqual(self.thread()['tasks'][0]['status'], 'on-owner')
        for args in (('react', 'topic', 'm1', '✅', '--by', 'dana'), ('react', 'topic', 'm1', '✅', '--by', 'דנה\u200f'),
                     ('close', 'topic', '--by', 'Dana'), ('merge', 'other', '--into', 'topic', '--by', 'dana'),
                     ('task', 'set', 'topic', '1', '--text', 'x', '--by', 'dana')):
            with self.subTest(args=args):
                r = self.run_cli(*args, ok=False)
                self.assertIn('--by', r.stderr)
        # the CLI's own words name him as the installation does
        r = self.run_cli('ack', 'topic', 'm2', ok=False)
        self.assertIn('דנה', r.stderr)
        self.assertNotIn('דנה', json.dumps(self.thread()['tasks']))         # stored as ids, never as his name

    def test_an_old_state_is_migrated_once_with_a_private_backup(self):
        """Version 3: the id that an installation used for him is replaced in every field that holds a person's id,
        and nowhere else (the words of a message, a title, a note keep it). The file as it was is kept in the private
        folder (never beside the state, which is served), the derived files follow, and a second load does nothing."""
        private = self.configure(owner_aliases=['dana'])
        said = 'dana wrote this; on-dana too'
        mark = {'by': 'dana', 'ts': 5.0}
        live = {
            'id': 'live', 'title': 'dana title', 'context': said, 'status': 'open', 'created': 1.0, 'updated': 9.0, 'next': 5,
            'summary': said, 'links': [{'label': 'dana', 'url': 'https://example.com/dana'}], 'slot': 1,
            'state': 'on-dana', 'note': said, 'state_ts': 9.0, 'state_by': 'dana', 'auto': False, 'opened_by': 'dana',
            'split_from': {'thread': 'old', 'msg': 'm1', 'from': 'dana', 'ts': 1.0, 'text': said},
            'messages': [
                {'id': 'm1', 'from': 'dana', 'text': said, 'ts': 2.0, 'status': 'acked', 'reactions': {'👍': mark, '✅': True}},
                {'id': 'm2', 'from': 'fork', 'text': said, 'ts': 3.0, 'reply_to': {'id': 'm1', 'from': 'dana', 'text': said},
                 'reactions': {'❓': {'by': 'fork', 'ts': 4.0}}},
                {'id': 'm3', 'from': 'system', 'text': said, 'ts': 4.0,
                 'merge': {'thread': 'old', 'title': said, 'messages': 1, 'first': 1.0, 'last': 1.0, 'tasks': [], 'by': 'dana'}},
                {'id': 'm4', 'from': 'fork', 'text': said, 'ts': 5.0, 'q': True, 'options': ['dana', 'on-dana']}],
            'question': {'id': 'm4', 'text': said, 'options': ['dana', 'on-dana'], 'from': 'dana', 'ts': 5.0},
            'questions': [{'id': 'm4', 'text': said, 'options': ['dana', 'on-dana'], 'from': 'dana', 'ts': 5.0}],
            'tasks': [{'n': 1, 'text': said, 'status': 'on-dana', 'owner': 'dana', 'by': 'dana', 'note': said, 'from': None,
                       'ts': 1.0, 'updated': 2.0, 'history': [{'text': 'dana', 'ts': 1.5, 'by': 'dana'}]},
                      {'n': 2, 'text': 'x', 'status': 'working', 'owner': 'me', 'note': '', 'from': None, 'ts': 1.0, 'updated': 2.0}]}
        closed = {'id': 'old', 'title': 'old', 'context': '', 'status': 'closed', 'created': 1.0, 'updated': 2.0, 'next': 2,
                  'messages': [{'id': 'm1', 'from': 'dana', 'text': 'dana', 'ts': 1.0, 'status': 'acked'}], 'links': [], 'tasks': [],
                  'slot': None, 'state': 'done', 'note': '', 'state_ts': 2.0, 'state_by': 'dana', 'closed_ts': 2.0, 'closed_by': 'dana'}
        self.board.mkdir(parents=True)
        raw = json.dumps({'version': 2, 'threads': {'live': live, 'old': closed}}, ensure_ascii=False, indent=2) + '\n'
        (self.board / 'state.json').write_text(raw, encoding='utf-8')
        self.run_cli('list')
        state = json.loads((self.board / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['version'], 3)
        t, old = state['threads']['live'], state['threads']['old']
        self.assertEqual((t['state'], t['state_by'], t['opened_by'], t['split_from']['from']), ('on-owner', 'owner', 'owner', 'owner'))
        self.assertEqual((old['state_by'], old['closed_by'], old['messages'][0]['from']), ('owner', 'owner', 'owner'))
        m = {x['id']: x for x in t['messages']}
        self.assertEqual((m['m1']['from'], m['m1']['reactions'], m['m2']['reply_to']['from'], m['m2']['reactions']['❓']['by'], m['m3']['merge']['by']),
                         ('owner', {'👍': {'by': 'owner', 'ts': 5.0}, '✅': True}, 'owner', 'fork', 'owner'))
        self.assertEqual((t['question']['from'], t['questions'][0]['from']), ('owner', 'owner'))
        k1, k2 = t['tasks']
        self.assertEqual((k1['status'], k1['owner'], k1['by'], k1['history'][0]['by'], k2['owner']), ('on-owner', 'owner', 'owner', 'owner', 'owner'))
        # free text is never touched: every word the state held is still there
        self.assertEqual((t['title'], t['context'], t['summary'], t['note'], t['links'][0]['label'], t['split_from']['text']),
                         ('dana title', said, said, said, 'dana', said))
        self.assertEqual({x['text'] for x in t['messages']} | {k1['text'], k1['note'], m['m2']['reply_to']['text'], m['m3']['merge']['title']}, {said})
        self.assertEqual((m['m4']['options'], t['question']['options'], t['question']['text'], k1['history'][0]['text']), (['dana', 'on-dana'], ['dana', 'on-dana'], said, 'dana'))
        # nothing else says the old id as an id: a whole value 'dana' / 'on-dana' is left only where it is text
        def ids(value, key=None):
            if isinstance(value, dict):
                return [x for k, v in value.items() for x in ids(v, k)]
            if isinstance(value, list):
                return [x for v in value for x in ids(v, key)]
            return [key] if value in ('dana', 'on-dana') else []
        self.assertEqual(sorted(set(ids(state))), ['label', 'options', 'text'])
        # the derived files say the same
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['threads']['live']['state'], 'on-owner')      # ('old' closed long ago: cold, in closed.json, sqlite177)
        self.assertIn('old', [r.get('id') for r in json.loads((self.board / 'closed.json').read_text(encoding='utf-8'))['threads']])
        self.assertEqual(json.loads((self.board / 'full/old.json').read_text(encoding='utf-8'))['messages'][0]['from'], 'owner')
        # the backup: the bytes as they were, private, and only there
        backups = list((private / 'backups').glob('state.json.v2-*'))
        self.assertEqual([b.read_text(encoding='utf-8') for b in backups], [raw])
        self.assertEqual((backups[0].stat().st_mode & 0o777, backups[0].parent.stat().st_mode & 0o777), (0o600, 0o700))
        self.assertEqual(sorted(p.name for p in self.board.iterdir() if p.name.startswith('state.json')), ['state.json'])
        # a second load changes nothing and keeps no second copy
        def stored():       # (what is told to him is the notifier's, and moves with the clock)
            data = json.loads((self.board / 'state.json').read_text(encoding='utf-8'))
            for x in data['threads'].values():
                x.pop('alert', None)
            return data
        after = stored()
        self.run_cli('list')
        self.run_cli('show', 'live')
        self.assertEqual(stored(), after)
        self.assertEqual(len(list((private / 'backups').iterdir())), 1)
        self.assertEqual(self.js('pending'), [])

    def test_an_old_state_without_config_still_loads(self):
        """No owner_aliases: the old id is left as it was (some agent's name, as far as this code knows) and nothing breaks;
        'human' and 'me' are his everywhere."""
        old = {'id': 'topic', 'title': 'T', 'context': '', 'status': 'open', 'created': 1.0, 'updated': 3.0, 'next': 3,
               'links': [], 'slot': 1, 'state': 'on-dana', 'note': 'n', 'state_ts': 3.0, 'state_by': 'me', 'auto': True,
               'messages': [{'id': 'm1', 'from': 'dana', 'text': 'x', 'ts': 2.0, 'status': 'pending'},
                            {'id': 'm2', 'from': 'fork', 'text': 'y', 'ts': 3.0}],
               'tasks': [{'n': 1, 'text': 'x', 'status': 'on-dana', 'owner': 'dana', 'note': '', 'from': None, 'ts': 1.0, 'updated': 1.0}]}
        self.board.mkdir(parents=True)
        (self.board / 'state.json').write_text(json.dumps({'version': 2, 'threads': {'topic': old}}), encoding='utf-8')
        for args in (('list',), ('pending',), ('show', 'topic'), ('tasks', 'topic'), ('say', 'topic', '--from', 'fork', 'z')):
            with self.subTest(args=args):
                r = self.run_cli(*args)
                self.assertNotIn('Traceback', r.stderr)
        t = self.thread()
        self.assertEqual((t['messages'][0]['from'], t['tasks'][0]['owner'], t['tasks'][0]['status']), ('dana', 'dana', 'on-dana'))
        backups = list((self.root / '.threads-config/threads/backups').glob('state.json.v2-*'))
        self.assertEqual(len(backups), 1)
        # the alias configured after the upgrade still takes: the next load mends the file (one backup was enough)
        self.configure(owner_aliases=['dana'])
        self.run_cli('list')
        t = json.loads((self.board / 'state.json').read_text(encoding='utf-8'))['threads']['topic']
        self.assertEqual((t['messages'][0]['from'], t['tasks'][0]['owner'], t['tasks'][0]['status']), ('owner', 'owner', 'on-owner'))
        self.assertEqual(json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))['threads']['topic']['stamps'][0][1], 'owner')
        self.assertEqual(list((self.root / '.threads-config/threads/backups').iterdir()), backups)
        self.assertEqual(self.js('pending')[0]['msg_id'], 'm1')        # his message, picked up as his

    def test_install_writes_how_the_pages_name_him(self):
        """The pages ship naming him "Me"; `threads install` writes it in the installation's language ("אני" here),
        or the installation's owner_name, as JSON that cannot leave the script."""
        self.assertEqual((ROOT / 'suda.html').read_text(encoding='utf-8').count("const OWNER_NAME='Me';"), 1)
        self.run_cli('install')
        self.assertIn("const OWNER_NAME='אני';", (self.board / 'suda.html').read_text(encoding='utf-8'))
        self.configure(owner_name='  דנה </script><b>"x"  ')
        self.run_cli('install')
        for page in ('suda.html',):
            text = (self.board / page).read_text(encoding='utf-8')
            self.assertIn('const OWNER_NAME="\\u05d3\\u05e0\\u05d4 \\u003c/script>\\u003cb>\\"x\\"";', text, page)
            self.assertNotIn("const OWNER_NAME='אני';", text)
            self.assertEqual(text.count('</script>'), (ROOT / page).read_text(encoding='utf-8').count('</script>'))
        self.configure(owner_name=['not', 'a', 'name'])
        self.run_cli('install')
        self.assertIn("const OWNER_NAME='אני';", (self.board / 'suda.html').read_text(encoding='utf-8'))

    def test_lifecycle_and_sorting(self):
        self.new()
        self.new('second')
        self.assertEqual(self.js('list', '--json')[0]['id'], 'topic')   # slot order, not last activity
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'tower', 'intro', ok=True).stdout.strip(), 'm1')
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'fork', '-', input='**שלום**\ncode').stdout.strip(), 'm2')
        self.run_cli('close', 'topic')
        warning = self.run_cli('say', 'topic', '--from', 'owner', 'reply')
        self.assertTrue(warning.stderr)
        rows = self.js('list', '--json')
        self.assertEqual([t['id'] for t in rows], ['second', 'topic'])
        self.assertEqual(len(self.js('list', '--open', '--json')), 1)
        human = self.run_cli('list').stdout
        self.assertIn('topic\tclosed\t3\t1', human)
        t = self.js('show', 'topic', '--json')
        self.assertEqual(t['next'], 4)
        self.assertEqual(t['messages'][1]['text'], '**שלום**\ncode')
        self.assertIn('**שלום**', self.run_cli('show', 'topic').stdout)
        self.run_cli('reopen', 'topic')
        self.assertEqual(self.js('show', 'topic', '--json')['status'], 'open')
        self.run_cli('rm', 'topic', ok=False)
        self.run_cli('rm', 'topic', '--yes')
        self.run_cli('show', 'topic', ok=False)
        self.assertEqual(len(self.js('list', '--json')), 1)

    def test_say_rejects_empty_and_reads_stdin(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'tower', '   ', ok=False)
        self.run_cli('say', 'topic', '--from', 'fork', '-', input='', ok=False)
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'fork', '-', input='שורה\n`x`').stdout.strip(), 'm1')
        self.assertEqual(self.js('show', 'topic', '--json')['messages'][0]['text'], 'שורה\n`x`')

    def test_ids(self):
        for tid in ('Bad', '-bad', '../bad', '', 'a'*49, 'a_b', 'a\n'):
            with self.subTest(tid=tid):
                self.run_cli('new', tid, 'title', ok=False)
        self.new('a'*48)
        self.new('0-good')
        self.run_cli('new', '0-good', 'duplicate', ok=False)

    def test_pending_history_ack(self):
        self.new()
        self.new('other')
        self.run_cli('say', 'topic', '--from', 'tower', 'intro')
        self.run_cli('say', 'topic', '--from', 'owner', 'first')
        self.run_cli('say', 'other', '--from', 'owner', 'second')
        self.run_cli('say', 'topic', '--from', 'fork', 'later')
        pending = self.js('pending')
        self.assertEqual([m['text'] for m in pending], ['first', 'second'])
        self.assertEqual(pending[0]['context'], 'רקע')
        self.assertEqual(len(pending[0]['history']), 1)
        self.assertEqual(set(pending[0]['history'][0]), {'id','from','text','ts'})
        self.run_cli('ack', 'topic', 'm1', ok=False)
        self.run_cli('ack', 'topic', 'm99', ok=False)
        self.run_cli('ack', 'topic', 'm2')
        first = self.js('show', 'topic', '--json')['messages'][1]
        self.run_cli('ack', 'topic', 'm2')
        self.assertEqual(first, self.js('show', 'topic', '--json')['messages'][1])
        self.assertEqual(len(self.js('pending')), 1)

    def test_ingest_dedupe_and_notification(self):
        self.new()
        started = time.monotonic()
        result = self.ingest()
        self.assertLess(time.monotonic()-started, 1)
        self.assertEqual(result, {'ok':True,'thread':'topic','msg_id':'m1','dup':False})
        self.assertTrue(self.ingest()['dup'])
        self.assertEqual(len(self.js('pending')), 1)
        records = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['args'], ['[threads] reply in topic (m1): run: threads pending'])
        self.assertIsNone(records[0]['pane'])
        self.assertIn('/opt/homebrew/bin', records[0]['path'].split(os.pathsep))
        self.run_cli('close', 'topic')
        # a message that is already here is answered as it was the first time, also after the thread was closed:
        # the page sends again when it heard no answer, and must not be told "not sent" about a stored message
        self.assertEqual(self.ingest(), {'ok':True,'thread':'topic','msg_id':'m1','dup':True})
        closed = self.ingest(cid='new', ok=False)
        self.assertEqual((closed['ok'], closed['error']), (False, 'השרשור סגור'))
        self.assertNotIn('again', closed)                   # a refusal: the page does not send it again by itself
        self.assertEqual(len(self.js('pending')), 1)

    def test_a_reply_the_server_could_not_store_just_now_says_that_another_try_may_do(self):
        """The owner, thread suda m332: a message that did not get through must go again without his press. The page
        tries again by itself only when the receipt says the failure may pass (`again`): the lock was not free
        in time. A refusal never says so, and neither does a request that cannot be read."""
        import fcntl
        self.new()
        env = dict(self.env, BOARD_LOCK_TIMEOUT='0.2')
        with open(self.board / '.state.json.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.ingest(ok=False, env=env), {'ok': False, 'error': 'לא ניתן לקרוא או לשמור את ההודעה', 'again': True})
        self.assertEqual(self.ingest(env=env), {'ok':True,'thread':'topic','msg_id':'m1','dup':False})         # the same message, the next try
        path = self.board / 'state/state.json'
        for raw in ('not json', '{"op":"reply","thread":"topic","text":"x","cid":7}', '{"op":"reply","thread":"topic","text":"","cid":"c2"}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                r = self.run_cli('ingest', ok=False)
                self.assertEqual(set(json.loads(r.stdout)), {'ok', 'error'})
        self.assertEqual(len(self.js('pending')), 1)

    def test_ingest_rejected_inputs(self):
        self.new()
        bad = [dict(tid='unknown'), dict(text=''), dict(text='   '), dict(text='x'*8001),
               dict(text=None), dict(cid='x'*81), dict(cid=None), dict(cid='')]
        for args in bad:
            with self.subTest(args=str(args)[:80]):
                result = self.ingest(ok=False, **args)
                self.assertFalse(result['ok'])
                self.assertTrue(result['error'])
        self.assertEqual(self.js('pending'), [])
        self.assertFalse(self.record.exists())

    def test_notify_failure_and_disable(self):
        self.new()
        env = dict(self.env, THREADS_NOTIFY_CMD='/nonexistent/threads-recorder')
        self.assertTrue(self.ingest(env=env)['ok'])
        self.assertIn('m1', (self.board / 'notify.log').read_text())
        self.assertTrue(self.ingest(cid='two', env=dict(self.env, THREADS_NOTIFY='0'))['ok'])
        self.assertFalse(self.record.exists())
        self.assertEqual(len(self.js('pending')), 2)

    def test_concurrent_say(self):
        self.new()
        def say(i):
            return self.run_cli('say', 'topic', '--from', 'tower', str(i)).stdout.strip()
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            ids = list(pool.map(say, range(20)))
        t = self.js('show', 'topic', '--json')
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(len(t['messages']), 20)
        self.assertEqual({m['text'] for m in t['messages']}, {str(i) for i in range(20)})
        self.assertEqual(t['next'], 21)

    def test_install_over_an_old_board_page_leaves_a_redirect_to_suda(self):
        """The board page (board.html) is gone, suda.html is the page (suda m620). Old links point at
        .../threads/board.html#<id>: an installation that has one gets, in its place, a small page that moves on to
        suda.html with the same #id (and ?query). A new installation never gets a board.html."""
        self.run_cli('install')
        self.assertFalse((self.board / 'board.html').exists())
        (self.board / 'board.html').write_text('<html><!-- the old board page, of an older version --></html>', encoding='utf-8')
        self.run_cli('install')
        page = (self.board / 'board.html').read_text(encoding='utf-8')
        self.assertIn("location.replace('suda.html'+location.search+location.hash)", page)
        self.assertIn('<a id="go" href="suda.html">', page)                          # a plain link when the script does not run
        self.assertNotIn('the old board page', page)
        self.assertIsNone(re.search('[\u0590-\u05ff]', page))                         # no language of its own
        self.assertIsNone(re.search(r'(src|href)="(https?:)?//', page))              # nothing from elsewhere
        self.run_cli('install')                                                      # and again: still the redirect, nothing more
        self.assertEqual((self.board / 'board.html').read_text(encoding='utf-8'), page)
        import shutil
        node = shutil.which('node')
        if not node:
            return
        # where it goes, for an old link to a thread (and to a message in it)
        go = ("const s=require('fs').readFileSync(process.argv[1],'utf8').match(/<script>([\\s\\S]*?)<\\/script>/)[1];"
              "const out=[];for(const [search,hash] of [['','#topic'],['?n=3','#topic/m4'],['','']]){"
              "const location={search,hash,replace(u){out.push(u);}};new Function('location',s)(location);}"
              "console.log(JSON.stringify(out))")
        r = subprocess.run([node, '-e', go, str(self.board / 'board.html')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ['suda.html#topic', 'suda.html?n=3#topic/m4', 'suda.html'])

    def test_install_preserves_state_and_hook(self):
        self.run_cli('install')
        fresh = json.loads((self.board / 'state.json').read_text())
        self.assertEqual((fresh['version'], fresh['threads']), (3, {}))
        self.assertEqual(set(fresh['policy']), {'idle_hours','grace_hours','resolved_hours','slot_cooldown_hours','task_archive_hours'})
        self.assertLessEqual({'reply', 'close', 'reopen', 'keep', 'done', 'sweep', 'rename', 'task', 'react', 'snooze', 'unsnooze', 'draft'}, set(fresh['ops']))
        self.new()
        original = (self.board / 'state.json').read_bytes()
        self.run_cli('install')
        self.assertEqual((self.board / 'state.json').read_bytes(), original)
        # the repo's page, as this installation (Hebrew) writes it: its language, its table, nothing else
        same = subprocess.run([sys.executable, '-c', 'import sys\nsys.path.insert(0, sys.argv[1])\nimport threads\nfrom pathlib import Path\n'
                               "print(threads.localized_page(Path(sys.argv[1], 'suda.html').read_text(encoding='utf-8')) == Path(sys.argv[2]).read_text(encoding='utf-8'))",
                               str(ROOT), str(self.board / 'suda.html')], env=self.env, capture_output=True, text=True)
        self.assertEqual(same.stdout.strip(), 'True', same.stderr)
        self.assertIn('<html lang="he" dir="rtl">', (self.board / 'suda.html').read_text(encoding='utf-8'))
        self.assertFalse((self.board / 'board.html').exists())      # the old board page is gone (suda m620)
        # a second front end is published only when the repository ships it
        self.assertEqual((self.board / 'slack.html').exists(), (ROOT / 'slack.html').exists())
        hook = self.board / 'on-state.sh'
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertIn(str(CLI), hook.read_text())
        self.ingest()
        r = subprocess.run([str(hook)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)['dup'])

    def test_install_puts_the_md_viewer_where_the_board_server_imports_it(self):
        # suda-fixes m149: the viewer lives in Suda; the board server imports mdv_web from THREADS_MDV_DIR, else
        # ~/.local/share/threads/mdv. A board elsewhere (BOARDS_DIR, as here) gets it beside its boards folder.
        self.run_cli('install')
        mdv = self.root / 'threads-mdv'
        for part in ('mdv_web.py', 'mdv/web.py', 'mdv/worker.py', 'static/index.html', 'static/app.js',
                     'static/vendor/mermaid.min.js'):
            self.assertTrue((mdv / part).is_file(), part)
        page = (ROOT / 'suda.html').read_text()
        self.assertIn(page.split('// <pure>', 1)[1].split('// </pure>', 1)[0].strip()[:200], (mdv / 'static/suda-pure.js').read_text())
        self.assertIn('--side:', (mdv / 'static/suda.css').read_text())
        self.assertIn('id="i-copy"', (mdv / 'static/icons.svg.html').read_text())
        self.assertFalse((mdv / 'samples').exists())
        self.assertEqual([p for p in mdv.rglob('__pycache__')], [])
        for d in [mdv, *[p for p in mdv.rglob('*') if p.is_dir()]]:
            self.assertEqual(d.stat().st_mode & 0o777, 0o755, d)
        # a second install replaces the copy whole: a file the repository no longer has is gone
        (mdv / 'mdv' / 'old.py').write_text('stale')
        self.run_cli('install')
        self.assertFalse((mdv / 'mdv' / 'old.py').exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.startswith('threads-mdv')), ['threads-mdv'])
        # THREADS_MDV_DIR wins
        there = self.root / 'elsewhere' / 'mdv'
        self.run_cli('install', env=dict(self.env, THREADS_MDV_DIR=str(there)))
        self.assertTrue((there / 'mdv_web.py').is_file())

    def test_pulse_on_mutations(self):
        self.new()
        pulse = self.board / '.pulse'
        for args in [('say','topic','--from','owner','reply'), ('ack','topic','m1'),
                     ('close','topic'), ('reopen','topic'), ('rm','topic','--yes')]:
            os.utime(pulse, (1,1))
            self.run_cli(*args)
            self.assertGreater(pulse.stat().st_mtime, 1)
        self.new()
        os.utime(pulse, (1,1))
        self.ingest()
        self.assertGreater(pulse.stat().st_mtime, 1)


    # ── v2: stable slots, whose turn, questions, self-closing ───────────────

    def test_slots_are_stable(self):
        e = self.at
        for tid in ('a', 'b', 'c'):
            self.run_cli('new', tid, 'T ' + tid, env=e(0))
        def slots(env):
            return {t['id']: t['slot'] for t in json.loads(self.run_cli('list', '--json', env=env).stdout) if t['status'] == 'open'}
        self.assertEqual(slots(e(0)), {'a': 1, 'b': 2, 'c': 3})
        # new activity never reorders
        self.run_cli('say', 'c', '--from', 'fork', 'news', env=e(0.1))
        rows = json.loads(self.run_cli('list', '--json', env=e(0.2)).stdout)
        self.assertEqual([t['id'] for t in rows], ['a', 'b', 'c'])
        # a closed thread frees its slot; the others stay where they were
        self.run_cli('close', 'b', env=e(1))
        self.assertEqual(slots(e(1)), {'a': 1, 'c': 3})
        self.assertEqual(self.thread('b', env=e(1))['slot'], 2)        # remembered for the "freed" tile
        # a freshly freed slot is not handed to another topic
        self.run_cli('new', 'd', 'T d', env=e(2))
        self.assertEqual(slots(e(2))['d'], 4)
        # after the cooldown the lowest free slot is reused
        self.run_cli('new', 'e', 'T e', env=e(8))
        self.assertEqual(slots(e(8))['e'], 2)
        # reopening: the old slot when it is free, otherwise the lowest free one
        self.run_cli('reopen', 'b', env=e(8.1))
        self.assertEqual(slots(e(8.1)), {'a': 1, 'e': 2, 'c': 3, 'd': 4, 'b': 5})
        self.run_cli('close', 'c', env=e(9))
        self.run_cli('reopen', 'c', env=e(9.5))
        self.assertEqual(slots(e(9.5))['c'], 3)
        table = [row.split('\t') for row in self.run_cli('list', env=e(9.5)).stdout.splitlines()]
        self.assertEqual(table[0], ['ID', 'STATUS', 'MESSAGES', 'PENDING', 'TITLE', 'SLOT', 'STATE', 'NOTE'])    # v1 columns first
        self.assertEqual([(row[0], row[5]) for row in table[1:] if row[1] == 'open'], [('a', '1'), ('e', '2'), ('c', '3'), ('d', '4'), ('b', '5')])

    def test_open_threads_always_own_one_slot(self):
        # A record an older CLI or a hand edit left without a slot, with a duplicate, or with nonsense.
        for tid in 'abcd':
            self.new(tid)
        path = self.board / 'state.json'
        data = json.loads(path.read_text())
        del data['threads']['b']['slot']
        data['threads']['c']['slot'] = 1
        data['threads']['d']['slot'] = 'x'
        path.write_text(json.dumps(data))
        slots = {t['id']: t['slot'] for t in self.js('list', '--json')}
        self.assertEqual(slots['a'], 1)                                        # the first owner keeps its place
        self.assertEqual(sorted(slots.values()), [1, 2, 3, 4])
        self.assertEqual({k: v['slot'] for k, v in json.loads(path.read_text())['threads'].items()}, slots)   # mended on disk

    def test_state_command(self):
        self.new()
        self.run_cli('state', 'topic', 'on-owner', ok=False)                    # the one line is mandatory
        self.run_cli('state', 'topic', 'on-owner', '--note', '  ', ok=False)
        self.run_cli('state', 'topic', 'nonsense', '--note', 'x', ok=False)
        self.run_cli('state', 'topic', 'working', '--note', 'x'*201, ok=False)
        self.run_cli('state', 'nope', 'done', ok=False)
        self.run_cli('state', 'topic', 'on-owner', '--note', 'לאשר  מיזוג\nשל PR 7', env=self.at(1))
        t = self.thread(env=self.at(1))
        self.assertEqual((t['state'], t['note'], t['auto']), ('on-owner', 'לאשר מיזוג של PR 7', False))
        self.assertEqual(t['state_ts'], self.T0 + 3600)
        self.run_cli('state', 'topic', 'working', '--note', 'בונה', '--by', 'builder')
        t = self.thread()
        self.assertEqual((t['state'], t['state_by'], t['note']), ('working', 'builder', 'בונה'))
        self.run_cli('state', 'topic', 'done')
        self.assertEqual(self.thread()['state'], 'done')
        self.assertIn('\tdone\t', self.run_cli('list').stdout)

    def test_turn_follows_the_conversation(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        t = self.thread(env=e(0))
        self.assertEqual((t['state'], t['auto']), ('on-owner', True))
        self.ingest(text='תמזג ותמשיך', env=e(1))
        t = self.thread(env=e(1))
        self.assertEqual((t['state'], t['auto']), ('working', True))
        self.assertIn('תמזג ותמשיך', t['note'])
        self.run_cli('ack', 'topic', 'm1', env=e(1.5))
        t = self.thread(env=e(1.5))
        self.assertEqual((t['state'], t['state_by'], t['state_ts']), ('working', 'fork', self.T0 + 1.5*3600))
        # an agent that answers and forgets the state must not leave the thread "working" for ever
        self.run_cli('say', 'topic', '--from', 'fork', '**סיימתי** את המיזוג\nעוד שורה', env=e(2))
        t = self.thread(env=e(2))
        self.assertEqual((t['state'], t['auto'], t['note']), ('on-owner', True, 'לקרוא: סיימתי את המיזוג עוד שורה'))
        # message and state in one command
        self.run_cli('say', 'topic', '--from', 'fork', 'ממשיך', '--state', 'working', '--note', 'מריץ בדיקות', '--by', 'builder', env=e(3))
        t = self.thread(env=e(3))
        self.assertEqual((t['state'], t['auto'], t['note'], t['state_by']), ('working', False, 'מריץ בדיקות', 'builder'))
        self.run_cli('say', 'topic', '--from', 'fork', 'x', '--state', 'on-owner', ok=False, env=e(3))
        self.assertEqual(len(self.thread(env=e(3))['messages']), 3)             # the refused command wrote nothing
        # an explicit "on you" line survives a later plain message
        self.run_cli('state', 'topic', 'on-owner', '--note', 'להחליט A או B', env=e(4))
        self.run_cli('say', 'topic', '--from', 'tower', 'תזכורת', env=e(4.5))
        t = self.thread(env=e(4.5))
        self.assertEqual((t['state'], t['note'], t['auto']), ('on-owner', 'להחליט A או B', False))

    def test_ask_and_quick_answer(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'למזג?', '--options', 'כן', ok=False, env=e(0))               # a choice needs 2+
        self.run_cli('ask', 'topic', 'למזג?', '--options', ','.join('abcdefg'), ok=False, env=e(0))  # and at most 6
        self.run_cli('ask', 'topic', 'למזג?', '--options', 'כן,' + 'x'*41, ok=False, env=e(0))
        self.run_cli('ask', 'topic', '  ', ok=False, env=e(0))
        self.assertEqual(self.thread(env=e(0))['messages'], [])
        out = self.run_cli('ask', 'topic', 'למזג את PR 7?', '--options', 'כן, לא ,כן', env=e(1)).stdout.strip()
        self.assertEqual(out, 'm1')
        t = self.thread(env=e(1))
        self.assertEqual(t['question'], {'id': 'm1', 'text': 'למזג את PR 7?', 'options': ['כן', 'לא'], 'from': 'fork', 'ts': self.T0 + 3600})
        self.assertEqual((t['state'], t['note'], t['auto']), ('on-owner', 'למזג את PR 7?', False))
        self.assertEqual((t['messages'][0]['options'], t['messages'][0]['q']), (['כן', 'לא'], True))
        # a stale tab must not answer a question that is no longer the open one
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c0', 'q': 'm0'}, ok=False, env=e(1.5))['ok'])
        good = self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm1'}, env=e(2))
        self.assertEqual(good, {'ok': True, 'thread': 'topic', 'msg_id': 'm2', 'dup': False})
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm1'}, env=e(2.1))['dup'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'לא', 'cid': 'c2', 'q': 'm1'}, ok=False, env=e(2.2))['ok'])
        t = self.thread(env=e(3))
        self.assertIsNone(t['question'])
        self.assertEqual((t['state'], len(t['messages'])), ('working', 2))
        self.assertEqual(t['messages'][1]['re'], {'q': 'm1', 'text': 'למזג את PR 7?'})
        row = json.loads(self.run_cli('pending', env=e(3)).stdout)[0]
        self.assertEqual(row['re'], {'q': 'm1', 'text': 'למזג את PR 7?'})
        # a free-text question has no buttons
        self.run_cli('ask', 'topic', 'מה התאריך?', '--from', 'tower', env=e(4))
        q = self.thread(env=e(4))['question']
        self.assertEqual((q['options'], q['from']), ([], 'tower'))
        # a typed reply written under the open question settles it too
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'מחר', 'cid': 'c3', 'under': q['id']}, env=e(5))['ok'])
        t = self.thread(env=e(5))
        self.assertIsNone(t['question'])
        self.assertEqual((t['state'], t['messages'][-1]['re']['q']), ('working', q['id']))

    def test_an_open_question_outlives_what_agents_write_after_it(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'למזג היום?', '--options', 'כן,לא', env=e(1))
        # the agent that asked goes on working, and says so: the question is still his to answer
        self.run_cli('say', 'topic', '--from', 'fork', 'בינתיים מריץ בדיקות', '--state', 'working', '--note', 'מריץ בדיקות', env=e(2))
        t = self.thread(env=e(2))
        self.assertEqual((t['state'], t['question']['id'], t['question']['options']), ('working', 'm1', ['כן', 'לא']))
        self.run_cli('state', 'topic', 'on-owner', '--note', 'מחכה לתשובה שלך', env=e(3))
        self.assertEqual(self.thread(env=e(3))['question']['id'], 'm1')
        # a plain report after it: the thread is on him for the QUESTION (a real ask, not "read this")
        self.run_cli('state', 'topic', 'working', '--note', 'עוד רגע', env=e(4))
        self.run_cli('say', 'topic', '--from', 'fork', 'הבדיקות עברו', env=e(5))
        t = self.thread(env=e(5))
        self.assertEqual((t['state'], t['auto'], t['note'], t['question']['id']), ('on-owner', False, 'למזג היום?', 'm1'))
        self.assertFalse(self.post({'op': 'done', 'thread': 'topic', 'last': 'm3'}, ok=False, env=e(6))['ok'])       # "read it" does not put a question away
        # his tap still lands on it, and only then is it over
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'כן', 'q': 'm1'}, env=e(7))['ok'])
        t = self.thread(env=e(7))
        self.assertEqual((t['question'], t['state'], t['messages'][-1]['re']), (None, 'working', {'q': 'm1', 'text': 'למזג היום?'}))
        # a new question replaces the old one; done and resolve end it
        self.run_cli('ask', 'topic', 'ועכשיו?', '--options', 'א,ב', env=e(8))
        self.run_cli('ask', 'topic', 'בעצם?', '--options', 'ג,ד', env=e(9))
        self.assertEqual(self.thread(env=e(9))['question']['text'], 'בעצם?')
        self.run_cli('state', 'topic', 'done', '--note', 'ירד מהפרק', env=e(10))
        self.assertIsNone(self.thread(env=e(10))['question'])

    def test_typed_reply_is_filed_under_the_question_he_saw(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'למזג את PR 7?', '--options', 'כן,לא', env=e(1))                 # m1: on his screen
        self.run_cli('ask', 'topic', 'למחוק את גיבוי הפרודקשן?', '--options', 'כן,לא', env=e(2))     # m2: arrives while his reply waits
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן, קדימה', 'cid': 'c1', 'under': 'm1'}, env=e(3))['ok'])
        t = self.thread(env=e(3))
        self.assertEqual(t['messages'][-1]['re'], {'q': 'm1', 'text': 'למזג את PR 7?'})             # what he answered
        self.assertEqual((t['question']['id'], t['state']), ('m2', 'on-owner'))                    # the new one still waits on him
        row = json.loads(self.run_cli('pending', env=e(3)).stdout)[0]
        self.assertEqual(row['re']['q'], 'm1')
        # nothing was on his screen, a question is open now: it stays open
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'משהו אחר', 'cid': 'c2', 'under': None}, env=e(4))['ok'])
        t = self.thread(env=e(4))
        self.assertNotIn('re', t['messages'][-1])
        self.assertEqual(t['question']['id'], 'm2')
        # an older page does not say: the reply is stored and filed under nothing, and it closes no question (suda
        # m508: a "yes" must never be filed as the answer to a question he did not see); m2 stays open, on him
        self.ingest(text='תשובה מדף ישן', cid='c3', env=e(5))
        t = self.thread(env=e(5))
        self.assertNotIn('re', t['messages'][-1])
        self.assertEqual((t['question']['id'], t['state']), ('m2', 'on-owner'))
        self.assertIn(t['messages'][-1]['id'], [r['msg_id'] for r in json.loads(self.run_cli('pending', env=e(5)).stdout)])
        for bad in ({'under': 5}, {'under': ['m1']}, {'q': 5}):
            self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c9', **bad}, ok=False, env=e(6))['ok'])

    # ── several open questions in one thread (the owner, suda m508: "when there are two questions, one cancels the other") ──

    def ids(self, t):
        return [q['id'] for q in t['questions']]

    def test_two_asks_keep_both_open_and_his_answer_closes_only_its_own(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.assertEqual(self.run_cli('ask', 'topic', 'למזג את PR 7?', '--options', 'כן,לא', env=e(1)).stdout.strip(), 'm1')
        self.assertEqual(self.run_cli('ask', 'topic', 'לפרוס לסטייג׳ינג?', '--options', 'עכשיו,מחר', '--from', 'tower', env=e(2)).stdout.strip(), 'm2')
        t = self.thread(env=e(2))
        self.assertEqual(self.ids(t), ['m1', 'm2'])                     # oldest first
        self.assertEqual(t['question']['id'], 'm2')                     # `question` stays the newest: old pages keep working
        self.assertEqual(t['questions'][0], {'id': 'm1', 'text': 'למזג את PR 7?', 'options': ['כן', 'לא'], 'from': 'fork', 'ts': self.T0 + 3600})
        self.assertEqual((t['state'], t['note'], t['auto']), ('on-owner', 'לפרוס לסטייג׳ינג?', False))
        self.assertIn('למזג את PR 7?', self.run_cli('show', 'topic', env=e(2)).stdout)
        # he taps an answer of the OLDER one (the page says the newest was on his screen): that one closes, the other stays on him
        good = self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm1', 'under': 'm2'}, env=e(3))
        self.assertEqual(good['msg_id'], 'm3')
        t = self.thread(env=e(3))
        self.assertEqual((self.ids(t), t['question']['id']), (['m2'], 'm2'))
        self.assertEqual(t['messages'][-1]['re'], {'q': 'm1', 'text': 'למזג את PR 7?'})
        self.assertEqual((t['state'], t['note'], t['auto']), ('on-owner', 'לפרוס לסטייג׳ינג?', False))
        self.assertEqual(t['seen']['msg'], 'm3')            # he saw both: his own answer is no news to push to him
        self.assertIsNone(t.get('alert'))
        self.assertEqual([r['re']['q'] for r in json.loads(self.run_cli('pending', env=e(3)).stdout)], ['m1'])
        # a second device that still shows m1 open cannot answer it again
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'לא', 'cid': 'c2', 'q': 'm1'}, ok=False, env=e(3.5))['ok'])
        # then the newer one: the last open question ends, and the turn goes to the agents
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'מחר', 'cid': 'c3', 'q': 'm2', 'under': 'm2'}, env=e(4))['ok'])
        t = self.thread(env=e(4))
        self.assertEqual((t['questions'], t['question'], t['state']), ([], None, 'working'))
        self.assertEqual([r['re']['q'] for r in json.loads(self.run_cli('pending', env=e(4)).stdout)], ['m1', 'm2'])

    def test_his_ticks_answer_the_question_they_were_ticked_in(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'מה לכלול?', '--multi', '--options', 'א,ב,ג', env=e(1))         # m1
        self.run_cli('ask', 'topic', 'כן או לא?', '--options', 'כן,לא', env=e(2))                    # m2
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'q': 'm1', 'answer': {'': ['א', 'ג']}}, env=e(3))['ok'])
        t = self.thread(env=e(3))
        self.assertEqual((t['messages'][-1]['re']['q'], t['messages'][-1]['re']['answer']), ('m1', {'': ['א', 'ג']}))
        self.assertEqual((self.ids(t), t['state']), (['m2'], 'on-owner'))
        # ticks sent for a question with no groups are refused, whichever is open
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c2', 'q': 'm2', 'answer': {'': ['כן']}}, ok=False, env=e(4))['ok'])

    def test_a_typed_reply_answers_the_question_it_replies_to_else_the_newest_he_saw(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        for i, q in enumerate(('ראשונה?', 'שנייה?', 'שלישית?'), 1):
            self.run_cli('ask', 'topic', q, env=e(i))                                                  # m1 m2 m3, words only
        # a reply to the question's own message answers that one
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'על הראשונה', 'cid': 'c1', 'reply_to': 'm1', 'under': 'm3'}, env=e(4))['ok'])
        t = self.thread(env=e(4))
        self.assertEqual((t['messages'][-1]['re']['q'], self.ids(t)), ('m1', ['m2', 'm3']))
        # a plain typed reply answers the newest question that was on his screen
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'על האחרונה', 'cid': 'c2', 'under': 'm3'}, env=e(5))['ok'])
        t = self.thread(env=e(5))
        self.assertEqual((t['messages'][-1]['re']['q'], self.ids(t), t['state']), ('m3', ['m2'], 'on-owner'))
        # a question that arrived while he was typing is not answered by words he wrote before it: m6 stays, and is news
        self.run_cli('ask', 'topic', 'רביעית?', env=e(6))                                             # m6
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'על השנייה', 'cid': 'c3', 'under': 'm2'}, env=e(7))['ok'])
        t = self.thread(env=e(7))
        self.assertEqual((t['messages'][-1]['re']['q'], self.ids(t), t['state']), ('m2', ['m6'], 'on-owner'))
        self.assertNotEqual((t.get('seen') or {}).get('msg'), 'm7')
        # an older page that does not say: no question is closed or named (suda m508: a "yes" must never be filed as
        # the answer to a question he did not see)
        self.ingest(text='מדף ישן', cid='c4', env=e(8))
        t = self.thread(env=e(8))
        self.assertEqual((self.ids(t), t['state'], 're' in t['messages'][-1]), (['m6'], 'on-owner', False))

    def test_ask_appends_up_to_a_limit_and_replace_supersedes(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        for i in range(1, 6):
            self.run_cli('ask', 'topic', f'שאלה {i}?', '--options', 'כן,לא', env=e(i))              # m1 … m5
        r = self.run_cli('ask', 'topic', 'שאלה 6?', '--options', 'כן,לא', ok=False, env=e(6))
        self.assertIn('--replace', r.stderr)
        self.assertRegex(r.stderr, '[א-ת]')
        t = self.thread(env=e(6))
        self.assertEqual((len(t['messages']), self.ids(t)), (5, ['m1', 'm2', 'm3', 'm4', 'm5']))
        # --replace takes one open question back and asks the new one in the same command
        r = self.run_cli('ask', 'topic', 'שאלה 6?', '--options', 'כן,לא', '--replace', 'm2', env=e(7))
        self.assertEqual((r.stdout.strip(), 'm2' in r.stderr), ('m6', True))
        t = self.thread(env=e(7))
        self.assertEqual(self.ids(t), ['m1', 'm3', 'm4', 'm5', 'm6'])
        self.assertIn('--replace', self.run_cli('ask', 'topic', 'x?', '--replace', 'm2', ok=False, env=e(8)).stderr)   # not open any more
        self.run_cli('ask', 'topic', 'x?', '--replace', 'm1', '--replace-all', ok=False, env=e(8))
        self.assertEqual(len(self.thread(env=e(8))['messages']), 6)             # a refused ask writes nothing
        # the same question asked again by the same agent (same words, same options) replaces it, and says so
        r = self.run_cli('ask', 'topic', 'שאלה 3?', '--options', 'כן,לא', env=e(9))                    # m7
        self.assertIn('m3', r.stderr)
        self.assertEqual(self.ids(self.thread(env=e(9))), ['m1', 'm4', 'm5', 'm6', 'm7'])
        # --replace-all: this question is the only one
        self.run_cli('ask', 'topic', 'מההתחלה?', '--options', 'כן,לא', '--replace-all', env=e(10))      # m8
        t = self.thread(env=e(10))
        self.assertEqual((self.ids(t), t['question']['id'], t['state'], t['note']), (['m8'], 'm8', 'on-owner', 'מההתחלה?'))
        # a stale tab that taps a replaced question is refused
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'q': 'm4'}, ok=False, env=e(11))['ok'])
        help_ = self.run_cli('ask', '--help').stdout
        self.assertIn('--replace', help_)
        self.assertIn('--replace-all', help_)

    def test_what_ends_the_topic_ends_every_open_question(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'א?', '--options', 'כן,לא', env=e(1))
        self.run_cli('ask', 'topic', 'ב?', '--options', 'כן,לא', env=e(2))
        self.run_cli('say', 'topic', '--from', 'fork', 'דיווח', env=e(3))                              # m3: a plain report keeps both on him
        t = self.thread(env=e(3))
        self.assertEqual((self.ids(t), t['state'], t['auto'], t['note']), (['m1', 'm2'], 'on-owner', False, 'ב?'))
        self.assertFalse(self.post({'op': 'done', 'thread': 'topic', 'last': 'm3'}, ok=False, env=e(4))['ok'])     # "read it" puts no question away
        # close is an undo away: both come back with a reopen
        self.post({'op': 'close', 'thread': 'topic', 'last': 'm3'}, env=e(5))
        self.post({'op': 'reopen', 'thread': 'topic'}, env=e(6))
        self.assertEqual(self.ids(self.thread(env=e(6))), ['m1', 'm2'])
        self.run_cli('state', 'topic', 'done', '--note', 'ירד מהפרק', env=e(7))
        t = self.thread(env=e(7))
        self.assertEqual((t['questions'], t['question']), ([], None))
        self.run_cli('ask', 'topic', 'ג?', '--options', 'כן,לא', env=e(8))
        self.run_cli('ask', 'topic', 'ד?', '--options', 'כן,לא', env=e(9))
        self.run_cli('resolve', 'topic', '--note', 'נפתר', env=e(10))
        self.assertEqual(self.thread(env=e(10))['questions'], [])
        # merged away: its questions end with it
        self.run_cli('new', 'other', 'אחר', env=e(11))
        self.run_cli('ask', 'other', 'ה?', '--options', 'כן,לא', env=e(11))
        self.run_cli('ask', 'other', 'ו?', '--options', 'כן,לא', env=e(11.5))
        self.run_cli('merge', 'other', '--into', 'topic', env=e(12))
        t = self.thread('other', env=e(12))
        self.assertEqual((t['questions'], t['question']), ([], None))
        line = self.thread(env=e(12))['messages'][-1]['text']          # said in the thread it went into, not silent
        self.assertIn('ה?', line)
        self.assertIn('ו?', line)

    def test_a_late_answer_is_filed_under_its_question_and_leaves_the_open_ones(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'ישנה?', '--options', 'כן,לא', env=e(1))                        # m1
        self.run_cli('say', 'topic', '--from', 'fork', 'עברתי לנושא אחר', '--state', 'done', '--note', 'נסגר', env=e(2))
        self.run_cli('ask', 'topic', 'חדשה?', '--options', 'כן,לא', env=e(3))                        # m3
        self.run_cli('ask', 'topic', 'עוד חדשה?', '--options', 'כן,לא', env=e(4))                    # m4
        # his late answer to m1 (a reply to its message): filed under it; the two open ones stay, and on him
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c1', 'reply_to': 'm1', 'under': 'm4'}, env=e(5))['ok'])
        t = self.thread(env=e(5))
        self.assertEqual((t['messages'][-1]['re'], self.ids(t), t['state']), ({'q': 'm1', 'text': 'ישנה?'}, ['m3', 'm4'], 'on-owner'))
        # with nothing open, a late answer hands the turn over as before
        self.run_cli('state', 'topic', 'done', '--note', 'נסגר', env=e(6))
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'c2', 'reply_to': 'm4', 'under': None}, env=e(7))['ok'])
        t = self.thread(env=e(7))
        self.assertEqual((t['messages'][-1]['re']['q'], t['questions'], t['state']), ('m4', [], 'working'))

    def test_a_state_from_before_several_questions_is_read_without_loss(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('new', 'quiet', 'שקט', env=e(0))
        self.run_cli('ask', 'topic', 'ישנה?', '--options', 'כן,לא', env=e(1))
        path = self.board / 'state.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for t in data['threads'].values():
            t.pop('questions', None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.ids(self.thread(env=e(2))), ['m1'])
        self.assertEqual(self.thread('quiet', env=e(2))['questions'], [])
        self.run_cli('ask', 'topic', 'חדשה?', '--options', 'כן,לא', env=e(3))
        self.assertEqual(self.ids(self.thread(env=e(3))), ['m1', 'm2'])
        # an older CLI that knows only `question` (a rollback) knew only the newest: when it replaced it, that one is
        # over and the older one it never saw stays open; when it ended the topic, all are over
        data = json.loads(path.read_text(encoding='utf-8'))
        t = data['threads']['topic']
        t['question'] = {'id': 'm9', 'text': 'מגרסה ישנה', 'options': [], 'from': 'fork', 'ts': self.T0}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.ids(self.thread(env=e(4))), ['m1', 'm9'])
        t.update(question=None, state='done')
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.thread(env=e(4))['questions'], [])
        # a damaged list is refused, not guessed at
        t['questions'] = [{'id': 5}]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertIn('פגום', self.run_cli('show', 'topic', ok=False, env=e(4)).stderr)

    def test_stale_page_cannot_dismiss_or_close_what_he_did_not_see(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח ראשון', env=e(1))                # m1: on his screen
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח שני: צריך החלטה', env=e(2))      # m2: the tab has not refreshed
        for op in ('done', 'close'):
            self.assertFalse(self.post({'op': op, 'thread': 'topic', 'last': 'm1'}, ok=False, env=e(3))['ok'])
        self.assertFalse(self.post({'op': 'done', 'thread': 'topic'}, ok=False, env=e(3))['ok'])      # "read it" must say what was read
        t = self.thread(env=e(3))
        self.assertEqual((t['status'], t['state']), ('open', 'on-owner'))
        self.assertTrue(self.post({'op': 'done', 'thread': 'topic', 'last': 'm2'}, env=e(4))['ok'])
        self.assertTrue(self.post({'op': 'close', 'thread': 'topic', 'last': 'm2'}, env=e(5))['ok'])
        self.assertEqual(self.thread(env=e(5))['status'], 'closed')

    def test_his_done_always_ends_his_turn(self):
        # suda-fixes m426: "/done must always work, even if something is open; it is always my right to finish".
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=e(1))                                    # m1
        self.run_cli('ask', 'topic', 'לפרוס?', '--options', 'כן,לא', '--from', 'fork', env=e(2))            # m2: a real ask
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'לבנות את א', env=e(2.5)).stdout.strip(), '1')
        # the automatic "read it" of the page keeps its guard: it puts no ask away
        self.assertFalse(self.post({'op': 'done', 'thread': 'topic', 'last': 'm2'}, ok=False, env=e(3))['ok'])
        for bad in ('yes', 1, False, None):
            with self.subTest(always=bad):
                self.assertFalse(self.post({'op': 'done', 'thread': 'topic', 'last': 'm2', 'always': bad}, ok=False, env=e(3))['ok'])
        got = self.post({'op': 'done', 'thread': 'topic', 'last': 'm2', 'always': True}, env=e(4))
        self.assertTrue(got['ok'])
        self.assertEqual((got['asks'], got['tasks'], got['unseen']), (['m2'], [1], []))
        t = self.thread(env=e(4))
        self.assertEqual((t['status'], t['state'], t['state_by'], t['questions'], t['question']), ('open', 'done', 'owner', [], None))
        self.assertNotIn('לקרוא', t['note'])
        ask = next(m for m in t['messages'] if m['id'] == 'm2')
        self.assertEqual((ask['q'], ask['text'], ask['options']), (True, 'לפרוס?', ['כן', 'לא']))      # kept in the history,
        self.assertEqual(ask['q_closed'], {'ts': self.T0 + 4 * 3600, 'by': 'owner'})   # and said to be closed unanswered
        self.assertEqual([(k['n'], k['status']) for k in t['tasks']], [(1, 'todo')])      # tasks stay as they are
        # again: nothing to change, nothing rewritten
        again = self.post({'op': 'done', 'thread': 'topic', 'last': 'm2', 'always': True}, env=e(5))
        self.assertTrue(again['ok'])
        self.assertEqual(self.thread(env=e(5))['state_ts'], self.T0 + 4 * 3600)
        # a message he has not seen: done all the same, and it comes back to the page to be shown, not lost
        self.run_cli('say', 'topic', '--from', 'fork', 'עוד משהו חשוב', env=e(6))                           # m3
        self.run_cli('state', 'topic', 'on-owner', '--note', 'עליך: להחליט', '--force', env=e(6.5))
        got = self.post({'op': 'done', 'thread': 'topic', 'last': 'm2', 'always': True}, env=e(7))
        self.assertTrue(got['ok'])
        self.assertEqual([(x['id'], x['from'], x['text']) for x in got['unseen']], [('m3', 'fork', 'עוד משהו חשוב')])
        t = self.thread(env=e(7))
        self.assertEqual(t['state'], 'done')
        self.assertEqual(t['messages'][-1]['text'], 'עוד משהו חשוב')
        # a closed thread is already over: his /done there is no error
        self.post({'op': 'close', 'thread': 'topic', 'last': 'm3'}, env=e(8))
        self.assertTrue(self.post({'op': 'done', 'thread': 'topic', 'last': 'm3', 'always': True}, env=e(9))['ok'])
        self.assertEqual(self.thread(env=e(9))['status'], 'closed')

    def test_his_done_while_his_reply_waits_on_the_agents(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', env=e(1))
        self.ingest(text='תבדוק', env=e(2))                                                       # m2: on the agents now
        self.assertEqual(self.thread(env=e(2))['state'], 'working')
        self.assertTrue(self.post({'op': 'done', 'thread': 'topic', 'last': 'm2', 'always': True}, env=e(3))['ok'])
        t = self.thread(env=e(3))
        self.assertEqual(t['state'], 'done')
        self.assertEqual(t['messages'][-1]['status'], 'pending')        # his words still reach the agents

    def test_an_agent_ends_a_thread_over_open_tasks_on_his_word(self):
        # suda-fixes m428: when he asks in words to finish, the agent that acts on it may end the thread over open
        # tasks, naming the message of his that said so (not a blind --force).
        e = self.at
        for n, (cmd, extra) in enumerate((('state', ['done']), ('resolve', []), ('close', [])), 1):
            tid = f'topic{n}'
            with self.subTest(cmd=cmd):
                self.run_cli('new', tid, 'כותרת', env=e(0))
                self.run_cli('say', tid, '--from', 'fork', 'דוח', env=e(1))                       # m1: an agent's
                self.ingest(tid, text='סיים את זה', env=e(2))                               # m2: his
                self.run_cli('task', 'add', tid, 'לבנות את א', env=e(2.5))
                by = ['--by', 'fork'] if cmd == 'close' else []
                self.assertIn('--on-his-word', self.run_cli(cmd, tid, *extra, *by, ok=False, env=e(3)).stderr)
                self.run_cli(cmd, tid, *extra, *by, '--on-his-word', 'm1', ok=False, env=e(3))    # not his message
                self.run_cli(cmd, tid, *extra, *by, '--on-his-word', 'm9', ok=False, env=e(3))    # no such message
                self.run_cli(cmd, tid, *extra, *by, '--on-his-word', 'm2', env=e(4))
                t = self.thread(tid, env=e(4))
                self.assertEqual(t['his_word'], {'msg': 'm2', 'cmd': cmd, 'by': 'fork' if cmd == 'close' else 'agent', 'ts': self.T0 + 4 * 3600})
                self.assertEqual([(k['n'], k['status']) for k in t['tasks']], [(1, 'todo')])
                self.assertEqual(t['status'] if cmd == 'close' else t['state'], 'closed' if cmd == 'close' else 'done')
        self.run_cli('new', 'topic9', 'כותרת', env=e(0))
        self.ingest('topic9', text='סיים', env=e(1))
        self.run_cli('task', 'add', 'topic9', 'x', env=e(1.5))
        self.run_cli('say', 'topic9', '--from', 'fork', 'סיימתי', '--state', 'done', '--on-his-word', 'm1', env=e(2))
        self.assertEqual(self.thread('topic9', env=e(2))['state'], 'done')

    # ── snippets: long text lives in its own file ───────────────────────────

    LONG = 'שורה ארוכה עם English ועברית, מספר 123\n' * 2000        # 2000 lines, about 78 000 characters

    def test_long_text_from_the_page_becomes_a_snippet(self):
        e, long = self.at, self.LONG
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        # a typed message with an attached file
        r = self.post({'op': 'reply', 'thread': 'topic', 'text': 'הנה הלוג', 'cid': 'c1', 'under': None,
                       'snippet': {'text': long, 'name': '../../var/log/app.log'}}, env=e(1))
        self.assertEqual(r, {'ok': True, 'thread': 'topic', 'msg_id': 'm1', 'dup': False})
        m = self.thread(env=e(1))['messages'][0]
        s = m['snippet']
        self.assertEqual(m['text'], 'הנה הלוג')
        self.assertEqual((s['file'], s['name'], s['only']), ('snippets/topic/m1.log', 'app.log', False))   # the name is a base name, never a path
        self.assertEqual((s['chars'], s['lines'], s['bytes']), (len(long), 2000, len(long.encode('utf-8'))))
        self.assertTrue(0 < len(s['head']) <= 600 and len(s['head'].splitlines()) <= 12)
        self.assertTrue(long.startswith(s['head'].rstrip('…')))
        self.assertEqual((self.board / s['file']).read_text(encoding='utf-8'), long)                     # the whole text, exactly
        row = json.loads(self.run_cli('pending', env=e(1)).stdout)[0]
        self.assertEqual(row['text'], 'הנה הלוג')
        self.assertEqual(row['snippet'], {'path': str(self.board / 'snippets/topic/m1.log'), 'name': 'app.log',
                                          'bytes': s['bytes'], 'chars': s['chars'], 'lines': 2000})
        # a retry of the same reply stores nothing twice
        stamp = (self.board / s['file']).stat().st_mtime_ns
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'הנה הלוג', 'cid': 'c1', 'under': None,
                                   'snippet': {'text': long, 'name': 'app.log'}}, env=e(1.1))['dup'])
        self.assertEqual((self.board / s['file']).stat().st_mtime_ns, stamp)
        # a snippet with no typed message: the text is a short preview, flagged so a page does not show it twice
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c2', 'under': None, 'snippet': {'text': long}}, env=e(2))['ok'])
        m = self.thread(env=e(2))['messages'][1]
        self.assertEqual((m['snippet']['file'], m['snippet']['name'], m['snippet']['only']), ('snippets/topic/m2.txt', None, True))
        self.assertTrue(0 < len(m['text']) <= 200 and '\n' not in m['text'])
        self.assertIn('שורה ארוכה', self.thread(env=e(2))['note'])                                    # "ענית: «…»" stays one short line
        # a long paste into a plain box is not lost either: over 4000 characters inline is stored as a snippet
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'א' * 5000, 'cid': 'c3', 'under': None}, env=e(3))['ok'])
        m = self.thread(env=e(3))['messages'][2]
        self.assertEqual((m['snippet']['chars'], m['snippet']['only'], (self.board / m['snippet']['file']).read_text(encoding='utf-8')), (5000, True, 'א' * 5000))
        self.assertLessEqual(len(m['text']), 200)
        # 4000 characters and less stay inline
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'ב' * 4000, 'cid': 'c4', 'under': None}, env=e(4))['ok'])
        self.assertNotIn('snippet', self.thread(env=e(4))['messages'][3])
        # the notification stays one short line
        records = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertTrue(all(len(r['args'][0]) < 200 for r in records))

    def test_snippet_limits_and_refusals(self):
        self.new()
        before = sorted(p.name for p in self.board.rglob('*') if p.is_file() and p.name != 'state.json' and not p.name.startswith('.'))
        state = (self.board / 'state.json').read_bytes()
        bad = [{'snippet': {'text': 'א' * 10_000_001}},                # 20 000 002 bytes: over the limit
               {'snippet': {'text': ''}}, {'snippet': {'text': '  \n '}}, {'snippet': {'text': 5}}, {'snippet': 'x'}, {'snippet': ['x']},
               {'snippet': {'text': 'x', 'name': 5}}, {'text': 'x' * 8001, 'snippet': {'text': 'y'}}, {'text': 'x' * 8001}, {'text': ''}]
        for extra in bad:
            with self.subTest(extra=str(extra)[:60]):
                payload = {'op': 'reply', 'thread': 'topic', 'text': 'שלום', 'cid': 'c1', **extra}
                self.assertFalse(self.post(payload, ok=False)['ok'])
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.assertEqual(sorted(p.name for p in self.board.rglob('*') if p.is_file() and p.name != 'state.json' and not p.name.startswith('.')), before)
        # the largest snippet that is allowed, an odd name, an unknown extension
        ok = self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c2', 'snippet': {'text': 'א' * 1_000_000, 'name': ' דוח\tסופי.PDF '}})
        self.assertTrue(ok['ok'])
        s = self.thread()['messages'][0]['snippet']
        self.assertEqual((s['file'], s['name'], s['bytes']), ('snippets/topic/m1.txt', 'דוח סופי.PDF', 2_000_000))

    def test_a_big_text_file_comes_from_the_page_in_parts(self):
        """The owner (a big-file thread, m6): a text file over 2 MB (a 7 MB crash report). The board server takes a
        request of up to 4 MB, so the page sends a big text in parts (op snippet-part, each under PART_MAX bytes),
        then the reply names how many: the server joins them into the snippet's file. The parts wait outside the
        served folder, and go once the message is stored (or after hours, if it never comes)."""
        e = self.at
        self.new()
        whole = ('Thread 0 Crashed:: Dispatch queue: com.apple.main-thread\n' + 'א' * 40 + '\n') * 70_000   # ~10 MB
        size = len(whole.encode('utf-8'))
        self.assertGreater(size, 7_000_000)
        cut = [whole[i:i + 700_000] for i in range(0, len(whole), 700_000)]
        n = len(cut)
        for i, part in enumerate(cut):
            got = self.post({'op': 'snippet-part', 'thread': 'topic', 'cid': 'big-1', 'i': i, 'n': n, 'text': part}, env=e(1))
            self.assertEqual(got, {'ok': True, 'op': 'snippet-part', 'thread': 'topic', 'i': i, 'n': n})
            # what he sent does not stay in the served folder, not even in the request
            self.assertEqual((self.board / 'state/state.json').read_text().strip(), '{}')
        self.assertFalse(any('Thread 0 Crashed' in p.read_text(errors='ignore') for p in self.board.rglob('*') if p.is_file()))
        got = self.post({'op': 'reply', 'thread': 'topic', 'text': 'דוח הקריסה', 'cid': 'big-1', 'under': None,
                         'snippet': {'name': 'crash.ips', 'parts': n}}, env=e(1.1))
        self.assertTrue(got['ok'] and not got['dup'], got)
        m = self.thread(env=e(1.1))['messages'][0]
        self.assertEqual((m['text'], m['snippet']['name'], m['snippet']['bytes']), ('דוח הקריסה', 'crash.ips', size))
        self.assertEqual((self.board / m['snippet']['file']).read_text(encoding='utf-8'), whole)
        self.assertEqual(self.run_cli('snippet', 'topic', 'm1', env=e(1.1)).stdout, whole)
        # the parts are gone, and the same reply sent again (no answer reached the page) is the same message
        self.assertFalse(any((self.root / '.threads-config').rglob('*.part')))
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'דוח הקריסה', 'cid': 'big-1', 'under': None,
                                   'snippet': {'name': 'crash.ips', 'parts': n}}, env=e(1.2))['dup'])
        self.assertEqual(len(self.thread(env=e(1.2))['messages']), 1)

    def test_parts_of_a_big_text_refused_and_left_over(self):
        e = self.at
        self.new()
        part = lambda **kw: {'op': 'snippet-part', 'thread': 'topic', 'cid': 'p-1', 'i': 0, 'n': 2, 'text': 'שורה\n', **kw}
        for bad in ({'i': 2}, {'i': -1}, {'n': 0}, {'n': 101}, {'i': True}, {'n': '2'}, {'text': 5}, {'text': ''},
                    {'text': 'x' * 1_500_001}, {'cid': ''}, {'cid': 'x' * 81}, {'thread': 'nope'}):
            with self.subTest(bad=str(bad)[:40]):
                self.assertFalse(self.post(part(**bad), ok=False, env=e(1))['ok'])
        # a reply whose parts did not all arrive: refused, nothing stored
        self.assertTrue(self.post(part(), env=e(1))['ok'])
        missing = self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'p-1', 'under': None, 'snippet': {'parts': 2}}, ok=False, env=e(1))
        self.assertFalse(missing['ok'])
        for bad in ({'parts': 0}, {'parts': 101}, {'parts': '2'}, {'parts': 2, 'text': 'x'}):
            with self.subTest(snippet=bad):
                self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'p-1', 'under': None, 'snippet': bad}, ok=False, env=e(1))['ok'])
        self.assertEqual(self.thread(env=e(1))['messages'], [])
        # parts never hold more than a whole snippet: the part that would pass 20 MB is refused
        big = 'x' * 1_500_000
        for i in range(13):
            self.assertTrue(self.post({'op': 'snippet-part', 'thread': 'topic', 'cid': 'p-2', 'i': i, 'n': 14, 'text': big}, env=e(1))['ok'])
        self.assertFalse(self.post({'op': 'snippet-part', 'thread': 'topic', 'cid': 'p-2', 'i': 13, 'n': 14, 'text': big}, ok=False, env=e(1))['ok'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'p-2', 'under': None, 'snippet': {'parts': 14}}, ok=False, env=e(1))['ok'])
        # and only a few big texts are on their way at once (p-1 and p-2 are two of them)
        for k in range(6):
            self.assertTrue(self.post(part(cid=f'q-{k}'), env=e(1))['ok'])
        crowd = self.post(part(cid='q-6'), ok=False, env=e(1))
        self.assertFalse(crowd['ok'])
        # a closed thread takes no parts
        self.run_cli('close', 'topic', env=e(1))
        self.assertFalse(self.post(part(cid='p-3'), ok=False, env=e(1))['ok'])
        # what never became a message is cleared after some hours by the sweep
        self.assertTrue(any((self.root / '.threads-config').rglob('*.part')))
        self.run_cli('sweep', env=e(8))
        self.assertFalse(any((self.root / '.threads-config').rglob('*.part')))

    def test_a_big_text_file_from_the_command_line(self):
        self.new()
        log = self.root / 'crash.ips'
        log.write_text('x' * 7_000_000, encoding='utf-8')
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'fork', 'דוח', '--snippet', str(log), '--state', 'working', '--note', 'בודק').stdout.strip(), 'm1')
        self.assertEqual(self.thread()['messages'][0]['snippet']['bytes'], 7_000_000)
        log.write_text('x' * 20_000_001, encoding='utf-8')
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח', '--snippet', str(log), '--state', 'working', '--note', 'בודק', ok=False)

    def test_snippets_from_the_command_line(self):
        self.new()
        log = self.root / 'run.log'
        log.write_text(self.LONG, encoding='utf-8')
        # an agent attaches a file to its message
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'fork', 'הלוג המלא מצורף', '--snippet', str(log), '--state', 'working', '--note', 'בודק').stdout.strip(), 'm1')
        m = self.thread()['messages'][0]
        self.assertEqual((m['text'], m['snippet']['file'], m['snippet']['name'], m['snippet']['only']), ('הלוג המלא מצורף', 'snippets/topic/m1.log', 'run.log', False))
        self.assertEqual(self.run_cli('snippet', 'topic', 'm1').stdout, self.LONG)
        self.assertIn(str(self.board / 'snippets/topic/m1.log'), self.run_cli('show', 'topic').stdout)
        self.assertEqual(self.js('show', 'topic', '--json')['messages'][0]['snippet']['path'], str(self.board / 'snippets/topic/m1.log'))
        # an agent message is inline up to 50 000 characters; a longer one is kept as a snippet instead of being refused
        self.run_cli('say', 'topic', '--from', 'fork', '-', input='x' * 50_000)
        self.assertNotIn('snippet', self.thread()['messages'][1])
        self.run_cli('say', 'topic', '--from', 'fork', '-', input=self.LONG)
        m = self.thread()['messages'][2]
        self.assertEqual((m['snippet']['only'], m['snippet']['chars']), (True, len(self.LONG)))
        # what the owner says through the CLI follows the page's rule: over 4000 characters is a snippet
        self.run_cli('say', 'topic', '--from', 'owner', 'ג' * 4001)
        self.assertEqual(self.thread()['messages'][3]['snippet']['chars'], 4001)
        # refusals: a missing file, a file that is not text, a snippet of nothing (too large: test_a_big_text_file_from_the_command_line)
        (self.root / 'bin.dat').write_bytes(b'\xff\xfe\x00binary')
        (self.root / 'empty.txt').write_text('  \n')
        for name in ('nope.txt', 'bin.dat', 'empty.txt'):
            with self.subTest(file=name):
                self.run_cli('say', 'topic', '--from', 'fork', 'x', '--snippet', str(self.root / name), ok=False)
        self.run_cli('snippet', 'topic', 'm2', ok=False)                    # that message has none
        self.run_cli('snippet', 'topic', 'm99', ok=False)
        self.assertEqual(len(self.thread()['messages']), 4)
        # removing the thread removes its files; the files of another thread stay
        self.new('other')
        self.run_cli('say', 'other', '--from', 'fork', 'x', '--snippet', str(log))
        self.run_cli('rm', 'topic', '--yes')
        self.assertFalse((self.board / 'snippets/topic').exists())
        self.assertTrue((self.board / 'snippets/other/m1.log').exists())

    def test_snippet_command_reads_only_inside_the_snippets_folder(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'x' * 60_000)
        path = self.board / 'state.json'
        data = json.loads(path.read_text())
        secret = self.root / 'secret.txt'
        secret.write_text('do not print me')
        for evil in ('../../secret.txt', str(secret), 'snippets/../../../secret.txt', 'state.json'):
            with self.subTest(file=evil):
                data['threads']['topic']['messages'][0]['snippet']['file'] = evil
                path.write_text(json.dumps(data))
                r = self.run_cli('snippet', 'topic', 'm1', ok=False)
                self.assertNotIn('do not print me', r.stdout + r.stderr)

    # ── rename, tasks, reply-to, reactions, snooze, drafts ──────────────────

    def test_rename_keeps_the_id_and_the_slot(self):
        self.new()
        slot = self.thread()['slot']
        self.run_cli('rename', 'topic', '  שם   חדש\n')
        self.assertEqual(self.thread()['title'], 'שם חדש')
        self.assertEqual(self.post({'op': 'rename', 'thread': 'topic', 'title': 'מהדף'}), {'ok': True, 'thread': 'topic', 'op': 'rename', 'title': 'מהדף'})
        for bad in ('', '   ', 'x' * 201, 5, None):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'rename', 'thread': 'topic', 'title': bad}, ok=False)['ok'])
        self.run_cli('rename', 'topic', '', ok=False)
        t = self.thread()
        self.assertEqual((t['title'], t['slot'], t['id']), ('מהדף', slot, 'topic'))
        self.run_cli('close', 'topic')
        self.assertTrue(self.post({'op': 'rename', 'thread': 'topic', 'title': 'גם כשהוא סגור'})['ok'])
        self.assertFalse(self.record.exists())                                    # nobody is mailed about a name

    def test_a_task_title_is_corrected_in_place(self):
        """The owner (a tasks thread, m132): a task described wrong is corrected, not archived and added again (it would
        lose its number). `threads task set <id> <n> --text`: the number, status, owner and note stay; the old words
        are kept in the task's history with when and by whom."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבנות את א', '--owner', 'fork', env=e(1))
        self.run_cli('task', 'set', 'topic', '1', 'building', '--note', 'רץ', env=e(2))
        self.run_cli('task', 'set', 'topic', '1', '--text', '  לבנות את ב  ', '--owner', 'tower', env=e(3))
        k = self.thread(env=e(3))['tasks'][0]
        self.assertEqual((k['n'], k['text'], k['status'], k['note'], k['owner'], k['updated']),
                         (1, 'לבנות את ב', 'building', 'רץ', 'tower', self.T0 + 3 * 3600))
        # who corrected it: the owner before the change (not the one it is handed to), or --by
        self.assertEqual(k['history'], [{'text': 'לבנות את א', 'ts': self.T0 + 3 * 3600, 'by': 'fork'}])
        # with a status too, in one call; a second correction adds to the history
        self.run_cli('task', 'set', 'topic', '1', 'done', '--text', 'לבנות את ג', '--by', 'worker-3', env=e(4))
        k = self.thread(env=e(4))['tasks'][0]
        self.assertEqual((k['text'], k['status']), ('לבנות את ג', 'done'))
        self.assertEqual([(h['text'], h['by']) for h in k['history']], [('לבנות את א', 'fork'), ('לבנות את ב', 'worker-3')])
        self.run_cli('task', 'set', 'topic', '1', '--text', 'x', '--by', 'Owner', ok=False, env=e(4))
        # the same words: nothing to record
        self.run_cli('task', 'set', 'topic', '1', '--text', 'לבנות את ג', env=e(5))
        self.assertEqual(len(self.thread(env=e(5))['tasks'][0]['history']), 2)
        # refused: empty words, nothing to change, no such task
        self.run_cli('task', 'set', 'topic', '1', '--text', '   ', ok=False, env=e(6))
        self.run_cli('task', 'set', 'topic', '1', ok=False, env=e(6))
        self.run_cli('task', 'set', 'topic', '9', '--text', 'x', ok=False, env=e(6))
        k = self.thread(env=e(6))['tasks'][0]
        self.assertEqual((k['text'], len(k['history'])), ('לבנות את ג', 2))
        self.assertIn('לבנות את ג', self.run_cli('tasks', 'topic', env=e(6)).stdout)

    def test_tasks_of_a_thread(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.ingest(text='1. לבנות את א\n2. לבדוק את ב', env=e(1))                 # m1: two requests in one message
        self.run_cli('ack', 'topic', 'm1', env=e(1.5))                          # picked up (a reply nobody picked up blocks the archive by itself)
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'לבנות  את א', '--from-msg', 'm1', '--owner', 'fork', env=e(2)).stdout.strip(), '1')
        self.assertEqual(self.run_cli('task', 'add', 'topic', 'לבדוק את ב', env=e(2)).stdout.strip(), '2')
        self.run_cli('task', 'add', 'topic', '  ', ok=False, env=e(2))
        self.run_cli('task', 'add', 'topic', 'x', '--from-msg', 'm9', ok=False, env=e(2))
        self.run_cli('task', 'set', 'topic', '1', 'building', '--note', 'רץ ב-CI', env=e(3))
        self.run_cli('task', 'set', 'topic', '2', 'nonsense', ok=False, env=e(3))
        self.run_cli('task', 'set', 'topic', '9', 'done', ok=False, env=e(3))
        tasks = self.thread(env=e(3))['tasks']
        self.assertEqual([(k['n'], k['text'], k['status'], k['owner'], k['note'], k['from']) for k in tasks],
                         [(1, 'לבנות את א', 'building', 'fork', 'רץ ב-CI', 'm1'), (2, 'לבדוק את ב', 'todo', '', '', None)])
        self.assertEqual((tasks[0]['ts'], tasks[0]['updated']), (self.T0 + 2 * 3600, self.T0 + 3 * 3600))
        # his one tap on the page
        self.assertEqual(self.post({'op': 'task', 'thread': 'topic', 'n': 2, 'status': 'done'}, env=e(4)),
                         {'ok': True, 'thread': 'topic', 'op': 'task', 'n': 2, 'status': 'done'})
        self.assertEqual(self.thread(env=e(4))['tasks'][1]['by'], 'owner')
        for bad in ({'n': 'x'}, {'n': 99}, {'n': True}, {'status': 'zz'}, {'status': None}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'task', 'thread': 'topic', 'n': 2, 'status': 'todo', **bad}, ok=False, env=e(4))['ok'])
        self.assertIn('building', self.run_cli('tasks', 'topic', env=e(4)).stdout)
        self.assertEqual([k['n'] for k in json.loads(self.run_cli('tasks', 'topic', '--json', env=e(4)).stdout)], [1, 2])
        # a task that is not done keeps the thread from archiving itself (and "done" over it must be forced)
        self.run_cli('state', 'topic', 'done', ok=False, env=e(5))
        self.run_cli('state', 'topic', 'done', '--force', env=e(5))
        self.assertIsNone(self.thread(env=e(5))['archive_at'])
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(6))
        self.assertIsNotNone(self.thread(env=e(6))['archive_at'])
        self.assertEqual(len(json.loads(self.record.read_text().splitlines()[0])['args']), 1)  # only his reply mailed the tower
        self.assertEqual(len(self.record.read_text().splitlines()), 1)

    def test_reply_to_a_message_and_reactions(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה ראשונה\nעם פירוט ארוך ' + 'x' * 300, '--state', 'working')
        self.run_cli('say', 'topic', '--from', 'fork', 'הצעה שנייה', '--state', 'working')
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'את זה', 'cid': 'c1', 'under': None, 'reply_to': 'm1'})['ok'])
        m = self.thread()['messages'][-1]
        self.assertEqual((m['reply_to']['id'], m['reply_to']['from']), ('m1', 'fork'))
        self.assertTrue(m['reply_to']['text'].startswith('הצעה ראשונה עם פירוט') and len(m['reply_to']['text']) <= 140)
        row = self.js('pending')[0]
        self.assertEqual((row['reply_to']['id'], row['reply_to']['from']), ('m1', 'fork'))
        self.assertTrue(row['reply_to']['text'].startswith('הצעה ראשונה\nעם פירוט ארוך xxx') and len(row['reply_to']['text']) > 300)   # the fork gets all of it
        for bad in ('m99', 5, ''):
            self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': 'c2', 'reply_to': bad}, ok=False)['ok'])
        # reactions: quick feedback that changes nobody's turn
        before = {k: self.thread()[k] for k in ('state', 'note', 'state_ts', 'question')}
        mails = len(self.record.read_text().splitlines())
        self.assertEqual(self.post({'op': 'react', 'thread': 'topic', 'msg': 'm2', 'emoji': '👍', 'on': True}),
                         {'ok': True, 'thread': 'topic', 'op': 'react', 'msg': 'm2', 'emoji': '👍', 'on': True})
        self.assertEqual(self.thread()['messages'][1]['reactions']['👍']['by'], 'owner')
        self.assertTrue(self.post({'op': 'react', 'thread': 'topic', 'msg': 'm2', 'emoji': '👍', 'on': False})['ok'])
        self.assertNotIn('👍', self.thread()['messages'][1].get('reactions', {}))
        self.assertEqual(len(self.record.read_text().splitlines()), mails)                # 👍 wakes nobody
        self.assertTrue(self.post({'op': 'react', 'thread': 'topic', 'msg': 'm2', 'emoji': '❓', 'on': True})['ok'])
        records = [json.loads(line)['args'][0] for line in self.record.read_text().splitlines()]
        self.assertEqual(len(records), mails + 1)                                         # a question mark does
        self.assertIn('❓', records[-1])
        self.assertIn('topic', records[-1])
        for bad in ({'emoji': '💩'}, {'msg': 'm99'}, {'on': 'yes'}, {'msg': 5}):
            self.assertFalse(self.post({'op': 'react', 'thread': 'topic', 'msg': 'm2', 'emoji': '👍', 'on': True, **bad}, ok=False)['ok'])
        self.assertEqual({k: self.thread()[k] for k in ('state', 'note', 'state_ts', 'question')}, before)

    def test_he_answers_words_he_marked_in_a_message(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'שלוש הצעות:\n1. **להמתין** לשבוע הבא\n2. לדחוף היום\n3. לבטל', env=e(0))
        reply = {'op': 'reply', 'thread': 'topic', 'cid': 'q1', 'text': 'את זה', 'reply_to': 'm1'}
        self.assertTrue(self.post({**reply, 'quote': '  להמתין לשבוע הבא\u202e \n\n2. לדחוף היום\x00'}, env=e(1))['ok'])
        m = self.thread(env=e(1))['messages'][1]
        self.assertEqual(m['reply_to'], {'id': 'm1', 'from': 'fork', 'text': 'שלוש הצעות: 1. להמתין לשבוע הבא 2. לדחוף היום 3. לבטל', 'quote': 'להמתין לשבוע הבא\n2. לדחוף היום'})
        row = self.js('pending')[0]['reply_to']
        self.assertEqual((row['quote'], row['text'].startswith('שלוש הצעות:\n1. **להמתין**')), ('להמתין לשבוע הבא\n2. לדחוף היום', True))      # the agent gets the whole message and the marked words
        self.assertIn('[בתגובה ל-m1: «להמתין לשבוע הבא 2. לדחוף היום»]', self.run_cli('show', 'topic', env=e(1)).stdout)
        self.assertIn('quote', json.loads((self.board / 'state.json').read_text())['ops'])
        for bad in ({'quote': 'x' * 501}, {'quote': '\n'.join('abcdefg')}, {'quote': ' \u200f '}, {'quote': 5}, {'quote': ['a']}):
            with self.subTest(bad=str(bad)[:40]):
                self.assertFalse(self.post({**reply, 'cid': 'q2', **bad}, ok=False, env=e(2))['ok'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'q3', 'text': 'בלי הודעה', 'quote': 'מילים'}, ok=False, env=e(2))['ok'])      # words of which message?
        self.assertEqual(len(self.thread(env=e(2))['messages']), 2)

    def test_snooze_sleeps_quietly_and_wakes_loudly(self):
        e, H = self.at, 3600
        local = lambda hours: time.strftime('%Y-%m-%d %H:%M', time.localtime(self.T0 + hours * H))
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('state', 'topic', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('snooze', 'topic', '--until', local(10), env=e(1))
        self.assertEqual(self.thread(env=e(1))['snooze']['until'], self.T0 + 10 * H)
        self.assertTrue(self.post({'op': 'snooze', 'thread': 'topic', 'until': self.T0 + 20 * H}, env=e(2))['ok'])       # the page sends a time
        self.assertEqual(self.thread(env=e(2))['snooze']['until'], self.T0 + 20 * H)
        for bad in (self.T0, 'x', None, self.T0 + 400 * 24 * H):
            self.assertFalse(self.post({'op': 'snooze', 'thread': 'topic', 'until': bad}, ok=False, env=e(2))['ok'])
        self.run_cli('snooze', 'topic', '--until', local(1), ok=False, env=e(2))        # a time that passed
        self.run_cli('list', env=e(19.9))
        self.assertIn('snooze', self.thread(env=e(19.9)))
        self.assertFalse(self.record.exists())                                           # going to sleep wakes nobody
        self.run_cli('list', env=e(20.1))                                                # the first command after the time
        t = self.thread(env=e(20.1))
        self.assertNotIn('snooze', t)
        self.assertEqual((t['state'], t['reminder']['until']), ('on-owner', self.T0 + 20 * H))
        self.assertIn('בונה', t['note'])
        records = [json.loads(line)['args'][0] for line in self.record.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertIn('[threads] snooze woke topic', records[0])
        self.run_cli('list', env=e(21))
        self.assertEqual(len(self.record.read_text().splitlines()), 1)                    # woken once
        # unsnooze: cancels a sleep, or dismisses the reminder
        self.assertTrue(self.post({'op': 'unsnooze', 'thread': 'topic'}, env=e(22))['ok'])
        self.assertNotIn('reminder', self.thread(env=e(22)))
        self.run_cli('snooze', 'topic', '--until', '+2h', env=e(23))
        self.assertEqual(self.thread(env=e(23))['snooze']['until'], self.T0 + 25 * H)
        self.run_cli('unsnooze', 'topic', env=e(23.5))
        self.assertNotIn('snooze', self.thread(env=e(26)))
        self.assertEqual(len(self.record.read_text().splitlines()), 1)
        # "tomorrow 09:00" is tomorrow by the clock of this machine
        self.run_cli('snooze', 'topic', '--until', 'tomorrow 09:00', env=e(30))
        day = time.localtime(self.T0 + 30 * H + 24 * H)
        expect = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 9, 0, 0, 0, 0, -1))
        self.assertEqual(self.thread(env=e(30))['snooze']['until'], expect)
        # a sleeping thread does not archive itself; his reply wakes it at once
        self.run_cli('state', 'topic', 'done', env=e(31))
        self.assertIsNone(self.thread(env=e(31))['archive_at'])
        self.ingest(text='בעצם עכשיו', cid='c9', env=e(32))
        self.assertNotIn('snooze', self.thread(env=e(32)))
        self.run_cli('close', 'topic', env=e(33))
        self.run_cli('snooze', 'topic', '--until', '+1h', ok=False, env=e(33))          # only an open thread sleeps

    def test_the_timer_sweep_is_silent_until_something_happens(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('state', 'topic', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('snooze', 'topic', '--until', '+2h', env=e(0))
        state = (self.board / 'state.json').read_bytes()
        self.assertEqual(self.run_cli('sweep', '--quiet', env=e(1)).stdout, '')            # a minute with nothing due: no line, no write
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        line = self.run_cli('sweep', '--quiet', env=e(2.1)).stdout
        self.assertRegex(line, r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d woke: topic\n$')
        self.assertEqual(self.run_cli('sweep', '--quiet', env=e(2.2)).stdout, '')
        self.run_cli('unsnooze', 'topic', env=e(3))
        self.run_cli('state', 'topic', 'done', env=e(3))
        self.assertRegex(self.run_cli('sweep', '--quiet', env=e(40)).stdout, r' archived: topic\n$')
        self.assertEqual(json.loads(self.run_cli('sweep', env=e(41)).stdout), [])                                   # without the flag: the list, as before

    def test_drafts_are_kept_beside_the_state(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        state = (self.board / 'state.json').read_bytes()
        os.utime(self.board / '.pulse', (1, 1))
        self.assertEqual(self.post({'op': 'draft', 'thread': 'topic', 'text': 'חצי משפט'}, env=e(1)),
                         {'ok': True, 'thread': 'topic', 'op': 'draft', 'ts': self.T0 + 3600})
        drafts = lambda: json.loads((self.board / 'drafts.json').read_text())['drafts']
        self.assertEqual(drafts()['topic'], {'text': 'חצי משפט', 'ts': self.T0 + 3600})
        self.assertTrue(self.post({'op': 'draft', 'thread': '_new', 'text': 'נושא שעוד לא נפתח'}, env=e(1))['ok'])      # the new-topic form
        for bad in ({'thread': 'ghost'}, {'text': 5}, {'text': 'x' * 20_001}, {'thread': 7}):
            self.assertFalse(self.post({'op': 'draft', 'thread': 'topic', 'text': 'x', **bad}, ok=False, env=e(1))['ok'])
        # a draft is not a message: the state, the pages and the tower are left alone
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.assertEqual((self.board / '.pulse').stat().st_mtime, 1)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.js('pending'), [])
        # deleting leaves a marker, so another device knows it was cleared and when
        self.assertTrue(self.post({'op': 'draft', 'thread': 'topic', 'text': ''}, env=e(2))['ok'])
        self.assertEqual(drafts()['topic'], {'text': '', 'ts': self.T0 + 2 * 3600})
        # a sent reply clears the draft of its thread
        self.post({'op': 'draft', 'thread': 'topic', 'text': 'כמעט שלחתי'}, env=e(3))
        self.ingest(text='שלחתי', env=e(4))
        self.assertEqual(drafts()['topic'], {'text': '', 'ts': self.T0 + 4 * 3600})
        self.assertEqual(drafts()['_new']['text'], 'נושא שעוד לא נפתח')

    def test_grouped_and_multi_select_answers(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        groups = self.root / 'q.json'
        groups.write_text(json.dumps([{'title': 'tools', 'items': ['alpha-tool', {'text': 'beta-tool', 'recommended': True}, 'epsilon']},
                                      {'title': 'orbit', 'items': ['shopflow', 'gamma-pr']}], ensure_ascii=False))
        self.assertEqual(self.run_cli('ask', 'topic', 'אילו חלונות לסגור?', '--groups-file', str(groups), env=e(1)).stdout.strip(), 'm1')
        q = self.thread(env=e(1))['question']
        self.assertEqual((q['multi'], q['options']), (True, ['alpha-tool', 'beta-tool', 'epsilon', 'shopflow', 'gamma-pr']))    # flat, for a page that knows only buttons
        self.assertEqual(q['groups'], [{'title': 'tools', 'items': [{'text': 'alpha-tool', 'recommended': False}, {'text': 'beta-tool', 'recommended': True}, {'text': 'epsilon', 'recommended': False}]},
                                       {'title': 'orbit', 'items': [{'text': 'shopflow', 'recommended': False}, {'text': 'gamma-pr', 'recommended': False}]}])
        reply = {'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'q': 'm1'}
        for bad in ({'answer': {'tools': ['nope']}}, {'answer': {'ghost': ['shopflow']}}, {'answer': {'tools': 'alpha-tool'}}, {'answer': ['alpha-tool']},
                    {'answer': {}}, {'answer': {'tools': []}, 'note': '  '}, {'answer': {'tools': ['alpha-tool']}, 'note': 5}, {'answer': {'tools': ['alpha-tool']}, 'q': 'm0'}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({**reply, **bad}, ok=False, env=e(2))['ok'])
        self.assertEqual(len(self.thread(env=e(2))['messages']), 1)
        self.assertTrue(self.post({**reply, 'answer': {'orbit': ['gamma-pr'], 'tools': ['epsilon', 'alpha-tool']}, 'note': 'את השאר להשאיר'}, env=e(3))['ok'])
        t = self.thread(env=e(3))
        m = t['messages'][-1]
        self.assertEqual(m['text'], '**tools:** alpha-tool, epsilon\n**orbit:** gamma-pr\nהערה: את השאר להשאיר')                 # the written order, readable
        self.assertEqual(m['re'], {'q': 'm1', 'text': 'אילו חלונות לסגור?', 'answer': {'tools': ['alpha-tool', 'epsilon'], 'orbit': ['gamma-pr']}, 'note': 'את השאר להשאיר'})
        self.assertEqual((t['question'], t['state']), (None, 'working'))
        self.assertEqual(json.loads(self.run_cli('pending', env=e(3)).stdout)[0]['re']['answer'], {'tools': ['alpha-tool', 'epsilon'], 'orbit': ['gamma-pr']})
        # a flat multi-select; a note alone is an answer too; an old page may still tap one option
        self.run_cli('ask', 'topic', 'מה לכלול?', '--multi', '--options', 'א, ב ,ג', env=e(4))
        q = self.thread(env=e(4))['question']
        self.assertEqual((q['groups'], q['options']), ([{'title': '', 'items': [{'text': k, 'recommended': False} for k in 'אבג']}], ['א', 'ב', 'ג']))
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c2', 'q': q['id'], 'answer': {'': []}, 'note': 'אף אחד, תסביר קודם'}, env=e(5))['ok'])
        self.assertEqual(self.thread(env=e(5))['messages'][-1]['text'], 'לא נבחר דבר\nהערה: אף אחד, תסביר קודם')
        self.run_cli('ask', 'topic', 'שוב?', '--multi', '--options', 'א,ב', env=e(6))
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c3', 'q': self.thread(env=e(6))['question']['id'], 'text': 'ב'}, env=e(7))['ok'])
        # a single-choice question does not take a grouped answer; bad group files are refused
        self.run_cli('ask', 'topic', 'כן או לא?', '--options', 'כן,לא', env=e(8))
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c4', 'q': self.thread(env=e(8))['question']['id'], 'answer': {'': ['כן']}}, ok=False, env=e(9))['ok'])
        for bad in ([], [{'title': 'a', 'items': []}], [{'title': 'a', 'items': ['x']}, {'title': 'a', 'items': ['y']}], [{'title': 'a', 'items': ['x', 'x']}],
                    [{'title': 'a', 'items': ['x' * 81]}], 'x', [{'items': ['x']}] * 13):
            groups.write_text(json.dumps(bad))
            self.run_cli('ask', 'topic', 'רע', '--groups-file', str(groups), ok=False, env=e(9))
        self.run_cli('ask', 'topic', 'רע', '--multi', ok=False, env=e(9))

    def test_a_new_topic_from_the_page(self):
        e = self.at
        self.run_cli('new', 'older', 'נושא ישן', env=e(0))
        self.post({'op': 'draft', 'thread': '_new', 'text': '{"title":"x"}'}, env=e(0))
        got = self.post({'op': 'new', 'title': 'Snap build 17', 'text': 'תבדוק למה הבנייה נכשלת', 'cid': 'n1',
                         'context': 'רקע קצר', 'links': [{'label': 'PR', 'url': 'https://example.com/pr/1'}]}, env=e(1))
        self.assertEqual(got, {'ok': True, 'op': 'new', 'thread': 'snap-build-17', 'msg': 'm1', 'msg_id': 'm1', 'dup': False})
        t = self.thread('snap-build-17', env=e(1))
        self.assertEqual((t['title'], t['slot'], t['state'], t['context'], t['links'], t['opened_by']),
                         ('Snap build 17', 2, 'working', 'רקע קצר', [{'label': 'PR', 'url': 'https://example.com/pr/1'}], 'owner'))
        self.assertEqual((t['messages'][0]['text'], t['messages'][0]['status'], 'title_pending' in t), ('תבדוק למה הבנייה נכשלת', 'pending', False))
        mail = json.loads(self.record.read_text().splitlines()[-1])['args'][0]
        self.assertIn('[threads] NEW topic snap-build-17 opened by owner (m1)', mail)
        self.assertNotIn('threads rename', mail)
        self.assertEqual(json.loads((self.board / 'drafts.json').read_text())['drafts']['_new']['text'], '')       # the form's draft is over
        self.assertIn('new', json.loads((self.board / 'state.json').read_text())['ops'])
        # the page sent it twice: the same thread
        again = self.post({'op': 'new', 'title': 'Snap build 17', 'text': 'תבדוק למה הבנייה נכשלת', 'cid': 'n1'}, env=e(1))
        self.assertEqual((again['thread'], again['dup']), ('snap-build-17', True))
        # the same title as an open thread: refused, and the page is told which thread it is
        refused = self.post({'op': 'new', 'title': 'snap BUILD 17', 'text': 'שוב', 'cid': 'n2'}, ok=False, env=e(1))
        self.assertEqual((refused['ok'], refused['thread']), (False, 'snap-build-17'))
        # no title: the first words stand in, and the tower is told a title is owed
        got = self.post({'op': 'new', 'text': 'המזגן בסלון לא מגיב לפקודות מהטלפון כבר יומיים, צריך לבדוק את זה', 'cid': 'n3'}, env=e(2))
        t = self.thread(got['thread'], env=e(2))
        self.assertEqual((t['title'], t['title_pending']), ('המזגן בסלון לא מגיב לפקודות מהטלפון כבר…', True))
        self.assertEqual(got['thread'], 'hmzgn-bslvn-la-mgyb')
        mail = json.loads(self.record.read_text().splitlines()[-1])['args'][0]
        self.assertIn(f'threads rename {got["thread"]}', mail)
        self.assertTrue([r for r in self.js('pending') if r['thread'] == got['thread']][0]['title_pending'])
        self.run_cli('rename', got['thread'], 'מזגן הסלון', env=e(3))
        self.assertNotIn('title_pending', self.thread(got['thread'], env=e(3)))
        # the page's own stand-in title is taken as it is; a title only is a message too; ids never collide
        got = self.post({'op': 'new', 'title': 'טיוטה של כותרת…', 'title_pending': True, 'text': 'גוף', 'cid': 'n4'}, env=e(4))
        self.assertTrue(self.thread(got['thread'], env=e(4))['title_pending'])
        self.assertTrue(self.post({'op': 'rename', 'thread': got['thread'], 'title': 'כותרת אמיתית'}, env=e(4))['ok'])
        self.assertNotIn('title_pending', self.thread(got['thread'], env=e(4)))
        got = self.post({'op': 'new', 'title': '🙂🙂', 'cid': 'n5'}, env=e(5))
        self.assertEqual((got['thread'], self.thread('t-1', env=e(5))['messages'][0]['text']), ('t-1', '🙂🙂'))
        self.run_cli('close', 'snap-build-17', env=e(6))
        self.assertEqual(self.post({'op': 'new', 'title': 'Snap build 17', 'text': 'סיבוב שני', 'cid': 'n6'}, env=e(6))['thread'], 'snap-build-17-2')
        count = len(json.loads((self.board / 'state.json').read_text())['threads'])
        for bad in ({'text': '', 'title': ' '}, {'text': 'x' * 8001}, {'cid': ''}, {'cid': 5}, {'title': 'x' * 121}, {'title': 7}, {'links': 'x'},
                    {'links': [{'label': 'a', 'url': 'javascript:alert(1)'}]}, {'context': 5}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'new', 'title': 'עוד נושא', 'text': 'גוף', 'cid': 'n9', **bad}, ok=False, env=e(7))['ok'])
        self.assertEqual(len(json.loads((self.board / 'state.json').read_text())['threads']), count)

    @staticmethod
    def png(w=3, h=2, extra=()):
        import struct, zlib
        chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + b''.join(chunk(k, d) for k, d in extra)
                + chunk(b'IDAT', zlib.compress(b'\0' * (h * (1 + 3 * w)))) + chunk(b'IEND', b''))

    @staticmethod
    def jpeg(w=40, h=30, turn=6):
        import struct
        seg = lambda marker, data: b'\xff' + bytes([marker]) + struct.pack('>H', len(data) + 2) + data
        tiff = b'II*\0' + struct.pack('<IH', 8, 2) + struct.pack('<HHIHH', 0x0112, 3, 1, turn, 0) + struct.pack('<HHII', 0x8825, 4, 1, 99) + struct.pack('<I', 0) + b'GPS-HOME-32.08,34.78'
        return (b'\xff\xd8' + seg(0xE0, b'JFIF\0\x01\x01\0\0\x01\0\x01\0\0') + seg(0xE1, b'Exif\0\0' + tiff) + seg(0xE1, b'http://ns.adobe.com/xap/1.0/\0<x>XMP-OWNER</x>')
                + seg(0xED, b'Photoshop 3.0\0IPTC-CITY') + seg(0xFE, b'COMMENT-BY-CAMERA') + seg(0xE2, b'ICC_PROFILE\0\x01\x01profile')
                + seg(0xC0, struct.pack('>BHHB', 8, h, w, 1) + b'\x01\x11\0') + seg(0xDA, b'\x01\x01\0\0\x3f\0') + b'\x12\xff\x00\x34\xff\xd0\x56' + b'\xff\xd9'
                + b'SEFT-TRAILER-UTC-2026')

    @staticmethod
    def gif(w=5, h=7):
        import struct
        return (b'GIF89a' + struct.pack('<HHBBB', w, h, 0, 0, 0) + b'\x21\xfe\x08GPS-HOME\0' + b'\x2c' + struct.pack('<HHHHB', 0, 0, w, h, 0)
                + b'\x02\x02\x4c\x01\0' + b';' + b'TRAILER-AFTER-THE-END')

    @staticmethod
    def webp():
        import struct
        chunk = lambda kind, data: kind + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b'')
        body = (b'WEBP' + chunk(b'VP8X', bytes([0x0C, 0, 0, 0]) + (9).to_bytes(3, 'little') + (4).to_bytes(3, 'little'))
                + chunk(b'VP8L', b'\x2f' + ((9) | (4 << 14)).to_bytes(4, 'little') + b'\0') + chunk(b'EXIF', b'GPS-HOME') + chunk(b'XMP ', b'<x>OWNER</x>'))
        return b'RIFF' + struct.pack('<I', len(body)) + body

    def test_pictures_in_messages(self):
        import base64
        e, b64 = self.at, lambda raw: base64.b64encode(raw).decode()
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        png = self.png(extra=((b'tEXt', b'Author\0owner'), (b'eXIf', b'II*\0GPS-HOME'), (b'tIME', b'\x07\xea\x0b\x10\x02\x00\x00')))
        reply = {'op': 'reply', 'thread': 'topic', 'cid': 'p1', 'text': ''}
        got = self.post({**reply, 'images': [{'name': '../../IMG_1.PNG', 'type': 'image/png', 'data': b64(png), 'caption': '  המסך   שנתקע '},
                                             {'name': 'photo.jpg', 'type': 'image/jpeg', 'data': b64(self.jpeg())}]}, env=e(1))
        self.assertTrue(got['ok'])
        m = self.thread(env=e(1))['messages'][0]
        self.assertEqual((m['text'], m['placeholder'], m['status']), ('2 תמונות', True, 'pending'))
        self.assertEqual(m['images'][0], {'file': 'uploads/topic/m1-1.png', 'name': 'IMG_1.PNG', 'bytes': len(self.png()), 'w': 3, 'h': 2, 'caption': 'המסך שנתקע',
                                          'path': str((self.board / 'uploads/topic/m1-1.png').resolve())})
        self.assertEqual((self.board / 'uploads/topic/m1-1.png').read_bytes(), self.png())                    # what the camera added is gone, the pixels are not
        stored = (self.board / 'uploads/topic/m1-2.jpg').read_bytes()
        for secret in (b'GPS-HOME', b'XMP-OWNER', b'IPTC-CITY', b'COMMENT-BY-CAMERA', b'SEFT-TRAILER'):
            self.assertNotIn(secret, stored)
        self.assertIn(b'ICC_PROFILE', stored)                                                                  # colours stay right
        self.assertTrue(stored.startswith(b'\xff\xd8\xff\xe1') and stored.endswith(b'\x12\xff\x00\x34\xff\xd0\x56\xff\xd9'))
        self.assertEqual((m['images'][1]['w'], m['images'][1]['h'], 'caption' in m['images'][1]), (30, 40, False))     # stored turned: shown 30 wide
        self.assertEqual(self.run_cli('show', 'topic', env=e(1)).stdout.count('[תמונה: '), 2)
        row = self.js('pending')[0]
        self.assertEqual([(i['path'], i['caption']) for i in row['images']],
                         [(str((self.board / 'uploads/topic/m1-1.png').resolve()), 'המסך שנתקע'), (str((self.board / 'uploads/topic/m1-2.jpg').resolve()), None)])
        self.assertIn('images', json.loads((self.board / 'state.json').read_text())['ops'])
        # text beside a picture is his text; webp and gif are taken too
        self.assertTrue(self.post({**reply, 'cid': 'p2', 'text': 'ככה זה נראה', 'images': [{'data': b64(self.webp())}, {'data': b64(self.gif())}]}, env=e(2))['ok'])
        m = self.thread(env=e(2))['messages'][1]
        self.assertEqual((m['text'], 'placeholder' in m, [(i['file'], i['w'], i['h']) for i in m['images']]),
                         ('ככה זה נראה', False, [('uploads/topic/m2-1.webp', 10, 5), ('uploads/topic/m2-2.gif', 5, 7)]))
        stored = (self.board / 'uploads/topic/m2-1.webp').read_bytes()
        self.assertEqual((self.board / 'uploads/topic/m2-2.gif').read_bytes(), self.gif().replace(b'\x21\xfe\x08GPS-HOME\0', b'').replace(b'TRAILER-AFTER-THE-END', b''))
        self.assertTrue(b'GPS-HOME' not in stored and b'OWNER' not in stored and stored[20] & 0x0C == 0 and int.from_bytes(stored[4:8], 'little') == len(stored) - 8)
        # refused before anything is written
        files = sorted(p.name for p in (self.board / 'uploads/topic').iterdir())
        for bad in ([], [{'data': b64(png)}] * 5, [{'data': 'not base64!'}], [{'data': b64(b'<svg onload=alert(1)>')}], [{'data': b64(b'\x89PNG\r\n\x1a\n' + b'\0' * 40)}],
                    [{'data': b64(png), 'caption': 'x' * 501}], [{'data': b64(png), 'caption': 5}], [{'name': 'a.png'}], 'x', [{'data': b64(self.jpeg()[:-30])}],
                    [{'data': b64(b'\xff\xd8\xff' + b'\0' * 2_000_001)}]):
            with self.subTest(bad=str(bad)[:60]):
                self.assertFalse(self.post({**reply, 'cid': 'p3', 'images': bad}, ok=False, env=e(3))['ok'])
        self.assertEqual(sorted(p.name for p in (self.board / 'uploads/topic').iterdir()), files)
        self.assertEqual(len(self.thread(env=e(3))['messages']), 2)
        # an agent sends pictures and a page of its own
        shot, page = self.root / 'shot.png', self.root / 'chart.html'
        shot.write_bytes(png)
        page.write_text('<h1>גרף</h1><script>document.title = 1</script>', encoding='utf-8')
        self.run_cli('say', 'topic', '--from', 'fork', 'לפני ואחרי', '--image', str(shot), '--caption', 'לפני', '--image', str(shot), '--html', str(page), env=e(4))
        m = self.thread(env=e(4))['messages'][2]
        self.assertEqual(([(i['file'], i.get('caption')) for i in m['images']], m['html']),
                         ([('uploads/topic/m3-1.png', 'לפני'), ('uploads/topic/m3-2.png', None)], {'file': 'uploads/topic/m3.html.txt', 'name': 'chart.html', 'bytes': len(page.read_bytes())}))
        self.assertEqual((self.board / 'uploads/topic/m3.html.txt').read_bytes(), page.read_bytes())
        self.assertIn('[דף HTML: ', self.run_cli('show', 'topic', env=e(4)).stdout)
        junk = self.root / 'junk.png'
        junk.write_text('not a picture')
        self.run_cli('say', 'topic', '--from', 'fork', 'x', '--image', str(junk), ok=False, env=e(5))
        self.run_cli('say', 'topic', '--from', 'fork', 'x', '--image', str(shot), '--caption', 'a', '--caption', 'b', ok=False, env=e(5))
        self.run_cli('say', 'topic', '--from', 'owner', 'x', '--html', str(page), ok=False, env=e(5))
        self.assertEqual(len(self.thread(env=e(5))['messages']), 3)
        # a link where the thread's folder should be is never written through
        self.run_cli('new', 'other', 'אחר', env=e(6))
        outside = self.root / 'outside'
        outside.mkdir()
        os.symlink(outside, self.board / 'uploads/other')
        self.assertFalse(self.post({**reply, 'thread': 'other', 'cid': 'p4', 'images': [{'data': b64(png)}]}, ok=False, env=e(6))['ok'])
        self.assertEqual(list(outside.iterdir()), [])
        self.run_cli('rm', 'topic', '--yes', env=e(7))
        self.assertFalse((self.board / 'uploads/topic').exists())                                              # its files go with it

    # ── videos (the owner) ──────────────────

    def video_env(self, hours=0):
        """The CLI with no ffmpeg: no poster is made, so what is stored is exactly what these tests built."""
        return dict(self.at(hours), THREADS_FFMPEG='')

    def write(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        return path

    def test_an_agent_attaches_a_video_checked_by_its_bytes_and_stored_like_a_picture(self):
        import struct
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        demo = self.write('demo.mp4', tiny_mp4(udta=b'\xa9xyz+32.0853+034.7818/SECRET-PLACE'))
        r = self.run_cli('say', 'topic', '--from', 'fork', 'ככה זה עובד', '--video', str(demo), '--caption', '  ההדגמה   מהמק ', env=e(1))
        self.assertEqual(r.stdout.strip(), 'm1')
        m = self.thread(env=e(1))['messages'][0]
        where = (self.board / 'uploads/topic/m1-v1.mp4').resolve()
        stored = where.read_bytes()
        self.assertEqual(m['text'], 'ככה זה עובד')
        self.assertEqual(m['videos'], [{'file': 'uploads/topic/m1-v1.mp4', 'name': 'demo.mp4', 'bytes': len(stored), 'type': 'mp4',
                                        'w': 320, 'h': 180, 'seconds': 1.5, 'caption': 'ההדגמה מהמק', 'path': str(where)}])
        # moov is first (so a player that cannot ask for a range still starts at once), the place is gone, the frames are where they were
        self.assertEqual([kind for kind, _, _ in mp4_boxes(stored)], [b'ftyp', b'moov', b'mdat'])
        self.assertNotIn(b'SECRET-PLACE', stored)
        self.assertNotIn(b'udta', stored)
        offset = struct.unpack('>I', stored[stored.index(b'stco') + 12:stored.index(b'stco') + 16])[0]
        self.assertEqual(stored[offset:offset + 9], b'FRAME-TWO')
        self.assertIn(f'[סרטון: {where} · 320x180 · 1.5 שניות · ההדגמה מהמק]', self.run_cli('show', 'topic', env=e(1)).stdout)
        # a file whose moov is already first comes through with its offsets as they were
        first = tiny_mp4(moov_last=False)
        self.run_cli('say', 'topic', '--from', 'fork', 'שוב', '--video', str(self.write('first.mp4', first)), env=e(2))
        self.assertEqual((self.board / 'uploads/topic/m2-v1.mp4').read_bytes(), first)
        # the kind is read from the bytes: a webm named .mp4 is a webm, and is stored as one
        self.run_cli('say', 'topic', '--from', 'fork', 'וגם', '--video', str(self.write('clip.mp4', tiny_webm(w=640, h=360))), env=e(3))
        v = self.thread(env=e(3))['messages'][2]['videos'][0]
        self.assertEqual({k: v[k] for k in ('file', 'name', 'type', 'w', 'h', 'seconds')},
                         {'file': 'uploads/topic/m3-v1.webm', 'name': 'clip.mp4', 'type': 'webm', 'w': 640, 'h': 360, 'seconds': 1.5})
        self.assertEqual((self.board / 'uploads/topic/m3-v1.webm').read_bytes(), tiny_webm(w=640, h=360))
        # a video and not a word: the text stands in, as for a picture
        self.run_cli('say', 'topic', '--from', 'fork', '', '--video', str(demo), env=e(4))
        m = self.thread(env=e(4))['messages'][3]
        self.assertEqual((m['text'], m['placeholder']), ('סרטון', True))
        # pictures and videos in one message: a --caption right after a --video is the video's, the rest go to the pictures in order
        shot = self.write('shot.png', self.png())
        self.run_cli('say', 'topic', '--from', 'fork', 'הכול', '--image', str(shot), '--video', str(demo), '--caption', 'הסרטון',
                     '--caption', 'התמונה', '--video', str(self.write('b.webm', tiny_webm())), env=e(5))
        m = self.thread(env=e(5))['messages'][4]
        self.assertEqual([(i['file'], i.get('caption')) for i in m['images']], [('uploads/topic/m5-1.png', 'התמונה')])
        self.assertEqual([(v['file'], v.get('caption')) for v in m['videos']], [('uploads/topic/m5-v1.mp4', 'הסרטון'), ('uploads/topic/m5-v2.webm', None)])
        # what he sends with a video reaches the agents with the file's path
        self.run_cli('say', 'topic', '--from', 'owner', 'שלי', '--video', str(demo), env=e(6))
        row = next(r for r in self.js('pending') if r['msg_id'] == 'm6')
        self.assertEqual(row['videos'], [{'path': str((self.board / 'uploads/topic/m6-v1.mp4').resolve()), 'caption': None, 'name': 'demo.mp4',
                                          'bytes': len(stored), 'type': 'mp4', 'w': 320, 'h': 180, 'seconds': 1.5}])
        self.run_cli('rm', 'topic', '--yes', env=e(7))
        self.assertFalse((self.board / 'uploads/topic').exists())

    def test_a_video_that_is_not_one_or_is_too_big_is_refused_before_anything_is_written(self):
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'ראשונה', env=e(0))
        big = self.root / 'big.mp4'
        with open(big, 'wb') as f:          # sparse: nothing is really written
            f.truncate(100_000_001)
        cases = {
            'a picture named .mp4': ([str(self.write('pic.mp4', self.png()))], 'mp4 או webm'),
            'text': ([str(self.write('notes.webm', b'hello, not a video at all'))], 'mp4 או webm'),
            'QuickTime': ([str(self.write('screen.mp4', tiny_mp4(brand=b'qt  ')))], 'QuickTime'),
            'sound only (mp4)': ([str(self.write('song.mp4', tiny_mp4(handler=b'soun')))], 'אין בו וידאו'),
            'sound only (webm)': ([str(self.write('song.webm', tiny_webm(track_type=2)))], 'אין בו וידאו'),
            'matroska': ([str(self.write('x.webm', tiny_webm(doctype=b'matroska')))], 'mp4 או webm'),
            'cut short': ([str(self.write('cut.mp4', tiny_mp4()[:-40]))], 'פגום'),
            'no moov': ([str(self.write('nomoov.mp4', tiny_mp4()[:32] + mp4_box(b'mdat', b'x' * 20)))], 'פגום'),
            'too big': ([str(big)], '100MB'),
            'three': ([str(self.write('a.mp4', tiny_mp4()))] * 3, 'עד 2 סרטונים'),
            'missing': ([str(self.root / 'nowhere.mp4')], 'nowhere.mp4'),
        }
        for what, (files, says) in cases.items():
            with self.subTest(what):
                args = [a for f in files for a in ('--video', f)]
                r = self.run_cli('say', 'topic', '--from', 'fork', 'x', *args, ok=False, env=e(1))
                self.assertIn(says, r.stderr)
        for what, extra in (('two captions for one video', ['--caption', 'א', '--caption', 'ב']), ('a caption too long', ['--caption', 'x' * 501])):
            with self.subTest(what):
                self.run_cli('say', 'topic', '--from', 'fork', 'x', '--video', str(self.root / 'a.mp4'), *extra, ok=False, env=e(1))
        self.assertEqual(len(self.thread(env=e(1))['messages']), 1)
        self.assertFalse((self.board / 'uploads/topic').exists())

    def test_a_hostile_video_file_is_refused_or_cleaned_and_never_hangs_or_crashes(self):
        import struct
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        # 64-bit chunk offsets are moved with the frames too
        self.run_cli('say', 'topic', '--from', 'fork', 'רחב', '--video', str(self.write('wide.mp4', tiny_mp4(wide=True))), env=e(1))
        stored = (self.board / 'uploads/topic/m1-v1.mp4').read_bytes()
        offset = struct.unpack('>Q', stored[stored.index(b'co64') + 12:stored.index(b'co64') + 20])[0]
        self.assertEqual((stored[offset:offset + 9], [k for k, _, _ in mp4_boxes(stored)]), (b'FRAME-TWO', [b'ftyp', b'moov', b'mdat']))
        # boxes nested thousands deep: never walked down (no recursion without end)
        deep = b'x'
        for _ in range(3000):
            deep = mp4_box(b'trak', deep)
        started = time.monotonic()
        r = self.run_cli('say', 'topic', '--from', 'fork', 'עמוק', '--video', str(self.write('deep.mp4', tiny_mp4(extra=deep))), env=e(2))
        self.assertNotIn('Traceback', r.stderr)
        # a webm of endless empty elements before its tracks: refused at once, not read element by element to its end
        void = b'\xec\x80' * 400_000
        head = ebml(b'\x1a\x45\xdf\xa3', ebml(b'\x42\x82', b'webm'))
        r = self.run_cli('say', 'topic', '--from', 'fork', 'ריק', '--video', str(self.write('void.webm', head + ebml(b'\x18\x53\x80\x67', void))), ok=False, env=e(3))
        self.assertRegex(r.stderr, 'פגום|אין בו וידאו')
        self.assertNotIn('Traceback', r.stderr)
        # a box whose 64-bit size runs far past the end of the file
        r = self.run_cli('say', 'topic', '--from', 'fork', 'x', '--video', str(self.write('huge.mp4', tiny_mp4()[:32] + struct.pack('>I4sQ', 1, b'mdat', 1 << 60) + b'x' * 20)), ok=False, env=e(3))
        self.assertIn('פגום', r.stderr)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(len(self.thread(env=e(3))['messages']), 2)

    # ── the hostile review of b1d1074 ──

    def strict_files(self):
        """state.json, summary.json and full/*.json as a page reads them: a number JSON cannot hold (Infinity, NaN)
        makes the page's fetch(...).json() throw, and the whole board stops loading."""
        def refuse(constant):
            raise ValueError('not JSON: ' + constant)
        for path in [self.board / 'state.json', self.board / 'summary.json', *sorted((self.board / 'full').glob('*.json'))]:
            with self.subTest(file=path.name):
                json.loads(path.read_text(encoding='utf-8'), parse_constant=refuse)

    def test_no_video_can_put_a_number_json_cannot_hold_into_the_state(self):
        import struct
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        hostile = {         # what is stored as its length: a scale of more than 8 bytes is none (the usual one stands)
            'a scale of 300 digits': (tiny_webm(scale=(10 ** 300).to_bytes(125, 'big'), duration=1e14), 0),
            'the largest 8-byte scale and an endless duration': (tiny_webm(scale=b'\xff' * 8, duration=1e300), 0),
            'a scale of 200 bytes': (tiny_webm(scale=b'\x7f' * 200), 1.5),
            'an mp4 of 2**32 seconds': (tiny_mp4(timescale=1, length=0xFFFFFFFE), 0),
        }
        for n, (what, (raw, seconds)) in enumerate(hostile.items(), 1):
            with self.subTest(what):
                r = self.run_cli('say', 'topic', '--from', 'fork', what, '--video', str(self.write(f'h{n}.bin', raw)), env=e(n))
                self.assertNotIn('Traceback', r.stderr)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.thread(env=e(n))['messages'][-1]['videos'][0]['seconds'], seconds)
        self.strict_files()
        # and no other field can either: a number that is not one, put into the state by hand, is never written out
        state = json.loads((self.board / 'state.json').read_text(encoding='utf-8'))
        state['threads']['topic']['messages'][0]['videos'][0]['seconds'] = float('nan')
        (self.board / 'state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        self.run_cli('say', 'topic', '--from', 'fork', 'אחרי', ok=False, env=e(9))
        for name in ('summary.json', 'full/topic.json'):
            self.assertNotIn('NaN', (self.board / name).read_text(encoding='utf-8'))

    def test_a_fragmented_mp4_or_one_with_odd_offsets_keeps_no_place_and_no_uuid(self):
        import struct
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        secret = b'\xa9xyz+32.0853+034.7818/SECRET-PLACE'
        xmp = mp4_box(b'uuid', b'\xbe\x7a\xcf\xcb\x97\xa9\x42\xe8\x9c\x71\x99\x94\x91\xe3\xaf\xac' + b'<x:xmpmeta>GPS-IN-XMP</x:xmpmeta>')
        cases = {
            # fragmented (moov carries mvex): kept in place, the private boxes made free space of the same size
            'fragmented': tiny_mp4(udta=secret, extra=mp4_box(b'mvex', b'\0' * 8) + xmp),
            # a chunk offset that points into a free box, not into mdat: the file cannot be moved, still nothing private stays
            'odd offsets': tiny_mp4(udta=secret, pad=mp4_box(b'free', b'\0' * 16), offset=40, extra=xmp),
            # an ordinary one with XMP inside moov
            'uuid in moov': tiny_mp4(extra=xmp),
        }
        for n, (what, raw) in enumerate(cases.items(), 1):
            with self.subTest(what):
                self.run_cli('say', 'topic', '--from', 'fork', what, '--video', str(self.write(f'f{n}.mp4', raw)), env=e(n))
                stored = (self.board / f'uploads/topic/m{n}-v1.mp4').read_bytes()
                for leak in (b'SECRET-PLACE', b'GPS-IN-XMP', b'udta', b'uuid'):
                    self.assertNotIn(leak, stored)
                if what != 'uuid in moov':
                    self.assertEqual(len(stored), len(raw))         # nothing moved: every offset still holds
                    stco = stored.index(b'stco')
                    self.assertEqual(stored[stco + 12:stco + 16], raw[raw.index(b'stco') + 12:raw.index(b'stco') + 16])

    def test_a_camera_file_with_a_track_of_data_is_refused_with_the_way_to_keep_only_picture_and_sound(self):
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        r = self.run_cli('say', 'topic', '--from', 'fork', 'x', '--video', str(self.write('gopro.mp4', tiny_mp4(extra=mp4_track(b'meta')))), ok=False, env=e(1))
        self.assertIn('-map 0:v', r.stderr)
        for handler in (b'soun', b'tmcd'):          # sound and a timecode are fine
            self.run_cli('say', 'topic', '--from', 'fork', 'x', '--video', str(self.write('ok.mp4', tiny_mp4(extra=mp4_track(handler)))), env=e(2))

    def test_a_webm_keeps_no_tags_title_or_date_and_still_plays(self):
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        cases = {
            'tags after the frames': tiny_webm(title=b'SECRET-TITLE', date=b'\x00' * 8, tags=b'+32.0853+034.7818/SECRET-PLACE'),
            'a live recording: frames of no size, tags after them': tiny_webm(tags=b'+32.0853+034.7818/SECRET-PLACE', unknown_cluster=True),
            'a title of one letter': tiny_webm(title=b'S'),
        }
        for n, (what, raw) in enumerate(cases.items(), 1):
            with self.subTest(what):
                mid = self.run_cli('say', 'topic', '--from', 'fork', what, '--video', str(self.write(f'w{n}.webm', raw)), env=e(n)).stdout.strip()
                stored = (self.board / f'uploads/topic/{mid}-v1.webm').read_bytes()
                self.assertEqual(len(stored), len(raw))
                for leak in (b'SECRET', b'LOCATION', b'\x7b\xa9\x81S'):
                    self.assertNotIn(leak, stored)
                self.assertIn(b'FRAME-BYTES-HERE', stored)
                # what is stored is a webm the CLI takes again, with the same shape
                self.run_cli('say', 'topic', '--from', 'fork', 'שוב', '--video', str(self.write(f'again{n}.webm', stored)), env=e(n))
                v = self.thread(env=e(n))['messages'][-1]['videos'][0]
                self.assertEqual((v['w'], v['h'], v['seconds']), (320, 180, 1.5))

    def test_a_long_index_of_chunks_is_moved_without_a_copy_per_number(self):
        """A 16 MB index of chunk offsets (4 million) unpacked into Python numbers took 227 MB and 1.6 s; a 100 MB
        file about 1.4 GB. The peak memory of the CLI stays under 6 times the file (the old way took 14 times; 4 was too close to a busy machine)."""
        import array
        import struct
        count = 4_000_000
        frames = b'F' * 64 + b'|' + b'G' * 63
        raw = tiny_mp4(frames=frames)
        # the same file with an index of `count` offsets, every one at the second frame
        stco = raw.index(b'stco')
        at = struct.unpack('>I', raw[stco + 12:stco + 16])[0]
        offsets = array.array('I', [at]) * count
        if sys.byteorder == 'little':
            offsets.byteswap()
        grown = 4 * (count - 1)
        moov = raw.index(b'moov') - 4
        body = raw[moov:]
        for name in (b'moov', b'trak', b'mdia', b'minf', b'stbl', b'stco'):
            i = body.index(name) - 4
            body = body[:i] + struct.pack('>I', struct.unpack('>I', body[i:i + 4])[0] + grown) + body[i + 4:]
        i = body.index(b'stco')
        body = body[:i + 8] + struct.pack('>I', count) + offsets.tobytes() + body[i + 16:]
        big = self.write('long.mp4', raw[:moov] + body)
        e = self.video_env(1)
        self.run_cli('new', 'topic', 'כותרת', env=e)
        probe = ('import resource, subprocess, sys, time\nt = time.monotonic()\n'
                 'r = subprocess.run(sys.argv[1:], capture_output=True)\n'
                 'print(r.returncode, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, time.monotonic() - t)')
        def measured(*args):
            out = subprocess.run([sys.executable, '-c', probe, sys.executable, str(CLI), *args], env=e, capture_output=True, text=True, timeout=120).stdout.split()
            return int(out[0]), int(out[1]) * (1 if sys.platform == 'darwin' else 1024), float(out[2])      # bytes on a Mac, KB elsewhere
        _, idle, _ = measured('list')                               # what the CLI takes before it reads a file
        code, peak, took = measured('say', 'topic', '--from', 'fork', 'ארוך', '--video', str(big))
        self.assertEqual(code, 0)
        self.assertLess(peak - idle, 6 * big.stat().st_size, f'{(peak - idle) / 1e6:.0f} MB more than idle for a {big.stat().st_size / 1e6:.0f} MB file')
        self.assertLess(took, 10)
        stored = (self.board / 'uploads/topic/m1-v1.mp4').read_bytes()
        i = stored.index(b'stco')
        first, last = struct.unpack('>I', stored[i + 12:i + 16])[0], struct.unpack('>I', stored[i + 8 + 4 * count:i + 12 + 4 * count])[0]
        self.assertEqual((stored[first:first + 3], stored[last:last + 3]), (b'GGG', b'GGG'))

    def test_a_long_text_of_slashes_does_not_hold_say(self):
        """The look for a local video in the words went over the text once for every place in it."""
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        for n, text in enumerate(('/-' * 25000, '/-' * 25000 + '.mp4', 'a/' * 25000 + 'x.webm'), 1):
            with self.subTest(n=n):
                started = time.monotonic()
                self.run_cli('say', 'topic', '--from', 'fork', '-', input=text, env=e(n))
                self.assertLess(time.monotonic() - started, 1.5)

    def test_a_video_into_a_closed_thread_is_kept_as_a_message_is_and_the_agent_is_warned(self):
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('close', 'topic', env=e(1))
        r = self.run_cli('say', 'topic', '--from', 'fork', 'מאוחר', '--video', str(self.write('demo.mp4', tiny_mp4())), env=e(2))
        self.assertIn('השרשור סגור', r.stderr)
        m = self.thread(env=e(2))['messages'][-1]
        self.assertEqual(m['videos'][0]['file'], 'uploads/topic/m1-v1.mp4')
        self.assertTrue((self.board / 'uploads/topic/m1-v1.mp4').is_file())

    def test_a_video_named_by_its_local_path_is_not_attached_and_the_agent_is_told_how(self):
        """The page never opens a local path (nor would the board serve one): the CLI does not guess either, it says
        how to attach the file."""
        e = self.video_env
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        demo = self.write('demo.mp4', tiny_mp4())
        r = self.run_cli('say', 'topic', '--from', 'fork', f'ההקלטה כאן: {demo}', env=e(1))
        m = self.thread(env=e(1))['messages'][-1]
        self.assertNotIn('videos', m)
        self.assertIn(f'--video {demo}', r.stderr)
        r = self.run_cli('say', 'topic', '--from', 'fork', f'ההקלטה: {demo}', '--video', str(demo), env=e(2))
        self.assertNotIn('--video', r.stderr)

    # ── a small picture beside a big one (suda-fixes task 31, m120 #4, approved m130) ──
    def real_picture(self, name, size, fmt=None, alpha=False):
        """A picture as a camera or a screenshot makes it, drawn by ffmpeg: noise, so it does not shrink to nothing."""
        import shutil
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is not installed')
        path = self.root / name
        w, h = (int(x) for x in size.split('x'))
        small = '%dx%d' % (max(2, w // 12), max(2, h // 12))
        src = ('nullsrc=size=%s,geq=random(1)*255:128:128,scale=%s:flags=bilinear' % (small, size) if not alpha else
               'color=c=red@0.4:size=%s,format=rgba,geq=r=random(1)*255:g=90:b=60:a=random(2)*200+20,scale=%s:flags=bilinear' % (small, size))
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', src, '-frames:v', '1', *(['-pix_fmt', 'rgba'] if alpha else []),
                        *(['-q:v', '2'] if name.endswith('.jpg') else []), str(path)], check=True, timeout=60)
        return ffmpeg, path

    def test_a_big_picture_gets_a_small_one_beside_it_that_the_page_shows_until_he_taps(self):
        ffmpeg, photo = self.real_picture('photo.jpg', '2000x1500')
        _, shot = self.real_picture('shot.png', '1080x2400')
        _, clear = self.real_picture('clear.png', '1200x900', alpha=True)
        env = dict(self.at(1), THREADS_FFMPEG=ffmpeg)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.run_cli('say', 'topic', '--from', 'fork', 'שלוש', '--image', str(photo), '--image', str(shot), '--image', str(clear), env=env)
        m = self.thread(env=env)['messages'][0]
        thumbs = [i.get('thumb') for i in m['images']]
        self.assertTrue(all(thumbs), m['images'])
        self.assertEqual([t['file'] for t in thumbs], ['uploads/topic/m1-1.thumb.jpg', 'uploads/topic/m1-2.thumb.jpg', 'uploads/topic/m1-3.thumb.png'])
        self.assertEqual([(t['w'], t['h']) for t in thumbs], [(720, 540), (324, 720), (720, 540)])        # the long side 720, the shape kept
        for i, t in zip(m['images'], thumbs):
            raw = (self.board / t['file']).read_bytes()
            self.assertEqual(len(raw), t['bytes'])
            self.assertLess(t['bytes'], i['bytes'] * 0.6, 'worth its place: much smaller than the picture')
            self.assertTrue((self.board / i['file']).is_file(), 'the picture itself stays, whole')
        self.assertTrue((self.board / thumbs[0]['file']).read_bytes().startswith(b'\xff\xd8\xff'))
        clear_thumb = (self.board / thumbs[2]['file']).read_bytes()
        self.assertTrue(clear_thumb.startswith(b'\x89PNG') and clear_thumb[25] in (4, 6), 'what can be seen through stays so (a png with alpha)')
        self.assertNotIn('.thumb.', self.run_cli('show', 'topic', env=env).stdout, 'the agents read the picture itself')

    def test_a_small_picture_has_no_small_copy_and_without_ffmpeg_none_is_made(self):
        ffmpeg, little = self.real_picture('little.png', '200x150')
        _, big = self.real_picture('big.jpg', '1600x1200')
        env = dict(self.at(1), THREADS_FFMPEG=ffmpeg)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.run_cli('say', 'topic', '--from', 'fork', 'קטנה', '--image', str(little), env=env)
        self.assertNotIn('thumb', self.thread(env=env)['messages'][0]['images'][0], 'nothing to save on a small picture')
        self.run_cli('say', 'topic', '--from', 'fork', 'בלי', '--image', str(big), env=dict(env, THREADS_FFMPEG=''))
        self.assertNotIn('thumb', self.thread(env=env)['messages'][1]['images'][0])
        # an ffmpeg that fails, or writes what is not a picture, never costs the picture
        bad = self.write('bad-ffmpeg', b'#!/bin/sh\necho not-a-picture\nexit 0\n')
        bad.chmod(0o755)
        for tool in ('/usr/bin/false', str(bad)):
            r = self.run_cli('say', 'topic', '--from', 'fork', 'שבור', '--image', str(big), env=dict(env, THREADS_FFMPEG=tool))
            self.assertEqual(r.returncode, 0, r.stderr)
            last = self.thread(env=env)['messages'][-1]['images'][0]
            self.assertNotIn('thumb', last)
            self.assertTrue((self.board / last['file']).is_file())
        self.assertEqual(sorted(p.name for p in (self.board / 'uploads/topic').iterdir() if 'thumb' in p.name), [])

    def test_a_picture_from_the_page_and_the_picture_of_an_option_get_their_small_one_too(self):
        import base64
        ffmpeg, photo = self.real_picture('photo.jpg', '1800x1200')
        env = dict(self.at(1), THREADS_FFMPEG=ffmpeg)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        got = self.post({'op': 'reply', 'thread': 'topic', 'cid': 'p1', 'text': '',
                         'images': [{'name': 'IMG.jpg', 'type': 'image/jpeg', 'data': base64.b64encode(photo.read_bytes()).decode()}]}, env=env)
        self.assertTrue(got['ok'])
        mine = self.thread(env=env)['messages'][0]['images'][0]
        self.assertEqual(mine['thumb']['file'], 'uploads/topic/m1-1.thumb.jpg')
        row = self.js('pending')[0]          # the agents get the picture itself, never the small one
        self.assertEqual([r['path'] for r in row['images']], [str((self.board / mine['file']).resolve())])
        self.assertNotIn('.thumb.', json.dumps(row))
        self.run_cli('ask', 'topic', 'איזו?', '--options', 'א,ב', '--option-image', f'א={photo}', env=env)
        q = self.thread(env=env)['messages'][-1]
        self.assertEqual(q['option_images']['א']['thumb']['file'], 'uploads/topic/%s-o1.thumb.jpg' % q['id'])
        self.assertTrue((self.board / q['option_images']['א']['thumb']['file']).is_file())

    def test_a_picture_his_page_sent_smaller_says_how_big_the_original_was(self):
        """m198: his page may send a picture re-encoded smaller (a slow link); the full one never reached the server,
        so the page says so instead of offering full quality. The page names the original's sides: kept when sane,
        dropped otherwise, never a reason to refuse the picture."""
        import base64
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        b64 = base64.b64encode(self.jpeg()).decode()           # stored 30x40
        base = {'op': 'reply', 'thread': 'topic', 'text': ''}
        self.assertTrue(self.post({**base, 'cid': 's1', 'images': [{'data': b64, 'shrunk': {'w': 3000, 'h': 4000}}]}, env=e(1))['ok'])
        self.assertEqual(self.thread(env=e(1))['messages'][0]['images'][0]['shrunk'], {'w': 3000, 'h': 4000})
        bad = [{'w': '3000', 'h': 4000}, {'w': 0, 'h': 4000}, {'w': 20, 'h': 30}, {'w': 30, 'h': 40}, {'w': 99999, 'h': 4000}, {'w': True, 'h': 4000}, 'big', [3000, 4000], None]
        for n, value in enumerate(bad, 2):
            got = self.post({**base, 'cid': 's%d' % n, 'images': [{'data': b64, 'shrunk': value}]}, env=e(n))
            self.assertTrue(got['ok'], value)
            self.assertNotIn('shrunk', self.thread(env=e(n))['messages'][-1]['images'][0], value)

    def test_a_real_video_gets_a_poster_of_its_first_frame_when_ffmpeg_is_here(self):
        import shutil
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is not installed')
        demo = self.root / 'real.mp4'
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10:duration=1',
                        '-pix_fmt', 'yuv420p', '-metadata', 'title=SECRET-TITLE', str(demo)], check=True, timeout=60)
        self.assertEqual([k for k, _, _ in mp4_boxes(demo.read_bytes())][-1], b'moov')       # as ffmpeg writes it: moov last
        env = dict(self.at(1), THREADS_FFMPEG=ffmpeg)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.run_cli('say', 'topic', '--from', 'fork', 'אמיתי', '--video', str(demo), env=env)
        v = self.thread(env=env)['messages'][0]['videos'][0]
        self.assertEqual((v['w'], v['h'], v['seconds'], v['poster']), (160, 90, 1.0, 'uploads/topic/m1-v1.jpg'))
        poster = (self.board / v['poster']).read_bytes()
        self.assertTrue(poster.startswith(b'\xff\xd8\xff'))
        stored = (self.board / v['file']).read_bytes()
        self.assertEqual([k for k, _, _ in mp4_boxes(stored)][:2], [b'ftyp', b'moov'])
        self.assertNotIn(b'SECRET-TITLE', stored)
        probe = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                'stream=nb_read_frames', '-of', 'csv=p=0', str(self.board / v['file'])], capture_output=True, text=True, timeout=60)
        self.assertEqual((probe.returncode, probe.stderr, probe.stdout.strip()), (0, '', '10'))       # every frame still decodes
        # without ffmpeg there is no poster, and the video is the same
        self.run_cli('say', 'topic', '--from', 'fork', 'בלי', '--video', str(demo), env=dict(env, THREADS_FFMPEG=''))
        self.assertNotIn('poster', self.thread(env=env)['messages'][1]['videos'][0])
        # a webm ffmpeg wrote with a place and a title (its Tags, its Info): neither is stored, every frame still decodes
        clip = self.root / 'real.webm'
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10:duration=1', '-c:v', 'libvpx', '-b:v', '60k',
                        '-metadata', 'location=+32.0853+034.7818/', '-metadata', 'title=SECRET-TITLE', str(clip)], check=True, timeout=60)
        self.assertIn(b'+32.0853', clip.read_bytes())
        mid = self.run_cli('say', 'topic', '--from', 'fork', 'webm', '--video', str(clip), env=env).stdout.strip()
        v = self.thread(env=env)['messages'][-1]['videos'][0]
        stored = (self.board / v['file']).read_bytes()
        self.assertEqual((v['file'], len(stored), v['w'], v['h'], v['seconds']), (f'uploads/topic/{mid}-v1.webm', len(clip.read_bytes()), 160, 90, 1.0))
        for leak in (b'+32.0853', b'SECRET-TITLE', b'LOCATION'):
            self.assertNotIn(leak, stored)
        probe = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                'stream=nb_read_frames', '-of', 'csv=p=0', str(self.board / v['file'])], capture_output=True, text=True, timeout=60)
        self.assertEqual((probe.returncode, probe.stderr, probe.stdout.strip()), (0, '', '10'))

    def notified(self):
        """An environment in which a recorder stands in for the push service and for the phone."""
        import shlex
        for name, body in (('push.py', "print(os.environ.get('PUSH_STATUS', '201'))"), ('snap.py', '')):
            (self.root / name).write_text("import json, os, sys\nwith open(os.environ['TOLD_RECORD'], 'a') as f:\n f.write(json.dumps([%r] + sys.argv[1:]) + '\\n')\n%s\n" % (name[:-3], body))
        self.told = self.root / 'told.jsonl'
        return dict(self.env, TZ='UTC', TOLD_RECORD=str(self.told), THREADS_PUSH_CMD=shlex.join([sys.executable, str(self.root / 'push.py')]),
                    THREADS_SNAP_CMD=shlex.join([sys.executable, str(self.root / 'snap.py')]))

    def tellings(self, kind):
        rows = [json.loads(line) for line in self.told.read_text().splitlines()] if self.told.exists() else []
        return [row[1:] for row in rows if row[0] == kind]

    def test_he_is_told_by_push_and_then_on_his_phone(self):
        base = self.notified()
        e = lambda minutes, **more: dict(base, THREADS_NOW=str(self.T0 + minutes * 60), **more)      # T0 is 08:00 UTC
        private = self.root / '.threads-config/threads'
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח ביניים', env=e(1))
        self.assertEqual(self.tellings('push'), [])                                                 # nobody subscribed: nothing to send
        self.post({'op': 'seen', 'thread': 'topic', 'last': 'm1'}, env=e(1))
        fcm = 'https://fcm.googleapis.com/fcm/send/abc123'
        got = self.post({'op': 'push-subscribe', 'sub': {'endpoint': fcm, 'keys': {'p256dh': 'x', 'auth': 'y'}}}, env=e(2))
        self.assertEqual(got, {'ok': True, 'op': 'push-subscribe', 'publicKey': json.loads((self.board / 'push.json').read_text())['publicKey']})
        self.assertEqual(len(base64_url_decode(got['publicKey'])), 65)
        self.assertEqual(list(json.loads((private / 'push-subs.json').read_text())), [fcm])
        self.assertEqual(((private / 'push-subs.json').stat().st_mode & 0o777, (private / 'vapid.pem').stat().st_mode & 0o777), (0o600, 0o600))
        self.assertEqual([p.name for p in self.board.rglob('*') if 'vapid' in p.name or 'subs' in p.name], [])      # nothing private in the served folder
        for bad in ('http://fcm.googleapis.com/x', 'https://evil.example/x', 'https://fcm.googleapis.com.evil.example/x', 'https://user@fcm.googleapis.com/x',
                    'https://fcm.googleapis.com:8443/x', 'https://127.0.0.1/x', 5, None):
            with self.subTest(endpoint=bad):
                self.assertFalse(self.post({'op': 'push-subscribe', 'sub': {'endpoint': bad}}, ok=False, env=e(2))['ok'])
        self.assertFalse(self.post({'op': 'push-subscribe', 'sub': 'x'}, ok=False, env=e(2))['ok'])
        # an agent's message that is on him: one push, once
        self.run_cli('say', 'topic', '--from', 'fork', 'סיימתי, תסתכל', env=e(3))
        self.assertEqual(self.tellings('push'), [[fcm]])
        self.assertEqual(self.thread(env=e(4))['alert']['key'][:3], 'm2|')
        self.run_cli('list', env=e(5))
        self.assertEqual(len(self.tellings('push')), 1)
        # he looked: the alert is over, and the phone is left alone
        self.run_cli('notify', '--snap', 'on', '--url', 'https://suda.example/threads/suda.html', env=e(5))
        self.assertTrue(self.post({'op': 'seen', 'thread': 'topic', 'last': 'm2'}, env=e(6))['ok'])
        self.assertNotIn('alert', self.thread(env=e(6)))
        self.run_cli('sweep', env=e(40))
        self.assertEqual(self.tellings('snap'), [])
        self.assertFalse(self.post({'op': 'seen', 'thread': 'topic', 'last': 'm9'}, ok=False, env=e(40))['ok'])
        state = (self.board / 'state.json').read_bytes()
        self.assertTrue(self.post({'op': 'seen', 'thread': 'topic', 'last': 'm1'}, env=e(40))['ok'])          # an older tab: he has seen more already
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        # a question he does not open: a push now, his phone a quarter of an hour later, once
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא', env=e(50))
        self.assertEqual(len(self.tellings('push')), 2)
        self.run_cli('sweep', env=e(64))
        self.assertEqual(self.tellings('snap'), [])
        self.run_cli('sweep', env=e(65.1))
        self.assertEqual(self.tellings('snap'), [['--open', 'url:https://suda.example/threads/suda.html#topic', 'עליך: כותרת', 'להמשיך?']])
        self.run_cli('sweep', env=e(200))
        self.assertEqual((len(self.tellings('snap')), len(self.tellings('push'))), (1, 2))
        # his answer ends it; a progress note that is not on him tells nobody
        self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'כן', 'q': 'm3'}, env=e(201))
        self.assertNotIn('alert', self.thread(env=e(201)))
        self.run_cli('say', 'topic', '--from', 'fork', 'מתקדם', '--state', 'working', '--note', 'בונה', env=e(202))
        self.assertEqual(len(self.tellings('push')), 2)
        # a muted thread: no push, no phone
        self.assertTrue(self.post({'op': 'mute', 'thread': 'topic', 'on': True}, env=e(203))['ok'])
        self.run_cli('say', 'topic', '--from', 'fork', 'עוד דוח', env=e(204))
        self.run_cli('sweep', env=e(260))
        self.assertEqual((len(self.tellings('push')), len(self.tellings('snap')), self.thread(env=e(260))['mute']), (2, 1, True))
        self.run_cli('mute', 'topic', '--off', env=e(261))
        self.assertEqual((len(self.tellings('push')), 'mute' in self.thread(env=e(261))), (3, False))          # unmuted: it is on him and unseen
        self.post({'op': 'seen', 'thread': 'topic', 'last': 'm6'}, env=e(262))
        # quiet hours hold everything until they end (13:00 to 14:00 UTC here)
        self.assertEqual(self.post({'op': 'quiet', 'from': '13:00', 'to': '14:00'}, env=e(270))['quiet'], {'from': '13:00', 'to': '14:00'})
        for bad in ({'from': '25:00', 'to': '07:00'}, {'from': '22:00'}, {'from': 22, 'to': 7}):
            self.assertFalse(self.post({'op': 'quiet', **bad}, ok=False, env=e(270))['ok'])
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח לילה', env=e(310))                        # 13:10
        self.run_cli('sweep', env=e(355))
        self.assertEqual((len(self.tellings('push')), len(self.tellings('snap'))), (3, 1))
        self.run_cli('sweep', env=e(361))                                                             # 14:01
        self.assertEqual((len(self.tellings('push')), len(self.tellings('snap'))), (4, 1))
        self.run_cli('sweep', env=e(377))                                                             # a quarter of an hour after he was told
        self.assertEqual(len(self.tellings('snap')), 2)
        self.assertTrue(self.post({'op': 'quiet', 'off': True}, env=e(378))['ok'])
        self.assertIsNone(self.js('notify')['quiet'])
        # the push service says this browser is gone: it is forgotten
        self.run_cli('say', 'topic', '--from', 'fork', 'עוד אחד', env=e(400, PUSH_STATUS='410'))
        self.assertEqual(json.loads((private / 'push-subs.json').read_text()), {})
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': fcm}}, env=e(401))
        self.assertTrue(self.post({'op': 'push-unsubscribe', 'endpoint': fcm}, env=e(402))['ok'])
        self.assertEqual(json.loads((private / 'push-subs.json').read_text()), {})
        # settings from the command line; THREADS_NOTIFY=0 silences everything
        self.run_cli('notify', '--fallback-minutes', '30', '--quiet', '22:00-07:00', '--snap', 'off', env=e(403))
        got = json.loads(self.run_cli('notify', env=e(403)).stdout)
        self.assertEqual((got['fallback_minutes'], got['quiet'], got['snap'], got['browsers'], got['push_key']), (30, {'from': '22:00', 'to': '07:00'}, False, 0, True))
        for bad in (['--quiet', '7-22'], ['--fallback-minutes', '0'], ['--url', 'javascript:x'], ['--contact', 'me']):
            self.run_cli('notify', *bad, ok=False, env=e(403))
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': fcm}}, env=e(404))
        count = len(self.tellings('push'))
        self.run_cli('notify', '--quiet', 'off', env=e(404))
        self.run_cli('say', 'topic', '--from', 'fork', 'בשקט', env=e(405, THREADS_NOTIFY='0'))
        self.assertEqual(len(self.tellings('push')), count)

    def test_switching_the_phone_on_does_not_replay_what_already_waits(self):
        base = self.notified()
        e = lambda minutes: dict(base, THREADS_NOW=str(self.T0 + minutes * 60))
        self.run_cli('new', 'old', 'ישן', env=e(0))
        self.run_cli('say', 'old', '--from', 'fork', 'מחכה כבר מזמן', env=e(0))
        self.run_cli('notify', '--snap', 'on', env=e(600))
        self.run_cli('sweep', env=e(700))
        self.assertEqual(self.tellings('snap'), [])
        self.run_cli('say', 'old', '--from', 'fork', 'דבר חדש', env=e(701))
        self.run_cli('sweep', env=e(717))
        self.assertEqual([row[-2:] for row in self.tellings('snap')], [['עליך: ישן', 'לקרוא: דבר חדש']])

    def test_his_phone_is_told_at_once_unless_a_page_has_his_focus(self):
        base = self.notified()
        e = lambda seconds, **more: dict(base, THREADS_NOW=str(self.T0 + seconds), **more)                  # seconds here, not minutes
        private = self.root / '.threads-config/threads'
        here = lambda seconds, page='tab-aaaaaa1', focused=True, **more: self.post({'op': 'presence', 'page': page, 'focused': focused, **more}, env=e(seconds))
        snaps = lambda: [row[-2][len('עליך: '):] for row in self.tellings('snap')]
        saw = lambda seconds, tid: self.post({'op': 'seen', 'thread': tid, 'last': self.thread(tid, env=e(seconds))['messages'][-1]['id']}, env=e(seconds))
        for tid in ('topic', 'other'):
            self.run_cli('new', tid, 'כותרת' if tid == 'topic' else 'אחר', '--state', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('notify', '--snap', 'on', '--url', 'https://suda.example/threads/suda.html', env=e(0))
        self.assertIn('presence', json.loads((self.board / 'state.json').read_text())['ops'])
        # pages that never reported his focus (older ones): nobody can tell, so the phone waits its minutes as before
        self.run_cli('say', 'topic', '--from', 'fork', 'דוח ישן', env=e(1))
        self.run_cli('sweep', env=e(30))
        self.assertEqual((snaps(), json.loads(self.run_cli('notify', env=e(30)).stdout)['on_suda']), ([], None))
        saw(31, 'topic')
        # from the first report on, the pages say where he is. Nobody is on Suda: his phone hears of it at once
        here(40, focused=False)
        self.assertEqual(json.loads((private / 'presence.json').read_text())['pages'], {})
        self.run_cli('say', 'topic', '--from', 'fork', 'סיימתי, תסתכל', env=e(60))
        self.assertEqual(self.tellings('snap'), [['--open', 'url:https://suda.example/threads/suda.html#topic', 'עליך: כותרת', 'לקרוא: סיימתי, תסתכל']])
        self.run_cli('sweep', env=e(70))
        self.assertEqual(snaps(), ['כותרת'])                                                                 # once
        # a page has his focus: the phone is left alone. The heartbeat rewrites no state and nothing of it is served
        state = (self.board / 'state.json').read_bytes()
        self.assertEqual(here(100, thread='topic', idle=3), {'ok': True, 'op': 'presence', 'focused': True, 'ts': self.T0 + 100})
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.assertEqual([p.name for p in self.board.rglob('*') if 'presence' in p.name], [])
        self.assertEqual((private / 'presence.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue(json.loads(self.run_cli('notify', env=e(101)).stdout)['on_suda'])
        self.run_cli('say', 'other', '--from', 'fork', 'גם כאן', env=e(110))
        here(120)
        self.run_cli('sweep', env=e(130))
        self.assertEqual(snaps(), ['כותרת'])
        # he left Suda without opening it: it reaches his phone at the next look (the timer's, within a minute)
        self.assertEqual(here(135, focused=False), {'ok': True, 'op': 'presence', 'focused': False, 'ts': self.T0 + 135})
        self.run_cli('sweep', env=e(140))
        self.assertEqual(snaps(), ['כותרת', 'אחר'])
        self.assertFalse(json.loads(self.run_cli('notify', env=e(141)).stdout)['on_suda'])
        saw(150, 'topic'), saw(150, 'other')
        # a page that went silent (closed without a word) stops counting after 45 seconds
        here(200)
        self.run_cli('say', 'topic', '--from', 'fork', 'עוד דבר', env=e(244))
        self.assertEqual(len(snaps()), 2)
        self.run_cli('sweep', env=e(246))
        self.assertEqual(len(snaps()), 3)
        saw(250, 'topic')
        # a window left in front of an empty chair: it has the focus, but nobody touched it for over two minutes
        here(300, idle=100)
        self.run_cli('say', 'topic', '--from', 'fork', 'מישהו שם?', env=e(310))                              # 110 seconds: he may still be reading
        self.assertEqual(len(snaps()), 3)
        self.run_cli('sweep', env=e(325))                                                                   # 125 seconds
        self.assertEqual(len(snaps()), 4)
        here(330, idle=500)                                                                                 # and a report that says so is not him
        self.assertFalse(json.loads(self.run_cli('notify', env=e(331)).stdout)['on_suda'])
        saw(340, 'topic')
        # two tabs: one that loses his focus does not clear the other's
        here(400, page='tab-aaaaaa1'), here(400, page='tab-bbbbbb2')
        here(401, page='tab-aaaaaa1', focused=False)
        self.run_cli('say', 'topic', '--from', 'fork', 'שני חלונות', env=e(402))
        self.assertEqual(len(snaps()), 4)
        # he is on Suda and still does not open it: after the fallback minutes his phone gets it anyway
        here(402 + 890)
        self.run_cli('sweep', env=e(402 + 899))
        self.assertEqual(len(snaps()), 4)
        here(402 + 900)
        self.run_cli('sweep', env=e(402 + 901))
        self.assertEqual(len(snaps()), 5)
        saw(1310, 'topic')
        # two messages one after the other, nobody there: one alert now, the next not within a minute
        self.run_cli('say', 'topic', '--from', 'fork', 'חלק א', env=e(1400))
        self.run_cli('say', 'topic', '--from', 'fork', 'חלק ב', env=e(1405))
        self.assertEqual([row[-1] for row in self.tellings('snap')[5:]], ['לקרוא: חלק א'])
        self.run_cli('sweep', env=e(1459))
        self.assertEqual(len(snaps()), 6)
        self.run_cli('sweep', env=e(1461))
        self.assertEqual([row[-1] for row in self.tellings('snap')[5:]], ['לקרוא: חלק א', 'לקרוא: חלק ב'])
        saw(1470, 'topic')
        # the same when the turn leaves him and comes back at once: the thread does not ring twice in a minute
        self.run_cli('state', 'other', 'working', '--note', 'ממשיך', env=e(1480))
        self.run_cli('say', 'other', '--from', 'fork', 'שאלה', env=e(1481))
        self.run_cli('state', 'other', 'working', '--note', 'רגע', env=e(1483))
        self.run_cli('say', 'other', '--from', 'fork', 'שאלה מתוקנת', env=e(1485))
        self.assertEqual([row[-1] for row in self.tellings('snap')[7:]], ['לקרוא: שאלה'])
        self.run_cli('sweep', env=e(1542))
        self.assertEqual([row[-1] for row in self.tellings('snap')[7:]], ['לקרוא: שאלה', 'לקרוא: שאלה מתוקנת'])
        saw(1545, 'other')
        # a muted thread and quiet hours are kept, also when nobody is there (T0 is 08:00 UTC)
        self.post({'op': 'mute', 'thread': 'topic', 'on': True}, env=e(1500))
        self.run_cli('say', 'topic', '--from', 'fork', 'בשקט', env=e(1600))
        self.post({'op': 'quiet', 'from': '08:20', 'to': '09:00'}, env=e(1601))
        self.run_cli('say', 'other', '--from', 'fork', 'בשעות השקט', env=e(1700))
        self.run_cli('sweep', env=e(3590))
        self.assertEqual(len(snaps()), 9)
        self.run_cli('sweep', env=e(3601))                                                                  # 09:00: the quiet hours are over
        self.assertEqual(snaps()[9:], ['אחר'])
        # what is not a report of a page is refused; a thread that is no id is kept as none
        for bad in ({'focused': True}, {'page': 'x', 'focused': True}, {'page': 'a b c d e f', 'focused': True}, {'page': 'tab-aaaaaa1'}, {'page': 'tab-aaaaaa1', 'focused': 'yes'},
                    {'page': 'tab-aaaaaa1', 'focused': True, 'idle': -1}, {'page': 'tab-aaaaaa1', 'focused': True, 'idle': 'x'}, {'page': 'tab-aaaaaa1', 'focused': True, 'idle': True},
                    {'page': 'tab-aaaaaa1', 'focused': True, 'idle': 1e400}, {'page': 'p' * 41, 'focused': True}):
            with self.subTest(report=bad):
                self.assertFalse(self.post({'op': 'presence', **bad}, ok=False, env=e(3700))['ok'])
        self.assertTrue(here(3700, thread='../../etc')['ok'])
        self.assertEqual(json.loads((private / 'presence.json').read_text())['pages'], {'tab-aaaaaa1': {'ts': self.T0 + 3700, 'thread': '', 'idle': 0}})
        # junk cannot grow the file, and a board with notifications off still takes the report (a page test needs the receipt)
        for n in range(30):
            here(3701, page=f'junk-{n:06d}')
        self.assertEqual(len(json.loads((private / 'presence.json').read_text())['pages']), 20)
        self.assertTrue(self.post({'op': 'presence', 'page': 'tab-aaaaaa1', 'focused': True}, env=e(3702, THREADS_NOTIFY='0'))['ok'])
        # the idle limit is a setting
        self.run_cli('notify', '--idle-minutes', '10', env=e(3800))
        self.assertEqual(json.loads(self.run_cli('notify', env=e(3800)).stdout)['idle_minutes'], 10)
        here(3801, idle=500)
        self.assertTrue(json.loads(self.run_cli('notify', env=e(3802)).stdout)['on_suda'])
        for bad in ('0', '-1', 'x', '100000'):
            self.run_cli('notify', '--idle-minutes', bad, ok=False, env=e(3800))

    def test_a_page_action_never_waits_for_the_push(self):
        base = self.notified()
        e = lambda minutes: dict(base, THREADS_NOW=str(self.T0 + minutes * 60))
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': 'https://updates.push.services.mozilla.com/wpush/v2/abc'}}, env=e(0))
        self.run_cli('snooze', 'topic', '--until', '+10m', env=e(1))
        self.assertEqual(self.post({'op': 'sweep'}, env=e(11))['archived'], [])                     # the wake puts it on him: a push is owed
        for _ in range(100):
            if self.tellings('push'):
                break
            time.sleep(0.1)
        self.assertEqual(self.tellings('push'), [['https://updates.push.services.mozilla.com/wpush/v2/abc']])

    def wait_for(self, check, what):
        for _ in range(150):
            if check():
                return
            time.sleep(0.1)
        self.fail(what)

    def test_a_voice_message_becomes_a_reply_when_its_words_are_in(self):
        import base64, shlex
        ear = self.root / 'ear.py'
        ear.write_text("import os, sys, time\nopen(os.environ['EAR_RECORD'], 'a').write(sys.argv[1] + '\\n')\ntime.sleep(float(os.environ.get('EAR_SLEEP', '0')))\n"
                       "sys.exit(3) if os.environ.get('EAR_FAIL') else print('  תבדוק את הלוג של אתמול  ')\n")
        env = dict(self.env, THREADS_SONIOX_CMD=shlex.join([sys.executable, str(ear)]), EAR_RECORD=str(self.root / 'ear.log'))
        e = lambda minutes, **more: dict(env, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        webm = base64.b64encode(b'\x1a\x45\xdf\xa3' + b'opus-audio' * 40).decode()
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.assertIn('voice', json.loads((self.board / 'state.json').read_text())['ops'])
        got = self.post({'op': 'reply', 'thread': 'topic', 'cid': 'v1', 'text': '', 'voice': {'type': 'audio/webm;codecs=opus', 'data': webm, 'seconds': 12.34}}, env=e(1, EAR_SLEEP='1.5'))
        self.assertEqual(got, {'ok': True, 'thread': 'topic', 'msg_id': 'm1', 'dup': False})
        t = json.loads((self.board / 'state.json').read_text())['threads']['topic']
        m = t['messages'][0]
        self.assertEqual((m['status'], m['voice']['state'], m['voice']['file'], m['voice']['seconds'], m['placeholder'], t['state']),
                         ('transcribing', 'transcribing', 'uploads/topic/m1.webm', 12.3, True, 'working'))
        self.assertEqual(json.loads(self.run_cli('pending', env=e(1)).stdout), [])                     # not a reply for the agents yet
        self.assertFalse(self.record.exists())
        self.run_cli('ack', 'topic', 'm1', ok=False, env=e(1))
        self.wait_for(lambda: json.loads((self.board / 'state.json').read_text())['threads']['topic']['messages'][0]['status'] == 'pending', 'the words never arrived')
        m = self.thread(env=e(2))['messages'][0]
        self.assertEqual((m['text'], m['voice']['state'], 'placeholder' in m, 'started' in m['voice']), ('תבדוק את הלוג של אתמול', 'done', False, False))
        row = json.loads(self.run_cli('pending', env=e(2)).stdout)[0]
        self.assertEqual((row['text'], row['voice']), ('תבדוק את הלוג של אתמול', {'path': str((self.board / 'uploads/topic/m1.webm').resolve()), 'seconds': 12.3, 'state': 'done'}))
        self.wait_for(self.record.exists, 'the tower was not told')
        self.assertEqual(json.loads(self.record.read_text().splitlines()[0])['args'][0], '[threads] reply in topic (m1): run: threads pending')       # his words are read with `threads pending`, never from the mail
        self.assertIn('ענית: «תבדוק את הלוג', self.thread(env=e(2))['note'])
        self.assertEqual((self.root / 'ear.log').read_text().strip(), str((self.board / 'uploads/topic/m1.webm').resolve()))
        # a failure loses nothing: the message is handed over with the recording and no words
        self.post({'op': 'reply', 'thread': 'topic', 'cid': 'v2', 'text': '', 'voice': {'data': base64.b64encode(b'OggS' + b'x' * 50).decode(), 'seconds': 3}}, env=e(3, EAR_FAIL='1'))
        self.wait_for(lambda: json.loads((self.board / 'state.json').read_text())['threads']['topic']['messages'][1]['status'] == 'pending', 'a failed transcript left the message in the air')
        m = self.thread(env=e(4))['messages'][1]
        self.assertEqual((m['voice']['state'], m['voice']['file'], m['placeholder']), ('failed', 'uploads/topic/m2.ogg', True))
        self.assertIn('התמלול נכשל', m['text'])
        self.assertEqual(json.loads(self.run_cli('pending', env=e(4)).stdout)[1]['voice']['state'], 'failed')
        # a worker that died: the timer starts another, and after three tries the message is handed over as it is
        data = json.loads((self.board / 'state.json').read_text())
        topic = data['threads']['topic']
        topic['messages'].append({'id': 'm3', 'from': 'owner', 'text': 'הקלטה קולית', 'ts': self.T0 + 300, 'status': 'transcribing', 'placeholder': True, 'cid': 'v3',
                                  'voice': {'file': 'uploads/topic/m1.webm', 'bytes': 5, 'seconds': 2, 'state': 'transcribing', 'started': self.T0 + 300, 'tries': 3}})
        topic.update(next=4, voicing=['m3'])
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False))
        self.run_cli('sweep', env=e(10))
        self.assertEqual(self.thread(env=e(10))['messages'][2]['status'], 'transcribing')
        self.run_cli('sweep', env=e(21))
        t = self.thread(env=e(21))
        self.assertEqual((t['messages'][2]['status'], t['messages'][2]['voice']['state'], 'voicing' in t), ('pending', 'failed', False))
        # refusals write nothing
        files = sorted(p.name for p in (self.board / 'uploads/topic').iterdir())
        for bad in ({'data': webm}, {'data': webm, 'seconds': 0}, {'data': webm, 'seconds': 5000}, {'data': 'x!', 'seconds': 3}, {'data': base64.b64encode(b'RIFFxxxxWAVE').decode(), 'seconds': 3},
                    {'data': base64.b64encode(b'OggS' + b'x' * 3_000_001).decode(), 'seconds': 3}, 'x'):
            with self.subTest(bad=str(bad)[:50]):
                self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'v9', 'text': '', 'voice': bad}, ok=False, env=e(22))['ok'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'v9', 'text': '', 'voice': {'data': webm, 'seconds': 3}, 'images': [{'data': 'x'}]}, ok=False, env=e(22))['ok'])
        self.assertEqual(sorted(p.name for p in (self.board / 'uploads/topic').iterdir()), files)
        # a board that cannot transcribe says so in its ops and refuses a recording
        plain = dict(self.env, THREADS_NOW=str(self.T0 + 30 * 60))
        self.run_cli('state', 'topic', 'working', '--note', 'x', env=plain)
        self.assertNotIn('voice', json.loads((self.board / 'state.json').read_text())['ops'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'v8', 'text': '', 'voice': {'data': webm, 'seconds': 3}}, ok=False, env=plain)['ok'])

    def test_only_the_tower_sees_a_run_request_in_pending(self):
        """A ▶ request is the tower's alone (2026-11-20: an agent that read `pending` ran the tower's command before
        the tower did). `pending` leaves a row with `run` out for anyone else; the tower sees it, with its sha256, by
        `--as tower` or THREADS_ROLE=tower. Rows without `run` are for everyone, as before."""
        import hashlib
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', 'הנה:\n```\n! echo hi\n```', env=e(0))
        ask = {'msg_id': 'm1', 'block_index': 0, 'sha256': hashlib.sha256('! echo hi'.encode()).hexdigest()}
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': '▶ הרץ את הפקודה מהודעה m1', 'under': None,
                                   'cid': 'r1', 'run': ask}, env=e(1))['ok'])
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': 'ועוד משהו', 'under': None, 'cid': 'r2'}, env=e(2))['ok'])
        rows = lambda *extra, env=e(3): json.loads(self.run_cli('pending', *extra, env=env).stdout)
        self.assertEqual([r['text'] for r in rows()], ['ועוד משהו'])                     # an agent: no run row at all
        self.assertFalse(any('run' in r for r in rows()))
        for seen in (rows('--as', 'tower'), rows(env=dict(e(3), THREADS_ROLE='tower'))):
            self.assertEqual([r['text'] for r in seen], ['▶ הרץ את הפקודה מהודעה m1', 'ועוד משהו'])
            self.assertEqual(seen[0]['run'], {**ask, 'command': '! echo hi'})          # the sha256 as today
        self.assertEqual([r['text'] for r in rows(env=dict(e(3), THREADS_ROLE='fork'))], ['ועוד משהו'])

    def test_a_run_request_he_saved_is_listed_only_for_the_tower(self):
        """threads-slack3 on saved179: `threads saved` keeps the ▶ guard of `pending` (runrole161): a pending run request
        he saved is the tower's alone; another agent does not see it, nor its text."""
        import hashlib
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', 'הנה:\n```\n! echo hi\n```', env=e(0))
        ask = {'msg_id': 'm1', 'block_index': 0, 'sha256': hashlib.sha256('! echo hi'.encode()).hexdigest()}
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': '▶ הרץ את הפקודה מהודעה m1', 'under': None,
                                   'cid': 'r1', 'run': ask}, env=e(1))['ok'])
        self.assertTrue(self.post({'op': 'save', 'thread': 'topic', 'msg': 'm2', 'on': True}, env=e(2))['ok'])
        self.assertTrue(self.post({'op': 'save', 'thread': 'topic', 'msg': 'm1', 'on': True}, env=e(2))['ok'])
        rows = lambda *extra, env=e(3): json.loads(self.run_cli('saved', '--json', *extra, env=env).stdout)
        self.assertEqual([r['msg'] for r in rows()], ['m1'], 'an agent: the run request is not there at all')
        self.assertNotIn('הרץ', self.run_cli('saved', env=e(3)).stdout)
        self.assertEqual([r['msg'] for r in rows(env=dict(e(3), THREADS_ROLE='fork'))], ['m1'])
        for seen in (rows('--as', 'tower'), rows(env=dict(e(3), THREADS_ROLE='tower'))):
            self.assertEqual(sorted(r['msg'] for r in seen), ['m1', 'm2'])

    def test_he_may_ask_the_tower_to_run_its_own_command(self):
        import hashlib
        e = self.at
        sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', 'כדי לנקות:\n```\n! launchctl list | rg threads\n\n  ! tail -3 ~/Library/Logs/threads-sweep.log  \n```\nואז דיאגרמה:\n```mermaid\ngraph TD; a-->b\n```\nובעברית:\n```\n! echo שלום\n```\n```\nls -la\n```', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', '```\n! rm -rf /tmp/x\n```', env=e(0))
        command = '! launchctl list | rg threads\n! tail -3 ~/Library/Logs/threads-sweep.log'
        reply = {'op': 'reply', 'thread': 'topic', 'text': '▶ הרץ את הפקודה מהודעה m1', 'under': None}
        for name, bad in (('wrong hash', {'msg_id': 'm1', 'block_index': 0, 'sha256': sha(command + ' ')}), ('a diagram', {'msg_id': 'm1', 'block_index': 1, 'sha256': sha('graph TD; a-->b')}),
                          ('hebrew', {'msg_id': 'm1', 'block_index': 2, 'sha256': sha('! echo שלום')}), ('no bang', {'msg_id': 'm1', 'block_index': 3, 'sha256': sha('ls -la')}),
                          ('out of range', {'msg_id': 'm1', 'block_index': 4, 'sha256': sha(command)}), ('not the tower', {'msg_id': 'm2', 'block_index': 0, 'sha256': sha('! rm -rf /tmp/x')}),
                          ('no such message', {'msg_id': 'm9', 'block_index': 0, 'sha256': sha(command)}), ('negative', {'msg_id': 'm1', 'block_index': -1, 'sha256': sha(command)}),
                          ('types', {'msg_id': 'm1', 'block_index': '0', 'sha256': sha(command)}), ('not an object', 'm1')):
            with self.subTest(name):
                self.assertFalse(self.post({**reply, 'cid': 'r0', 'run': bad}, ok=False, env=e(1))['ok'])
        self.assertEqual(len(self.thread(env=e(1))['messages']), 2)
        ask = {'msg_id': 'm1', 'block_index': 0, 'sha256': sha(command)}
        self.assertTrue(self.post({**reply, 'cid': 'r1', 'run': ask}, env=e(2))['ok'])
        self.assertEqual(self.thread(env=dict(e(2), THREADS_ROLE='tower'))['messages'][2]['run'], ask)     # the tower's view
        row = json.loads(self.run_cli('pending', '--as', 'tower', env=e(2)).stdout)[0]
        self.assertEqual((row['run'], row['text']), ({**ask, 'command': command}, '▶ הרץ את הפקודה מהודעה m1'))      # the command comes from the tower's message
        self.assertFalse(self.post({**reply, 'cid': 'r2', 'run': ask}, ok=False, env=e(3))['ok'])                  # asked already, not picked up yet
        self.run_cli('ack', 'topic', 'm3', '--as', 'tower', env=e(4))
        self.assertTrue(self.post({**reply, 'cid': 'r3', 'run': ask}, env=e(5))['ok'])                             # again, after the tower took the first
        self.assertIn('run', json.loads((self.board / 'state.json').read_text())['ops'])

    def test_he_adds_and_rewords_a_task_from_the_reply_box(self):
        """Slash commands (suda m555, m637): `/task <text>` and `/task <n> = <text>` from the page are the page ops
        task-add and task-text, with the checks of `threads task add` and `task set --text`; he is the author."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('task', 'add', 'topic', 'קיימת', '--owner', 'fork', env=e(0))
        got = self.post({'op': 'task-add', 'thread': 'topic', 'text': '  לכתוב   תיעוד '}, env=e(1))
        self.assertEqual((got['ok'], got['n']), (True, 2))
        task = self.thread(env=e(1))['tasks'][1]
        self.assertEqual({k: task.get(k) for k in ('n', 'text', 'status', 'owner', 'by', 'from')},
                         {'n': 2, 'text': 'לכתוב תיעוד', 'status': 'todo', 'owner': '', 'by': 'owner', 'from': None})
        # a thread that says done is not done once he adds work to it
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(2))
        self.run_cli('task', 'set', 'topic', '2', 'done', env=e(2))
        self.run_cli('state', 'topic', 'done', '--note', 'סיימנו', env=e(2))
        self.assertEqual(self.post({'op': 'task-add', 'thread': 'topic', 'text': 'עוד דבר'}, env=e(3))['n'], 3)
        self.assertEqual(self.thread(env=e(3))['state'], 'working')
        # new words: the number stays, the old words are kept with him as the one who changed them
        self.assertTrue(self.post({'op': 'task-text', 'thread': 'topic', 'n': 2, 'text': 'לכתוב את ה-README'}, env=e(4))['ok'])
        task = self.thread(env=e(4))['tasks'][1]
        self.assertEqual((task['n'], task['text'], task['status'], task['history']),
                         (2, 'לכתוב את ה-README', 'done', [{'text': 'לכתוב תיעוד', 'ts': self.T0 + 4 * 3600, 'by': 'owner'}]))
        stamp = (self.board / 'state.json').stat().st_mtime_ns
        self.assertTrue(self.post({'op': 'task-text', 'thread': 'topic', 'n': 2, 'text': 'לכתוב את ה-README'}, env=e(4))['ok'])     # the same words: nothing to write
        self.assertEqual((self.board / 'state.json').stat().st_mtime_ns, stamp)
        # refusals, as the CLI refuses
        for bad in ({'op': 'task-add', 'thread': 'topic', 'text': '   '}, {'op': 'task-add', 'thread': 'topic', 'text': 'x' * 301},
                    {'op': 'task-add', 'thread': 'topic'}, {'op': 'task-add', 'thread': 'topic', 'text': 7}, {'op': 'task-add', 'thread': 'nope', 'text': 'x'},
                    {'op': 'task-text', 'thread': 'topic', 'n': 9, 'text': 'x'}, {'op': 'task-text', 'thread': 'topic', 'n': '2', 'text': 'x'},
                    {'op': 'task-text', 'thread': 'topic', 'n': 2, 'text': ' '}, {'op': 'task-text', 'thread': 'topic', 'n': 2, 'text': 'x' * 301},
                    {'op': 'task-text', 'thread': 'topic', 'n': True, 'text': 'x'}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post(bad, ok=False, env=e(5))['ok'])
        self.assertEqual([k['n'] for k in self.thread(env=e(5))['tasks']], [1, 2, 3])
        # a closed thread takes no new work and no new words (one that archived itself comes back, as with the CLI)
        self.run_cli('close', 'topic', '--force', env=e(6))
        self.assertFalse(self.post({'op': 'task-add', 'thread': 'topic', 'text': 'x'}, ok=False, env=e(7))['ok'])
        self.assertFalse(self.post({'op': 'task-text', 'thread': 'topic', 'n': 1, 'text': 'x'}, ok=False, env=e(7))['ok'])
        self.run_cli('new', 'auto', 'נושא', env=e(7))
        self.run_cli('close', 'auto', env=e(7))
        state = json.loads((self.board / 'state.json').read_text())
        state['threads']['auto']['closed_by'] = 'auto'
        (self.board / 'state.json').write_text(json.dumps(state))
        self.assertEqual(self.post({'op': 'task-add', 'thread': 'auto', 'text': 'חוזר'}, env=e(8))['n'], 1)
        self.assertEqual(self.thread('auto', env=e(8))['status'], 'open')
        ops = json.loads((self.board / 'state.json').read_text())['ops']
        self.assertLessEqual({'task-add', 'task-text', 'command'}, set(ops))

    def test_a_command_to_the_agents_is_a_reply_with_its_name_and_words(self):
        """`/status`, `/explain …`, `/review`, `/split <title>` … from the reply box: an ordinary reply whose text is the
        command line, with `command: {name, args}` checked here, stored on his message and shown in `threads pending`."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        reply = {'op': 'reply', 'thread': 'topic', 'under': None}
        self.assertTrue(self.post({**reply, 'cid': 'c1', 'text': '/מצב', 'command': {'name': 'status', 'args': ''}}, env=e(1))['ok'])
        self.post({**reply, 'cid': 'c2', 'text': '/explain the cache', 'command': {'name': 'explain', 'args': '  the   cache '}}, env=e(1))
        self.post({**reply, 'cid': 'c3', 'text': 'just words'}, env=e(1))
        msgs = self.thread(env=e(1))['messages']
        self.assertEqual([m.get('command') for m in msgs], [{'name': 'status', 'args': ''}, {'name': 'explain', 'args': 'the cache'}, None])
        rows = json.loads(self.run_cli('pending', env=e(1)).stdout)
        self.assertEqual([(r['text'], r.get('command')) for r in rows],
                         [('/מצב', {'name': 'status', 'args': ''}), ('/explain the cache', {'name': 'explain', 'args': 'the cache'}), ('just words', None)])
        shown = self.run_cli('show', 'topic', env=e(1)).stdout
        self.assertEqual((shown.count('[פקודה: /status]'), shown.count('[פקודה: /explain the cache]')), (1, 1))
        for name in ('review', 'prs', 'draft', 'install'):
            with self.subTest(name=name):
                self.assertTrue(self.post({**reply, 'cid': 'k-' + name, 'text': '/' + name, 'command': {'name': name, 'args': ''}}, env=e(1))['ok'])
        self.assertTrue(self.post({**reply, 'cid': 'k-split', 'text': '/split A new topic', 'command': {'name': 'split', 'args': 'A new topic'}}, env=e(1))['ok'])
        # refusals: an unknown command, bad words, a command beside what a command does not carry, on another op
        count = len(self.thread(env=e(1))['messages'])
        for name, bad in (('unknown', {**reply, 'text': '/rm', 'command': {'name': 'rm', 'args': ''}}),
                          ('a page action is not an agent command', {**reply, 'text': '/done', 'command': {'name': 'done', 'args': ''}}),
                          ('not an object', {**reply, 'text': '/status', 'command': 'status'}),
                          ('extra keys', {**reply, 'text': '/status', 'command': {'name': 'status', 'args': '', 'run': 'x'}}),
                          ('no args key', {**reply, 'text': '/status', 'command': {'name': 'status'}}),
                          ('args not text', {**reply, 'text': '/status', 'command': {'name': 'status', 'args': 3}}),
                          ('two lines', {**reply, 'text': '/explain a', 'command': {'name': 'explain', 'args': 'a\nb'}}),
                          ('too long', {**reply, 'text': '/explain a', 'command': {'name': 'explain', 'args': 'x' * 301}}),
                          ('split needs a title', {**reply, 'text': '/split', 'command': {'name': 'split', 'args': ' '}}),
                          ('prs takes no words', {**reply, 'text': '/prs all', 'command': {'name': 'prs', 'args': 'all'}}),
                          ('the text is the command line', {**reply, 'text': 'status please', 'command': {'name': 'status', 'args': ''}}),
                          ('with a picture', {**reply, 'text': '/status', 'command': {'name': 'status', 'args': ''}, 'images': []}),
                          ('as an answer', {**reply, 'text': '/status', 'command': {'name': 'status', 'args': ''}, 'q': 'm1'}),
                          ('run without the block', {**reply, 'text': '/run', 'command': {'name': 'run', 'args': ''}}),
                          ('on another op', {'op': 'done', 'thread': 'topic', 'last': 'm1', 'command': {'name': 'status', 'args': ''}}),
                          ('on a task', {'op': 'task-add', 'thread': 'topic', 'text': 'x', 'command': {'name': 'status', 'args': ''}})):
            with self.subTest(name):
                self.assertFalse(self.post({**bad, 'cid': 'bad-' + name}, ok=False, env=e(2))['ok'])
        self.assertEqual(len(self.thread(env=e(2))['messages']), count)
        self.assertEqual(self.thread(env=e(2))['tasks'], [])
        # a command answers no question, also when it quotes the question's message: the question keeps its buttons
        self.run_cli('ask', 'topic', 'איזה?', '--options', 'א,ב', '--from', 'fork', env=e(2))
        qid = self.thread(env=e(2))['question']['id']
        self.assertTrue(self.post({**reply, 'cid': 'c-q1', 'text': '/explain', 'command': {'name': 'explain', 'args': ''}, 'under': qid, 'reply_to': qid}, env=e(2))['ok'])
        after = self.thread(env=e(2))
        self.assertEqual((after['question']['id'], after['state'], 're' in after['messages'][-1]), (qid, 'on-owner', False))
        self.assertTrue(self.post({**reply, 'cid': 'c-q2', 'text': 'א', 'under': qid}, env=e(2))['ok'])       # his words do answer it
        self.assertIsNone(self.thread(env=e(2))['question'])
        # a closed thread takes no command
        self.run_cli('close', 'topic', env=e(3))
        self.assertFalse(self.post({**reply, 'cid': 'c9', 'text': '/status', 'command': {'name': 'status', 'args': ''}}, ok=False, env=e(4))['ok'])
        # only his message carries a command: what an agent writes is text, also when it starts with a slash, and a
        # command written into an agent's message by hand is neither shown nor handed on
        self.run_cli('reopen', 'topic', env=e(5))
        self.run_cli('say', 'topic', '--from', 'fork', '/status', env=e(5))
        self.assertNotIn('command', self.thread(env=e(5))['messages'][-1])
        before = self.run_cli('show', 'topic', env=e(5)).stdout.count('[פקודה:')
        state = json.loads((self.board / 'state.json').read_text())
        state['threads']['topic']['messages'][-1]['command'] = {'name': 'status', 'args': ''}
        (self.board / 'state.json').write_text(json.dumps(state))
        self.assertEqual(self.run_cli('show', 'topic', env=e(5)).stdout.count('[פקודה:'), before)
        self.assertNotIn(state['threads']['topic']['messages'][-1]['id'], [r['msg_id'] for r in json.loads(self.run_cli('pending', env=e(5)).stdout)])

    def test_slash_run_asks_for_the_last_block_through_the_run_flow(self):
        """`/run` is the ▶ request for the last block of the thread: the reply carries `run` (checked as today) and
        `command: {name: run}`; the stored text is the server's own, as for a press on ▶."""
        import hashlib
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('say', 'topic', '--from', 'tower', '```\n! echo hi\n```', env=e(0))
        ask = {'msg_id': 'm1', 'block_index': 0, 'sha256': hashlib.sha256(b'! echo hi').hexdigest()}
        reply = {'op': 'reply', 'thread': 'topic', 'text': '/run', 'under': None, 'last': 'm1'}
        self.assertFalse(self.post({**reply, 'cid': 'r0', 'run': {**ask, 'sha256': '0' * 64}, 'command': {'name': 'run', 'args': ''}}, ok=False, env=e(1))['ok'])
        self.assertFalse(self.post({**reply, 'cid': 'r1', 'run': ask, 'command': {'name': 'status', 'args': ''}}, ok=False, env=e(1))['ok'])
        self.assertTrue(self.post({**reply, 'cid': 'r2', 'run': ask, 'command': {'name': 'run', 'args': ''}}, env=e(2))['ok'])
        row = json.loads(self.run_cli('pending', '--as', 'tower', env=e(2)).stdout)[0]
        self.assertEqual((row['run']['command'], row['command'], row['text']), ('! echo hi', {'name': 'run', 'args': ''}, '▶ הרץ את הפקודה מהודעה m1'))

    def test_tasks_come_before_done_and_stale_ones_are_named(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבנות את הטופס', '--owner', 'fork-a', env=e(0))
        self.run_cli('task', 'add', 'topic', 'לבדוק בטלפון', '--owner', 'owner', env=e(0))
        self.run_cli('task', 'set', 'topic', '1', 'working', env=e(0))
        r = self.run_cli('say', 'topic', '--from', 'fork', 'התקדמות', '--state', 'working', '--note', 'בונה', '--by', 'fork-a', env=e(1))
        self.assertEqual(r.stderr, '')                                                              # an hour is not stale
        r = self.run_cli('say', 'topic', '--from', 'fork', 'עוד', '--state', 'working', '--note', 'בונה', '--by', 'fork-a', env=e(3))
        self.assertRegex(r.stderr, r'^threads: task 1 «לבנות את הטופס» still working since \d\d:\d\d \(threads task set topic 1 <status> --note …\)\n$')
        self.assertEqual(self.run_cli('state', 'topic', 'working', '--note', 'x', '--by', 'someone-else', env=e(3)).stderr, '')
        self.assertIn('task 1', self.run_cli('state', 'topic', 'working', '--note', 'x', env=e(3)).stderr)        # nobody named: every open task counts
        for cmd in (['state', 'topic', 'done'], ['resolve', 'topic'], ['say', 'topic', '--from', 'fork', 'סיימתי', '--state', 'done']):
            r = self.run_cli(*cmd, ok=False, env=e(4))
            self.assertIn('1 (working) לבנות את הטופס; 2 (todo) לבדוק בטלפון', r.stderr)
        self.assertEqual(len(self.thread(env=e(4))['messages']), 2)
        self.run_cli('state', 'topic', 'done', '--force', env=e(4))
        self.assertEqual(self.thread(env=e(4))['state'], 'done')
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(5))
        self.run_cli('task', 'set', 'topic', '2', 'done', env=e(5))
        self.assertEqual(self.run_cli('resolve', 'topic', env=e(5)).stderr, '')

    def test_a_board_that_is_not_the_real_one_reaches_nothing_outside(self):
        """No stand-in named, and the board is a test's: no mail to the tower, no phone alert, no push, no
        transcription service. (HOME is a fake and the proxy is dead, so a miss here cannot reach anything either.)"""
        home, tools, calls = self.root / 'home', self.root / 'tools', self.root / 'outside-calls.txt'
        (home / '.local/bin').mkdir(parents=True)
        tools.mkdir()
        (home / '.soniox').write_text('FAKE-KEY-OF-A-TEST\n')
        for folder, name in ((tools, 'tuios'), (tools, 'snap'), (home / '.local/bin', 'snap')):
            (folder / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n')
            (folder / name).chmod(0o755)
        boardlib = os.environ.get('THREADS_BOARDLIB_DIR') or str(Path.home() / '.claude/skills/html-interview-board')
        env = {k: v for k, v in self.env.items() if k not in ('THREADS_NOTIFY_CMD', 'THREADS_NOTIFY', 'THREADS_PUSH_CMD', 'THREADS_SNAP_CMD', 'THREADS_SONIOX_CMD', 'THREADS_CONFIG_DIR')}
        env.update(HOME=str(home), THREADS_BOARDLIB_DIR=boardlib, PATH=f"{tools}{os.pathsep}{env['PATH']}", TZ='UTC',
                   https_proxy='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
        e = lambda minutes: dict(env, THREADS_NOW=str(self.T0 + minutes * 60))
        self.run_cli('install', env=e(0))
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'שלום'}, env=e(1))['ok'])          # would mail the tower
        private = self.root / '.threads-config/threads'
        (private / 'push-subs.json').write_text(json.dumps({'https://fcm.googleapis.com/fcm/send/abc': 1}))
        self.run_cli('notify', '--snap', 'on', env=e(2))
        self.run_cli('say', 'topic', '--from', 'fork', 'תסתכל', env=e(3))                                                  # would push
        self.run_cli('sweep', env=e(20))                                                                                   # would alert the phone
        data = json.loads((self.board / 'state.json').read_text())
        self.assertEqual(data['threads']['topic']['alert']['snapped'], self.T0 + 20 * 60)                                  # the alert WAS due
        (self.board / 'uploads/topic').mkdir(parents=True)
        (self.board / 'uploads/topic/m9.webm').write_bytes(b'\x1a\x45\xdf\xa3audio')
        data['threads']['topic']['messages'].append({'id': 'm9', 'from': 'owner', 'text': 'הקלטה קולית', 'ts': self.T0, 'status': 'transcribing', 'placeholder': True, 'cid': 'v',
                                                     'voice': {'file': 'uploads/topic/m9.webm', 'bytes': 9, 'seconds': 2, 'state': 'transcribing'}})
        data['threads']['topic'].update(next=10, voicing=['m9'])
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False))
        self.run_cli('sweep', env=e(40))                                                                                   # would start a transcribing worker
        m = [x for x in self.thread(env=e(40))['messages'] if x['id'] == 'm9'][0]
        self.assertEqual((m['status'], m['voice']['state'], m['voice']['error']), ('pending', 'failed', 'this board does not transcribe'))      # settled at once, by nobody outside
        self.assertNotIn('voice', json.loads((self.board / 'state.json').read_text())['ops'])
        self.run_cli('transcribe', 'topic', 'm9', env=e(41))
        time.sleep(1.5)                                                                                                    # anything detached has had its chance
        self.assertFalse(calls.exists(), calls.read_text() if calls.exists() else '')
        log = self.board / 'notify.log'
        self.assertFalse(log.exists(), log.read_text() if log.exists() else '')                                            # not even an attempt that failed

    def test_his_tasks_have_one_owner_name(self):
        self.new()
        self.run_cli('task', 'add', 'topic', 'לבדוק בטלפון', '--owner', 'Human')
        self.run_cli('task', 'add', 'topic', 'לבנות', '--owner', 'fork-a')
        self.run_cli('task', 'set', 'topic', '2', 'working', '--owner', 'ME')
        self.assertEqual([k['owner'] for k in self.js('tasks', 'topic', '--json')], ['owner', 'owner'])

    def test_options_with_pictures_keep_their_order_and_mark_the_recommended(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        one, two = self.root / 'one.png', self.root / 'two.png'
        one.write_bytes(self.png(extra=((b'tEXt', b'Author\0x'),)))
        two.write_bytes(self.png(w=4, h=4))
        self.run_cli('ask', 'topic', 'איזה אייקון?', '--options', 'א. בועה,ב. שרשור,ג. סולמית', '--option-image', f'א. בועה={one}', '--option-image', f'ג. סולמית={two}',
                     '--recommended', 'ב. שרשור', env=e(1))
        t = self.thread(env=e(1))
        q = t['question']
        self.assertEqual((q['options'], q['recommended']), (['א. בועה', 'ב. שרשור', 'ג. סולמית'], 'ב. שרשור'))           # as written: the recommended one is marked, not moved
        self.assertEqual(q['option_images'], {'א. בועה': {'file': 'uploads/topic/m1-o1.png', 'w': 3, 'h': 2}, 'ג. סולמית': {'file': 'uploads/topic/m1-o3.png', 'w': 4, 'h': 4}})
        self.assertEqual((t['messages'][0]['option_images'], t['messages'][0]['recommended']), (q['option_images'], 'ב. שרשור'))
        self.assertEqual((self.board / 'uploads/topic/m1-o1.png').read_bytes(), self.png())                              # cleaned like any picture
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'ג. סולמית', 'q': 'm1'}, env=e(2))['ok'])
        # ticks: a picture named beside the item in the groups file, or by --option-image
        groups = self.root / 'q.json'
        groups.write_text(json.dumps([{'title': 'סגנון', 'items': [{'text': 'שטוח', 'image': 'one.png'}, {'text': 'מלא', 'recommended': True}]},
                                      {'title': 'צבע', 'items': ['סגול', 'ורוד']}], ensure_ascii=False))
        self.run_cli('ask', 'topic', 'מה לשלב?', '--groups-file', str(groups), '--option-image', f'ורוד={two}', env=e(3))
        q = self.thread(env=e(3))['question']
        self.assertEqual(q['groups'][0]['items'][0], {'text': 'שטוח', 'recommended': False, 'image': {'file': 'uploads/topic/m3-o1.png', 'w': 3, 'h': 2}})
        self.assertEqual((q['groups'][1]['items'][1]['image']['file'], sorted(q['option_images'])), ('uploads/topic/m3-o4.png', ['ורוד', 'שטוח']))
        self.run_cli('ask', 'topic', 'ומה עוד?', '--multi', '--options', 'א,ב,ג', '--recommended', 'ב', env=e(4))
        self.assertEqual([i['recommended'] for i in self.thread(env=e(4))['question']['groups'][0]['items']], [False, True, False])
        # labelled options out of their order are refused; unlabelled ones may come in any order
        count = len(self.thread(env=e(4))['messages'])
        junk = self.root / 'junk.png'
        junk.write_text('not a picture')
        for bad in (['--options', 'ב. לדחוף,א. לחכות'], ['--options', '2) שתיים,1) אחת'], ['--options', 'B - second,A - first'], ['--options', 'כן,לא', '--recommended', 'אולי'],
                    ['--options', 'כן,לא', '--option-image', f'אולי={one}'], ['--options', 'כן,לא', '--option-image', f'כן={junk}'],
                    ['--options', 'כן,לא', '--option-image', f'כן={one}', '--option-image', f'כן={two}'], ['--options', 'כן,לא', '--option-image', 'כן']):
            with self.subTest(bad=bad[1:]):
                self.run_cli('ask', 'topic', 'רע', *bad, ok=False, env=e(5))
        self.assertEqual(len(self.thread(env=e(5))['messages']), count)
        self.assertFalse((self.board / 'uploads/topic/m5-o1.png').exists())
        for fine in ('לא,כן', 'א. ראשון,ג. שלישי', '1. אחת,2. שתיים,10. עשר', 'לדחוף היום,לחכות'):
            self.run_cli('ask', 'topic', 'טוב', '--options', fine, '--replace-all', env=e(6))      # one at a time: only the options are checked here

    def test_a_live_message_is_updated_in_place(self):
        base = self.notified()
        e = lambda minutes, **more: dict(base, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc'}}, env=e(0))
        card = '```status\n{"title":"PR","state":"running"}\n```'
        self.assertEqual(self.run_cli('say', 'topic', '--from', 'fork', card, '--live', '--state', 'working', '--note', 'CI רץ', env=e(1)).stdout.strip(), 'm1')
        self.run_cli('say', 'topic', '--from', 'fork', 'הודעה רגילה', '--state', 'working', '--note', 'CI רץ', env=e(2))
        self.run_cli('update', 'topic', 'm1', '--from', 'fork', card.replace('running', 'ok'), env=e(3))
        t = self.thread(env=e(3))
        m = t['messages'][0]
        self.assertEqual((m['id'], m['ts'], m['edited'], m['edits'], m['live'], 'ok' in m['text'], len(t['messages'])), ('m1', self.T0 + 60, self.T0 + 180, 1, True, True, 2))
        self.assertEqual((t['state'], t['note'], self.tellings('push')), ('working', 'CI רץ', []))                      # nobody's turn changed, nobody was told
        state = (self.board / 'state.json').read_bytes()
        self.run_cli('update', 'topic', 'm1', '--from', 'fork', card.replace('running', 'ok'), env=e(4))                # the same text again: nothing is written
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.run_cli('update', 'topic', 'm1', '--from', 'fork', '-', '--state', 'on-owner', '--note', 'ה-CI נכשל: להחליט אם לחזור', input=card.replace('running', 'failed'), env=e(5))
        t = self.thread(env=e(5))
        self.assertEqual((t['state'], t['messages'][0]['edits'], len(self.tellings('push'))), ('on-owner', 2, 1))      # with a turn of its own he IS told
        self.assertIn('[הודעה חיה · עודכנה 2 פעמים]', self.run_cli('show', 'topic', env=e(5)).stdout)
        # only a message that was made to change, by its own sender; never his, never a question, never in a closed thread
        self.run_cli('ask', 'topic', 'שאלה?', '--options', 'כן,לא', env=e(6))
        self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': 'כן', 'q': 'm3'}, env=e(7))
        for bad in (['m2', '--from', 'fork', 'x'], ['m1', '--from', 'tower', 'x'], ['m3', '--from', 'fork', 'x'], ['m4', '--from', 'fork', 'x'], ['m9', '--from', 'fork', 'x'],
                    ['m1', '--from', 'fork', ' '], ['m1', '--from', 'fork', 'x', '--note', 'בלי מצב'], ['m1', '--from', 'owner', 'x']):
            with self.subTest(bad=bad):
                self.run_cli('update', 'topic', *bad, ok=False, env=e(8))
        self.run_cli('say', 'topic', '--from', 'owner', 'x', '--live', ok=False, env=e(8))
        self.run_cli('close', 'topic', env=e(9))
        self.run_cli('update', 'topic', 'm1', '--from', 'fork', 'אחרי הסגירה', ok=False, env=e(9))
        self.assertEqual(self.thread(env=e(9))['messages'][0]['edits'], 2)

    def test_a_message_is_split_into_a_topic_of_its_own(self):
        base = self.notified()
        e = lambda minutes, **more: dict(base, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        self.run_cli('new', 'source', 'נושא המקור', '--state', 'working', '--note', 'בונה', env=e(0))
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc'}}, env=e(0))
        self.run_cli('say', 'source', '--from', 'fork', 'דבר ראשון', '--state', 'working', '--note', 'בונה', env=e(1))
        self.run_cli('say', 'source', '--from', 'fork', 'ודרך אגב, **המזגן בסלון** לא מגיב כבר יומיים', env=e(2))           # on him, pushed once
        self.post({'op': 'seen', 'thread': 'source', 'last': 'm2'}, env=e(3))
        got = self.post({'op': 'new', 'cid': 's1', 'title': '', 'text': '', 'split': {'thread': 'source', 'msg': 'm2'}}, env=e(4))
        self.assertTrue(got['ok'])
        new = self.thread(got['thread'], env=e(4))
        self.assertEqual(new['split_from'], {'thread': 'source', 'msg': 'm2', 'from': 'fork', 'ts': self.T0 + 120, 'text': 'ודרך אגב, **המזגן בסלון** לא מגיב כבר יומיים'})
        self.assertEqual((new['title'], new['title_pending'], new['links']),
                         ('ודרך אגב, המזגן בסלון לא מגיב כבר…', True, [{'label': 'מקור: נושא המקור', 'url': '/threads/suda.html#source/m2'}]))
        self.assertEqual(self.js('pending')[0]['split_from']['text'], 'ודרך אגב, **המזגן בסלון** לא מגיב כבר יומיים')    # the fork gets the message it was cut from
        src = self.thread('source', env=e(4))
        line = src['messages'][-1]
        self.assertEqual(({k: line[k] for k in ('id', 'from', 'text', 'split_to')}, 'status' in line, src['messages'][1]['split_to']),
                         ({'id': 'm3', 'from': 'system', 'text': 'פוצל לנושא חדש', 'split_to': {'thread': got['thread'], 'title': new['title']}}, False, got['thread']))
        self.assertEqual((src['state'], src['seen']['msg'], 'alert' in src, len(self.tellings('push'))), ('on-owner', 'm3', False, 1))      # nobody's turn, and no news
        self.run_cli('sweep', env=e(60))
        self.assertEqual(len(self.tellings('push')), 1)
        self.assertIn('split', json.loads((self.board / 'state.json').read_text())['ops'])
        # with words of his own they are his first message; an unseen source is not told again because of the line
        self.run_cli('say', 'source', '--from', 'fork', 'עוד עניין: הדלת', env=e(61))                                    # pushed (2), not seen
        got2 = self.post({'op': 'new', 'cid': 's2', 'title': 'הדלת', 'text': 'תבדוק מי אחראי', 'split': {'thread': 'source', 'msg': 'm4'}}, env=e(62))
        self.assertEqual((self.thread(got2['thread'], env=e(62))['messages'][0]['text'], len(self.tellings('push'))), ('תבדוק מי אחראי', 2))
        self.assertEqual(self.post({'op': 'new', 'cid': 's2', 'title': 'הדלת', 'text': 'תבדוק מי אחראי', 'split': {'thread': 'source', 'msg': 'm4'}}, env=e(63))['dup'], True)
        count = len(json.loads((self.board / 'state.json').read_text())['threads'])
        for bad in ({'thread': 'ghost', 'msg': 'm1'}, {'thread': 'source', 'msg': 'm99'}, {'thread': 'source', 'msg': 'm3'}, {'thread': 'source'}, 'source', {'thread': 5, 'msg': 'm1'}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'new', 'cid': 's9', 'title': 'עוד', 'text': 'x', 'split': bad}, ok=False, env=e(64))['ok'])
        self.assertEqual(len(json.loads((self.board / 'state.json').read_text())['threads']), count)

    def test_help_visual_prints_the_chapter_of_the_skill(self):
        shown = self.run_cli('help', 'visual').stdout
        self.assertTrue(shown.startswith('## Visual toolkit'))
        for word in ('mermaid', '--image', '--html', '--snippet', '--option-image', '--recommended', '--groups-file', 'actions', '--live', 'threads update',
                     'threads task', 'reply_to.quote', 'https://github.com/'):
            self.assertIn(word, shown)
        self.assertNotIn('visual:end', shown)
        self.assertEqual((ROOT / 'SKILL.md').read_text().count('<!-- visual:start -->'), 1)
        for flag in ('--option-image', '--recommended', '--live', '--image', '--caption', '--html', '--snippet', '--multi', '--groups-file'):      # the chapter names only what the CLI has
            self.assertIn(flag, self.run_cli('ask' if flag in ('--option-image', '--recommended', '--multi', '--groups-file') else 'say', '--help').stdout)
        self.assertIn('usage:', self.run_cli('help').stdout)

    def test_his_place_in_a_thread_follows_him_to_other_devices(self):
        base = self.notified()
        e = lambda minutes, **more: dict(base, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.post({'op': 'push-subscribe', 'sub': {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc'}}, env=e(0))
        for n in range(1, 4):
            self.run_cli('say', 'topic', '--from', 'fork', f'הודעה {n}', '--state', 'working', '--note', 'בונה', env=e(n))
        self.run_cli('say', 'topic', '--from', 'fork', 'תסתכל על זה', env=e(4))                                           # m4, on him: pushed
        places = lambda: json.loads((self.board / 'places.json').read_text())['places']
        self.assertIn('place', json.loads((self.board / 'state.json').read_text())['ops'])
        # the phone: he reads up to m2, m1 at the top of the screen
        got = self.post({'op': 'place', 'thread': 'topic', 'seen': 'm2', 'at': 'm1', 'bottom': False}, env=e(5))
        self.assertEqual(got, {'ok': True, 'thread': 'topic', 'op': 'place', 'ts': self.T0 + 300})
        self.assertEqual(places()['topic'], {'seen': 'm2', 'at': 'm1', 'bottom': False, 'ts': self.T0 + 300})
        t = self.thread(env=e(5))
        self.assertEqual((t['seen'], 'alert' in t), ({'msg': 'm2', 'ts': self.T0 + 300}, True))                           # seen moved in the state too; m4 is still unseen
        # a scroll that shows nothing new touches only the small file: no state write, no page woken
        state, pulse = (self.board / 'state.json').read_bytes(), self.board / '.pulse'
        os.utime(pulse, (1, 1))
        self.assertEqual(self.post({'op': 'place', 'thread': 'topic', 'seen': 'm2', 'at': 'm2', 'bottom': False}, env=e(6))['ts'], self.T0 + 360)
        self.assertEqual(self.post({'op': 'place', 'thread': 'topic', 'seen': 'm1', 'at': 'm1', 'bottom': False}, env=e(7))['ts'], self.T0 + 420)      # scrolled back up
        self.assertEqual(((self.board / 'state.json').read_bytes(), pulse.stat().st_mtime, places()['topic']['at']), (state, 1, 'm1'))
        self.assertEqual(self.thread(env=e(7))['seen']['msg'], 'm2')                                                      # what he has seen never moves back
        written = (self.board / 'places.json').stat().st_mtime_ns
        self.assertEqual(self.post({'op': 'place', 'thread': 'topic', 'seen': 'm1', 'at': 'm1', 'bottom': False}, env=e(8))['ts'], self.T0 + 420)      # the same place again: nothing written
        self.assertEqual((self.board / 'places.json').stat().st_mtime_ns, written)
        # the Mac: he reads to the end; the alert is over, the place says "at the end" for the device he opens next
        self.assertTrue(self.post({'op': 'place', 'thread': 'topic', 'seen': 'm4', 'at': 'm3', 'bottom': True}, env=e(9))['ok'])
        t = self.thread(env=e(9))
        self.assertEqual((t['seen']['msg'], 'alert' in t, places()['topic']), ('m4', False, {'seen': 'm4', 'at': 'm3', 'bottom': True, 'ts': self.T0 + 540}))
        self.run_cli('notify', '--snap', 'on', env=e(10))
        self.run_cli('sweep', env=e(60))
        self.assertEqual(self.tellings('snap'), [])
        # refused: a message that is not of this thread, a thread that is not, wrong kinds
        for bad in ({'seen': 'm9'}, {'at': 'm9'}, {'thread': 'ghost'}, {'bottom': 'yes'}, {'seen': 4}, {'at': None}, {'seen': ''}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'place', 'thread': 'topic', 'seen': 'm4', 'at': 'm4', 'bottom': True, **bad}, ok=False, env=e(61))['ok'])
        self.assertEqual(places()['topic']['ts'], self.T0 + 540)
        self.run_cli('new', 'empty', 'ריק', env=e(62))
        self.assertTrue(self.post({'op': 'place', 'thread': 'empty', 'seen': '', 'at': '', 'bottom': True}, env=e(63))['ok'])
        self.run_cli('rm', 'topic', '--yes', env=e(64))
        self.assertEqual(sorted(places()), ['empty'])                                                                     # a removed thread has no place

    def test_finished_tasks_move_to_an_archive(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        for text in ('ראשונה', 'שנייה', 'שלישית', 'רביעית'):
            self.run_cli('task', 'add', 'topic', text, env=e(0))
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(1))
        self.run_cli('task', 'set', 'topic', '2', 'done', env=e(2))
        tasks = lambda h: {k['n']: k.get('archived') for k in self.thread(env=e(h))['tasks']}
        self.assertIn('task-archive', json.loads((self.board / 'state.json').read_text())['ops'])
        # his tap on one task, and back
        self.assertEqual(self.post({'op': 'task-archive', 'thread': 'topic', 'n': 1, 'on': True}, env=e(3))['archived'], [1])
        self.assertEqual(tasks(3), {1: self.T0 + 3 * 3600, 2: None, 3: None, 4: None})
        state = (self.board / 'state.json').read_bytes()
        self.assertEqual(self.post({'op': 'task-archive', 'thread': 'topic', 'n': 1, 'on': True}, env=e(3.5))['archived'], [1])      # a second tap writes nothing
        self.assertEqual((self.board / 'state.json').read_bytes(), state)
        self.assertEqual(self.post({'op': 'task-archive', 'thread': 'topic', 'n': 1, 'on': False}, env=e(4))['archived'], [])
        # one tap for everything that is done; a task that is not done cannot go
        self.assertEqual(self.post({'op': 'task-archive', 'thread': 'topic', 'n': 'done', 'on': True}, env=e(5))['archived'], [1, 2])
        for bad in ({'n': 3, 'on': True}, {'n': 9, 'on': True}, {'n': 'done', 'on': False}, {'n': 'all', 'on': True}, {'n': 1}, {'n': 1, 'on': 'yes'}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post({'op': 'task-archive', 'thread': 'topic', **bad}, ok=False, env=e(5))['ok'])
        t = self.thread(env=e(5))
        self.assertEqual((t['state'], t['note'], [k['n'] for k in t['tasks']]), ('working', 'בונה', [1, 2, 3, 4]))          # kept, and nobody's turn moved
        # the list hides them unless asked; a task opened again comes back
        self.assertEqual([row.split('\t')[0] for row in self.run_cli('tasks', 'topic', env=e(5)).stdout.splitlines()[1:]], ['3', '4'])
        self.assertEqual(len(self.run_cli('tasks', 'topic', '--all', env=e(5)).stdout.splitlines()), 5)
        self.assertEqual(len(json.loads(self.run_cli('tasks', 'topic', '--json', env=e(5)).stdout)), 4)
        self.run_cli('task', 'set', 'topic', '2', 'working', env=e(6))
        self.assertTrue(self.post({'op': 'task', 'thread': 'topic', 'n': 1, 'status': 'todo'}, env=e(6))['ok'])
        self.assertEqual(tasks(6), {1: None, 2: None, 3: None, 4: None})
        # agents: one task, or everything done long enough
        self.run_cli('task', 'set', 'topic', '1', 'done', env=e(7))
        self.run_cli('task', 'set', 'topic', '3', 'done', env=e(9))
        self.run_cli('task', 'archive', 'topic', '2', ok=False, env=e(9))                                                 # not done
        self.run_cli('task', 'archive', 'topic', ok=False, env=e(9))
        self.run_cli('task', 'archive', 'topic', '1', '--done-older-than', '1', ok=False, env=e(9))
        self.assertEqual(self.run_cli('task', 'archive', 'topic', '--done-older-than', '1', env=e(9.5)).stdout.strip(), '1')
        self.assertEqual(self.run_cli('task', 'archive', 'topic', '3', env=e(9.5)).stdout.strip(), '3')
        self.run_cli('task', 'unarchive', 'topic', '3', env=e(9.6))
        self.assertEqual({n for n, when in tasks(9.6).items() if when}, {1})
        # by itself: twelve hours after a task was done (the timer's sweep), and the policy can change that
        self.run_cli('sweep', env=e(20.9))
        self.assertIsNone(tasks(20.9)[3])
        self.run_cli('sweep', '--quiet', env=e(21.1))
        self.assertEqual(tasks(21.1)[3], self.T0 + 21.1 * 3600)
        self.run_cli('policy', '--task-archive-hours', '0', env=e(22))
        self.run_cli('task', 'set', 'topic', '4', 'done', env=e(22))
        self.run_cli('sweep', env=e(500))
        self.assertIsNone(tasks(500)[4])

    def test_a_thread_marked_urgent_and_the_mark_taken_away(self):
        """The owner, suda m501/m505: when he says something is urgent it goes to the top of its section. The mark is
        his (a page op) or an agent's (`threads urgent <id>`); it moves nobody's turn and alerts nobody; it goes
        when it is taken away or when the thread is closed."""
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        state = lambda: json.loads((self.board / 'state.json').read_text())['threads']['topic']
        self.assertIn('urgent', json.loads((self.board / 'state.json').read_text())['ops'])
        before = state()
        self.run_cli('urgent', 'topic', env=e(1))
        self.assertEqual(state()['urgent'], float(e(1)['THREADS_NOW']))
        self.assertEqual((state()['state'], state()['note'], state()['state_ts']), (before['state'], before['note'], before['state_ts']), 'the mark moved the turn')
        self.run_cli('urgent', 'topic', env=e(2))                    # again: the first time stays
        self.assertEqual(state()['urgent'], float(e(1)['THREADS_NOW']))
        self.run_cli('urgent', 'topic', '--off', env=e(3))
        self.assertNotIn('urgent', state())
        # his press on the page
        self.assertTrue(self.post({'op': 'urgent', 'thread': 'topic', 'on': True}, env=e(4))['ok'])
        self.assertEqual(state()['urgent'], float(e(4)['THREADS_NOW']))
        for bad in ('yes', 1, None):
            self.assertFalse(self.post({'op': 'urgent', 'thread': 'topic', 'on': bad}, ok=None, env=e(5)).get('ok'), bad)
        self.assertTrue(self.post({'op': 'urgent', 'thread': 'topic', 'on': False}, env=e(6))['ok'])
        self.assertNotIn('urgent', state())
        # closed: the mark goes with it
        self.run_cli('urgent', 'topic', env=e(7))
        self.run_cli('close', 'topic', env=e(8))
        self.assertNotIn('urgent', state())
        self.run_cli('urgent', 'topic', ok=False, env=e(9))          # a closed thread is not urgent

    def test_a_pull_request_merged_after_its_chip_shows_soon(self):
        """The owner, suda m469: "is there a way to see on the GitHub chip that something was merged after the chip was
        made, without making everything complicated?", and m478: "not to load with updates: only when needed. In
        the chat itself, update; not checking all the time. Out and back, update in the background. A press on the
        chip, update a minute or two later (sometimes I merge there)". The timer never looks; opening the thread
        looks at its open pull requests a minute old; a press on a chip asks for that one alone, a minute later."""
        import shlex
        gh = self.root / 'gh.py'
        gh.write_text("""import json, os, sys
url = sys.argv[1]
open(os.environ['GH_RECORD'], 'a').write(url + '\\n')
merged = os.environ.get('GH_MERGED') == url
print(json.dumps({'number': int(url.rsplit('/', 1)[1]), 'title': 't', 'state': 'MERGED' if merged else 'OPEN', 'isDraft': False,
                  'author': {'login': 'y'}, 'baseRefName': 'main', 'headRefName': 'x', 'reviewDecision': '', 'statusCheckRollup': [], 'updatedAt': '2026-11-16T10:00:00Z'}))
""")
        record = self.root / 'gh.log'
        env = dict(self.env, THREADS_GH_CMD=shlex.join([sys.executable, str(gh)]), GH_RECORD=str(record))
        e = lambda minutes, **more: dict(env, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        links = lambda: json.loads((self.board / 'links.json').read_text())['links'] if (self.board / 'links.json').exists() else {}
        asked = lambda: record.read_text().splitlines() if record.exists() else []
        pr = 'https://github.com/acme/orbit/pull/1640'
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('say', 'topic', '--from', 'fork', 'נפתח ' + pr, '--state', 'working', '--note', 'בונה', env=e(1))
        self.wait_for(lambda: links().get(pr, {}).get('state') == 'open', 'the pull request was never looked up')
        # merged on GitHub; the timer does not look, ever
        for minute in (4.1, 20, 90):
            self.run_cli('sweep', '--quiet', env=e(minute, GH_MERGED=pr))
        time.sleep(0.5)
        self.assertEqual((links()[pr]['state'], len(asked())), ('open', 1), 'the timer looked at a pull request')
        # another one: he opens its thread a little over a minute after it was looked at, and it is looked at at once
        pr2 = pr[:-4] + '1641'
        self.run_cli('say', 'topic', '--from', 'fork', 'ועוד ' + pr2, '--state', 'working', '--note', 'בונה', env=e(10))
        self.wait_for(lambda: links().get(pr2, {}).get('state') == 'open', 'the second was never looked up')
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(10.5))['queued'], 1)      # the first is old; the second, half a minute old, is fresh enough
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic', }, env=e(11.2, GH_MERGED=pr2))['queued'], 1)
        self.wait_for(lambda: links()[pr2]['state'] == 'merged', 'opening the thread did not look again')
        # a press on the first chip: the page asks a minute later for that pull request alone (it is merged by then)
        count = len(asked())
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic', 'url': pr}, env=e(92, GH_MERGED=pr))['queued'], 1)
        self.wait_for(lambda: links()[pr]['state'] == 'merged', 'the press on the chip did not look again')
        self.assertEqual(asked()[count:], [pr], 'more than the pressed chip was looked at')
        # only a pull request of that thread, and only a well-formed one
        for bad in (pr[:-4] + '9999', 'https://evil.example/pull/1', 5, ['x']):
            r = self.post({'op': 'link-meta', 'thread': 'topic', 'url': bad}, env=e(93))
            self.assertFalse(r.get('queued'), bad)

    def test_the_state_of_a_pull_request_is_kept_for_its_chip(self):
        import shlex
        gh = self.root / 'gh.py'
        gh.write_text("""import json, os, sys
url = sys.argv[1]
open(os.environ['GH_RECORD'], 'a').write(' '.join(sys.argv[1:]) + '\\n')
if url.endswith('/404') or os.environ.get('GH_DOWN'):
    sys.exit(1)
merged = os.environ.get('GH_MERGED') == url
print(json.dumps({'number': int(url.rsplit('/', 1)[1]), 'title': 'החזר חלקי\\u202e', 'state': 'MERGED' if merged else 'OPEN', 'isDraft': url.endswith('/7'),
                  'author': {'login': 'owner'}, 'baseRefName': 'main', 'headRefName': 'feat/refund', 'reviewDecision': 'APPROVED',
                  'statusCheckRollup': [{'status': 'COMPLETED', 'conclusion': 'SUCCESS'}, {'status': 'IN_PROGRESS', 'conclusion': ''}],
                  'updatedAt': '2026-11-16T10:00:00Z'}))
""")
        record = self.root / 'gh.log'
        env = dict(self.env, THREADS_GH_CMD=shlex.join([sys.executable, str(gh)]), GH_RECORD=str(record))
        e = lambda minutes, **more: dict(env, THREADS_NOW=str(self.T0 + minutes * 60), **more)
        links = lambda: json.loads((self.board / 'links.json').read_text())['links'] if (self.board / 'links.json').exists() else {}
        asked = lambda: record.read_text().splitlines() if record.exists() else []
        pr = 'https://github.com/acme/orbit/pull/'
        self.run_cli('new', 'topic', 'כותרת', '--state', 'working', '--note', 'בונה', env=e(0))
        # an agent names two pull requests (one with a tail, one twice): each is looked up once, soon after
        self.run_cli('say', 'topic', '--from', 'fork', f'נפתח {pr}1614/files ועוד {pr}7 וגם {pr}1614#issuecomment-5 וגם https://github.com/x/y/issues/3',
                     '--state', 'working', '--note', 'בונה', env=e(1))
        self.wait_for(lambda: len(links()) == 2, 'the pull requests were never looked up')
        self.assertEqual(sorted(line.split()[0] for line in asked()), [pr + '1614', pr + '7'])
        self.assertEqual(links()[pr + '1614'], {'kind': 'pr', 'repo': 'acme/orbit', 'number': 1614, 'title': 'החזר חלקי', 'state': 'open', 'author': 'owner',
                                                'base': 'main', 'head': 'feat/refund', 'ci': 'pending', 'review': 'approved', 'updated': 1794823200.0, 'checked': links()[pr + '1614']['checked']})
        self.assertEqual(links()[pr + '7']['state'], 'draft')
        self.assertIn('link-meta', json.loads((self.board / 'state.json').read_text())['ops'])
        state = (self.board / 'state.json').read_bytes()
        # he opens the thread: what is known and fresh is not asked about again
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(2)), {'ok': True, 'thread': 'topic', 'op': 'link-meta', 'queued': 0})
        # the timer never asks (m478: only when he is in the thread, or after a press on the chip)
        self.run_cli('sweep', '--quiet', env=e(30))
        time.sleep(0.5)
        self.assertEqual(len(asked()), 2)
        # he opens the thread again later: an open pull request is looked at again, and a change wakes the pages
        os.utime(self.board / '.pulse', (1, 1))
        self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(12, GH_MERGED=pr + '1614'))
        self.wait_for(lambda: links()[pr + '1614']['state'] == 'merged', 'a merge was never noticed')
        self.wait_for(lambda: len(asked()) == 4, 'the draft was not looked at again')
        self.assertGreater((self.board / '.pulse').stat().st_mtime, 1)
        self.assertEqual((self.board / 'state.json').read_bytes(), state)                              # the state itself is not rewritten for a chip
        # merged: never asked about again; the draft still is
        self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(30, GH_MERGED=pr + '1614'))
        self.wait_for(lambda: len(asked()) == 5, 'the draft was not looked at again')
        time.sleep(0.5)
        self.assertEqual([line.split()[0] for line in asked()].count(pr + '1614'), 2)
        # one that cannot be read is remembered as such; his own message names one too
        self.post({'op': 'reply', 'thread': 'topic', 'cid': 'c1', 'text': f'ומה עם {pr}404 ?'}, env=e(31))
        self.wait_for(lambda: pr + '404' in links(), 'his pull request was never looked up')
        self.assertEqual({k: v for k, v in links()[pr + '404'].items() if k != 'checked'}, {'kind': 'pr', 'state': '', 'error': True, 'tries': 1})
        count = len(asked())
        # he opens the thread ten minutes later: the draft is due again, and a first failure is tried again soon (not in six hours)
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(42))['queued'], 2)
        self.wait_for(lambda: len(asked()) == count + 2 and links()[pr + '404'].get('tries') == 2, 'the queued ones were not looked up')
        self.assertFalse(self.post({'op': 'link-meta', 'thread': 'ghost'}, ok=False, env=e(43))['ok'])
        # a lookup that fails never replaces what is known; after three failures in a row it is left alone for hours
        known = dict(links())
        self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(60, GH_DOWN='1'))                      # GitHub does not answer
        self.wait_for(lambda: links()[pr + '404'].get('tries') == 3, 'opening the thread did not ask')
        self.wait_for(lambda: len(asked()) == count + 4, 'the draft was not asked about')
        time.sleep(0.3)
        self.assertEqual((links()[pr + '7'], links()[pr + '1614']), (known[pr + '7'], known[pr + '1614']))
        self.post({'op': 'link-meta', 'thread': 'topic'}, env=e(70))                                   # the draft again (and it answers); the unreadable one not
        self.wait_for(lambda: links()[pr + '7']['checked'] > known[pr + '7']['checked'], 'what was known was not asked about again')
        time.sleep(0.3)
        self.assertEqual((len(asked()), links()[pr + '404']['tries']), (count + 5, 3))
        # a board that may not reach outside asks nobody and writes no file
        self.run_cli('say', 'topic', '--from', 'fork', f'עוד אחד {pr}99', '--state', 'working', '--note', 'בונה', env=self.at(1))
        self.assertEqual(self.post({'op': 'link-meta', 'thread': 'topic'}, env=self.at(1))['queued'], 0)
        time.sleep(0.5)
        self.assertNotIn(pr + '99', links())

    def test_message_ids_of_a_removed_thread_are_not_reused(self):
        self.new()
        self.assertEqual(self.run_cli('ask', 'topic', 'לפרוס לסטייג׳ינג?', '--options', 'כן,לא').stdout.strip(), 'm1')
        self.run_cli('rm', 'topic', '--yes')
        self.new()
        self.assertEqual(self.run_cli('ask', 'topic', 'לפרוס לפרודקשן?', '--options', 'כן,לא').stdout.strip(), 'm2')
        kept = {'op': 'reply', 'thread': 'topic', 'text': 'כן', 'cid': 'kept', 'q': 'm1'}             # an answer a page kept for the old thread
        self.assertFalse(self.post(kept, ok=False)['ok'])

    def test_resolve_and_page_actions(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('resolve', 'topic', '--note', 'מוזג', env=e(1))
        t = self.thread(env=e(1))
        self.assertEqual((t['state'], t['resolved'], t['note']), ('done', True, 'מוזג'))
        self.assertEqual((t['soon_at'], t['archive_at']), (self.T0 + 3600, self.T0 + 3*3600))   # resolved: 2 hours
        # "keep open" restarts the long clock
        self.assertTrue(self.post({'op': 'keep', 'thread': 'topic'}, env=e(2))['ok'])
        t = self.thread(env=e(2))
        self.assertFalse(t['resolved'])
        self.assertEqual(t['archive_at'], self.T0 + (2 + 24)*3600)
        # one tap closes; reopening returns to the same slot
        self.assertTrue(self.post({'op': 'close', 'thread': 'topic'}, env=e(3))['ok'])
        t = self.thread(env=e(3))
        self.assertEqual((t['status'], t['closed_by'], t['closed_ts']), ('closed', 'owner', self.T0 + 3*3600))
        self.assertTrue(self.post({'op': 'close', 'thread': 'topic'}, env=e(3.1))['ok'])          # second tap / second device
        self.assertEqual(self.thread(env=e(3.1))['closed_ts'], self.T0 + 3*3600)
        self.assertFalse(self.post({'op': 'keep', 'thread': 'topic'}, ok=False, env=e(3.2))['ok'])
        self.assertTrue(self.post({'op': 'reopen', 'thread': 'topic'}, env=e(4))['ok'])
        t = self.thread(env=e(4))
        self.assertEqual((t['status'], t['slot'], t['state'], t['resolved']), ('open', 1, 'done', False))
        # "read it, nothing to do" dismisses only an automatic "on you"
        self.run_cli('say', 'topic', '--from', 'fork', 'עדכון', env=e(5))
        self.assertTrue(self.post({'op': 'done', 'thread': 'topic', 'last': 'm1'}, env=e(5.1))['ok'])
        self.assertEqual(self.thread(env=e(5.1))['state'], 'done')
        self.run_cli('ask', 'topic', 'A או B?', '--options', 'A,B', env=e(6))
        self.assertFalse(self.post({'op': 'done', 'thread': 'topic', 'last': 'm2'}, ok=False, env=e(6.1))['ok'])
        for bad in ({'op': 'nope', 'thread': 'topic'}, {'op': 'close', 'thread': 'ghost'}, {'op': 'close'}, {'thread': 'topic'}, {'op': 'close', 'thread': ['topic']}):
            with self.subTest(bad=bad):
                self.assertFalse(self.post(bad, ok=False, env=e(7))['ok'])
        t = self.thread(env=e(7))
        self.assertEqual((t['status'], len(t['messages'])), ('open', 2))
        self.assertTrue(self.post({'op': 'sweep'}, env=e(7))['ok'])

    def test_reopen_restores_the_thread_as_it_was(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        self.run_cli('ask', 'topic', 'A או B?', '--options', 'A,B', env=e(1))
        self.post({'op': 'close', 'thread': 'topic'}, env=e(2))
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': 'A', 'cid': 'c1', 'q': 'm1'}, ok=False, env=e(2.5))['ok'])
        self.post({'op': 'reopen', 'thread': 'topic'}, env=e(3))           # the undo of a close
        t = self.thread(env=e(3))
        self.assertEqual((t['state'], t['note'], t['question']['options'], t['slot']), ('on-owner', 'A או B?', ['A', 'B'], 1))
        # an archived thread comes back with its outcome line and a fresh clock
        self.run_cli('resolve', 'topic', '--note', 'נבחר A', env=e(4))
        self.run_cli('list', env=e(7))
        self.assertEqual(self.thread(env=e(7))['closed_by'], 'auto')
        self.run_cli('reopen', 'topic', env=e(8))
        t = self.thread(env=e(8))
        self.assertEqual((t['state'], t['note'], t['resolved'], t['archive_at']), ('done', 'נבחר A', False, self.T0 + (8 + 24)*3600))

    def test_idle_threads_close_themselves(self):
        e = self.at
        for tid in ('quiet', 'mine', 'busy', 'asked'):
            self.run_cli('new', tid, 'T ' + tid, env=e(0))
        self.run_cli('say', 'quiet', '--from', 'fork', 'סיכום', '--state', 'done', '--note', 'נגמר', env=e(0))
        self.run_cli('state', 'busy', 'working', '--note', 'בונה', env=e(0))
        self.run_cli('state', 'mine', 'on-owner', '--note', 'להחליט', env=e(0))
        self.run_cli('say', 'asked', '--from', 'owner', 'רגע', env=e(0))        # a reply nobody picked up yet
        self.run_cli('state', 'asked', 'done', env=e(0))
        t = self.thread('quiet', env=e(0))
        self.assertEqual((t['soon_at'], t['archive_at']), (self.T0 + 12*3600, self.T0 + 24*3600))
        for tid in ('busy', 'mine', 'asked'):
            self.assertIsNone(self.thread(tid, env=e(0))['archive_at'], tid)
        self.assertEqual(self.thread('quiet', env=e(23.9))['status'], 'open')
        pulse = self.board / '.pulse'
        os.utime(pulse, (1, 1))
        # any command after the deadline archives it, and nothing is deleted
        rows = {t['id']: t for t in json.loads(self.run_cli('list', '--json', env=e(25)).stdout)}
        self.assertEqual((rows['quiet']['status'], rows['quiet']['closed_by'], rows['quiet']['closed_ts']), ('closed', 'auto', self.T0 + 25*3600))
        self.assertEqual((rows['quiet']['note'], len(rows['quiet']['messages'])), ('נגמר', 1))
        self.assertGreater(pulse.stat().st_mtime, 1)                             # open pages refresh
        # whatever waits on someone never closes by itself
        rows = {t['id']: t['status'] for t in json.loads(self.run_cli('list', '--json', env=e(5000)).stdout)}
        self.assertEqual(rows, {'quiet': 'closed', 'mine': 'open', 'busy': 'open', 'asked': 'open'})
        # activity restarts the clock
        self.run_cli('reopen', 'quiet', env=e(5000))
        self.run_cli('say', 'quiet', '--from', 'fork', 'עוד', '--state', 'done', env=e(5010))
        self.assertEqual(self.thread('quiet', env=e(5010))['archive_at'], self.T0 + (5010 + 24)*3600)
        # the numbers are data, not code
        self.run_cli('policy', '--idle-hours', '1', '--grace-hours', '0.5', env=e(5010))
        self.assertEqual(self.thread('quiet', env=e(5010))['archive_at'], self.T0 + 5010*3600 + 5400)
        self.assertEqual(json.loads(self.run_cli('policy', env=e(5010)).stdout)['idle_hours'], 1)
        self.run_cli('policy', '--idle-hours', '-1', ok=False, env=e(5010))
        self.assertIn('quiet', self.run_cli('sweep', env=e(5012)).stdout)
        self.assertEqual(self.thread('quiet', env=e(5012))['status'], 'closed')
        # a read that changes nothing does not wake the pages
        os.utime(pulse, (1, 1))
        self.run_cli('list', env=e(5012))
        self.run_cli('pending', env=e(5012))
        self.assertEqual(pulse.stat().st_mtime, 1)

    def test_migrates_v1_state_and_keeps_a_backup(self):
        v1 = {'version': 1, 'threads': {
            'old': {'id': 'old', 'title': 'ישן', 'context': 'רקע', 'status': 'closed', 'created': 90.0, 'updated': 95.0, 'next': 1, 'messages': []},
            'b': {'id': 'b', 'title': 'B', 'context': '', 'status': 'open', 'created': 200.0, 'updated': 260.0, 'next': 3, 'messages': [
                {'id': 'm1', 'from': 'owner', 'text': 'שאלה', 'ts': 250.0, 'status': 'acked', 'acked_ts': 251.0},
                {'id': 'm2', 'from': 'fork', 'text': '**תשובה** ארוכה', 'ts': 260.0}]},
            'a': {'id': 'a', 'title': 'A', 'context': '', 'status': 'open', 'created': 100.0, 'updated': 150.0, 'next': 2, 'messages': [
                {'id': 'm1', 'from': 'owner', 'text': 'תעשה', 'ts': 150.0, 'status': 'pending', 'cid': 'x'}]},
            'c': {'id': 'c', 'title': 'C', 'context': '', 'status': 'open', 'created': 300.0, 'updated': 300.0, 'next': 1, 'messages': []}}}
        self.board.mkdir(parents=True)
        raw = json.dumps(v1, ensure_ascii=False, indent=2) + '\n'
        (self.board / 'state.json').write_text(raw)
        rows = {t['id']: t for t in self.js('list', '--json')}
        self.assertEqual(json.loads((self.board / 'state.json').read_text())['version'], 3)
        backups = list((self.root / '.threads-config/threads/backups').glob('state.json.v1-*'))    # private: never in the served folder
        self.assertEqual(len(backups), 1)
        self.assertEqual(list(self.board.glob('state.json.*')), [])
        self.assertEqual(backups[0].read_text(), raw)
        self.assertEqual({k: rows[k]['slot'] for k in 'abc'}, {'a': 1, 'b': 2, 'c': 3})   # by creation time
        self.assertIsNone(rows['old']['slot'])
        self.assertEqual({k: rows[k]['status'] for k in rows}, {'a': 'open', 'b': 'open', 'c': 'open', 'old': 'closed'})
        self.assertEqual((rows['a']['state'], rows['b']['state'], rows['c']['state']), ('working', 'on-owner', 'on-owner'))
        self.assertEqual((rows['b']['note'], rows['b']['auto']), ('לקרוא: תשובה ארוכה', True))
        for tid in 'abc':
            self.assertEqual(rows[tid]['messages'], v1['threads'][tid]['messages'])       # history untouched
            self.assertIsNone(rows[tid]['archive_at'])                                    # migration closes nothing
        self.assertEqual(len(self.js('pending')), 1)
        self.run_cli('say', 'c', '--from', 'tower', 'x')
        self.assertEqual(len(list(backups[0].parent.glob('state.json.v1-*'))), 1)

    def test_pinned_header_fields(self):
        self.run_cli('new', 'topic', 'כותרת', '--summary', 'על מה זה', '--note', 'לבחור תאריך', '--link', 'PR #7=https://example.com/pr/7')
        t = self.thread()
        self.assertEqual((t['summary'], t['note'], t['auto'], t['state']), ('על מה זה', 'לבחור תאריך', False, 'on-owner'))
        self.assertEqual(t['links'], [{'label': 'PR #7', 'url': 'https://example.com/pr/7'}])
        self.run_cli('link', 'topic', 'לוח', '/acme/sim-lab-spot/board.html')
        self.run_cli('link', 'topic', 'runbook', '~/PG/snap-linux/lead/runbook.md')
        self.run_cli('link', 'topic', 'PR #7', 'https://example.com/pr/8')                # same label replaces
        for bad in ('javascript:alert(1)', 'data:text/html,x', '//evil.example/x', 'ftp://x/y', ''):
            with self.subTest(bad=bad):
                self.run_cli('link', 'topic', 'רע', bad, ok=False)
        t = self.thread()
        self.assertEqual([link['label'] for link in t['links']], ['PR #7', 'לוח', 'runbook'])
        self.assertEqual(t['links'][0]['url'], 'https://example.com/pr/8')
        self.run_cli('link', 'topic', 'לוח', '--rm')
        self.run_cli('link', 'topic', 'אין', '--rm', ok=False)
        self.assertEqual(len(self.thread()['links']), 2)
        self.run_cli('set', 'topic', '--summary', 'חדש', '--title', 'כותרת 2')
        self.run_cli('set', 'topic', ok=False)
        t = self.thread()
        self.assertEqual((t['title'], t['summary']), ('כותרת 2', 'חדש'))
        human = self.run_cli('show', 'topic').stdout
        for part in ('לבחור תאריך', 'PR #7', 'חדש'):
            self.assertIn(part, human)
        self.run_cli('new', 'w', 'עובד', '--state', 'working', '--note', 'בונה', '--by', 'builder')
        t = self.thread('w')
        self.assertEqual((t['state'], t['state_by'], t['slot']), ('working', 'builder', 2))
        self.run_cli('new', 'bad', 'x', '--state', 'on-owner', '--note', 'x'*201, ok=False)
        self.run_cli('show', 'bad', ok=False)

    def test_pending_rows_keep_v1_keys(self):
        self.new()
        self.run_cli('say', 'topic', '--from', 'owner', 'first')
        row = self.js('pending')[0]
        self.assertLessEqual({'thread', 'title', 'context', 'msg_id', 'text', 'ts', 'history'}, set(row))
        self.assertEqual((row['slot'], row['state']), (1, 'working'))


HEBREW = re.compile('[\u0590-\u05ff]')


class Languages(unittest.TestCase):
    """The public code speaks English; an installation names its own language (config.json "lang") and gets its
    table (locales/<lang>.json and its parts). The owner's installation is Hebrew, as the other tests describe it."""
    setUp, run_cli, new, post = ThreadsTests.setUp, ThreadsTests.run_cli, ThreadsTests.new, ThreadsTests.post

    def english(self):
        (self.root / '.threads-config/threads/config.json').unlink()

    def inside(self, code, lang=None):
        """Run `code` with threads imported, on this test's board (with this language, or none configured)."""
        config = self.root / '.threads-config/threads/config.json'
        if lang is None:
            config.unlink(missing_ok=True)
        else:
            config.write_text(json.dumps({'lang': lang}), encoding='utf-8')
        r = subprocess.run([sys.executable, '-c', f'import json, sys\nsys.path.insert(0, {str(ROOT)!r})\nimport threads\n' + code],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_without_a_language_every_refusal_is_english(self):
        """No config: whatever the CLI refuses, it says so in English (a sample of many refusals, and the page's)."""
        self.english()
        self.run_cli('new', 'topic', 'Topic', '--context', 'Background')
        self.run_cli('new', 'shut', 'Shut')
        self.run_cli('close', 'shut')
        self.run_cli('task', 'add', 'topic', 'something to do')
        big = self.root / 'big.txt'
        with big.open('wb') as f:
            f.truncate(20_000_001)          # sparse: past the snippet limit without using the disk
        bad_image = self.root / 'bad.png'
        bad_image.write_bytes(b'\x89PNG\r\n\x1a\nnot really')
        refusals = [('say', 'topic', '--from', 'fork', ''), ('say', 'topic', '--from', 'fork', '   '),
                    ('say', 'nope', '--from', 'fork', 'hi'), ('state', 'topic', 'on-owner'),
                    ('task', 'set', 'topic', '9', 'done'), ('task', 'add', 'topic', ' '), ('say', 'topic', '--from', 'fork', 'x', '--snippet', str(big)),
                    ('say', 'topic', '--from', 'fork', 'x', '--image', str(bad_image)), ('snooze', 'topic', '--until', 'someday'),
                    ('ask', 'topic', 'which?', '--options', 'one'), ('ask', 'topic', 'which?', '--options', 'B) two,A) one'),
                    ('ask', 'topic', '', '--options', 'a,b'), ('new', 'Bad Id', 'T'), ('new', 'topic', 'again'),
                    ('merge', 'topic', '--into', 'topic'), ('merge', 'topic', '--into', 'nope'), ('merge', 'topic', '--into', 'shut'), ('show', 'nope'),
                    ('resolve', 'topic', '--by', 'fork'), ('say', 'topic', '--from', 'owner', 'x', '--state', 'working'),
                    ('link', 'topic', '', 'https://example.com'), ('link', 'topic', 'x', 'javascript:alert(1)'),
                    ('notify', '--quiet', 'later'), ('space', 'add', 'BAD', 'name'), ('rename', 'topic', ' '),
                    ('update', 'topic', 'm99', '--from', 'fork', 'x'), ('react', 'topic', 'm99', '✅'), ('task', 'archive', 'topic')]
        for args in refusals:
            with self.subTest(args=args):
                r = self.run_cli(*args, ok=False)
                self.assertNotIn('Traceback', r.stderr)
                self.assertTrue(r.stderr.strip(), 'a refusal says why')
                self.assertIsNone(HEBREW.search(r.stdout + r.stderr), r.stderr)
        for payload in ({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c1'}, {'op': 'reply', 'thread': 'shut', 'text': 'x', 'cid': 'c2'},
                        {'op': 'reply', 'thread': 'nope', 'text': 'x', 'cid': 'c3'}, {'op': 'nonsense'}, {'op': 'task', 'thread': 'topic', 'n': 7, 'status': 'done'},
                        {'op': 'rename', 'thread': 'topic', 'title': ''}, {'op': 'quiet', 'from': 'x', 'to': 'y'}, {'op': 'new', 'title': '', 'text': ''}):
            with self.subTest(payload=payload):
                got = self.post(payload, ok=False)
                self.assertFalse(got['ok'])
                self.assertIsNone(HEBREW.search(got['error']), got['error'])
        # and what the server writes for the page to show: a state note, a closed question, a merge
        self.run_cli('merge', 'topic', '--into', 'other', ok=False)
        self.run_cli('new', 'other', 'Other')
        self.run_cli('merge', 'topic', '--into', 'other')
        shown = self.run_cli('show', 'other').stdout + self.run_cli('show', 'topic').stdout
        self.assertIsNone(HEBREW.search(shown), shown)

    def test_tr_fills_its_values_in_the_installations_language_and_falls_back_to_english(self):
        code = ("print(json.dumps([threads.tr('Thread {id} is already in space {space}', id='a', space='b'), threads.tr('Thread not found'),"
                " threads.tr('Nothing in any table: {n} {{x}}', n=3), threads.tr('Plain text, no values'), threads.owner_name()]))")
        self.assertEqual(self.inside(code, 'he'), ['השרשור a כבר במרחב b', 'השרשור לא נמצא', 'Nothing in any table: 3 {x}', 'Plain text, no values', 'הבעלים'])
        self.assertEqual(self.inside(code), ['Thread a is already in space b', 'Thread not found', 'Nothing in any table: 3 {x}', 'Plain text, no values', 'the owner'])
        self.assertEqual(self.inside(code, 'xx'), self.inside(code))          # a language with no table: English

    def test_the_cli_table_answers_every_message_and_keeps_its_placeholders(self):
        """Every tr('…') of threads.py and live_hook.py has its line in locales/he.cli.json, with the same {names}."""
        import ast
        import string
        table = json.loads((ROOT / 'locales/he.cli.json').read_text(encoding='utf-8'))
        said = set()
        for name in ('threads.py', 'live_hook.py'):
            for node in ast.walk(ast.parse((ROOT / name).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'tr' and node.args and isinstance(node.args[0], ast.Constant):
                    said.add(node.args[0].value)
        said.discard('the owner')       # tr(OWNER_NAME)
        self.assertEqual(sorted(said - set(table)), [])
        names = lambda text: sorted(n for _, n, _, _ in string.Formatter().parse(text) if n)
        for en, he in table.items():
            with self.subTest(en=en):
                self.assertIsNone(HEBREW.search(en))
                self.assertNotIn('\u2014', en)
                self.assertNotIn('\u2013', en)
                self.assertEqual(names(en), names(he))

    def test_an_installed_page_says_its_language(self):
        """English: lang="en" dir="ltr", no table, the owner as the page names him ("Me"). Hebrew: lang="he" dir="rtl", the table,
        the owner is "אני"; the worker and the manifest speak it too."""
        self.english()
        self.run_cli('install')
        for page in ('suda.html',):
            text = (self.board / page).read_text(encoding='utf-8')
            self.assertIn('<html lang="en" dir="ltr">', text, page)
            self.assertIn("var LANG='en',L10N={};", text, page)
            self.assertEqual(re.findall(r"const OWNER_NAME=[^;]*;", text), re.findall(r"const OWNER_NAME=[^;]*;", (ROOT / page).read_text(encoding='utf-8')))
        self.assertEqual((self.board / 'sw.js').read_text(encoding='utf-8'), (ROOT / 'sw.js').read_text(encoding='utf-8'))
        self.assertEqual((self.board / 'manifest.json').read_text(encoding='utf-8'), (ROOT / 'manifest.json').read_text(encoding='utf-8'))
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')
        self.run_cli('install')
        table = {k: v for k, v in json.loads((ROOT / 'locales/he.json').read_text(encoding='utf-8')).items() if not k.startswith('_')}
        for page in ('suda.html',):
            text = (self.board / page).read_text(encoding='utf-8')
            self.assertIn('<html lang="he" dir="rtl">', text, page)
            self.assertNotIn("var LANG='en',L10N={};", text, page)
            installed = json.loads(re.search(r'var LANG="he",L10N=(\{.*?\});\n', text)[1])
            self.assertLessEqual(table.items(), installed.items())
            self.assertNotIn('Thread not found', installed)          # the CLI's own messages reach a page translated
            self.assertIn("const OWNER_NAME='אני';", text, page)
        worker = (self.board / 'sw.js').read_text(encoding='utf-8')
        self.assertIn('var LANG="he",DIR="rtl",L10N={"There is an update in the threads": "יש עדכון בשרשורים", "Your turn: {title}": "עליך: {title}"};', worker)
        manifest = json.loads((self.board / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['lang'], manifest['dir'], manifest['description']), ('he', 'rtl', 'השרשורים שלי: מה עליך, מה בעבודה, מה הושלם'))



# ── a number on every change, and the changes beside the summary (sse153) ─────

def apply_entry(summary, entry):
    """What a page does with one entry of changes.json, in Python: the reference the page's catchUp is held to."""
    out = dict(summary)
    out['threads'] = dict(summary['threads'])
    out.update(entry.get('top', {}))
    for key in entry.get('drop', []):
        out.pop(key, None)
    for tid, row in entry.get('threads', {}).items():
        if row is None:
            out['threads'].pop(tid, None)
        else:
            out['threads'][tid] = row
    for tid, edit in entry.get('edit', {}).items():
        row = dict(out['threads'][tid])
        row.update(edit.get('set', {}))
        for key in edit.get('drop', []):
            row.pop(key, None)
        for key, patch in edit.get('list', {}).items():
            before = row[key]
            items = (list(before) + [None] * patch['n'])[:patch['n']]
            for i, j in patch.get('from', []):
                items[i] = before[j]
            for i, value in patch.get('at', []):
                items[i] = value
            row[key] = items
        out['threads'][tid] = row
    out['seq'] = entry['seq']
    return out


def chain(entries):
    """Each entry starts from the number the one before it reached."""
    return all(b['from'] == a['seq'] and b['seq'] > a['seq'] for a, b in zip(entries, entries[1:]))


class SideWriteTests(unittest.TestCase):
    """The files beside the board are asked "changed since?" by their whole-second time (suda-fixes 16). A file's
    time must never be earlier than the moment its new content became visible: a writer that stamps it at the
    flush and renames it seconds later (a slow fsync on a busy disk) would hide the change behind a 304."""
    setUp = ThreadsTests.setUp

    STALL = r"""
import os, sys, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
real = os.fsync
def slow(fd):
    time.sleep(1.6)
    return real(fd)
os.fsync = slow
import importlib
mod = importlib.import_module(sys.argv[2])
path = sys.argv[3]
while time.time() % 1 > 0.1:
    time.sleep(0.005)
start = time.time()
getattr(mod, sys.argv[4])(path, '{"v":"new"}\n')
print(int(start), os.stat(path).st_mtime, time.time())
"""

    def stalled(self, module, writer):
        path = self.root / 'side-file.json'
        r = subprocess.run([sys.executable, '-c', self.STALL, str(ROOT), module, str(path), writer], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        start, mtime, done = r.stdout.split()
        return int(start), float(mtime), float(done)

    def test_threads_stamps_a_side_file_when_its_content_is_there(self):
        start, mtime, done = self.stalled('threads', 'side_write')
        self.assertGreater(int(mtime), start, 'the file kept the second of its flush, %.1f s before its rename' % (done - start))

    def test_live_hook_stamps_live_json_when_its_content_is_there(self):
        # (live_hook writes without fsync; its stall would be the write itself: the time is taken just before the rename)
        import importlib.util, inspect
        spec = importlib.util.spec_from_file_location('live_hook', ROOT / 'live_hook.py')
        live_hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_hook)
        src = inspect.getsource(live_hook.write_atomic)
        self.assertLess(src.index('os.utime('), src.index('os.replace('), src)

    def test_every_writer_of_a_side_file_in_threads_goes_through_side_write(self):
        text = (ROOT / 'threads.py').read_text(encoding='utf-8')
        for name in ('LINKS', 'PLACES', 'DRAFTS'):
            self.assertNotIn('bl.atomic_write_text(%s,' % name, text)
            self.assertIn('side_write(%s,' % name, text)


class SeqTests(unittest.TestCase):
    """Every change to the board has a number; changes.json holds the last ones, so a page that is a few behind
    reads a few small entries instead of the whole summary (the owner's guarantees 1, 2 and 5, sse153)."""
    setUp, run_cli, js, new = ThreadsTests.setUp, ThreadsTests.run_cli, ThreadsTests.js, ThreadsTests.new

    def read(self, name):
        return json.loads((self.board / name).read_text(encoding='utf-8'))

    def seq(self):
        return self.read('state.json')['seq']

    def say(self, text, tid='topic', **kw):
        self.run_cli('say', tid, '--from', 'fork', text, '--state', 'working', '--note', 'עובד', **kw)

    def test_every_save_that_changes_the_board_has_the_next_number_everywhere(self):
        self.new()
        first = self.seq()
        self.assertIs(type(first), int)
        self.assertGreater(first, 0)
        before = first
        for i in range(3):
            self.say('הודעה %d' % i)
            n = self.seq()
            # a higher number, never below the clock (a board put back from a backup never gives one again)
            self.assertGreater(n, before)
            self.assertGreaterEqual(n, int(time.time() * 1000) - 60_000)
            # the summary, changes.json and the pulse all say the same number
            self.assertEqual(self.read('summary.json')['seq'], n)
            self.assertEqual(self.read('changes.json')['seq'], n)
            self.assertEqual((self.board / '.pulse').read_text(), str(n))
            last = self.read('changes.json')['entries'][-1]
            self.assertEqual((last['from'], last['seq']), (before, n))
            # named by the number it starts from: what a page at that number lacks, to the board's number
            self.assertEqual(self.read('changes/%d.json' % before), {'seq': n, 'entries': [last]})
            before = n
        # a command that only reads changes nothing and numbers nothing
        self.run_cli('list')
        self.run_cli('show', 'topic')
        self.assertEqual(self.seq(), before)

    def test_the_number_never_goes_back_when_a_file_beside_the_state_knows_a_higher_one(self):
        """A state.json put back from a backup, or a summary rewritten: the next number is above every number a page
        may already hold, so a page never takes a new board for one it has seen."""
        self.new()
        self.say('אחת')
        high = self.seq()
        state = self.read('state.json')
        state['seq'] = 3
        (self.board / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
        self.say('שתיים')
        self.assertGreater(self.seq(), high)
        # a board with no number anywhere starts from the clock, never from a small number a page may hold
        state = self.read('state.json')
        del state['seq']
        (self.board / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
        for name in ('summary.json', 'changes.json', '.pulse'):
            (self.board / name).unlink()
        before = int(time.time() * 1000)
        self.say('שלוש')
        self.assertGreaterEqual(self.seq(), before)

    def test_entries_reproduce_the_summary_exactly(self):
        """Every entry applied to the summary before it gives the summary after it: new threads, messages, tasks,
        a closed and a removed thread, a top-level change (policy), and a thread whose rows only partly changed."""
        self.new()
        self.new('other')
        snaps = {self.seq(): self.read('summary.json')}
        steps = [('say', 'topic', '--from', 'fork', 'שלום **עולם**', '--state', 'working', '--note', 'עובד'),
                 ('task', 'add', 'topic', 'משימה ראשונה', '--owner', 'fork'),
                 ('task', 'set', 'topic', '1', 'done', '--note', 'בוצע'),
                 ('ask', 'other', 'כן או לא?', '--options', 'כן,לא'),
                 ('react', 'topic', 'm1', '✅'),
                 ('policy', '--idle-hours', '5'),
                 ('close', 'other'),
                 ('new', 'third', 'שלישי', '--context', 'רקע'),
                 ('rm', 'other', '--yes')]
        for args in steps:
            self.run_cli(*args)
            snaps[self.seq()] = self.read('summary.json')
        changes = self.read('changes.json')
        self.assertTrue(chain(changes['entries']), changes['entries'])
        self.assertEqual(changes['seq'], max(snaps))
        for start in sorted(snaps):
            got = snaps[start]
            for entry in changes['entries']:
                if entry['seq'] > start:
                    got = apply_entry(got, entry)
                    self.assertEqual(got, snaps[entry['seq']], 'entry %d' % entry['seq'])
        # a removed thread is null; an existing thread that changed a little is an edit, not its whole row
        removed = next(e for e in changes['entries'] if 'other' in e.get('threads', {}) and e['threads']['other'] is None)
        self.assertEqual(removed['seq'], changes['seq'])
        said = next(e for e in changes['entries'] if e['from'] == min(snaps))
        self.assertIn('topic', said['edit'])
        self.assertNotIn('topic', said.get('threads', {}))
        policy = next(e for e in changes['entries'] if 'policy' in e.get('top', {}))
        self.assertEqual(policy['top']['policy'], snaps[policy['seq']]['policy'])

    def test_a_say_carries_only_the_new_message_not_the_whole_tail(self):
        """The summary carries an open thread's last 4 messages whole; a new one moves them up. The entry names the
        three that moved by where they were, and carries only the new message (and its stamp)."""
        self.new()
        for i in range(6):
            self.say('הודעה ארוכה מספר %d ' % i + 'מילה ' * 400)
        entry = self.read('changes.json')['entries'][-1]
        patch = entry['edit']['topic']['list']
        self.assertEqual(patch['messages']['from'], [[0, 1], [1, 2], [2, 3]])
        self.assertEqual([i for i, _ in patch['messages']['at']], [3])
        self.assertEqual(patch['stamps']['n'], 6)
        self.assertEqual([i for i, _ in patch['stamps']['at']], [5])
        self.assertLess(len((self.board / ('changes/%d.json' % entry['from'])).read_bytes()), 6000)

    def test_the_pages_own_catch_up_reproduces_the_summary(self):
        """The same entries, applied by the page's own code (catchUp in suda.html, under node)."""
        import shutil
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        self.new()
        before = self.read('summary.json')
        for args in [('say', 'topic', '--from', 'fork', 'שלום', '--state', 'working', '--note', 'עובד'),
                     ('task', 'add', 'topic', 'משימה', '--owner', 'fork'), ('new', 'b', 'בי', '--context', 'x'),
                     ('policy', '--idle-hours', '7'), ('rm', 'b', '--yes')]:
            self.run_cli(*args)
        after, changes = self.read('summary.json'), self.read('changes.json')
        page = (ROOT / 'suda.html').read_text(encoding='utf-8')
        pure = page.split('// <pure>')[1].split('// </pure>')[0]
        script = "'use strict';\n" + pure + '\nconst [b,c]=JSON.parse(require("fs").readFileSync(0,"utf8"));process.stdout.write(JSON.stringify(catchUp(b,c)));'
        r = subprocess.run([node, '-e', script], input=json.dumps([before, changes], ensure_ascii=False), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), after)

    def test_changes_are_bounded_by_bytes(self):
        self.new()
        big = 'א' * 40_000
        for i in range(8):
            self.say(big + str(i))
        raw = (self.board / 'changes.json').read_bytes()
        self.assertLessEqual(len(raw), 256 * 1024)
        changes = json.loads(raw)
        self.assertEqual(changes['seq'], self.seq())
        self.assertGreaterEqual(len(changes['entries']), 1)
        self.assertEqual(changes['entries'][-1]['seq'], self.seq())
        self.assertTrue(chain(changes['entries']))
        # the files of single entries are kept for the same window only
        kept = sorted(int(p.stem) for p in (self.board / 'changes').glob('*.json'))
        self.assertEqual(kept, [e['from'] for e in changes['entries']])

    def test_changes_are_bounded_by_count(self):
        self.new()
        self.ingest_many(205)
        changes = self.read('changes.json')
        self.assertEqual(len(changes['entries']), 200)
        self.assertEqual(changes['entries'][-1]['seq'], self.seq())
        self.assertEqual(len(list((self.board / 'changes').glob('*.json'))), 200)

    def ingest_many(self, n):
        for i in range(n):
            self.run_cli('state', 'topic', 'working', '--note', 'צעד %d' % i)

    def test_changes_are_written_atomically_before_the_summary_and_the_pulse(self):
        self.env['THREADS_STORE'] = 'file'      # a guarantee of the file store (THREADS_STORE=file); the SQLite store never reads summary.json back (tests/test_store.py)
        # The board library threads.py will use: THREADS_BOARDLIB_DIR, else the installed board skill, else the one a
        # release ships beside the app (suda/suda_boardlib.py). None (a fresh clone, CI): nothing to spy on.
        found = [Path(d) / 'boardlib.py' for d in (self.env.get('THREADS_BOARDLIB_DIR'), str(Path.home() / '.claude/skills/html-interview-board')) if d]
        found = [p for p in found if p.is_file()] + [p for p in (ROOT / 'suda_boardlib.py',) if p.is_file()]
        if not found:
            self.skipTest('no board library: set THREADS_BOARDLIB_DIR, install the board skill, or ship suda/suda_boardlib.py')
        self.new()
        log = self.root / 'writes.log'
        wrapper = self.root / 'spy.py'
        wrapper.write_text(
            "import importlib, os, runpy, sys\n"
            "sys.path.insert(0, %r)\n"
            "lib = importlib.import_module(%r)\n"
            "sys.modules.setdefault('boardlib', lib)\n"       # (a release imports it under its own name; this is the one)
            "real = lib.atomic_write_text\n"
            "def spy(path, text):\n"
            "    with open(os.environ['SPY_LOG'], 'a') as f: f.write(os.path.basename(str(path)) + '\\n')\n"
            "    real(path, text)\n"
            "lib.atomic_write_text = spy\n"
            "sys.argv = [sys.argv[1]] + sys.argv[2:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n" % (str(found[0].parent), found[0].stem))
        r = subprocess.run([sys.executable, str(wrapper), str(CLI), 'say', 'topic', '--from', 'fork', 'שלום', '--state', 'working', '--note', 'x'],
                           env=dict(self.env, SPY_LOG=str(log)), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        names = log.read_text().split()
        n = self.read('changes.json')['entries'][-1]['from']
        for name in ('changes.json', '%d.json' % n, 'summary.json', '.pulse', 'state.json'):
            self.assertIn(name, names)
        self.assertLess(names.index('%d.json' % n), names.index('changes.json'))
        self.assertLess(names.index('changes.json'), names.index('summary.json'))
        self.assertLess(names.index('summary.json'), names.index('.pulse'))
        self.assertLess(names.index('state.json'), names.index('changes.json'))
        self.assertEqual([p.name for p in self.board.iterdir() if p.name.endswith('.tmp')], [])

    def test_a_summary_that_is_gone_starts_the_changes_again(self):
        """Without the summary before it there is nothing to describe a change against: the entries start again, and
        a page that is behind reads the whole summary."""
        self.env['THREADS_STORE'] = 'file'      # a guarantee of the file store (THREADS_STORE=file); the SQLite store never reads summary.json back (tests/test_store.py)
        self.new()
        self.say('אחת')
        (self.board / 'summary.json').unlink()
        self.say('שתיים')
        changes = self.read('changes.json')
        self.assertEqual((changes['seq'], changes['entries']), (self.seq(), []))
        self.say('שלוש')
        changes = self.read('changes.json')
        self.assertEqual([e['seq'] for e in changes['entries']], [self.seq()])

    def test_a_summary_rewritten_by_another_writer_starts_the_changes_again(self):
        """A writer that does not number (an older threads.py, a hand edit) rewrites the summary under the same number.
        A page at that number has the content from before it: an entry that describes the next change against the
        rewritten summary would leave that page half updated. changes.json carries a mark of the summary it ends at;
        when the summary on disk is not that one, the entries start again and a page behind reads the whole summary."""
        self.env['THREADS_STORE'] = 'file'      # a guarantee of the file store (THREADS_STORE=file); the SQLite store never reads summary.json back (tests/test_store.py)
        self.new()
        self.say('אחת')
        summary = self.read('summary.json')
        summary['threads']['topic']['title'] = 'נכתב בלי מספר'
        (self.board / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False))
        self.say('שתיים')
        self.assertEqual(self.read('changes.json')['entries'], [])
        self.say('שלוש')
        self.assertEqual([e['seq'] for e in self.read('changes.json')['entries']], [self.seq()])

    def test_a_page_a_few_changes_behind_reads_all_it_lacks_in_one_file(self):
        """On a slow link each request costs a round trip and a wait for a connection: a page several changes behind
        must not walk them one file at a time. changes/<n>.json holds every change from n to the board's number, for
        the last CHANGES_FAN numbers; older files keep what they held (a page that far behind walks, or reads
        changes.json)."""
        self.new()
        numbers = [self.seq()]
        for i in range(9):
            self.say('הודעה %d' % i)
            numbers.append(self.seq())
        changes = self.read('changes.json')
        by_seq = {e['seq']: e for e in changes['entries']}
        for k, n in enumerate(numbers[:-1]):
            got = self.read('changes/%d.json' % n)
            if len(numbers) - 1 - k <= 6:
                self.assertEqual(got, {'seq': numbers[-1], 'entries': [by_seq[m] for m in numbers[k + 1:]]}, k)
            else:
                self.assertEqual(got['entries'][0], by_seq[numbers[k + 1]])
                self.assertTrue(chain(got['entries']))
                self.assertEqual(got['seq'], got['entries'][-1]['seq'])

    def test_the_summary_starts_with_its_number_and_the_mark_of_its_content(self):
        """A page checks the first bytes of summary.json (a Range request) to know that the summary under its number
        is still the one it holds. The mark is of the content without the number and the mark."""
        self.env['THREADS_STORE'] = 'file'      # a guarantee of the file store (THREADS_STORE=file); the SQLite store never reads summary.json back (tests/test_store.py)
        self.new()
        self.say('אחת')
        text = (self.board / 'summary.json').read_text(encoding='utf-8')
        summary = json.loads(text)
        content = {k: v for k, v in summary.items() if k not in ('seq', 'mark')}
        mark = '%08x' % zlib.crc32(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        self.assertTrue(text.startswith('{"seq":%d,"mark":"%s",' % (self.seq(), mark)), text[:80])
        self.assertEqual(self.read('changes.json')['mark'], mark)
        # the state carries no mark: a writer that copies the state into a summary can never give it one
        self.assertNotIn('mark', self.read('state.json'))

    def test_a_summary_rewritten_without_its_mark_is_never_kept_under_its_number(self):
        """An unnumbered writer (an older threads.py) rewrote the summary and kept the number. The next numbered save
        gives a new number even when it changes nothing more, so a page that holds the number from before reads."""
        self.env['THREADS_STORE'] = 'file'      # a guarantee of the file store (THREADS_STORE=file); the SQLite store never reads summary.json back (tests/test_store.py)
        self.new()
        self.say('אחת')
        held = self.seq()
        summary = self.read('summary.json')
        del summary['mark']
        summary['threads']['topic']['title'] = 'נכתב בלי מספר'
        (self.board / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False))
        self.run_cli('show', 'topic')
        self.run_cli('policy', '--idle-hours', str(self.read('state.json')['policy']['idle_hours']))     # a save that changes nothing
        self.assertGreater(self.seq(), held)
        self.assertEqual(self.read('changes.json')['entries'], [])
        self.assertNotEqual(self.read('summary.json')['threads']['topic']['title'], 'נכתב בלי מספר')

    def test_the_number_strictly_increases_under_concurrent_writers(self):
        self.new()
        start = self.seq()
        snaps = {}

        def one(i):
            return self.run_cli('say', 'topic', '--from', 'fork', 'מקביל %d' % i, '--state', 'working', '--note', 'x')
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(one, range(24)))
        changes = self.read('changes.json')
        self.assertEqual(len(changes['entries']), 24)
        self.assertTrue(chain(changes['entries']))
        self.assertEqual((changes['entries'][0]['from'], changes['entries'][-1]['seq']), (start, self.seq()))
        self.assertEqual(len(self.read('summary.json')['threads']['topic']['stamps']), 24)


if __name__ == '__main__':
    unittest.main()
