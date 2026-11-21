#!/usr/bin/env python3
"""Hostile review of the live waveform (d1ca356..667e0be), end to end.

The harness of test_e2e.py: headless Chrome with a stand-in microphone, the real board server on 127.0.0.1 over a
temporary board. Every test states the CORRECT behaviour, so a FAIL is a hole. The page is never changed: a test
only watches it (it counts the frames the drawing loop asks for, the times the canvas is resized) or stands in
for the browser (a canvas with no 2D context, no AudioContext, a denser screen, the dark theme).

The frames of this headless browser come at any pace (about one a second on a loaded machine), so nothing here
counts on time: a test waits for frames, or drives the loop's own callback by hand.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import re
import time
import unittest

import test_e2e

# What the page is watched with. The drawing loop is known by what it reads (the analyser's samples).
ARM = r"""(()=>{
  if(window.ADV)return 'armed';
  const realRAF=window.requestAnimationFrame.bind(window),realCAF=window.cancelAnimationFrame.bind(window),realNow=performance.now.bind(performance);
  const A=window.ADV={pending:new Set(),most:0,draws:0,raf:0,levels:0,errs:[],sets:0,shifts:[],last:null,manual:false,cb:null,clock:null};
  const isDraw=cb=>String(cb).includes('getByteTimeDomainData');
  window.requestAnimationFrame=cb=>{
    if(!isDraw(cb))return realRAF(cb);
    if(A.manual){A.cb=cb;A.pending.add('hand');A.most=Math.max(A.most,A.pending.size);return 987654321;}
    const id=realRAF(t=>{A.pending.delete(id);A.draws++;cb(t);});
    A.pending.add(id);A.most=Math.max(A.most,A.pending.size);return id;
  };
  window.cancelAnimationFrame=id=>{if(id===987654321){A.cb=null;A.pending.delete('hand');return;}A.pending.delete(id);return realCAF(id);};
  performance.now=()=>A.clock!=null?A.clock:realNow();
  // one frame of the loop, by hand, at a time of the test's choosing
  A.step=at=>{const cb=A.cb;if(!cb)return false;A.cb=null;A.pending.delete('hand');A.clock=at;try{A.draws++;cb(at);}catch(e){A.errs.push(String(e&&e.message||e));}finally{A.clock=null;}return true;};
  const tick=()=>{A.raf++;realRAF(tick);};realRAF(tick);
  const level=window.waveLevel;window.waveLevel=function(){A.levels++;return level.apply(this,arguments);};
  const rects=window.waveRects;window.waveRects=function(bars,live,shift,w,h,rtl){A.shifts.push(shift);if(A.shifts.length>600)A.shifts.shift();A.last={n:bars.length,live,shift,w,h,rtl};return rects.apply(this,arguments);};
  addEventListener('error',e=>A.errs.push(String(e.message)));
  const c=document.querySelector('#rec-wave'),d=Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype,'width');
  Object.defineProperty(c,'width',{get(){return d.get.call(this);},set(v){A.sets++;d.set.call(this,v);},configurable:true});
  return 'ok';
})()"""
SEE = ('JSON.stringify({rec:!!rec,done:!!(rec&&rec.done),locked:!!(rec&&rec.locked),pending:ADV.pending.size,most:ADV.most,draws:ADV.draws,raf:ADV.raf,'
       'levels:ADV.levels,errs:ADV.errs,sets:ADV.sets,bars:rec&&rec.wave?rec.wave.bars.length:-1,hidden:document.querySelector("#rec").hidden,'
       'clock:document.querySelector("#rec-time").textContent,meter:document.querySelector("#rec-level").style.transform,last:ADV.last})')
# The picture: its backing store, its place on the page, how much ink stands in every column of the backing store
# (in rows: the sum of the alpha), and the colour of its most solid pixel.
PICTURE = r"""(()=>{const c=document.querySelector('#rec-wave'),w=c.width,h=c.height,box=c.getBoundingClientRect(),look=getComputedStyle(c);
  const out={w,h,cli:[c.clientWidth,c.clientHeight],box:[Math.round(box.width*100)/100,Math.round(box.height*100)/100],dpr:devicePixelRatio,ink:0,cols:[],best:[0,0,0,0],color:look.color,dir:look.direction};
  const pen=w&&h?c.getContext('2d'):null;
  if(!pen)return JSON.stringify(out);
  const d=pen.getImageData(0,0,w,h).data;
  for(let x=0;x<w;x++){let sum=0;for(let y=0;y<h;y++){const i=(y*w+x)*4,a=d[i+3];if(a){sum+=a;out.ink++;if(a>out.best[3])out.best=[d[i],d[i+1],d[i+2],a];}}out.cols.push(Math.round(sum/255*100)/100);}
  return JSON.stringify(out);})()"""
# The boxes of the bar: [left, right, width] of everything in it that is shown, the mic beside it, and how much of the hint is cut.
BOXES = r"""(()=>{const q=s=>document.querySelector(s),r=el=>{const b=el.getBoundingClientRect();if(!b.width&&!b.height)return null;return [Math.round(b.left*10)/10,Math.round(b.right*10)/10,Math.round(b.width*10)/10,Math.round(b.top*10)/10,Math.round(b.bottom*10)/10];};
  const hint=q('#rec-hint'),bar=q('#rec'),range=document.createRange();range.selectNodeContents(hint);
  const on=s=>{const el=q(s),b=el.getBoundingClientRect();if(!b.width)return false;const at=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);return !!at&&(at===el||el.contains(at));};
  return JSON.stringify({vw:innerWidth,bar:r(bar),cancel:r(q('#rec-cancel')),dot:r(q('.rec-dot')),time:r(q('#rec-time')),level:r(q('.rec-level')),wave:r(q('#rec-wave')),hint:r(hint),send:r(q('#rec-send')),mic:r(q('#mic')),
    hintText:hint.textContent,hintNeeds:Math.round(range.getBoundingClientRect().width*10)/10,hintCut:hint.scrollWidth-hint.clientWidth,barOver:bar.scrollWidth-bar.clientWidth,
    clock:q('#rec-time').textContent,cancelOn:on('#rec-cancel'),sendOn:on('#rec-send')});})()"""
# The layout as it was before the change (the three rules of d1ca356, and no canvas), to compare with.
OLD = ('(()=>{let s=document.querySelector("#adv-old");if(!s){s=document.createElement("style");s.id="adv-old";document.head.appendChild(s);}'
       's.textContent=%s?".rec-level{flex:1 1 40px!important;min-width:24px!important;max-width:180px!important}.rec-wave{display:none!important}.rec-hint{flex:2 1 0!important}":"";return "ok";})()')
COVER, INNER, DESKTOP = ('cover', 360, 840), ('inner', 750, 835), ('desktop', 1280, 800)
SMALL = ('small', 320, 700)


class AdvWave(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    RECORDING = 'JSON.stringify(!document.querySelector("#rec").hidden)'
    A, B = ('adv-wave-a', 'גל קול: ביקורת עוינת'), ('adv-wave-b', 'נושא שני לביקורת')

    # ── tools ────────────────────────────────────────────────────────────────

    def voices(self, tid):
        return [m for m in self.thread(tid)['messages'] if m.get('voice')]

    def fresh(self, size, scale=None, media=('light',), thread=None):
        """A newly loaded page on the thread, at this size (and density), with the watch armed."""
        self.needs('voice')
        b = self.browser
        for tid, title in (self.A, self.B):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        b.run('set', 'media', *media)
        tid, title = thread or self.A
        name, w, h = size
        if scale is not None:
            b.run('set', 'viewport', str(w), str(h), str(scale))
            self.addCleanup(lambda: b.run('set', 'viewport', str(w), str(h), '1', check=False))
        self.open_thread(size, tid, title)
        if scale is not None:
            b.run('set', 'viewport', str(w), str(h), str(scale))
        if not b.eval('JSON.stringify(!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)&&typeof MediaRecorder==="function")'):
            self.skipTest('this browser has no microphone API on a loopback page')
        b.wait('JSON.stringify(!!document.querySelector("#mic").offsetParent)', what='the record button')
        self.assertEqual(b.eval(ARM), 'ok')
        self.addCleanup(self.drop)

    def see(self):
        return self.browser.eval(SEE)

    def picture(self):
        return self.browser.eval(PICTURE)

    def frames(self, n=3, timeout=120):
        start = self.browser.eval('JSON.stringify(ADV.raf)')
        self.browser.wait('JSON.stringify(ADV.raf>=%d)' % (start + n), timeout=timeout, what='%d frames of the screen' % n)

    def press(self):
        self.browser.pointer('#mic', 'pointerdown')
        self.browser.wait(self.RECORDING, timeout=20, what='the recording to start')

    def lock(self):
        self.browser.eval('(()=>{lockRec();return "ok";})()')
        self.browser.pointer('#mic', 'pointerup')
        self.browser.wait('JSON.stringify(!!rec&&rec.locked)', timeout=10, what='a locked recording')

    def locked(self):
        self.press()
        self.lock()

    def drawn(self, timeout=120):
        """Wait until the loop has drawn bars on the canvas; give the picture back."""
        self.browser.wait('(()=>{const c=document.querySelector("#rec-wave");if(!c.width||!c.height||!rec||rec.wave.bars.length<2)return JSON.stringify(false);'
                          'const d=c.getContext("2d").getImageData(0,0,c.width,c.height).data;for(let i=3;i<d.length;i+=4)if(d[i])return JSON.stringify(true);return JSON.stringify(false);})()',
                          timeout=timeout, what='bars on the canvas')
        return self.picture()

    def gone(self, timeout=30):
        self.browser.wait('JSON.stringify(!rec&&document.querySelector("#rec").hidden)', timeout=timeout, what='the recording gone')

    def drop(self):
        try:
            self.browser.eval('(()=>{if(typeof ADV!=="undefined"){ADV.manual=false;}if(rec)finishRec("cancel");return "ok";})()')
            self.gone()
        except Exception:
            pass

    def limit(self):
        """As if he had recorded for ten minutes: the recording stops and waits, locked, for send or delete."""
        self.browser.eval('(()=>{rec.started=performance.now()-600000;return "ok";})()')
        self.browser.wait('JSON.stringify(!!rec&&rec.done&&rec.locked)', timeout=30, what='the limit of ten minutes')

    def quiet(self, what):
        """No frame of the loop is asked for, and none comes."""
        before = self.see()
        self.assertEqual(before['pending'], 0, 'a frame of the loop is still asked for after %s: %s' % (what, before))
        self.frames(3)
        after = self.see()
        self.assertEqual((after['pending'], after['levels'], after['draws']), (0, before['levels'], before['draws']), 'the loop went on after %s: %s' % (what, after))
        return after

    @staticmethod
    def dense(pic):
        return min(2, pic['dpr'] or 1)

    # ── 1. it never breaks or delays a recording ─────────────────────────────

    def test_with_no_2d_context_the_meter_goes_on_and_the_recording_is_sent(self):
        """A canvas that gives no 2D context (iOS gives null once the page's canvases are over its memory limit).
        The recording, its clock and its sending must be as before, and so must the meter."""
        self.fresh(COVER)
        b = self.browser
        b.eval('(()=>{document.querySelector("#rec-wave").getContext=()=>null;return "ok";})()')
        before = len(self.voices(self.A[0]))
        self.locked()
        self.frames(4)
        first = self.see()
        self.frames(5)
        later = self.see()
        b.wait('JSON.stringify(document.querySelector("#rec-time").textContent!=="0:00")', timeout=30, what='the clock of the recording')
        b.click('#rec-send')
        self.gone()
        self.until(lambda: len(self.voices(self.A[0])) > before, timeout=60, what='the voice message in state.json')
        self.assertEqual(self.see()['pending'], 0)
        # the hole: five frames of the screen went by and the meter was not touched
        self.assertGreaterEqual(later['levels'] - first['levels'], 3,
                                'with no 2D context the loop died, and the meter with it: %s then %s' % (first, later))
        self.assertEqual(later['errs'], [], 'an exception escaped the loop')

    def test_with_no_audio_graph_the_recording_its_clock_its_limit_and_its_end_are_as_before(self):
        for what, stand_in in (('no AudioContext', 'window.AudioContext=undefined;window.webkitAudioContext=undefined;'),
                               ('an AudioContext that throws', 'window.AudioContext=function(){throw new Error("no audio here");};'),
                               ('an analyser that throws', '{const Real=window.AudioContext;window.AudioContext=class extends Real{createAnalyser(){throw new Error("no analyser");}};}'),
                               ('a suspended AudioContext', '{const Real=window.AudioContext;window.AudioContext=class extends Real{constructor(){super();this.suspend();}};}')):
            with self.subTest(what=what):
                self.fresh(COVER)
                b = self.browser
                b.eval('(()=>{%s return "ok";})()' % stand_in)
                before = len(self.voices(self.A[0]))
                self.locked()
                b.wait('JSON.stringify(document.querySelector("#rec-time").textContent!=="0:00")', timeout=30, what='the clock of the recording')
                self.limit()
                held = self.see()
                self.assertEqual((held['clock'], held['pending']), ('10:00', 0), held)
                b.click('#rec-send')
                self.gone()
                self.until(lambda: len(self.voices(self.A[0])) > before, timeout=60, what='the voice message in state.json')
                # and one that is thrown away
                self.locked()
                b.click('#rec-cancel')
                self.gone()
                after = self.quiet(what)
                self.assertEqual(after['errs'], [], after)
                self.assertEqual(len(self.voices(self.A[0])), before + 1)

    # ── 2. cheap: one loop, none left behind ─────────────────────────────────

    def test_however_the_recording_ends_no_loop_is_left_and_the_picture_is_wiped(self):
        self.fresh(COVER)
        b = self.browser
        tid, other = self.A[0], self.B[0]
        sent = len(self.voices(tid))
        tap = '(()=>{micPress.at=performance.now();return "ok";})()'
        slide = ('(()=>{const el=document.querySelector("#mic"),r=el.getBoundingClientRect();el.dispatchEvent(new PointerEvent("pointermove",{bubbles:true,cancelable:true,pointerId:7,'
                 'pointerType:"touch",button:0,buttons:1,clientX:r.left+r.width/2+130,clientY:r.top+r.height/2,isPrimary:true}));return "ok";})()')
        endings = (
            ('the finger is lifted: sent', False, lambda: b.pointer('#mic', 'pointerup'), 1),
            ('a tap: thrown away', False, lambda: (b.eval(tap), b.pointer('#mic', 'pointerup')), 0),
            ('the finger slides to the side: thrown away', False, lambda: b.eval(slide), 0),
            ('locked, the bin', True, lambda: b.click('#rec-cancel'), 0),
            ('locked, send', True, lambda: b.click('#rec-send'), 1),
            ('locked, Esc', True, lambda: b.press('Escape'), 0),
            ('held, he goes to another thread', False, lambda: b.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(other)), 0),
            ('locked, he goes to another thread', True, lambda: b.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(other)), 0),
            ('the recorder fails', True, lambda: b.eval('(()=>{rec.recorder.onerror(new Event("error"));return "ok";})()'), 0),
            ('the limit, then send', True, 'limit-send', 1),
            ('the limit, then the bin', True, 'limit-bin', 0),
            ('the limit, then another thread', True, 'limit-left', 0),
        )
        for what, lock, end, more in endings:
            with self.subTest(ending=what):
                if b.eval('JSON.stringify(view.ch)') != tid:
                    b.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
                    b.wait('JSON.stringify(view.ch===%s&&!!document.querySelector("#mic").offsetParent)' % json.dumps(tid), timeout=20, what='the thread again')
                self.press()
                if lock:
                    self.lock()
                pic = self.drawn()
                self.assertGreater(pic['ink'], 0, 'the recording after the last one draws nothing: %s' % {k: pic[k] for k in ('w', 'h', 'cli', 'ink')})
                self.assertEqual(pic['w'], round(pic['cli'][0] * self.dense(pic)), pic['cli'])
                b.wait('JSON.stringify(performance.now()-rec.started>900)', timeout=10, what='a recording long enough to send')
                if isinstance(end, str):
                    self.limit()
                    kept = self.picture()
                    self.assertGreater(kept['ink'], 0, 'the picture is not kept while the recording waits at its limit')
                    self.quiet(what + ' (waiting at the limit)')
                    # the mic is pressed again while it waits: nothing new starts
                    b.eval('(()=>{window.HELD=rec;beginRec(null);return "ok";})()')
                    b.pointer('#mic', 'pointerdown')
                    b.pointer('#mic', 'pointerup')
                    self.frames(2)
                    self.assertTrue(b.eval('JSON.stringify(rec===HELD&&rec.done)'), 'a press at the limit changed the recording')
                    self.assertEqual(self.see()['pending'], 0)
                    {'limit-send': lambda: b.click('#rec-send'), 'limit-bin': lambda: b.click('#rec-cancel'),
                     'limit-left': lambda: b.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(other))}[end]()
                else:
                    end()
                self.gone()
                after = self.quiet(what)
                wiped = self.picture()
                self.assertEqual(wiped['ink'], 0, 'the last recording is still drawn after ' + what)
                self.assertLessEqual(after['most'], 1, 'two frames of the loop were asked for at once: %s' % after)
                sent += more
                if more:
                    self.until(lambda: len(self.voices(tid)) >= sent, timeout=60, what='the voice message in state.json after ' + what)
        time.sleep(1)
        self.assertEqual(len(self.voices(tid)), sent, 'a recording that was thrown away was sent, or one was sent twice')
        self.assertEqual(self.see()['errs'], [])

    def test_many_recordings_in_a_row_leave_one_loop_and_the_canvas_is_not_resized_frame_after_frame(self):
        self.fresh(COVER)
        b = self.browser
        for _ in range(12):
            self.locked()
            b.click('#rec-cancel')
            self.gone()
        self.locked()
        self.drawn()
        start = self.see()
        self.frames(8)
        end = self.see()
        self.assertLessEqual(end['most'], 1, end)
        self.assertEqual(end['pending'], 1, end)
        # one drawing for a frame of the screen, and no more
        self.assertLessEqual(end['levels'] - start['levels'], end['raf'] - start['raf'] + 1, (start, end))
        self.assertGreaterEqual(end['levels'] - start['levels'], 4, (start, end))
        self.assertEqual(end['sets'], start['sets'], 'the canvas was resized while its place did not change: %s then %s' % (start, end))
        self.assertLessEqual(end['bars'], 320)
        self.assertEqual(end['errs'], [])

    def test_a_frame_of_the_loop_is_cheap_resizes_nothing_and_forces_no_layout(self):
        """300 frames in a row, by hand, 16.7 ms apart, over a full history and a level that changes every frame."""
        import os
        import tempfile
        for size in (COVER, DESKTOP):
            with self.subTest(width=size[1]):
                self.fresh(size)
                b = self.browser
                b.eval('(()=>{ADV.manual=true;return "ok";})()')
                self.locked()
                t0 = b.eval('JSON.stringify(rec.wave.last)')
                b.eval('(()=>{const real=window.waveLevel;let n=0;window.waveLevel=function(s){real.call(this,s);return (n++%%50)/50;};ADV.step(%r+5);'
                       'rec.wave.bars=Array.from({length:WAVE_MAX},(_,i)=>(i%%9)/9);return "ok";})()' % t0)
                out = os.path.join(tempfile.mkdtemp(prefix='adv-wave-trace-'), 'trace.json')
                traced = b.run('trace', 'start', check=False).returncode == 0
                got = b.eval('(()=>{const t=performance.now(),sets=ADV.sets;for(let i=1;i<=300;i++)ADV.step(%r+100+i*16.7);'
                             'return JSON.stringify({ms:performance.now()-t,sets:ADV.sets-sets,errs:ADV.errs,bars:rec.wave.bars.length,drawn:ADV.last});})()' % t0)
                layouts = None
                if traced and b.run('trace', 'stop', out, check=False).returncode == 0 and os.path.exists(out):
                    with open(out) as f:
                        events = json.load(f)
                    events = events.get('traceEvents', events) if isinstance(events, dict) else events
                    layouts = sum(1 for e in events if e.get('name') == 'Layout' and e.get('ph') in ('X', 'B'))
                self.assertEqual(got['errs'], [])
                self.assertEqual(got['bars'], 320, got)
                self.assertEqual(got['sets'], 0, 'the canvas was resized while its place did not change')
                self.assertLess(got['ms'] / 300, 0.5, 'a frame of the loop costs %.3f ms on this Mac' % (got['ms'] / 300))
                if layouts is not None:
                    self.assertLessEqual(layouts, 5, '%d layouts for 300 frames: the loop forces one every frame' % layouts)
                self.drop()

    def test_while_the_page_is_hidden_no_frame_is_drawn_and_a_recording_that_ends_there_leaves_no_loop(self):
        self.fresh(COVER)
        b = self.browser
        self.locked()
        self.drawn()
        # the page writes down what it sees twice a second: the test cannot ask it while another tab is in front
        b.eval('(()=>{window.LOG=[];setInterval(()=>LOG.push({hidden:document.hidden,levels:ADV.levels,pending:ADV.pending.size,rec:!!rec,done:!!(rec&&rec.done),bars:rec?rec.wave.bars.length:-1}),500);return "ok";})()')
        self.frames(2)
        before = self.see()
        b.run('tab', 'new', 'about:blank')
        self.addCleanup(lambda: b.run('tab', 'close', check=False))
        time.sleep(5)
        b.run('tab', 't1')
        b.wait('JSON.stringify(!document.hidden)', timeout=20, what='the page in front again')
        log = b.eval('JSON.stringify(LOG)')
        away = [row for row in log if row['hidden']]
        if len(away) < 3:
            self.skipTest('this browser does not hide the page behind another tab: %s' % log[-4:])
        self.assertTrue(all(row['rec'] and not row['done'] for row in away), 'the recording ended because the page was hidden')
        self.assertLessEqual(away[-1]['levels'] - away[0]['levels'], 1, 'frames were drawn while the page was hidden: %s' % away)
        self.frames(4)
        back = self.see()
        self.assertGreater(back['levels'], away[-1]['levels'], 'the loop did not go on when the page came back')
        self.assertEqual((back['pending'], back['most']), (1, 1), back)
        self.assertLessEqual(back['bars'] - before['bars'], (back['levels'] - before['levels']) + 1, 'more than one bar for the time the page was away')
        # now it ends while the page is hidden: first the limit, then he is given no chance to send
        b.eval('(()=>{LOG.length=0;setTimeout(()=>{rec.started=performance.now()-600000;},1500);setTimeout(()=>{finishRec("cancel");},5000);return "ok";})()')
        b.run('tab', 'new', 'about:blank')
        time.sleep(8)
        b.run('tab', 't1')
        b.wait('JSON.stringify(!document.hidden)', timeout=20, what='the page in front again')
        self.gone()
        log = b.eval('JSON.stringify(LOG)')
        waited = [row for row in log if row['hidden'] and row['done']]
        self.assertTrue(waited, 'the limit was not reached while the page was hidden: %s' % log)
        self.assertTrue(all(row['pending'] == 0 for row in waited), 'a frame was still asked for at the limit, behind another tab: %s' % waited)
        self.quiet('an end behind another tab')
        self.assertEqual(self.picture()['ink'], 0)

    # ── 3. the picture ───────────────────────────────────────────────────────

    def expected(self, pic, slots, rtl):
        """The ink of every column of the backing store when bars of these heights (CSS px) stand in these slots."""
        k = self.dense(pic)
        cols = [0.0] * pic['w']
        for slot, height in slots.items():
            for x in range(3):
                css = slot * 5 + x
                if not rtl:
                    css = pic['cli'][0] - 1 - css
                for sub in range(int(k)):
                    at = int(css * k + sub)
                    if 0 <= at < pic['w']:
                        cols[at] = max(cols[at], height * k)
        return cols

    def test_the_bars_stand_where_they_should_on_the_canvas_in_hebrew_in_english_and_on_a_dense_screen(self):
        # the history is held still: three whole bars (the oldest loud, then silence, then half) and a quarter now
        frozen = '(()=>{window.waveStep=function(w,level,at){w.bars=[1,0,0.5];w.peak=0.25;w.last=at-1e6;return false;};return "ok";})()'
        for what, scale, ltr in (('Hebrew', None, False), ('English', None, True), ('Hebrew, a dense screen', 2, False), ('English, a dense screen', 3, True)):
            with self.subTest(page=what):
                self.fresh(COVER, scale=scale)
                b = self.browser
                if ltr:
                    b.eval('(()=>{document.documentElement.dir="ltr";return "ok";})()')
                self.locked()
                self.drawn()
                b.eval(frozen)
                self.frames(3)
                pic = self.picture()
                self.assertEqual(pic['dir'], 'ltr' if ltr else 'rtl')
                self.assertEqual(pic['dpr'], scale or 1)
                self.assertEqual((pic['w'], pic['h']), (round(pic['cli'][0] * self.dense(pic)), round(pic['cli'][1] * self.dense(pic))), pic['cli'])
                self.assertLessEqual(pic['w'], pic['cli'][0] * 2 + 1)
                want = self.expected(pic, {0: 7, 1: 14, 2: 2, 3: 28}, rtl=not ltr)
                self.assertEqual(pic['cols'], want, 'the bars are not where they should be (%s, %s px wide, density %s)' % (what, pic['cli'][0], pic['dpr']))
                self.drop()

    def test_the_history_slides_away_from_the_newest_bar_and_steps_where_motion_is_reduced(self):
        for what, media in (('sliding', ('light',)), ('stepping', ('light', 'reduced-motion'))):
            with self.subTest(motion=what):
                self.fresh(COVER, media=media)
                b = self.browser
                b.eval('(()=>{ADV.manual=true;return "ok";})()')           # the loop's frames come from the test, at times it chooses
                self.locked()
                t0 = b.eval('JSON.stringify(rec.wave.last)')
                self.assertGreater(t0, 0)
                seen = b.eval('(()=>{const out=[];for(const ms of [10,35,69,70,80,105,139.5,140,141,400,401]){ADV.step(%r+ms);out.push([ms,ADV.last&&ADV.last.shift,rec.wave.bars.length]);}'
                              'return JSON.stringify({out,errs:ADV.errs,pending:ADV.pending.size});})()' % t0)
                self.assertEqual(seen['errs'], [])
                self.assertEqual(seen['pending'], 1)
                got = [(ms, round(shift, 3), bars) for ms, shift, bars in seen['out']]
                if what == 'sliding':
                    want = [(10, round(10 / 70, 3), 0), (35, 0.5, 0), (69, round(69 / 70, 3), 0), (70, 0, 1), (80, round(10 / 70, 3), 1), (105, 0.5, 1),
                            (139.5, round(69.5 / 70, 3), 1), (140, 0, 2), (141, round(1 / 70, 3), 2), (400, 0, 3), (401, round(1 / 70, 3), 3)]
                else:
                    # (a whole step, since the review: the bar being heard is then never behind the last whole one)
                    want = [(ms, 1, bars) for ms, bars in ((10, 0), (35, 0), (69, 0), (70, 1), (80, 1), (105, 1), (139.5, 1), (140, 2), (141, 2), (400, 3), (401, 3))]
                self.assertEqual(got, want)
                # on the canvas: a loud bar half way to its next place is half a step from the edge
                if what == 'sliding':
                    b.eval('(()=>{window.waveStep=function(w,level,at){w.bars=[1];w.peak=0;return false;};rec.wave.last=%r+1000;ADV.step(%r+1035);return "ok";})()' % (t0, t0))
                    pic = self.picture()
                    k = self.dense(pic)
                    loud = [(x, v) for x, v in enumerate(pic['cols']) if v > 2 * k + 0.01]
                    centre = sum((x + 0.5) * v for x, v in loud) / sum(v for _, v in loud) / k
                    self.assertAlmostEqual(centre, 0.5 * 5 + 1.5, delta=0.05, msg='half way to its next place the bar is not half a step from the edge: %s' % pic['cols'][:12])
                self.drop()

    def test_the_picture_follows_its_place_when_the_recording_is_locked_and_when_the_phone_is_unfolded(self):
        self.fresh(COVER)
        b = self.browser
        self.addCleanup(lambda: b.viewport(360, 840))
        self.press()
        held = self.drawn()
        self.assertEqual(held['w'], round(held['cli'][0] * self.dense(held)))
        self.lock()
        self.frames(3)
        locked = self.drawn()
        self.assertNotEqual(locked['cli'][0], held['cli'][0], 'locking did not change the width of the wave: the test proves nothing')
        self.assertEqual(locked['w'], round(locked['cli'][0] * self.dense(locked)), 'after the lock the picture is not as wide as its place: %s' % locked['cli'])
        self.assertGreater(sum(locked['cols'][:3]), 0, 'after the lock nothing stands at the edge of the newest bar')
        bars = self.see()['bars']
        b.viewport(750, 835)                                     # the phone is unfolded while he records
        self.frames(3)
        self.assertTrue(b.eval('JSON.stringify(!!rec&&rec.locked&&!rec.done)'), 'unfolding the phone ended the recording')
        wide = self.drawn()
        self.assertGreater(wide['cli'][0], locked['cli'][0])
        self.assertEqual(wide['w'], round(wide['cli'][0] * self.dense(wide)), 'after unfolding the picture is not as wide as its place: %s' % wide['cli'])
        self.assertGreater(sum(wide['cols'][:3]), 0)
        self.assertGreaterEqual(self.see()['bars'], bars, 'the history was lost when the phone was unfolded')
        b.viewport(360, 840)
        self.frames(3)
        back = self.drawn()
        self.assertEqual(back['w'], round(back['cli'][0] * self.dense(back)))
        self.assertEqual(self.see()['errs'], [])

    def test_a_screen_of_any_density_gets_a_picture_no_larger_than_twice_its_place(self):
        for scale in (2.625, 3, 0.5, 1.25):
            with self.subTest(density=scale):
                self.fresh(DESKTOP if scale == 3 else COVER, scale=scale)
                self.locked()
                pic = self.drawn()
                self.assertAlmostEqual(pic['dpr'], scale, places=2)
                self.assertEqual(pic['w'], round(pic['cli'][0] * min(2, scale)), pic)
                self.assertEqual(pic['h'], round(pic['cli'][1] * min(2, scale)), pic)
                self.assertLessEqual(pic['w'] * pic['h'], 840 * 56)
                self.assertGreater(sum(pic['cols'][:3]), 0, 'nothing stands at the edge of the newest bar')
                self.drop()

    def test_at_the_limit_the_picture_is_away_and_never_shown_squeezed(self):
        """The recording hits ten minutes: it stops and waits for send or delete. The bar changes then (the long
        hint comes), after the picture's last frame was drawn: left in a smaller place it was shown squeezed.
        Decided after this review: at the limit nothing is heard any more, so the meter and the picture are away
        and the line that says "ten minutes" has their room."""
        self.fresh(COVER)
        self.locked()
        before = self.drawn()
        self.assertGreater(before['cli'][0], 40)
        self.limit()
        self.frames(2)
        kept = self.picture()
        self.assertEqual(kept['cli'][0], 0, 'at the limit the picture is still shown, in %s px (it was drawn for %s px)' % (kept['cli'][0], before['cli'][0]))
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#rec-hint").getBoundingClientRect().width>=60&&!document.querySelector(".rec-level").offsetParent)'))

    def test_the_picture_is_made_sharp_again_when_the_density_of_the_screen_changes(self):
        """The window goes to a denser screen (or he zooms) while he records and the place of the wave keeps its
        width in CSS px."""
        self.fresh(DESKTOP)
        b = self.browser
        self.addCleanup(lambda: b.run('set', 'viewport', '1280', '800', '1', check=False))
        self.locked()
        before = self.drawn()
        self.assertEqual((before['dpr'], before['w']), (1, before['cli'][0]))
        b.run('set', 'viewport', '1280', '800', '2')
        self.frames(4)
        after = self.drawn()
        self.assertEqual(after['dpr'], 2)
        self.assertEqual(after['cli'], before['cli'], 'the place of the wave changed with the density: the test proves nothing')
        self.assertEqual(after['w'], after['cli'][0] * 2, 'the screen is twice as dense and the picture is still %s px for %s px' % (after['w'], after['cli'][0]))

    def test_the_bars_take_the_colour_of_the_theme_also_when_it_changes_while_he_records(self):
        self.fresh(COVER, media=('light',))
        b = self.browser
        self.addCleanup(lambda: b.run('set', 'media', 'light', check=False))
        rgb = lambda text: [int(n) for n in re.findall(r'\d+', text)[:3]]
        self.locked()
        light = self.drawn()
        self.assertEqual(light['best'][:3], rgb(light['color']), 'in the light theme the bars are not of the colour CSS gives them')
        b.run('set', 'media', 'dark')
        self.frames(4)
        dark = self.drawn()
        self.assertNotEqual(rgb(dark['color']), rgb(light['color']), 'the theme did not change: the test proves nothing')
        self.assertEqual(dark['best'][:3], rgb(dark['color']), 'the theme went dark and the bars kept the colour of the light one')

    def test_a_late_second_close_of_an_older_recording_does_not_blank_the_one_in_progress(self):
        """closeRec runs twice for one recording when its recorder says 'error' and then 'stop'. The second run
        wipes the canvas whoever owns it now."""
        self.fresh(COVER)
        b = self.browser
        self.locked()
        self.drawn()
        b.eval('(()=>{window.OLDER=rec;return "ok";})()')
        b.click('#rec-cancel')
        self.gone()
        self.locked()
        self.drawn()
        b.eval('(()=>{closeRec(OLDER);return "ok";})()')             # what a late 'stop' of the older recorder does
        self.assertTrue(b.eval('JSON.stringify(!!rec&&rec!==OLDER&&!document.querySelector("#rec").hidden)'), 'the recording in progress was ended')
        self.frames(4)
        pic = self.picture()
        self.assertGreater(pic['ink'], 0, 'the recording in progress has no picture any more (the canvas is %s px wide for a place of %s px)' % (pic['w'], pic['cli'][0]))

    # ── 4. the bar still fits ────────────────────────────────────────────────

    def boxes(self, old=False):
        self.browser.eval(OLD % ('true' if old else 'false'))
        got = self.browser.eval(BOXES)
        self.browser.eval(OLD % 'false')
        return got

    def check_fit(self, got, locked, what, full=False):
        bar = got['bar']
        self.assertLessEqual(got['barOver'], 0, '%s: something sticks out of the bar: %s' % (what, got))
        shown = [(k, got[k]) for k in ('cancel', 'dot', 'time', 'level', 'wave', 'hint', 'send') if got[k]]
        for name, box in shown:
            self.assertTrue(bar[0] - 0.5 <= box[0] and box[1] <= bar[1] + 0.5, '%s: %s is outside the bar: %s' % (what, name, got))
        ordered = sorted(shown, key=lambda item: -item[1][1])            # Hebrew: from the right
        self.assertEqual([name for name, _ in ordered], [name for name, _ in shown], '%s: the parts are out of order' % what)
        for (a, abox), (c, cbox) in zip(ordered, ordered[1:]):
            self.assertLessEqual(cbox[1], abox[0] + 0.5, '%s: %s lies over %s: %s' % (what, c, a, got))
        self.assertGreaterEqual(got['time'][2], 30, what)
        if full:        # decided after this review: at the limit nothing is heard any more, the meter and the wave are away and the line of words has the room
            self.assertIsNone(got['level'], what)
            self.assertIsNone(got['wave'], what)
            self.assertIsNotNone(got['hint'], '%s: no hint' % what)
        else:
            self.assertGreaterEqual(got['level'][2], 20, what)
            self.assertGreaterEqual(got['wave'][2], 32, what)          # (the wave gives way to the hint on a narrow phone: 32 px at the least, since the review)
        if locked:
            self.assertIsNone(got['mic'], what)
            for name in ('cancel', 'send'):
                self.assertIsNotNone(got[name], '%s: %s is not shown' % (what, name))
                self.assertGreaterEqual(got[name][2], 36, '%s: %s is too small to press' % (what, name))
                self.assertTrue(0 <= got[name][0] and got[name][1] <= got['vw'], '%s: %s is off the screen' % (what, name))
                self.assertTrue(got[name + 'On'], '%s: %s is covered by something' % (what, name))
        else:
            self.assertIsNotNone(got['mic'], what)
            for name, box in shown:
                self.assertGreaterEqual(box[0], got['mic'][1], '%s: %s lies over the mic: %s' % (what, name, got))
            self.assertIsNotNone(got['hint'], '%s: no hint' % what)

    def test_the_bar_holds_everything_at_every_width_held_and_locked_with_any_clock(self):
        for size in (SMALL, COVER, INNER, DESKTOP):
            with self.subTest(width=size[1]):
                self.fresh(size)
                b = self.browser
                self.press()
                self.frames(2)
                for clock, ms in (('0:0', 3000), ('9:4', 580000)):
                    b.eval('(()=>{rec.started=performance.now()-%d;paintRec();return "ok";})()' % ms)
                    got = self.boxes()
                    self.assertTrue(got['clock'].startswith(clock), got['clock'])
                    self.check_fit(got, False, '%s px, held, %s' % (size[1], got['clock']))
                    if size is not SMALL:               # the 320 px screen has its own test below
                        self.assertLessEqual(got['hintCut'], 0, '%s px, held: the hint is cut: %s' % (size[1], got))
                b.eval('(()=>{rec.started=performance.now()-3000;paintRec();return "ok";})()')
                self.lock()
                for clock, ms in (('0:0', 3000), ('9:4', 580000)):
                    b.eval('(()=>{rec.started=performance.now()-%d;paintRec();return "ok";})()' % ms)
                    got = self.boxes()
                    self.assertTrue(got['clock'].startswith(clock), got['clock'])
                    self.check_fit(got, True, '%s px, locked, %s' % (size[1], got['clock']))
                self.limit()
                got = self.boxes()
                self.assertEqual(got['clock'], '10:00')
                self.check_fit(got, True, '%s px, at the limit' % size[1], full=True)
                self.drop()

    def test_on_a_320_px_phone_the_hint_is_whole_while_he_holds(self):
        """Before the change "הצידה: ביטול" was whole on a 320 px screen; it tells him how to throw the recording away."""
        self.fresh(SMALL)
        self.press()
        self.frames(2)
        old, new = self.boxes(old=True), self.boxes()
        self.assertEqual(old['hintCut'], 0, 'before the change the hint was cut too: %s' % old)
        self.assertLessEqual(new['hintCut'], 0, 'the hint needs %s px and has %s (it had %s before the change): %s px of it are cut'
                             % (new['hintNeeds'], new['hint'][2], old['hint'][2], new['hintCut']))

    def test_at_360_px_the_hint_keeps_the_room_it_had_for_larger_text(self):
        """The hint is 66 px wide in this Chrome with the Mac's Hebrew font. His phone has another font, and Android
        can make text larger: before the change the hint had 96 px at 360 px, so text a quarter larger was whole."""
        self.fresh(COVER)
        b = self.browser
        self.press()
        self.frames(2)
        b.eval('(()=>{document.querySelector("#rec-hint").style.fontSize="16.25px";return "ok";})()')
        old, new = self.boxes(old=True), self.boxes()
        self.assertEqual(old['hintCut'], 0, 'before the change the larger hint was cut too: %s' % old)
        self.assertLessEqual(new['hintCut'], 0, 'a hint of %s px had %s px before the change and has %s now: %s px of it are cut'
                             % (new['hintNeeds'], old['hint'][2], new['hint'][2], new['hintCut']))

    def test_at_the_limit_no_less_of_the_hint_is_shown_than_before_the_change(self):
        """"הגעת ל-10 דקות. לשלוח או למחוק." is all he is told when the recording stops by itself."""
        for size in (SMALL, COVER):
            with self.subTest(width=size[1]):
                self.fresh(size)
                self.locked()
                self.limit()
                self.frames(2)
                old, new = self.boxes(old=True), self.boxes()
                self.assertGreaterEqual(new['hint'][2], min(old['hint'][2], new['hintNeeds']) - 1,
                                        'at %s px the hint needs %s px; it had %s before the change and has %s now' % (size[1], new['hintNeeds'], old['hint'][2], new['hint'][2]))
                self.drop()

    def test_below_320_px_the_bar_at_the_limit_keeps_its_send_button_inside_as_it_did(self):
        """Narrower than the widths the change promises (a folded phone's 280 px cover): before the change the
        locked bar still held its two buttons there."""
        self.fresh(('tiny', 280, 700))
        self.locked()
        self.limit()
        self.frames(2)
        old, new = self.boxes(old=True), self.boxes()
        self.assertLessEqual(old['barOver'], 0, 'before the change the bar overflowed too: %s' % old)
        self.assertLessEqual(new['barOver'], 0, 'at 280 px the bar overflows by %s px: send stands at %s, the bar at %s (before the change send stood at %s)'
                             % (new['barOver'], new['send'][:2], new['bar'][:2], old['send'][:2]))

    # ── outside the change (the lines are older than the diff): seen on the way ──

    def test_outside_the_change_two_finishes_before_the_recorder_stops_send_one_message(self):
        """finishRec('send') stops the recorder; its 'stop' comes a task later. A second finishRec in between (the
        limit's timer and his press on send, or two presses) finds the recorder inactive and closes at once, and
        the 'stop' closes again: closeRec has no guard, so sendVoice runs twice."""
        self.fresh(COVER)
        b = self.browser
        before = len(self.voices(self.A[0]))
        self.locked()
        self.drawn()
        b.wait('JSON.stringify(performance.now()-rec.started>1200)', timeout=10, what='a recording long enough to send')
        b.eval('(()=>{finishRec("send");finishRec("send");return "ok";})()')
        self.gone()
        self.until(lambda: len(self.voices(self.A[0])) > before, timeout=60, what='the voice message in state.json')
        time.sleep(5)
        self.assertEqual(len(self.voices(self.A[0])) - before, 1, 'one recording was sent as two messages')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvWave.__dict__:
        setattr(AdvWave, _name, None)


if __name__ == '__main__':
    unittest.main()
