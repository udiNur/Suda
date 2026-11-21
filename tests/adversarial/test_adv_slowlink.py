#!/usr/bin/env python3
"""Hostile review of the bad-link change (suda-fixes 20, m59): linkState, waits, beats, ups, postBig, shrinkPlan.

Each test asserts the SAFE outcome, so a failing test is a hole. Tests marked "pinned" pass on 6c9c463: they
record a safe behavior that was checked and should stay.

The pure part runs under node like test_slack.py (the page between `// <pure>` and `// </pure>`). The end to end
part uses the harness of test_e2e.py (headless Chrome, the real board server on loopback, a temporary board),
with the page reached through a small proxy on 127.0.0.1 that carries what the browser sends at 25 KB/s
(0.2 Mbps, his restaurant's upload) and what comes back at full speed. Unlike Chrome's own network emulation
(which throttles inside the browser, before the socket), the proxy is a slow line the way a real one is: the
browser hands the body to its socket at once, and the line drains it slowly.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import socket
import threading
import time
import unittest
from pathlib import Path

import test_slack

NODE = shutil.which('node')


class SlowLinkPure(unittest.TestCase):
    page, node, pure_js = test_slack.SlackPageTests.page, test_slack.SlackPageTests.node, test_slack.SlackPageTests.pure_js

    # ── holes ──────────────────────────────────────────────────────────────

    def test_a_swinging_link_does_not_turn_the_mode_off_again_and_again(self):
        """The hold is counted from the moment the mode turned on, not from the last time the link was slow. So once
        the mode has been on longer than its hold, the first three calm reads turn it off at once, and those calm
        reads are the mode's own doing (the media waits, the link goes idle). Off, the media loads, the link is
        loaded again, on again. In his restaurant (952 ms loaded, 90 ms idle) the mode goes off 5 times in the
        first 32 minutes, and then every 30 minutes for as long as he stays: each time every held picture and
        video of the conversation starts loading on a 1.75 Mbps line."""
        self.pure_js(r"""
        let s=linkState('auto',{},{},null,0),waits=[],offs=[];
        const beats=[10500,10600,10400,10500,10600,10500];
        for(let t=0;t<40*60000;t+=5000){
          waits.push(s.on?90:950);waits=waits.slice(-6);           // off: the media loads and the line is loaded
          const n=linkState('auto',{},{waits,beats},s,t);
          if(s.on&&!n.on)offs.push(Math.round(t/1000));
          s=n;
        }
        assert.ok(offs.length<=2,'the mode went off at '+offs.join(', ')+' s');
        """)

    def test_latency_samples_from_an_hour_ago_do_not_keep_the_mode_on(self):
        """The waits have no age. The page measures one only when it reads a small board file (a change file,
        mostly when the board changes), so on a quiet board the three slow waits of the restaurant stay the
        last word: an hour later, at home, with the server's heartbeat coming on time every 10 s (and judging
        the link each time), the mode is still on and every picture still waits for a tap. The beats prove the
        line calm; the waits are never asked again."""
        self.pure_js(r"""
        // (the page keeps each wait with the moment it was measured; a bare number is one of this moment)
        const slow=[{ms:900,t:0},{ms:950,t:0},{ms:900,t:0}];
        const on=linkState('auto',{},{waits:slow},null,0);
        assert.strictEqual(on.on,true);
        const calm=[10200,10300,10100,10200,10300,10200].map(ms=>({ms,t:3590000}));
        const later=linkState('auto',{},{waits:slow,beats:calm},on,3600000);
        assert.strictEqual(later.on,false,JSON.stringify(later));
        """)

    def test_a_message_found_at_the_load_does_not_say_it_waits_behind_another(self):
        """`behind` (and `sent`) are kept in the stored outbox (forStorage keeps every field) and unsentAtLoad
        carries them back. A reply that waited behind a picture when the page went away comes back at the next
        load saying "ממתין לשליחה: יישלח אחרי ההודעה הקודמת" also when the picture already reached the server
        (it is let go at the load) and nothing is before it; and when its own pictures are still coming back
        from the device's store it keeps saying so for as long as that takes. What it waits for is not known
        at the load: these words are not his to read until the page sees it behind another again."""
        self.pure_js(r"""
        const stored=forStorage({cid:'c2',from:'owner',text:'תשובה',delivery:'waiting',auto:true,behind:true,tries:0,ts:100,sent:[60000,300000]});
        const back=unsentAtLoad(JSON.parse(JSON.stringify(stored)),101);
        assert.strictEqual(back.delivery,'waiting');
        assert.ok(!back.behind,'behind came back: '+JSON.stringify(back));
        assert.ok(!back.sent,'sent came back: '+JSON.stringify(back));
        assert.ok(!deliveryLine(back).includes('אחרי ההודעה הקודמת'),deliveryLine(back));
        """)

    def test_a_big_send_that_still_moves_is_not_cut_at_ten_minutes(self):
        """SKILL.md now tells the agents a big send "is cut and sent again only when nothing moved for 20 s", and
        postBig says it is given up only when nothing moves. sendDeadline also cuts every send at 10 minutes
        from its start, moving or not. On 0.2 Mbps (25 KB/s) 10 minutes carry 15 MB: a long recording (its
        base64 is a third bigger) or a message with several big pictures that is still going up steadily is
        cut at 600 s, sent again from the first byte, cut again; each cut has no answer while the line is up,
        so it counts as "deaf" and after 5 tries (50 minutes of his upload) it fails with "השרת לא עונה להודעה
        הזאת, אף שהחיבור תקין", which is not what happened."""
        self.pure_js(r"""
        const bytes=16e6,start=0,moved=599000;                     // the last progress a second before the 10th minute
        assert.ok(sendDeadline(bytes,start,moved)>=moved+SEND_LIMIT,'cut at '+sendDeadline(bytes,start,moved)+' ms');
        """)

    # ── pinned: checked, and safe ──────────────────────────────────────────

    def test_pinned_odd_measures_and_an_odd_before_never_throw(self):
        """Pinned (passes): strings, NaN, null entries and a `was` from an older page (no whys, a string `at`)
        do not throw and do not turn the mode on."""
        self.pure_js(r"""
        for(const m of [{waits:'abc'},{waits:[NaN,'800',null]},{beats:{}},{beats:[Infinity,-5,'x']},{ups:[null,{bytes:'60000',ms:'0',t:0}]},null,'x',{reads:'x'}])
          assert.strictEqual(linkState('auto',{},m,null,1000).on,false,JSON.stringify(m));
        for(const was of [{on:true,why:'wait',at:'x'},{on:true,whys:'wait'},{on:true,why:5},{on:true,why:'measured',at:0},'x',7])
          assert.doesNotThrow(()=>linkState('auto',{},{},was,1e6));
        // an old {on, why, at} that the mode turned on by itself, no whys: held, then off
        assert.strictEqual(linkState('auto',{},{},{on:true,why:'measured',at:1e6-1000},1e6).on,true);
        assert.strictEqual(linkState('auto',{},{},{on:true,why:'measured',at:0},1e6).on,false);
        assert.doesNotThrow(()=>slowWords({on:true,whys:[1,null,'wait']}));
        assert.doesNotThrow(()=>slowMarkText({on:true,why:'up',whys:null}));
        """)

    def test_pinned_one_late_heartbeat_or_one_slow_moment_does_not_turn_it_on(self):
        """Pinned (passes): one late beat (a short sleep, a busy main thread, a server hiccup), a beat across a
        hidden stretch, the first beat after the line opened, and two slow waits of one moment do not turn it on."""
        self.pure_js(r"""
        const off=linkState('auto',{},{},null,0);
        assert.strictEqual(linkState('auto',{},{beats:[10400,45000,10300,10500]},off,1e5).on,false);
        assert.strictEqual(beatGap(1000,40000,[[5000,30000]]),null);         // the page was hidden between them
        assert.strictEqual(beatGap(null,40000,[]),null);                      // no beat before it (the line has just opened)
        assert.strictEqual(beatGap(1000,70000,[]),null);                      // a line that stood still: not lateness
        assert.strictEqual(linkState('auto',{},{waits:[90,1500,1400,90,90,90]},off,1e5).on,false);
        """)

    def test_pinned_pictures_are_shrunk_by_the_state_and_his_choice_of_load_still_shrinks_on_a_slow_upload(self):
        """Pinned (passes): shrinkPlan follows the state: 1024/0.6 when uploads are slow, also when he chose
        "תמיד לטעון" (which keeps the mode off but not his uploads fast); 1280/0.7 when on; 1600/0.82 otherwise.
        (Whether "תמיד לטעון" should also mean "send my pictures as they are" is a question for the owner.)"""
        self.pure_js(r"""
        const slowUps=[{bytes:300000,ms:12000,t:0}];
        const load=linkState('load',{},{ups:slowUps},null,1000);
        assert.strictEqual(load.on,false);assert.strictEqual(load.up,true);
        assert.deepStrictEqual(shrinkPlan(load),{side:1024,quality:0.6});
        assert.deepStrictEqual(shrinkPlan({on:true}),{side:1280,quality:0.7});
        assert.deepStrictEqual(shrinkPlan(null),{side:PICTURE_SIDE,quality:0.82});
        assert.deepStrictEqual(shrinkPlan('x'),{side:PICTURE_SIDE,quality:0.82});
        """)

    def test_pinned_what_is_posted_never_carries_sent_or_behind(self):
        """Pinned (checked by reading deliver): the reply's state is built field by field (op, thread, text, cid,
        images, voice, ...), so msg.sent and msg.behind never reach the server."""
        page = self.page()
        body = page.split('async function deliver(id,msg){', 1)[1].split('\n}\n', 1)[0]
        build = body.split("const state=msg.answer?", 1)[1].split('const parts=', 1)[0]
        self.assertNotIn('state.sent', build)
        self.assertNotIn('state.behind', build)
        self.assertNotIn('...msg', build)


