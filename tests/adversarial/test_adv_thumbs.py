#!/usr/bin/env python3
"""Hostile review of suda-fixes task 31 (the small copy of a big picture, commit 76329f2).

Every test here asserts the SAFE outcome of a hole the review found, and fails on 76329f2:
- Unit (the CLI, as test_threads.py drives it):
  * an ffmpeg that hangs costs 30 s per picture, so four pictures of one reply from the page keep the hook past the
    board server's 60 s limit (answer_server.py kills on-state.sh then): the reply is never stored;
  * a moving picture (an APNG, an animated GIF) gets a still copy, and the conversation shows it frozen;
  * a copy whose shape is not the picture's (an ffmpeg that does not turn a picture by its EXIF orientation) is kept.
- End to end (the harness of test_e2e_thumbs.py: the real board server on loopback, headless Chrome):
  * on a slow link a page of the gallery that showed its small copy beside the one on the screen never gets the
    picture itself: no press in the viewer loads it;
  * on a slow link the gallery opened from a copy he loaded shows nothing of it (a blank held box);
  * a copy that is not on the server (404) hides a picture that is there: the conversation never shows it and a tap
    never opens it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import unittest

import test_e2e
import test_e2e_thumbs
import test_threads
from test_e2e import SIZES, png

FFMPEG = shutil.which('ffmpeg')
COVER, INNER, DESK = SIZES
HOOK_LIMIT = 60         # seconds: answer_server.py runs on-state.sh with timeout=60 and answers 500 after it


def flat_png(w, h):
    """A PNG of one colour: a few hundred bytes whatever its sides."""
    import struct, zlib

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x50\x90\xd0' * w) * h)) + chunk(b'IEND', b''))


def animated(raw):
    """Whether a picture's bytes move: an APNG (acTL), a GIF of more than one image, an animated WebP (ANIM)."""
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return b'acTL' in raw[:raw.find(b'IDAT')]
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        return raw.count(b'\x00\x2c') + raw.count(b'\x21\xf9\x04') > 2
    if raw[:4] == b'RIFF':
        return b'ANIM' in raw[:64]
    return False


