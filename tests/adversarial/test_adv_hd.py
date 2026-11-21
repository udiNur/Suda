#!/usr/bin/env python3
"""Hostile review of m198 (68e6f8d): the 'איכות מלאה' button on a small copy, and `shrunk` on a picture his page sent
smaller. Every test here asserts the safe outcome and fails on 68e6f8d.

- e2e (the harness of test_e2e_thumbs: the real board server on loopback, a temporary board, headless Chrome), with
  a handler that can refuse the small copies (a line that drops) and logs every request with its query.
- CLI (the harness of test_threads): what an agent reads of a picture his page sent smaller."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import json
from pathlib import Path
import time
import unittest

import test_e2e_thumbs
import test_threads
from test_e2e_thumbs import COVER, DESK

HD = '#log .shot .shot-hd'
IMG = 'document.querySelector("#log .shot img")'


class AdvHd(test_e2e_thumbs.Thumbs):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Refusing(base):
            refuse_copies = 0       # how many more requests for a small copy are refused (a line that drops)
            raw = []                # every request under uploads/, with its query

            def do_GET(self):
                if '/uploads/' in self.path:
                    Refusing.raw.append(self.path)
                if Refusing.refuse_copies and '.thumb.' in self.path:
                    Refusing.refuse_copies -= 1
                    self.send_error(404)
                    return
                return super().do_GET()
        cls.refusing = Refusing
        cls.server.RequestHandlerClass = Refusing

    def setUp(self):
        super().setUp()
        self.refusing.refuse_copies = 0
        del self.refusing.raw[:]

    def tearDown(self):
        self.counting.late = 0
        self.refusing.refuse_copies = 0
        # nothing of a slow picture is left on its way into the next test
        time.sleep(0.2)

    def rect(self, selector):
        return self.browser.eval('JSON.stringify((b=>({l:b.left,t:b.top,r:b.right,b:b.bottom}))(document.querySelector(%s).getBoundingClientRect()))' % json.dumps(selector))

    def open_failed(self, tid):
        """His thread with one big picture whose small copy did not come (the line dropped)."""
        self.pictures(tid, self.big[0])
        self.refusing.refuse_copies = 99
        self.open_thread(DESK, tid, 'תמונות גדולות')
        self.browser.eval('(()=>{const s=document.querySelector("#log .shot");if(s)s.scrollIntoView({block:"center"});return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .shot.failed"))', timeout=30, what='the tile of a copy that did not load')

    # ── keyboard ──

    def test_on_a_touch_screen_the_full_quality_button_takes_a_finger_44_px_wide_and_high(self):
        """The review: the page's touch targets are 44 px; the button may look smaller, its hit area may not."""
        tid = 'adv-hd-touch'
        self.pictures(tid, self.big[0])
        for size in (COVER, DESK):
            with self.subTest(size=size[0]):
                self.show(size, tid, 1)
                got = self.browser.eval('(()=>{document.documentElement.classList.add("touch");const b=document.querySelector(%s);b.scrollIntoView({block:"center"});'
                                        'const r=b.getBoundingClientRect(),cx=(r.left+r.right)/2,cy=(r.top+r.bottom)/2,'
                                        'hit=(x,y)=>{const e=document.elementFromPoint(x,y);return !!e&&!!e.closest(".shot-hd");};'
                                        'return JSON.stringify({w:r.width,h:r.height,up:hit(cx,cy-21.5),down:hit(cx,cy+21.5),start:hit(cx-21.5,cy),end:hit(cx+21.5,cy)})})()' % json.dumps(HD))
                for side in ('up', 'down', 'start', 'end'):
                    self.assertTrue(got[side], 'a finger 21.5 px %s of its middle misses the button: %s' % (side, got))
                self.assertLessEqual(got['h'], 40, 'it may still look small: %s' % got)

    def test_keys_stay_on_the_picture_after_full_quality_is_chosen_from_the_keyboard(self):
        """The button removes itself in its own press: the keys fell onto the page itself (document.body), out of the
        message he was walking with the arrows. A held picture's press (holdMedia.load) puts them back; this one did not."""
        tid = 'adv-hd-keys'
        self.pictures(tid, self.big[0])
        self.show(DESK, tid, 1)
        self.browser.press('Escape')
        self.browser.press('ArrowUp')
        self.assertTrue(self.active()['isRow'], self.active())
        self.browser.press('Enter')
        for _ in range(10):
            if 'shot-hd' in self.active()['cls']:
                break
            self.browser.press('ArrowLeft')
        self.assertIn('shot-hd', self.active()['cls'], 'the button is one of the message\'s items')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector(%s))' % json.dumps(HD), what='the button gone')
        a = self.active()
        self.assertTrue(a['inRow'], 'the keys are still in the message (on its picture), not on the page itself: %r' % a)

    def test_in_the_gallery_the_keys_stay_on_their_tool_when_a_page_says_it_was_sent_smaller(self):
        """The gallery keeps the keys on a tool by its index among the tools; the note is put among them on one page
        and not on the next, so the keys jump to the tool beside ('+' becomes '100%')."""
        tid = 'adv-hd-galkeys'
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        data = base64.b64encode(self.small.read_bytes()).decode()
        status, result, _ = self.post({'op': 'reply', 'thread': tid, 'cid': 'g1', 'text': '',
                                       'images': [{'name': 'a.png', 'data': data}, {'name': 'b.png', 'data': data, 'shrunk': {'w': 4000, 'h': 3000}}]})
        self.assertEqual(status, 200, result)
        self.show(DESK, tid, 2)
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader:not([hidden]) .pager .pic-pane img"))', what='the gallery')
        plus = 'הגדלה (+)'
        self.browser.eval('(()=>{[...document.querySelector("#reader-tools").children].find(n=>n.getAttribute("aria-label")===%s).focus();return "ok";})()' % json.dumps(plus))
        self.assertEqual(self.active()['label'], plus)
        self.browser.press('ArrowLeft')            # onward, right to left: the page sent smaller
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-tools .shrunk-note"))', what='the page sent smaller')
        time.sleep(0.6)
        self.assertEqual(self.active()['label'], plus, 'the keys stay on the tool they stood on')
        self.browser.press('Escape')

    # ── where the button stands ──

    def test_the_full_quality_button_stands_on_the_picture_not_beside_it(self):
        """It is placed in the corner of the figure; a caption wider than a tall picture widens the figure, and the
        button floats in the empty space beside the picture."""
        tid = 'adv-hd-cap'
        tall = self.draw(Path(self.tmp.name) / 'adv-tall.jpg', '1000x2400', 7)
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', 'תמונה', '--image', str(tall), '--caption', 'כיתוב ארוך מאוד שמרחיב את המסגרת של התמונה הרבה מעבר לרוחב שלה')
        self.show(DESK, tid, 1)
        img, hd = self.rect('#log .shot img'), self.rect(HD)
        self.assertTrue(img['l'] <= hd['l'] and hd['r'] <= img['r'] and img['t'] <= hd['t'] and hd['b'] <= img['b'],
                        'the button lies on the picture: picture %r, button %r' % (img, hd))

    # ── a copy that did not load ──

    def test_full_quality_on_a_copy_that_did_not_load_asks_for_the_picture_once(self):
        """The copy failed: its retry timer is running. The button sets the picture itself but leaves the timer, which
        fires in the middle of the (slow) download and asks again at ?again=1: the bytes so far are thrown away. The
        copy that failed is also asked again, as the background under the picture."""
        tid = 'adv-hd-failed'
        self.open_failed(tid)
        self.assertTrue(self.browser.visible(HD), 'the button is there over the tile')
        self.counting.late = 5                 # the picture itself comes slowly
        at = len(self.refusing.raw)
        self.browser.click(HD)
        self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0)(%s))' % IMG, timeout=30, what='the picture itself')
        after = [p.split('/uploads/%s/' % tid)[1] for p in self.refusing.raw[at:]]
        self.assertEqual(after, ['m1-1.jpg'], 'his tap asks for the picture itself once, and for nothing else')

    def test_a_press_on_the_tile_that_brought_the_picture_itself_leaves_no_full_quality_button(self):
        """A press on the tile of a copy that did not load asks for the picture itself (task 31). Once it is there the
        button still offers 'איכות מלאה', for a picture that is already in full (and its tap fetches the failed copy)."""
        tid = 'adv-hd-tile'
        self.open_failed(tid)
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0&&!i.getAttribute("src").includes(".thumb."))(%s))' % IMG,
                          timeout=30, what='the picture itself')
        self.assertFalse(self.browser.visible(HD), 'nothing left to bring to full quality')

    # ── drawn again ──

    def test_drawn_again_while_the_picture_itself_is_on_its_way_the_copy_stays_under_it(self):
        """He tapped the button on a slow line; the conversation is drawn again (the link's mode turns, dark mode, a
        search) before the picture arrives. The new tile asks for the picture itself with nothing under it: the copy
        he was looking at is gone and an empty box stands there until the picture comes."""
        tid = 'adv-hd-redraw'
        self.pictures(tid, self.big[0])
        self.show(DESK, tid, 1)
        self.counting.late = 4
        self.browser.click(HD)
        time.sleep(0.3)
        self.browser.eval('(()=>{logSignature="";render();return "ok";})()')        # what judgeLink does when the mode turns
        got = self.browser.eval('JSON.stringify((i=>({src:i.getAttribute("src"),under:getComputedStyle(i).backgroundImage,there:i.complete&&i.naturalWidth>0}))(%s))' % IMG)
        self.assertEqual(got['src'], 'uploads/%s/m1-1.jpg' % tid, 'drawn again in full quality')
        self.assertFalse(got['there'], 'the picture itself is still on its way (the test is not vacuous)')
        self.assertIn('m1-1.thumb.jpg', got['under'], 'the copy stays in sight until the picture is there')
        self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0)(%s))' % IMG, timeout=30, what='the picture itself')

    def test_in_a_grid_the_copy_under_the_picture_keeps_its_shape(self):
        """In a grid every cell is 4:3 and the picture is drawn whole inside it (object-fit: contain). The copy under
        it is stretched to the whole cell (100% 100%): a tall picture is drawn squashed until the picture comes."""
        tid = 'adv-hd-grid'
        tall = self.draw(Path(self.tmp.name) / 'adv-tall2.jpg', '1000x2400', 8)
        self.pictures(tid, tall, self.big[0])
        self.show(DESK, tid, 2)
        self.counting.late = 4
        self.browser.click(HD)
        time.sleep(0.3)
        got = self.browser.eval('JSON.stringify((i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);return {w:r.width,h:r.height,under:s.backgroundImage,size:s.backgroundSize,there:i.complete&&i.naturalWidth>0}})(%s))' % IMG)
        self.assertIn('.thumb.', got['under'], 'the copy is under the picture while it comes')
        self.assertFalse(got['there'])
        kept = got['size'] in ('contain',) or abs((got['w'] / got['h']) / (1000 / 2400) - 1) < 0.03
        self.assertTrue(kept, 'the copy is drawn in the picture\'s own shape (1000x2400), not stretched to its %.0fx%.0f cell (%s)'
                        % (got['w'], got['h'], got['size']))
        self.browser.wait('JSON.stringify((i=>i.complete&&i.naturalWidth>0)(%s))' % IMG, timeout=30, what='the picture itself')

    # ── the note of a picture sent smaller ──

    def test_on_a_phone_the_note_of_a_picture_sent_smaller_can_be_read(self):
        """`.reader-tools span{flex:1;min-width:8ch}` takes the note too: on a phone it gets 80 px, its words do not
        wrap, and the original's sides (the point of the note) run under the zoom buttons."""
        tid = 'adv-hd-phone'
        self.ok('new', tid, 'תמונות גדולות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        data = base64.b64encode(self.small.read_bytes()).decode()
        status, result, _ = self.post({'op': 'reply', 'thread': tid, 'cid': 'p1', 'text': '',
                                       'images': [{'name': 'a.png', 'data': data, 'shrunk': {'w': 4032, 'h': 3024}}]})
        self.assertEqual(status, 200, result)
        self.show(COVER, tid, 1)
        self.browser.click('#log .shot-open')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader:not([hidden]) #reader-tools .shrunk-note"))', what='the viewer with the note')
        time.sleep(0.4)
        got = self.browser.eval('JSON.stringify((()=>{const n=document.querySelector("#reader-tools .shrunk-note"),g=document.createRange();g.selectNodeContents(n);const b=g.getBoundingClientRect();'
                                'const hit=[...document.querySelectorAll("#reader-tools button,#reader-tools a")].filter(x=>{const r=x.getBoundingClientRect();'
                                'return r.width&&!(r.right<=b.left||r.left>=b.right||r.bottom<=b.top||r.top>=b.bottom)}).map(x=>x.getAttribute("aria-label")||x.textContent.trim());'
                                'return {sw:n.scrollWidth,cw:n.clientWidth,hit}})())')
        self.assertLessEqual(got['sw'], got['cw'] + 1, 'the whole note fits in its place: %r' % got)
        self.assertEqual(got['hit'], [], 'no button stands over the words of the note')
        self.browser.press('Escape')


class AdvShrunkCli(test_threads.ThreadsTests):
    """What an agent reads of a picture his page sent smaller. SKILL.md tells agents the full one never reached the
    Mac and to ask again when the detail matters; the record keeps `shrunk`, but the rows agents read (`pending`, the
    text of `show`) are built by image_rows, which keeps only path, caption, name, bytes, w, h."""

    def shrunk_reply(self):
        e = self.at
        self.run_cli('new', 'topic', 'כותרת', env=e(0))
        b64 = base64.b64encode(self.jpeg()).decode()           # stored 30x40
        got = self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 's1',
                         'images': [{'data': b64, 'shrunk': {'w': 3000, 'h': 4000}}]}, env=e(1))
        self.assertTrue(got['ok'])
        self.assertEqual(self.thread(env=e(1))['messages'][0]['images'][0]['shrunk'], {'w': 3000, 'h': 4000})
        return e

    def test_pending_tells_the_agent_the_picture_was_sent_smaller(self):
        e = self.shrunk_reply()
        row = json.loads(self.run_cli('pending', env=e(2)).stdout)[0]
        self.assertEqual(row['images'][0].get('shrunk'), {'w': 3000, 'h': 4000}, row['images'])

    def test_show_as_text_tells_the_agent_the_picture_was_sent_smaller(self):
        e = self.shrunk_reply()
        out = self.run_cli('show', 'topic', env=e(2)).stdout
        line = next(x for x in out.splitlines() if x.startswith('[תמונה:'))
        self.assertTrue('3000' in line and '4000' in line, line)


def load_tests(loader, tests, pattern):
    """Only the tests of this file: the ones inherited from test_e2e_thumbs, test_e2e and test_threads run there."""
    suite = unittest.TestSuite()
    for cls in (AdvShrunkCli, AdvHd):
        own = [name for name in sorted(vars(cls)) if name.startswith('test_')]
        suite.addTests(cls(name) for name in own)
    return suite


if __name__ == '__main__':
    unittest.main(verbosity=2)
