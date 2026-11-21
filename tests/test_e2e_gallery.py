#!/usr/bin/env python3
"""End to end: the pictures of a thread open as a gallery (the owner, thread suda m395).

"When you send pictures I always want to be able to move between them by scrolling. But mind that scrolling is
not mixed up with the state in which I enlarge a picture and move it with my finger." The same harness as
test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). The fingers are real ones:
the browser itself is told to swipe and to pinch (Chrome's own gesture commands), so what is checked is what the
browser does with a finger, not what a script pretends.

What is checked: a press on a picture opens it among all the pictures of its thread, in their order; a swipe
moves to the next one; in a picture that was enlarged the same swipe moves over the picture and the gallery stays
where it is, until the picture's edge; two fingers enlarge and never turn the page; a double tap enlarges and
brings back; the arrows, the side buttons, Esc and the phone's Back do what they say; and only the pictures near
the one on the screen are loaded.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import json
import os
import socket
import struct
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

import test_e2e
from test_e2e import SIZES, png


class Cdp:
    """Chrome's own remote control, spoken over a plain socket: enough to make a finger swipe and two fingers pinch."""

    def __init__(self, url):
        at = urlparse(url)
        self.sock = socket.create_connection((at.hostname, at.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n'
                           % (at.path or '/', at.hostname, at.port, key)).encode())
        head = b''
        while b'\r\n\r\n' not in head:
            head += self.sock.recv(4096)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise RuntimeError('no websocket: ' + head[:80].decode('latin1'))
        self.rest, self.n, self.session = head.split(b'\r\n\r\n', 1)[1], 0, None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, text):
        raw, mask = text.encode(), os.urandom(4)
        head = b'\x81' + (bytes([0x80 | len(raw)]) if len(raw) < 126 else bytes([0x80 | 126]) + struct.pack('>H', len(raw)) if len(raw) < 65536
                           else bytes([0x80 | 127]) + struct.pack('>Q', len(raw)))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))

    def _take(self, n):
        while len(self.rest) < n:
            more = self.sock.recv(65536)
            if not more:
                raise RuntimeError('the browser closed the line')
            self.rest += more
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def _recv(self):
        text = b''
        while True:
            a, b = self._take(2)
            size = b & 0x7f
            if size == 126:
                size = struct.unpack('>H', self._take(2))[0]
            elif size == 127:
                size = struct.unpack('>Q', self._take(8))[0]
            body = self._take(size)
            if a & 0x0f in (0, 1):
                text += body
                if a & 0x80:
                    return json.loads(text)
            elif a & 0x0f == 8:
                raise RuntimeError('the browser closed the line')

    def call(self, method, params=None, timeout=60):
        self.n += 1
        msg = {'id': self.n, 'method': method, 'params': params or {}}
        if self.session:
            msg['sessionId'] = self.session
        self._send(json.dumps(msg))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = self._recv()
            if got.get('id') == self.n:
                if 'error' in got:
                    raise RuntimeError('%s: %s' % (method, got['error']))
                return got.get('result', {})
        raise RuntimeError(method + ': no answer')

    def page(self, part):
        """Speak to the page whose address holds `part`."""
        target = next(t for t in self.call('Target.getTargets')['targetInfos'] if t['type'] == 'page' and part in t['url'])
        self.session = self.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})['sessionId']

    def swipe(self, x, y, dx, dy=0, speed=1200):
        """One finger put down at (x, y) and moved by (dx, dy): what the browser does with it is the browser's own."""
        self.call('Input.synthesizeScrollGesture', {'x': x, 'y': y, 'xDistance': dx, 'yDistance': dy, 'speed': speed, 'gestureSourceType': 'touch', 'preventFling': True})

    def touch(self, kind, points):
        self.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [{'x': round(px), 'y': round(py), 'id': n, 'radiusX': 8, 'radiusY': 8, 'force': 1} for n, (px, py) in enumerate(points)]})

    def pinch(self, x, y, factor, drift=0, steps=14):
        """Two fingers put down around (x, y) and moved apart (factor > 1) or together, as real touches; `drift` px is
        how far the middle between them wanders sideways on the way (a hand is never exact)."""
        near, far = (40, 40 * factor) if factor > 1 else (40 / factor, 40)
        self.touch('touchStart', [(x - near, y)])
        self.touch('touchStart', [(x - near, y), (x + near, y)])
        for i in range(1, steps + 1):
            half, mid = near + (far - near) * i / steps, x + drift * i / steps
            self.touch('touchMove', [(mid - half, y), (mid + half, y)])
            time.sleep(0.016)
        self.touch('touchEnd', [(x + drift - far, y)])
        self.touch('touchEnd', [])
        time.sleep(0.1)

    def tap(self, x, y, count=1):
        self.call('Input.synthesizeTapGesture', {'x': x, 'y': y, 'tapCount': count, 'duration': 40, 'gestureSourceType': 'touch'})


