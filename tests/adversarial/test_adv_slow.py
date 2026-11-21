#!/usr/bin/env python3
"""Hostile review of the slow link mode (suda.html): each test asserts the SAFE outcome, so a failure is a hole.

The harness is the one of test_e2e_slowmode.py (headless Chrome, the real board server on loopback, a temporary
board, a server that writes down every download under uploads/). The pure decision runs under node like test_slack.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest
from pathlib import Path

import test_e2e
import test_e2e_slowmode
from test_e2e import SIZES, SLUG, png
import test_slack

LIVE_PICS = '[...document.querySelectorAll("#log .shot img")].filter(i=>!i.hidden&&i.complete&&i.naturalWidth>0).length'


class SlowPure(unittest.TestCase):
    page, node, pure_js = test_slack.SlackPageTests.page, test_slack.SlackPageTests.node, test_slack.SlackPageTests.pure_js

    def test_one_big_slow_read_among_quick_ones_does_not_turn_the_mode_on(self):
        """The decision claims "the middle one" of the last reads, but the speed is the middle of only the BIG reads:
        one big read (a long thread's whole file read while the phone slept, a server busy for a moment) among
        quick small ones is the whole verdict, and pictures are held for at least a minute on a fast link."""
        self.pure_js(r"""
        const S=(bytes,ms)=>({bytes,ms}),off={on:false,why:'',at:0};
        const got=slowLink('auto',{effectiveType:'4g'},[S(3000,60),S(3000,70),S(3000,80),S(3000,60),S(900000,20000)],off,1000000);
        assert.strictEqual(got.on,false,JSON.stringify(got));
        """)

    def test_measured_fast_reads_turn_off_a_mode_that_type_3g_turned_on(self):
        """effectiveType '3g' comes from the browser's RTT estimate (a far server, a VPN relay): the page's own reads
        say the line is quick, yet 'type' wins over every measurement, forever. (The brief lists 3g on purpose; this
        records that nothing the page sees can overrule it.)"""
        self.pure_js(r"""
        const S=(bytes,ms)=>({bytes,ms}),off={on:false,why:'',at:0},quick=[S(300000,300),S(300000,250),S(300000,280)];
        const got=slowLink('auto',{effectiveType:'3g',downlink:20,rtt:300},quick,off,1000000);
        assert.strictEqual(got.on,false,JSON.stringify(got));
        """)

    def test_a_read_across_a_hidden_or_frozen_stretch_says_nothing_of_the_link(self):
        """A read that was on its way while the page was hidden (the phone locked) or frozen took as long as the
        sleep, not as long as the line: it is not a sample. `gaps` are the stretches the page was away, in the
        timing's own clock (an open one ends at Infinity)."""
        self.pure_js(r"""
        const e={name:'http://h/b/summary.json?t=1',transferSize:5000,startTime:100,requestStart:200,responseEnd:9000};
        assert.strictEqual(linkSample(e,[[500,4000]]),null);              // hidden in the middle of it
        assert.strictEqual(linkSample(e,[[8000,Infinity]]),null);         // hidden at its end, still away
        assert.strictEqual(linkSample(e,[[50,150]]),null);                // it started while the page was away
        assert.deepStrictEqual(linkSample(e,[[0,50],[9500,9800]]),{bytes:5000,ms:8800});   // away only before and after it
        assert.deepStrictEqual(linkSample(e,[]),{bytes:5000,ms:8800});assert.deepStrictEqual(linkSample(e),{bytes:5000,ms:8800});
        // the stretches the page was away, kept from its visibility and freeze events
        const g=[];awayStep(g,'hidden',10);awayStep(g,'visible',30);awayStep(g,'freeze',50);awayStep(g,'hidden',55);awayStep(g,'resume',70);awayStep(g,'visible',80);
        assert.deepStrictEqual(g,[[10,30],[50,80]]);
        const h=[];awayStep(h,'hidden',5);assert.deepStrictEqual(h,[[5,Infinity]]);awayStep(h,'visible',9);assert.deepStrictEqual(h,[[5,9]]);
        const many=[];for(let i=0;i<100;i++){awayStep(many,'hidden',i*10);awayStep(many,'visible',i*10+5);}assert.ok(many.length<=20);
        """)


class AdvSlow(test_e2e_slowmode.SlowMode):
    """Attacks on the slow link mode."""

    def question(self, tid, title, multi=False):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        args = ['ask', tid, 'איזה עיצוב?', '--options', 'אדום,כחול'] + (['--multi'] if multi else [])
        for i, label in enumerate(('אדום', 'כחול')):
            path = Path(self.tmp.name) / ('%s-%d.png' % (tid, i))
            path.write_bytes(png(240, 180, shade=40 * i))
            args += ['--option-image', '%s=%s' % (label, path)]
        self.ok(*args)

    def video_then_long_text(self, tid, title):
        """A video in m1, then a message so long that the video is far above the screen when the thread opens."""
        self.needs('images')
        if not self.clip:
            self.skipTest('no ffmpeg')
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', '-', '--video', str(self.clip), '--caption', 'הסרטון', '--by', 'e2e', '--state', 'working', '--note', 'מדיה',
                input='סרטון\n')
        for n in range(30):           # (one long message is folded into a snippet: many short ones are not)
            self.ok('say', tid, '--from', 'fork', '-', '--by', 'e2e', '--state', 'working', '--note', 'ארוך',
                    input='\n\n'.join('הודעה %d, שורה %d אחרי הסרטון' % (n, i) for i in range(6)) + '\n')

    def test_load_all_in_thread_also_loads_the_pinned_question_pictures(self):
        """'Load all in thread' looks only in #log; the pinned question (#pin, outside the log) keeps its option
        pictures held after he pressed it, and they are not counted in the bar either."""
        tid = 'e2e-adv-pin'
        self.question(tid, 'שאלה עם תמונות')
        self.setting_first('tap')
        self.open_thread(SIZES[2], tid, 'שאלה עם תמונות')
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&document.querySelectorAll(".media-hold").length>0)' % json.dumps(tid), timeout=30, what='held pictures')
        before = self.browser.eval('JSON.stringify({pin:document.querySelectorAll("#pin .media-hold").length,log:document.querySelectorAll("#log .media-hold").length})')
        if not before['pin']:
            self.skipTest('no pinned question with pictures here: %s' % before)
        self.browser.eval('(()=>{loadAllHere();return "ok";})()')
        time.sleep(1.5)
        after = self.browser.eval('JSON.stringify({pin:[...document.querySelectorAll("#pin .media-hold")].filter(b=>!b.done).length,log:document.querySelectorAll("#log .media-hold").length})')
        self.assertEqual(after, {'pin': 0, 'log': 0}, 'before: %s' % before)

    def test_load_all_in_thread_also_loads_the_pictures_of_the_answer_form(self):
        tid = 'e2e-adv-form'
        self.question(tid, 'טופס עם תמונות', multi=True)
        self.setting_first('tap')
        self.open_thread(SIZES[0], tid, 'טופס עם תמונות')
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&!!thread(%s).question)' % (json.dumps(tid), json.dumps(tid)), timeout=30, what='the question')
        self.browser.eval('(()=>{openAnswer();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#answer").hidden&&document.querySelectorAll("#answer .media-hold").length===2)', timeout=10, what='the form, its pictures held')
        self.assertEqual(self.asked(tid), [])
        self.assertTrue(self.browser.eval('JSON.stringify(heldHere().length>=2)'))
        self.browser.eval('(()=>{loadAllHere();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#answer .media-hold").length===0&&[...document.querySelectorAll("#answer .opt-pic img")].filter(i=>!i.hidden&&i.naturalWidth>0).length===2)',
                          timeout=20, what='the pictures of the form')

    def test_a_playing_video_keeps_playing_when_the_link_is_judged_slow(self):
        """When the mode turns (by itself, from measured reads: the video he plays is what slows the reads), the
        whole conversation is drawn again; the <video> is taken out of the page and put back, which pauses it."""
        tid = 'e2e-adv-play'
        self.needs('images')
        if not self.clip:
            self.skipTest('no ffmpeg')
        self.media_thread(tid, 'סרטון מתנגן')
        self.open_with('load', tid, 'סרטון מתנגן')
        self.setting(None)          # back to auto: the reads decide now
        self.browser.eval('(()=>{judgeLink();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log video")&&document.querySelector("#log video").readyState>=2)', timeout=30, what='the video')
        played = self.browser.eval('(async()=>{const v=document.querySelector("#log video");v.muted=true;v.loop=true;await v.play();'
                                   'await new Promise(r=>setTimeout(r,400));return JSON.stringify(!v.paused);})()')
        self.assertTrue(played, 'could not start the video')
        # the reads of the board turn slow (what the PerformanceObserver would push), and the link is judged again
        got = self.browser.eval('(async()=>{linkSamples.splice(0,linkSamples.length,{bytes:200000,ms:9000},{bytes:200000,ms:9000},{bytes:200000,ms:9000});'
                                'judgeLink();await new Promise(r=>setTimeout(r,600));const v=document.querySelector("#log video");'
                                'return JSON.stringify({on:slowState.on,why:slowState.why,paused:v?v.paused:null,inPage:!!v&&v.isConnected});})()')
        self.assertTrue(got['on'], got)
        self.assertEqual((got['inPage'], got['paused']), (True, False), got)

    def test_a_video_drawn_before_the_mode_turned_on_and_never_asked_for_waits(self):
        """A video drawn while the link was quick but still above the screen has no src yet (it is asked for when it
        comes near the screen). The mode turns on; clipNode does not hold a video already in clipEls, so when he
        scrolls up the whole file is asked for on the slow link."""
        tid = 'e2e-adv-offscreen'
        self.video_then_long_text(tid, 'סרטון למעלה')
        self.setting_first('load')
        # read to its end before: the page opens at the bottom, far below the video (not at the first unread, its top)
        self.browser.eval('(()=>{localStorage.setItem(%s,"99999999999999");return "ok";})()' % json.dumps(SLUG + ':seen:' + tid))
        self.open_thread(SIZES[0], tid, 'סרטון למעלה')
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&!!document.querySelector("#log video"))' % json.dumps(tid), timeout=30, what='the video element')
        time.sleep(1)
        src = self.browser.eval('JSON.stringify(document.querySelector("#log video").getAttribute("src"))')
        self.assertIsNone(src, 'the page did not open far below the video')
        self.assertIsNone(self.browser.eval('JSON.stringify(document.querySelector("#log video").getAttribute("poster"))'), 'its poster was asked for far from the screen')
        del self.counting.asked[:]
        self.browser.eval('(()=>{setSlowChoice("tap");return "ok";})()')
        self.browser.eval('(async()=>{const at=document.querySelector("#log .clip");at.scrollIntoView({block:"center"});await new Promise(r=>setTimeout(r,1500));return "ok";})()')
        self.assertEqual(self.asked(tid), [], 'the video or its poster was downloaded on "always tap" without his press')
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector("#log .clip .media-hold"))'), 'the video is not held')

    def test_load_all_from_the_keyboard_leaves_the_keys_somewhere(self):
        """The bar's "load all" is pressed with the keyboard: the bar then hides with the keys in it, so they are
        nowhere (document.body), not back in the reply box (keysToBox's rules)."""
        tid = 'e2e-adv-keys'
        self.media_thread(tid, 'מקלדת איטית')
        self.open_with('tap', tid, 'מקלדת איטית', SIZES[2])
        self.browser.eval('(()=>{const b=[...document.querySelectorAll(".slow-bar button")].find(b=>b.textContent==="טען הכל בשרשור");b.focus();return "ok";})()')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .media-hold").length===0)', timeout=20, what='everything loaded')
        time.sleep(0.6)
        at = self.browser.eval('JSON.stringify((()=>{const a=document.activeElement;return a===document.body||!a?"body":(a.id||a.className||a.tagName)+(a.closest("[hidden]")?" (hidden)":"");})())')
        self.assertNotEqual(at, 'body')
        self.assertNotIn('(hidden)', at)

    def test_a_held_page_of_the_gallery_loaded_with_enter_keeps_the_keys_in_the_viewer(self):
        """In the gallery the held page is a button; Enter on it removes it (box.remove()) with the keys in it."""
        tid = 'e2e-adv-galkeys'
        self.media_thread(tid, 'גלריה במקלדת')
        self.open_with('tap', tid, 'גלריה במקלדת', SIZES[2])
        self.browser.eval('(()=>{document.querySelector("#log .shot .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img")[0].naturalWidth>0)', timeout=20, what='the first picture')
        self.browser.eval('(()=>{document.querySelector("#log .shot .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader .pic-pane .media-hold"))', timeout=10, what='the held page')
        self.browser.eval('(()=>{document.querySelector("#reader .pic-pane .media-hold").focus();return "ok";})()')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader .pic-pane .media-hold"))', timeout=10, what='the page loaded')
        time.sleep(0.3)
        inside = self.browser.eval('JSON.stringify(!!document.activeElement&&document.activeElement!==document.body&&!!document.activeElement.closest("#reader"))')
        self.assertTrue(inside, 'the keys left the viewer')

    def test_the_picture_he_just_sent_does_not_turn_into_a_placeholder(self):
        """His own picture is shown from this browser (a blob:) while it is on its way; once the server holds the
        message, its address is uploads/... which mediaSeen never saw (the blob was what loaded), so on a slow link
        the picture he has just sent turns into "לחץ לטעינה" in front of him."""
        self.needs('images')
        tid = 'e2e-adv-own'
        self.ok('new', tid, 'התמונה שלי', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        shot = Path(self.tmp.name) / 'own.png'
        shot.write_bytes(png(200, 120, shade=60))
        self.setting_first('tap')
        self.open_thread(SIZES[2], tid, 'התמונה שלי')
        self.browser.upload('#pic-file', shot)
        self.browser.wait('JSON.stringify(document.querySelectorAll(".tray-caption").length===1)', what='the picture in the tray')
        self.browser.fill('#input', 'התמונה ששלחתי')
        self.browser.click('#send')
        self.until(lambda: any(m.get('images') for m in self.thread(tid)['messages']), timeout=30, what='the stored picture')
        self.browser.wait('JSON.stringify(synced&&thread(%s).messages.some(m=>Array.isArray(m.images)&&m.images.some(i=>i.file))&&!localOf(thread(%s)).length)' % (json.dumps(tid), json.dumps(tid)),
                          timeout=30, what='the page holding the server copy')
        time.sleep(1)
        got = self.browser.eval('JSON.stringify({held:document.querySelectorAll("#log .msg.own .media-hold").length,shown:[...document.querySelectorAll("#log .msg.own .shot img")].filter(i=>!i.hidden).length})')
        self.assertEqual(got['held'], 0, got)

    def test_held_media_in_the_conversation_are_no_extra_tab_stops_and_the_bar_says_its_state_apart(self):
        tid = 'e2e-adv-tab'
        self.media_thread(tid, 'טאב איטי')
        self.open_with('tap', tid, 'טאב איטי', SIZES[2])
        got = self.browser.eval('JSON.stringify({tabbable:[...document.querySelectorAll("#log .media-hold")].filter(b=>b.tabIndex>=0).length,'
                                'shots:[...document.querySelectorAll("#log .shot-open")].map(b=>b.tabIndex),'
                                'bar:document.querySelector(".slow-bar").getAttribute("role"),live:[...document.querySelectorAll(".slow-bar [role=status],.slow-bar [aria-live]")].map(n=>n.tagName+":"+n.textContent)})')
        self.assertEqual(got['tabbable'], 0, got)
        self.assertEqual(set(got['shots']), {-1}, got)
        self.assertIsNone(got['bar'], got)
        self.assertEqual(len(got['live']), 1, got)
        self.assertNotIn('BUTTON', got['live'][0])

    def test_strange_stored_sides_and_names_neither_break_the_layout_nor_inject(self):
        """Sides from the stored message (huge, zero, negative, strings, Infinity from 1e400) and a name with markup."""
        tid = 'e2e-adv-layout'
        self.media_thread(tid, 'מידות מוזרות')
        self.open_with('tap', tid, 'מידות מוזרות', SIZES[0])
        got = self.browser.eval(r'''(()=>{const out=[],host=document.querySelector("#log .pics")||document.querySelector("#log");
          const cases=[{w:1e9,h:1},{w:1,h:1e9},{w:0,h:0},{w:-5,h:-7},{w:"abc",h:"x"},{w:Infinity,h:1},{w:NaN,h:NaN},{w:"300",h:"200",bytes:1e400}];
          for(const [i,f] of cases.entries()){
            const b=holdMedia("uploads/e2e-adv-layout/m9-"+(i+1)+".png",{...f,name:'<img src=x onerror="window.pwned=1">'},()=>{});
            if(!b){out.push("not held");continue;}
            host.append(b);const r=b.getBoundingClientRect();out.push({w:Math.round(r.width),h:Math.round(r.height),imgs:b.querySelectorAll("img").length});b.remove();}
          return JSON.stringify({out,pwned:!!window.pwned,vw:innerWidth,vh:innerHeight});})()''')
        self.assertFalse(got['pwned'])
        for one in got['out']:
            self.assertIsInstance(one, dict, got)
            self.assertEqual(one['imgs'], 0, got)
            self.assertLessEqual(one['w'], got['vw'], got)
            self.assertGreaterEqual(one['w'], 60, got)
            self.assertLessEqual(one['h'], got['vh'], got)
            self.assertGreaterEqual(one['h'], 60, got)


# Only the scenarios of this file: those of test_e2e.Suda and of SlowMode run in their own files.
for _base in (test_e2e.Suda, test_e2e_slowmode.SlowMode):
    for _name in list(vars(_base)):
        if _name.startswith('test') and _name not in AdvSlow.__dict__:
            setattr(AdvSlow, _name, None)
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvSlow.__dict__:
        setattr(AdvSlow, _name, None)


def load_tests(loader, tests, pattern):
    """Only the classes of this file (the harness classes it borrows run in their own files)."""
    suite = unittest.TestSuite()
    for case in (SlowPure, AdvSlow):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__ == '__main__':
    unittest.main()
