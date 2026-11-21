#!/usr/bin/env python3
"""Second hostile review of the gallery: what test_adv_gallery_e2e.py does not cover.

Every test states the CORRECT behaviour: a FAIL is a hole in suda.html. Same harness as test_adv_gallery_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_adv_gallery_e2e
import test_e2e_gallery
from test_e2e import SIZES

PHONE, FOLD, DESK = SIZES

# A gallery of three pictures whose middle one is an address the server does not have: it fails to load.
BROKEN = ('(()=>{const t=thread("e2e-gallery"),base=galleryOf(wholeOf(t),t.id);'
          'const list=[{...base[0]},{...base[1],src:"/gal2-missing-%d.png",title:"חסרה",name:"x.png"},{...base[2]}];'
          'openReader({title:"x",image:list[%d].src,photo:true,name:"x",gallery:{list,at:%d}});return "ok";})()')
TILE = ('(()=>{const p=[...document.querySelectorAll("#reader-body .page")][1],pane=p&&p.firstChild,t=pane&&pane.querySelector(".shot-retry"),'
        'i=pane&&pane.querySelector("img"),b=t?t.getBoundingClientRect():null;'
        'return JSON.stringify({failed:!!pane&&pane.classList.contains("failed"),tile:!!b&&b.width>0,x:b?b.left+b.width/2:0,y:b?b.top+b.height/2:0,'
        'src:i?i.getAttribute("src"):""});})()')


class AdvGal2(test_adv_gallery_e2e.AdvGallery):

    def broken(self, at, n):
        self.browser.eval(BROKEN % (n, at, at))
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager"))', what='the gallery')
        # the page itself asks again twice (1.5 s, then 4 s): wait for both, so only his press can ask a third time
        self.browser.wait('JSON.stringify(%s.includes("again=2"))' % ('JSON.parse(' + TILE + ').src'), timeout=12, what='the page gave up asking')
        time.sleep(0.4)
        tile = self.browser.eval(TILE)
        self.assertTrue(tile['failed'] and tile['tile'], tile)
        return tile

    # ── a picture that fails to load inside the gallery ──────────────────────

    def test_held_a_finger_on_the_tile_of_a_picture_that_did_not_load_asks_for_it_again(self):
        """Suspected: the row captures every finger (pager.setPointerCapture), so the tap's click might go to the
        row and miss the tile's listener on the pane. It does not: Chrome sends the tap's click to the tile."""
        self.show(PHONE)
        f = self.moving(False)
        self.watch_errors()
        tile = self.broken(1, 1)
        f.tap(tile['x'], tile['y'])
        time.sleep(0.6)
        after = self.browser.eval(TILE)
        self.assertIn('again=3', after['src'], 'a tap on the tile did not ask for the picture again: %s' % after)
        self.assertEqual(self.errors(), [])

    def test_held_a_mouse_on_the_tile_of_a_picture_that_did_not_load_asks_for_it_again(self):
        self.show(DESK)
        self.moving(False)
        tile = self.broken(1, 2)
        self.browser.eval('(()=>{const t=[...document.querySelectorAll("#reader-body .page")][1].querySelector(".shot-retry");'
                          'const o={bubbles:true,clientX:%d,clientY:%d,pointerId:1,pointerType:"mouse",button:0,isPrimary:true};'
                          't.dispatchEvent(new PointerEvent("pointerdown",o));t.dispatchEvent(new PointerEvent("pointerup",o));t.click();return "ok";})()' % (tile['x'], tile['y']))
        time.sleep(0.4)
        self.assertIn('again=3', self.browser.eval(TILE)['src'])

    def test_held_a_picture_that_did_not_load_does_not_stop_the_row(self):
        self.show(PHONE)
        f = self.moving()
        self.watch_errors()
        self.broken(1, 3)
        self.assertEqual(self.rest()['says'], '2 מתוך 3')
        self.hand(f, 60, 400, 200)
        self.assertEqual(self.rest()['says'], '3 מתוך 3')
        self.hand(f, 300, 400, -200)
        self.hand(f, 300, 400, -200)
        self.assertEqual(self.rest()['says'], '1 מתוך 3')
        self.assertEqual(self.errors(), [])

    # ── Back / Escape and the windows that share the reader ──────────────────

    def test_held_the_apps_back_closes_the_gallery_and_stays_in_the_thread(self):
        self.show(PHONE)
        self.moving()
        self.press_picture(2)
        took = self.browser.eval('JSON.stringify(window.sudaBack())')
        self.assertIs(took, True)
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        time.sleep(0.4)
        self.assertEqual(self.browser.eval('JSON.stringify([view.ch,view.read||false,!!readerGallery,!!readerPic])'), [self.TID, False, False, False])
        # and a second Back now leaves for the list, as before
        self.assertIs(self.browser.eval('JSON.stringify(window.sudaBack())'), True)
        self.browser.wait('JSON.stringify(view.ch===null)', what='the list')

    def test_held_after_the_gallery_a_diagram_and_a_text_open_as_before(self):
        self.show(DESK)
        self.moving()
        self.watch_errors()
        self.press_picture(1)
        self.key('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        svg = "data:image/svg+xml," + "%3Csvg xmlns='http://www.w3.org/2000/svg' width='3000' height='2000'%3E%3Crect width='3000' height='2000' fill='red'/%3E%3C/svg%3E"
        self.browser.eval('(()=>{openReader({title:"d",image:%s,code:"graph LR; a-->b"});return "ok";})()' % json.dumps(svg))
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body.pic img")&&document.querySelector("#reader-body.pic img").getBoundingClientRect().width>0)', what='the diagram')
        time.sleep(0.4)
        look = 'JSON.stringify((()=>{const b=document.querySelector("#reader-body");return {cls:b.className,pager:!!b.querySelector(".pager"),gal:!!readerGallery,x:Math.round(b.scrollLeft),y:Math.round(b.scrollTop),count:!!document.querySelector("#reader-tools .gal-count")};})())'
        before = self.browser.eval(look)
        self.assertEqual((before['cls'], before['pager'], before['gal'], before['count']), ('reader-body pic', False, False, False), before)
        self.browser.eval('(()=>{document.querySelector("#reader-tools .zoom").click();return "ok";})()')       # its own size: room to move
        time.sleep(0.2)
        start = self.browser.eval(look)
        self.key('ArrowDown')
        time.sleep(0.6)
        self.assertGreater(self.browser.eval(look)['y'], start['y'], 'the arrows no longer move the diagram')
        self.key('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        self.assertEqual(self.errors(), [])

    def test_held_closed_leaves_no_frame_or_timer_running(self):
        """After the gallery closes in the middle of a slide, nothing of it runs: no requestAnimationFrame of its own,
        no timeout that touches the reader."""
        self.show(DESK)
        self.moving()
        self.watch_errors()
        self.press_picture(1)
        self.browser.eval('(()=>{window.__raf=0;const r=window.requestAnimationFrame;window.requestAnimationFrame=cb=>{window.__raf++;return r(cb);};return "ok";})()')
        self.key('ArrowLeft')
        self.key('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        time.sleep(1.2)
        self.browser.eval('(()=>{window.__raf=0;return "ok";})()')
        time.sleep(1.0)
        self.assertLess(self.browser.eval('JSON.stringify(window.__raf)'), 3, 'frames still asked for after the gallery closed')
        self.assertEqual(self.browser.eval('JSON.stringify([!!readerGallery,!!readerPic,document.querySelector("#reader-body").childNodes.length])'), [False, False, 0])
        self.assertEqual(self.errors(), [])


# Only this file's scenarios.
for _name in dir(test_adv_gallery_e2e.AdvGallery):
    if _name.startswith('test') and _name not in AdvGal2.__dict__:
        setattr(AdvGal2, _name, None)


if __name__ == '__main__':
    unittest.main()
