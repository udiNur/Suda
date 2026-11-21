#!/usr/bin/env python3
"""End to end: the page and the diagram library are kept on the device (suda-fixes 30, approved by the owner, m130).

Measured on his weak link (netlab): every opening read suda.html again in the background (230 KB), the page asked
the server for the file's date every 30 s with a HEAD, and every load that showed a diagram read
vendor/mermaid.min.js again (1.66 MB on the wire): the diagram frame is sandboxed with no origin of its own, so the
browser's cache never helps it. On a slow link the frame gave up after 20 s.

Now: the worker's reading of the page behind an opening, and the page's own check for a newer build, ask the server
with If-Modified-Since (a 304, no body, when the file was not written since); the page keeps the diagram library
in a cache named after its version and hands its text to the frame; the frame's wait goes on while bytes still
arrive. The same harness as test_e2e.py (headless Chrome, the real board server on loopback, where a worker is
allowed; a temporary board), with a server that writes down every request and its answer.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import shutil
import subprocess
import time
import unittest

import test_e2e
from test_e2e import SIZES

NODE = shutil.which('node')
DIAGRAM = '```mermaid\nflowchart LR\n  A[לפני] --> B[אחרי]\n```'
DRAWN = 'JSON.stringify(!!document.querySelector("#log figure.diagram .diagram-pic"))'

# A small DevTools client in node: attaches to the page's target and sets the network's conditions for as long as
# it runs. One JSON per line on stdin, "ok" per line on stdout.
CDP = r"""
const [url,match]=process.argv.slice(1);
const ws=new WebSocket(url);let id=0;const waiting=new Map();
const send=(method,params={},sessionId)=>new Promise((ok,bad)=>{const n=++id;waiting.set(n,{ok,bad});ws.send(JSON.stringify({id:n,method,params,...(sessionId?{sessionId}:{})}));});
// the conditions now, given to every frame of the page too (a sandboxed frame is a target of its own)
let now={offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1};const sessions=new Set();
const apply=async sid=>{await send('Network.enable',{},sid);await send('Network.emulateNetworkConditions',now,sid);};
ws.onmessage=async e=>{
  const m=JSON.parse(e.data);
  if(m.id&&waiting.has(m.id)){const w=waiting.get(m.id);waiting.delete(m.id);m.error?w.bad(Error(JSON.stringify(m.error))):w.ok(m.result);return;}
  if(m.method==='Target.attachedToTarget'){
    const sid=m.params.sessionId;sessions.add(sid);
    try{await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:true,flatten:true},sid);await apply(sid);}catch{}
    try{await send('Runtime.runIfWaitingForDebugger',{},sid);}catch{}
  }
};
ws.onerror=()=>process.exit(2);
ws.onopen=async()=>{
  try{
    const {targetInfos}=await send('Target.getTargets');
    const page=targetInfos.find(t=>t.type==='page'&&t.url.includes(match));
    if(!page)throw Error('no page with '+match);
    const session=(await send('Target.attachToTarget',{targetId:page.targetId,flatten:true})).sessionId;
    sessions.add(session);await send('Network.enable',{},session);
    await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:true,flatten:true},session);
    console.log('ready');
    let buf='';
    process.stdin.on('data',async d=>{
      buf+=d;let at;
      while((at=buf.indexOf('\n'))>=0){
        const p=JSON.parse(buf.slice(0,at));buf=buf.slice(at+1);
        now={offline:false,latency:p.latency||0,downloadThroughput:p.down||-1,uploadThroughput:p.up||-1};
        try{for(const sid of sessions)await send('Network.emulateNetworkConditions',now,sid).catch(()=>{});console.log('ok');}
        catch(e){console.log('error '+e.message);}
      }
    });
    process.stdin.on('end',()=>process.exit(0));
  }catch(e){console.error(e.message);process.exit(3);}
};
"""


class Link:
    def __init__(self, browser, match):
        url = browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1].strip()
        self.proc = subprocess.Popen([NODE, '-e', CDP, url, match], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if self.proc.stdout.readline().strip() != 'ready':
            raise RuntimeError('the DevTools client did not start: ' + self.proc.stderr.read()[-300:])

    def set(self, latency=0, down=-1, up=-1):
        self.proc.stdin.write(json.dumps({'latency': latency, 'down': down, 'up': up}) + '\n')
        self.proc.stdin.flush()
        answer = self.proc.stdout.readline().strip()
        if answer != 'ok':
            raise RuntimeError(answer)

    def close(self):
        try:
            self.set()
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


class Cache(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    link = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Logging(base):
            log = []            # (method, path, status) of every request

            def send_response(self, code, message=None):
                Logging.log.append((self.command, self.path.split('?')[0], code))
                return super().send_response(code, message)
        cls.logging = Logging
        cls.server.RequestHandlerClass = Logging

    def tearDown(self):
        if self.link:
            self.link.close()
            Cache.link = None

    def asked(self, end, method=None):
        return [(m, s) for m, p, s in self.logging.log if p.endswith(end) and (method is None or m == method)]

    def with_worker(self, tid, title):
        self.open_thread(SIZES[2], tid, title)
        ok = self.browser.eval('(async()=>{if(!("serviceWorker" in navigator)||!window.isSecureContext)return "false";await navigator.serviceWorker.ready;return "true";})()')
        if not ok:
            self.skipTest('this browser allows no worker on a loopback page')
        # the next opening is the worker's
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait('JSON.stringify(!!navigator.serviceWorker.controller)', timeout=20, what='the worker in charge of the page')

    def diagram_thread(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', '-', '--by', 'e2e', '--state', 'working', '--note', 'דיאגרמה', input='דיאגרמה\n\n' + DIAGRAM)

    def test_an_opening_reads_the_page_only_when_it_changed(self):
        tid, title = 'e2e-cache-open', 'פתיחה בלי לקרוא שוב'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.with_worker(tid, title)
        time.sleep(1.5)                                     # (the worker's reading behind the last opening)
        del self.logging.log[:]
        for _ in range(3):
            self.open_thread(SIZES[2], tid, title)
        time.sleep(2)
        got = self.asked('/suda.html', 'GET')
        self.assertTrue(got, 'the worker read nothing behind the openings')
        self.assertEqual([s for m, s in got if s == 200], [], 'the page was read whole again: %s' % got)

    def test_the_build_check_asks_once_and_reads_nothing_when_the_page_did_not_change(self):
        tid, title = 'e2e-cache-build', 'בדיקת גרסה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        page = self.board / 'suda.html'
        original = page.read_text(encoding='utf-8')
        self.addCleanup(page.write_text, original, encoding='utf-8')
        self.with_worker(tid, title)
        time.sleep(1.5)
        del self.logging.log[:]
        for _ in range(3):
            self.browser.eval('(async()=>{buildChecked=0;await checkBuild(0);return "ok";})()')
        got = self.asked('/suda.html')
        self.assertEqual(self.asked('/suda.html', 'HEAD'), [], 'a HEAD and then a GET: two requests where one does')
        self.assertEqual(len(got), 3, got)
        self.assertTrue(all(s == 304 for m, s in got), got)
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#newer").hidden)'))
        # another build: the same one request reads it, and the strip says so
        changed = original.replace('<span data-t>Go to a topic</span>', '<span data-t>Go to a topic </span>')      # (the markup is English, translated in the page)
        self.assertNotEqual(changed, original)
        time.sleep(1.1)                                     # (Last-Modified is in whole seconds)
        page.write_text(changed, encoding='utf-8')
        self.browser.eval('(async()=>{buildChecked=0;await checkBuild(0);return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#newer").hidden)', timeout=15, what='the strip for the new build')

    def test_the_diagram_library_is_read_once_across_openings(self):
        tid, title = 'e2e-cache-mermaid', 'ספריית הדיאגרמות נשמרת'
        self.diagram_thread(tid, title)
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait(DRAWN, timeout=60, what='the diagram drawn')
        before = len(self.asked('/vendor/mermaid.min.js', 'GET'))
        for _ in range(2):
            self.open_thread(SIZES[2], tid, title)
            self.browser.wait(DRAWN, timeout=60, what='the diagram drawn again')
        self.assertEqual(len(self.asked('/vendor/mermaid.min.js', 'GET')), before, self.asked('/vendor/mermaid.min.js'))

    @unittest.skipUnless(NODE, 'node is not installed')
    def test_a_diagram_is_drawn_on_a_line_that_needs_longer_than_20_s_for_the_library(self):
        tid, title = 'e2e-cache-slow', 'דיאגרמה בקו איטי'
        self.diagram_thread(tid, title)
        self.ok('new', tid + '-plain', 'בלי דיאגרמה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid + '-plain', 'בלי דיאגרמה')
        self.assertFalse(self.browser.eval(DRAWN))
        # nothing kept yet: the library comes over the line
        self.browser.eval('(async()=>{for(const k of await caches.keys())if(!k.startsWith("suda-shell"))await caches.delete(k);return "ok";})()')
        Cache.link = Link(self.browser, '/suda.html?s=desktop&n=%d' % test_e2e.Suda.visits)
        size = (test_e2e.SKILL.parent / 'threads').exists() and 0
        rate = 150000                                       # bytes a second: the library (5.5 MB as this server sends it) takes 35 s
        self.link.set(latency=100, down=rate, up=rate)
        t0 = time.monotonic()
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait(DRAWN, timeout=120, what='the diagram drawn on a slow line')
        self.assertGreater(time.monotonic() - t0, 20, 'the line was not slow enough to test the wait')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Cache.__dict__:
        setattr(Cache, _name, None)


if __name__ == '__main__':
    unittest.main()
