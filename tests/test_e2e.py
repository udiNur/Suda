#!/usr/bin/env python3
"""End to end: Suda (suda.html) in a headless browser, the real board server, the CLI behind its hook.

What runs here is what runs on the Mac: answer_server.py from the html-interview-board skill, on 127.0.0.1
and a free port, over a temp BOARDS_DIR; `threads install` publishes the page into it; the page posts to
/api/state, the server runs on-state.sh, and that runs `threads.py ingest`. agent-browser drives headless
Chrome at the cover (360x840), inner (750x835) and desktop sizes of his phone and his Mac.

The scenarios of features whose server side has not landed are SKIPPED until state.ops lists their op
('new', 'images', 'run', 'voice'); they run by themselves once it does, with no change here. Without
agent-browser or a browser the whole file skips. Nothing here binds beyond loopback.

Contracts (worker-a to worker-c, tuios mails 2257, 2291, 2329, 2352):
  new:    {op:'new', text, title, cid, title_pending?:true, context?, links?} -> {ok, thread, msg:'m1'}; the thread
          keeps title_pending until the first `threads rename`.
  images: reply {..., images:[{name,type,data,caption?}]} -> message.images[{file,name,bytes,w,h,caption?}];
          `threads pending` rows carry each image's absolute path and caption.
  run:    reply {text:'▶ הרץ את הפקודה מהודעה mN', run:{msg_id, block_index, sha256}}; accepted only for a
          runnable block of a tower message with a matching hash; the pending row carries
          run{msg_id, block_index, sha256, command} with the command taken from the stored tower message.
  voice:  reply {text:'', voice:{type, data, seconds}} -> message.voice{file, bytes, seconds, state}; the audio
          sits under uploads/<thread>/; the message is pending only once the transcript (or a failure) is in.
          The words come from THREADS_SONIOX_CMD when it is set (a command given the audio path, printing the
          words): the harness sets it to its own stand-in, so no test ever reads the real key.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import hashlib
import http.client
import importlib
import importlib.util
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
import threading
import time
import unittest
import zlib

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
SKILL = Path(os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board')))
AB = shutil.which('agent-browser')
SLUG = 'e2e-suda'
TZ = 'Asia/Jerusalem'
SIZES = (('cover', 360, 840), ('inner', 750, 835), ('desktop', 1280, 800))
# Headless Chrome answers getUserMedia with a fake microphone, so the record button can be pressed.
CHROME_ARGS = '--use-fake-ui-for-media-stream,--use-fake-device-for-media-stream,--autoplay-policy=no-user-gesture-required'
RECORDER = ("import json, os, sys\nfrom pathlib import Path\n"
            "with Path(os.environ['NOTIFY_RECORD']).open('a') as f:\n f.write(json.dumps({'args': sys.argv[1:]}) + '\\n')\n")
TRANSCRIPT = 'שלום, זו הודעה קולית לבדיקה מקצה לקצה'
# Stands in for Soniox: given the audio path, prints the words; refuses an empty or missing file like a failed upload would.
HEARER = ("import os, sys, time\npath = sys.argv[1] if len(sys.argv) > 1 else ''\ntime.sleep(2)\n"
          "sys.exit('no audio at ' + repr(path)) if not (path and os.path.isfile(path) and os.path.getsize(path) > 0) else print(%r)\n" % TRANSCRIPT)


def png(w, h, shade=0):
    """A small valid PNG, so the page's picture path runs on real image bytes."""
    rows = []
    for y in range(h):
        row = bytearray(b'\x00')
        for x in range(w):
            row += bytes([(x * 255 // max(w - 1, 1)), (120 + shade) & 255, (y * 255 // max(h - 1, 1))])
        rows.append(bytes(row))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def fenced_blocks(text):
    """The run rule of mail 2352, as the server must apply it: every fenced block, numbered from 0."""
    blocks, cur = [], None
    for line in text.split('\n'):
        if re.match(r'\s*```', line):
            if cur is None:
                cur = []
            else:
                blocks.append(cur)
                cur = None
            continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        blocks.append(cur)
    return blocks


def command_of(text, index):
    lines = [l.strip() for l in fenced_blocks(text)[index] if l.strip()]
    return '\n'.join(lines)


class Browser:
    """One agent-browser session: headless Chrome, driven by the CLI."""

    def __init__(self, name):
        self.name = name

    def run(self, *args, stdin=None, timeout=90, check=True):
        r = subprocess.run([AB, '--session', self.name, *args], input=stdin, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            raise RuntimeError('agent-browser ' + ' '.join(args[:2]) + ': ' + (r.stderr or r.stdout).strip()[-600:])
        return r

    def launch(self):
        self.run('--args', CHROME_ARGS, 'open', 'about:blank', timeout=120)

    def close(self):
        try:
            self.run('close', timeout=60, check=False)
        except Exception:
            pass

    def viewport(self, w, h):
        self.run('set', 'viewport', str(w), str(h))

    def open(self, url):
        self.run('open', url)

    def upload(self, selector, *files):
        self.run('upload', selector, *[str(f) for f in files])

    def eval(self, js):
        """Run `js` (an expression, or an async IIFE) and give back its JSON-decoded value: the script must end in a
        JSON.stringify'd value (or a plain string / number)."""
        r = self.run('eval', '--json', '--stdin', stdin=js)
        out = json.loads(r.stdout)
        if not out.get('success'):
            raise RuntimeError(str(out.get('error'))[:600])
        value = out['data'].get('result')
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    def wait(self, js, timeout=15, what='the page'):
        """Poll an expression until it is truthy; give it back."""
        end = time.monotonic() + timeout
        while True:
            value = self.eval(js)
            if value:
                return value
            if time.monotonic() > end:
                seen = ' '.join(str(self.eval('JSON.stringify(document.body.innerText)')).split())[:400]
                raise AssertionError('waited %ss for %s: %s\nthe page says: %s' % (timeout, what, js.strip()[:160], seen))
            time.sleep(0.25)

    def text(self):
        return self.eval('JSON.stringify(document.body.innerText)')

    def visible(self, selector):
        return bool(self.eval('JSON.stringify(!!(document.querySelector(%s)||{}).offsetParent)' % json.dumps(selector)))

    def click(self, selector):
        self.eval('(()=>{const el=document.querySelector(%s);if(!el)throw Error("no "+%s);el.click();return "ok";})()'
                  % (json.dumps(selector), json.dumps(selector)))

    def fill(self, selector, text):
        self.eval('(()=>{const el=document.querySelector(%s);el.focus();el.value=%s;el.dispatchEvent(new Event("input",{bubbles:true}));'
                  'el.dispatchEvent(new Event("change",{bubbles:true}));return "ok";})()' % (json.dumps(selector), json.dumps(text)))

    def press(self, key, times=1):
        """A key on a physical keyboard (agent-browser's names: Tab, Shift+Tab, Escape, Enter, ArrowLeft, Digit1, Control+k)."""
        for _ in range(times):
            self.run('press', key)

    def pointer(self, selector, kind, pointer_type='touch'):
        self.eval('(()=>{const el=document.querySelector(%s),r=el.getBoundingClientRect();'
                  'el.dispatchEvent(new PointerEvent(%s,{bubbles:true,cancelable:true,pointerId:7,pointerType:%s,button:0,buttons:1,'
                  'clientX:r.left+r.width/2,clientY:r.top+r.height/2,isPrimary:true}));return "ok";})()'
                  % (json.dumps(selector), json.dumps(kind), json.dumps(pointer_type)))


class Suda(unittest.TestCase):
    """The page against the real server and the CLI. One server, one board and one browser for the class."""

    server = browser = None

    @classmethod
    def setUpClass(cls):
        if not AB:
            raise unittest.SkipTest('agent-browser is not installed')
        if os.environ.get('SUDA_E2E_SERVER') != 'own' and not (SKILL / 'answer_server.py').is_file():
            raise unittest.SkipTest('the board server is not at ' + str(SKILL))
        cls.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-e2e-', dir=ROOT)
        root = Path(cls.tmp.name)
        cls.boards = root / 'boards'
        cls.boards.mkdir()
        cls.board = cls.boards / SLUG
        cls.record = root / 'notifications.jsonl'
        recorder, hearer = root / 'record.py', root / 'hear.py'
        recorder.write_text(RECORDER)
        hearer.write_text(HEARER, encoding='utf-8')
        # The hook runs with the server's environment: the board folder, a mail recorder, never a real tuios.
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'THREADS_NOW', 'TUIOS_PANE_ID', 'BOARD_LOCK_TIMEOUT', 'THREADS_SONIOX_CMD'):
            os.environ.pop(key, None)
        # The MD Viewer (suda-fixes m149): `threads install` puts it beside the boards, the server loads it from
        # there, it opens only the test's own notes, and its model is the stand-in.
        cls.notes = root / 'notes'
        cls.notes.mkdir()
        os.environ.update(BOARDS_DIR=str(cls.boards), TZ=TZ, NOTIFY_RECORD=str(cls.record),
                          THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]),
                          THREADS_SONIOX_CMD=shlex.join([sys.executable, str(hearer)]),
                          THREADS_MDV_DIR=str(root / 'threads-mdv'), MDV_ROOTS_JSON=str(root / 'no-roots.json'),
                          MDV_EXTRA_ROOTS=str(cls.notes), MDV_FAKE_MODEL='1')
        cls.env = dict(os.environ, THREADS_SLUG=SLUG)
        cls.start_server()
        # the owner's own board is in Hebrew (config.json "lang"): these scenarios are his
        config = root / '.threads-config' / SLUG
        config.mkdir(parents=True, exist_ok=True)
        (config / 'config.json').write_text(json.dumps({'lang': os.environ.get('SUDA_E2E_LANG', 'he')}))
        r = cls.cli('install')
        assert r.returncode == 0, r.stderr
        assert (cls.board / 'suda.html').is_file() and os.access(cls.board / 'on-state.sh', os.X_OK)
        cls.ops = cls.state().get('ops') or []
        cls.browser = Browser('threads-e2e-%d' % os.getpid())
        try:
            cls.browser.launch()
        except Exception as e:          # no Chrome here: the file skips, the suite stays green
            cls.browser = None
            cls.server.shutdown()
            raise unittest.SkipTest('agent-browser could not open a browser: ' + str(e)[:200])

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.close()
        if cls.server:
            cls.server.shutdown()
        cls.tmp.cleanup()

    @classmethod
    def start_server(cls):
        if os.environ.get('SUDA_E2E_SERVER') == 'own':      # Suda's own server.py, as a fresh clone runs it
            spec = importlib.util.spec_from_file_location('suda_server_e2e', ROOT / 'server.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            slug = getattr(cls, 'SLUG', None) or SLUG              # (one board a server: the one this class names)
            mod.bl.BOARDS_DIR, mod.SLUG = cls.boards, slug
            cls.server = mod.Server(('127.0.0.1', 0), mod.Handler)
            cls.port = cls.server.server_address[1]
            threading.Thread(target=cls.server.serve_forever, daemon=True).start()
            cls.origin = 'http://127.0.0.1:%d' % cls.port
            cls.url = cls.origin + '/' + slug + '/suda.html'
            return
        sys.path.insert(0, str(SKILL))
        bl = importlib.import_module('boardlib')
        importlib.reload(bl)                      # BOARDS_DIR is read when the module loads
        # each class's server loads its own installed viewer, not the one an earlier class in this process installed
        # (and deleted with its folder): the viewer's package is read again
        for name in [n for n in sys.modules if n == 'mdv' or n.startswith('mdv.')]:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location('answer_server_e2e', SKILL / 'answer_server.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ROOT = cls.boards
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), mod.Handler)       # loopback only, a free port
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = 'http://127.0.0.1:%d' % cls.port
        cls.url = cls.origin + '/' + SLUG + '/suda.html'

    # ── the CLI, the state, the server ───────────────────────────────────────

    @classmethod
    def cli(cls, *args, input=None):
        return subprocess.run([sys.executable, str(CLI), *args], env=cls.env, input=input, capture_output=True, text=True)

    @classmethod
    def ok(cls, *args, input=None):
        r = cls.cli(*args, input=input)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout.strip()

    @classmethod
    def state(cls):
        return json.loads((cls.board / 'state.json').read_text(encoding='utf-8'))

    @classmethod
    def thread(cls, tid):
        return cls.state()['threads'][tid]

    @classmethod
    def pending(cls):
        return json.loads(cls.ok('pending', '--as', 'tower') or '[]')     # the tower's view: ▶ requests too

    def until(self, probe, timeout=15, what='the server'):
        """Poll the CLI or the state until `probe()` gives something; give it back."""
        end = time.monotonic() + timeout
        while True:
            got = probe()
            if got:
                return got
            if time.monotonic() > end:
                self.fail('waited %ss for %s' % (timeout, what))
            time.sleep(0.3)

    def post(self, op):
        """A page op sent straight to the server, as the page does: the server's receipt (the hook's last line)."""
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=70)
        body = json.dumps({'board': SLUG, 'state': op}, ensure_ascii=False).encode()
        c.request('POST', '/api/state', body, {'Content-Type': 'application/json', 'Origin': self.origin, 'Host': '127.0.0.1:%d' % self.port})
        r = c.getresponse()
        result = json.loads(r.read())
        out = result.get('out') or []
        try:
            receipt = json.loads(out[-1]) if out else {}
        except ValueError:
            receipt = {}
        return r.status, result, receipt

    def needs(self, op):
        if op not in self.ops:
            self.skipTest("the server side has not landed: '%s' is not in state.ops (%s)" % (op, ', '.join(self.ops)))

    def mails(self):
        return [json.loads(line)['args'][0] for line in self.record.read_text().splitlines()] if self.record.exists() else []

    visits = 0

    def open(self, size, hash=''):
        name, w, h = size
        self.browser.viewport(w, h)
        # A fresh query every time: a URL that differs only by its hash would not reload the page.
        Suda.visits += 1
        self.browser.open(self.url + '?s=%s&n=%d' % (name, Suda.visits) + ('#' + hash if hash else ''))
        self.browser.wait('JSON.stringify(document.readyState==="complete"&&!!document.querySelector("#input"))', what='the page')

    def open_thread(self, size, tid, title):
        self.open(size, tid)
        self.browser.wait('JSON.stringify(document.body.innerText.includes(%s)&&!!document.querySelector("#input").offsetParent)' % json.dumps(title),
                          what='thread ' + tid + ' on screen')

    # ── always: the road from the page to the tower ──────────────────────────

    def test_a_reply_typed_on_the_page_reaches_the_tower_at_every_size(self):
        self.ok('new', 'e2e-hello', 'נושא לבדיקה מקצה לקצה', '--summary', 'הדף, השרת וה-CLI יחד', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-hello', 'נושא לבדיקה מקצה לקצה')
                text = 'שלום מהדפדפן, מסך ' + size[0]
                self.browser.fill('#input', text)
                self.browser.click('#send')
                row = self.until(lambda: next((r for r in self.pending() if r['text'] == text), None), what='the reply in `threads pending`')
                self.assertEqual((row['thread'], row['title']), ('e2e-hello', 'נושא לבדיקה מקצה לקצה'))
                self.until(lambda: '[threads] reply in e2e-hello' in ' '.join(self.mails()), what='the tower\'s mail')   # the hook mails after it saved
                self.browser.wait('JSON.stringify(document.body.innerText.includes(%s))' % json.dumps(text), what='his message on the page')
                self.assertTrue(self.browser.visible('#input'))
        self.assertEqual([m['from'] for m in self.thread('e2e-hello')['messages']], ['owner'] * 3)

    # ── a message becomes a new topic ────────────────────────────────────────

    def test_a_message_is_split_into_a_new_topic_that_quotes_and_links_it(self):
        self.needs('new')
        self.ok('new', 'e2e-src', 'נושא המקור', '--summary', 'פיצול', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', 'e2e-src', '--from', 'tower', '-', '--state', 'working', '--note', 'יש הודעה', '--by', 'tower', input='לבדוק את הכפתור החדש בטלפון מחר בבוקר\nועוד שורה'), 'm1')
        self.open(SIZES[2], 'e2e-src')
        self.browser.wait('JSON.stringify(view.ch==="e2e-src"&&!!thread("e2e-src"))', what='the source thread')
        # the message menu offers the split; the form opens filled from the message, and he confirms
        self.browser.eval('(()=>{menuFor={kind:"msg",id:"m1",at:{x:300,y:300}};showSheet();return "ok";})()')
        self.browser.eval('(()=>{const b=[...document.querySelectorAll("#sheet-items .sheet-item")].find(x=>x.textContent.includes("פצל לנושא חדש"));if(!b)throw Error("no split item");b.click();return "ok";})()')
        knows = 'split' in self.ops
        self.browser.wait('JSON.stringify(!document.getElementById("topic").hidden&&document.getElementById("topic-links").value.includes("#e2e-src/m1"))', what='the form filled from the message')
        form = self.browser.eval('JSON.stringify({text:document.getElementById("topic-text").value,links:document.getElementById("topic-links").value,title:document.getElementById("topic-title").value})')
        self.assertEqual(form['title'], '')
        self.assertIn('=/' + SLUG + '/suda.html#e2e-src/m1', form['links'])
        if not knows:
            self.assertEqual(form['text'], '> לבדוק את הכפתור החדש בטלפון מחר בבוקר\n> ועוד שורה\n\n')
        before = set(self.state()['threads'])
        self.browser.click('#topic-ok')
        tid = self.until(lambda: next((k for k in self.state()['threads'] if k not in before), None), what='the new topic in state.json')
        t = self.thread(tid)
        self.assertIs(t.get('title_pending'), True)
        self.assertTrue(any(l['url'] == '/' + SLUG + '/suda.html#e2e-src/m1' and l['label'].startswith('מקור: ') for l in t['links']), t['links'])
        self.assertEqual((t['messages'][0]['from'], t['messages'][0].get('status')), ('owner', 'pending'))
        if knows:
            self.assertEqual(t['split_from']['thread'], 'e2e-src')
            self.assertEqual(t['split_from']['msg'], 'm1')
            src = self.thread('e2e-src')
            self.assertEqual(src['messages'][0].get('split_to'), tid)
            self.assertTrue(any(m.get('from') == 'system' and m.get('split_to', {}).get('thread') == tid for m in src['messages']), 'a system line in the source')
        else:
            self.assertTrue(t['messages'][0]['text'].startswith('> לבדוק את הכפתור החדש'))
            self.assertEqual(t['title'], 'לבדוק את הכפתור החדש בטלפון מחר בבוקר')
        # he lands in the new topic, which points back at the source
        self.browser.wait('JSON.stringify(view.ch===%s)' % json.dumps(tid), what='the page in the new topic')
        self.assertTrue(self.browser.eval('JSON.stringify(document.body.innerText.includes("מקור: נושא המקור"))'))

    # ── read aloud ───────────────────────────────────────────────────────────

    def test_a_message_is_read_aloud_through_the_browsers_voice_in_hebrew(self):
        self.ok('new', 'e2e-read', 'הקראה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', 'e2e-read', '--from', 'tower', '-', '--state', 'working', '--note', 'יש הודעה', '--by', 'tower', input='**חשוב:** לבדוק את `ultra logs`\n- פריט א\n```sh\n! ls\n```'), 'm1')
        self.open(SIZES[2], 'e2e-read')
        self.browser.wait('JSON.stringify(view.ch==="e2e-read"&&!!thread("e2e-read"))', what='the thread')
        if not self.browser.eval('JSON.stringify("speechSynthesis" in window)'):
            self.skipTest('this browser has no speech')
        # the browser's voice is asked with the words of the message, in Hebrew; the same item then stops it
        self.browser.eval('(()=>{window.__spoken=[];speechSynthesis.speak=u=>{window.__spoken.push({text:u.text,lang:u.lang,voice:u.voice&&u.voice.lang});window.__on=true;};'
                          'Object.defineProperty(speechSynthesis,"speaking",{get:()=>!!window.__on,configurable:true});speechSynthesis.cancel=()=>{window.__on=false;};return "ok";})()')
        item = lambda: self.browser.eval('(()=>{menuFor={kind:"msg",id:"m1",at:{x:300,y:300}};showSheet();const b=[...document.querySelectorAll("#sheet-items .sheet-item")].find(x=>x.textContent.includes("הקרא"));'
                                         'const label=b?b.textContent.trim():"";if(b)b.click();return JSON.stringify(label);})()')
        self.assertEqual(item(), 'הקרא בקול')
        spoken = self.browser.wait('JSON.stringify(window.__spoken.length?window.__spoken:null)', what='the utterance')
        self.assertEqual(spoken[0]['text'], 'חשוב: לבדוק את ultra logs. פריט א. קטע קוד.')
        self.assertEqual(spoken[0]['lang'], 'he-IL')
        self.assertEqual(item(), 'עצור את ההקראה')
        self.assertFalse(self.browser.eval('JSON.stringify(!!window.__on)'), 'the second press stopped it')

    # ── new topic from the page, without a title ─────────────────────────────

    def test_a_new_topic_without_a_title_opens_and_is_named_by_the_tower(self):
        self.needs('new')
        words = 'לבדוק את הכפתור החדש בטלפון של ההקלטות מחר בבוקר'          # 9 words: the title is the first 7 and an ellipsis
        for n, size in enumerate(SIZES):
            with self.subTest(size=size[0]):
                self.open(size)
                self.browser.wait('JSON.stringify(!!document.querySelector("#new-topic")&&!document.querySelector("#new-topic").hidden)', what='the new-topic button')
                self.browser.click('#new-topic')
                self.browser.wait('JSON.stringify(!!document.querySelector("#topic-text").offsetParent)', what='the form')
                text = words + ' ' + size[0]
                self.browser.fill('#topic-text', text)
                before = set(self.state()['threads'])
                self.browser.click('#topic-ok')
                tid = self.until(lambda: next((k for k, t in self.state()['threads'].items() if k not in before and t['messages'] and t['messages'][0]['text'] == text), None),
                                 what='the new thread in state.json')
                t = self.thread(tid)
                self.assertRegex(tid, r'^[a-z0-9][a-z0-9-]{0,47}$')
                self.assertEqual(t['title'], 'לבדוק את הכפתור החדש בטלפון של ההקלטות…')
                self.assertIs(t.get('title_pending'), True)
                self.assertEqual((t['messages'][0]['id'], t['messages'][0]['from'], t['messages'][0].get('status')), ('m1', 'owner', 'pending'))
                self.assertTrue(t['status'] == 'open' and t['slot'])
                self.assertTrue(any(r['thread'] == tid and r['text'] == text for r in self.pending()))
                self.until(lambda: tid in ' '.join(self.mails()), what='a mail to the tower naming ' + tid)
                # the page landed him in the new topic and said the tower will name it
                self.browser.wait('JSON.stringify(location.hash==="#"+%s&&document.body.innerText.includes("המגדל ייתן לו שם"))' % json.dumps(tid), what='the page in the new topic')
                self.assertFalse(self.browser.visible('#topic-text'))
                # the tower names it: the flag goes, and the page shows the name
                self.ok('rename', tid, 'הקלטות: כפתור חדש ' + size[0])
                t = self.thread(tid)
                self.assertEqual(t['title'], 'הקלטות: כפתור חדש ' + size[0])
                self.assertFalse(t.get('title_pending'))
                self.browser.wait('JSON.stringify(document.body.innerText.includes(%s))' % json.dumps('הקלטות: כפתור חדש ' + size[0]), what='the new title on the page')
        # a retry with the same cid opens nothing new; an empty form never leaves the page
        op = {'op': 'new', 'text': 'עוד פעם אותו דבר', 'title': 'עוד פעם אותו דבר', 'title_pending': True, 'cid': 'e2e-cid-1'}
        a, b = self.post(op)[2], self.post(op)[2]
        self.assertTrue(a.get('ok') and a.get('thread') and a.get('msg') == 'm1', a)
        self.assertEqual((b.get('ok'), b.get('thread')), (True, a['thread']))
        self.assertEqual(sum(t['messages'][0]['text'] == 'עוד פעם אותו דבר' for t in self.state()['threads'].values() if t['messages']), 1)
        self.open(SIZES[0])
        self.browser.click('#new-topic')
        self.browser.wait('JSON.stringify(!!document.querySelector("#topic-text").offsetParent)', what='the form')
        count = len(self.state()['threads'])
        self.browser.click('#topic-ok')
        self.browser.wait('JSON.stringify(document.querySelector("#topic-text-bad").textContent.trim().length>0)', what='the page refusing an empty topic')
        time.sleep(1)
        self.assertEqual(len(self.state()['threads']), count)

    # ── pictures with captions ───────────────────────────────────────────────

    def test_pictures_with_captions_reach_the_tower_in_his_order(self):
        self.needs('images')
        self.ok('new', 'e2e-pics', 'תמונות עם כיתוב', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        first, second = Path(self.tmp.name) / 'first.png', Path(self.tmp.name) / 'second.png'
        first.write_bytes(png(320, 200))
        second.write_bytes(png(64, 48, shade=90))
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-pics', 'תמונות עם כיתוב')
                self.browser.upload('#pic-file', first, second)
                self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===2)', what='two pictures in the tray')
                self.browser.fill('.tray-caption[data-n="1"]', 'המסך הראשון ' + size[0])
                self.browser.fill('.tray-caption[data-n="2"]', 'המסך השני ' + size[0])
                text = 'שתי תמונות, ' + size[0]
                self.browser.fill('#input', text)
                self.browser.click('#send')
                row = self.until(lambda: next((r for r in self.pending() if r['text'] == text), None), timeout=30, what='the reply with pictures in `threads pending`')
                m = next(m for m in self.thread('e2e-pics')['messages'] if m['text'] == text)
                self.assertEqual(len(m['images']), 2)
                for i, (image, caption, w, h) in enumerate(zip(m['images'], ('המסך הראשון ', 'המסך השני '), (320, 64), (200, 48))):
                    self.assertEqual(image['caption'], caption + size[0])
                    self.assertEqual((image['w'], image['h']), (w, h))
                    self.assertRegex(image['file'], r'^uploads/e2e-pics/m\d+-%d\.(jpg|png|gif|webp)$' % (i + 1))
                    stored = self.board / image['file']
                    self.assertTrue(stored.is_file() and stored.stat().st_size == image['bytes'] > 0, image['file'])
                # the tower's row: each picture as a path on this Mac, with its caption, in his order
                carried = row.get('images')
                self.assertIsInstance(carried, list, row)
                self.assertEqual([c.get('caption') for c in carried], ['המסך הראשון ' + size[0], 'המסך השני ' + size[0]])
                for c in carried:
                    path = c.get('path') or c.get('file')
                    self.assertTrue(path and os.path.isabs(path) and Path(path).is_file(), c)
                # and the page shows both, each with its caption
                self.browser.wait('JSON.stringify([...document.querySelectorAll("figure figcaption")].map(f=>f.textContent).filter(x=>x.includes(%s)).length===2)' % json.dumps(size[0]),
                                  what='the two captions on the page')

    # ── ▶ run: the tower runs only what it wrote ─────────────────────────────

    TOWER_TEXT = ('להתקנה בטלפון:\n```\n! ultra install -r app.apk\n  ! ultra logs --tail 20\n```\n'
                  'ובעברית, שלא רץ:\n```sh\n! echo שלום\n```\nוזה לא פקודה:\n```\nls -la\n```')

    def test_the_run_button_asks_the_tower_for_exactly_the_block_it_wrote(self):
        self.needs('run')
        command = command_of(self.TOWER_TEXT, 0)
        self.assertEqual(command, '! ultra install -r app.apk\n! ultra logs --tail 20')
        digest = hashlib.sha256(command.encode()).hexdigest()
        for size in SIZES:
            tid = 'e2e-run-' + size[0]
            with self.subTest(size=size[0]):
                self.ok('new', tid, 'כפתור הרץ ' + size[0], '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
                self.assertEqual(self.ok('say', tid, '--from', 'tower', '-', '--state', 'working', '--note', 'יש פקודה', '--by', 'tower', input=self.TOWER_TEXT), 'm1')
                self.assertEqual(self.ok('say', tid, '--from', 'fork', '-', '--state', 'working', '--note', 'לא מגדל', '--by', 'fork', input='```\n! ls\n```'), 'm2')
                self.open_thread(size, tid, 'כפתור הרץ ' + size[0])
                # one button: block 0 of the tower's message; not the Hebrew block, not the bare command, not the fork's
                buttons = self.browser.wait('JSON.stringify([...document.querySelectorAll("button.run")].filter(b=>b.offsetParent).length)', what='the run button')
                self.assertEqual(buttons, 1)
                self.browser.click('button.run')
                self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the confirm sheet')
                lines = self.browser.eval('JSON.stringify([...document.querySelectorAll("#run-command .run-line")].map(l=>l.textContent))')
                self.assertEqual(lines, command.split('\n'))
                self.assertIn('m1', self.browser.eval('JSON.stringify(document.querySelector("#run-note").textContent)'))
                self.browser.click('#run-ok')
                row = self.until(lambda: next((r for r in self.pending() if r['thread'] == tid), None), what='the run request in `threads pending`')
                self.assertEqual(row['text'], '▶ הרץ את הפקודה מהודעה m1')
                self.assertNotIn('ultra', row['text'])
                self.assertEqual(row['run'], {'msg_id': 'm1', 'block_index': 0, 'sha256': digest, 'command': command})
                stored = self.thread(tid)['messages'][-1]
                self.assertEqual((stored['from'], stored.get('status'), stored['run']['sha256']), ('owner', 'pending', digest))
                self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#run").hidden)'))
                # asked again while the first request waits: the page does not send twice
                self.browser.wait('JSON.stringify(document.body.innerText.includes("▶ הרץ את הפקודה מהודעה m1"))', what='his request on the page')
                self.browser.click('button.run')
                time.sleep(1)
                if not self.browser.eval('JSON.stringify(document.querySelector("#run").hidden)'):
                    self.browser.click('#run-ok')
                    time.sleep(2)
                self.assertEqual(sum(r['thread'] == tid for r in self.pending()), 1)
        # the server refuses what the page never sends: a wrong hash, a block that is not a command, a message not from the tower
        tid = 'e2e-run-cover'
        before = len(self.thread(tid)['messages'])
        bad = [{'msg_id': 'm1', 'block_index': 0, 'sha256': '0' * 64},                         # tampered
               {'msg_id': 'm1', 'block_index': 1, 'sha256': hashlib.sha256('! echo שלום'.encode()).hexdigest()},   # Hebrew: not runnable
               {'msg_id': 'm1', 'block_index': 2, 'sha256': hashlib.sha256(b'ls -la').hexdigest()},             # no "! "
               {'msg_id': 'm1', 'block_index': 3, 'sha256': digest},                                           # out of range
               {'msg_id': 'm2', 'block_index': 0, 'sha256': hashlib.sha256(b'! ls').hexdigest()},               # the fork's, not the tower's
               {'msg_id': 'm9', 'block_index': 0, 'sha256': digest}]                                           # no such message
        for i, run in enumerate(bad):
            with self.subTest(run=run):
                status, result, receipt = self.post({'op': 'reply', 'thread': tid, 'cid': 'e2e-bad-%d' % i, 'text': '▶ הרץ את הפקודה מהודעה ' + run['msg_id'], 'under': None, 'run': run})
                self.assertFalse(receipt.get('ok'), (status, result))
                self.assertRegex(str(receipt.get('error') or ' '.join(result.get('out') or [])), r'[\u0590-\u05FF]')
        self.assertEqual(len(self.thread(tid)['messages']), before)
        self.assertEqual(sum(r['thread'] == tid for r in self.pending()), 1)

    # ── a voice message ──────────────────────────────────────────────────────

    def test_a_recording_is_kept_on_the_mac_and_reaches_the_tower_as_words(self):
        self.needs('voice')
        self.ok('new', 'e2e-voice', 'הודעה קולית', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[0], 'e2e-voice', 'הודעה קולית')
        if not self.browser.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.skipTest('this browser has no microphone API on a loopback page')
        self.browser.wait('JSON.stringify(!!document.querySelector("#mic").offsetParent)', what='the record button')
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("0:0")||!document.querySelector("#send").hidden===false)', timeout=10, what='the recording to start')
        time.sleep(2)
        self.browser.pointer('#mic', 'pointerup')           # held past a tap: release = send
        m = self.until(lambda: next((m for m in self.thread('e2e-voice')['messages'] if m.get('voice')), None), timeout=30, what='the voice message in state.json')
        voice = m['voice']
        self.assertRegex(voice['file'], r'^uploads/e2e-voice/m\d+\.(webm|m4a|ogg)$')
        stored = self.board / voice['file']
        self.assertTrue(stored.is_file() and stored.stat().st_size == voice['bytes'] > 0, voice)
        self.assertTrue(1 <= voice['seconds'] <= 10, voice)
        self.assertIn(voice['state'], ('transcribing', 'done', 'failed'))
        for key in ('key', 'api', 'soniox'):
            self.assertNotIn(key, json.dumps(self.state()).lower())
        self.browser.wait('JSON.stringify(!!document.querySelector("audio"))', what='a player on the page')
        # While the words are not in, the message is not the tower's and the page says so. The words may land at any
        # moment, so each look is trusted only when the state still says "transcribing" after it was taken.
        still = lambda: self.thread('e2e-voice')['messages'][-1]['voice']['state'] == 'transcribing'
        rows = self.pending()
        if still():
            self.assertFalse(any(r['thread'] == 'e2e-voice' for r in rows), rows)
        shown = self.browser.eval('JSON.stringify(document.body.innerText.includes("מתמלל"))')
        if still():
            self.assertTrue(shown, 'the page should say it is transcribing')
        # the words come in (from the stand-in), the message becomes the tower's, with the audio's path beside the words
        done = self.until(lambda: next((m for m in self.thread('e2e-voice')['messages'] if m.get('voice', {}).get('state') in ('done', 'failed')), None),
                          timeout=60, what='the transcript')
        self.assertEqual((done['voice']['state'], done['text']), ('done', TRANSCRIPT))
        row = self.until(lambda: next((r for r in self.pending() if r['thread'] == 'e2e-voice'), None), what='the voice message in `threads pending`')
        self.assertEqual(row['text'], TRANSCRIPT)
        self.assertTrue(os.path.isabs(row['voice']['path']) and Path(row['voice']['path']).is_file(), row['voice'])
        self.assertEqual(row['voice']['state'], 'done')
        self.browser.wait('JSON.stringify(document.body.innerText.includes(%s)&&!document.body.innerText.includes("מתמלל"))' % json.dumps(TRANSCRIPT), what='the words on the page')

    # ── the keyboard alone (suda-kbd, task 62): every window takes the keys, keeps Tab inside and gives them back ──

    ACTIVE = ('JSON.stringify((a=>({tag:a.tagName.toLowerCase(),id:a.id||"",cls:String(a.className||""),k:a.dataset?a.dataset.k||"":"",'
              'label:a.getAttribute?a.getAttribute("aria-label")||a.textContent.trim().slice(0,30):"",inAnswer:!!a.closest("#answer"),inNotify:!!a.closest("#notify"),'
              'inReader:!!a.closest("#reader"),inRow:!!a.closest("#log .msg"),isRow:a.classList&&a.classList.contains("msg"),ring:getComputedStyle(a).outlineStyle!=="none"&&parseFloat(getComputedStyle(a).outlineWidth)>0}))'
              '(document.activeElement))')

    def active(self):
        return self.browser.eval(self.ACTIVE)

    def tab_until(self, predicate, limit=40, what='a control'):
        for _ in range(limit):
            self.browser.press('Tab')
            a = self.active()
            if predicate(a):
                return a
        self.fail('no ' + what + ' within %d Tabs; at %r' % (limit, a))

    def test_keyboard_alone_ticks_the_boxes_and_comes_back_to_the_button(self):
        groups = Path(self.tmp.name) / 'groups.json'
        groups.write_text(json.dumps([{"title": "שרת", "items": ["Web Push", {"text": "גיבוי", "recommended": True}]}, {"title": "דף", "items": ["אייקון", "מצב כהה"]}], ensure_ascii=False), encoding='utf-8')
        self.ok('new', 'e2e-kbd-multi', 'תיבות סימון מהמקלדת', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', 'e2e-kbd-multi', 'מה להכניס לגרסה?', '--groups-file', str(groups))
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-kbd-multi', 'תיבות סימון מהמקלדת')
                # what was ticked at the other size is kept on the device: start this size clean
                self.browser.eval('(()=>{for(const k of Object.keys(localStorage))if(k.includes("ticks:"))localStorage.removeItem(k);ticks.clear();pinSignature="";render();return "ok";})()')
                self.browser.press('Escape')                                   # out of the composer
                self.tab_until(lambda a: a['k'] == 'pick-list', what='the "בחר מהרשימה" button')
                self.browser.press('Enter')
                self.browser.wait('JSON.stringify(!document.querySelector("#answer").hidden)', what='the form')
                a = self.active()
                self.assertEqual((a['tag'], a['inAnswer'], a['ring']), ('input', True, True), a)          # the keys land on the first box, with a visible ring
                for _ in range(12):                                                                   # Tab never leaves the form
                    self.browser.press('Tab')
                    self.assertTrue(self.active()['inAnswer'], self.active())
                self.browser.press('Shift+Tab', 12)
                self.browser.press('ArrowDown')                                 # up and down walk the boxes, Space ticks
                self.browser.press('Space')
                self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll("#answer input[type=checkbox]")].filter(b=>b.checked).length)'), 1)
                self.assertFalse(self.browser.eval('JSON.stringify(document.querySelector("#answer-send").disabled)'))
                self.browser.press('Escape')
                self.browser.wait('JSON.stringify(document.querySelector("#answer").hidden)', what='the form to close')
                self.assertEqual(self.active()['k'], 'pick-list', self.active())                     # back on the button, even though the strip was drawn again

    def test_keyboard_alone_reaches_the_pictures_and_tools_of_the_chosen_message(self):
        self.ok('new', 'e2e-kbd-pics', 'כפתורי ההודעה מהמקלדת', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        shot = Path(self.tmp.name) / 'kbd.png'
        shot.write_bytes(png(120, 80))
        self.ok('say', 'e2e-kbd-pics', '--from', 'tower', '-', '--image', str(shot), '--caption', 'לפני', '--by', 'e2e', '--state', 'working', '--note', 'תמונה',
                input='תמונה וקוד:\n\n```sh\n! echo hi\n```\n')
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-kbd-pics', 'כפתורי ההודעה מהמקלדת')
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot-open"))', what='the picture as a button')
                self.browser.press('Escape')
                self.browser.press('ArrowUp')                                   # the last message is chosen and holds the keys
                self.assertTrue(self.active()['isRow'], self.active())
                self.browser.press('Enter')                                     # into its buttons
                a = self.active()
                self.assertTrue(a['inRow'] and not a['isRow'], a)
                for _ in range(12):
                    if 'shot-open' in self.active()['cls']:
                        break
                    self.browser.press('ArrowLeft')
                self.assertIn('shot-open', self.active()['cls'])
                self.browser.press('Enter')
                self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden)', what='the picture on the full screen')
                self.assertTrue(self.active()['inReader'], self.active())
                self.browser.press('Tab', 3)
                self.assertTrue(self.active()['inReader'], self.active())                              # Tab stays in the reader
                self.browser.press('Escape')
                self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader to close')
                self.assertIn('shot-open', self.active()['cls'])                                      # back on the picture
                self.assertIn('העתקת הקוד', self.browser.eval('JSON.stringify(messageItems(itemRow()).map(n=>n.getAttribute("aria-label")||n.textContent.trim()))'))
                self.browser.press('Escape')                                    # out of the buttons, onto the message
                self.assertTrue(self.active()['isRow'], self.active())
                self.browser.press('Escape')                                    # let go of the message
                self.assertFalse(self.browser.eval('JSON.stringify(!!cursor)'))

    def test_a_held_answer_is_taken_back_with_esc_and_the_tower_never_sees_it(self):
        self.ok('new', 'e2e-kbd-hold', 'תשובה שחוזרת בה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', 'e2e-kbd-hold', 'מתי?', '--options', 'מחר,מחרתיים,בשבוע הבא')
        self.open_thread(SIZES[2], 'e2e-kbd-hold', 'תשובה שחוזרת בה')
        self.browser.wait('JSON.stringify(quickAnswers().length===3)', what='the three answers')
        self.browser.press('Digit1')                                            # from the empty composer
        held = self.browser.eval('JSON.stringify((optimistic.get("e2e-kbd-hold")||[]).map(m=>[m.text,m.delivery]))')
        self.assertEqual(held, [['מחר', 'holding']])
        self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll(".toast kbd")].map(k=>k.textContent))'), ['Esc'])   # the key is written on the notice
        self.browser.press('Escape')
        self.assertEqual(self.browser.eval('JSON.stringify((optimistic.get("e2e-kbd-hold")||[]).length)'), 0)
        time.sleep(5)
        self.assertEqual([r for r in self.pending() if r['thread'] == 'e2e-kbd-hold'], [])
        self.browser.press('ArrowDown')                                         # the answers are back: arrows walk them, Enter chooses
        self.browser.press('ArrowDown')
        self.browser.press('Enter')
        self.assertEqual(self.active()['id'], 'input')                                               # the keys move on to the composer
        row = self.until(lambda: next((r for r in self.pending() if r['thread'] == 'e2e-kbd-hold'), None), timeout=15, what='the answer in `threads pending`')
        self.assertEqual(row['text'], 'מחרתיים')

    def test_the_windows_keep_tab_inside_and_give_the_keys_back(self):
        self.ok('new', 'e2e-kbd-win', 'חלונות מהמקלדת', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-kbd-win', 'חלונות מהמקלדת')
        self.browser.press('Escape')
        # the settings
        self.tab_until(lambda a: a['id'] == 'bell', limit=120, what='the settings button')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector("#notify").hidden&&document.querySelector("#notify-body").children.length>0)', what='the settings to be drawn')
        self.browser.wait('JSON.stringify(document.activeElement.closest("#notify")&&document.activeElement.id!=="notify-close")', what='the keys on the first setting')
        for _ in range(10):
            self.browser.press('Tab')
            self.assertTrue(self.active()['inNotify'], self.active())
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#notify").hidden)', what='the settings to close')
        self.assertEqual(self.active()['id'], 'bell')
        # the message menu, from the chosen message
        self.browser.fill('#input', 'שלום')
        self.browser.click('#send')
        self.browser.wait('JSON.stringify(!!document.querySelector(\'#log .msg[data-mid]:not([data-mid=""])\'))', timeout=20, what='the message, confirmed by the server, on the page')
        self.browser.press('Escape')
        self.browser.press('ArrowUp')
        self.browser.press('ContextMenu')
        self.browser.wait('JSON.stringify(!document.querySelector("#sheet").hidden)', what='the menu')
        self.assertIn('sheet-item', self.active()['cls'])
        self.browser.press('Tab', 3)
        self.assertFalse(self.browser.eval('JSON.stringify(document.querySelector("#sheet").hidden)'))                 # Tab stays in the menu
        self.assertTrue(self.active()['ring'], self.active())                                                      # with a ring on the item
        self.browser.press('Escape')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#sheet").hidden)'))
        self.assertTrue(self.active()['isRow'], self.active())
        # the new-topic form: Tab reaches its buttons past the folded "context and links"
        if 'new' in self.ops:
            self.browser.press('Escape')
            self.browser.press('Escape')
            self.browser.press('n')
            self.browser.wait('JSON.stringify(!document.querySelector("#topic").hidden)', what='the new-topic form')
            self.assertEqual(self.active()['id'], 'topic-text')
            self.browser.press('Tab', 3)
            self.assertEqual(self.active()['id'], 'topic-ok', self.active())
            self.browser.press('Escape')
            self.browser.wait('JSON.stringify(document.querySelector("#topic").hidden)', what='the form to close')

    def test_a_notice_and_the_pill_carry_their_keys_and_answer_to_them(self):
        self.ok('new', 'e2e-kbd-notice', 'בועות עם מקש', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for i in range(14):
            self.ok('say', 'e2e-kbd-notice', '--from', 'fork', 'הודעה מספר %d.\n\nשורה שנייה, כדי שהשיחה תהיה ארוכה מהחלון.\n\nושורה שלישית.' % (i + 1), '--by', 'e2e', '--state', 'working', '--note', 'ממלאים')
        self.open_thread(SIZES[2], 'e2e-kbd-notice', 'בועות עם מקש')
        self.browser.eval('(()=>{toast("עליך: נושא לדוגמה","פתח",()=>{window.__went=(window.__went||0)+1;});return "ok";})()')
        self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll(".toast kbd")].map(k=>k.textContent))'), ['G'])
        self.browser.press('g')                                                 # from the empty composer
        self.assertEqual((self.browser.eval('JSON.stringify(window.__went)'), self.browser.eval('JSON.stringify(input.value)')), (1, ''))
        self.browser.fill('#input', 'כותב')
        self.browser.eval('(()=>{toast("עליך: שוב","פתח",()=>{window.__went+=1;});return "ok";})()')
        self.browser.press('g')                                                 # mid-word: a letter is a letter
        self.assertEqual((self.browser.eval('JSON.stringify(window.__went)'), self.browser.eval('JSON.stringify(input.value)')), (1, 'כותבg'))
        self.browser.fill('#input', '')
        self.browser.viewport(1280, 420)                                        # a short window: the conversation is longer than it
        self.browser.eval('(()=>{scroller.scrollTop=0;syncJump();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#jump").hidden)', what='the pill under the conversation')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#jump kbd").textContent)'), 'End')
        self.browser.press('End')                                               # from the empty composer
        self.browser.wait('JSON.stringify(document.querySelector("#jump").hidden)', what='the pill to go once the end is on screen')

    def test_in_the_composer_the_arrows_scroll_a_short_text_and_home_end_keep_to_the_line(self):
        self.ok('new', 'e2e-kbd-arrows', 'חצים בתיבת ההודעה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for i in range(14):
            self.ok('say', 'e2e-kbd-arrows', '--from', 'fork', 'הודעה %d.\n\nשורה שנייה.\n\nשורה שלישית.' % (i + 1), '--by', 'e2e', '--state', 'working', '--note', 'ממלאים')
        self.open_thread(SIZES[2], 'e2e-kbd-arrows', 'חצים בתיבת ההודעה')
        self.browser.viewport(1280, 420)                                        # a short window: the conversation is longer than it
        top = lambda: self.browser.eval('JSON.stringify(scroller.scrollTop)')
        caret = lambda: self.browser.eval('JSON.stringify([input.selectionStart,input.selectionEnd])')
        self.browser.eval('(()=>{input.focus();scroller.scrollTop=200;return "ok";})()')
        # nothing written: up and down scroll the conversation, a page with PageDown
        self.browser.press('ArrowUp')
        self.assertLess(top(), 200)
        self.browser.press('ArrowDown')
        self.assertEqual(top(), 200)
        self.browser.press('PageDown')
        self.assertGreater(top(), 400)
        # one line: still the conversation; the caret stays where it was
        self.browser.fill('#input', 'שורה אחת')
        self.browser.eval('(()=>{input.focus();input.setSelectionRange(3,3);scroller.scrollTop=200;return "ok";})()')
        self.browser.press('ArrowDown')
        self.assertEqual((top(), caret()), (248, [3, 3]))
        # two lines: the arrows move the caret; from the first line up (and the last line down) they scroll
        self.browser.fill('#input', 'ראשונה\nשנייה')
        self.browser.eval('(()=>{input.focus();input.setSelectionRange(9,9);scroller.scrollTop=200;return "ok";})()')
        self.browser.press('ArrowUp')
        self.assertEqual(top(), 200)
        self.assertLessEqual(caret()[0], 6, caret())
        self.browser.press('ArrowUp')
        self.assertEqual(top(), 152)
        # Home and End: the logical ends of the caret's line (a Hebrew line: Home is its right edge)
        self.browser.eval('(()=>{input.setSelectionRange(9,9);return "ok";})()')
        self.browser.press('Home')
        self.assertEqual(caret(), [7, 7])
        self.browser.press('End')
        self.assertEqual(caret(), [12, 12])
        self.browser.press('Shift+Home')
        self.assertEqual(caret(), [7, 12])
        self.browser.fill('#input', '')

    def test_a_digit_never_answers_while_he_writes_records_or_attaches(self):
        # suda m309: a question arrives while he types or records; 2 must not answer it
        self.ok('new', 'e2e-kbd-busy', 'ספרה באמצע כתיבה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', 'e2e-kbd-busy', 'מתי?', '--options', 'מחר,מחרתיים,בשבוע הבא')
        self.open_thread(SIZES[2], 'e2e-kbd-busy', 'ספרה באמצע כתיבה')
        self.browser.wait('JSON.stringify(quickAnswers().length===3)', what='the three answers')
        held = lambda: self.browser.eval('JSON.stringify((optimistic.get("e2e-kbd-busy")||[]).map(m=>m.delivery))')
        # a word in the composer: the digit is a digit
        self.browser.fill('#input', 'כותב')
        self.browser.press('2')
        self.assertEqual((held(), self.browser.eval('JSON.stringify(input.value)')), ([], 'כותב2'))
        self.browser.press('ArrowDown')
        self.assertEqual(self.active()['id'], 'input')
        self.browser.fill('#input', '')
        # another text field (the search box): the same
        self.browser.press('Escape')
        self.browser.press('Slash')
        self.browser.wait('JSON.stringify(find.open)', what='the search box')
        self.browser.press('2')
        self.assertEqual((held(), self.browser.eval('JSON.stringify(document.getElementById("find-q").value)')), ([], '2'))
        self.browser.press('Escape')
        # pictures waiting beside the empty box: a message is being made
        if 'images' in self.ops:
            shot = Path(self.tmp.name) / 'busy.png'
            shot.write_bytes(png(40, 30))
            self.browser.upload('#pic-file', shot)
            self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===1)', what='the picture in the tray')
            self.browser.press('Escape')
            self.browser.press('2')
            self.assertEqual(held(), [])
            self.browser.eval('(()=>{pictures.delete("e2e-kbd-busy");keepTray("e2e-kbd-busy");renderTray();render();return "ok";})()')
        # a recording in progress: the keys sit on its send button, and still no digit answers
        if 'voice' in self.ops and self.browser.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.browser.eval('(()=>{beginRec(null);return "ok";})()')
            self.browser.wait('JSON.stringify(!!rec&&document.activeElement.id==="rec-send")', timeout=10, what='the recording to start')
            self.browser.press('2')
            self.browser.press('ArrowDown')
            self.assertEqual(held(), [])
            self.assertNotIn(self.active()['cls'], ('btn option', 'opt'))
            self.browser.press('Escape')                                        # the recording is thrown away
            self.browser.wait('JSON.stringify(!rec)', timeout=10, what='the recording to end')
        # the empty box, nothing waiting: the digit answers (and Esc takes it back)
        self.browser.eval('(()=>{input.focus();return "ok";})()')
        self.browser.press('2')
        self.assertEqual(held(), ['holding'])
        self.browser.press('Escape')
        self.assertEqual(held(), [])

    def test_every_setting_is_a_command_of_the_palette(self):
        self.ok('new', 'e2e-kbd-palette', 'הגדרות מהלוח', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-kbd-palette', 'הגדרות מהלוח')
        labels = lambda: self.browser.eval('JSON.stringify([...document.querySelectorAll("#sw-results [role=option]")].map(o=>o.textContent.trim()))')
        def ask(text):
            self.browser.press('Escape')
            self.browser.press('Control+k')
            self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
            self.browser.fill('#sw-query', text)
            self.browser.wait('JSON.stringify(document.querySelectorAll("#sw-results [role=option]").length>0)', what='results for ' + text)
            return labels()
        self.assertTrue(all(any(word in l for l in ask('מראה')) for word in ('בהיר', 'כהה')), labels())
        self.assertEqual(len([l for l in ask('הודעות קצרות') if 'הודעות קצרות:' in l]), 3)
        self.browser.press('Enter')                                              # the first one: the notices move there
        self.browser.wait('JSON.stringify(document.querySelector("#switcher").hidden)', what='the palette to close')
        self.assertEqual(self.browser.eval('JSON.stringify(store.get("toast-at",""))'), 'top-left')
        self.assertTrue(any('התראות' in l and ('הפעל' in l or 'כבה' in l or 'הפעלה' in l) for l in ask('התראות')), labels())
        if 'quiet' in self.ops:
            self.assertTrue(any(l.startswith('›שעות שקט:') or 'שעות שקט:' in l for l in ask('שעות שקט')), labels())
        if 'mute' in self.ops:
            self.assertTrue(any('השתק' in l for l in ask('השתק')), labels())
        self.browser.press('Escape')

    # ── rich blocks: drawn by the page from what the agent wrote ─────────────

    RICH_TEXT = ('**עלויות:**\n```chart\n{"type":"bar","title":"עלות","labels":["א","ב","ג"],"series":[{"name":"x","values":[4766,2100,95]},{"name":"y","values":[0,900,40]}],"prefix":"$"}\n```\n'
                 '```widget\n{"title":"מחשבון","inputs":[{"id":"n","label":"מכונות","min":100,"max":5000,"step":100,"value":1000}],"outputs":[{"label":"מחזור","formula":"n*1125","prefix":"$","decimals":0}]}\n```\n'
                 '```carousel\n{"slides":[{"title":"ראשון","image":1},{"title":"שני","image":2},{"title":"שלישי","text":"בלי תמונה"}]}\n```\n'
                 '```svg\n<svg viewBox="0 0 100 40"><rect width="100" height="40" fill="#dbeafe"/></svg>\n```\n'
                 '```status\n{"title":"PR #1","state":"running","lines":[{"label":"CI","value":"רץ","state":"running"}],"progress":0.5}\n```\n'
                 '```chart\n{"labels":["א"],"series":[{"values":["x"]}]}\n```')
    RICH_PROBE = ('JSON.stringify((()=>{const q=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)];'
                  'return {legend:all(".chart-legend b").map(b=>b.textContent),vals:all(".chart-svg .val").map(v=>v.textContent),'
                  'out:q(".widget-out-value").textContent,slider:q(".slider-val").textContent,slides:all(".slide").length,pics:all(".pics img").length,'
                  'svg:!!q(".svg-pic")&&q(".svg-pic").src.startsWith("data:image/svg+xml"),status:q(".status-title").textContent,progress:q(".progress").getAttribute("aria-valuenow"),'
                  'error:q(".rich-error").textContent,code:all(".card.code").length,scripts:all(".card.rich script").length,width:q(".chart-svg").getBoundingClientRect().width};})())')

    def test_rich_blocks_are_drawn_from_the_agents_json_and_answer_a_finger_or_a_key(self):
        self.ok('new', 'e2e-rich', 'בלוקים עשירים', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        first, second = Path(self.tmp.name) / 'r1.png', Path(self.tmp.name) / 'r2.png'
        first.write_bytes(png(120, 80))
        second.write_bytes(png(120, 80, shade=90))
        self.assertEqual(self.ok('say', 'e2e-rich', '--from', 'fork', '-', '--image', str(first), '--caption', 'אחת', '--image', str(second), '--caption', 'שתיים',
                                 '--state', 'working', '--note', 'בלוקים', '--by', 'fork', input=self.RICH_TEXT), 'm1')
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-rich', 'בלוקים עשירים')
                self.browser.wait('JSON.stringify(document.querySelectorAll(".card.rich").length===5&&document.querySelectorAll(".chart-svg .bar").length===6)', what='the five cards and six bars')
                got = self.browser.eval(self.RICH_PROBE)
                self.assertEqual(got['legend'], ['x', 'y'])
                self.assertIn('$4,766', got['vals'])
                self.assertEqual((got['out'], got['slider']), ('$1,125,000', '1,000'))
                self.assertEqual((got['slides'], got['pics']), (3, 0))        # the carousel took both pictures: the grid shows none
                self.assertTrue(got['svg'])
                self.assertEqual((got['status'], got['progress']), ('PR #1', '50'))
                self.assertIn('מספרים בלבד', got['error'])
                self.assertEqual((got['code'], got['scripts']), (1, 0))      # the broken block stays a code card; nothing of the agent's runs
                self.assertGreater(got['width'], 200)                        # the chart is drawn at the width it has
                # the slider moves the result as he drags it
                self.browser.eval('(()=>{const r=document.querySelector(".slider input");r.value="2000";r.dispatchEvent(new Event("input",{bubbles:true}));return "ok"})()')
                self.browser.wait('JSON.stringify(document.querySelector(".widget-out-value").textContent==="$2,250,000")', what='the result after the slider moved')
                # the carousel: the next button, then the arrow key, move to the next slide
                self.browser.click('.card.carousel .card-top button[aria-label="הבא"]')
                self.browser.wait('JSON.stringify(document.querySelector(".slide-n").textContent==="2 / 3")', what='the second slide after a press')
                self.browser.eval('(()=>{const s=document.querySelector(".slides");s.focus();s.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft",bubbles:true}));return "ok"})()')
                self.browser.wait('JSON.stringify(document.querySelector(".slide-n").textContent==="3 / 3")', what='the third slide after an arrow key')
                # the chart's data as a table: a sheet card with its own copy and CSV
                self.browser.click('.card.chart .card-top button[aria-label="טבלה"]')
                self.browser.wait('JSON.stringify(!!document.querySelector(".chart-table .card.sheet")&&document.querySelectorAll(".chart-table td").length===9)', what='the data table')
    # ── a live card: the agent updates its message in place, the card redraws ──

    LIVE_CARD = '```status\n{"title":"PR #7","state":"%s","lines":[{"label":"CI","value":"%s","state":"%s"}],"progress":%s,"note":"%s"}\n```'

    def test_a_live_status_card_is_redrawn_in_place_when_the_agent_updates_it(self):
        if self.cli('update', '--help').returncode != 0:
            self.skipTest("the server side has not landed: 'threads update' is unknown")
        self.ok('new', 'e2e-live', 'כרטיס חי', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.assertEqual(self.ok('say', 'e2e-live', '--from', 'fork', '-', '--live', '--state', 'working', '--note', 'רץ', '--by', 'fork',
                                 input=self.LIVE_CARD % ('running', 'רץ', 'running', '0.3', 'מתעדכן')), 'm1')
        self.open_thread(SIZES[0], 'e2e-live', 'כרטיס חי')
        probe = ('JSON.stringify((()=>{const c=document.querySelector(".card.status");if(!c)return null;const q=s=>c.querySelector(s);'
                 'return {live:q(".card-title").textContent,state:[...c.classList].find(x=>x.startsWith("st-")),progress:q(".progress").getAttribute("aria-valuenow"),'
                 'line:q(".status-line dd").textContent,when:q(".card-when")?q(".card-when").textContent:"",rows:document.querySelectorAll(".msg").length};})())')
        self.browser.wait('JSON.stringify(!!document.querySelector(".card.status"))', what='the status card')
        before = self.browser.eval(probe)
        self.assertEqual((before['live'], before['state'], before['progress'], before['when']), ('סטטוס · חי', 'st-running', '30', ''))
        # the agent writes the card again: the same message, redrawn, no new row
        self.ok('update', 'e2e-live', 'm1', '--from', 'fork', '-', input=self.LIVE_CARD % ('ok', '84 עברו', 'ok', '1', 'הסתיים'))      # prints nothing: the same message, changed
        m = self.thread('e2e-live')['messages'][0]
        self.assertTrue(m.get('live') and m.get('edited') and m.get('edits') == 1, m)
        self.browser.wait('JSON.stringify((()=>{const c=document.querySelector(".card.status");return !!c&&c.classList.contains("st-ok");})())', timeout=30, what='the card in its new state')
        after = self.browser.eval(probe)
        self.assertEqual((after['state'], after['progress'], after['line'], after['rows']), ('st-ok', '100', '84 עברו · תקין', before['rows']))
        self.assertTrue(after['when'].startswith('עודכן '), after['when'])
    # ── a picture on the whole screen: the keys move over it ─────────────────

    def test_a_diagram_on_the_whole_screen_answers_the_arrows_plus_minus_and_zero(self):
        self.ok('new', 'e2e-zoom', 'דיאגרמה במסך מלא', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        wide = 'flowchart LR\n' + '\n'.join('  n%d[צעד %d מתוך הזרימה הארוכה] --> n%d' % (i, i, i + 1) for i in range(8))
        self.assertEqual(self.ok('say', 'e2e-zoom', '--from', 'fork', '-', '--state', 'working', '--note', 'דיאגרמה', '--by', 'fork', input='הזרימה:\n```mermaid\n' + wide + '\n```'), 'm1')
        key = lambda code, extra='': 'document.dispatchEvent(new KeyboardEvent("keydown",{code:%s,key:"",bubbles:true,cancelable:true%s}))' % (json.dumps(code), extra)
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.open_thread(size, 'e2e-zoom', 'דיאגרמה במסך מלא')
                self.browser.wait('JSON.stringify(!!document.querySelector("figure.diagram .diagram-pic"))', timeout=40, what='the diagram drawn')
                self.browser.click('figure.diagram .card-top button[aria-label="מסך מלא"]')
                self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body img")&&document.querySelector("#reader-body img").naturalWidth>0)', what='the reader with the picture')
                probe = ('JSON.stringify((()=>{const b=document.querySelector("#reader-body"),i=b.querySelector("img");'
                         'return {w:i.clientWidth,pct:document.querySelector(".reader-tools .zoom").textContent,left:b.scrollLeft,fits:i.clientWidth<=b.clientWidth&&i.clientHeight<=b.clientHeight};})())')
                start = self.browser.eval(probe)
                self.browser.eval(key('Equal') + ';' + key('Equal') + ';"ok"')
                bigger = self.until(lambda: (lambda g: g if g['w'] > start['w'] else None)(self.browser.eval(probe)), what='a bigger picture after +')
                self.assertNotEqual(bigger['pct'], start['pct'])
                # the arrows move over it once it is wider than the screen
                self.browser.eval(key('ArrowRight') + ';"ok"')
                self.until(lambda: self.browser.eval(probe)['left'] > bigger['left'], what='the picture moved to the right')
                self.browser.eval(key('Minus') + ';"ok"')
                smaller = self.until(lambda: (lambda g: g if g['w'] < bigger['w'] else None)(self.browser.eval(probe)), what='a smaller picture after −')
                self.browser.eval(key('Digit0') + ';"ok"')
                fitted = self.until(lambda: (lambda g: g if g['fits'] else None)(self.browser.eval(probe)), what='the whole picture on the screen after 0')
                self.assertLess(fitted['w'], smaller['w'])
                self.browser.eval(key('Escape') + ';"ok"')
                self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed by Esc')
    # ── Esc closes every window and popup, from wherever the keys are ────────

    PR_URL = 'https://github.com/acme/orbit/pull/1614'

    def test_esc_closes_every_window_and_popup_from_any_focus(self):
        self.ok('new', 'e2e-esc', 'אסקייפ סוגר הכול', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        shot, page = Path(self.tmp.name) / 'esc.png', Path(self.tmp.name) / 'esc.html'
        shot.write_bytes(png(200, 120))
        page.write_text('<!doctype html><html><body style="margin:0"><button id="in" style="font-size:24px;height:200px;width:100%">בתוך הדף של הסוכן</button></body></html>', encoding='utf-8')
        (self.board / 'links.json').write_text(json.dumps({'version': 1, 'links': {self.PR_URL: {'kind': 'pr', 'state': 'open', 'title': 'החזר חלקי', 'repo': 'acme/orbit', 'number': 1614, 'author': 'owner'}}, 'wanted': []}), encoding='utf-8')
        self.assertEqual(self.ok('say', 'e2e-esc', '--from', 'fork', '-', '--image', str(shot), '--caption', 'צילום', '--html', str(page), '--state', 'working', '--note', 'יש', '--by', 'fork',
                                 input='ה-PR: ' + self.PR_URL + '\nועוד שורה'), 'm1')
        self.ok('task', 'add', 'e2e-esc', 'משימה לבדיקה', '--owner', 'e2e')
        self.ok('ask', 'e2e-esc', 'מה לבחור?', '--multi', '--options', 'א,ב,ג')
        hidden = lambda sel: 'JSON.stringify(document.querySelector(%s).hidden)' % json.dumps(sel)
        shown = lambda sel: 'JSON.stringify(!document.querySelector(%s).hidden)' % json.dumps(sel)
        esc = lambda what, sel: (self.browser.press('Escape'), self.browser.wait(hidden(sel), what=what + ' closed by Esc'))

        self.open_thread(SIZES[2], 'e2e-esc', 'אסקייפ סוגר הכול')
        self.browser.wait('JSON.stringify(!!document.querySelector(".card.canvas iframe")&&!!document.querySelector(".pics img")&&!!document.querySelector("a.chip-link[data-kind=pr]"))', timeout=20, what='the picture, the frame and the chip')
        # the picture on the whole screen, with the keys on one of its tools
        self.browser.click('.pics img')
        self.browser.wait(shown('#reader'), what='the picture reader')
        self.browser.eval('(()=>{document.querySelector(".reader-tools .zoom").focus();return "ok"})()')
        esc('the picture reader', '#reader')
        # the agent's page on the whole screen, with the keys INSIDE its frame
        self.browser.wait('JSON.stringify(!!document.querySelector(".card.canvas iframe").style.height)', timeout=20, what='the frame in the conversation to have told its height (its tail runs)')
        self.browser.click('.card.canvas .card-top button[aria-label="מסך מלא"]')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader iframe"))', what='the frame reader')
        self.browser.wait('JSON.stringify((()=>{const f=document.querySelector("#reader iframe");return !!f&&!!f.srcdoc;})())', what='the frame reader to have its page')
        time.sleep(1.5)                                                   # the sandboxed page cannot be asked whether it has loaded: give it a moment
        self.browser.eval('(()=>{document.querySelector("#reader iframe").focus();return "ok"})()')
        self.browser.wait('JSON.stringify(document.activeElement===document.querySelector("#reader iframe"))', what='the keys inside the frame')
        esc('the frame reader', '#reader')
        # the agent's page in the conversation: Esc inside it gives the keys back to its message
        self.browser.eval('(()=>{document.querySelector(".card.canvas iframe").focus();return "ok"})()')
        self.browser.wait('JSON.stringify(document.activeElement===document.querySelector(".card.canvas iframe"))', what='the keys inside the frame in the conversation')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.activeElement.classList.contains("msg"))', what='the keys back on the message')
        self.browser.press('Escape')
        # the card of a pull request, shown while its chip holds the keys
        self.browser.eval('(()=>{const a=document.querySelector("a.chip-link[data-kind=pr]");a.focus();a.dispatchEvent(new FocusEvent("focusin",{bubbles:true}));showCard(a,false);return "ok"})()')
        self.browser.wait(shown('#link-card'), what='the pull request card')
        esc('the pull request card', '#link-card')
        # the menu of a message, from one of its items
        self.browser.press('Escape')
        self.browser.press('ArrowUp')
        self.browser.press('ContextMenu')
        self.browser.wait(shown('#sheet'), what='the menu')
        self.browser.press('Tab')
        esc('the menu', '#sheet')
        self.browser.press('Escape')
        # the switcher, in the middle of typing
        self.browser.press('Control+k')
        self.browser.wait(shown('#switcher'), what='the switcher')
        self.browser.press('a')
        esc('the switcher', '#switcher')
        # the tasks list, with the keys on one of its buttons
        self.browser.click('#tasks-toggle')
        self.browser.wait(shown('#tasks-list'), what='the tasks list open')
        self.browser.eval('(()=>{const b=document.querySelector("#tasks-list button,#tasks-views button,#tasks-list [tabindex],#tasks-toggle");if(b)b.focus();return "ok"})()')
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.activeElement.closest("#tasks"))'), 'the keys inside the tasks list')
        self.browser.press('Escape')
        self.browser.wait(hidden('#tasks-list'), what='the tasks list folded by Esc')
        self.assertEqual(self.browser.eval('JSON.stringify(document.activeElement.id)'), 'tasks-toggle')
        # the search box, the details, the help, the settings, the long-text dialog, the form of the question, each from inside
        self.browser.press('/')
        self.browser.wait(shown('#find'), what='the search')
        self.browser.press('a')
        esc('the search', '#find')
        self.browser.press('i')
        self.browser.wait('JSON.stringify(document.querySelector("#info").getAttribute("aria-pressed")==="true")', what='the details')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#info").getAttribute("aria-pressed")==="false")', what='the details closed by Esc')
        for what, open_js, sel in (('the help', 'showHelp()', '#help'), ('the settings', 'openNotify()', '#notify'), ('the long-text dialog', 'openSnip(false)', '#snip'), ('the form of the question', 'openAnswer()', '#answer')):
            self.browser.eval('(()=>{%s;return "ok"})()' % open_js)
            self.browser.wait(shown(sel), what=what)
            self.browser.press('Tab')
            self.assertTrue(self.browser.eval('JSON.stringify(!!document.activeElement.closest(%s))' % json.dumps(sel)), what + ': the keys inside it')
            esc(what, sel)
        # a notice: Esc takes it away when nothing else is open
        self.browser.eval('(()=>{toast("הודעה קצרה");return "ok"})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll(".toast").length===1)', what='the notice')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelectorAll(".toast").length===0)', what='the notice gone after Esc')
        # on the phone the picture reader is a step of the history: Esc goes back all the same
        self.open_thread(SIZES[0], 'e2e-esc', 'אסקייפ סוגר הכול')
        self.browser.wait('JSON.stringify(!!document.querySelector(".pics img"))', timeout=20, what='the picture')
        self.browser.click('.pics img')
        self.browser.wait(shown('#reader'), what='the picture reader on the phone')
        esc('the picture reader on the phone', '#reader')

if __name__ == '__main__':
    unittest.main()
