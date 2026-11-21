#!/usr/bin/env python3
"""End to end: on a slow link pictures and videos wait for his press (the owner: "on a very slow link, diagrams may
still load, but heavy things like images do not load by default; a 'tap to load' button instead").

The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board), with a
server that writes down every download of a file under uploads/. The mode is forced by its setting (kept per device
in localStorage), or by the browser's own word (navigator.connection.saveData, stood in for on the page).

What is checked: with the mode on, opening a thread asks the server for none of its pictures, videos or video
frames; each shows its place with its size and a "לחץ לטעינה" button, and the bar over the conversation says why;
a press loads that one only; "טען הכל בשרשור" loads the rest; the gallery holds the page beside the one he opened;
the setting wins both ways ("always load" over Save-Data, "always tap" on a quick link, back to "auto"); and the
diagram of the same thread is drawn as always.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES, SLUG, png

FFMPEG = shutil.which('ffmpeg')
HOLDS = ('(()=>JSON.stringify([...document.querySelectorAll("#log .media-hold")].map(b=>{const r=b.getBoundingClientRect();'
         'return {src:b.dataset.src,text:b.textContent,label:b.getAttribute("aria-label")||b.closest("button").getAttribute("aria-label"),w:Math.round(r.width),h:Math.round(r.height)};})))()')
STATE = ('(()=>JSON.stringify({held:document.querySelectorAll("#log .media-hold").length,videos:document.querySelectorAll("#log video").length,'
         'shown:[...document.querySelectorAll("#log .shot img")].filter(i=>!i.hidden&&i.complete&&i.naturalWidth>0).length,'
         'bar:(()=>{const b=document.querySelector(".slow-bar");return b&&!b.hidden&&b.offsetParent?b.innerText:"";})(),'
         'diagram:!!document.querySelector("#log figure.diagram .diagram-pic"),'
         'asked:performance.getEntriesByType("resource").filter(e=>e.name.includes("/uploads/")).map(e=>e.name.split("/uploads/")[1])}))()')
DIAGRAM = '```mermaid\nflowchart LR\n  A[לפני] --> B[אחרי]\n```'


class SlowMode(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Counting(base):
            asked = []          # every download of a file under uploads/

            def do_GET(self):
                if '/uploads/' in self.path:
                    Counting.asked.append(self.path.split('?')[0])
                return super().do_GET()
        cls.counting = Counting
        cls.server.RequestHandlerClass = Counting
        cls.clip = None
        if FFMPEG:
            cls.clip = Path(cls.tmp.name) / 'slow.mp4'
            subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=1',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(cls.clip)], check=True, timeout=60)

    def setUp(self):
        del self.counting.asked[:]

    def media_thread(self, tid, title):
        """A thread with a diagram, two pictures and (where ffmpeg is) a video, in one message."""
        self.needs('images')
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        first, second = Path(self.tmp.name) / (tid + '-1.png'), Path(self.tmp.name) / (tid + '-2.png')
        first.write_bytes(png(320, 200, shade=30))
        second.write_bytes(png(200, 320, shade=90))
        args = ['say', tid, '--from', 'fork', '-', '--image', str(first), '--caption', 'הראשונה', '--image', str(second), '--caption', 'השנייה']
        if self.clip:
            args += ['--video', str(self.clip), '--caption', 'הסרטון']
        self.ok(*args, '--by', 'e2e', '--state', 'working', '--note', 'מדיה', input='תמונות, סרטון ודיאגרמה\n\n' + DIAGRAM)

    def setting(self, value):
        """His choice on this device, kept where the page keeps it; None: never chosen."""
        key = json.dumps(SLUG + ':slow-media')
        self.browser.eval('(()=>{%s;return "ok";})()' % ('localStorage.removeItem(%s)' % key if value is None else 'localStorage.setItem(%s,%s)' % (key, json.dumps(value))))

    def setting_first(self, value):
        """The setting, kept before the page is opened at all (a page on the desktop opens a thread by itself)."""
        self.browser.open(self.origin + '/' + SLUG + '/state.json')
        self.setting(value)

    def open_with(self, value, tid, title, size=SIZES[0]):
        self.setting_first(value)
        self.open_thread(size, tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .shot").length===2)' % json.dumps(tid),
                          timeout=30, what='the pictures of the message')

    def page_state(self):
        return self.browser.eval(STATE)

    def asked(self, tid):
        return sorted({p.split('/uploads/%s/' % tid)[1] for p in self.counting.asked if '/uploads/%s/' % tid in p})

    def shown(self, tid, n):
        """The file the conversation shows for picture n: its small copy where the server kept one (task 31)."""
        i = self.thread(tid)['messages'][0]['images'][n - 1]
        return (i.get('thumb') or i)['file'].rsplit('/', 1)[1]

    def expected_files(self, tid):
        return sorted([self.shown(tid, 1), self.shown(tid, 2)] + (['m1-v1.jpg', 'm1-v1.mp4'] if self.clip else []))

    def test_with_the_mode_forced_nothing_heavy_is_asked_for_until_he_presses(self):
        tid = 'e2e-slow-tap'
        self.media_thread(tid, 'קליטה איטית')
        for size in SIZES:
            with self.subTest(size=size[0]):
                del self.counting.asked[:]
                self.open_with('tap', tid, 'קליטה איטית', size)
                self.browser.wait('JSON.stringify(!!document.querySelector("#log figure.diagram .diagram-pic"))', timeout=40, what='the diagram, drawn as always')
                self.browser.eval('(async()=>{document.querySelector("#log .clips,#log .pics").scrollIntoView({block:"center"});await new Promise(r=>setTimeout(r,1200));return "ok";})()')
                st = self.page_state()
                self.assertEqual(self.asked(tid), [], 'a held file was asked for')
                self.assertEqual(st['asked'], [], st)
                self.assertEqual((st['held'], st['videos'], st['shown']), (3 if self.clip else 2, 0, 0), st)
                self.assertTrue(st['diagram'])
                self.assertIn('קליטה איטית: מדיה בלחיצה', st['bar'])
                self.assertIn('טען הכל בשרשור', st['bar'])
                holds = self.browser.eval(HOLDS)
                for hold in holds:
                    self.assertIn('לחץ לטעינה', hold['text'])
                    self.assertTrue(hold['label'].startswith('לחץ לטעינה: '), hold)
                    self.assertGreaterEqual(hold['w'], 100, hold)
                    self.assertGreaterEqual(hold['h'], 80, hold)
                    self.assertLessEqual(hold['w'], size[1], hold)
                self.assertIn('KB', holds[0]['text'])
                if self.clip:
                    self.assertTrue(holds[2]['text'].startswith('סרטון0:01 · '), holds[2])        # what it is, its length, its bytes
                # its press loads that one only, and the picture stands in its place
                self.browser.eval('(()=>{document.querySelector("#log .shot .shot-open").click();return "ok";})()')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img")[0].complete&&document.querySelectorAll("#log .shot img")[0].naturalWidth>0)', timeout=20, what='the picture he pressed')
                self.assertEqual(self.asked(tid), [self.shown(tid, 1)])
                self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#reader").hidden)'), 'the press that loads also opened the viewer')
                st = self.page_state()
                self.assertEqual((st['held'], st['shown']), (2 if self.clip else 1, 1), st)
                # "load all" loads the rest of the thread, the video included, and the bar goes away
                self.browser.eval('(()=>{[...document.querySelectorAll(".slow-bar button")].find(b=>b.textContent==="טען הכל בשרשור").click();return "ok";})()')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img")[1].complete&&document.querySelectorAll("#log .shot img")[1].naturalWidth>0)', timeout=20, what='the other picture')
                if self.clip:
                    self.browser.wait('JSON.stringify(!!document.querySelector("#log video")&&document.querySelector("#log video").readyState>=1)', timeout=30, what='the video')
                st = self.page_state()
                self.assertEqual((st['held'], st['shown'], st['bar']), (0, 2, ''), st)
                self.assertEqual(self.asked(tid), self.expected_files(tid))

    def test_the_gallery_holds_the_page_beside_the_one_he_opened(self):
        tid = 'e2e-slow-gallery'
        self.media_thread(tid, 'גלריה איטית')
        self.open_with('tap', tid, 'גלריה איטית', SIZES[2])
        self.browser.eval('(()=>{document.querySelector("#log .shot .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot img")[0].naturalWidth>0)', timeout=20, what='the picture he pressed')
        self.browser.eval('(()=>{document.querySelector("#log .shot .shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&document.querySelectorAll("#reader .pic-pane").length===2)', timeout=10, what='the gallery')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader .pic-pane .media-hold"))', timeout=10, what='the page beside it, held')
        self.browser.wait('JSON.stringify(document.querySelector("#reader .pic-pane img").naturalWidth>0)', timeout=20, what='the picture he opened')
        # his press loaded what the conversation shows; his tap that opened it, the picture itself
        self.assertEqual(self.asked(tid), sorted({self.shown(tid, 1), 'm1-1.png'}))
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#reader .pic-pane img").getAttribute("src"))'), 'uploads/%s/m1-1.png' % tid)
        self.browser.eval('(()=>{document.querySelector("#reader .pic-pane .media-hold").click();return "ok";})()')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#reader .pic-pane img")].every(i=>i.naturalWidth>0))', timeout=20, what='the other page, after his press')
        self.assertEqual(self.asked(tid), sorted({self.shown(tid, 1), 'm1-1.png', 'm1-2.png'}), 'a press in the viewer loads the picture itself')

    def test_the_setting_wins_both_ways(self):
        tid = 'e2e-slow-setting'
        self.media_thread(tid, 'הגדרת מדיה')
        fake = ('(()=>{Object.defineProperty(navigator,"connection",{configurable:true,get:()=>({saveData:true,effectiveType:"4g",addEventListener(){}})});'
                'judgeLink();return JSON.stringify(slowState);})()')
        # "always load" beats the browser's Save-Data
        self.setting_first('load')
        self.open(SIZES[0])
        self.assertEqual(self.browser.eval(fake)['on'], False)
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#log .shot img")].filter(i=>i.naturalWidth>0).length===2)', timeout=20, what='the pictures, loaded')
        self.assertEqual(self.page_state()['held'], 0)
        # auto with Save-Data: held, and the settings say why
        del self.counting.asked[:]
        self.setting_first(None)
        self.open(SIZES[0])
        got = self.browser.eval(fake)
        self.assertEqual({k: got[k] for k in ('on', 'why', 'at')}, {'on': True, 'why': 'save-data', 'at': self.browser.eval('JSON.stringify(slowState.at)')})
        self.assertEqual(got['whys'], ['save-data'])
        tid2 = tid + '-2'
        self.media_thread(tid2, 'הגדרת מדיה שנייה')
        self.browser.wait('JSON.stringify(!!thread(%s))' % json.dumps(tid2), timeout=20, what='the second thread')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid2))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .media-hold").length>=2)', timeout=20, what='the held media')
        self.assertEqual(self.asked(tid2), [])
        # the first thread too, then back: its rows are kept in the page for the way back
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .media-hold").length>=2&&document.body.innerText.includes("הגדרת מדיה"))', timeout=20, what='the first thread, held')
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid2))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .media-hold").length>=2&&thread(%s)&&view.ch===%s)' % (json.dumps(tid2), json.dumps(tid2)), timeout=20, what='the second thread again')
        self.browser.eval('(()=>{openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .slow-state"))', timeout=10, what='the setting')
        said = self.browser.eval('JSON.stringify(document.querySelector("#notify-body .slow-state").textContent)')
        self.assertIn('קליטה איטית: מדיה בלחיצה', said)
        self.assertIn('חיסכון בנתונים', said)
        pressed = self.browser.eval('JSON.stringify([...document.querySelectorAll("#notify-body .slow-state + .chips button")].map(b=>[b.textContent,b.getAttribute("aria-pressed")]))')
        self.assertEqual(pressed, [['אוטומטי', 'true'], ['תמיד לטעון', 'false'], ['תמיד בלחיצה', 'false']])
        # "always load", pressed in the settings: everything held comes, and stays so for this device
        self.browser.eval('(()=>{[...document.querySelectorAll("#notify-body .chips button")].find(b=>b.textContent==="תמיד לטעון").click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .media-hold").length===0&&[...document.querySelectorAll("#log .shot img")].filter(i=>i.naturalWidth>0).length===2)',
                          timeout=20, what='the media, loaded by the setting')
        self.assertEqual(self.browser.eval('JSON.stringify(localStorage.getItem(%s))' % json.dumps(SLUG + ':slow-media')), 'load')
        self.assertIn('נטענים כרגיל', self.browser.eval('JSON.stringify(document.querySelector("#notify-body .slow-state").textContent)'))
        # the thread he was in before, whose rows the page kept, is not held either
        self.browser.eval('(()=>{closeNotify();openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify(view.ch===%s&&document.querySelectorAll("#log .media-hold").length===0&&[...document.querySelectorAll("#log .shot img")].filter(i=>i.naturalWidth>0).length===2)' % json.dumps(tid),
                          timeout=20, what='the kept thread, loaded')
        # "always tap" on a quick link, from Cmd+K: what is drawn from now on waits again (what was shown stays)
        self.browser.eval('(()=>{Object.defineProperty(navigator,"connection",{configurable:true,get:()=>({effectiveType:"4g",addEventListener(){}})});'
                          'const c=actions().find(c=>c.id==="slow:tap");c.run();return "ok";})()')
        st = self.page_state()
        self.assertEqual(st['held'], 0, 'a picture already shown was taken away')
        self.assertEqual(self.browser.eval('JSON.stringify(slowState.on)'), True)
        self.assertTrue(self.browser.eval('JSON.stringify(actions().some(c=>c.id==="slow:auto")&&actions().some(c=>c.id==="slow:load")&&!actions().some(c=>c.id==="slow:tap"))'))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in SlowMode.__dict__:
        setattr(SlowMode, _name, None)


if __name__ == '__main__':
    unittest.main()