# ── end to end: a line whose upload is slow the way a real one is ─────────────────────────────────────────

class SlowUpProxy:
    """127.0.0.1 only. Forwards to the board server; what the browser sends goes on at `rate` bytes a second,
    what comes back at full speed. Its own receive buffer is small, so the only place a body can wait is the
    browser's own socket (on a phone: its send buffer), as on a slow line."""

    def __init__(self, target_port, rate):
        self.target, self.rate = target_port, rate
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
        self.lsock.bind(('127.0.0.1', 0))
        self.lsock.listen(64)
        self.port = self.lsock.getsockname()[1]
        self.carried = []           # (time, bytes) of every chunk carried up
        self.stop = False
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.stop:
            try:
                c, _ = self.lsock.accept()
            except OSError:
                return
            try:
                c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
                s = socket.create_connection(('127.0.0.1', self.target))
            except OSError:
                c.close()
                continue
            threading.Thread(target=self.up, args=(c, s), daemon=True).start()
            threading.Thread(target=self.down, args=(s, c), daemon=True).start()

    def up(self, c, s):
        step = 0.05
        try:
            while True:
                data = c.recv(max(1, int(self.rate * step)))
                if not data:
                    break
                self.carried.append((time.monotonic(), len(data)))
                s.sendall(data)
                time.sleep(len(data) / self.rate)
        except OSError:
            pass
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def down(self, s, c):
        try:
            while True:
                data = s.recv(65536)
                if not data:
                    break
                c.sendall(data)
        except OSError:
            pass
        for sock in (c, s):
            try:
                sock.close()
            except OSError:
                pass

    def close(self):
        self.stop = True
        try:
            self.lsock.close()
        except OSError:
            pass