class AdvThumbsCli(test_threads.ThreadsTests):
    """The server side of the small copy, through the CLI and the page's ingest."""

    def stand_in(self, name, body):
        path = self.write(name, ('#!/bin/sh\n' + body + '\n').encode())
        path.chmod(0o755)
        return path

    def test_adv_a_hung_ffmpeg_never_keeps_a_reply_past_the_hook_limit(self):
        """A stuck ffmpeg (a machine under load, a wedged decoder, a THREADS_FFMPEG wrapper) is waited for 30 s per
        picture, inside the hook and under the lock. Four pictures: 120 s, and the board server kills on-state.sh at
        60 s, so his reply from the page is never stored (and it fails again on every retry). Safe: the copies give
        up in time, the reply is stored with its pictures, and the whole ingest stays well inside the hook's limit."""
        import base64
        hung = self.stand_in('hung-ffmpeg', 'exec sleep 100')
        env = dict(self.at(1), THREADS_FFMPEG=str(hung))
        self.run_cli('new', 'topic', 'כותרת', env=env)
        pics = [{'name': 'p%d.png' % n, 'type': 'image/png', 'data': base64.b64encode(png(800, 6, n * 20)).decode()} for n in range(4)]
        path = self.board / 'state/state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'op': 'reply', 'thread': 'topic', 'cid': 'hung1', 'text': 'ארבע', 'images': pics}))
        began = time.monotonic()
        p = subprocess.Popen([sys.executable, str(test_threads.CLI), 'ingest'], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=HOOK_LIMIT + 5)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            self.fail('the ingest of one reply with 4 pictures ran past %d s with a hung ffmpeg: the board server '
                      'kills the hook at %d s, and the reply is lost' % (HOOK_LIMIT + 5, HOOK_LIMIT))
        took = time.monotonic() - began
        self.assertEqual(p.returncode, 0, err)
        self.assertLess(took, HOOK_LIMIT - 15, 'a hung ffmpeg costs %.0f s of the hook\'s %d s' % (took, HOOK_LIMIT))
        images = self.thread(env=env)['messages'][0]['images']
        self.assertEqual(len(images), 4)
        self.assertFalse(any('thumb' in i for i in images))

    def test_adv_a_moving_picture_is_never_shown_as_a_still_copy(self):
        """An animated GIF or APNG gets a copy of its first frame only (-frames:v 1, a png or a jpg), and the
        conversation shows that copy: the picture stops moving until he taps it. Safe: a moving picture has no copy,
        or a copy that moves too."""
        if not FFMPEG:
            self.skipTest('ffmpeg is not installed')
        made = []
        for name, size, extra in (('moving.png', '1200x720', ['-plays', '0', '-f', 'apng']),
                                  ('moving.gif', '1800x1080', [])):
            path = self.root / name
            subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'nullsrc=size=100x60:r=2,geq=random(1)*255:128:128,scale=%s:flags=bilinear' % size,
                            '-frames:v', '3', *extra, str(path)], check=True, timeout=60)
            raw = path.read_bytes()
            if len(raw) <= 2_000_000:
                self.assertTrue(animated(raw), name + ' must move, or the test proves nothing')
                made.append(path)
        self.assertTrue(made)
        env = dict(self.at(1), THREADS_FFMPEG=FFMPEG)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        args = ['say', 'topic', '--from', 'fork', 'זזות']
        for path in made:
            args += ['--image', str(path)]
        self.run_cli(*args, env=env)
        for path, image in zip(made, self.thread(env=env)['messages'][0]['images']):
            with self.subTest(picture=path.name):
                self.assertTrue(animated((self.board / image['file']).read_bytes()), 'the stored picture itself still moves')
                if 'thumb' in image:
                    copy = (self.board / image['thumb']['file']).read_bytes()
                    self.assertTrue(animated(copy), 'a moving picture is shown in the conversation by a still copy: %s' % image['thumb']['file'])

    def test_adv_a_copy_of_another_shape_than_the_picture_is_not_kept(self):
        """The copy is checked as a picture, never against the picture it stands for. An ffmpeg that does not turn a
        jpg by its EXIF orientation (or writes anything else that decodes) gives a landscape copy of a portrait
        picture, and the page stretches it into the picture's place (and shows it so in the conversation).
        Safe: a copy is kept only when its shape is the picture's."""
        landscape = self.write('landscape.png', flat_png(720, 405))
        sideways = self.stand_in('sideways-ffmpeg', 'cat >/dev/null; cat %s' % landscape)
        portrait = self.write('portrait.png', png(800, 1600, 3))
        self.assertLessEqual(landscape.stat().st_size, portrait.stat().st_size * 0.6, 'the copy must be small enough to be kept')
        env = dict(self.at(1), THREADS_FFMPEG=str(sideways))
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.run_cli('say', 'topic', '--from', 'fork', 'לאורך', '--image', str(portrait), env=env)
        image = self.thread(env=env)['messages'][0]['images'][0]
        self.assertEqual((image['w'], image['h']), (800, 1600))
        if 'thumb' in image:
            w, h = image['thumb']['w'], image['thumb']['h']
            W, H = image['w'], image['h']        # the same shape, to the pixel a scaling rounds off
            self.assertTrue(abs(w - h * W / H) <= 1 or abs(h - w * H / W) <= 1,
                            'a %dx%d copy kept for a %dx%d picture' % (w, h, W, H))

    def test_adv_a_copy_that_cannot_be_written_never_costs_the_picture(self):
        """put_thumb writes the copy with put_file and nothing catches what that raises: when the copy alone cannot
        be written (here a folder squats its name; in life, a disk that fills between the picture and its copy),
        the whole message is refused, though "the copy is never a reason to refuse a picture" (SKILL.md).
        Safe: the message is stored with its picture, without a copy."""
        if not FFMPEG:
            self.skipTest('ffmpeg is not installed')
        photo = self.write('wide.png', png(1600, 40, 5))
        env = dict(self.at(1), THREADS_FFMPEG=FFMPEG)
        self.run_cli('new', 'topic', 'כותרת', env=env)
        for ext in ('jpg', 'png'):
            (self.board / ('uploads/topic/m1-1.thumb.' + ext)).mkdir(parents=True)
        r = subprocess.run([sys.executable, str(test_threads.CLI), 'say', 'topic', '--from', 'fork', 'רחבה', '--image', str(photo)],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, 'the message was refused for its copy: ' + r.stderr.strip()[-300:])
        image = self.thread(env=env)['messages'][0]['images'][0]
        self.assertTrue((self.board / image['file']).is_file())


