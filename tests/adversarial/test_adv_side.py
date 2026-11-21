#!/usr/bin/env python3
"""Hostile review of savings164 (askSince, sideFetch: the files beside the board asked "changed since?").

Every test asserts the SAFE outcome, so a FAIL is a real hole.

  - the page's clock moved back after a full read: the minute's full read must still come;
  - the server's clock moved back (a 304 dated before the kept copy's Date): the page must read in full;
  - two reads of one path in flight, the older answer landing last: the next read must still give the newest;
  - a body cut off half way (the cuttable fetch): nothing bad is kept;
  - end to end: the project's own writer (boardlib.atomic_write_text) whose write lands in the same second as the
    copy before it, renamed only after the page read that copy (a slow fsync): the next read must give it;
  - the gateway (a copy of the Caddy config, on 127.0.0.1 only): Date and Last-Modified pass, a 304 passes.

Run: THREADS_BOARDLIB_DIR=$HOME/.claude/skills/html-interview-board python3 test_adv_side.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import email.utils
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = _paths.APP
PAGE = (ROOT / 'suda.html').read_text(encoding='utf-8')
PURE = PAGE.split('// <pure>')[1].split('// </pure>')[0]
SIDE = PAGE.split('// <side>')[1].split('// </side>')[0] if '// <side>' in PAGE else ''
NODE = shutil.which('node')
SKILL = Path(os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board')))
CADDY = Path(os.environ.get('SUDA_TEST_CADDY', '/nonexistent'))     # (a caddy binary, when this machine has one)


def node(script):
    r = subprocess.run([NODE, '-e', "'use strict';\n" + script], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return r.stdout


@unittest.skipUnless(NODE, 'node is not installed')
class Clocks(unittest.TestCase):
    def test_a_full_read_dated_in_the_future_is_due_now(self):
        """The phone's clock moved back an hour after the last full read (NTP, a manual fix, a dead battery):
        nowMs - full is negative, and the "in full at least once a minute" promise is gone for that hour."""
        node(PURE + r"""
        const assert=require('assert');
        const T=Date.parse('Fri, 20 Nov 2026 01:00:00 GMT'),http=ms=>new Date(ms).toUTCString(),now=1_000_000_000;
        const held={lm:http(T),date:http(T+10000),full:now+3600000};
        assert.strictEqual(askSince(held,now),'','a full read "an hour from now" still trusted: '+askSince(held,now));
        """)

    def run_js(self, body, fake):
        self.assertTrue(SIDE, 'suda.html has no // <side> block')
        return json.loads(node(PURE + fake + SIDE + '\n(async()=>{' + body + '})().catch(e=>{console.error(e);process.exit(1);});'))

    FILE = r"""
    const assert=require('assert');
    // a server like SimpleHTTPRequestHandler: 304 when the file's whole-second time <= If-Modified-Since
    let file={body:'{"v":1}',lm:'Fri, 20 Nov 2026 01:00:00 GMT'},srvClock='Fri, 20 Nov 2026 01:00:30 GMT';const asked=[];
    const serve=ims=>ims&&Date.parse(file.lm)<=Date.parse(ims)?new Response(null,{status:304,headers:{Date:srvClock}})
      :new Response(file.body,{status:200,headers:{'Last-Modified':file.lm,Date:srvClock}});
    globalThis.fetch=async(url,opts)=>{const ims=opts&&opts.headers&&opts.headers['If-Modified-Since']||'';asked.push(ims);return serve(ims);};
    """

    def test_a_304_dated_before_the_kept_copy_is_not_believed(self):
        """The Mac's clock steps back 40 s (timed after a wake, a manual fix). A write after the step gets a time
        before the kept copy's Last-Modified, so the server answers 304 to a changed file. The 304 itself says so:
        its Date is before the kept copy's Date. The page must then read in full."""
        got = self.run_js(r"""
          await sideFetch('live.json');                                  // v1 kept: LM 01:00:00, Date 01:00:30
          srvClock='Fri, 20 Nov 2026 00:59:50 GMT';                         // the clock went back 40 s
          file={body:'{"v":2}',lm:'Fri, 20 Nov 2026 00:59:45 GMT'};     // written after the step
          const text=await (await sideFetch('live.json')).text();
          console.log(JSON.stringify({text,asked}));
        """, self.FILE)
        self.assertEqual(got['text'], '{"v":2}', got)

    def test_two_reads_in_flight_the_older_landing_last_never_hide_the_newer(self):
        got = self.run_js(r"""
          let release;const gate=new Promise(r=>release=r);
          const first=globalThis.fetch;let n=0;
          globalThis.fetch=async(url,opts)=>{const r=await first(url,opts);if(n++===0)await gate;return r;};
          const a=sideFetch('drafts.json');                              // served v1, delivered late
          await new Promise(r=>setTimeout(r,10));
          file={body:'{"v":2}',lm:'Fri, 20 Nov 2026 01:00:20 GMT'};
          const b=await (await sideFetch('drafts.json')).text();         // served v2, delivered first
          release();const aText=await (await a).text();                  // v1 lands last and is kept
          const c=await (await sideFetch('drafts.json')).text();
          console.log(JSON.stringify({aText,b,c,asked}));
        """, self.FILE)
        self.assertEqual((got['aText'], got['b'], got['c']), ('{"v":1}', '{"v":2}', '{"v":2}'), got)

    def test_a_body_cut_half_way_keeps_nothing_bad(self):
        got = self.run_js(r"""
          await sideFetch('places.json');                                // v1 kept (old enough)
          file={body:'{"v":2}',lm:'Fri, 20 Nov 2026 01:00:20 GMT'};
          const plain=globalThis.fetch;
          globalThis.fetch=async(url,opts)=>{const r=await plain(url,opts);if(r.status!==200)return r;
            return new Response(new ReadableStream({start(c){c.error(new DOMException('cut','AbortError'));}}),{status:200,headers:r.headers});};
          let cut=false;try{await sideFetch('places.json');}catch{cut=true;}
          globalThis.fetch=plain;
          const after=await (await sideFetch('places.json')).text();
          console.log(JSON.stringify({cut,after,asked}));
        """, self.FILE)
        self.assertTrue(got['cut'], got)
        self.assertEqual(got['after'], '{"v":2}', got)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(CADDY.is_file() and (SKILL / 'answer_server.py').is_file(), 'no caddy (SUDA_TEST_CADDY) or no board server')
