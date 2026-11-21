"""Hostile review, batch 4 (files, parsers and ids: pictures, an agent's page, voice, new topics, snippets).

One test per attack. A test named `test_held_...` is an attack the code withstood; any other
test asserts the correct / safe outcome of a suspected hole, so a FAILING test is a real hole.
Every CLI call runs against a temp board inside this repository, with a stand-in for every
outside service. Nothing here reaches the network: the one test about the real transcription
service runs the code in a process of its own, under a HOME of its own, with the calls replaced."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import concurrent.futures
import fcntl
import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
import zlib

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
TZ = 'Asia/Jerusalem'
BOARDLIB = os.environ.get('THREADS_BOARDLIB_DIR') or str(Path.home() / '.claude/skills/html-interview-board')
ID = r'[a-z0-9][a-z0-9-]{0,47}'
SECRET = b'GPS-32.0853N-34.7818E-SECRET'
RECORDER = ("import json, os, sys\nfrom pathlib import Path\n"
            "with Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args': sys.argv[1:]}) + '\\n')\n")
# The stand-in for the transcription service: it writes down what it was given, and may be slow, loud or failing.
EAR = ("import os, sys, time\n"
       "open(os.environ['EAR_RECORD'], 'a').write(sys.argv[1] + '\\n')\n"
       "time.sleep(float(os.environ.get('EAR_SLEEP', '0')))\n"
       "sys.stderr.write(os.environ.get('EAR_STDERR', ''))\n"
       "open(os.environ['EAR_RECORD'] + '.done', 'a').write(sys.argv[1] + '\\n')\n"
       "sys.exit(3) if os.environ.get('EAR_FAIL') else print(os.environ.get('EAR_WORDS', 'מילים מההקלטה'))\n")
# threads.py as a module, in a process of its own (its board is whatever BOARDS_DIR of that process says).
PRELUDE = r'''
import importlib.util, json, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('threads_under_test', os.environ['ADVD_CLI'])
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
assert os.environ['ADVD_ROOT'] in str(T.BOARD.resolve()), 'never the live board'
'''


def b64(raw):
    return base64.b64encode(raw).decode('ascii')


# ── pictures, built by hand ─────────────────────────────────────────────────

def seg(marker, payload):
    return b'\xff' + bytes([marker]) + struct.pack('>H', len(payload) + 2) + payload


def jpeg(extra=b'', w=3, h=2, trailer=b'', scan=b'\x12\x34\xff\x00\x56\xff\xd0\x78'):
    """The frame of a JPEG in the order a camera writes it; `extra` sits where metadata sits."""
    return (b'\xff\xd8' + seg(0xE0, b'JFIF\0\1\1\0\0\1\0\1\0\0') + extra + seg(0xDB, b'\0' + bytes(64))
            + seg(0xC0, b'\x08' + struct.pack('>HH', h, w) + b'\x01\x01\x11\x00') + seg(0xC4, b'\0' + bytes(16))
            + seg(0xDA, b'\x01\x01\x00\x00\x3f\x00') + scan + b'\xff\xd9' + trailer)


def exif(turn=6, extra=b''):
    """An EXIF block with one tag (orientation), and whatever else a camera adds after it."""
    return b'Exif\0\0' + b'MM\0*' + struct.pack('>IH', 8, 1) + struct.pack('>HHIHH', 0x0112, 3, 1, turn, 0) + struct.pack('>I', 0) + extra


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(extra=b'', w=1, h=1, trailer=b''):
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + extra
            + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'') + trailer)


def gif(extra=b'', w=1, h=1, trailer=b''):
    return (b'GIF89a' + struct.pack('<HH', w, h) + b'\x80\0\0' + b'\0\0\0\xff\xff\xff' + extra
            + b',\0\0\0\0\1\0\1\0\0' + b'\x02\x02\x4c\x01\x00' + b';' + trailer)


def riff(kind, data):
    return kind + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b'')


def webp(extra=b'', w=1, h=1, trailer=b'', flags=0x0C):
    body = (b'WEBP' + riff(b'VP8X', bytes([flags, 0, 0, 0]) + (w - 1).to_bytes(3, 'little') + (h - 1).to_bytes(3, 'little'))
            + riff(b'VP8 ', b'\x30\x01\x00\x9d\x01\x2a' + struct.pack('<HH', w & 0x3FFF, h & 0x3FFF) + bytes(8)) + extra)
    return b'RIFF' + struct.pack('<I', len(body)) + body + trailer


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
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'THREADS_NOW', 'THREADS_BOARDLIB_DIR', 'BOARD_LOCK_TIMEOUT',
                    'THREADS_SONIOX_CMD', 'THREADS_SONIOX_MODEL', 'THREADS_PUSH_CMD', 'THREADS_SNAP_CMD', 'THREADS_CONFIG_DIR'):
            self.env.pop(key, None)
        # the owner's own installation is in Hebrew (config.json "lang"): these tests describe it
        (self.root / '.threads-config/threads').mkdir(parents=True, exist_ok=True)
        (self.root / '.threads-config/threads/config.json').write_text('{"lang": "he"}', encoding='utf-8')

    def cli(self, *args, env=None, input=None, text=True, timeout=180):
        env = env or self.env
        assert env['BOARDS_DIR'] == str(self.root / 'boards') and env.get('THREADS_NOTIFY_CMD'), 'never the live board'
        return subprocess.run([sys.executable, str(CLI), *args], env=env, input=input, capture_output=True, text=text, timeout=timeout)

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


class AdvD(unittest.TestCase):
    T0 = 1_800_000_000.0    # 2027-01-15 10:00 in Jerusalem
    H = 3600

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-advd-', dir=ROOT, ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.box = Box(Path(self.tmp.name) / 'main')
        self.root, self.board, self.env = self.box.root, self.box.board, self.box.env
        self.count = 0
        # a worker that has settled its recording still mails the tower: let it finish before the folder goes
        self.addCleanup(lambda: time.sleep(0.4) if (self.root / 'ear.py').exists() else None)

    # ── helpers ─────────────────────────────────────────────────────────────

    def at(self, hours, **extra):
        return dict(self.env, THREADS_NOW=repr(self.T0 + hours * self.H), **extra)

    def ear(self, hours=0, **extra):
        """An environment in which recordings are transcribed by the stand-in."""
        script = self.root / 'ear.py'
        script.write_text(EAR)
        return self.at(hours, THREADS_SONIOX_CMD=shlex.join([sys.executable, str(script)]), EAR_RECORD=str(self.root / 'ear.log'), **extra)

    def heard(self):
        log = self.root / 'ear.log'
        return log.read_text().splitlines() if log.exists() else []

    def run_cli(self, *args, ok=True, input=None, env=None):
        r = self.box.cli(*args, env=env, input=input)
        self.assertNotIn('Traceback', r.stderr, f'{args}: a traceback instead of an answer')
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def post(self, payload, ok=True, env=None):
        """What the page does. Always exactly one JSON line; exit 0 exactly when ok."""
        r = self.box.post(payload, env=env)
        self.assertNotIn('Traceback', r.stderr, f'{str(payload)[:80]}: a traceback instead of an answer')
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, f'{str(payload)[:80]}: {r.stdout!r} {r.stderr!r}')
        answer = json.loads(lines[0])
        self.assertIsInstance(answer.get('ok'), bool)
        self.assertEqual(answer['ok'], r.returncode == 0, f'{str(payload)[:80]}: exit {r.returncode} with {answer}')
        if ok is not None:
            self.assertEqual(answer['ok'], ok, f'{str(payload)[:80]}: {answer}')
        return answer

    def refused(self, payload, env=None):
        """A refusal: one JSON line, non-zero exit, and NOTHING written, woken or mailed."""
        before, mails, pulse = self.box.files(), self.box.mails(), self.board / '.pulse'
        if pulse.exists():
            os.utime(pulse, (1, 1))
        answer = self.post(payload, ok=False, env=env)
        self.assertEqual(self.box.files(), before, f'{str(payload)[:80]}: a refused request wrote something')
        self.assertEqual(self.box.mails(), mails, f'{str(payload)[:80]}: a refused request mailed someone')
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

    def cid(self):
        self.count += 1
        return f'cid-{self.count}'

    def reply(self, text='', ok=True, env=None, tid='topic', cid=None, **extra):
        return self.post({'op': 'reply', 'thread': tid, 'text': text, 'cid': cid or self.cid(), **extra}, ok=ok, env=env)

    def topic(self, ok=True, env=None, **fields):
        return self.post({'op': 'new', 'cid': self.cid(), **fields}, ok=ok, env=env)

    def stored(self, data, tid='topic', **more):
        """Send one picture from the page. (the bytes that were stored, its record in the message), or (None, None) when refused."""
        answer = self.reply(ok=None, tid=tid, images=[{'data': b64(data), **more}])
        if not answer['ok']:
            return None, None
        record = self.state()['threads'][tid]['messages'][-1]['images'][0]
        return (self.board / record['file']).read_bytes(), record

    def files_of(self, *kinds):
        """The files (not folders) under uploads/ and snippets/."""
        found = []
        for kind in kinds or ('uploads', 'snippets'):
            base = self.board / kind
            found += sorted(p.relative_to(self.board).as_posix() for p in base.rglob('*') if not p.is_dir() or p.is_symlink()) if base.is_dir() else []
        return found

    def wait_for(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.05)
        self.fail(what)

    def settled(self, tid='topic'):
        """Wait until no recording of the thread is in the air (so no worker outlives the test)."""
        self.wait_for(lambda: all(m.get('status') != 'transcribing' for m in self.state()['threads'][tid]['messages']), 'a recording was never settled')
        spoken = [f"reply in {tid} ({m['id']})" for m in self.state()['threads'][tid]['messages'] if isinstance(m.get('voice'), dict)]
        deadline = time.monotonic() + 10            # the worker tells the tower after the state is saved; never a failure by itself
        while not all(any(tag in mail for mail in self.box.mails()) for tag in spoken) and time.monotonic() < deadline:
            time.sleep(0.05)

    def mailed(self, count, seconds=10):
        """Give the workers time to tell the tower (they do it after the state is saved). Never a failure by itself."""
        deadline = time.monotonic() + seconds
        while len(self.box.mails()) < count and time.monotonic() < deadline:
            time.sleep(0.05)

    def driver(self, script, env, input=None):
        """Run threads.py as a module in a process of its own; the last line it prints is JSON."""
        env = dict(env, ADVD_CLI=str(CLI), ADVD_ROOT=str(ROOT))
        assert env['BOARDS_DIR'] == str(self.root / 'boards'), 'never the live board'
        r = subprocess.run([sys.executable, '-c', PRELUDE + script], env=env, input=input, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    # ════════════════════════════════════════════════════════════════════════
    # PICTURES: what survives the cleaning
    # ════════════════════════════════════════════════════════════════════════

    def test_held_what_a_camera_writes_beside_the_pixels_is_dropped(self):
        self.new()
        cases = {
            'jpeg exif': jpeg(seg(0xE1, exif(1, SECRET))), 'jpeg xmp': jpeg(seg(0xE1, b'http://ns.adobe.com/xap/1.0/\0' + SECRET)),
            'jpeg iptc': jpeg(seg(0xED, b'Photoshop 3.0\0' + SECRET)), 'jpeg comment': jpeg(seg(0xFE, SECRET)),
            'jpeg app3-15': jpeg(b''.join(seg(m, SECRET) for m in (0xE3, 0xE4, 0xEB, 0xEC, 0xEF))),
            'jpeg after the end': jpeg(trailer=SECRET + b'\xff\xd8\xff\xe1' + SECRET), 'jpeg fill bytes before exif': jpeg(b'\xff\xff\xff' + seg(0xE1, exif(1, SECRET))),
            'jpeg exif between scans': jpeg(scan=b'\x12' + seg(0xE1, exif(1, SECRET)) + seg(0xDA, b'\x01\x01\x00\x00\x3f\x00') + b'\x33'),
            'png text': png(chunk(b'tEXt', b'Comment\0' + SECRET)), 'png compressed text': png(chunk(b'zTXt', b'c\0\0' + SECRET)),
            'png xmp': png(chunk(b'iTXt', b'XML:com.adobe.xmp\0\0\0\0\0' + SECRET)), 'png exif': png(chunk(b'eXIf', SECRET)),
            'png time': png(chunk(b'tIME', SECRET)), 'png after the end': png(trailer=SECRET),
            'webp exif': webp(riff(b'EXIF', SECRET)), 'webp xmp': webp(riff(b'XMP ', SECRET)), 'webp short tail': webp(trailer=SECRET[:7]),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                raw, record = self.stored(data)
                self.assertIsNotNone(raw, 'a well-formed picture was refused')
                self.assertNotIn(SECRET[:7], raw)
                self.assertTrue(raw.startswith(data[:2]) and record['file'].endswith('.' + {'j': 'jpg', 'p': 'png', 'w': 'webp'}[name[0]]))
        raw, record = self.stored(webp(riff(b'EXIF', SECRET)))
        self.assertEqual(raw[20] & 0x0C, 0, 'the header still says the file carries EXIF / XMP')
        # a picture stored turned keeps the one tag that says so, and nothing else of its EXIF
        raw, record = self.stored(jpeg(seg(0xE1, exif(6, SECRET)), w=3, h=2))
        self.assertEqual((raw.count(b'Exif\0\0'), SECRET in raw, record['w'], record['h']), (1, False, 2, 3))
        self.assertEqual(raw[2:4] + raw[6:12], b'\xff\xe1Exif\0\0')
        self.assertEqual(struct.unpack('>H', raw[4:6])[0], 34)

    def test_a_picture_stored_turned_stays_turned_in_every_kind(self):
        """A JPEG keeps the one tag that says how to turn it. A WebP carries the same tag in its EXIF chunk, and
        that chunk is dropped whole: a picture taken sideways is then shown sideways."""
        self.new()
        tiff = exif(6, SECRET)[6:]                  # the TIFF block alone, as a WebP stores it
        raw, record = self.stored(webp(riff(b'EXIF', tiff), w=4, h=3))
        self.assertNotIn(SECRET, raw)
        self.assertIn(b'\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06', raw, f'the orientation is gone (stored as w={record["w"]} h={record["h"]})')

    def test_a_jpeg_keeps_only_the_segments_a_decoder_needs(self):
        """APP2 and APP14 are kept whatever they hold ("the colour profile"), and so are APP0 and the reserved
        JPGn segments: whatever sits there is stored and served."""
        self.new()
        cases = {'APP2 that is no colour profile (FlashPix)': seg(0xE2, b'FPXR\0' + SECRET), 'APP2 that is no colour profile (MPF)': seg(0xE2, b'MPF\0' + SECRET),
                 'a second APP0 that is not JFIF': seg(0xE0, exif(1, SECRET)), 'APP14 that is not Adobe': seg(0xEE, SECRET), 'a reserved JPG0 segment': seg(0xF0, SECRET)}
        for name, extra in cases.items():
            with self.subTest(segment=name):
                raw, _ = self.stored(jpeg(extra))
                self.assertIsNotNone(raw)
                self.assertNotIn(SECRET, raw, f'{name}: its content survived the cleaning')

    def test_a_png_keeps_only_the_chunks_a_decoder_needs(self):
        """Five chunk kinds are dropped by name; every other ancillary or private chunk is stored as it came."""
        self.new()
        for kind in (b'caBX', b'mkBS', b'prVW', b'exIf', b'tXMP', b'zzZz'):
            with self.subTest(chunk=kind.decode()):
                raw, _ = self.stored(png(chunk(kind, SECRET)))
                self.assertIsNotNone(raw)
                self.assertNotIn(SECRET, raw, f'{kind.decode()}: its content survived the cleaning')

    def test_a_gif_is_cleaned_like_the_other_kinds(self):
        """A GIF is stored byte for byte: its comments, its XMP block and whatever follows the picture."""
        self.new()
        cases = {'a comment': gif(b'\x21\xfe' + bytes([len(SECRET)]) + SECRET + b'\0'),
                 'an XMP application block': gif(b'\x21\xff\x0bXMP DataXMP' + bytes([len(SECRET)]) + SECRET + b'\0'),
                 'bytes after the end': gif(trailer=SECRET)}
        for name, data in cases.items():
            with self.subTest(case=name):
                raw, _ = self.stored(data)
                self.assertIsNotNone(raw)
                self.assertNotIn(SECRET, raw, f'{name}: survived the cleaning')

    def test_a_webp_keeps_only_the_chunks_a_decoder_needs(self):
        """Only the chunks called exactly 'EXIF' and 'XMP ' are dropped; the declared end of the file is not honoured."""
        self.new()
        cases = {"a chunk called 'exif'": webp(riff(b'exif', SECRET)), "a chunk called 'XMP\\0'": webp(riff(b'XMP\0', SECRET)),
                 'an unknown chunk': webp(riff(b'GPS ', SECRET)), 'a chunk after the declared end of the file': webp(trailer=riff(b'JUNK', SECRET))}
        for name, data in cases.items():
            with self.subTest(case=name):
                raw, _ = self.stored(data)
                self.assertIsNotNone(raw)
                self.assertNotIn(SECRET, raw, f'{name}: survived the cleaning')

    def test_the_picture_he_sent_does_not_stay_on_the_board_as_it_came(self):
        """The server keeps the request at state/state.json, inside the served folder, until the next action:
        the picture as his phone made it (place, device, time) is there in full after it was "cleaned"."""
        self.new()
        original = jpeg(seg(0xE1, exif(1, SECRET)))
        raw, _ = self.stored(original)
        self.assertNotIn(SECRET, raw)
        left = [p.relative_to(self.board).as_posix() for p in self.board.rglob('*')
                if p.is_file() and (SECRET in p.read_bytes() or b64(original).encode() in p.read_bytes())]
        self.assertEqual(left, [], 'the picture with its metadata is still served from the board')

    # ── what counts as a picture ────────────────────────────────────────────

    def test_a_file_with_no_picture_in_it_is_not_stored_as_one(self):
        """The first bytes decide the kind and nothing checks that a picture follows them."""
        self.new()
        cases = {'a JPEG that is only its two ends': b'\xff\xd8\xff\xd9', 'a PNG with no header and no pixels': b'\x89PNG\r\n\x1a\n' + chunk(b'IEND', b''),
                 'a WebP with no chunks': b'RIFF\x04\0\0\0WEBP', 'ten bytes of GIF header': b'GIF89a\1\0\1\0',
                 'markup behind a GIF header': b'GIF89a' + b'<svg onload=alert(1)><script>alert(document.domain)</script>',
                 'a script behind a GIF header': b'GIF89a/*' + b'\0\0' + b'*/=1;alert(document.domain)//'}
        for name, data in cases.items():
            with self.subTest(case=name):
                before = self.files_of('uploads')
                answer = self.reply(ok=None, images=[{'data': b64(data)}])
                self.assertFalse(answer['ok'], f'{name}: stored as {sorted(set(self.files_of("uploads")) - set(before))}')

    def test_a_picture_that_claims_absurd_dimensions_is_refused(self):
        """A file of a few dozen bytes may claim any size; the claim is stored and the page is handed the file."""
        self.new()
        cases = {'png 4,000,000,000 x 4,000,000,000': png(w=4_000_000_000, h=4_000_000_000), 'jpeg 65,535 x 65,535': jpeg(w=65535, h=65535),
                 'gif 65,535 x 65,535': gif(w=65535, h=65535), 'webp 16,777,216 x 16,777,216': webp(w=1 << 24, h=1 << 24)}
        for name, data in cases.items():
            with self.subTest(case=name):
                raw, record = self.stored(data)
                self.assertIsNone(raw, f'{name}: stored ({len(data)} bytes) with w={record and record["w"]} h={record and record["h"]}')

    def test_held_no_bytes_make_a_parser_crash_stall_or_grow(self):
        seeds = {'jpeg': jpeg(seg(0xE1, exif(6)) + seg(0xE2, b'ICC_PROFILE\0\1\1' + bytes(20)) + seg(0xFE, b'hi')),
                 'png': png(chunk(b'tEXt', b'k\0v') + chunk(b'eXIf', b'II*\0')), 'gif': gif(b'\x21\xfe\x02hi\0'),
                 'webp': webp(riff(b'EXIF', b'abc') + riff(b'XMP ', b'<x/>'))}
        report = self.driver(r'''
import base64, random, struct, time
job = json.load(sys.stdin)
random.seed(job['seed'])
bad, slow, cases = {}, [], 0
MAGIC = {'jpg': b'\xff\xd8', 'png': b'\x89PNG\r\n\x1a\n', 'gif': b'GIF8', 'webp': b'RIFF'}

def run(data, tag):
    global cases
    cases += 1
    started = time.perf_counter()
    try:
        p = T.picture(data, 'name.png', 'caption')
        if not (isinstance(p['raw'], bytes) and p['raw'].startswith(MAGIC[p['ext']]) and len(p['raw']) <= len(data) + 64
                and all(v is None or type(v) is int for v in (p['w'], p['h']))):
            bad.setdefault(tag + ': a record that is not a picture', base64.b64encode(data[:80]).decode())
    except ValueError:
        pass
    except BaseException as exc:
        bad.setdefault(f'{tag}: {type(exc).__name__}: {exc}'[:140], base64.b64encode(data[:80]).decode())
    took = time.perf_counter() - started
    if took > job['slow']:
        slow.append([tag, len(data), round(took, 2)])

PIECES = [b'\xff', b'\xff\xff', b'\xff\xd9', b'\xff\xda\x00\x02', b'\xff\xe1\xff\xff', b'\0\0\0\0', b'\xff\xff\xff\xff', b'IHDR', b'IEND',
          b'VP8X', b'VP8 ', b'VP8L', b'EXIF', b'Exif\0\0', b'II*\0', b'MM\0*', b'\xff\xc0\x00\x03\x08', b'VP8X\0\0\0\0', b'VP8X\x09\0\0\0']
LENGTHS = [b'\0\0\0\0', b'\xff\xff\xff\xff', b'\x7f\xff\xff\xff', b'\0\0\0\1', b'\1\0\0\0', b'\0\0\0\x08', b'\xff\xff\0\0']
for kind, seed in ((k, base64.b64decode(v)) for k, v in job['seeds'].items()):
    for cut in range(len(seed) + 1):                     # every truncation, every tail, every hole
        run(seed[:cut], kind + ' cut short')
        run(seed[:12] + seed[cut:], kind + ' with a hole')
    for i in range(len(seed)):                           # every byte set to a value a parser treats specially
        for value in (0, 1, 2, 0x7F, 0x80, 0xD9, 0xDA, 0xE1, 0xFF):
            run(seed[:i] + bytes([value]) + seed[i + 1:], kind + ' with one byte changed')
    for _ in range(job['rounds']):
        d = bytearray(seed)
        for _ in range(random.randint(1, 6)):
            op, pos = random.random(), random.randrange(len(d) + 1)
            if op < 0.3 and d:
                d[random.randrange(len(d))] ^= 1 << random.randrange(8)
            elif op < 0.5:
                d[pos:pos] = random.choice(PIECES + [random.randbytes(random.randint(1, 9))])
            elif op < 0.7:
                del d[pos:pos + random.randint(1, 12)]
            elif op < 0.85 and len(d) > 4:
                at = random.randrange(len(d) - 3)
                d[at:at + 4] = random.choice(LENGTHS)
            else:
                a, b = sorted((random.randrange(len(d) + 1), random.randrange(len(d) + 1)))
                d[pos:pos] = d[a:b]
        run(bytes(d), kind + ' mutated')
# the most work two megabytes can ask for
M, sof, sos = 2_000_000, b'\xff\xc0\x00\x0b\x08\x00\x02\x00\x03\x01\x01\x11\x00', b'\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00'
head = b'\xff\xd8' + sof + sos
big_ifd = b'Exif\0\0MM\0*' + struct.pack('>I', 8) + b'\xff\xff' + struct.pack('>HHIHH', 1, 1, 1, 1, 0) * 5400
for tag, data in (('a scan of stuffed bytes', head + b'\xff\x00' * ((M - len(head) - 2) // 2) + b'\xff\xd9'),
                  ('a scan of fill bytes', head + b'\xff' * (M - len(head) - 2) + b'\xff\xd9'),
                  ('a scan of restart markers', head + b'\xff\xd0' * ((M - len(head) - 2) // 2) + b'\xff\xd9'),
                  ('fill bytes and no picture', b'\xff\xd8' + b'\xff' * (M - 4) + b'\xff\xd9'),
                  ('half a million empty segments', b'\xff\xd8' + b'\xff\xdb\x00\x02' * ((M - 4) // 4) + b'\xff\xd9'),
                  ('half a million empty scans', b'\xff\xd8' + b'\xff\xda\x00\x02' * ((M - 4) // 4) + b'\xff\xd9'),
                  ('thirty EXIF blocks of 5400 tags', b'\xff\xd8' + (b'\xff\xe1' + struct.pack('>H', len(big_ifd) + 2) + big_ifd) * 30 + b'\xff\xd9'),
                  ('empty PNG chunks', b'\x89PNG\r\n\x1a\n' + b'\0\0\0\0zzZz\0\0\0\0' * ((M - 20) // 12) + b'\0\0\0\0IEND\xaeB`\x82'),
                  ('empty WebP chunks', b'RIFF\0\0\0\0WEBP' + b'JUNK\0\0\0\0' * ((M - 12) // 8)),
                  ('a WebP of headers', b'RIFF\0\0\0\0WEBP' + b'VP8X\x01\0\0\0\x0c\0' * ((M - 12) // 10))):
    run(data, tag)
print(json.dumps({'cases': cases, 'bad': bad, 'slow': slow}))
''', self.env, input=json.dumps({'seed': 20261116, 'rounds': 8000, 'slow': 3.0, 'seeds': {k: b64(v) for k, v in seeds.items()}}))
        self.assertGreater(report['cases'], 30000)
        self.assertEqual(report['bad'], {}, 'something other than a refusal came out of a parser')
        self.assertEqual(report['slow'], [], 'a parser needed seconds for one picture')

    def test_held_the_heaviest_request_a_page_can_send_is_answered_in_time(self):
        self.new()
        head = b'\xff\xd8' + seg(0xC0, b'\x08' + struct.pack('>HH', 2, 3) + b'\x01\x01\x11\x00') + seg(0xDA, b'\x01\x01\x00\x00\x3f\x00')
        heavy = head + b'\xff' * (1_450_000 - len(head) - 2) + b'\xff\xd9'
        payload = json.dumps({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'heavy', 'images': [{'data': b64(heavy)}, {'data': b64(heavy)}]})
        self.assertLess(len(payload), 4_000_000)
        started = time.monotonic()
        self.post(payload, ok=None)
        self.assertLess(time.monotonic() - started, 20)

    # ── the name, the caption, the limits ───────────────────────────────────

    def test_held_the_name_of_a_picture_is_a_label_never_a_path_or_a_kind(self):
        self.new()
        for name, label in (('../../etc/passwd', 'passwd'), ('C:\\Users\\x\\evil.html', 'evil.html'), ('a\x00b\x1b[2J.svg', 'ab[2J.svg'),
                            ('\u202egnp.exe', 'gnp.exe'), ('\u2066x\u2069\u200b.png', 'x.png'), ('x' * 300 + '.html', 'x' * 120), ('שם  עם\n רווחים.png', 'שם עם רווחים.png'),
                            ('', None), (5, None), ('   ', None), ('/', None), (['a'], None), ('\ud800', None)):
            with self.subTest(name=repr(name)):
                raw, record = self.stored(gif(), name=name)
                self.assertEqual(record['name'], label)
                self.assertRegex(record['file'], r'^uploads/topic/m\d+-1\.gif$')
                self.assertEqual(raw, gif())
        self.assertEqual(sorted({Path(p).suffix for p in self.files_of('uploads')}), ['.gif'])
        self.assertTrue(all((self.board / 'uploads/topic').resolve() == (self.board / p).resolve().parent for p in self.files_of('uploads')))

    def test_a_caption_carries_no_control_or_direction_characters(self):
        """The name of a picture is stripped of them; its caption is not, and `threads show` prints it to a terminal."""
        self.new()
        _, record = self.stored(gif(), caption='לפני\x1b[2J\x1b]0;title\x07אחרי\x00\x08\u202eהפוך\u2066מבודד\u2069')
        hostile = [f'U+{ord(ch):04X}' for ch in record.get('caption', '') if unicodedata.category(ch) == 'Cc' or ch in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069']
        self.assertEqual(hostile, [], 'stored in the caption')
        self.assertNotIn('\x1b', self.run_cli('show', 'topic').stdout)

    def test_held_picture_limits_and_types(self):
        self.new()
        good = b64(gif())
        bad = [[], {}, 'x', None, 5, [{'data': good}] * 5, [None], ['x'], [[{'data': good}]], [{}], [{'data': 5}], [{'data': None}], [{'data': [good]}],
               [{'data': ''}], [{'data': '!!!'}], [{'data': good[:12] + '\n' + good[12:]}], [{'data': ' ' + good}], [{'data': good.replace('/', '_').replace('+', '-') + '-_'}],
               [{'data': good + '\ud800'}], [{'data': good, 'caption': 5}], [{'data': good, 'caption': ['x']}], [{'data': good, 'caption': 'x' * 501}],
               [{'data': b64(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')}], [{'data': b64(b'<!doctype html><script>alert(1)</script>')}],
               [{'data': b64(b'BM' + bytes(60))}], [{'data': b64(b'\0\0\0\x18ftypheic' + bytes(40))}], [{'data': b64(b'GIF89a')}], [{'data': b64(b'GIF89a\1\0\1')}],
               [{'data': b64(b'\xff\xd8\xff')}], [{'data': b64(b'\xff\xd8\xff\xe1\x00')}], [{'data': b64(b'\x89PNG\r\n\x1a\n')}],
               [{'data': b64(b'\x89PNG\r\n\x1a\n' + b'\0\0\0\0IHDR' + bytes(4) + chunk(b'IEND', b''))}], [{'data': b64(b'\x89PNG\r\n\x1a\n' + b'\xff\xff\xff\xffIDAT' + bytes(40))}],
               [{'data': b64(b'RIFF\x0c\0\0\0WEBPVP8X\0\0\0\0')}], [{'data': b64(b'RIFF\x0c\0\0\0WEBPVP8 \x04\0\0\0abcd')}], [{'data': b64(b'RIFF\x0c\0\0\0WEBPJUNK\xff\xff\xff\xff')}],
               [{'data': b64(jpeg()[:-2])}], [{'data': b64(png()[:-12])}],
               [{'data': good}, {'data': good}, {'data': 'x!'}], [{'data': good}, {'data': b64(b'not a picture')}, {'data': good}],
               [{'data': b64(b'GIF89a' + bytes(2_000_001))}]]
        for images in bad:
            with self.subTest(images=str(images)[:70]):
                self.refused({'op': 'reply', 'thread': 'topic', 'text': 'עם תמונה', 'cid': self.cid(), 'images': images})
        self.assertEqual((self.thread()['messages'], self.files_of()), ([], []))
        # four pictures of every kind in one message are the most, and each file is named by the tool
        self.reply(images=[{'data': b64(d), 'name': 'x.html'} for d in (jpeg(), png(), gif(), webp())])
        self.assertEqual(self.files_of(), ['uploads/topic/m1-1.jpg', 'uploads/topic/m1-2.png', 'uploads/topic/m1-3.gif', 'uploads/topic/m1-4.webp'])
        self.assertEqual({mimetypes.guess_type(p)[0].split('/')[0] for p in self.files_of()}, {'image'})

    def test_held_an_agents_picture_goes_through_the_same_door(self):
        self.new()
        folder = self.root / 'agent'
        folder.mkdir()
        (folder / 'photo.html').write_bytes(jpeg(seg(0xE1, exif(1, SECRET)) + seg(0xFE, SECRET), trailer=SECRET))
        (folder / 'text.png').write_text('<html>')
        (folder / 'big.gif').write_bytes(b'GIF89a' + bytes(2_000_001))
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--image', str(folder / 'photo.html'), '--caption', '  כיתוב   של\nהמגדל ')
        record = self.thread()['messages'][0]['images'][0]
        self.assertEqual((record['file'], record['name'], record['caption']), ('uploads/topic/m1-1.jpg', 'photo.html', 'כיתוב של המגדל'))
        self.assertNotIn(SECRET, (self.board / record['file']).read_bytes())
        before = self.box.files()
        for args in (['--image', str(folder / 'text.png')], ['--image', str(folder / 'big.gif')], ['--image', str(folder / 'missing.png')], ['--image', str(folder)],
                     ['--image', str(folder / 'photo.html')] * 5, ['--image', str(folder / 'photo.html'), '--caption', 'a', '--caption', 'b'],
                     ['--image', str(folder / 'photo.html'), '--caption', 'x' * 501], ['--caption', 'כיתוב בלי תמונה']):
            with self.subTest(args=str(args)[-60:]):
                self.run_cli('say', 'topic', '--from', 'tower', 'ראה', *args, ok=False)
        self.assertEqual(self.box.files(), before)

    # ════════════════════════════════════════════════════════════════════════
    # FILES: orphans, links, paths
    # ════════════════════════════════════════════════════════════════════════

    def test_held_a_reply_that_is_refused_wrote_none_of_its_files(self):
        self.new()
        self.run_cli('ask', 'topic', 'להמשיך?', '--options', 'כן,לא')
        self.run_cli('new', 'shut', 'סגור')
        self.run_cli('close', 'shut')
        files = {'images': [{'data': b64(png())}, {'data': b64(gif())}], 'snippet': {'text': 'לוג ארוך', 'name': 'a.log'}}
        for extra in ({'q': 'm9'}, {'reply_to': 'm9'}, {'answer': {'x': ['y']}, 'q': 'm1'}, {'run': {'msg_id': 'm1', 'block_index': 0, 'sha256': 'x'}},
                      {'under': 5}, {'thread': 'shut'}, {'thread': 'nowhere'}, {'cid': ''}, {'cid': 'c\ud800'}, {'text': 'x' * 8001}, {'text': 'x\udfff'},
                      {'images': files['images'] + [{'data': b64(b'bad')}]}, {'snippet': {'text': 'x\ud800'}}, {'last': 5}):
            with self.subTest(extra=str(extra)[:60]):
                self.refused({'op': 'reply', 'thread': 'topic', 'text': 'עם קבצים', 'cid': self.cid(), **files, **extra})
        self.assertEqual(self.files_of(), [])

    def test_held_a_save_that_fails_takes_its_files_back(self):
        self.new()
        self.reply('ראשונה', images=[{'data': b64(png())}], snippet={'text': 'קטע', 'name': 'a.md'})
        page = self.root / 'page.html'
        page.write_text('<p>דף</p>')
        picture = self.root / 'pic.gif'
        picture.write_bytes(gif())
        before = self.box.files()
        os.chmod(self.board, 0o555)                 # the state can be read and locked, and cannot be replaced
        self.addCleanup(os.chmod, self.board, 0o755)
        try:
            answer = self.post({'op': 'reply', 'thread': 'topic', 'text': 'שנייה', 'cid': 'c-fail', 'snippet': {'text': 'עוד קטע', 'name': 'b.log'},
                                'images': [{'data': b64(jpeg())}, {'data': b64(gif())}, {'data': b64(webp())}]}, ok=False)
            self.run_cli('say', 'topic', '--from', 'tower', 'א' * 60_000, '--image', str(picture), '--image', str(picture), '--html', str(page), ok=False)
            voice = self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'v-fail', 'voice': {'data': b64(b'OggS' + bytes(40)), 'seconds': 2}}, ok=False, env=self.ear())
        finally:
            os.chmod(self.board, 0o755)
        self.assertEqual((answer['ok'], voice['ok']), (False, False))
        self.assertEqual(self.box.files(), before, 'a command whose state was never saved left files behind')
        self.assertEqual(self.heard(), [])
        self.assertEqual(self.reply('שלישית', images=[{'data': b64(gif())}])['msg_id'], 'm2')
        self.assertEqual((self.board / 'uploads/topic/m2-1.gif').read_bytes(), gif())

    def test_held_text_that_cannot_be_stored_leaves_no_file_behind(self):
        self.new()
        self.new('caps')
        picture = self.root / 'pic.gif'
        picture.write_bytes(gif())
        # the page: refused before anything is written, or stored without the character that cannot be
        answer = self.reply(ok=None, tid='caps', images=[{'data': b64(gif()), 'caption': 'כיתוב\udc80'}])
        self.assertEqual(self.files_of(), ['uploads/caps/m1-1.gif'] if answer['ok'] else [])
        self.assertEqual([m['images'][0]['caption'] for m in self.thread('caps')['messages']], ['כיתוב'] if answer['ok'] else [])
        # an agent: the note reaches the state only when it is saved, after the files were written
        (self.root / 'p.html').write_text('<p>x</p>')
        r = self.box.cli('say', 'topic', '--from', 'tower', 'ראה', '--state', 'working', '--note', b'bad\xff', '--image', str(picture), '--html', str(self.root / 'p.html'))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('Traceback', r.stderr)
        mine = lambda: [p for p in self.files_of() if '/caps/' not in p]
        self.assertEqual((self.thread()['messages'], mine()), ([], []))
        # a new topic whose link cannot be stored: its long first message is a file by then
        answer = self.post({'op': 'new', 'title': 'נושא', 'text': 'ב' * 5000, 'cid': 'n1', 'links': [{'label': 'x\ud800', 'url': 'https://a.example'}]}, ok=False)
        self.assertEqual((answer['ok'], list(self.state()['threads']), mine()), (False, ['topic', 'caps'], []))

    def test_a_topic_that_was_never_opened_leaves_no_folder_behind(self):
        """The file of its first message is taken back, the folder made for it is not."""
        self.new()
        self.post({'op': 'new', 'title': 'נושא', 'text': 'ב' * 5000, 'cid': 'n1', 'links': [{'label': 'x\ud800', 'url': 'https://a.example'}]}, ok=False)
        self.assertEqual(list(self.state()['threads']), ['topic'])
        left = sorted(p.relative_to(self.board).as_posix() for kind in ('snippets', 'uploads') for p in (self.board / kind).glob('*'))
        self.assertEqual(left, [], 'a folder named after a thread that does not exist')

    def test_a_file_of_a_message_reaches_the_disk_before_the_state_that_names_it(self):
        """A snippet used to be written through boardlib.atomic_write_text (flush, fsync, rename). `put_file` renames
        without the fsync, while the state that points at the file is still fsynced: after a power cut the message
        can be there and its snippet, picture or recording empty."""
        self.new()
        source, picture = self.root / 'log.txt', self.root / 'pic.gif'
        source.write_text('שורה\n' * 50)
        picture.write_bytes(gif())
        report = self.driver(r'''
synced, real = [], os.fsync

def fsync(fd):
    synced.append(os.fstat(fd).st_ino)
    return real(fd)

os.fsync = fsync
sys.argv = ['threads.py', 'say', 'topic', '--from', 'tower', 'ראה', '--snippet', os.environ['ADVD_FILE'], '--image', os.environ['ADVD_PIC']]
code = T.main()
files = {p.relative_to(T.BOARD).as_posix(): p.stat().st_ino in synced for p in sorted(T.BOARD.rglob('m1*'))}
print(json.dumps({'exit': code, 'state': T.STATE.stat().st_ino in synced, 'files': files}))
''', dict(self.env, ADVD_FILE=str(source), ADVD_PIC=str(picture)))
        self.assertEqual((report['exit'], report['state'], sorted(report['files'])), (0, True, ['snippets/topic/m1.txt', 'uploads/topic/m1-1.gif']))
        self.assertEqual([name for name, on_disk in report['files'].items() if not on_disk], [], 'renamed into place without an fsync')

    def test_held_a_held_lock_refuses_before_anything_is_written(self):
        self.new()
        with open(self.board / '.state.json.lock', 'a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                env = dict(self.env, BOARD_LOCK_TIMEOUT='0.3')
                self.refused({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c1', 'images': [{'data': b64(gif())}], 'snippet': {'text': 'קטע'}}, env=env)
                self.refused({'op': 'new', 'title': 'נושא', 'text': 'ב' * 5000, 'cid': 'n1'}, env=env)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        self.assertEqual(self.files_of(), [])

    def test_cleaning_up_after_a_failure_never_deletes_the_file_of_another_message(self):
        """The files of a command that failed are removed after the lock is released, by name. A command that
        took the lock in between was given the same message id, so the same file name: its picture is deleted."""
        self.new()
        mine, other = self.root / 'mine.gif', self.root / 'other.gif'
        mine.write_bytes(gif())
        other.write_bytes(gif(trailer=b'the picture of the tower'))
        report = self.driver(r'''
import contextlib, subprocess
real_lock, state_lock = T.bl.file_lock, {'used': False}

@contextlib.contextmanager
def lock(path, *args, **kwargs):
    failed = False
    try:
        with real_lock(path, *args, **kwargs):
            yield
    except BaseException:
        failed = True
        raise
    finally:
        # The lock is free and the failed command has not removed its files yet: another agent speaks now.
        if failed and str(path) == str(T.STATE) and not state_lock['used']:
            state_lock['used'] = True
            subprocess.run([sys.executable, os.environ['ADVD_CLI'], 'say', 'topic', '--from', 'tower', 'התמונה של המגדל', '--image', os.environ['ADVD_OTHER']],
                           check=True, capture_output=True)

T.bl.file_lock = lock
# a note that cannot be stored (bytes that are not UTF-8 on the command line): the save fails after the picture was written
sys.argv = ['threads.py', 'say', 'topic', '--from', 'fork', 'התמונה של הענף', '--state', 'working', '--note', 'bad\udcff', '--image', os.environ['ADVD_MINE']]
print(json.dumps({'exit': T.main(), 'raced': state_lock['used']}))
''', dict(self.env, ADVD_MINE=str(mine), ADVD_OTHER=str(other)))
        self.assertEqual(report, {'exit': 1, 'raced': True})
        messages = self.thread()['messages']
        self.assertEqual([(m['from'], m['images'][0]['file']) for m in messages], [('tower', 'uploads/topic/m1-1.gif')])
        self.assertTrue((self.board / 'uploads/topic/m1-1.gif').exists(), "the tower's stored message lost its picture to the clean-up of a command that failed")

    def test_held_a_link_where_a_folder_of_files_should_be_is_never_written_through(self):
        self.new()
        outside = self.root / 'outside'
        outside.mkdir()
        page = self.root / 'page.html'
        page.write_text('<p>דף</p>')
        page.with_name('x.gif').write_bytes(gif())
        payload = lambda: {'op': 'reply', 'thread': 'topic', 'text': '', 'cid': self.cid(), 'images': [{'data': b64(gif())}]}
        for kind, sub in (('uploads', 'topic'), ('uploads', None), ('snippets', 'topic'), ('snippets', None)):
            with self.subTest(link=f'{kind}/{sub or ""}'):
                link = self.board / kind / sub if sub else self.board / kind
                link.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(outside, link)
                try:
                    if kind == 'uploads':
                        self.refused(payload())
                        self.refused({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': self.cid(), 'voice': {'data': b64(b'OggS' + bytes(20)), 'seconds': 2}}, env=self.ear())
                        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--html', str(page), ok=False)
                        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--image', str(page.with_name('x.gif')), ok=False)
                    else:
                        self.refused({'op': 'reply', 'thread': 'topic', 'text': 'x' * 5000, 'cid': self.cid()})
                        self.refused({'op': 'reply', 'thread': 'topic', 'text': 'x', 'cid': self.cid(), 'snippet': {'text': 'קטע'}})
                finally:
                    os.unlink(link)
                    if sub:
                        link.parent.rmdir()
        self.assertEqual((list(outside.iterdir()), self.thread()['messages']), ([], []))
        # a dangling link is no better
        os.symlink(self.root / 'nowhere', self.board / 'uploads')
        self.refused(payload())
        self.assertFalse((self.root / 'nowhere').exists())

    def test_a_link_that_points_at_itself_is_refused_like_any_other_link(self):
        """`folder()` resolves the path; on this Python a link loop there raises RuntimeError, which nothing catches:
        the page gets a traceback (with the absolute path of the board) where one JSON line is promised."""
        self.new()
        (self.board / 'uploads').mkdir()
        os.symlink('topic', self.board / 'uploads/topic')
        r = self.box.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'c1', 'images': [{'data': b64(gif())}]})
        self.assertNotIn('Traceback', r.stderr, r.stderr.strip().splitlines()[-1:])
        self.assertEqual((r.returncode, json.loads(r.stdout)['ok']), (1, False))

    def test_held_a_link_at_the_name_of_a_file_is_replaced_never_followed(self):
        self.new()
        victim = self.root / 'victim.txt'
        victim.write_text('do not touch')
        for kind, name in (('uploads', 'm1-1.gif'), ('snippets', 'm1.log'), ('uploads', 'm2.html.txt'), ('uploads', 'm3.ogg')):
            (self.board / kind / 'topic').mkdir(parents=True, exist_ok=True)
            os.symlink(victim, self.board / kind / 'topic' / name)
        page = self.root / 'page.html'
        page.write_text('<p>דף</p>')
        self.reply(images=[{'data': b64(gif())}], snippet={'text': 'קטע', 'name': 'a.log'})
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--html', str(page))
        self.reply(voice={'data': b64(b'OggS' + bytes(20)), 'seconds': 2}, env=self.ear())
        self.settled()
        self.assertEqual(victim.read_text(), 'do not touch')
        for kind, name in (('uploads', 'm1-1.gif'), ('snippets', 'm1.log'), ('uploads', 'm2.html.txt'), ('uploads', 'm3.ogg')):
            self.assertFalse((self.board / kind / 'topic' / name).is_symlink(), name)
        self.assertEqual((self.board / 'uploads/topic/m1-1.gif').read_bytes(), gif())

    def test_removing_a_thread_never_deletes_through_a_link(self):
        """`folder()` refuses to write through a link at uploads/ or snippets/, so nothing of the thread can be
        there; `rm` goes through that link all the same and deletes the folder that has the thread's name."""
        self.new('victim')
        for kind in ('uploads', 'snippets'):
            elsewhere = self.root / f'elsewhere-{kind}'
            (elsewhere / 'victim').mkdir(parents=True)
            (elsewhere / 'victim/precious.txt').write_text('not a file of this board')
            os.symlink(elsewhere, self.board / kind)
        self.run_cli('rm', 'victim', '--yes')
        for kind in ('uploads', 'snippets'):
            with self.subTest(link=kind):
                self.assertTrue((self.root / f'elsewhere-{kind}/victim/precious.txt').exists(), f'rm followed the link at {kind}/ and deleted a folder outside the board')

    def test_held_removing_a_thread_whose_folder_is_a_link_leaves_the_target(self):
        self.new('victim')
        self.new('other')
        self.reply(tid='other', images=[{'data': b64(gif())}], snippet={'text': 'קטע'})
        for kind in ('uploads', 'snippets'):
            elsewhere = self.root / f'elsewhere-{kind}'
            elsewhere.mkdir()
            (elsewhere / 'precious.txt').write_text('not a file of this board')
            os.symlink(elsewhere, self.board / kind / 'victim')
        self.run_cli('rm', 'victim', '--yes')
        self.assertTrue(all((self.root / f'elsewhere-{kind}/precious.txt').exists() for kind in ('uploads', 'snippets')))
        self.assertEqual([p for p in self.files_of() if 'other' in p], ['uploads/other/m1-1.gif', 'snippets/other/m1.txt'])

    def test_held_an_id_that_is_not_a_plain_folder_name_never_loads(self):
        self.new()
        self.reply(images=[{'data': b64(gif())}])
        good = self.state()
        for bad in ('..', '.', 'A', 'a.', 'a/b', 'con.', '', ' x', 'x ', 'x' * 49, '-a', 'a_b', 'ａ', 'a\n', 'topic/../topic'):
            with self.subTest(id=repr(bad)):
                data = json.loads(json.dumps(good))
                data['threads'][bad] = dict(json.loads(json.dumps(good['threads']['topic'])), id=bad)
                self.put_state(data)
                before = self.box.files()
                for args in (['list'], ['rm', bad, '--yes'], ['rm', 'topic', '--yes'], ['say', 'topic', '--from', 'tower', 'x'], ['transcribe', bad, 'm1'], ['sweep']):
                    r = self.box.cli(*args, env=self.ear())
                    self.assertNotIn('Traceback', r.stderr)
                self.refused({'op': 'reply', 'thread': bad, 'text': '', 'cid': self.cid(), 'images': [{'data': b64(gif())}]})
                self.refused({'op': 'new', 'title': 'נושא', 'text': 'x', 'cid': self.cid()})
                self.assertEqual(self.box.files(), before)
        self.assertTrue((self.board / 'uploads/topic/m1-1.gif').exists())

    def test_held_a_file_path_written_into_the_state_by_hand_is_never_followed(self):
        self.new()
        self.new('other')
        self.reply(tid='other', images=[{'data': b64(gif())}], snippet={'text': 'קטע של אחר', 'name': 'o.log'})
        outside = self.root / 'outside.png'
        outside.write_bytes(png())
        (self.board / 'uploads/topic').mkdir(parents=True)
        os.symlink(outside, self.board / 'uploads/topic/link.png')
        data = self.state()
        topic = data['threads']['topic']
        topic['messages'].append({
            'id': 'm1', 'from': 'owner', 'text': 'x', 'ts': self.T0, 'status': 'pending', 'cid': 'c1',
            'images': [{'file': '../../../outside.png'}, {'file': str(outside)}, {'file': 'uploads/other/m1-1.gif'}, {'file': 'uploads/topic/link.png'},
                       {'file': 'uploads/topic'}, {'file': 'uploads/topic/../other/m1-1.gif'}, {'file': 5}, 'x', None],
            'snippet': {'file': 'snippets/other/m1.log', 'chars': 5, 'only': True}, 'html': {'file': '/etc/hosts'},
            'voice': {'file': 'uploads/other/m1-1.gif', 'state': 'done', 'seconds': 2}})
        topic['next'] = 2
        self.put_state(data)
        shown = json.loads(self.run_cli('show', 'topic', '--json').stdout)['messages'][0]
        self.assertEqual([r for r in shown['images'] if isinstance(r, dict) and 'path' in r], [])
        self.assertNotIn('path', shown['snippet'])
        row = json.loads(self.run_cli('pending').stdout)[-1]
        self.assertEqual((row['msg_id'], row['text'], [k for k in ('images', 'voice', 'snippet') if k in row]), ('m1', 'x', []))
        text = self.run_cli('show', 'topic').stdout
        self.assertFalse(any(word in text for word in ('outside', '/etc/hosts', 'uploads/other', 'snippets/other', 'link.png')), text)
        self.run_cli('snippet', 'topic', 'm1', ok=False)

    def test_held_threads_named_like_the_folders_of_the_board(self):
        names = ('uploads', 'snippets', 'state', 'icons', 'vendor', 'con', 'nul', 'tower', 'new', '0')
        for tid in names:
            self.run_cli('new', tid, 'כותרת ' + tid)
            self.reply('ב' * 4500, tid=tid, images=[{'data': b64(gif())}])
        self.assertEqual(self.files_of(), sorted(f'uploads/{t}/m1-1.gif' for t in names) + sorted(f'snippets/{t}/m1.txt' for t in names))
        self.run_cli('rm', 'uploads', '--yes')
        self.run_cli('rm', 'state', '--yes')
        left = [t for t in names if t not in ('uploads', 'state')]
        self.assertEqual(self.files_of(), sorted(f'uploads/{t}/m1-1.gif' for t in left) + sorted(f'snippets/{t}/m1.txt' for t in left))
        self.assertTrue((self.board / 'state/state.json').exists() and (self.board / 'state.json').exists())

    # ════════════════════════════════════════════════════════════════════════
    # AN AGENT'S PAGE
    # ════════════════════════════════════════════════════════════════════════

    def test_held_no_file_the_tool_can_make_is_served_as_something_a_browser_runs(self):
        """The board server answers with the type Python guesses from the name (SimpleHTTPRequestHandler)."""
        self.new()
        page = self.root / 'page.html'
        page.write_text('<script>alert(1)</script>')
        payload = b'<html><script>alert(document.domain)</script>'
        self.reply(images=[{'data': b64(d), 'name': 'x.html'} for d in (jpeg(seg(0xE0, payload)), png(chunk(b'IDAT', payload)), gif(trailer=payload), webp(riff(b'ALPH', payload)))],
                   snippet={'text': payload.decode(), 'name': 'x.html'})
        for n, name in enumerate(('a.md', 'a.log', 'a.svg', 'a.xhtml', 'a.js', 'a.htm', 'a.html.md', 'a'), 2):
            self.reply('ראה', snippet={'text': payload.decode(), 'name': name})
        page.with_name('p.svg').write_bytes(gif())
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--html', str(page), '--snippet', str(page), '--image', str(page.with_name('p.svg')))
        for data in (b'\x1a\x45\xdf\xa3' + payload, b'\0\0\0\x18ftyp' + payload, b'OggS' + payload):
            self.reply(voice={'data': b64(data), 'seconds': 1, 'type': 'text/html'}, env=self.ear())
            self.settled()
        kinds = {Path(p).name.split('.', 1)[1]: mimetypes.guess_type(p)[0] for p in self.files_of()}
        self.assertEqual(sorted(kinds), ['gif', 'html.txt', 'jpg', 'log', 'm4a', 'md', 'ogg', 'png', 'txt', 'webm', 'webp'])
        runs = {ext: kind for ext, kind in kinds.items() if kind and (kind.startswith('text/') and kind not in ('text/plain', 'text/markdown') or 'xml' in kind or 'script' in kind or 'html' in kind)}
        self.assertEqual(runs, {})
        self.assertEqual((kinds['html.txt'], kinds['txt'], kinds['gif']), ('text/plain', 'text/plain', 'image/gif'))

    def test_held_an_agents_page_is_stored_as_text_under_a_name_the_tool_chose(self):
        self.new()
        folder = self.root / 'agent'
        folder.mkdir()
        (folder / 'evil.HTML').write_text('<script>alert(document.domain)</script>')
        (folder / 'latin.html').write_bytes('<p>caf\xe9</p>'.encode('latin-1'))
        (folder / 'utf16.html').write_bytes('<p>x</p>'.encode('utf-16'))
        (folder / 'blank.html').write_text(' \n\u200b')
        (folder / 'big.html').write_text('<p>' + 'x' * 500_000 + '</p>')
        (folder / 'edge.html').write_text('x' * 500_000)
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה דף', '--html', str(folder / 'evil.HTML'))
        m = self.thread()['messages'][0]
        self.assertEqual(m['html'], {'file': 'uploads/topic/m1.html.txt', 'name': 'evil.HTML', 'bytes': 39})
        self.assertEqual(self.files_of(), ['uploads/topic/m1.html.txt'])
        self.assertEqual(mimetypes.guess_type('uploads/topic/m1.html.txt')[0], 'text/plain')      # what the board server answers with
        before = self.box.files()
        for args in (['--from', 'owner', 'x', '--html', str(folder / 'evil.HTML')], ['--from', 'tower', 'x', '--html', str(folder / 'latin.html')],
                     ['--from', 'tower', 'x', '--html', str(folder / 'utf16.html')], ['--from', 'tower', 'x', '--html', str(folder / 'blank.html')],
                     ['--from', 'tower', 'x', '--html', str(folder / 'big.html')], ['--from', 'tower', 'x', '--html', str(folder / 'missing.html')],
                     ['--from', 'tower', 'x', '--html', str(folder)], ['--from', 'tower', '', '--html', str(folder / 'evil.HTML')]):
            with self.subTest(args=str(args)[-50:]):
                self.run_cli('say', 'topic', *args, ok=False)
        self.assertEqual(self.box.files(), before)
        self.run_cli('say', 'topic', '--from', 'fork', 'בדיוק בגבול', '--html', str(folder / 'edge.html'))
        self.assertEqual(self.thread()['messages'][1]['html']['bytes'], 500_000)
        # a page cannot make one: whatever it sends beside a reply, no message of his carries a page
        self.reply('שלום', html={'file': 'uploads/topic/m1.html.txt', 'name': 'x', 'bytes': 1}, page={'raw': '<script>'})
        self.assertNotIn('html', self.thread()['messages'][2])

    def test_the_limit_of_an_agents_page_is_checked_on_what_is_stored(self):
        """The limit is read from the size the file system reports and the file is then read twice: for anything
        that is not a plain file (a pipe, a FIFO, a file still being written) the page that is stored was never measured."""
        self.new()
        fifo = self.root / 'page.fifo'
        os.mkfifo(fifo)

        def feed():
            for part in (b'<p>' + b'x' * 600_000 + b'</p>', b'<p>short</p>'):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                    except OSError:                 # nobody reads (yet, or any more)
                        time.sleep(0.05)
                        continue
                    os.set_blocking(fd, True)
                    try:
                        with os.fdopen(fd, 'wb') as f:
                            f.write(part)
                    except OSError:                 # the reader went away
                        return
                    time.sleep(0.5)
                    break

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        r = self.box.cli('say', 'topic', '--from', 'tower', 'ראה דף', '--html', str(fifo), timeout=40)
        writer.join(15)
        self.assertNotIn('Traceback', r.stderr)
        pages = [m['html']['bytes'] for m in self.thread()['messages'] if 'html' in m]
        self.assertEqual([size for size in pages if size > 500_000], [], 'a page over the limit was stored')

    # ════════════════════════════════════════════════════════════════════════
    # A VOICE MESSAGE
    # ════════════════════════════════════════════════════════════════════════

    def test_held_a_recording_is_judged_by_its_bytes_and_its_numbers(self):
        self.new()
        env = self.ear()
        webm = b64(b'\x1a\x45\xdf\xa3' + b'opus' * 30)
        raw = lambda seconds: '{"op": "reply", "thread": "topic", "cid": "raw", "text": "", "voice": {"data": "%s", "seconds": %s}}' % (webm, seconds)
        for seconds in ('NaN', 'Infinity', '-Infinity', '1e999', '-1', '0', '-0.0', '900.01', 'true', '"3"', 'null', '[3]', '1' + '0' * 400):
            with self.subTest(seconds=seconds[:12]):
                self.refused(raw(seconds), env=env)
        for voice in ({'data': webm}, {'seconds': 3}, {'data': 5, 'seconds': 3}, {'data': 'x!', 'seconds': 3}, {'data': webm + '\n', 'seconds': 3}, {'data': '', 'seconds': 3},
                      {'data': b64(b'RIFF\x24\0\0\0WAVEfmt '), 'seconds': 3}, {'data': b64(b'ID3\x04' + bytes(40)), 'seconds': 3}, {'data': b64(png()), 'seconds': 3},
                      {'data': b64(b'<html>'), 'seconds': 3}, {'data': b64(b'\x1a\x45\xdf'), 'seconds': 3}, {'data': b64(b'OggS' + bytes(3_000_000)), 'seconds': 3},
                      'x', None, [], 5):
            with self.subTest(voice=str(voice)[:50]):
                self.refused({'op': 'reply', 'thread': 'topic', 'cid': self.cid(), 'text': '', 'voice': voice}, env=env)
        # beside anything else a reply can carry, a recording is refused
        for extra in ({'images': [{'data': b64(gif())}]}, {'snippet': {'text': 'קטע'}}, {'answer': {}, 'q': 'm1'}, {'run': {}}):
            with self.subTest(extra=str(extra)[:40]):
                self.refused({'op': 'reply', 'thread': 'topic', 'cid': self.cid(), 'text': '', 'voice': {'data': webm, 'seconds': 3}, **extra}, env=env)
        self.assertEqual((self.files_of(), self.heard()), ([], []))
        # the kind is what the bytes say, whatever the page claims, and the file is named by the tool
        for n, (data, ext) in enumerate(((b'\x1a\x45\xdf\xa3<html>', 'webm'), (b'\0\0\0\x18ftypM4A ' + bytes(20), 'm4a'), (b'OggS' + bytes(20), 'ogg')), 1):
            self.reply(voice={'data': b64(data), 'seconds': 900, 'type': 'text/html', 'file': '../../x.html', 'name': 'x.html', 'ext': 'html'}, env=env)
            self.settled()
            self.assertEqual(self.state()['threads']['topic']['messages'][-1]['voice']['file'], f'uploads/topic/m{n}.{ext}')
        self.assertEqual(self.files_of(), ['uploads/topic/m1.webm', 'uploads/topic/m2.m4a', 'uploads/topic/m3.ogg'])
        self.assertEqual(self.heard(), [str((self.board / p).resolve()) for p in self.files_of()])
        self.mailed(3)
        # a board with no stand-in (and it is not the real board) takes no recording at all
        self.refused({'op': 'reply', 'thread': 'topic', 'cid': self.cid(), 'text': '', 'voice': {'data': webm, 'seconds': 3}})

    def test_a_recording_never_swallows_words_he_typed(self):
        """A recording is "sent alone": pictures, a snippet, ticks and a run request beside it are refused, but
        not the text of the reply. A short text is silently replaced; a long one becomes a snippet beside the
        recording, and `threads pending` then gives the tower that text in place of the transcript."""
        self.new()
        env = self.ear(EAR_WORDS='המילים שנאמרו')
        webm = {'data': b64(b'\x1a\x45\xdf\xa3' + b'opus' * 30), 'seconds': 3}
        for name, typed in (('a short text', 'המילים שהקלדתי ביד'), ('a long text', 'הקלדתי ' * 700)):
            with self.subTest(case=name):
                answer = self.reply(typed, ok=None, env=env, voice=webm)
                if not answer['ok']:
                    continue                        # refused like every other companion of a recording: nothing is lost
                self.settled()
                m = self.state()['threads']['topic']['messages'][-1]
                row = next(r for r in json.loads(self.run_cli('pending', env=env).stdout) if r['msg_id'] == m['id'])
                self.assertNotIn('snippet', m, 'a recording was stored with a snippet beside it')
                self.assertIn('המילים שנאמרו', row['text'], 'the tower is not given the transcript')
                self.assertIn(typed.strip()[:18], json.dumps(m, ensure_ascii=False), 'the words he typed are gone and the page was told ok')

    def test_recordings_in_the_air_are_bounded(self):
        """Every recording a page sends is answered at once and starts a process of its own, which uploads it to the
        service with his key. Nothing counts them: N posts are N workers and N uploads at the same time."""
        self.new()
        env = self.ear(EAR_SLEEP='3')
        sent = [self.reply(ok=None, env=env, voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 900})['ok'] for _ in range(10)]
        done = self.root / 'ear.log.done'
        at_once = len(self.heard()) - (len(done.read_text().splitlines()) if done.exists() else 0)       # inside the service right now
        self.wait_for(lambda: all(m.get('status') != 'transcribing' for m in self.state()['threads']['topic']['messages']), 'a recording was never settled', seconds=90)
        self.mailed(sum(sent))
        self.assertLessEqual(at_once, 5, f'{sum(sent)} of 10 recordings were taken and {at_once} of them were at the service at the same moment')

    def test_held_a_failed_transcript_tells_nothing_of_the_machine(self):
        self.new()
        env = self.ear(EAR_FAIL='1', EAR_STDERR='Authorization: Bearer sk-SECRET-KEY at /Users/someone/.soniox')
        self.reply(voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 2}, env=env)
        self.settled()
        m = self.state()['threads']['topic']['messages'][0]
        self.assertEqual((m['status'], m['voice']['state'], m['voice']['error'], m['placeholder']), ('pending', 'failed', 'CalledProcessError', True))
        self.wait_for(lambda: self.box.mails(), 'the tower was not told')
        everything = b''.join(v for v in self.box.files().values() if isinstance(v, bytes)) + '\n'.join(self.box.mails()).encode()
        self.assertFalse(any(word in everything for word in (b'sk-SECRET', b'Bearer', b'/Users/someone', b'ear.py')))
        row = json.loads(self.run_cli('pending', env=env).stdout)[0]
        self.assertEqual(row['voice'], {'path': str((self.board / 'uploads/topic/m1.ogg').resolve()), 'seconds': 2.0, 'state': 'failed', 'error': 'CalledProcessError'})

    def test_held_the_worker_reads_no_file_outside_the_folder_of_the_thread(self):
        self.new()
        self.new('other')
        env = self.ear()
        self.reply(tid='other', voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 2}, env=env)
        self.settled('other')
        outside = self.root / 'outside.webm'
        outside.write_bytes(b'\x1a\x45\xdf\xa3')
        (self.board / 'uploads/topic').mkdir(parents=True)
        os.symlink(outside, self.board / 'uploads/topic/m1.webm')
        (self.root / 'ear.log').unlink()
        base = self.state()
        for file in ('../../../outside.webm', str(outside), 'uploads/other/m1.ogg', 'uploads/topic/m1.webm', 'uploads/topic/../other/m1.ogg', 'uploads/topic', '', 5, None):
            with self.subTest(file=str(file)[-40:]):
                data = json.loads(json.dumps(base))
                data['threads']['topic'].update(next=2, voicing=['m1'], messages=[{
                    'id': 'm1', 'from': 'owner', 'text': 'הקלטה קולית', 'ts': self.T0, 'status': 'transcribing', 'placeholder': True, 'cid': 'v1',
                    'voice': {'file': file, 'bytes': 4, 'seconds': 2, 'state': 'transcribing', 'started': self.T0, 'tries': 1}}])
                self.put_state(data)
                r = self.box.cli('transcribe', 'topic', 'm1', env=env)
                self.assertNotIn('Traceback', r.stderr)
                self.assertEqual(self.heard(), [], 'the worker handed a file that is not in the thread to the service')

    def test_the_worker_transcribes_only_the_recording_of_its_own_message(self):
        """Hand-edited state only. The worker checks that `voice.file` is inside the thread's folder and nothing
        else; and it looks for the file before the state has been checked at all."""
        self.new()
        self.new('other')
        env = self.ear()
        self.reply(voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 2}, env=env)           # topic m1: settled
        self.reply(tid='other', voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 2}, env=env)
        self.settled()
        self.settled('other')
        (self.root / 'ear.log').unlink()
        base = self.state()
        stuck = {'id': 'm2', 'from': 'owner', 'text': 'הקלטה קולית', 'ts': self.T0, 'status': 'transcribing', 'placeholder': True, 'cid': 'v2'}
        with self.subTest(case='the recording of another message of the thread'):
            data = json.loads(json.dumps(base))
            data['threads']['topic']['messages'].append(dict(stuck, voice={'file': 'uploads/topic/m1.ogg', 'bytes': 44, 'seconds': 2, 'state': 'transcribing', 'started': self.T0, 'tries': 1}))
            data['threads']['topic'].update(next=3, voicing=['m2'])
            self.put_state(data)
            self.box.cli('transcribe', 'topic', 'm2', env=env)
            self.assertEqual(self.heard(), [], 'a recording was transcribed into a message it does not belong to')
        (self.root / 'ear.log').unlink(missing_ok=True)
        with self.subTest(case='a record whose id is not its key: a state every command refuses'):
            data = json.loads(json.dumps(base))
            data['threads']['topic']['messages'].append(dict(stuck, voice={'file': 'uploads/other/m1.ogg', 'bytes': 44, 'seconds': 2, 'state': 'transcribing', 'started': self.T0, 'tries': 1}))
            data['threads']['topic'].update(next=3, voicing=['m2'], id='other')
            self.put_state(data)
            self.run_cli('list', ok=False, env=env)
            self.box.cli('transcribe', 'topic', 'm2', env=env)
            self.assertEqual(self.heard(), [], "another thread's recording went to the service out of a state file nothing else would read")

    def test_held_many_workers_settle_a_recording_once(self):
        self.new()
        slow, fast = self.ear(EAR_SLEEP='1.5'), self.ear(EAR_SLEEP='0.3')
        self.reply(voice={'data': b64(b'OggS' + bytes(40)), 'seconds': 2}, env=slow)          # its own worker is slow
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            done = list(pool.map(lambda _: self.box.cli('transcribe', 'topic', 'm1', env=fast), range(3)))
        self.assertEqual([(r.returncode, r.stdout, r.stderr) for r in done], [(0, '', '')] * 3)
        self.wait_for(lambda: len(self.heard()) == 4, 'the first worker never started')
        time.sleep(2.2)                             # ...and it finds the message settled
        m = self.state()['threads']['topic']['messages'][0]
        self.assertEqual((m['status'], m['text'], m['voice']['state'], 'voicing' in self.state()['threads']['topic']), ('pending', 'מילים מההקלטה', 'done', False))
        self.assertEqual(len([mail for mail in self.box.mails() if 'reply in topic (m1)' in mail]), 1)
        before = self.box.files()
        for mid in ('m1', 'm9'):                    # a message that is settled, a message that is not there
            self.run_cli('transcribe', 'topic', mid, env=fast)
        self.assertEqual((self.box.files(), len(self.heard())), (before, 4))
        self.run_cli('say', 'topic', '--from', 'tower', 'הודעה בלי הקלטה', env=fast)
        before = self.box.files()
        self.run_cli('transcribe', 'topic', 'm2', env=fast)
        self.run_cli('transcribe', 'nowhere', 'm1', env=fast)
        self.assertEqual((self.box.files(), len(self.heard())), (before, 4))

    def test_a_board_that_is_not_the_real_one_never_calls_the_real_service(self):
        """`voice_of` takes a recording only on the real board or with a stand-in; the worker has no such rule.
        A recording left in the air on any other board (a copy of the real state, a test whose later commands run
        without the stand-in) is retried by whatever command runs 15 minutes later: that worker reads ~/.soniox
        and uploads the file. Here HOME is a folder of this test and the two functions that reach the network
        are replaced, so nothing leaves the machine."""
        self.new()
        (self.board / 'uploads/topic').mkdir(parents=True)
        (self.board / 'uploads/topic/m1.webm').write_bytes(b'\x1a\x45\xdf\xa3' + b'opus' * 30)
        data = self.state()
        data['threads']['topic'].update(next=2, voicing=['m1'], messages=[{
            'id': 'm1', 'from': 'owner', 'text': 'הקלטה קולית', 'ts': self.T0, 'status': 'transcribing', 'placeholder': True, 'cid': 'v1',
            'voice': {'file': 'uploads/topic/m1.webm', 'bytes': 124, 'seconds': 2, 'state': 'transcribing', 'started': self.T0, 'tries': 1}}])
        self.put_state(data)
        home = self.root / 'home'
        home.mkdir()
        (home / '.soniox').write_text('SONIOX_API_KEY="a-key-of-this-test-only"\n')
        env = dict(self.at(0.3), HOME=str(home), THREADS_BOARDLIB_DIR=BOARDLIB)
        self.assertNotIn('THREADS_SONIOX_CMD', env)
        report = self.driver(r'''
calls, spawned = [], []

def service(method, path, key, body=None, headers=None):
    calls.append({'method': method, 'path': path, 'with_a_key': bool(key), 'bytes': len(body or b'')})
    raise OSError('Soniox answered 599')

def network(*args, **kwargs):
    calls.append({'method': 'urlopen'})
    raise OSError('no network in a test')

T.soniox, T.urllib.request.urlopen, real = service, network, T.subprocess.Popen

def popen(args, *more, **kwargs):
    if list(args[2:3]) == ['transcribe']:           # the worker main() starts: run here instead, where nothing can leave
        spawned.append(list(args[3:]))
        return None
    return real(args, *more, **kwargs)

T.subprocess.Popen = popen
sys.argv = ['threads.py', 'list']                   # any command at all, a quarter of an hour later
code = T.main()
for tid, mid in spawned:
    T.transcribe(tid, mid)
print(json.dumps({'exit': code, 'spawned': spawned, 'calls': calls, 'ready': T.voice_ready()}))
''', env)
        self.assertEqual((report['exit'], report['ready']), (0, False))
        self.assertEqual(report['calls'], [], f"a board that takes no recordings sent one to the service (workers started: {report['spawned']})")

    # ════════════════════════════════════════════════════════════════════════
    # A NEW TOPIC FROM THE PAGE
    # ════════════════════════════════════════════════════════════════════════

    def test_a_new_topic_always_has_a_title_he_can_see(self):
        """Without a title the first words of the message stand in, after the markdown marks are dropped:
        a message that is only marks leaves nothing, and the thread is created with an empty title."""
        for text in ('**', '``', '```', '```js', '`\u200b`', '** `` **'):
            with self.subTest(text=text):
                answer = self.topic(ok=None, text=text)
                if answer['ok']:
                    title = self.state()['threads'][answer['thread']]['title']
                    self.assertTrue(any(unicodedata.category(ch)[0] not in 'CZ' for ch in title), f'the topic {answer["thread"]} was opened with the title {title!r}')

    def test_a_new_topic_does_not_swallow_what_it_cannot_carry(self):
        """Pictures, a recording or a file sent with a new topic are dropped without a word, and the page is told ok."""
        for name, extra in (('pictures', {'images': [{'data': b64(gif()), 'caption': 'כיתוב'}]}), ('a snippet', {'snippet': {'text': 'לוג ארוך', 'name': 'a.log'}}),
                            ('a recording', {'voice': {'data': b64(b'OggS' + bytes(40)), 'seconds': 2}})):
            with self.subTest(carries=name):
                answer = self.topic(ok=None, env=self.ear(), title='נושא עם ' + name, text='ראה מצורף', **extra)
                if answer['ok']:
                    self.settled(answer['thread'])
                    m = self.state()['threads'][answer['thread']]['messages'][0]
                    self.assertTrue(any(k in m for k in ('images', 'snippet', 'voice')), f'{name}: gone, and the answer was {answer}')

    def test_held_ids_made_from_hostile_titles_are_plain_folder_names(self):
        self.new()
        self.run_cli('new', 'topic-2', 'עוד אחד')
        titles = ['topic', 'topic 2', 'a' * 120, 'מילה ' * 20, '!!!???', '\u202e\u200f\u2066 x', 'שלום עולם', 'Ünïcödé Ｆｕｌｌ ①②③ ℋ', '../../etc/passwd',
                  'CON', 'con.', 'tower', '_new', '__proto__', '12345', '7', 'uploads', '-rf --yes', 'a.b.c', '.', '..', 'İstanbul ß ǅ', '🙂🙂🙂', 'x\x00y\x1b[2J',
                  't 1', 't-1', 'T 2', '-- -- --', 'ab', 'abc', 'a b', 'ﬁ ﬂ ﬃ', '٣٤٥ ௧௨௩', '%2e%2e%2f', 'a/b\\c', 'x' * 27 + ' y', 'x' * 28, 'נושא\u05bcמנוקד', 'q' * 26 + ' 2']
        made = []
        for title in titles:
            with self.subTest(title=title[:30]):
                answer = self.topic(title=title, text='הודעה ראשונה')
                made.append(answer['thread'])
                self.assertRegex(answer['thread'], f'^{ID}$')
                self.assertFalse(answer['dup'])
        self.assertEqual(len(set(made)), len(made), 'two topics were given one id')
        self.assertTrue(set(made).isdisjoint({'topic', 'topic-2'}))
        self.assertEqual(sorted(self.state()['threads']), sorted(made + ['topic', 'topic-2']))
        self.run_cli('list')
        # each has its own folder, directly under uploads/
        for tid in made[:6]:
            self.reply(tid=tid, images=[{'data': b64(gif())}])
        self.assertEqual(self.files_of(), sorted(f'uploads/{tid}/m2-1.gif' for tid in made[:6]))

    def test_held_the_id_of_a_removed_thread_is_never_given_again(self):
        first = self.topic(title='alpha beta', text='ראשון')
        self.assertEqual(first['thread'], 'alpha-beta')
        self.reply(tid='alpha-beta', images=[{'data': b64(gif())}], snippet={'text': 'קטע'})
        self.run_cli('rm', 'alpha-beta', '--yes')
        self.assertEqual(self.files_of(), [])
        self.run_cli('new', 'gamma', 'גמא')
        self.run_cli('rm', 'gamma', '--yes')
        self.assertEqual([self.topic(title=title, text='שני')['thread'] for title in ('Alpha Beta', 'alpha, beta!', 'gamma')], ['alpha-beta-2', 'alpha-beta-3', 'gamma-2'])
        # an answer kept by a page for the removed thread lands nowhere
        self.refused({'op': 'reply', 'thread': 'alpha-beta', 'text': 'תשובה ישנה', 'cid': 'old', 'images': [{'data': b64(gif())}]})

    def test_held_one_post_sent_many_times_at_once_opens_one_topic(self):
        post = json.dumps({'op': 'new', 'title': 'נושא אחד', 'text': 'ב' * 4500, 'cid': 'same-cid', 'context': 'רקע'})
        script = r'''
try:
    answer = T.opened(json.load(sys.stdin), T.now())
except ValueError as exc:
    answer = {'ok': False, 'error': str(exc), **getattr(exc, 'extra', {})}
print(json.dumps(answer))
'''
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            answers = list(pool.map(lambda _: self.driver(script, self.env, input=post), range(8)))
        self.assertEqual([a['ok'] for a in answers], [True] * 8, answers)
        self.assertEqual(({a['thread'] for a in answers}, sorted(a['dup'] for a in answers)), ({'nvsha-achd'}, [False] + [True] * 7))
        self.assertEqual((list(self.state()['threads']), self.files_of()), (['nvsha-achd'], ['snippets/nvsha-achd/m1.txt']))
        self.assertEqual(len([m for m in self.box.mails() if 'NEW topic' in m]), 1)
        # the same title under another cid: the open topic is named, nothing is made
        answer = self.refused({'op': 'new', 'title': 'נושא  אחד', 'text': 'שוב', 'cid': 'other-cid'})
        self.assertEqual(answer.get('thread'), 'nvsha-achd')

    def test_held_sixty_open_topics_are_the_most_a_page_can_open(self):
        self.new('seed')
        data = self.state()
        for n in range(2, 61):
            data['threads'][f'bulk-{n}'] = dict(json.loads(json.dumps(data['threads']['seed'])), id=f'bulk-{n}', title=f'נושא {n}', slot=n)
        self.put_state(data)
        self.run_cli('list')
        self.refused({'op': 'new', 'title': 'אחד יותר מדי', 'text': 'ב' * 4500, 'cid': 'over'})
        self.assertEqual(len(self.state()['threads']), 60)
        self.post({'op': 'close', 'thread': 'bulk-60', 'last': ''})
        self.assertFalse(self.topic(title='עכשיו יש מקום', text='x')['dup'])
        self.assertEqual(sum(t['status'] == 'open' for t in self.state()['threads'].values()), 60)
        self.refused({'op': 'new', 'title': 'ושוב אין', 'text': 'x', 'cid': 'over-2'})

    def test_held_what_a_new_topic_carries_is_checked_before_anything_is_made(self):
        ok = {'title': 'נושא', 'text': 'הודעה'}
        link = {'label': 'קישור', 'url': 'https://a.example/x'}
        for extra in ({'links': [link] * 9}, {'links': 'x'}, {'links': [5]}, {'links': [{'label': '', 'url': 'https://a.example'}]}, {'links': [{'label': 'x' * 41, 'url': 'https://a.example'}]},
                      {'links': [{'label': 'x'}]}, {'links': [{'label': 'x', 'url': 5}]}, {'links': [{'label': 'x', 'url': 'javascript:alert(1)'}]},
                      {'links': [{'label': 'x', 'url': '  JaVaScRiPt:alert(1)'}]}, {'links': [{'label': 'x', 'url': 'data:text/html,<script>alert(1)</script>'}]},
                      {'links': [{'label': 'x', 'url': '//evil.example/x'}]}, {'links': [{'label': 'x', 'url': '/\\evil.example'}]}, {'links': [{'label': 'x', 'url': '\\\\evil.example'}]},
                      {'links': [{'label': 'x', 'url': 'java\nscript:alert(1)'}]}, {'links': [{'label': 'x', 'url': 'vbscript:x'}]}, {'links': [{'label': 'x', 'url': 'https://a.example/' + 'x' * 500}]},
                      {'links': [{'label': 'x', 'url': 'file:///etc/passwd'}]}, {'links': [{'label': 'x', 'url': 'https:evil.example'}]},
                      {'context': 'x' * 20_001}, {'context': 5}, {'context': None}, {'context': 'x\ud800'}, {'text': 'x' * 8001}, {'text': 5}, {'text': None}, {'text': 'x\udfff'},
                      {'title': 'x' * 121}, {'title': 5}, {'title': None}, {'title': ['x']}, {'title': 'x\ud800'}, {'title': '', 'text': ''}, {'title': ' \u200b', 'text': '\n'},
                      {'cid': ''}, {'cid': '   '}, {'cid': 'x' * 81}, {'cid': 5}, {'cid': None}, {'cid': 'x\ud800'}):
            with self.subTest(extra=str(extra)[:60]):
                self.refused({'op': 'new', 'cid': self.cid(), **ok, **extra})
        self.assertFalse((self.board / 'state.json').exists())
        answer = self.topic(title='  נושא   עם\nקישורים ', text='', context='רקע\n' * 5000, links=[dict(link, label=f'קישור {n}') for n in range(8)])
        t = self.state()['threads'][answer['thread']]
        self.assertEqual((t['title'], t['messages'][0]['text'], len(t['links']), len(t['context']), t['opened_by'], 'title_pending' in t),
                         ('נושא עם קישורים', 'נושא עם קישורים', 8, 20_000, 'owner', False))

    def test_held_a_cid_names_one_message_in_one_place(self):
        self.new()
        self.reply('תשובה רגילה', cid='shared')                                              # cid() is overridden below
        first = self.post({'op': 'new', 'title': 'נושא א', 'text': 'x', 'cid': 'shared'})
        self.assertEqual((first['thread'], first['dup']), ('nvsha-a', False))                # a reply elsewhere with this cid is no topic
        again = self.post({'op': 'new', 'title': 'כותרת אחרת לגמרי', 'text': 'y', 'cid': 'shared'})
        self.assertEqual((again['thread'], again['dup'], again['msg_id']), ('nvsha-a', True, 'm1'))
        self.assertEqual(sorted(self.state()['threads']), ['nvsha-a', 'topic'])
        other = self.post({'op': 'new', 'title': 'נושא ב', 'text': 'x', 'cid': 'second'})
        got = self.post({'op': 'reply', 'thread': other['thread'], 'text': 'תשובה בנושא ב', 'cid': 'shared'})
        self.assertEqual((got['dup'], got['msg_id']), (False, 'm2'))                         # the opener of ANOTHER topic does not shadow it
        self.assertEqual([m['text'] for m in self.state()['threads'][other['thread']]['messages']], ['x', 'תשובה בנושא ב'])
        # removed and sent again: a new topic, under a new id
        self.run_cli('rm', 'nvsha-a', '--yes')
        back = self.post({'op': 'new', 'title': 'נושא א', 'text': 'x', 'cid': 'shared'})
        self.assertEqual((back['thread'], back['dup']), ('nvsha-a-2', False))

    # ════════════════════════════════════════════════════════════════════════
    # SNIPPETS, AFTER THE CHANGE
    # ════════════════════════════════════════════════════════════════════════

    def test_held_a_snippet_keeps_every_byte(self):
        self.new()
        text = '\ufeffשורה א\r\nשורה ב\rשורה ג\n\n\tטאב\u2028מפריד\x0c\x00סוף בלי שורה חדשה'
        self.reply('ראה', snippet={'text': text, 'name': 'win.LOG'})
        long = ('שורה ארוכה\r\n' * 600)[:6000]
        self.reply(long)
        source = self.root / 'crlf.md'
        source.write_bytes(text.encode('utf-8') + b'\r\n')
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--snippet', str(source))
        self.run_cli('say', 'topic', '--from', 'fork', 'א\r\n' * 20_000)
        files = {'snippets/topic/m1.log': text, 'snippets/topic/m2.txt': long, 'snippets/topic/m3.md': text + '\r\n', 'snippets/topic/m4.txt': 'א\r\n' * 20_000}
        self.assertEqual(self.files_of(), sorted(files))
        for name, expected in files.items():
            self.assertEqual((self.board / name).read_bytes(), expected.encode('utf-8'), name)
        for mid, expected in (('m1', text + '\n'), ('m2', long), ('m3', text + '\r\n'), ('m4', 'א\r\n' * 20_000)):
            self.assertEqual(self.box.cli('snippet', 'topic', mid, text=False).stdout, expected.encode('utf-8'), mid)
        rows = {row['msg_id']: row for row in json.loads(self.run_cli('pending').stdout)}
        self.assertEqual((rows['m2']['text'], rows['m2']['snippet']['chars'], rows['m1']['text'], rows['m1']['snippet']['bytes']), (long, 6000, 'ראה', len(text.encode('utf-8'))))
        m = self.thread()['messages']
        self.assertEqual([(x['snippet']['bytes'], x['snippet']['chars']) for x in m], [(len(v.encode('utf-8')), len(v)) for v in files.values()])
        # a new topic with a long first message keeps it the same way
        answer = self.topic(text=long)
        self.assertEqual((self.board / f"snippets/{answer['thread']}/m1.txt").read_bytes(), long.encode('utf-8'))
        self.assertEqual(json.loads(self.run_cli('pending').stdout)[-1]['text'], long)

    def test_held_a_snippet_file_is_named_by_the_tool_and_refused_whole(self):
        self.new()
        for n, (name, on_disk, label) in enumerate((('a.HTML', 'm1.txt', 'a.HTML'), ('../../x.md', 'm2.md', 'x.md'), ('.log', 'm3.txt', '.log'), ('x.svg.LOG', 'm4.log', 'x.svg.LOG'),
                                                    ('C:\\dir\\y.txt\x00', 'm5.txt', 'y.txt'), ('z.php\u202e', 'm6.txt', 'z.php'), (None, 'm7.txt', None)), 1):
            self.reply('ראה', snippet={'text': '<script>alert(1)</script>', **({'name': name} if name is not None else {})})
            record = self.thread()['messages'][-1]['snippet']
            self.assertEqual((record['file'], record['name']), (f'snippets/topic/{on_disk}', label))
        self.assertEqual({mimetypes.guess_type(p)[0] for p in self.files_of()} & {'text/html', 'image/svg+xml', 'application/xhtml+xml'}, set())
        binary = self.root / 'bin.txt'
        binary.write_bytes(b'\xff\xfe\x00not text')
        before = self.box.files()
        for snippet in ({'text': ''}, {'text': ' \n\u200b'}, {'text': 5}, {'text': 'x', 'name': 5}, {'text': 'x\ud800'}, {'text': 'א' * 10_000_001}, 'x', None, []):
            self.refused({'op': 'reply', 'thread': 'topic', 'text': 'ראה', 'cid': self.cid(), 'snippet': snippet})
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--snippet', str(binary), ok=False)
        self.run_cli('say', 'topic', '--from', 'tower', 'ראה', '--snippet', str(self.root / 'missing.txt'), ok=False)
        self.assertEqual(self.box.files(), before)


if __name__ == '__main__':
    unittest.main()
