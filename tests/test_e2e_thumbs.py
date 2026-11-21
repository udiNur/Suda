#!/usr/bin/env python3
"""End to end: a big picture is shown small until he taps it (suda-fixes task 31; the owner, m120 #4, approved m130).

The server keeps a small copy beside a big picture (its long side 720 px, a jpg, or a png when it can be seen through).
- The conversation shows the small copy; the picture itself is not asked for until he taps it, and then it opens.
- The viewer shows the small copy at once and the picture itself over it once it is there.
- Among the pictures of a thread the pages beside the one on the screen hold their small copy; a page gets its picture
  itself when it is on the screen.
- On a slow link a held picture says what its small copy costs, and his press loads the small copy only.
- A picture with no small copy (a small one, an old one) is shown as before.
- The pictures of a question's options show their small copy too.
Every download of a file under uploads/ is counted by the server. The same harness as test_e2e.py (headless Chrome, the
real board server on loopback, a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
from pathlib import Path
import shutil
import subprocess
import time
import unittest

import test_e2e
from test_e2e import SIZES

FFMPEG = shutil.which('ffmpeg')
COVER, INNER, DESK = SIZES


class Thumbs(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest('ffmpeg is not installed: the server makes no small copies')
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Counting(base):
            asked = []          # every download of a file under uploads/
            late = 0            # seconds a picture itself (not a small copy) takes to come: a slow line

            def do_GET(self):
                if '/uploads/' in self.path:
                    Counting.asked.append(self.path.split('?')[0])
                    if Counting.late and '.thumb.' not in self.path:
                        time.sleep(Counting.late)
                return super().do_GET()
        cls.counting = Counting
        cls.server.RequestHandlerClass = Counting
        folder = Path(cls.tmp.name)
        cls.big = [cls.draw(folder / ('big-%d.jpg' % n), '1800x1200', n) for n in (1, 2)]
        cls.small = cls.draw(folder / 'small.png', '240x160', 3)

    @staticmethod
    def draw(path, size, seed):
        w, h = (int(x) for x in size.split('x'))
        subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'nullsrc=size=%dx%d,geq=random(%d)*255:128:128,scale=%s:flags=bilinear' % (max(2, w // 12), max(2, h // 12), seed, size),
                        '-frames:v', '1', *(['-q:v', '2'] if path.suffix == '.jpg' else []), str(path)], check=True, timeout=60)
        return path

    def setUp(self):
        del self.counting.asked[:]
        self.counting.late = 0

    def asked(self, tid):
        return sorted({p.split('/uploads/%s/' % tid)[1] for p in self.counting.asked if '/uploads/%s/' % tid in p})

    def pictures(self, tid, *files, text='תמונות'):
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        args = ['say', tid, '--from', 'fork', text]
        for f in files:
            args += ['--image', str(f)]
        self.ok(*args)
        return self.thread(tid)['messages'][0]['images']

    def show(self, size, tid, shots):
        self.open_thread(size, tid, 'תמונות גדולות')
        # (a picture loads lazily: brought into sight first, so a page still settling does not leave it unasked)
        self.browser.wait('JSON.stringify(synced&&document.querySelectorAll("#log .shot img").length===%d)' % shots, timeout=30, what='the pictures drawn')
        self.browser.eval('(()=>{const s=[...document.querySelectorAll("#log .shot")];if(s.length)s.at(-1).scrollIntoView({block:"center"});return "ok";})()')
        self.browser.wait('JSON.stringify(synced&&document.querySelectorAll("#log .shot img").length===%d&&[...document.querySelectorAll("#log .shot img")].every(i=>i.complete&&i.naturalWidth>0))' % shots,
                          timeout=30, what='the pictures in the conversation')

    def shown(self):
        return self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .shot img")].map(i=>i.getAttribute("src")))')

    def test_the_conversation_shows_the_small_copy_and_a_tap_opens_the_picture_itself(self):
        tid = 'th-one'
        images = self.pictures(tid, self.big[0])
        self.assertEqual(images[0]['thumb']['file'], 'uploads/%s/m1-1.thumb.jpg' % tid)
        for size in (DESK, COVER):
            with self.subTest(size=size[0]):
                del self.counting.asked[:]
                self.show(size, tid, 1)
                self.assertEqual(self.shown(), ['uploads/%s/m1-1.thumb.jpg' % tid])
                self.assertEqual(self.asked(tid), ['m1-1.thumb.jpg'], 'the picture itself waits for his tap')
                shape = self.browser.eval('JSON.stringify((()=>{const i=document.querySelector("#log .shot img");return [i.getAttribute("width"),i.getAttribute("height")]})())')
                self.assertEqual(shape, ['1800', '1200'], 'its place keeps the shape of the picture itself')
                self.counting.late = 2
                self.browser.click('#log .shot-open')
                self.browser.wait('JSON.stringify(!!document.querySelector("#reader:not([hidden]) .reader-body img"))', what='the viewer')
                got = self.browser.eval('JSON.stringify((()=>{const i=document.querySelector("#reader .reader-body img");return {src:i.getAttribute("src"),under:getComputedStyle(i).backgroundImage}})())')
                self.assertEqual(got['src'], 'uploads/%s/m1-1.jpg' % tid, 'a tap opens the picture itself')
                self.assertIn('m1-1.thumb.jpg', got['under'], 'with the small copy standing in until it is there')
                self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0)(document.querySelector("#reader .reader-body img")))', what='the picture itself')
                self.assertEqual(self.browser.eval('JSON.stringify(getComputedStyle(document.querySelector("#reader .reader-body img")).backgroundImage)'), 'none',
                                 'once the picture is there the copy goes from under it (a picture one sees through shows nothing else)')
                self.counting.late = 0
                self.until(lambda: 'm1-1.jpg' in self.asked(tid), what='the picture itself asked for')
                self.browser.press('Escape')

    def test_a_picture_without_a_small_copy_is_shown_as_before(self):
        tid = 'th-small'
        images = self.pictures(tid, self.small)
        self.assertNotIn('thumb', images[0])
        self.show(DESK, tid, 1)
        self.assertEqual(self.shown(), ['uploads/%s/m1-1.png' % tid])

    def test_in_the_gallery_the_pages_beside_hold_their_small_copy_until_they_are_on_the_screen(self):
        tid = 'th-gallery'
        self.pictures(tid, self.big[0], self.big[1])
        self.show(DESK, tid, 2)
        self.assertEqual(self.asked(tid), ['m1-1.thumb.jpg', 'm1-2.thumb.jpg'])
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#reader .pager .pic-pane img").length===2)', what='the gallery')
        pages = self.browser.eval('JSON.stringify([...document.querySelectorAll("#reader .pager .pic-pane img")].map(i=>i.getAttribute("src")))')
        self.assertEqual(pages, ['uploads/%s/m1-1.jpg' % tid, 'uploads/%s/m1-2.thumb.jpg' % tid], 'the page beside holds its small copy')
        self.until(lambda: 'm1-1.jpg' in self.asked(tid), what='the picture on the screen')
        self.assertNotIn('m1-2.jpg', self.asked(tid))
        self.browser.press('ArrowLeft')          # onward, right to left
        self.browser.wait('JSON.stringify(document.querySelectorAll("#reader .pager .pic-pane img")[1].getAttribute("src")===%s)' % json.dumps('uploads/%s/m1-2.jpg' % tid),
                          what='the second picture itself, once on the screen')
        self.until(lambda: 'm1-2.jpg' in self.asked(tid), what='the second picture asked for')

    def test_on_a_slow_link_a_press_loads_only_the_small_copy_and_says_its_size(self):
        tid = 'th-slow'
        images = self.pictures(tid, self.big[0])
        self.browser.open(self.origin + '/' + test_e2e.SLUG + '/state.json')
        key = json.dumps(test_e2e.SLUG + ':slow-media')
        self.browser.eval('(()=>{localStorage.setItem(%s,"tap");return "ok";})()' % key)
        try:
            self.open_thread(COVER, tid, 'תמונות גדולות')
            self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot .media-hold"))', timeout=30, what='the held picture')
            said = self.browser.eval('JSON.stringify(document.querySelector("#log .shot .media-hold").innerText)')
            self.assertIn('%dKB' % round(images[0]['thumb']['bytes'] / 1000), said.replace(' ', ''), 'the cost of what a press loads')
            self.assertEqual(self.asked(tid), [])
            self.browser.click('#log .shot-open')
            self.browser.wait('JSON.stringify((i=>i&&i.complete&&i.naturalWidth>0)(document.querySelector("#log .shot img")))', what='the small copy')
            self.assertEqual(self.shown(), ['uploads/%s/m1-1.thumb.jpg' % tid])
            self.assertEqual(self.asked(tid), ['m1-1.thumb.jpg'], 'his press loads the small copy only')
        finally:
            self.browser.eval('(()=>{localStorage.removeItem(%s);return "ok";})()' % key)

    def test_the_pictures_of_options_show_their_small_copy(self):
        tid = 'th-options'
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('ask', tid, 'איזו?', '--options', 'א,ב', '--option-image', 'א=%s' % self.big[0], '--option-image', 'ב=%s' % self.big[1])
        self.open_thread(DESK, tid, 'תמונות גדולות')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .opts.tiles img").length===2)', timeout=30, what='the option tiles')
        srcs = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .opts.tiles img")].map(i=>i.getAttribute("src")))')
        self.assertTrue(srcs and all(s.endswith('.thumb.jpg') for s in srcs), srcs)


    def test_in_a_grid_of_pictures_a_square_one_is_shown_whole(self):
        """The owner (ultra-trackpad m326): four pictures in a grid cut a QR code's corners off (the cells were
        filled, cutting what stood out). Every picture of a grid is shown whole: scaled to fit its cell, never cut,
        never stretched."""
        tid = 'th-grid'
        qr = self.draw(Path(self.tmp.name) / 'qr.png', '300x300', 4)
        tall = self.draw(Path(self.tmp.name) / 'tall.png', '300x700', 5)
        self.pictures(tid, qr, self.big[0], tall, self.small)
        for size in (DESK, COVER):
            with self.subTest(size=size[0]):
                self.show(size, tid, 4)
                got = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .pics.many .shot img")].map(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);'
                                        'return {src:i.getAttribute("src"),fit:s.objectFit,w:r.width,h:r.height,nw:i.naturalWidth,nh:i.naturalHeight}}))')
                self.assertEqual(len(got), 4)
                for g in got:
                    self.assertIn(g['fit'], ('contain', 'scale-down'), '%s is cut or stretched to fill its cell: %s' % (g['src'], g))
                    # what is drawn of it fits inside its place: its whole width and its whole height
                    scale = min(g['w'] / g['nw'], g['h'] / g['nh'])
                    if g['fit'] == 'scale-down':
                        scale = min(scale, 1)
                    self.assertLessEqual(g['nw'] * scale, g['w'] + 0.5)
                    self.assertLessEqual(g['nh'] * scale, g['h'] + 0.5)

    # ── the owner, m198: a picture shown at lower quality can always be brought to full quality, in one tap ──
    HD = '#log .shot .shot-hd'

    def test_a_small_copy_carries_a_full_quality_button_that_brings_the_picture_itself_in_place(self):
        tid = 'th-hd'
        self.pictures(tid, self.big[0])
        self.show(DESK, tid, 1)
        self.assertTrue(self.browser.visible(self.HD), 'the copy says it can be had in full')
        label = self.browser.eval('JSON.stringify(document.querySelector(%s).getAttribute("aria-label"))' % json.dumps(self.HD))
        self.assertIn('איכות מלאה', label)
        self.assertEqual(self.asked(tid), ['m1-1.thumb.jpg'])
        self.counting.late = 2
        self.browser.click(self.HD)
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#reader").hidden)'), 'one tap brings it here, it opens nothing')
        got = self.browser.eval('JSON.stringify((i=>({src:i.getAttribute("src"),under:getComputedStyle(i).backgroundImage}))(document.querySelector("#log .shot img")))')
        self.assertEqual(got['src'], 'uploads/%s/m1-1.jpg' % tid)
        self.assertIn('m1-1.thumb.jpg', got['under'], 'the copy stays in sight until the picture is there')
        self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0)(document.querySelector("#log .shot img")))', what='the picture itself')
        self.counting.late = 0
        self.assertFalse(self.browser.visible(self.HD), 'nothing left to bring')
        # drawn again (a new message in the thread): it stays in full
        self.ok('say', tid, '--from', 'fork', 'עוד הודעה')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .msg").length>=2)', what='the new message')
        mark = self.browser.eval('(()=>{document.querySelector("#log .shot").dataset.old="1";logSignature="";render();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot")&&!document.querySelector("#log .shot").dataset.old)', what='the picture drawn again')
        self.assertEqual(self.shown(), ['uploads/%s/m1-1.jpg' % tid])
        self.assertFalse(self.browser.visible(self.HD))

    def test_on_a_slow_link_the_full_quality_button_works_after_his_press(self):
        tid = 'th-hd-slow'
        self.pictures(tid, self.big[0])
        self.browser.open(self.origin + '/' + test_e2e.SLUG + '/state.json')
        key = json.dumps(test_e2e.SLUG + ':slow-media')
        self.browser.eval('(()=>{localStorage.setItem(%s,"tap");return "ok";})()' % key)
        try:
            self.open_thread(COVER, tid, 'תמונות גדולות')
            self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot .media-hold"))', timeout=30, what='the held picture')
            self.assertFalse(self.browser.visible(self.HD), 'nothing is shown yet: nothing to bring to full')
            self.browser.click('#log .shot-open')
            self.browser.wait('JSON.stringify((i=>i&&i.complete&&i.naturalWidth>0)(document.querySelector("#log .shot img")))', what='the copy')
            self.assertEqual(self.asked(tid), ['m1-1.thumb.jpg'])
            self.assertTrue(self.browser.visible(self.HD), 'the copy he loaded on a slow link can be brought to full')
            self.browser.click(self.HD)
            self.browser.wait('JSON.stringify((i=>i.getAttribute("src")===%s&&i.complete&&i.naturalWidth>0)(document.querySelector("#log .shot img")))'
                              % json.dumps('uploads/%s/m1-1.jpg' % tid), what='the picture itself, after his tap')
            self.assertEqual(self.asked(tid), ['m1-1.jpg', 'm1-1.thumb.jpg'])
        finally:
            self.browser.eval('(()=>{localStorage.removeItem(%s);return "ok";})()' % key)

    def test_no_full_quality_button_where_the_picture_itself_is_shown(self):
        tid = 'th-hd-none'
        self.pictures(tid, self.small)
        self.show(DESK, tid, 1)
        self.assertFalse(self.browser.visible(self.HD), 'a picture with no copy is already in full')

    def test_a_picture_his_page_sent_smaller_says_so_in_the_viewer_instead_of_full_quality(self):
        import base64
        tid = 'th-shrunk'
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        status, result, receipt = self.post({'op': 'reply', 'thread': tid, 'cid': 'sh1', 'text': '',
                                             'images': [{'name': 'IMG.png', 'data': base64.b64encode(self.small.read_bytes()).decode(), 'shrunk': {'w': 4032, 'h': 3024}}]})
        self.assertEqual(status, 200, result)
        self.show(DESK, tid, 1)
        self.assertFalse(self.browser.visible(self.HD), 'nothing more on the server to bring')
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader:not([hidden]) .reader-body img"))', what='the viewer')
        note = self.browser.eval('JSON.stringify((document.querySelector("#reader .shrunk-note")||{}).textContent||"")')
        self.assertIn('4032×3024', note.replace('\u200e', ''), 'the viewer says the full picture was not sent, and how big it was')

def load_tests(loader, tests, pattern):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""
    return unittest.TestSuite(Thumbs(name) for name in sorted(vars(Thumbs)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
