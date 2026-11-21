#!/usr/bin/env python3
"""Hostile review of the live waveform (d1ca356..667e0be): the pure helpers under node, and the page as text.

Every test states the CORRECT behaviour, so a FAIL is a hole. Nothing here opens a browser or a server.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

PAGE = _paths.APP / 'suda.html'


class WavePure(unittest.TestCase):
    def page(self):
        return PAGE.read_text(encoding='utf-8')

    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = self.page().split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    # ── held: the numbers ────────────────────────────────────────────────────

    def test_the_level_of_any_samples_the_analyser_can_give_is_between_0_and_1(self):
        self.pure_js(r"""
        for(const odd of [null,undefined,[],new Uint8Array(0),'']){assert.strictEqual(waveLevel(odd),0,String(odd));}
        for(const fill of [0,1,127,128,129,255]){const v=waveLevel(new Uint8Array(256).fill(fill));assert.ok(v>=0&&v<=1&&Number.isFinite(v),fill+': '+v);}
        assert.strictEqual(waveLevel(new Uint8Array(256).fill(128)),0);assert.strictEqual(waveLevel(new Uint8Array(1).fill(0)),1);
        // the same number the meter showed before the change
        const old=wave=>{let sum=0;for(const v of wave)sum+=(v-128)*(v-128);return Math.min(1,Math.sqrt(sum/wave.length)/40);};
        let seed=7;const rnd=()=>(seed=(seed*1103515245+12345)&0x7fffffff)/0x7fffffff;
        for(let k=0;k<200;k++){const w=Uint8Array.from({length:256},()=>Math.floor(128+(rnd()-0.5)*rnd()*255));assert.strictEqual(waveLevel(w).toFixed(3),old(w).toFixed(3));}
        """)

    def test_the_history_is_bounded_and_clean_whatever_is_fed_to_it(self):
        self.pure_js(r"""
        let seed=11;const rnd=()=>(seed=(seed*1103515245+12345)&0x7fffffff)/0x7fffffff;
        const junk=[NaN,-1,-Infinity,Infinity,1e12,'x',undefined,null,{},0.5,1,0];
        const w={bars:[],peak:0,last:0};let at=5;
        for(let i=0;i<20000;i++){
          at+=[1,8,16,33,70,71,500,600000][Math.floor(rnd()*8)];             // frames of any length, and a tab that slept for minutes
          const stepped=waveStep(w,junk[Math.floor(rnd()*junk.length)],at);
          assert.ok(stepped===true||stepped===false);
          assert.ok(w.bars.length<=WAVE_MAX,'the history grew to '+w.bars.length);
          assert.ok(w.peak>=0&&w.peak<=1,'peak '+w.peak);
        }
        assert.strictEqual(w.bars.length,WAVE_MAX);
        for(const b of w.bars)assert.ok(b>=0&&b<=1&&Number.isFinite(b),'a bar of '+b);
        // the very first frame only starts the clock, and keeps what it heard
        const f={bars:[],peak:0,last:0};assert.strictEqual(waveStep(f,0.9,123456),false);assert.deepStrictEqual(f,{bars:[],peak:0.9,last:123456});
        // a sleep of minutes is one bar
        waveStep(f,0.1,123456+600000);assert.deepStrictEqual(f.bars,[0.9]);
        // a step is never missed: at 60, 30 and 120 frames a second a bar comes at least every two stretches
        for(const frame of [1000/120,1000/60,1000/30,69.9,70,70.1]){const g={bars:[],peak:0,last:0};let t=1000;for(let i=0;i<600;i++){waveStep(g,0.3,t);t+=frame;}
          const ms=600*frame,least=Math.floor(ms/(2*WAVE_EVERY))-1;assert.ok(g.bars.length>=Math.min(WAVE_MAX,least),frame+': '+g.bars.length+' bars in '+ms+' ms');}
        """)

    def test_inside_the_range_the_loop_can_give_the_bars_stand_where_they_should(self):
        self.pure_js(r"""
        const slot=WAVE_BAR+WAVE_GAP,H=28;
        const bars=Array.from({length:50000},(_,i)=>(i%7)/7);
        const began=Date.now();
        for(const W of [48,49,50,51,52,53,60,72,108,193,242,420,1,2,3,4]){
          for(const shift of [0,0.001,0.25,0.5,0.75,0.999]){
            const ltr=waveRects(bars,0.4,shift,W,H,false),rtl=waveRects(bars,0.4,shift,W,H,true);
            assert.strictEqual(ltr.length,rtl.length);
            assert.ok(ltr.length<=Math.ceil(W/slot)+2,'too many bars for '+W+': '+ltr.length);
            // the one being heard now is whole, at the edge where the writing goes on
            if(W>=WAVE_BAR){assert.strictEqual(ltr[0][0],W-WAVE_BAR);assert.strictEqual(rtl[0][0],0);}
            ltr.forEach(([x,y,w,h],i)=>{
              assert.strictEqual(w,WAVE_BAR);assert.ok(h>=2&&h<=H,'height '+h);assert.ok(y>=0&&y+h<=H,'above or below the picture');
              assert.ok(x+w>0&&x<W,'a bar wholly outside the picture at '+x+' of '+W);
              assert.ok(Math.abs(rtl[i][0]-(W-WAVE_BAR-x))<1e-9,'Hebrew is not the mirror of English');
              if(i>1)assert.ok(Math.abs((ltr[i-1][0]-x)-slot)<1e-9,'the whole bars are not a step apart');
            });
            // nothing is missing: the row reaches the far side of the picture
            if(W>=20){const far=Math.min(...ltr.map(r=>r[0]));assert.ok(far<slot,'a hole at the far side of '+W+' (shift '+shift+'): the last bar stands at '+far);}
          }
        }
        assert.ok(Date.now()-began<2000,'slow with a long history');
        // sliding is seamless: where the whole bars stand at the end of a stretch is where they stand when the next begins
        const few=[0.2,0.9,0.4],live=0.6,W=100;
        const before=waveRects(few,live,1,W,H,false),after=waveRects([...few,live],0,0,W,H,false);
        assert.deepStrictEqual(before.map(r=>[r[0],r[3]]),after.slice(1).map(r=>[r[0],r[3]]));
        // a picture of no size, or of a size that is no number, is no picture and no exception
        for(const [W2,H2] of [[0,28],[100,0],[-5,28],[NaN,28],[100,NaN],[undefined,undefined],[null,5]])assert.deepStrictEqual(waveRects([0.5],0.5,0.5,W2,H2,true),[]);
        // levels that are no levels are drawn as silence or as the loudest, never as something else
        for(const [lvl,h] of [[NaN,2],[-3,2],[undefined,2],['x',2],[9,H],[Infinity,H]])assert.strictEqual(waveRects([],lvl,0,W,H,false)[0][3],h,String(lvl));
        // fractional sizes (a picture that is 71.8 px wide) keep every bar inside
        for(const [x,y,w,h] of waveRects(few,live,0.3,71.8,27.5,true))assert.ok(x>=0&&y>=0&&y+h<=27.5);
        """)

    def test_the_page_as_text_one_loop_a_decorative_picture_and_nobody_else_uses_the_changed_rules(self):
        page = self.page()
        self.assertEqual(page.count('requestAnimationFrame(draw)'), 1)
        self.assertEqual(len(re.findall(r'<canvas id="rec-wave"[^>]*aria-hidden="true"', page)), 1)
        self.assertNotRegex(page, r'<canvas id="rec-wave"[^>]*(tabindex|role=)')
        # the two changed rules belong to the recording bar alone
        markup = page.split('<body', 1)[1].split('<script>', 1)[0]
        self.assertEqual(len(re.findall(r'class="[^"]*\brec-level\b', markup)), 1)
        self.assertEqual(len(re.findall(r'class="[^"]*\brec-hint\b', markup)), 1)
        script = page.split('<script>', 1)[1]
        self.assertNotRegex(script, r"""['"`][^'"`\n]*\brec-(level|hint)\b[^'"`\n]*['"`]\s*\)\s*(?!\.(style|textContent))\.className""")
        self.assertEqual(len(re.findall(r'rec-hint', script)), 1, 'another user of the hint')
        self.assertEqual(len(re.findall(r'rec-level', script)), 1, 'another user of the meter')
        # the bars take their colour from CSS, in both themes
        self.assertRegex(page, r'\.rec-wave\{[^}]*color:var\(--you\)')
        self.assertNotRegex(page.split('function startRec', 1)[1].split('function beginRec', 1)[0] if 'function beginRec' in page else '', r'fillStyle=[\'"]#')

    # ── holes ────────────────────────────────────────────────────────────────

    def test_where_motion_is_reduced_the_bar_that_is_heard_now_is_not_hidden_behind_the_last_whole_one(self):
        """Under prefers-reduced-motion the loop always asked for shift 0. Then the bar that is being heard and the
        newest whole bar were given the same place: one of them was never seen, and the edge showed the louder of
        "now" and "70 ms ago". After this review the loop asks for a whole step there (the page's own test pins
        `calm?1:`), and with that the places are apart."""
        self.assertIn('calm?1:(at-wave.last)/WAVE_EVERY', self.page() if hasattr(self, 'page') else (_paths.APP / 'suda.html').read_text(encoding='utf-8'))
        self.pure_js(r"""
        const W=100,H=28,calm=waveRects([0.2,1],0.1,1,W,H,true);
        const places=calm.map(r=>r[0]);
        assert.strictEqual(new Set(places).size,places.length,'two bars drawn on one place: '+JSON.stringify(calm));
        """)

    def test_a_shift_outside_0_to_1_never_puts_a_bar_outside_the_picture(self):
        """The helper says "shift (0 to 1)" and "only what is inside the picture is given", and clamps nothing."""
        self.pure_js(r"""
        const W=100,H=28;
        for(const shift of [-0.2,-1,-5,1.5,7,-Infinity,Infinity]){
          for(const rtl of [false,true])for(const [x] of waveRects([1,1,1],0.5,shift,W,H,rtl))
            assert.ok(x>=0&&x+WAVE_BAR<=W,'shift '+shift+(rtl?' (rtl)':'')+': a bar at '+x+' of '+W);
        }
        """)


if __name__ == '__main__':
    unittest.main()
