#!/usr/bin/env python3
"""End to end: a bad link that is not 2G (suda-fixes 20, the owner's m59).

In a restaurant his speed test said: latency 84 ms idle and 952 ms under load, 1.75 Mbps down, 0.2 Mbps up, no
loss. The slow link mode read only download speed and stayed off there. Here the same harness as test_e2e.py
(headless Chrome, the real board server on loopback, a temporary board) runs under Chrome's own network emulation
(the DevTools protocol, Network.emulateNetworkConditions, on the page's target) with profiles of his numbers:

- loaded: 952 ms latency, 1.75 Mbps down, 0.2 Mbps up. The mode turns on, and says why ("השהיה גבוהה"); a
  picture and a reply sent under it land exactly once and in his order, the picture goes up with its progress on the
  screen, the reply behind it says it waits for it, and the upload is measured slow ("העלאה איטית").
- idle: 84 ms latency, the same speeds. The latency alone does not turn the mode on; his picture's slow upload does.
- a line that drops in the middle of a picture's upload and comes back: the picture lands once.
- no emulation: the mode stays off.

navigator.connection is stood in for as a 4G link that saves nothing, so that only what the page measures decides.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import json
import os
import random
import shutil
import struct
import subprocess
import time
import unittest
import zlib
from pathlib import Path

import test_e2e
from test_e2e import SIZES

NODE = shutil.which('node')
MBIT = 1000000 / 8          # bytes per second in one Mbps
LOADED = {'latency': 952, 'down': 1.75 * MBIT, 'up': 0.2 * MBIT}
IDLE = {'latency': 84, 'down': 1.75 * MBIT, 'up': 0.2 * MBIT}

# A small DevTools client in node: attaches to the page's target, sets the network's conditions, and keeps the
# session open (the conditions last as long as it does). Reads one JSON per line on stdin; answers "ok" per line.
CDP = r"""
const [url,match]=process.argv.slice(1);
const ws=new WebSocket(url);let id=0,session=null;const waiting=new Map();
const send=(method,params={},sessionId)=>new Promise((ok,bad)=>{const n=++id;waiting.set(n,{ok,bad});ws.send(JSON.stringify({id:n,method,params,...(sessionId?{sessionId}:{})}));});
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&waiting.has(m.id)){const w=waiting.get(m.id);waiting.delete(m.id);m.error?w.bad(Error(JSON.stringify(m.error))):w.ok(m.result);}};
ws.onerror=e=>{console.error('ws error');process.exit(2);};
ws.onopen=async()=>{
  try{
    const {targetInfos}=await send('Target.getTargets');
    const page=targetInfos.find(t=>t.type==='page'&&t.url.includes(match));
    if(!page)throw Error('no page with '+match+': '+targetInfos.map(t=>t.url).join(' '));
    session=(await send('Target.attachToTarget',{targetId:page.targetId,flatten:true})).sessionId;
    await send('Network.enable',{},session);
    console.log('ready');
    let buf='';
    process.stdin.on('data',async d=>{
      buf+=d;let at;
      while((at=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,at);buf=buf.slice(at+1);
        const p=JSON.parse(line);
        try{
          await send('Network.emulateNetworkConditions',{offline:!!p.offline,latency:p.latency||0,downloadThroughput:p.down||-1,uploadThroughput:p.up||-1},session);
          console.log('ok');
        }catch(e){console.log('error '+e.message);}
      }
    });
    process.stdin.on('end',()=>process.exit(0));
  }catch(e){console.error(e.message);process.exit(3);}
};
"""


def noisy_png(w, h, seed=7):
    """A picture that does not compress (random pixels): its JPEG stays big enough to measure an upload."""
    rnd = random.Random(seed)
    raw = b''.join(b'\x00' + bytes(rnd.getrandbits(8) for _ in range(w * 3)) for _ in range(h))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class Link:
    """The page's network, under the DevTools protocol, for as long as this lives."""

    def __init__(self, browser, match):
        r = browser.run('get', 'cdp-url')
        url = r.stdout.strip().splitlines()[-1].strip()
        self.proc = subprocess.Popen([NODE, '-e', CDP, url, match], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()
        if line != 'ready':
            raise RuntimeError('the DevTools client did not start: %r %s' % (line, self.proc.stderr.read()[-400:]))

    def set(self, latency=0, down=-1, up=-1, offline=False):
        self.proc.stdin.write(json.dumps({'latency': latency, 'down': down, 'up': up, 'offline': offline}) + '\n')
        self.proc.stdin.flush()
        answer = self.proc.stdout.readline().strip()
        if answer != 'ok':
            raise RuntimeError('emulateNetworkConditions: ' + answer)

    def profile(self, p):
        self.set(p['latency'], p['down'], p['up'])

    def close(self):
        try:
            self.set()                 # the line as it was
        except Exception:
            pass
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


# navigator.connection as a 4G link that saves nothing: only what the page measures decides.
FOUR_G = ('(()=>{Object.defineProperty(navigator,"connection",{configurable:true,value:{effectiveType:"4g",saveData:false,downlink:10,rtt:50,'
          'addEventListener(){},removeEventListener(){}}});judgeLink();return "ok";})()')
STATE = 'JSON.stringify({on:slowState.on,why:slowState.why,whys:slowState.whys,up:slowState.up,waits:linkWaits.slice(),beats:linkBeats.slice(),ups:linkUps.slice()})'
LINES = 'JSON.stringify([...document.querySelectorAll("#log .msg.own .delivery")].map(d=>(d.querySelector("span")||d).innerText))'


@unittest.skipUnless(NODE, 'node is not installed')
class BadLink(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    link = None

    def tearDown(self):
        if self.link:
            self.link.close()
            BadLink.link = None

    def start(self, tid, title, profile):
        """The thread open on a desktop, then the line under the profile (the page itself loads on a quick line)."""
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, title)
        self.assertEqual(self.browser.eval(FOUR_G), 'ok')
        # what an earlier test chose on this device (media, his pictures) is not this test's
        self.browser.eval('(()=>{for(const k of ["slow-media","own-full"])localStorage.removeItem(%s+":"+k);judgeLink();return "ok";})()' % json.dumps(test_e2e.SLUG))
        BadLink.link = Link(self.browser, '/suda.html?s=desktop&n=%d' % test_e2e.Suda.visits)
        if profile:
            self.link.profile(profile)

    def agent_says(self, tid, n):
        """Agents write n times: each is a change, and the page reads it (its small change file, or the summary)."""
        for i in range(n):
            self.ok('say', tid, '--from', 'fork', 'עדכון %d' % i, '--by', 'e2e', '--state', 'working', '--note', 'עדכון %d' % i)
            time.sleep(1.5)

    def landed(self, tid, text=None, pictures=False):
        msgs = [m for m in self.thread(tid)['messages'] if m.get('from') == 'owner']
        if pictures:
            return [m for m in msgs if m.get('images')]
        return [m for m in msgs if m.get('text') == text]

    def picture(self, name, w=640, h=480):
        path = Path(self.tmp.name) / name
        path.write_bytes(noisy_png(w, h))
        return path

    def test_his_loaded_numbers_turn_it_on_and_a_picture_and_a_reply_land_once_in_order(self):
        tid, title = 'e2e-loaded', 'מסעדה תחת עומס'
        self.start(tid, title, LOADED)
        self.agent_says(tid, 4)
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.on&&s.whys.includes("wait")?JSON.stringify(s):"";})()' % STATE, timeout=40,
                                what='the mode on, for the latency')
        waits = [w['ms'] for w in got['waits']]
        self.assertGreaterEqual(sorted(waits)[-3], 700, got)
        # the settings say why
        words = self.browser.eval('JSON.stringify(slowWords(slowState))')
        self.assertIn('השהיה גבוהה', words)
        # a picture, and right after it a reply: the reply waits behind the picture, and says so
        self.browser.upload('#pic-file', self.picture('restaurant.png'))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
        self.browser.click('#send')
        text = 'תשובה אחרי התמונה'
        self.browser.fill('#input', text)
        self.browser.click('#send')
        seen = set()
        end = time.monotonic() + 120
        while time.monotonic() < end:
            for line in self.browser.eval(LINES) or []:
                seen.add(line)
            if self.landed(tid, pictures=True) and self.landed(tid, text):
                break
            time.sleep(0.3)
        self.assertTrue(any(l.startswith('שולח…') and '%' in l for l in seen), seen)
        self.assertIn('ממתין לשליחה: יישלח אחרי ההודעה הקודמת', seen)
        # exactly once each, and in his order
        pics, replies = self.landed(tid, pictures=True), self.landed(tid, text)
        self.assertEqual((len(pics), len(replies)), (1, 1), (pics, replies))
        ids = [m['id'] for m in self.thread(tid)['messages']]
        self.assertLess(ids.index(pics[0]['id']), ids.index(replies[0]['id']))
        # the picture was shrunk harder (the mode was on when it was chosen) and its upload was measured slow
        self.assertLessEqual(max(pics[0]['images'][0].get('w') or 0, pics[0]['images'][0].get('h') or 0), 1280)
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.up?JSON.stringify(s):"";})()' % STATE, timeout=10, what='the upload measured slow')
        self.assertIn('up', got['whys'])
        self.assertLess(got['ups'][-1]['bytes'] * 1000 / got['ups'][-1]['ms'], 50000, got)
        self.assertIn('העלאה איטית', self.browser.eval('JSON.stringify(slowWords(slowState))'))
        # and nothing is left waiting
        self.browser.wait('JSON.stringify(%s.every(l=>!l||!/שולח|ממתין|עוד לא נשלח/.test(l)))' % LINES.replace('JSON.stringify(', '(', 1), timeout=20,
                          what='every line settled')

    def test_his_idle_latency_alone_does_not_turn_it_on_but_his_slow_upload_does(self):
        tid, title = 'e2e-idle', 'מסעדה בשקט'
        self.start(tid, title, IDLE)
        self.agent_says(tid, 4)
        got = self.browser.eval(STATE)
        self.assertGreaterEqual(len(got['waits']), 3, got)
        self.assertFalse(got['on'], got)
        self.browser.upload('#pic-file', self.picture('idle.png'))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
        self.browser.click('#send')
        self.until(lambda: self.landed(tid, pictures=True), timeout=90, what='the picture')
        got = self.browser.wait('(()=>{const s=JSON.parse(%s);return s.on?JSON.stringify(s):"";})()' % STATE, timeout=10, what='the mode on, for the upload')
        self.assertEqual(got['whys'], ['up'], got)
        self.assertTrue(got['up'])
        self.assertEqual(len(self.landed(tid, pictures=True)), 1)

    def test_a_line_that_drops_in_the_middle_of_an_upload_lands_the_picture_once(self):
        tid, title = 'e2e-drop', 'מסעדה עם ניתוק'
        self.start(tid, title, IDLE)
        self.browser.upload('#pic-file', self.picture('drop.png', 800, 600))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
        self.browser.click('#send')
        self.browser.wait('JSON.stringify(%s.some(l=>/שולח… [1-9]/.test(l)))' % LINES.replace('JSON.stringify(', '(', 1), timeout=30, what='the upload under way')
        self.link.set(offline=True)
        time.sleep(4)
        self.link.profile(IDLE)
        self.browser.eval('(()=>{dispatchEvent(new Event("online"));return "ok";})()')
        self.until(lambda: self.landed(tid, pictures=True), timeout=120, what='the picture after the drop')
        time.sleep(3)
        self.assertEqual(len(self.landed(tid, pictures=True)), 1)

    def test_a_picture_still_going_up_when_the_line_comes_back_is_not_cut(self):
        """When the line comes back (sse153's lineBack), what left before it is cut and sent again on a fresh
        connection. A picture whose body moved a moment ago is on a live connection: on 0.2 Mbps cutting it would
        throw away the seconds it already took. It lands once, and is never sent again."""
        tid, title = 'e2e-back', 'מסעדה, הקו חוזר'
        self.start(tid, title, IDLE)
        self.browser.upload('#pic-file', self.picture('back.png', 800, 600))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
        self.browser.click('#send')
        self.browser.wait('JSON.stringify(%s.some(l=>/שולח… [1-9]/.test(l)))' % LINES.replace('JSON.stringify(', '(', 1), timeout=30, what='the upload under way')
        time.sleep(1.5)
        self.browser.eval('(()=>{lineBack();return "ok";})()')
        seen = set()
        end = time.monotonic() + 90
        while time.monotonic() < end and not self.landed(tid, pictures=True):
            seen.update(self.browser.eval(LINES) or [])
            time.sleep(0.3)
        self.assertEqual(len(self.landed(tid, pictures=True)), 1)
        self.assertFalse([l for l in seen if 'שולח שוב' in l], seen)
        tries = self.browser.eval('JSON.stringify([...optimistic.values()].flat().filter(m=>m.images).map(m=>m.tries||0))')
        self.assertTrue(all(t == 0 for t in tries), tries)

    def test_he_chooses_whether_his_pictures_go_full_size(self):
        """The owner (suda-fixes m195): "let me choose, but by default what I chose". In the settings, beside the
        choice for media: his own pictures at full size even on a slow link, or shrunk there. Unset, it follows his
        media choice ("always load": full size). Kept on this device."""
        tid, title = 'e2e-full', 'תמונות בגודל מלא'
        self.start(tid, title, None)
        key = lambda k: json.dumps(test_e2e.SLUG + ':' + k)
        self.browser.eval('(()=>{localStorage.removeItem(%s);localStorage.setItem(%s,"load");return "ok";})()' % (key('own-full'), key('slow-media')))
        self.assertTrue(self.browser.eval('JSON.stringify(ownFullNow())'), 'always load: full size by default')
        # "always tap": the mode is on, and by default his pictures are shrunk
        self.browser.eval('(()=>{setSlowChoice("tap");openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .own-full"))', timeout=10, what='the setting')
        chips = 'JSON.stringify([...document.querySelectorAll("#notify-body .own-full button")].map(b=>[b.textContent,b.getAttribute("aria-pressed")]))'
        self.assertEqual(self.browser.eval(chips), [['כמו בקליטה טובה', 'false'], ['מוקטנות בקליטה איטית', 'true']])
        tray_w = 'JSON.stringify((pictures.get(view.ch)||[]).map(p=>Math.max(p.w,p.h)))'
        clear = '(()=>{pictures.delete(view.ch);renderTray();return "ok";})()'
        pic = Path(self.tmp.name) / 'full.png'
        pic.write_bytes(test_e2e.png(1500, 1000, shade=40))
        self.browser.upload('#pic-file', pic)
        self.browser.wait('JSON.stringify(%s.length===1)' % tray_w.replace('JSON.stringify(', '(', 1), timeout=20, what='the picture in the tray')
        self.assertEqual(self.browser.eval(tray_w), [1280])
        # made smaller than the original: it says the original's sides (to the server, and kept on the device)
        shrunk = 'JSON.stringify((pictures.get(view.ch)||[]).map(p=>[p.shrunk||null,forTray([p])[0].shrunk||null,picturesForSend([p])[0].shrunk||null]))'
        self.assertEqual(self.browser.eval(shrunk), [[{'w': 1500, 'h': 1000}] * 3])
        self.assertEqual(self.browser.eval('JSON.stringify(fromTray(forTray(pictures.get(view.ch))).map(p=>p.shrunk||null))'), [{'w': 1500, 'h': 1000}])
        self.browser.eval(clear)
        # he chooses full size: the next picture keeps its 1500 px, and the choice is kept on this device
        self.browser.eval('(()=>{[...document.querySelectorAll("#notify-body .own-full button")].find(b=>b.textContent==="כמו בקליטה טובה").click();return "ok";})()')
        self.browser.wait('JSON.stringify(localStorage.getItem(%s)==="on")' % key('own-full'), timeout=10, what='the choice kept')
        self.assertEqual(self.browser.eval(chips), [['כמו בקליטה טובה', 'true'], ['מוקטנות בקליטה איטית', 'false']])
        self.assertNotIn('מוקטנות יותר', self.browser.eval('JSON.stringify(document.querySelector("#notify-body .slow-state").textContent)'))
        self.browser.upload('#pic-file', pic)
        self.browser.wait('JSON.stringify(%s.length===1)' % tray_w.replace('JSON.stringify(', '(', 1), timeout=20, what='the picture in the tray')
        self.assertEqual(self.browser.eval(tray_w), [1500])
        self.assertEqual(self.browser.eval(shrunk), [[None, None, None]], 'not made smaller: no mark')
        self.browser.eval(clear)
        # and from Cmd+K, back to shrunk
        self.browser.eval('(()=>{const c=actions().find(c=>c.id==="own-full:off");c.run();return "ok";})()')
        self.assertEqual(self.browser.eval('JSON.stringify(localStorage.getItem(%s))' % key('own-full')), 'off')
        self.assertTrue(self.browser.eval('JSON.stringify(actions().some(c=>c.id==="own-full:on"))'))

    def test_a_big_recording_on_a_slow_upload_keeps_his_order_when_the_line_comes_back(self):
        """The path this branch adds: a recording over 50 KB goes by XMLHttpRequest (postBig). On his 0.2 Mbps upload
        it takes seconds; he writes a reply meanwhile, and the line comes back twice while the recording is still
        going up (lineBack, as a reopened line or the probe does). The reply waits behind it and says so, the
        recording is not cut while its body moves, and each lands once, in his order."""
        tid, title = 'e2e-voice-order', 'הקלטה גדולה ואחריה תשובה'
        self.start(tid, title, IDLE)
        # a real recording of over 100 KB (Opus in webm, as the browser records it), handed to the page's own sendVoice
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is not installed')
        clip = Path(self.tmp.name) / 'long.webm'
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anoisesrc=d=50:c=pink:a=0.3', '-c:a', 'libopus', '-b:a', '24k', str(clip)],
                       check=True, timeout=60)
        self.assertGreater(clip.stat().st_size, 100000)
        # every big send the page starts is counted (a cut one is sent again from its first byte)
        self.browser.eval('(()=>{window.__bigSends=0;const send=XMLHttpRequest.prototype.send;XMLHttpRequest.prototype.send=function(b){window.__bigSends++;return send.call(this,b);};return "ok";})()')
        self.browser.eval('(()=>{const b=Uint8Array.from(atob(%s),c=>c.charCodeAt(0));'
                          'sendVoice({thread:%s,seconds:50,blob:new Blob([b],{type:"audio/webm"}),type:"audio/webm"});return "ok";})()'
                          % (json.dumps(base64.b64encode(clip.read_bytes()).decode()), json.dumps(tid)))
        self.browser.wait('JSON.stringify(%s.some(l=>/שולח… [0-9]+%%/.test(l)))' % LINES.replace('JSON.stringify(', '(', 1), timeout=30, what='the recording going up')
        text = 'כתבתי אחרי ההקלטה'
        self.browser.fill('#input', text)
        self.browser.click('#send')
        self.browser.wait('JSON.stringify(%s.includes("ממתין לשליחה: יישלח אחרי ההודעה הקודמת"))' % LINES.replace('JSON.stringify(', '(', 1), timeout=10,
                          what='the reply saying it waits behind the recording')
        for _ in range(2):
            time.sleep(1.5)
            self.browser.eval('(()=>{lineBack();return "ok";})()')
        mine = lambda: [m for m in self.thread(tid)['messages'] if m.get('from') == 'owner']
        try:
            self.until(lambda: len(mine()) >= 2, timeout=120, what='both on the server')
        except AssertionError:
            print('DEBUG', self.browser.eval('JSON.stringify([...optimistic.values()].flat().map(m=>({voice:!!m.voice,text:m.text,delivery:m.delivery,tries:m.tries,heard:m.heard,error:m.error,sent:m.sent})))'), self.browser.eval(LINES), [(m.get('text'), bool(m.get('voice'))) for m in mine()])
            raise
        time.sleep(2)
        got = mine()
        self.assertEqual(len(got), 2, got)
        self.assertTrue(got[0].get('voice'), 'the recording first: %s' % [(m.get('text'), bool(m.get('voice'))) for m in got])
        self.assertEqual(got[1].get('text'), text)
        self.assertEqual(self.browser.eval('JSON.stringify(window.__bigSends)'), 1, 'the recording was cut and sent again while it moved')

    def test_a_good_link_stays_off(self):
        tid, title = 'e2e-good', 'בבית'
        self.start(tid, title, None)
        self.agent_says(tid, 4)
        self.browser.upload('#pic-file', self.picture('home.png'))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#tray img, .tray img").length>0)', timeout=20, what='the picture in the tray')
        self.browser.click('#send')
        self.until(lambda: self.landed(tid, pictures=True), timeout=30, what='the picture')
        time.sleep(1)
        got = self.browser.eval(STATE)
        self.assertFalse(got['on'], got)
        self.assertFalse(got['up'], got)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in BadLink.__dict__:
        setattr(BadLink, _name, None)


if __name__ == '__main__':
    unittest.main()
