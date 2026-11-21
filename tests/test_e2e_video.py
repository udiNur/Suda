#!/usr/bin/env python3
"""End to end: a video an agent attached plays inside the thread (the owner).

The same harness as test_e2e.py: headless Chrome, the real board server (answer_server.py) on loopback, a temporary
board. The videos are made here by ffmpeg (1 second, a few KB, inside the test's temporary folder); without ffmpeg
the file skips.

What is checked: `threads say --video` puts a <video> in the message with this thread's own file as its source,
the browser's controls, preload of the start only, inline on a phone and never playing by itself; the start loads
(readyState >= 1: its length and size are known) at the phone's two sizes and the desktop's; the box fits the
screen and keeps the video's shape; the caption is under it. The board server gives the whole file to a request for
a part of it (it does not answer ranges): playing works all the same. A video he watches keeps playing when its
message is drawn again.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import shutil
import subprocess
import time
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES, SLUG

FFMPEG = shutil.which('ffmpeg')
CLIPS = ('(()=>JSON.stringify([...document.querySelectorAll("#log video")].map(v=>{const r=v.getBoundingClientRect(),f=v.closest("figure.clip"),c=f&&f.querySelector("figcaption");'
         'return {src:v.getAttribute("src"),controls:v.controls,preload:v.preload,inline:v.hasAttribute("playsinline"),autoplay:v.autoplay,paused:v.paused,muted:v.muted,'
         'ready:v.readyState,error:v.error&&v.error.code,vw:v.videoWidth,vh:v.videoHeight,duration:v.duration,left:Math.round(r.left),right:Math.round(r.right),w:Math.round(r.width),h:Math.round(r.height),'
         'dir:getComputedStyle(v.parentElement).direction,caption:c?c.textContent:"",poster:v.getAttribute("poster")};})))()')


class Video(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest('ffmpeg is not installed')
        super().setUpClass()
        cls.files = Path(cls.tmp.name) / 'videos'
        cls.files.mkdir()
        cls.mp4, cls.webm = cls.files / 'demo.mp4', cls.files / 'demo.webm'
        source = ['-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=1']
        for out, codec in ((cls.mp4, ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p']), (cls.webm, ['-c:v', 'libvpx', '-b:v', '60k'])):
            subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-y', *source, *codec, str(out)], check=True, timeout=60)

    def attach(self, tid, title):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', tid, '--from', 'fork', 'ככה זה נראה עכשיו', '--video', str(self.mp4), '--caption', 'ההדגמה בדסקטופ', '--video', str(self.webm),
                '--by', 'e2e', '--state', 'working', '--note', 'סרטונים')

    def clips(self):
        return self.browser.eval(CLIPS)

    def test_a_video_shows_in_its_message_and_its_start_loads_at_every_size(self):
        tid = 'e2e-video'
        self.attach(tid, 'סרטון בשרשור')
        stored = self.thread(tid)['messages'][0]['videos']
        self.assertEqual([v['file'] for v in stored], ['uploads/%s/m1-v1.mp4' % tid, 'uploads/%s/m1-v2.webm' % tid])
        for size in SIZES:
            name, width, height = size
            with self.subTest(size=name):
                self.browser.open('about:blank')
                self.open_thread(size, tid, 'סרטון בשרשור')
                self.browser.wait('JSON.stringify(document.querySelectorAll("#log video").length===2)', timeout=30, what='the two videos')
                self.browser.eval('(()=>{document.querySelectorAll("#log video")[1].scrollIntoView({block:"center"});return "ok";})()')
                self.browser.wait('JSON.stringify([...document.querySelectorAll("#log video")].every(v=>v.readyState>=1||v.error))', timeout=30, what='the start of both videos')
                clips = self.clips()
                for clip, file in zip(clips, ('uploads/%s/m1-v1.mp4' % tid, 'uploads/%s/m1-v2.webm' % tid)):
                    self.assertEqual(clip['src'], file)
                    self.assertIsNone(clip['error'], clip)
                    self.assertGreaterEqual(clip['ready'], 1, clip)
                    self.assertEqual((clip['vw'], clip['vh']), (320, 180), clip)
                    self.assertAlmostEqual(clip['duration'], 1.0, delta=0.2)
                    self.assertEqual((clip['controls'], clip['preload'], clip['inline'], clip['autoplay'], clip['paused']), (True, 'metadata', True, False, True), clip)
                    self.assertEqual(clip['dir'], 'ltr')
                    # it fits the screen, wide as the video is (16:9 within a pixel)
                    self.assertTrue(0 <= clip['left'] and clip['right'] <= width, (name, clip))
                    self.assertGreaterEqual(clip['w'], min(280, width - 80), (name, clip))
                    self.assertAlmostEqual(clip['w'] / clip['h'], 16 / 9, delta=0.03)
                    self.assertLessEqual(clip['h'], height * 0.7 + 1)
                self.assertEqual([c['caption'] for c in clips], ['ההדגמה בדסקטופ', ''])
                self.assertEqual(clips[0]['poster'], 'uploads/%s/m1-v1.jpg' % tid)          # ffmpeg is here: its first frame stands until it plays
                time.sleep(1)
                self.assertTrue(all(c['paused'] and not c['muted'] for c in self.clips()), 'a video played by itself')

    def test_the_board_server_gives_the_whole_video_to_a_request_for_a_part_and_it_plays(self):
        """answer_server.py is SimpleHTTPRequestHandler: no Accept-Ranges, a Range header is ignored (200 and the whole
        file). The page needs only the start of an mp4 because the CLI stores its index first; playing through works."""
        tid = 'e2e-video-range'
        self.attach(tid, 'סרטון וטווח')
        for file, kind in (('m1-v1.mp4', 'video/mp4'), ('m1-v2.webm', 'video/webm')):
            c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
            c.request('GET', '/%s/uploads/%s/%s' % (SLUG, tid, file), headers={'Range': 'bytes=100-199'})
            r = c.getresponse()
            body = r.read()
            whole = (self.board / 'uploads' / tid / file).read_bytes()
            self.assertEqual(r.getheader('Content-Type'), kind)
            self.assertIn(r.status, (200, 206))
            if r.status == 206:
                self.assertEqual((r.getheader('Content-Range'), body), ('bytes 100-199/%d' % len(whole), whole[100:200]))
            else:
                self.assertEqual(body, whole)
        self.open_thread(SIZES[2], tid, 'סרטון וטווח')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log video").length===2&&document.querySelector("#log video").readyState>=1)', timeout=30, what='the video')
        ended = self.browser.eval('(async()=>{const v=document.querySelector("#log video");v.muted=true;await v.play();'
                                  'await new Promise((ok,no)=>{v.onended=ok;setTimeout(()=>no(Error("did not end")),8000);});return JSON.stringify({ended:v.ended,at:v.currentTime});})()')
        self.assertTrue(ended['ended'], ended)

    def test_a_video_he_watches_keeps_playing_when_its_message_is_drawn_again(self):
        tid = 'e2e-video-keep'
        self.attach(tid, 'סרטון שממשיך')
        self.open_thread(SIZES[0], tid, 'סרטון שממשיך')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log video").length===2&&document.querySelector("#log video").readyState>=1)', timeout=30, what='the video')
        self.browser.eval('(async()=>{const v=document.querySelector("#log video");v.__mark=7;v.loop=true;v.muted=true;await v.play();return "ok";})()')
        self.ok('react', tid, 'm1', '👍', '--by', 'e2e')                        # the message changes: its row is drawn again
        self.browser.wait('JSON.stringify(document.querySelector("#log .msg[data-mid=\\"m1\\"]").innerText.includes("👍"))', timeout=20, what='the mark on the message')
        time.sleep(0.5)
        kept = self.browser.eval('(()=>{const v=document.querySelector("#log video");return JSON.stringify({mark:v.__mark,paused:v.paused,at:v.currentTime});})()')
        self.assertEqual((kept['mark'], kept['paused']), (7, False), kept)
        # another video that starts pauses the one that played
        self.browser.eval('(async()=>{const v=document.querySelectorAll("#log video")[1];v.scrollIntoView();v.muted=true;await new Promise(r=>setTimeout(r,500));await v.play();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#log video").paused)', timeout=10, what='the first video paused')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Video.__dict__:
        setattr(Video, _name, None)


if __name__ == '__main__':
    unittest.main()