if os.environ.get('THREADS_BOARDLIB_DIR') or (Path.home() / '.claude/skills/html-interview-board').is_dir():
    import test_e2e
    from test_e2e import SIZES

    FOUR_G = ('(()=>{Object.defineProperty(navigator,"connection",{configurable:true,value:{effectiveType:"4g",saveData:false,downlink:10,rtt:50,'
              'addEventListener(){},removeEventListener(){}}});judgeLink();return "ok";})()')
    STATE = 'JSON.stringify({on:slowState.on,whys:slowState.whys,up:slowState.up,ups:linkUps.slice()})'
    LINES = '[...document.querySelectorAll("#log .msg.own .delivery")].map(d=>(d.querySelector("span")||d).innerText)'

    @unittest.skipUnless(NODE, 'node is not installed')
    class SlowUpload(test_e2e.Suda):
        """Only the scenarios of this file: the ones inherited from test_e2e run there."""

        proxy = None

        def tearDown(self):
            if self.proxy:
                self.proxy.close()
                SlowUpload.proxy = None

        def test_a_picture_through_a_25_kb_s_upload_is_measured_slow_and_not_called_uploaded_early(self):
            """upHeard times a send from its start to xhr.upload's load, and the progress line takes e.loaded as
            "up". Both count the bytes the browser handed to its socket, not the bytes that crossed the line: a
            picture's body fits in the socket's send buffer (128 KB and more on a Mac; 512 KB and more for Wi-Fi
            and LTE on Android), so on his 0.2 Mbps upload it is "up" in a moment. The upload is measured fast
            (the reason "העלאה איטית" never comes, the hardest shrink never applies, the mode is not turned on by
            his uploads), and the line under the message says "הועלה. מחכה לאישור מהשרת…" while most of the
            body is still on its way. Chrome's network emulation throttles before the socket, so
            test_e2e_slowlink does not see this."""
            tid, title = 'adv-slowup', 'העלאה איטית אמיתית'
            self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            rate = 25000
            SlowUpload.proxy = SlowUpProxy(self.port, rate)
            self.url = 'http://127.0.0.1:%d/%s/suda.html' % (self.proxy.port, test_e2e.SLUG)
            self.open_thread(SIZES[2], tid, title)
            self.assertEqual(self.browser.eval(FOUR_G), 'ok')
            # a picture that does not compress, at its plan's size: its body is a few hundred KB
            import test_e2e_slowlink
            path = Path(self.tmp.name) / 'adv-slowup.png'
            path.write_bytes(test_e2e_slowlink.noisy_png(640, 480, seed=11))
            self.browser.upload('#pic-file', path)
            self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
            self.browser.eval('(()=>{window.__lines=[];window.__t0=performance.now();let was="";const tick=()=>{const now=%s;'
                              'if(now.join("|")!==was){was=now.join("|");for(const l of now)window.__lines.push([Math.round(performance.now()-window.__t0),l]);}'
                              'if(window.__lines.length<2000)setTimeout(tick,100);};tick();return "ok";})()' % LINES)
            self.browser.click('#send')
            msgs = self.until(lambda: [m for m in self.thread(tid)['messages'] if m.get('from') == 'owner' and m.get('images')], timeout=120, what='the picture')
            self.assertEqual(len(msgs), 1)
            got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.ups.length?JSON.stringify(s):"";})()' % STATE, timeout=10, what='an upload measured')
            lines = self.browser.eval('JSON.stringify(window.__lines)')
            up = got['ups'][-1]
            measured = up['bytes'] * 1000 / up['ms']
            first_uploaded = next((t for t, l in lines if l.startswith('הועלה')), None)
            last_sending = max((t for t, l in lines if l.startswith('שולח')), default=None)
            report = 'body %d B; measured %.0f B/s in %d ms; the line carries %d B/s; "uploaded" shown at %s ms, sending until %s ms; whys %s' % (
                up['bytes'], measured, up['ms'], rate, first_uploaded, last_sending, got['whys'])
            # the safe outcome: a 25 KB/s upload is read as slow (under 50 KB/s), and the mode says why
            self.assertLess(measured, 50000, report)
            self.assertIn('up', got['whys'], report)
            # and "uploaded" is not on the screen while most of the body has yet to cross the line (the page cannot
            # know when it crossed: it never says it is up before the server answered)
            if first_uploaded is not None:
                self.assertGreater(first_uploaded, 0.5 * up['bytes'] * 1000 / rate, report)
            self.assertTrue(any('מחכה לאישור מהשרת' in l for t, l in lines), report)

    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in SlowUpload.__dict__:
            setattr(SlowUpload, _name, None)


if __name__ == '__main__':
    unittest.main()