class AdvThumbsPage(test_e2e_thumbs.Thumbs):
    """The page side of the small copy, with every download under uploads/ counted by the server."""

    def slow(self):
        self.browser.open(self.origin + '/' + test_e2e.SLUG + '/state.json')
        key = json.dumps(test_e2e.SLUG + ':slow-media')
        self.browser.eval('(()=>{localStorage.setItem(%s,"tap");return "ok";})()' % key)
        self.addCleanup(lambda: self.browser.eval('(()=>{localStorage.removeItem(%s);return "ok";})()' % key))

    def press_held(self, n):
        """His press on the n-th held picture of the conversation (0-based); its small copy then loads."""
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot-open")[%d].click();return "ok";})()' % n)
        self.browser.wait('JSON.stringify((i=>i&&!i.hidden&&i.complete&&i.naturalWidth>0)(document.querySelectorAll("#log .shot img")[%d]))' % n,
                          what='the small copy he pressed for')

    def page(self, n):
        """What page n of the gallery shows: its picture, whether it is hidden, what stands under it, and a hold."""
        return self.browser.eval(
            '(()=>{const p=document.querySelectorAll("#reader .pager .page")[%d];const i=p&&p.querySelector(".pic-pane img");'
            'return JSON.stringify(i?{src:i.getAttribute("src"),hidden:i.hidden||!i.offsetParent,under:getComputedStyle(i).backgroundImage,'
            'loaded:i.complete&&i.naturalWidth>0,held:!!p.querySelector(".media-hold")}:null)})()' % n)

    def gallery(self, tid):
        self.slow()
        self.pictures(tid, self.big[0], self.big[1])
        self.open_thread(DESK, tid, 'תמונות גדולות')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot .media-hold").length===2)', timeout=30, what='the two held pictures')

    def test_adv_on_a_slow_link_a_page_beside_in_the_gallery_can_still_get_the_picture_itself(self):
        """Slow link: he loads the small copies, opens the first picture (the gallery) and loads it, then goes on to
        the second. Its page shows the small copy (it stood beside the first one), whole() leaves it there "until his
        press in the viewer", but the viewer has nothing to press: the pane's click only retries a failed picture.
        Safe: on that page his press (on its hold, or on the picture) loads the picture itself."""
        tid = 'adv-slow-gal'
        self.gallery(tid)
        self.press_held(0)
        self.press_held(1)
        self.browser.click('#log .shot-open')            # the first picture, now its copy: the gallery opens on it
        self.browser.wait('JSON.stringify(document.querySelectorAll("#reader .pager .page").length===2)', what='the gallery')
        first = self.page(0)
        if first and first['held']:                       # the picture itself on a slow link: it waits for his press
            self.browser.click('#reader .pager .page .media-hold')
        self.browser.wait('JSON.stringify((i=>!!i&&i.complete&&i.naturalWidth>0&&i.getAttribute("src").endsWith("m1-1.jpg"))'
                          '(document.querySelectorAll("#reader .pager .page")[0].querySelector(".pic-pane img")))', what='the first picture itself')
        self.browser.press('ArrowLeft')                    # onward, right to left
        self.browser.wait('JSON.stringify(document.querySelector("#reader .gal-count").textContent.includes("2"))', what='the second page on the screen')
        time.sleep(0.6)                                    # the row comes to rest
        second = self.page(1)
        self.assertTrue(second, 'the second page has its picture')
        self.assertNotIn('m1-2.jpg', self.asked(tid), 'a slow link: the picture itself waits for his press')
        if second['held']:
            self.browser.eval('(()=>{document.querySelectorAll("#reader .pager .page")[1].querySelector(".media-hold").click();return "ok";})()')
        else:
            self.browser.eval('(()=>{document.querySelectorAll("#reader .pager .page")[1].querySelector(".pic-pane img").click();return "ok";})()')
        try:
            self.until(lambda: 'm1-2.jpg' in self.asked(tid), timeout=8, what='the second picture itself')
        except AssertionError:
            self.fail('on a slow link the second page of the gallery shows only its small copy (%s), and his press in '
                      'the viewer never loads the picture itself' % self.page(1))

    def test_adv_on_a_slow_link_the_gallery_opened_from_his_copy_shows_that_copy(self):
        """Slow link: he presses a held picture, its small copy loads, and he taps it. The gallery's page for it
        asked for the picture itself, which a slow link held: the img was hidden behind a blank hold, so the copy
        he was looking at a moment ago was gone from the screen until a second press. Safe (the rule chosen, as the
        viewer of a single picture does): his tap that opens it is his yes to the picture itself, which comes at
        once, with the copy under it until it is there; never a blank hold and a second press."""
        tid = 'adv-slow-open'
        self.gallery(tid)
        self.press_held(0)
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#reader .pager .page").length===2)', what='the gallery')
        time.sleep(0.5)
        first = self.page(0)
        self.assertTrue(first and not first['hidden'] and not first.get('held'), 'the page he opened is a blank hold: %s' % first)
        self.assertIn(first['src'], ('uploads/%s/m1-1.jpg' % tid, 'uploads/%s/m1-1.thumb.jpg' % tid), first)
        self.until(lambda: 'm1-1.jpg' in self.asked(tid), what='the picture itself, from his tap')
        self.assertNotIn('m1-2.jpg', self.asked(tid), 'the page beside it still waits for his press')

    def test_adv_a_copy_missing_on_the_server_does_not_hide_the_picture(self):
        """The record names a small copy the server does not have (a board restored without it, a file lost): the
        conversation asks only for the copy, retries it, shows the failed tile, and his tap on it asks for the copy
        again instead of opening the picture, which is there. Safe: the picture is shown, or opened by his tap."""
        tid = 'adv-gone'
        images = self.pictures(tid, self.big[0])
        (self.board / images[0]['thumb']['file']).unlink()
        self.open_thread(DESK, tid, 'תמונות גדולות')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot img"))', what='the picture in the conversation')
        time.sleep(7)                                       # the page's own two retries (1.5 s, 4 s)
        self.browser.click('#log .shot-open')
        try:
            self.browser.wait('JSON.stringify((i=>i&&i.complete&&i.naturalWidth>0)(document.querySelector("#log .shot img"))'
                              '||(i=>!!i&&i.getAttribute("src")===%s)(document.querySelector("#reader:not([hidden]) .reader-body img")))'
                              % json.dumps(images[0]['file']), timeout=8, what='the picture itself')
        except AssertionError:
            self.fail('a missing small copy hides the picture: the conversation asked for %s only' % self.asked(tid))


def load_tests(loader, tests, pattern):
    """Only the scenarios of this file (the classes it builds on have their own)."""
    suite = unittest.TestSuite()
    for cls in (AdvThumbsCli, AdvThumbsPage):
        suite.addTests(cls(name) for name in sorted(vars(cls)) if name.startswith('test_adv_'))
    return suite


if __name__ == '__main__':
    unittest.main()