NOW = ('(()=>{const box=document.querySelector("#reader"),pager=document.querySelector("#reader-body .pager");if(box.hidden||!pager)return JSON.stringify({open:!box.hidden,gallery:!!pager});'
       'const view=pager.getBoundingClientRect(),pages=[...pager.querySelectorAll(".page")],at=pages.findIndex(p=>{const b=p.getBoundingClientRect();return Math.abs(b.left-view.left)<2;});'
       'const page=pages[at],pane=page&&page.querySelector(".pic-pane"),img=pane&&pane.querySelector("img"),save=document.querySelector("#reader-tools a[download]");'
       'return JSON.stringify({open:true,gallery:true,at,count:pages.length,title:document.querySelector("#reader-title").textContent,says:document.querySelector("#reader-tools .gal-count").textContent,'
       'src:img?new URL(img.src).pathname.split("/").slice(-2).join("/"):"",save:save?new URL(save.href).pathname.split("/").slice(-2).join("/"):"",'
       'wide:img?Math.round(img.getBoundingClientRect().width):0,pane:pane?[Math.round(pane.scrollLeft),Math.round(pane.scrollWidth-pane.clientWidth),Math.round(pane.scrollTop)]:null,'
       'box:pane?[Math.round(pane.getBoundingClientRect().left),Math.round(pane.getBoundingClientRect().top),Math.round(pane.clientWidth),Math.round(pane.clientHeight)]:null,'
       'loaded:pages.filter(p=>p.querySelector("img")).length,snapped:pages.some(p=>Math.abs(p.getBoundingClientRect().left-view.left)<2)});})()')


