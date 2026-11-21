#!/usr/bin/env python3
"""Hostile review of suda-fixes 30 (the page and the diagram library kept on his device): each test asserts the
SAFE outcome, so a failing test is a hole. The same harness as test_e2e.py (headless Chrome through agent-browser,
the real board server on loopback, a temporary board), with a server that can hold a read of the library open.

The holes:
  * diagram.html#given takes a script from whatever page is its parent and runs it. Suda's frame is sandboxed,
    but any other site can frame diagram.html WITHOUT a sandbox and run its script in the board's own origin
    (his threads, /api/state as him).
  * a library read that is not mermaid (cut short, a portal page) is kept under its version and given forever.
  * (older than the change) the worker's reading behind an opening never keeps anything: the kept Response it
    was given was already read by the opening, its clone() throws.
  * the worker's If-Modified-Since has whole seconds: a copy of the page kept from a write that a second write in
    the same second replaced (a page read while `threads install` wrote it) is never read again.
  * a library read the page gave up on goes on, and the next diagram starts another one next to it.
Pinned (they pass, marked so): an opening from the kept copy still shows a build written before it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import select
import socket
import threading
import time
import unittest

import test_e2e
from test_e2e import SIZES, SLUG

DIAGRAM = '```mermaid\nflowchart LR\n  A[לפני] --> B[אחרי]\n```'
DRAWN = 'JSON.stringify(!!document.querySelector("#log figure.diagram .diagram-pic"))'
FAILED = 'JSON.stringify([...document.querySelectorAll("#log figure.diagram .diagram-note")].some(n=>n.textContent.includes("לא ניתן לצייר")))'
KEPT_PAGE = ('(async()=>{const c=await caches.open("suda-shell-1"),r=await c.match(location.pathname);'
             'return JSON.stringify(r?(await r.arrayBuffer()).byteLength:-1);})()')
DROP_VENDOR = '(async()=>{for(const k of await caches.keys())if(k.startsWith("suda-vendor-"))await caches.delete(k);return "ok";})()'


class AdvCache(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Stall(base):
            """When `on`: a read of the library gets its headers and 256 KB, then nothing, until the browser lets
            the connection go (or the test ends). `now`/`most` count the reads held open at once."""
            on = False
            now = most = 0
            lock = threading.Lock()
            stop = threading.Event()

            def do_GET(self):
                if Stall.on and self.path.split('?')[0].endswith('/vendor/mermaid.min.js'):
                    return self.stall()
                return super().do_GET()

            def stall(self):
                data = (cls.board / 'vendor' / 'mermaid.min.js').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/javascript')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data[:262144])
                    self.wfile.flush()
                except OSError:
                    self.close_connection = True
                    return
                with Stall.lock:
                    Stall.now += 1
                    Stall.most = max(Stall.most, Stall.now)
                try:
                    end = time.monotonic() + 150
                    while not Stall.stop.is_set() and time.monotonic() < end:
                        ready, _, _ = select.select([self.connection], [], [], 0.3)
                        if ready:
                            try:
                                if not self.connection.recv(1, socket.MSG_PEEK):
                                    break               # the browser closed it
                            except OSError:
                                break
                finally:
                    with Stall.lock:
                        Stall.now -= 1
                self.close_connection = True
        cls.stall = Stall
        cls.server.RequestHandlerClass = Stall

    def diagram_thread(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', '-', '--by', 'e2e', '--state', 'working', '--note', 'דיאגרמה', input='דיאגרמה\n\n' + DIAGRAM)

    def with_worker(self, tid, title):
        self.open_thread(SIZES[2], tid, title)
        ok = self.browser.eval('(async()=>{if(!("serviceWorker" in navigator)||!window.isSecureContext)return "false";await navigator.serviceWorker.ready;return "true";})()')
        if not ok:
            self.skipTest('this browser allows no worker on a loopback page')
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait('JSON.stringify(!!navigator.serviceWorker.controller)', timeout=20, what='the worker in charge of the page')

    def raw_open(self):
        """An opening that does not wait for the page to work (a page cut short never shows its reply box)."""
        test_e2e.Suda.visits += 1
        self.browser.open(self.url + '?s=desktop&n=%d' % test_e2e.Suda.visits)

    # ── the frame takes a script from its parent: any site is a parent ──────────

    def test_another_site_cannot_run_a_script_in_the_boards_origin_through_diagram_html(self):
        """HOLE (important, security): diagram.html#given injects any {kind:'mermaid',source} its parent posts as a
        <script>. Suda's own frame is sandboxed (no origin), but nothing stops another site from framing
        https://suda.example.com/threads/diagram.html#given WITHOUT a sandbox: the board sends no frame-ancestors or
        X-Frame-Options, and the frame checks only that the message comes from its parent, which here is the
        attacker. The attacker's script then runs in the board's origin: it reads state.json (every thread) and
        can POST /api/state as him (same Origin and Host, so the server's and the gateway's guards pass), which
        tells the agents what to do. Before the change diagram.html ran no script it was given."""
        evil_dir = self.boards / 'adv-evil'
        evil_dir.mkdir(exist_ok=True)
        target = '%s/%s/diagram.html#given' % (self.origin, SLUG)
        (evil_dir / 'evil.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>another site</title>'
            '<iframe id="f" src="%s"></iframe><script>\n'
            'window.got=null;window.asked=false;\n'
            'const payload="window.mermaid={};fetch(\\"/%s/state.json\\").then(r=>r.text()).then(t=>'
            'parent.postMessage({kind:\\"pwned\\",origin:location.origin,read:t.length},\\"*\\"));";\n'
            'addEventListener("message",e=>{const d=e.data||{};\n'
            ' if(d.kind==="diagram-wants"){window.asked=true;e.source.postMessage({kind:"mermaid",source:payload},"*");}\n'
            ' if(d.kind==="pwned")window.got=d;});\n'
            '</script>' % (target, SLUG), encoding='utf-8')
        self.addCleanup(lambda: (evil_dir / 'evil.html').unlink(missing_ok=True))
        test_e2e.Suda.visits += 1
        self.browser.open('http://localhost:%d/adv-evil/evil.html?n=%d' % (self.port, test_e2e.Suda.visits))
        self.browser.wait('JSON.stringify(document.title==="another site")', what='the other site')
        self.assertNotEqual(self.browser.eval('JSON.stringify(location.origin)'), self.origin, 'the test page must be another origin')
        time.sleep(4)
        got = self.browser.eval('JSON.stringify(window.got)')
        self.assertIsNone(got, 'a script from another site ran in the board\'s origin through diagram.html#given: %s' % got)

    # ── a broken library kept forever ──────────────────────────────────────────

    def test_a_library_that_is_not_mermaid_is_not_kept_and_given_forever(self):
        """HOLE (important): mermaidSource keeps whatever a 200 brought, unchecked, in 'suda-vendor-12.3.0', and
        from then on gives that copy and never reads the file again. `threads install` rewrites
        vendor/mermaid.min.js in place (copytree), so a read during the copy gets a whole response that is cut
        short (the server sends the size it saw when it opened the file); a captive portal or a login page answers
        200 with HTML. The frame says 'diagram-broken', the page gives up, and the next diagram takes the same
        broken copy from the cache: no diagram draws on that device until MERMAID_V changes. Before the change the
        frame read the file each time and a later diagram drew."""
        lib = self.board / 'vendor' / 'mermaid.min.js'
        whole = lib.read_bytes()
        self.addCleanup(lib.write_bytes, whole)
        tid, title = 'adv-cache-cut', 'ספרייה חתוכה'
        self.diagram_thread(tid, title)
        self.ok('new', tid + '-plain', 'בלי דיאגרמה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid + '-plain', 'בלי דיאגרמה')
        self.browser.eval(DROP_VENDOR)
        lib.write_bytes(whole[:len(whole) // 3])          # what a read in the middle of the install's copy gets
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait(FAILED, timeout=60, what='the diagram not drawn from a cut library')
        lib.write_bytes(whole)                            # the install finished
        self.open_thread(SIZES[2], tid, title)            # a new opening: a new frame, a new reading
        self.browser.wait('JSON.stringify(%s||%s)' % (DRAWN[len('JSON.stringify('):-1], FAILED[len('JSON.stringify('):-1]),
                          timeout=60, what='the diagram drawn or given up')
        self.assertTrue(self.browser.eval(DRAWN), 'the cut library was kept and given again: the diagram is not drawn with the whole file on the server')

    # ── the worker's kept page is never replaced behind an opening ─────────────

    def test_the_reading_behind_an_opening_keeps_the_servers_page(self):
        """HOLE (important, older than this change, and this change keeps it): openShell answers the opening with
        the kept Response and hands the SAME object to readShell as `was`; by the time the server answers,
        the browser has read that body, so `before.clone()` throws ('body already used'), readShell fails before
        cache.put, and the reading behind an opening never keeps anything (nor tells the pages). Only the page's
        own check (through the worker, with no `was`) replaces the kept copy. A kept copy whose script cannot run
        its check (a page cut short while `threads install` wrote it, any broken build) is shown on every opening
        for good, though the server has a good page. With the 304 of this change the 200 case still goes through
        the same clone."""
        tid, title = 'adv-cache-behind', 'קריאה מאחורי הפתיחה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        page = self.board / 'suda.html'
        whole = page.read_bytes()

        def restore():
            page.write_bytes(whole)
            os.utime(page, None)
            try:
                self.browser.eval('(async()=>{await caches.delete("suda-shell-1");return "ok";})()')
            except Exception:
                pass
        self.addCleanup(restore)
        self.with_worker(tid, title)
        time.sleep(1.5)
        broken = b'<!doctype html><meta charset="utf-8"><title>broken build</title><p>a build that runs no script</p>'
        page.write_bytes(broken)                          # a broken build, a later second
        self.browser.eval('(async()=>{buildChecked=0;await checkBuild(0);return "ok";})()')    # the page's own check keeps it
        time.sleep(1)
        if self.browser.eval(KEPT_PAGE) != len(broken):
            self.skipTest('the page\'s check did not keep the broken build: the scenario did not set up')
        time.sleep(1.1)
        page.write_bytes(whole)                           # the good build again, written a later second
        for _ in range(2):
            self.raw_open()                               # the broken copy shows; the server's is read behind it
            time.sleep(3)
        self.assertEqual(self.browser.eval(KEPT_PAGE), len(whole), 'the reading behind two openings kept nothing: the broken build stays')
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector("#input"))'), 'the second opening still shows the broken build')

    # ── the worker's kept page and a write in the same second ────────────────

    def test_a_page_kept_from_a_write_replaced_in_the_same_second_is_read_again(self):
        """HOLE (important, rare but lasting): the worker now asks with If-Modified-Since = the kept copy's
        Last-Modified, in whole seconds, and the board server answers 304 for a file whose mtime is not later
        (Python's SimpleHTTPRequestHandler: mtime <= date). A copy kept from a write that was replaced within the
        same second is never read again. The bad case: the worker reads suda.html while `threads install` writes it
        (copyfile truncates, then writes): the response is whole but cut short; the install ends in the same
        second; from then on every opening shows the cut page (no script runs, so not even the page's own check),
        and every reading behind it gets a 304. (Today the clone hole above hides this one: with openShell giving
        readShell a clone, this test passes on the worker before the change and still fails on this one, checked.)"""
        tid, title = 'adv-cache-shell', 'עמוד חתוך שנשמר'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        page = self.board / 'suda.html'
        whole = page.read_bytes()

        def restore():
            page.write_bytes(whole)
            os.utime(page, None)
            try:
                self.browser.eval('(async()=>{await caches.delete("suda-shell-1");return "ok";})()')
            except Exception:
                pass
        self.addCleanup(restore)
        self.with_worker(tid, title)
        time.sleep(1.5)
        cut = whole[:len(whole) // 2]
        second = int(time.time()) + 2
        page.write_bytes(cut)                             # the install has written half the page
        os.utime(page, (second, second))
        self.open_thread(SIZES[2], tid, title)            # the kept copy shows; the worker reads the server's behind it
        time.sleep(2.5)
        kept = self.browser.eval(KEPT_PAGE)
        if kept != len(cut):
            self.skipTest('the worker did not keep the cut copy (%s of %s bytes): the scenario did not set up' % (kept, len(cut)))
        page.write_bytes(whole)                           # the install ends, in the same second
        os.utime(page, (second + 0.5, second + 0.5))
        for _ in range(2):
            self.raw_open()
            time.sleep(3)
        self.assertEqual(self.browser.eval(KEPT_PAGE), len(whole),
                         'the worker still keeps the page cut short (every opening shows it), the server has the whole page')

    # ── a read given up goes on ────────────────────────────────────────────────

    def test_a_library_read_given_up_is_not_read_twice_at_once(self):
        """HOLE (minor): when the frame gives up (nothing for QUIET_MS), mermaidSource's fetch is not aborted: on a
        dead line it holds its connection (one of the six a browser has per server over HTTP/1.1, as on
        http://192.0.2.10:8767), and when the next diagram asks, a second 5.5 MB read starts next to the first,
        both on the same slow line his messages need. Safe: the page lets the given-up read go, or the next diagram
        waits for the one already coming; never two at once."""
        Stall = self.stall
        tid, title = 'adv-cache-stall', 'קריאה שננטשה'
        self.diagram_thread(tid, title)
        self.diagram_thread(tid + '-2', 'קריאה שנייה')
        self.ok('new', tid + '-plain', 'בלי דיאגרמה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid + '-plain', 'בלי דיאגרמה')
        self.browser.eval(DROP_VENDOR)
        Stall.stop.clear()
        Stall.most = 0
        Stall.on = True

        def done():
            Stall.on = False
            Stall.stop.set()
        self.addCleanup(done)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait(FAILED, timeout=60, what='the page giving up on a dead line')
        time.sleep(3)                                     # (time for a read given up to be let go)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid + '-2'))
        self.browser.wait('JSON.stringify(view.ch===%s&&!!document.querySelector("#log figure.diagram"))' % json.dumps(tid + '-2'),
                          timeout=20, what='the second diagram')
        time.sleep(4)
        self.assertLessEqual(Stall.most, 1, 'two reads of the library open at once: the one given up was not let go')

    # ── pinned ──────────────────────────────────────────────────────────────────

    def test_pinned_an_opening_from_the_kept_copy_shows_a_build_written_before_it(self):
        """PINNED (passes): the page opened from the worker's kept copy takes its date (document.lastModified) from
        the kept copy's Last-Modified, so its If-Modified-Since is not 'now' and a build written before the opening
        is still read and offered."""
        tid, title = 'adv-cache-before', 'גרסה שנכתבה לפני הפתיחה'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        page = self.board / 'suda.html'
        original = page.read_text(encoding='utf-8')

        def restore():
            page.write_text(original, encoding='utf-8')
            try:
                self.browser.eval('(async()=>{await caches.delete("suda-shell-1");return "ok";})()')
            except Exception:
                pass
        self.addCleanup(restore)
        self.with_worker(tid, title)
        time.sleep(1.5)
        changed = original.replace('<span data-t>Go to a topic</span>', '<span data-t>Go to a topic </span>')      # (the markup is English, translated in the page)
        self.assertNotEqual(changed, original)
        time.sleep(1.1)
        page.write_text(changed, encoding='utf-8')
        time.sleep(1.1)
        self.open_thread(SIZES[2], tid, title)            # the old build, from the kept copy
        self.browser.wait('JSON.stringify(!document.querySelector("#newer").hidden)', timeout=20, what='the strip for the build written before the opening')

    # (master's pinned test that board.html still draws a diagram is not here: this line has no board.html, suda m620)

for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvCache.__dict__:
        setattr(AdvCache, _name, None)


if __name__ == '__main__':
    unittest.main()