class Gateway(unittest.TestCase):
    """The gateway's own handling (encode zstd/gzip + reverse_proxy, as a gateway in front of the board has it) between the page and the
    board server: a copy on 127.0.0.1, never the real one."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='.adv-side-gw-', dir=ROOT)
        root = Path(cls.tmp.name)
        (root / 'boards' / 'b').mkdir(parents=True)
        cls.file = root / 'boards' / 'b' / 'links.json'
        cls.file.write_text(json.dumps({'links': {str(i): 'x' * 40 for i in range(40)}}), encoding='utf-8')
        old = time.time() - 30
        os.utime(cls.file, (old, old))
        sys.path.insert(0, str(SKILL))
        os.environ.setdefault('BOARDS_DIR', str(root / 'boards'))
        spec = importlib.util.spec_from_file_location('answer_server_adv_side', SKILL / 'answer_server.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ROOT = root / 'boards'
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), mod.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.gw = free_port()
        conf = root / 'Caddyfile'
        conf.write_text('{\n\tadmin off\n\tauto_https off\n\tstorage file_system {\n\t\troot %s\n\t}\n}\n'
                        'http://127.0.0.1:%d {\n\tencode {\n\t\tzstd better\n\t\tgzip 6\n\t}\n'
                        '\theader Alt-Svc `h3=":443"; ma=86400`\n\troute {\n\t\thandle {\n'
                        '\t\t\treverse_proxy 127.0.0.1:%d {\n\t\t\t\tflush_interval -1\n\t\t\t}\n\t\t}\n\t}\n}\n'
                        % (root / 'data', cls.gw, cls.server.server_address[1]))
        cls.caddy = subprocess.Popen([str(CADDY), 'run', '--config', str(conf), '--adapter', 'caddyfile'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.gw), 0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.caddy.terminate()
        cls.caddy.wait(5)
        cls.server.shutdown()
        cls.tmp.cleanup()

    def get(self, headers):
        c = http.client.HTTPConnection('127.0.0.1', self.gw, timeout=5)
        c.request('GET', '/b/links.json?t=1', headers={'Accept-Encoding': 'zstd, gzip', **headers})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def test_dates_pass_and_a_304_passes_through_the_gateway(self):
        status, h, body = self.get({})
        self.assertEqual(status, 200)
        lm, date = h.get('Last-Modified'), h.get('Date')
        self.assertTrue(lm and date, h)
        self.assertEqual(lm, email.utils.formatdate(int(self.file.stat().st_mtime), usegmt=True))
        status, h2, body2 = self.get({'If-Modified-Since': lm})
        self.assertEqual((status, body2), (304, b''), h2)


if os.environ.get('SIDE_E2E', '1') == '1':
    import test_e2e
    from test_e2e import SIZES

    ASK = r"""(async()=>{const r=await sideFetch(%s);return JSON.stringify({status:r.status,text:await r.text()});})()"""

    class Writers(test_e2e.Suda):
        TID = 'adv-side'

        def setUp(self):
            if self.TID not in self.state()['threads']:
                self.ok('new', self.TID, 'קבצים לצד הלוח', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')

        def ask(self, name):
            return self.browser.eval(ASK % json.dumps(name))

        # boardlib.atomic_write_text lives in the shared board skill (not this repo): Suda's own writers of these files
        # set the time again after the rename (threads.side_write, live_hook.write_atomic; test_threads.SideWriteTests).
        # The same fix in boardlib itself is offered to the integrator; until then this stays an expected failure.
        @unittest.expectedFailure
        def test_a_slow_atomic_write_in_the_same_second_is_never_hidden(self):
            """boardlib.atomic_write_text (threads.py's writer of drafts, places and links) gives the file the time
            of its flush, not of its rename. Two saves in one second (a scroll, then another), the second one's
            fsync slow (a busy disk): the page reads the first copy 2 s on (trusted), the second lands after it
            with the first one's second. The next read must give the second save."""
            self.open_thread(SIZES[2], self.TID, 'קבצים לצד הלוח')
            bl = sys.modules['boardlib']
            path = self.board / 'adv-slow.json'
            while time.time() % 1 > 0.1:
                time.sleep(0.005)
            second = int(time.time())
            bl.atomic_write_text(path, '{"v":"first"}\n')
            real, slow_ones = os.fsync, set()

            def fsync(fd):
                if threading.current_thread() in slow_ones:
                    time.sleep(3.6)
                return real(fd)
            os.fsync = fsync
            try:
                writer = threading.Thread(target=bl.atomic_write_text, args=(path, '{"v":"second"}\n'))
                slow_ones.add(writer)
                writer.start()
                while time.time() < second + 2.2:
                    time.sleep(0.01)
                self.assertEqual(self.ask(path.name)['text'], '{"v":"first"}\n')
                writer.join()
            finally:
                os.fsync = real
            self.assertEqual(int(path.stat().st_mtime), second, 'the second save kept the first one\'s second')
            self.assertEqual(self.ask(path.name)['text'], '{"v":"second"}\n')

    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in Writers.__dict__:
            setattr(Writers, _name, None)


if __name__ == '__main__':
    unittest.main()