class Gallery(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID, TITLE = 'e2e-gallery', 'גלריית תמונות'
    SHOTS = (('first', 640, 400, 'צילום ראשון'), ('second', 300, 900, 'צילום שני, גבוה'), ('third', 1600, 500, 'צילום שלישי, רחב'), ('fourth', 200, 200, ''), ('fifth', 800, 800, 'חמישי'), ('sixth', 500, 320, 'שישי'))

    def pictures(self):
        """Six pictures in four messages: one alone, two together, one alone, two together; his own words between them."""
        self.needs('images')
        if self.TID in self.state()['threads']:
            return
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        files = []
        for n, (name, w, h, caption) in enumerate(self.SHOTS):
            path = Path(self.tmp.name) / (name + '.png')
            path.write_bytes(png(w, h, shade=20 + n * 35))
            files.append((path, caption))
        say = lambda text, *shots: self.ok('say', self.TID, '--from', 'fork', '-', *[arg for path, caption in shots for arg in ('--image', str(path), '--caption', caption or 'בלי כיתוב')],
                                           '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input=text)
        say('הודעה עם תמונה אחת', files[0])
        say('הודעה עם שתי תמונות', files[1], files[2])
        self.ok('say', self.TID, '--from', 'fork', 'הודעה בלי תמונה', '--by', 'e2e', '--state', 'working', '--note', 'תמונות')
        say('עוד תמונה אחת', files[3])
        say('ושתיים אחרונות', files[4], files[5])

    def show(self, size):
        self.pictures()
        self.browser.open('about:blank')
        self.open_thread(size, self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .shot img").length===6)' % json.dumps(self.TID), timeout=30, what='the six pictures in the conversation')
        if size is SIZES[0]:        # the phone: its pointer is a finger (the page reads that from the browser; this one says "a mouse")
            self.browser.eval('(()=>{document.documentElement.classList.add("coarse","touch");return "ok";})()')

    def press_picture(self, n):
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot-open")[%d].click();return "ok";})()' % n)
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        self.settle()

    def settle(self):
        """The page of the gallery has come to rest on one picture, and that picture is drawn at its size."""
        last = None
        for _ in range(60):
            now = self.browser.eval(NOW)
            if now.get('gallery') and now.get('snapped') and now.get('wide', 0) > 0 and now == last:
                return now
            last = now
            time.sleep(0.15)
        self.fail('the gallery never came to rest: %s' % last)

    def key(self, code):
        self.browser.eval('(()=>{document.dispatchEvent(new KeyboardEvent("keydown",{code:%s,key:%s,bubbles:true,cancelable:true}));return "ok";})()' % (json.dumps(code), json.dumps(code)))

    def fingers(self):
        cdp = Cdp(self.browser.run('get', 'cdp-url').stdout.strip().splitlines()[-1])
        self.addCleanup(cdp.close)
        cdp.page('/suda.html')
        return cdp

    def test_a_press_on_a_picture_opens_it_among_all_the_pictures_of_the_thread_and_a_swipe_moves_between_them(self):
        self.show(SIZES[0])
        self.press_picture(2)                       # the third picture of the thread: the second of the message with two
        now = self.settle()
        self.assertEqual((now['at'], now['count'], now['says']), (2, 6, '3 מתוך 6'), now)
        self.assertEqual(now['title'], 'צילום שלישי, רחב')
        self.assertTrue(now['src'].endswith('-2.png') and now['src'] == now['save'], now)
        self.assertLessEqual(now['loaded'], 3, 'more than the pictures beside the one on the screen were loaded: %s' % now)
        self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll("#reader .gal-nav")].filter(b=>b.offsetParent).length)'), 0, 'the side buttons are in the way of a finger')
        self.assertEqual(now['pane'][1], 0, 'a picture that fits its screen has nowhere to move: %s' % now)
        finger = self.fingers()
        x, y = now['box'][0] + now['box'][2] // 2, now['box'][1] + now['box'][3] // 2
        # Hebrew: the next picture stands to the left, and a finger that moves right brings it in
        finger.swipe(x - 120, y, 240)
        after = self.settle()
        self.assertEqual((after['at'], after['says'], after['title']), (3, '4 מתוך 6', 'בלי כיתוב'), after)
        self.assertTrue(after['src'] == after['save'] and after['src'] != now['src'], after)
        finger.swipe(x + 120, y, -240)
        self.settle()
        finger.swipe(x + 120, y, -240)
        back = self.settle()
        self.assertEqual((back['at'], back['says'], back['title']), (1, '2 מתוך 6', 'צילום שני, גבוה'), back)
        # a short pull that is let go brings the same picture back
        finger.swipe(x + 30, y, -50, speed=200)
        self.assertEqual(self.settle()['at'], 1)
        # at the first picture a finger that asks for an earlier one stays there
        finger.swipe(x + 120, y, -240)
        self.settle()
        finger.swipe(x + 120, y, -240)
        self.assertEqual(self.settle()['at'], 0)
        # the phone's Back closes the gallery and leaves him in the conversation
        self.browser.eval('(()=>{history.back();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden&&view.ch===%s)' % json.dumps(self.TID), what='the conversation again')
        # and a press on another picture opens the gallery on that one
        self.press_picture(5)
        self.assertEqual(self.settle()['says'], '6 מתוך 6')

    def test_in_an_enlarged_picture_a_finger_moves_the_picture_and_two_fingers_never_turn_the_page(self):
        self.show(SIZES[0])
        self.press_picture(0)
        fit = self.settle()
        self.assertEqual((fit['at'], fit['pane'][1]), (0, 0), fit)
        finger = self.fingers()
        x, y = fit['box'][0] + fit['box'][2] // 2, fit['box'][1] + fit['box'][3] // 2
        # two fingers apart: the picture grows under them, and the gallery stays on it
        finger.pinch(x, y, 2.5)
        big = self.settle()
        self.assertEqual(big['at'], 0, 'two fingers turned the page: %s' % big)
        self.assertGreater(big['wide'], fit['wide'] * 1.6, (fit, big))
        self.assertGreater(big['pane'][1], 40, 'the enlarged picture has nowhere to move: %s' % big)
        # one finger now moves over the picture: the gallery does not turn while the picture can still move
        start = big['pane'][0]
        toward = 1 if start < big['pane'][1] // 2 else -1                  # toward the side that has more room
        finger.swipe(x, y, -toward * 60)
        moved = self.settle()
        self.assertEqual(moved['at'], 0, 'a finger on an enlarged picture turned the page: %s' % moved)
        self.assertNotEqual(moved['pane'][0], start, 'the enlarged picture did not move under the finger: %s' % moved)
        # two fingers together: back to its size on the screen, still the same picture
        finger.pinch(x, y, 0.3)
        small = self.settle()
        self.assertEqual(small['at'], 0, small)
        self.assertLess(small['wide'], big['wide'], (big, small))
        # a double tap enlarges, another brings it back to the screen; neither turns the page
        self.browser.eval('(()=>{const img=document.querySelector("#reader-body .page .pic-pane img");img.dispatchEvent(new MouseEvent("dblclick",{bubbles:true,cancelable:true,clientX:%d,clientY:%d}));return "ok";})()' % (x, y))
        tapped = self.settle()
        self.browser.eval('(()=>{document.querySelector("#reader-tools button[aria-pressed]").click();return "ok";})()')       # "fit"
        fitted = self.settle()
        self.assertEqual((tapped['at'], fitted['at'], fitted['pane'][1]), (0, 0, 0), (tapped, fitted))
        self.assertGreater(tapped['wide'], fitted['wide'], (tapped, fitted))
        # with the picture at the size of the screen again, a finger turns the page
        finger.swipe(x - 120, y, 240)
        self.assertEqual(self.settle()['at'], 1)
        # a picture he enlarged and left is at the size of the screen when he comes back to it
        self.browser.eval('(()=>{const img=document.querySelector("#reader-body .page:nth-child(2) .pic-pane img");img.dispatchEvent(new MouseEvent("dblclick",{bubbles:true,cancelable:true,clientX:%d,clientY:%d}));return "ok";})()' % (x, y))
        self.assertGreater(self.settle()['pane'][1] + self.settle()['pane'][2], 0)
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        self.assertEqual(self.settle()['at'], 2)
        self.browser.eval('(()=>{readerGallery.go(-1);return "ok";})()')
        again = self.settle()
        self.assertEqual((again['at'], again['pane'][1]), (1, 0), again)

    def test_on_a_wide_screen_the_arrows_and_the_side_buttons_move_between_the_pictures_and_esc_closes(self):
        self.show(SIZES[2])
        self.press_picture(1)
        now = self.settle()
        self.assertEqual(now['says'], '2 מתוך 6', now)
        self.key('ArrowLeft')                        # Hebrew: left is onward
        self.assertEqual(self.settle()['says'], '3 מתוך 6')
        self.key('ArrowRight')
        self.settle()
        self.key('ArrowRight')
        self.assertEqual(self.settle()['says'], '1 מתוך 6')
        self.key('ArrowRight')                       # nothing before the first
        self.assertEqual(self.settle()['says'], '1 מתוך 6')
        # the buttons at the sides: the one for "back" is off at the first picture, the other moves on
        buttons = self.browser.eval('JSON.stringify([...document.querySelectorAll("#reader .gal-nav")].map(b=>[b.getAttribute("aria-label"),b.disabled,!!b.offsetParent]))')
        self.assertEqual(buttons, [['התמונה הקודמת', True, True], ['התמונה הבאה', False, True]], buttons)
        self.browser.click('#reader .gal-nav.next')
        self.assertEqual(self.settle()['says'], '2 מתוך 6')
        self.key('ArrowLeft')
        wide = self.settle()                        # the third picture: a wide one, whole on the screen
        self.assertEqual((wide['says'], wide['pane'][1]), ('3 מתוך 6', 0), wide)
        # enlarged: the arrows move over the picture first, and turn the page only at its edge
        for _ in range(8):
            self.key('Equal')
        big = self.settle()
        self.assertGreater(big['pane'][1], 100, big)
        self.assertGreater(big['wide'], wide['wide'], (wide, big))
        self.key('ArrowLeft')
        time.sleep(0.6)
        moved = self.settle()
        self.assertEqual(moved['says'], '3 מתוך 6', 'an arrow on an enlarged picture turned the page before the picture\'s edge')
        self.assertNotEqual(moved['pane'][0], big['pane'][0], 'the arrow did not move over the enlarged picture: %s' % moved)
        self.browser.eval('(()=>{document.querySelector("#reader-body .page:nth-child(3) .pic-pane").scrollLeft=0;return "ok";})()')
        self.key('ArrowLeft')                        # at the picture's left edge: onward
        self.assertEqual(self.settle()['says'], '4 מתוך 6')
        self.key('ArrowRight')
        again = self.settle()                       # and the picture he left enlarged is whole again
        self.assertEqual((again['says'], again['pane'][1]), ('3 מתוך 6', 0), again)
        self.key('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the gallery closed')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), self.TID)

    def test_a_thread_with_one_picture_opens_it_alone_as_before(self):
        self.needs('images')
        tid = 'e2e-gallery-one'
        self.ok('new', tid, 'תמונה אחת', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        path = Path(self.tmp.name) / 'only.png'
        path.write_bytes(png(400, 300, shade=60))
        self.ok('say', tid, '--from', 'fork', '-', '--image', str(path), '--caption', 'היחידה', '--by', 'e2e', '--state', 'working', '--note', 'תמונה', input='תמונה אחת בלבד')
        self.browser.open('about:blank')
        self.open_thread(SIZES[0], tid, 'תמונה אחת')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img").length===1)', timeout=30, what='the picture')
        self.browser.eval('(()=>{document.querySelector("#log .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body img"))', what='the picture on the whole screen')
        alone = self.browser.eval('JSON.stringify({pager:!!document.querySelector("#reader-body .pager"),nav:document.querySelectorAll("#reader .gal-nav").length,count:!!document.querySelector("#reader-tools .gal-count"),'
                                  'title:document.querySelector("#reader-title").textContent})')
        self.assertEqual(alone, {'pager': False, 'nav': 0, 'count': False, 'title': 'היחידה'}, alone)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Gallery.__dict__:
        setattr(Gallery, _name, None)


if __name__ == '__main__':
    unittest.main()
