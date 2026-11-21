#!/usr/bin/env python3
"""End to end: while he records, the wave of his voice is built beside the meter (the owner, thread suda m377).

"Like WhatsApp: beside the meter of the level, the history of the wave of the voice, to see the sound waves being
built in real time." The same harness as test_e2e.py (headless Chrome with a stand-in microphone that beeps, the
real board server on loopback, a temporary board). What is checked:

  - during a recording a row of bars is drawn beside the meter, it grows from the edge where the writing goes on
    (the left, in Hebrew), and the bar of the recording still fits the phone's narrow screen with its clock, its
    meter and its hint;
  - however long he records a fixed number of bars is kept, one drawing loop runs, and when the recording ends
    the loop stops and the picture is wiped.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

LOOK = ('(()=>{const c=document.querySelector("#rec-wave"),bar=document.querySelector("#rec"),box=c?c.getBoundingClientRect():null;'
        'if(!c||!box||!c.width||!c.height)return JSON.stringify({canvas:false});'
        'const data=c.getContext("2d").getImageData(0,0,c.width,c.height).data,inkAt=(from,to)=>{let n=0;'
        'for(let x=Math.floor(from*c.width);x<Math.floor(to*c.width);x++)for(let y=0;y<c.height;y++)if(data[(y*c.width+x)*4+3]>0)n++;return n;};'
        'const seen=id=>{const el=document.querySelector(id),b=el.getBoundingClientRect();return Math.round(b.width);};'
        'return JSON.stringify({canvas:true,shown:!!c.offsetParent,w:Math.round(box.width),h:Math.round(box.height),back:[c.width,c.height],dpr:devicePixelRatio,'
        'bars:rec&&rec.wave?rec.wave.bars.length:-1,ink:inkAt(0,1),left:inkAt(0,0.15),right:inkAt(0.8,1),fits:bar.scrollWidth<=bar.clientWidth+1,'
        'time:seen("#rec-time"),meter:seen(".rec-level"),hint:seen("#rec-hint"),cut:document.querySelector("#rec-hint").scrollWidth-document.querySelector("#rec-hint").clientWidth,'
        'dir:getComputedStyle(c).direction});})()')


class Wave(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    RECORDING = 'JSON.stringify(!document.querySelector("#rec").hidden)'

    def voices(self, tid):
        return [m for m in self.thread(tid)['messages'] if m.get('voice')]

    def thread_with_mic(self, size, tid, title):
        self.needs('voice')
        if tid not in self.state()['threads']:
            self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(size, tid, title)
        if not self.browser.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.skipTest('this browser has no microphone API on a loopback page')
        self.browser.wait('JSON.stringify(!!document.querySelector("#mic").offsetParent)', what='the record button')

    def test_while_he_records_bars_are_built_beside_the_meter_and_the_bar_still_fits(self):
        tid, title = 'e2e-wave', 'גל קול בזמן הקלטה'
        for size in (SIZES[0], SIZES[1]):               # the phone's narrow screen, and the wide one of the Fold
            with self.subTest(size=size[0]):
                self.thread_with_mic(size, tid, title)
                self.browser.pointer('#mic', 'pointerdown')
                self.browser.wait(self.RECORDING, timeout=10, what='the recording to start')
                self.browser.wait('JSON.stringify(!!rec&&!!rec.wave&&rec.wave.bars.length>=6)', timeout=10, what='the first bars')
                early = self.browser.eval(LOOK)
                self.assertTrue(early['canvas'] and early['shown'], early)
                self.assertGreaterEqual(early['w'], 48, early)
                self.assertGreaterEqual(early['h'], 20, early)
                self.assertLessEqual(early['back'][0], early['w'] * 2 + 2, early)       # sharp on a dense screen, and no larger than that needs
                self.assertGreater(early['ink'], 0, early)
                self.assertEqual(early['dir'], 'rtl')
                self.assertGreater(early['left'], 0, 'nothing is drawn at the edge where the newest bar stands: %s' % early)
                if early['w'] >= 200:                   # room for more than the few bars of the first moment: the far side is still empty
                    self.assertEqual(early['right'], 0, 'the bars do not grow from the edge of the newest one: %s' % early)
                # the bar of the recording still holds its clock, its meter and its hint, and nothing sticks out of it
                self.assertTrue(early['fits'], early)
                self.assertGreaterEqual(early['time'], 30, early)
                self.assertGreaterEqual(early['meter'], 20, early)
                self.assertGreaterEqual(early['hint'], 40, early)
                self.assertLessEqual(early['cut'], 0, 'the hint that says how to throw the recording away is cut: %s' % early)
                time.sleep(1.5)
                later = self.browser.eval(LOOK)
                self.assertGreater(later['bars'], early['bars'], (early, later))
                self.assertGreaterEqual(later['ink'], early['ink'], (early, later))
                self.browser.pointer('#mic', 'pointerup')           # held past a tap: release = send
                self.until(lambda: len(self.voices(tid)) >= (1 if size is SIZES[0] else 2), timeout=30, what='the voice message in state.json')
                self.assertFalse(self.browser.eval(self.RECORDING), 'the recording bar is still up after the release')

    def test_a_long_recording_keeps_a_fixed_number_of_bars_and_the_loop_ends_with_it(self):
        tid, title = 'e2e-wave-long', 'הקלטה ארוכה'
        self.thread_with_mic(SIZES[0], tid, title)
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait(self.RECORDING, timeout=10, what='the recording to start')
        self.browser.eval('(()=>{lockRec();return "ok";})()')
        self.browser.pointer('#mic', 'pointerup')
        self.browser.wait('JSON.stringify(!!rec&&rec.locked&&!!rec.wave&&rec.wave.bars.length>=3)', timeout=10, what='a locked recording with its first bars')
        # as if he had been recording for minutes: the history is full
        self.browser.eval('(()=>{rec.wave.bars=Array.from({length:WAVE_MAX},()=>0.5);window.DRAWN=0;const f=window.waveRects;window.waveRects=function(){DRAWN++;return f.apply(this,arguments);};return "ok";})()')
        time.sleep(2)
        seen = self.browser.eval('JSON.stringify({bars:rec.wave.bars.length,max:WAVE_MAX,drawn:DRAWN})')
        self.assertEqual(seen['bars'], seen['max'], seen)
        # one drawing for a frame of the screen, not more (a browser that is not in front draws fewer frames, down to one a second)
        self.assertTrue(1 <= seen['drawn'] <= 150, 'two seconds of one drawing loop: %s' % seen)
        look = self.browser.eval(LOOK)
        self.assertTrue(look['fits'] and look['ink'] > 0, look)
        # he throws the recording away: the loop stops and the picture is wiped
        self.browser.click('#rec-cancel')
        self.browser.wait('JSON.stringify(document.querySelector("#rec").hidden&&!rec)', timeout=10, what='the recording gone')
        after = self.browser.eval('JSON.stringify(DRAWN)')
        time.sleep(1)
        self.assertEqual(self.browser.eval('JSON.stringify(DRAWN)'), after, 'the drawing went on after the recording ended')
        wiped = self.browser.eval('(()=>{const c=document.querySelector("#rec-wave"),d=c.width&&c.height?c.getContext("2d").getImageData(0,0,c.width,c.height).data:[];let n=0;'
                                  'for(let i=3;i<d.length;i+=4)if(d[i]>0)n++;return JSON.stringify(n);})()')
        self.assertEqual(wiped, 0, 'the last recording is still drawn')
        self.assertEqual(self.voices(tid), [])


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Wave.__dict__:
        setattr(Wave, _name, None)


if __name__ == '__main__':
    unittest.main()
