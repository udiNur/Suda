#!/usr/bin/env python3
"""Hostile review of the gallery (the pictures of a thread on the whole screen), end to end.

Every test states the CORRECT behaviour: a test that FAILS is a hole in suda.html. The tests whose name begins
with `test_hole_` failed when they were written; the ones that begin with `test_held_` are attacks the change
withstood. The harness is the one of test_e2e_gallery.py (headless Chrome, the real board server on loopback, a
temporary board); the fingers are Chrome's own touches (Input.dispatchTouchEvent).

One thing to know about this machine: its headless Chrome says `prefers-reduced-motion: reduce`. So the shipped
test_e2e_gallery.py only ever ran the branch without animation (no smooth scrolling, no 420 ms timer, no momentum).
Most tests here tell the browser that motion is wanted (Emulation.setEmulatedMedia), as on an ordinary phone.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest
from pathlib import Path

import test_e2e_gallery
from test_e2e import SIZES, png

PHONE, FOLD, DESK = SIZES
TINY = ('tiny', 320, 700)

# Where the row of pages stands, and the picture of the page nearest to the screen.
ROW = ('(()=>{const box=document.querySelector("#reader"),pager=document.querySelector("#reader-body .pager");'
       'if(box.hidden||!pager)return JSON.stringify({open:!box.hidden,gallery:false});'
       'const view=pager.getBoundingClientRect(),pages=[...pager.querySelectorAll(".page")],lefts=pages.map(p=>p.getBoundingClientRect().left-view.left);'
       'let near=0;for(let i=1;i<lefts.length;i++)if(Math.abs(lefts[i])<Math.abs(lefts[near]))near=i;'
       'const pane=pages[near].firstChild,img=pane.querySelector("img"),fit=document.querySelector("#reader-tools button[aria-pressed]"),b=img?img.getBoundingClientRect():null;'
       'return JSON.stringify({open:true,gallery:true,near,off:+lefts[near].toFixed(2),left:+pager.scrollLeft.toFixed(2),width:+view.width.toFixed(2),held:pager.classList.contains("held"),'
       'says:document.querySelector("#reader-tools .gal-count").textContent,title:document.querySelector("#reader-title").textContent,'
       'pct:(document.querySelector("#reader-tools .zoom")||{}).textContent||"",fitted:fit?fit.getAttribute("aria-pressed"):"",'
       'imgs:pages.filter(p=>p.querySelector("img")).length,wide:b?Math.round(b.width):0,imgLeft:b?+b.left.toFixed(1):0,imgTop:b?+b.top.toFixed(1):0,imgHigh:b?+b.height.toFixed(1):0,'
       'x:+pane.scrollLeft.toFixed(1),y:+pane.scrollTop.toFixed(1),maxX:pane.scrollWidth-pane.clientWidth,maxY:pane.scrollHeight-pane.clientHeight,'
       'paneBox:[pane.getBoundingClientRect().left,pane.getBoundingClientRect().top,pane.clientWidth,pane.clientHeight].map(Math.round)});})()')

# A gallery of `count` pictures opened on picture `at` (the six files of the thread, each address made its own).
MANY = ('(()=>{const t=thread("e2e-gallery"),base=galleryOf(wholeOf(t),t.id),list=[];for(let i=0;i<%d;i++){const p=base[i%%base.length];list.push({...p,src:p.src+"?n="+i,title:"תמונה "+(i+1)});}'
        'openReader({title:"x",image:list[%d].src,photo:true,name:"x",gallery:{list,at:%d}});return "ok";})()')


class AdvGallery(test_e2e_gallery.Gallery):
    """Only the scenarios of this file."""

    ODD = 'e2e-gallery-odd'
    ODD_SHOTS = (('normal', 640, 400), ('wide', 4000, 300), ('tall', 300, 4000), ('dot', 1, 1), ('last', 500, 320))

    # ── helpers ──────────────────────────────────────────────────────────────

    def moving(self, on=True):
        """The browser is told whether he asked for less motion. To be called before the gallery opens."""
        f = self.fingers()
        f.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'no-preference' if on else 'reduce'}]})
        self.assertIs(self.browser.eval('JSON.stringify(matchMedia("(prefers-reduced-motion:reduce)").matches)'), not on)
        return f

    def watch_errors(self):
        self.browser.eval('(()=>{window.__errs=[];addEventListener("error",e=>window.__errs.push(String(e.message)));addEventListener("unhandledrejection",e=>window.__errs.push("rejection "+String(e.reason)));return "ok";})()')

    def errors(self):
        return self.browser.eval('JSON.stringify(window.__errs||[])')

    def row(self):
        return self.browser.eval(ROW)

    def rest(self, timeout=8):
        """The row has stopped: twice the same, not held by a finger or by the page, and the counter says the page
        that is on the screen (it follows the row a frame or two later; on a loaded machine a frame is long). When
        that never comes, the last reading is given back as it is, for the test to judge."""
        end, last = time.monotonic() + timeout, None
        while time.monotonic() < end:
            now = self.row()
            if now == last and now.get('gallery') and not now['held'] and now['says'].startswith('%d ' % (now['near'] + 1)):
                return now
            last = now
            time.sleep(0.2)
        return last

    def tp(self, f, kind, points):
        """Touches by their own numbers. touchStart / touchMove: the ones named are put down or moved; touchEnd: the
        ones named are lifted (none named: all of them)."""
        f.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [{'x': round(x), 'y': round(y), 'id': i, 'radiusX': 8, 'radiusY': 8, 'force': 1} for i, (x, y) in points.items()]})

    def hand(self, f, x, y, dx, steps=6, gap=0.012, lift=True):
        """One finger put down at (x, y) and moved sideways by dx, in steps; lifted at once (still moving)."""
        self.tp(f, 'touchStart', {0: (x, y)})
        for i in range(1, steps + 1):
            self.tp(f, 'touchMove', {0: (x + dx * i / steps, y)})
            time.sleep(gap)
        if lift:
            self.tp(f, 'touchEnd', {})

    def double_tap(self, f, x, y):
        """Two taps that the browser itself took as a double tap (in a slow run they may come too far apart)."""
        self.browser.eval('(()=>{if(!window.__dbl){window.__dbl={n:0};document.addEventListener("dblclick",()=>window.__dbl.n++,true);}window.__dbl.n=0;return "ok";})()')
        for _ in range(4):
            f.tap(x, y, 2)
            time.sleep(0.5)
            if self.browser.eval('JSON.stringify(window.__dbl.n)'):
                return
        self.skipTest('the browser never took two taps as a double tap (a slow run)')

    def close(self):
        self.browser.eval('(()=>{closeReader();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')

    def many(self, count, at):
        self.browser.eval(MANY % (count, at, at))
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        time.sleep(0.5)

    def odd(self, size):
        """A thread with a very wide picture, a very tall one and a tiny one between two ordinary ones."""
        self.needs('images')
        if self.ODD not in self.state()['threads']:
            self.ok('new', self.ODD, 'תמונות חריגות', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            for n, (name, w, h) in enumerate(self.ODD_SHOTS):
                path = Path(self.tmp.name) / (name + '.png')
                path.write_bytes(png(w, h, shade=20 + n * 35))
                self.ok('say', self.ODD, '--from', 'fork', '-', '--image', str(path), '--caption', name, '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input='תמונה ' + name)
        self.browser.open('about:blank')
        self.open_thread(size, self.ODD, 'תמונות חריגות')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .shot img").length===5)' % json.dumps(self.ODD), timeout=40, what='the five pictures')
        if size[1] < 700:
            self.browser.eval('(()=>{document.documentElement.classList.add("coarse","touch");return "ok";})()')

    def open_picture(self, n):
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot-open")[%d].click();return "ok";})()' % n)
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        self.browser.wait('JSON.stringify((()=>{const p=document.querySelector("#reader-body .pager"),v=p.getBoundingClientRect(),g=[...p.querySelectorAll(".page")].find(g=>Math.abs(g.getBoundingClientRect().left-v.left)<2),i=g&&g.querySelector("img");return !!i&&i.complete&&i.getBoundingClientRect().width>0;})())', what='the picture drawn')
        time.sleep(0.3)

    # ══ holes ════════════════════════════════════════════════════════════════

    def test_hole_two_fingers_on_two_pages_fight_over_the_row_and_turn_the_page(self):
        """Each page keeps its own count of fingers. While one finger holds the row a little to the side, the page
        beside it shows; a second finger that lands on THAT page is 'one finger' to it, and both pull the row."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(2)
        y = 420
        self.assertEqual(self.rest()['says'], '3 מתוך 6')
        # the first finger pulls the row 60 px (less than the quarter that turns a page) and stays down
        self.hand(f, 200, y, 60, steps=6, gap=0.02, lift=False)
        time.sleep(0.15)
        pulled = self.row()
        self.assertTrue(pulled['held'] and abs(abs(pulled['off']) - 60) < 3, pulled)
        # the second finger lands on the strip of the next page, which came in at the left
        hit = self.browser.eval('(()=>{const p=document.elementFromPoint(30,%d).closest(".page");return JSON.stringify(p?[...p.parentNode.children].indexOf(p):-1);})()' % y)
        self.assertEqual(hit, 3, 'the test is wrong: the second finger must land on the next page')
        self.tp(f, 'touchStart', {0: (260, y), 1: (30, y)})
        seen = [pulled['left']]
        for i in range(1, 11):
            self.tp(f, 'touchMove', {0: (260 + 2 * i, y), 1: (30 + 14 * i, y)})
            time.sleep(0.05)
            seen.append(self.row()['left'])
        self.tp(f, 'touchEnd', {0: (280, y)})           # the first finger went 80 px in all: on its own, the row goes back
        time.sleep(0.05)
        self.tp(f, 'touchEnd', {1: (170, y)})
        after = self.rest()
        jumps = [round(abs(b - a)) for a, b in zip(seen, seen[1:])]
        with self.subTest('the row does not jump'):
            self.assertLessEqual(max(jumps), 30, 'no finger moved more than 14 px between two readings, and the row jumped: %s (places %s)' % (jumps, seen))
        with self.subTest('the page does not turn'):
            self.assertEqual(after['says'], '3 מתוך 6', 'two fingers were on the gallery and the page turned: %s' % after)

    def test_hole_two_fingers_put_down_while_the_row_still_slides_do_not_enlarge(self):
        """The same hole as he would meet it: a swipe, and at once two fingers to enlarge the picture that comes in.
        For 420 ms two pages are on the screen; a finger on each is no pinch for either."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(2)
        y = 420
        self.browser.eval('(()=>{window.__hits=[];document.addEventListener("pointerdown",e=>{const p=e.target.closest&&e.target.closest(".page");window.__hits.push(p?[...p.parentNode.children].indexOf(p):-1);},true);return "ok";})()')
        self.hand(f, 100, y, 150, steps=5, gap=0.012)
        self.tp(f, 'touchStart', {0: (100, y)})
        self.tp(f, 'touchStart', {0: (100, y), 1: (300, y)})
        for i in range(1, 9):
            self.tp(f, 'touchMove', {0: (100 - 5 * i, y), 1: (300 + 5 * i, y)})
            time.sleep(0.02)
        self.tp(f, 'touchEnd', {0: (60, y)})
        self.tp(f, 'touchEnd', {1: (340, y)})
        hits = self.browser.eval('JSON.stringify(window.__hits)')
        after = self.rest()
        if len(hits) < 3 or hits[-1] == hits[-2]:
            self.skipTest('the two fingers came down on one page (the row had arrived, or had not yet moved): %s' % hits)
        with self.subTest('the swipe is not undone'):
            self.assertEqual(after['says'], '4 מתוך 6', 'the swipe had asked for the fourth picture; two fingers (on pages %s) left the row here: %s' % (hits[-2:], after))
        with self.subTest('the picture is enlarged'):
            self.assertEqual(after['fitted'], 'false', 'two fingers moved apart from 200 px to 280 px and nothing was enlarged (they landed on pages %s): %s' % (hits[-2:], after))

    def test_hole_a_very_wide_picture_is_not_whole_when_he_comes_back_and_eats_a_swipe(self):
        """A picture whose size on the screen is under 10% of its own (a panorama, a long screenshot): every 'fit'
        but the first goes through set(), which never goes under 10%. Leaving a page asks for 'fit'."""
        self.odd(PHONE)
        f = self.moving()
        self.open_picture(1)                    # 4000 x 300 on a 360 px screen: whole at 8%
        first = self.rest()
        self.assertEqual((first['says'], first['maxX'], first['wide']), ('2 מתוך 5', 0, 336), first)
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        self.assertEqual(self.rest()['says'], '3 מתוך 5')
        self.browser.eval('(()=>{readerGallery.go(-1);return "ok";})()')
        back = self.rest()
        self.assertEqual(back['says'], '2 מתוך 5', back)
        with self.subTest('whole again'):
            self.assertEqual((back['maxX'], back['wide'], back['fitted']), (0, 336, 'true'), 'he only passed by, and the picture is no longer whole on the screen (the tool still says "fit"): %s' % back)
        with self.subTest('one swipe turns the page'):
            self.hand(f, 60, 420, 220, steps=8, gap=0.015)
            self.assertEqual(self.rest()['says'], '3 מתוך 5', 'a swipe over a picture that was never enlarged did not turn the page')

    def test_hole_a_very_wide_picture_pinched_smaller_grows_and_the_double_tap_dies(self):
        self.odd(PHONE)
        f = self.moving()
        self.open_picture(1)
        first = self.rest()
        self.assertEqual((first['maxX'], first['wide']), (0, 336), first)
        y = first['paneBox'][1] + 20
        with self.subTest('pinched smaller it ends whole on the screen'):
            f.pinch(180, y, 0.5)
            small = self.rest()
            self.assertEqual((small['maxX'], small['wide']), (0, 336), 'two fingers moved together and the picture ended LARGER than the screen: %s' % small)
        with self.subTest('"fit" fits'):
            self.browser.eval('(()=>{document.querySelector("#reader-tools button[aria-pressed]").click();return "ok";})()')
            fit = self.rest()
            self.assertEqual((fit['maxX'], fit['wide']), (0, 336), fit)
        with self.subTest('a double tap enlarges and brings back, every time'):
            sizes = []
            for _ in range(4):
                self.double_tap(f, 180, y)
                sizes.append(self.rest()['wide'])
            self.assertTrue(sizes[0] > 600 and sizes[1] == 336 and sizes[2] > 600 and sizes[3] == 336, 'the picture after each of four double taps: %s' % sizes)

    def test_hole_a_double_tap_on_the_small_picture_opens_it_enlarged(self):
        """The first tap opens the gallery; the second lands on its page, and the browser calls the pair a double
        tap. In the gallery the whole page listens for one (before, only the picture itself did)."""
        seen = ('(()=>{window.__ev=[];for(const k of ["pointerdown","dblclick"])document.addEventListener(k,e=>window.__ev.push([k,!!(e.target.closest&&e.target.closest("#reader"))]),true);return "ok";})()')
        where = '(()=>{const b=document.querySelectorAll("#log .shot-open")[4];b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return JSON.stringify([r.left+r.width/2,r.top+r.height/2]);})()'
        with self.subTest('a finger'):
            self.show(PHONE)
            f = self.moving()
            self.browser.eval(seen)
            at = self.browser.eval(where)
            f.tap(at[0], at[1], 2)
            self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
            time.sleep(0.6)
            events, now = self.browser.eval('JSON.stringify(window.__ev)'), self.rest()
            if ['dblclick', True] not in events:
                self.skipTest('the second tap came too late to be a double tap (a slow run): %s' % events)
            self.assertEqual((now['says'], now['fitted'], now['maxX']), ('5 מתוך 6', 'true', 0), 'two taps on the small picture: it opened enlarged, and a swipe now moves it and does not turn the page: %s' % now)
        with self.subTest('a mouse'):
            self.show(DESK)
            f = self.moving()
            self.browser.eval(seen)
            at = self.browser.eval(where)
            for n in (1, 2):
                f.call('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': at[0], 'y': at[1], 'button': 'left', 'clickCount': n})
                f.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': at[0], 'y': at[1], 'button': 'left', 'clickCount': n})
                time.sleep(0.18)
            time.sleep(0.6)
            events, now = self.browser.eval('JSON.stringify(window.__ev)'), self.rest()
            if ['dblclick', True] not in events:
                self.skipTest('the second click did not land on the reader: %s' % events)
            self.assertEqual((now['says'], now['fitted'], now['maxX']), ('5 מתוך 6', 'true', 0), 'a double click on the small picture opened it enlarged: %s' % now)

    def test_hole_every_page_he_passed_keeps_its_picture(self):
        """Promised: only the page on the screen and its two neighbours hold an <img>."""
        self.show(DESK)
        self.press_picture(0)
        self.assertLessEqual(self.rest()['imgs'], 3)
        for _ in range(5):
            self.key('ArrowLeft')
            self.rest()
        now = self.rest()
        self.assertEqual(now['says'], '6 מתוך 6', now)
        self.assertLessEqual(now['imgs'], 3, 'after walking to the last picture every page still holds its picture: %s' % now)

    def test_hole_a_press_of_the_arrow_that_comes_before_the_row_is_half_way_is_lost(self):
        """go() adds its step to the page the row last PASSED, which changes only when the row is half way."""
        self.show(DESK)
        self.moving()
        self.many(40, 0)
        with self.subTest('the arrow key'):
            self.browser.eval('(()=>{let n=0;const press=()=>{document.dispatchEvent(new KeyboardEvent("keydown",{code:"ArrowLeft",key:"ArrowLeft",bubbles:true,cancelable:true}));if(++n<4)setTimeout(press,100);};press();return "ok";})()')
            time.sleep(0.6)
            self.assertEqual(self.rest()['says'], '5 מתוך 40', 'four presses of the arrow, 100 ms apart')
        self.close()
        self.many(40, 0)
        with self.subTest('the side button'):
            self.browser.eval('(()=>{let n=0;const b=document.querySelector("#reader .gal-nav.next"),press=()=>{b.click();if(++n<4)setTimeout(press,100);};press();return "ok";})()')
            time.sleep(0.6)
            self.assertEqual(self.rest()['says'], '5 מתוך 40', 'four presses of the side button, 100 ms apart')
        self.close()
        self.many(40, 0)
        with self.subTest('the arrow, then "+" for the picture he went to'):
            # until the row is half way the tools, the title and the download link are still those of the picture he left
            self.browser.eval('(()=>{const key=code=>document.dispatchEvent(new KeyboardEvent("keydown",{code,key:code,bubbles:true,cancelable:true}));key("ArrowLeft");setTimeout(()=>key("Equal"),80);return "ok";})()')
            time.sleep(0.6)
            now = self.rest()
            self.assertEqual((now['says'], now['fitted']), ('2 מתוך 40', 'false'), 'the arrow and, 80 ms later, "+": the picture he went to was not enlarged (the "+" went to the one he had left): %s' % now)

    def test_hole_on_a_screen_whose_width_is_not_a_whole_number_the_row_is_sent_beside_the_page(self):
        """A 1080 px phone at 2.625 is 411.43 px wide. The place of a page is taken as index x clientWidth, and
        clientWidth is a whole number: 0.43 px off for every page before it."""
        self.show(DESK)
        f = self.moving()
        self.browser.eval('(()=>{document.documentElement.classList.add("coarse","touch");document.querySelector(".dialog.reader").style.width="calc(1080px / 2.625)";return "ok";})()')
        self.many(40, 30)
        start = self.rest()
        self.assertEqual((start['says'], round(start['width'], 1)), ('31 מתוך 40', 411.4), start)
        self.browser.eval('(()=>{const pager=document.querySelector("#reader-body .pager");window.__to=[];window.__at=[];const t0=performance.now(),real=pager.scrollTo.bind(pager);'
                          'pager.scrollTo=o=>{window.__to.push(o.left);return real(o);};pager.addEventListener("scroll",()=>window.__at.push([Math.round(performance.now()-t0),+pager.scrollLeft.toFixed(1)]));return "ok";})()')
        box = start['paneBox']
        self.hand(f, box[0] + 80, box[1] + 200, 200, steps=6, gap=0.012)
        after = self.rest()
        self.assertEqual(after['says'], '32 מתוך 40', after)
        asked = self.browser.eval('JSON.stringify(window.__to)')
        trace = self.browser.eval('JSON.stringify(window.__at)')
        self.assertTrue(asked, 'the finger did not turn the page')
        self.assertLess(abs(asked[-1] - after['left']), 1.5, 'the row was sent to %s and the page is at %s: it stops beside the page and is pulled onto it only when the 420 ms are over. The row: %s' % (asked[-1], after['left'], trace[-12:]))

    def test_hole_two_fingers_do_not_enlarge_about_the_point_between_them_on_a_picture_narrower_than_its_page(self):
        """Promised: two fingers zoom about the point between them, the picture follows that point. The sum is done
        from the edge of the page; a picture narrower than its page stands in the middle of it."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(1)                   # 300 x 900: 216 px wide in a 360 px page
        fit = self.rest()
        self.assertLess(fit['wide'], 300, fit)
        px, py = 130, fit['paneBox'][1] + fit['paneBox'][3] // 2
        under = lambda now: (px - now['imgLeft']) / now['wide']
        before = under(fit)
        f.pinch(px, py, 3)
        big = self.rest()
        self.assertGreater(big['wide'], fit['wide'] * 2.5, big)
        after = under(big)
        self.assertLess(abs(after - before) * big['wide'], 20, 'the fingers held the picture at %.0f%% of its width, and after the pinch that point is %.0f px away from them (they are over %.0f%%)' % (before * 100, abs(after - before) * big['wide'], after * 100))

    def test_hole_when_one_of_three_fingers_is_lifted_the_picture_jumps(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(0)
        fit = self.rest()
        x, y = 180, fit['paneBox'][1] + 120
        self.tp(f, 'touchStart', {0: (x - 40, y)})
        self.tp(f, 'touchStart', {0: (x - 40, y), 1: (x + 40, y)})
        for i in range(1, 6):
            self.tp(f, 'touchMove', {0: (x - 40 - 6 * i, y), 1: (x + 40 + 6 * i, y)})
            time.sleep(0.02)
        time.sleep(0.3)
        pinched = self.row()
        self.assertGreater(pinched['wide'], fit['wide'] * 1.4, pinched)
        self.tp(f, 'touchStart', {0: (x - 70, y), 1: (x + 70, y), 2: (x + 75, y + 220)})      # a third finger (the palm) rests lower down
        time.sleep(0.2)
        self.tp(f, 'touchEnd', {0: (x - 70, y)})                                              # the first finger leaves
        time.sleep(0.2)
        self.tp(f, 'touchMove', {1: (x + 71, y), 2: (x + 75, y + 220)})                       # the second moves by one pixel
        time.sleep(0.3)
        moved = self.row()
        self.tp(f, 'touchEnd', {})
        self.assertEqual(moved['says'], '1 מתוך 6')
        self.assertLess(abs(moved['wide'] - pinched['wide']), pinched['wide'] * 0.05, 'a finger moved by 1 px and the picture went from %d px to %d px wide, from %s to %s' % (pinched['wide'], moved['wide'], pinched['x'], moved['x']))

    def test_hole_the_picture_he_leaves_jumps_back_to_its_size_while_half_of_it_is_still_on_the_screen(self):
        """'Whole again when he comes back' is done the moment the row is half way, under his eyes."""
        self.show(DESK)
        self.moving()
        self.press_picture(0)
        for _ in range(4):
            self.key('Equal')
        big = self.rest()
        self.assertEqual(big['fitted'], 'false', big)
        self.browser.eval('(()=>{const pager=document.querySelector("#reader-body .pager"),img=pager.querySelector(".page img");window.__seen=[];'
                          'pager.addEventListener("scroll",()=>window.__seen.push([+(Math.abs(pager.scrollLeft)/pager.clientWidth).toFixed(2),Math.round(img.getBoundingClientRect().width)]));return "ok";})()')
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        self.assertEqual(self.rest()['says'], '2 מתוך 6')
        seen = self.browser.eval('JSON.stringify(window.__seen)')
        early = [row for row in seen if row[0] < 0.9 and row[1] != big['wide']]
        self.assertEqual(early[:1], [], 'the picture he was leaving went from %d px to %d px wide when only %d%% of the way was done (the row: %s)' % (big['wide'], early[0][1] if early else 0, round(early[0][0] * 100) if early else 0, seen[:14]))

    def test_hole_the_momentum_of_a_picture_goes_on_after_the_reader_closed(self):
        """Promised: nothing keeps running after the reader closes, the momentum of a moving picture included."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(0)
        for _ in range(8):
            self.key('Equal')
        big = self.rest()
        self.assertGreater(big['maxX'], 1500, big)
        y = big['paneBox'][1] + 120
        self.browser.eval('(()=>{document.querySelector("#reader-body .pic-pane").scrollLeft=0;window.__ticks=0;const real=window.requestAnimationFrame;'
                          'window.requestAnimationFrame=function(fn){return real.call(window,t=>{if(/scrollLeft-=vx/.test(String(fn)))window.__ticks++;fn(t);});};return "ok";})()')
        self.hand(f, 300, y, -240, steps=6, gap=0.03)
        time.sleep(0.1)
        self.browser.eval('(()=>{closeReader();window.__closed=window.__ticks;return "ok";})()')
        time.sleep(0.6)
        closed, later = self.browser.eval('JSON.stringify([window.__closed,window.__ticks])')
        if not closed:
            self.skipTest('the picture was not let go while moving (a slow run): no momentum to speak of')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#reader").hidden)'))
        self.assertLessEqual(later - closed, 1, 'the reader is closed and the momentum of the picture ran %d more frames' % (later - closed))

    def test_hole_the_keys_fall_out_of_the_reader_when_the_page_turns(self):
        """The tools of the picture are replaced when the page turns; the one the keys stood on is gone."""
        self.show(DESK)
        self.moving()
        self.press_picture(0)
        self.browser.eval('(()=>{[...document.querySelectorAll("#reader-tools button")].find(b=>b.textContent==="+").focus();return "ok";})()')
        self.browser.press('Enter')
        self.assertEqual(self.rest()['fitted'], 'false')
        self.browser.press('ArrowLeft')
        time.sleep(0.5)
        self.browser.press('ArrowLeft')
        self.assertIn(self.rest()['says'], ('2 מתוך 6', '3 מתוך 6'))
        where = self.browser.eval('JSON.stringify([document.activeElement.tagName,document.querySelector("#reader").contains(document.activeElement)])')
        self.assertTrue(where[1], 'the keys stood on "+" in the reader; after the page turned they are on %s, outside the window' % where[0])

    def test_hole_the_place_is_not_said_to_a_screen_reader_when_the_page_turns(self):
        self.show(DESK)
        self.press_picture(0)
        live = self.browser.eval('(()=>{const lives=n=>{for(;n&&n.id!=="reader";n=n.parentElement){const l=n.getAttribute("aria-live"),r=n.getAttribute("role");if((l&&l!=="off")||r==="status"||r==="log")return true;}return false;};'
                                 'return JSON.stringify([lives(document.querySelector("#reader-tools .gal-count")),lives(document.querySelector("#reader-title"))]);})()')
        self.assertTrue(any(live), 'neither "3 מתוך 6" nor the title is in a live region: a press on "the next picture" says nothing')

    def test_hole_the_side_buttons_lie_over_the_picture(self):
        self.show(DESK)
        self.press_picture(2)                   # the wide one: it fills the width of its page
        now = self.rest()
        navs = self.browser.eval('JSON.stringify([...document.querySelectorAll("#reader .gal-nav")].map(n=>{const r=n.getBoundingClientRect();return [r.left,r.right,r.top,r.bottom];}))')
        left, right, top, bottom = now['imgLeft'], now['imgLeft'] + now['wide'], now['imgTop'], now['imgTop'] + now['imgHigh']
        over = [round(min(r[1], right) - max(r[0], left)) for r in navs if min(r[1], right) > max(r[0], left) and min(r[3], bottom) > max(r[2], top)]
        self.assertEqual(over, [], 'each side button covers that many px of the picture\'s width: %s' % over)

    def test_hole_a_tall_picture_that_fits_its_page_is_cut_and_moves_up_and_down(self):
        """The width is rounded to a whole pixel; the height follows it, and a tall picture ends higher than its page."""
        self.odd(PHONE)
        self.open_picture(2)                    # 300 x 4000
        now = self.rest()
        self.assertEqual((now['says'], now['fitted']), ('3 מתוך 5', 'true'), now)
        self.assertEqual(now['maxY'], 0, 'the picture is "fitted" and is %d px higher than its page' % now['maxY'])

    def test_hole_a_pull_the_system_took_away_turns_the_page(self):
        """A judgment: a finger the system cancels (a call comes in, the palm, the edge gesture) did not ask for
        anything. Past a quarter of the width the cancelled pull is carried out like a lifted one."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(2)
        self.assertEqual(self.rest()['says'], '3 מתוך 6')
        self.hand(f, 100, 420, 140, steps=8, gap=0.02, lift=False)       # 140 px of 360: under half the page
        f.call('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        now = self.rest()
        self.assertEqual((now['says'], now['off'], now['held']), ('3 מתוך 6', 0, False), 'the system took the finger away in the middle of a pull, and the page turned: %s' % now)

    def test_hole_a_pinch_let_go_sends_the_picture_sliding(self):
        """A judgment: the finger that is lifted second after a pinch is 'moving the picture', and gives it momentum."""
        self.show(PHONE)
        f = self.moving()
        self.press_picture(0)
        fit = self.rest()
        x, y = 180, fit['paneBox'][1] + 120
        self.tp(f, 'touchStart', {0: (x - 40, y)})
        self.tp(f, 'touchStart', {0: (x - 40, y), 1: (x + 40, y)})
        for i in range(1, 9):
            self.tp(f, 'touchMove', {0: (x - 40 - 10 * i, y), 1: (x + 40 + 10 * i, y)})
            time.sleep(0.02)
        self.tp(f, 'touchEnd', {1: (x + 120, y)})          # one finger is lifted, the other is still on its way out
        for i in range(1, 4):
            self.tp(f, 'touchMove', {0: (x - 120 - 10 * i, y)})
            time.sleep(0.02)
        self.tp(f, 'touchEnd', {})
        time.sleep(0.06)
        at_lift = self.row()
        time.sleep(0.9)
        later = self.row()
        self.assertEqual(later['says'], '1 מתוך 6')
        if later['x'] >= later['maxX'] - 1 or at_lift['x'] >= at_lift['maxX'] - 1:
            self.skipTest('the picture stood at its edge: nothing to see')
        self.assertLess(abs(later['x'] - at_lift['x']), 12, 'after both fingers of a pinch were lifted the picture slid on by %.0f px' % abs(later['x'] - at_lift['x']))

    # ══ held ═════════════════════════════════════════════════════════════════

    def test_held_with_motion_swipes_turn_one_page_each_and_the_row_rests_on_a_page(self):
        self.show(PHONE)
        f = self.moving()
        self.watch_errors()
        self.press_picture(1)
        y = 420
        self.hand(f, 60, y, 180)
        now = self.rest()
        self.assertEqual((now['says'], now['off'], now['title']), ('3 מתוך 6', 0, 'צילום שלישי, רחב'), now)
        # a short slow pull goes back
        self.hand(f, 100, y, 50, steps=6, gap=0.05)
        time.sleep(0.15)
        self.assertEqual((self.rest()['says'], self.rest()['off']), ('3 מתוך 6', 0))
        # a second swipe while the first is still on its way: two swipes, two pages
        self.hand(f, 60, y, 180)
        time.sleep(0.05)
        self.hand(f, 60, y, 180)
        now = self.rest()
        self.assertEqual((now['says'], now['off']), ('5 מתוך 6', 0), now)
        # back and onward at once: where it was
        self.hand(f, 300, y, -180)
        time.sleep(0.05)
        self.hand(f, 60, y, 180)
        self.assertEqual(self.rest()['says'], '5 מתוך 6')
        # at the last picture a finger that asks for more stays
        self.hand(f, 60, y, 180)
        self.hand(f, 60, y, 180)
        now = self.rest()
        self.assertEqual((now['says'], now['off']), ('6 מתוך 6', 0), now)
        # five fast swipes back
        for _ in range(5):
            self.hand(f, 300, y, -200, steps=4, gap=0.008)
        now = self.rest()
        self.assertEqual((now['off'], now['held']), (0, False), 'after five fast swipes the row is between two pages: %s' % now)
        self.assertEqual(now['says'], '%d מתוך 6' % (now['near'] + 1), now)
        self.assertLess(now['near'], 4, 'five fast swipes back did not move the row at all: %s' % now)
        self.assertEqual(self.errors(), [])

    def test_held_up_and_down_and_slanted_fingers_on_a_fitted_picture(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(2)
        y = 300
        # up and down: nothing
        self.tp(f, 'touchStart', {0: (180, y)})
        for i in range(1, 8):
            self.tp(f, 'touchMove', {0: (180 + 4 * i, y + 30 * i)})
            time.sleep(0.012)
        self.tp(f, 'touchEnd', {})
        now = self.rest()
        self.assertEqual((now['says'], now['off'], now['y']), ('3 מתוך 6', 0, 0), now)
        # more up than sideways, though far sideways: still nothing
        self.tp(f, 'touchStart', {0: (100, y)})
        for i in range(1, 8):
            self.tp(f, 'touchMove', {0: (100 + 20 * i, y + 30 * i)})
            time.sleep(0.012)
        self.tp(f, 'touchEnd', {})
        self.assertEqual(self.rest()['says'], '3 מתוך 6')
        # more sideways than down: the page turns
        self.tp(f, 'touchStart', {0: (100, y)})
        for i in range(1, 8):
            self.tp(f, 'touchMove', {0: (100 + 30 * i, y + 20 * i)})
            time.sleep(0.012)
        self.tp(f, 'touchEnd', {})
        self.assertEqual(self.rest()['says'], '4 מתוך 6')

    def test_held_two_fingers_on_one_page_never_turn_it(self):
        self.show(PHONE)
        f = self.moving()
        self.watch_errors()
        self.press_picture(0)
        fit = self.rest()
        x, y = 180, fit['paneBox'][1] + 120
        # the middle between the fingers wanders 150 px sideways while they open
        f.pinch(120, y, 2.5, drift=100)
        big = self.rest()
        self.assertEqual((big['says'], big['off']), ('1 מתוך 6', 0), big)
        self.assertGreater(big['wide'], fit['wide'] * 1.8, big)
        # far smaller than the screen: whole on it
        f.pinch(x, y, 0.3)
        small = self.rest()
        self.assertEqual((small['says'], small['wide'], small['maxX'], small['fitted']), ('1 מתוך 6', fit['wide'], 0, 'true'), small)
        # two fingers open; one is lifted; the other goes on moving the picture: no jump, and no page beyond its edge
        self.tp(f, 'touchStart', {0: (x - 40, y)})
        self.tp(f, 'touchStart', {0: (x - 40, y), 1: (x + 40, y)})
        for i in range(1, 11):
            self.tp(f, 'touchMove', {0: (x - 40 - 8 * i, y), 1: (x + 40 + 8 * i, y)})
            time.sleep(0.02)
        time.sleep(0.25)
        a = self.row()
        self.tp(f, 'touchEnd', {1: (x + 120, y)})
        time.sleep(0.25)
        b = self.row()
        self.assertEqual((b['x'], b['wide']), (a['x'], a['wide']), 'lifting one finger moved the picture')
        for i in range(1, 6):
            self.tp(f, 'touchMove', {0: (x - 120 + 10 * i, y)})
            time.sleep(0.03)
        time.sleep(0.25)
        c = self.row()
        self.assertAlmostEqual(c['x'], b['x'] - 50, delta=2, msg='the finger that stayed did not move the picture with it')
        # the picture is put near its left edge, and the same finger drags on far beyond it
        self.browser.eval('(()=>{document.querySelector("#reader-body .pic-pane").scrollLeft=30;return "ok";})()')
        for i in range(1, 21):
            self.tp(f, 'touchMove', {0: (x - 70 + 12 * i, y)})
            time.sleep(0.012)
        time.sleep(0.25)
        self.tp(f, 'touchEnd', {})
        d = self.rest()
        self.assertEqual((d['says'], d['off'], d['x']), ('1 מתוך 6', 0, 0), d)
        self.assertEqual(self.errors(), [])

    def test_held_a_second_finger_on_the_same_page_sends_the_row_back(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(2)
        y = 400
        self.hand(f, 120, y, 120, steps=8, gap=0.02, lift=False)
        time.sleep(0.15)
        self.assertTrue(self.row()['held'])
        self.tp(f, 'touchStart', {0: (240, y), 1: (300, y)})
        time.sleep(0.7)
        back = self.row()
        self.assertEqual((back['off'], back['held']), (0, False), back)
        for i in range(1, 6):
            self.tp(f, 'touchMove', {0: (240 - 6 * i, y), 1: (300 + 6 * i, y)})
            time.sleep(0.02)
        self.tp(f, 'touchEnd', {})
        now = self.rest()
        self.assertEqual((now['says'], now['off'], now['fitted']), ('3 מתוך 6', 0, 'false'), now)

    def test_held_an_enlarged_picture_moves_under_one_finger_and_turns_the_page_only_from_its_edge(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(4)
        fit = self.rest()
        y = fit['paneBox'][1] + 150
        for _ in range(4):
            self.key('Equal')
        big = self.rest()
        self.assertGreater(big['maxX'], 300, big)
        mid = 'document.querySelector("#reader-body .page:nth-child(5) .pic-pane")'
        self.browser.eval('(()=>{%s.scrollLeft=200;return "ok";})()' % mid)
        self.hand(f, 250, y, -150, steps=6, gap=0.03)
        time.sleep(0.2)
        moved = self.rest()
        self.assertEqual(moved['says'], '5 מתוך 6', moved)
        self.assertGreaterEqual(moved['x'], 345, moved)
        # at its right edge a finger that goes left has nothing more to show: the page before
        self.browser.eval('(()=>{%s.scrollLeft=1e6;return "ok";})()' % mid)
        self.hand(f, 250, y, -150)
        self.assertEqual(self.rest()['says'], '4 מתוך 6')
        self.hand(f, 60, y, 180)
        again = self.rest()
        self.assertEqual((again['says'], again['maxX'], again['fitted']), ('5 מתוך 6', 0, 'true'), 'left enlarged, it is whole again: %s' % again)

    def test_held_back_or_a_cancel_in_the_middle_of_a_pull_leaves_nothing_stuck(self):
        self.show(PHONE)
        f = self.moving()
        self.watch_errors()
        self.press_picture(2)
        y = 400
        self.hand(f, 120, y, 120, steps=8, gap=0.02, lift=False)
        self.browser.eval('(()=>{history.back();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        self.tp(f, 'touchMove', {0: (260, y)})
        self.tp(f, 'touchEnd', {})
        time.sleep(0.5)
        self.assertEqual(self.browser.eval('JSON.stringify([view.ch,!!readerGallery,!!readerPic,document.querySelector("#reader-body").childNodes.length])'), [self.TID, False, False, 0])
        self.press_picture(3)
        self.assertEqual(self.rest()['says'], '4 מתוך 6')
        self.hand(f, 60, y, 180)
        self.assertEqual(self.rest()['says'], '5 מתוך 6')
        # the system takes the finger away in the middle of a small pull: the row goes back and snaps again
        self.hand(f, 120, y, 40, steps=8, gap=0.02, lift=False)
        f.call('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        now = self.rest()
        self.assertEqual((now['says'], now['off'], now['held']), ('5 מתוך 6', 0, False), now)
        self.assertEqual(self.errors(), [])

    def test_held_the_window_changes_its_size_and_the_same_picture_stays(self):
        self.show(PHONE)
        self.moving()
        self.watch_errors()
        self.press_picture(3)
        for w, h in ((750, 835), (360, 840), (840, 360), (360, 840)):
            self.browser.viewport(w, h)
            now = self.rest()
            self.assertEqual((now['says'], abs(now['off']) < 1, now['maxX'], now['fitted']), ('4 מתוך 6', True, 0, 'true'), (w, h, now))
        self.assertEqual(self.errors(), [])

    def test_held_a_real_double_tap_enlarges_and_brings_back_also_beside_the_picture(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(0)
        fit = self.rest()
        y = fit['paneBox'][1] + 60
        self.double_tap(f, 100, y)
        big = self.rest()
        self.assertEqual((big['says'], big['fitted']), ('1 מתוך 6', 'false'), big)
        self.assertGreater(big['wide'], fit['wide'] * 1.8)
        self.double_tap(f, 100, y)
        self.assertEqual(self.rest()['wide'], fit['wide'])
        self.double_tap(f, 180, fit['paneBox'][1] + fit['paneBox'][3] - 60)          # on the empty part of the page, under the picture
        self.assertGreater(self.rest()['wide'], fit['wide'] * 1.8)

    def test_held_a_wheel_a_mouse_the_side_buttons_and_the_keys_after_them(self):
        self.show(DESK)
        f = self.moving()
        self.watch_errors()
        self.press_picture(0)
        box = self.rest()['paneBox']
        x, y = box[0] + box[2] / 2, box[1] + box[3] / 2
        f.call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': x, 'y': y, 'deltaX': -300, 'deltaY': 0})
        self.assertEqual(self.rest()['says'], '1 מתוך 6')
        f.call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': x, 'y': y, 'deltaX': -700, 'deltaY': 0})
        now = self.rest()
        self.assertEqual((now['says'], now['title'], now['off']), ('2 מתוך 6', 'צילום שני, גבוה', 0), now)
        # a double click enlarges; the mouse drags the enlarged picture
        for n in (1, 2):
            f.call('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y - 200, 'button': 'left', 'clickCount': n})
            f.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y - 200, 'button': 'left', 'clickCount': n})
        self.assertEqual(self.rest()['fitted'], 'false')
        for _ in range(4):
            self.key('Equal')
        a = self.rest()
        f.call('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        for i in range(1, 6):
            f.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y - 30 * i, 'button': 'left', 'buttons': 1})
        f.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y - 150, 'button': 'left', 'clickCount': 1})
        b = self.rest()
        self.assertAlmostEqual(b['y'], a['y'] + 150, delta=3)
        self.assertEqual(b['says'], '2 מתוך 6')
        # the side button to the last picture, where it is switched off under the mouse: the keys still answer
        for _ in range(6):
            r = self.browser.eval('(()=>{const b=document.querySelector("#reader .gal-nav.next"),r=b.getBoundingClientRect();return JSON.stringify([r.left+r.width/2,r.top+r.height/2]);})()')
            f.call('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': r[0], 'y': r[1], 'button': 'left', 'clickCount': 1})
            f.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': r[0], 'y': r[1], 'button': 'left', 'clickCount': 1})
            self.rest()
        self.assertEqual(self.rest()['says'], '6 מתוך 6')
        self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll("#reader .gal-nav")].map(b=>b.disabled))'), [False, True])
        self.browser.press('ArrowRight')
        self.assertEqual(self.rest()['says'], '5 מתוך 6')
        self.browser.press('Tab')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#reader").contains(document.activeElement))'))
        self.browser.press('Control+k')
        self.assertTrue(self.browser.eval('JSON.stringify(!document.querySelector("#reader").hidden&&view.ch===%s)' % json.dumps(self.TID)), 'the thread was switched under the open reader')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        self.assertEqual(self.errors(), [])

    def test_held_a_picture_of_a_carousel_opens_in_the_gallery_on_itself(self):
        self.needs('images')
        tid = 'e2e-gallery-carousel'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'קרוסלה וגלריה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            files = []
            for n in range(4):
                path = Path(self.tmp.name) / ('car%d.png' % n)
                path.write_bytes(png(300 + 40 * n, 200, shade=30 + n * 40))
                files.append(str(path))
            say = lambda text, *shots: self.ok('say', tid, '--from', 'fork', '-', *[arg for path, caption in shots for arg in ('--image', path, '--caption', caption)], '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input=text)
            say('לפני', (files[0], 'לפני הקרוסלה'))
            say('שתיים בקרוסלה, בסדר הפוך:\n```carousel\n{"slides":[{"title":"שקופית א","image":2},{"title":"שקופית ב","image":1}]}\n```', (files[1], 'בקרוסלה 1'), (files[2], 'בקרוסלה 2'))
            say('אחרי', (files[3], 'אחרי הקרוסלה'))
        self.browser.open('about:blank')
        self.open_thread(DESK, tid, 'קרוסלה וגלריה')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .card.carousel .slide img").length===2&&document.querySelectorAll("#log .shot img").length===2)' % json.dumps(tid), timeout=40, what='the carousel and the two pictures around it')
        for press, says, title, file in (('document.querySelectorAll("#log .card.carousel .slide img")[0]', '3 מתוך 4', 'בקרוסלה 2', 'm2-2.png'),
                                         ('document.querySelectorAll("#log .card.carousel .slide img")[1]', '2 מתוך 4', 'בקרוסלה 1', 'm2-1.png'),
                                         ('document.querySelectorAll("#log .shot-open")[1]', '4 מתוך 4', 'אחרי הקרוסלה', 'm3-1.png')):
            self.browser.eval('(()=>{%s.click();return "ok";})()' % press)
            self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
            now = self.rest()
            shown = self.browser.eval('(()=>{const pager=document.querySelector("#reader-body .pager"),v=pager.getBoundingClientRect(),g=[...pager.querySelectorAll(".page")].find(g=>Math.abs(g.getBoundingClientRect().left-v.left)<2);'
                                      'return JSON.stringify([new URL(g.querySelector("img").src).pathname.split("/").pop(),new URL(document.querySelector("#reader-tools a[download]").href).pathname.split("/").pop()]);})()')
            self.assertEqual((now['says'], now['title'], shown), (says, title, [file, file]), now)
            self.close()

    def test_held_a_row_drawn_before_new_pictures_came_opens_among_all_of_them(self):
        self.needs('images')
        tid = 'e2e-gallery-grow'
        self.ok('new', tid, 'גלריה שגדלה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        files = []
        for n in range(3):
            path = Path(self.tmp.name) / ('grow%d.png' % n)
            path.write_bytes(png(320, 200 + 30 * n, shade=30 + n * 50))
            files.append(str(path))
        say = lambda n: self.ok('say', tid, '--from', 'fork', '-', '--image', files[n], '--caption', 'גדלה %d' % (n + 1), '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input='הודעה %d' % (n + 1))
        say(0)
        say(1)
        self.browser.open('about:blank')
        self.open_thread(DESK, tid, 'גלריה שגדלה')
        shots = 'JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .shot img").length===%%d)' % json.dumps(tid)
        self.browser.wait(shots % 2, timeout=40, what='the two pictures')
        self.watch_errors()
        self.browser.eval('(()=>{window.__first=document.querySelectorAll("#log .shot-open")[0];window.__first.click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        self.assertEqual(self.rest()['says'], '1 מתוך 2')
        say(2)                                   # a third picture arrives while the gallery is open
        self.browser.wait(shots % 3, timeout=40, what='the third picture in the conversation')
        still = self.rest()
        self.assertEqual((still['says'], still['title'], still['off']), ('1 מתוך 2', 'גדלה 1', 0), 'the open gallery changed under him: %s' % still)
        self.key('ArrowLeft')
        self.assertEqual(self.rest()['says'], '2 מתוך 2')
        self.key('ArrowLeft')
        self.assertEqual(self.rest()['says'], '2 מתוך 2')
        self.browser.eval('(()=>{closeReader();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader closed')
        # the very button that was drawn when the thread had two pictures
        self.assertTrue(self.browser.eval('JSON.stringify(window.__first.isConnected)'), 'the row was drawn again: the test no longer says anything about an old row')
        self.browser.eval('(()=>{window.__first.click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        now = self.rest()
        self.assertEqual((now['says'], now['title']), ('1 מתוך 3', 'גדלה 1'), now)
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        self.rest()
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        self.assertEqual((self.rest()['says'], self.rest()['title']), ('3 מתוך 3', 'גדלה 3'))
        self.assertEqual(self.errors(), [])

    def test_held_his_own_pictures_still_on_their_way_are_the_last_pages(self):
        self.needs('images')
        tid = 'e2e-gallery-mine'
        self.ok('new', tid, 'התמונות שלי בדרך', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        server, mine1, mine2 = (Path(self.tmp.name) / name for name in ('srv.png', 'mine1.png', 'mine2.png'))
        server.write_bytes(png(320, 200))
        mine1.write_bytes(png(200, 300, shade=80))
        mine2.write_bytes(png(400, 240, shade=140))
        self.ok('say', tid, '--from', 'fork', '-', '--image', str(server), '--caption', 'מהשרת', '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input='תמונה מהסוכן')
        self.browser.open('about:blank')
        self.open_thread(DESK, tid, 'התמונות שלי בדרך')
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&document.querySelectorAll("#log .shot img").length===1)', timeout=40, what='the picture of the agent')
        self.watch_errors()
        # the line is dead for a message with pictures: it stays on its way
        self.browser.eval('(()=>{const real=window.fetch.bind(window);window.fetch=(url,opts)=>opts&&opts.body&&String(opts.body).includes("\\"images\\":[")?new Promise(()=>{}):real(url,opts);return "ok";})()')
        self.browser.upload('#pic-file', mine1, mine2)
        self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===2)', what='two pictures in the tray')
        self.browser.fill('.tray-caption[data-n="1"]', 'שלי ראשונה')
        self.browser.fill('.tray-caption[data-n="2"]', 'שלי שנייה')
        self.browser.fill('#input', 'שתיים שלי')
        self.browser.click('#send')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img").length===3)', what='his two pictures in the conversation')
        self.assertEqual(len(self.thread(tid)['messages']), 1, 'the message reached the server: the test no longer says anything about pictures on their way')
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot-open")[2].click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .pager img"))', what='the gallery')
        now = self.rest()
        self.assertEqual((now['says'], now['title']), ('3 מתוך 3', 'שלי שנייה'), now)
        self.assertGreater(now['wide'], 100, now)
        link = self.browser.eval('JSON.stringify([document.querySelector("#reader-tools a[download]").href.slice(0,5),document.querySelector("#reader-tools a[download]").download])')
        self.assertEqual(link[0], 'blob:', link)
        self.assertTrue(link[1].startswith('mine2'), link)
        self.key('ArrowRight')
        self.assertEqual((self.rest()['says'], self.rest()['title']), ('2 מתוך 3', 'שלי ראשונה'))
        self.key('ArrowRight')
        self.assertEqual((self.rest()['says'], self.rest()['title']), ('1 מתוך 3', 'מהשרת'))
        self.assertEqual(self.errors(), [])

    def test_held_a_picture_alone_still_answers_the_fingers_as_before(self):
        """The viewer of one picture shares picturePane: two fingers, a double tap on the picture, and one finger
        that the browser itself scrolls with (no pages, no pulling, nothing brought back to 'fit')."""
        self.needs('images')
        tid = 'e2e-gallery-alone'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'תמונה לבדה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            path = Path(self.tmp.name) / 'alone.png'
            path.write_bytes(png(640, 400, shade=60))
            self.ok('say', tid, '--from', 'fork', '-', '--image', str(path), '--caption', 'לבדה', '--by', 'e2e', '--state', 'working', '--note', 'תמונה', input='תמונה אחת')
        self.browser.open('about:blank')
        self.open_thread(PHONE, tid, 'תמונה לבדה')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img").length===1)', timeout=40, what='the picture')
        self.browser.eval('(()=>{document.documentElement.classList.add("coarse","touch");return "ok";})()')
        f = self.moving()
        self.watch_errors()
        self.browser.eval('(()=>{document.querySelector("#log .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body.pic img")&&document.querySelector("#reader-body.pic img").getBoundingClientRect().width>0)', what='the picture on the whole screen')
        look = ('(()=>{const b=document.querySelector("#reader-body"),i=b.querySelector("img"),r=b.getBoundingClientRect();return JSON.stringify({pager:!!b.querySelector(".pager"),cls:b.className,wide:Math.round(i.getBoundingClientRect().width),'
                'x:Math.round(b.scrollLeft),maxX:b.scrollWidth-b.clientWidth,top:Math.round(r.top),touch:getComputedStyle(b).touchAction,fit:document.querySelector("#reader-tools button[aria-pressed]").getAttribute("aria-pressed")});})()')
        fit = self.browser.eval(look)
        self.assertEqual((fit['pager'], fit['cls'], fit['maxX'], fit['touch']), (False, 'reader-body pic photo', 0, 'pan-x pan-y'), fit)
        y = fit['top'] + 100
        f.pinch(180, y, 2.5)
        time.sleep(0.4)
        big = self.browser.eval(look)
        self.assertGreater(big['wide'], fit['wide'] * 2, big)
        # two fingers together: it stays where they left it (only among the pictures of a thread is it brought back to the screen)
        f.pinch(180, y, 0.25)
        time.sleep(0.4)
        small = self.browser.eval(look)
        self.assertLess(small['wide'], fit['wide'], small)
        self.browser.eval('(()=>{document.querySelector("#reader-tools button[aria-pressed]").click();return "ok";})()')
        self.double_tap(f, 180, y)
        tapped = self.browser.eval(look)
        self.assertGreater(tapped['wide'], fit['wide'] * 1.8, tapped)
        # one finger: the browser's own scrolling
        f.swipe(250, y, -150)
        time.sleep(0.4)
        moved = self.browser.eval(look)
        self.assertGreater(moved['x'], tapped['x'] + 100, (tapped, moved))
        self.assertEqual(self.errors(), [])

    def test_held_two_hundred_pictures_open_light_and_stand_on_the_right_one(self):
        self.show(DESK)
        self.moving()
        self.watch_errors()
        t0 = time.monotonic()
        self.many(200, 150)
        now = self.rest()
        self.assertEqual((now['says'], now['title'], now['imgs'], abs(now['off']) < 1), ('151 מתוך 200', 'תמונה 151', 3, True), now)
        made = self.browser.eval('JSON.stringify([document.querySelectorAll("#reader-body .page").length,document.querySelectorAll("#reader-body *").length,document.querySelector("#reader-tools a[download]").getAttribute("href")])')
        self.assertEqual(made[0], 200)
        self.assertLess(made[1], 200 * 2 + 40, 'more than a page and an empty pane for each picture was built')
        self.assertTrue(made[2].endswith('?n=150'), made)
        self.assertLess(time.monotonic() - t0, 15)
        self.key('ArrowLeft')
        self.assertEqual(self.rest()['says'], '152 מתוך 200')
        self.assertEqual(self.errors(), [])

    def test_held_on_a_width_that_is_not_whole_the_row_ends_on_its_page_and_the_edges_of_a_picture_are_edges(self):
        self.show(DESK)
        f = self.moving()
        self.browser.eval('(()=>{document.documentElement.classList.add("coarse","touch");return "ok";})()')
        for width in ('calc(1080px / 2.625)', 'calc(1080px / 2.75)', '412.5px'):
            with self.subTest(width=width):
                self.browser.eval('(()=>{document.querySelector(".dialog.reader").style.width=%s;return "ok";})()' % json.dumps(width))
                self.many(200, 150)
                start = self.rest()
                box = start['paneBox']
                x, y = box[0] + box[2] / 2, box[1] + 200
                try:
                    self.assertEqual((start['says'], abs(start['off']) < 1), ('151 מתוך 200', True), start)
                    self.hand(f, x - 100, y, 200)
                    now = self.rest()
                    self.assertEqual((now['says'], abs(now['off']) < 1), ('152 מתוך 200', True), now)
                except BaseException:
                    self.close()
                    raise
                for _ in range(7):
                    self.key('Equal')
                pane = '[...document.querySelectorAll("#reader-body .page")][151].firstChild'
                self.browser.eval('(()=>{%s.scrollLeft=1e6;return "ok";})()' % pane)
                try:
                    self.assertGreater(self.rest()['maxX'], 300)
                    self.hand(f, x + 100, y, -200)
                    self.assertEqual(self.rest()['says'], '151 מתוך 200', 'at its right edge the enlarged picture did not let the page turn')
                finally:
                    self.close()

    def test_held_where_he_asked_for_less_motion_the_row_jumps(self):
        self.show(PHONE)
        f = self.moving(False)
        self.press_picture(1)
        self.browser.eval('(()=>{const pager=document.querySelector("#reader-body .pager");window.__how=[];const real=pager.scrollTo.bind(pager);pager.scrollTo=o=>{window.__how.push(o.behavior);return real(o);};return "ok";})()')
        self.hand(f, 60, 420, 180)
        time.sleep(0.1)
        now = self.row()
        self.assertEqual((now['says'], now['off'], now['held']), ('3 מתוך 6', 0, False), now)
        self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
        time.sleep(0.15)
        self.assertEqual(self.row()['says'], '4 מתוך 6')
        self.assertEqual(set(self.browser.eval('JSON.stringify(window.__how)')), {'auto'})

    def test_held_a_slow_phone_still_arrives(self):
        self.show(PHONE)
        f = self.moving()
        self.press_picture(0)
        f.call('Emulation.setCPUThrottlingRate', {'rate': 20})
        try:
            self.hand(f, 60, 420, 180)
            now = self.rest(12)
            self.assertEqual((now['says'], now['off']), ('2 מתוך 6', 0), now)
            self.browser.eval('(()=>{readerGallery.go(1);return "ok";})()')
            now = self.rest(12)
            self.assertEqual((now['says'], now['off']), ('3 מתוך 6', 0), now)
        finally:
            f.call('Emulation.setCPUThrottlingRate', {'rate': 1})

    def test_held_odd_pictures_open_whole_and_in_the_middle(self):
        for size in (TINY, PHONE, DESK):
            with self.subTest(size=size[0]):
                self.odd(size)
                for n, (name, w, h) in enumerate(self.ODD_SHOTS):
                    self.open_picture(n)
                    now = self.rest()
                    self.assertEqual((now['says'], now['title'], now['maxX'], now['fitted']), ('%d מתוך 5' % (n + 1), name, 0, 'true'), now)
                    box = now['paneBox']
                    self.assertAlmostEqual(now['imgLeft'] + now['wide'] / 2, box[0] + box[2] / 2, delta=1.5, msg='not in the middle of its page: %s' % now)
                    self.assertGreaterEqual(now['wide'], 1)
                    self.close()


class ShippedWithMotion(test_e2e_gallery.Gallery):
    """The four shipped scenarios of test_e2e_gallery.py, unchanged, in a browser that wants motion: the branch with
    smooth scrolling, the 420 ms timer and momentum, which this machine's browser never took."""

    def show(self, size):
        super().show(size)
        f = self.fingers()
        f.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'no-preference'}]})
        self.assertIs(self.browser.eval('JSON.stringify(matchMedia("(prefers-reduced-motion:reduce)").matches)'), False)


# Only this file's scenarios: the ones of test_e2e and of test_e2e_gallery run in their own files.
for _name in dir(test_e2e_gallery.Gallery):
    if _name.startswith('test') and _name not in AdvGallery.__dict__:
        setattr(AdvGallery, _name, None)
for _name in dir(test_e2e_gallery.test_e2e.Suda):
    if _name.startswith('test') and _name not in test_e2e_gallery.Gallery.__dict__:
        setattr(ShippedWithMotion, _name, None)


if __name__ == '__main__':
    unittest.main()
