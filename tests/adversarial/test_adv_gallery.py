#!/usr/bin/env python3
"""Hostile review of the gallery: the page's DOM-free helpers under node, with hostile numbers.

galleryOf, pageOf, pageLeft, galleryKey, dragMode, pageAfter, nearPages, galleryCount (suda.html, between
`// <pure>` and `// </pure>`). Every test states the CORRECT behaviour: FAIL = a hole. `test_hole_*` failed when
they were written (both are judgments about what a flick is); `test_held_*` are attacks the helpers withstood.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = _paths.APP / 'suda.html'


class AdvGalleryPure(unittest.TestCase):
    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        from test_slack import in_hebrew        # (the page's tests describe the owner's board, which is in Hebrew)
        pure = in_hebrew(PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0])
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    # ── holes (judgments) ────────────────────────────────────────────────────

    def test_hole_a_slip_of_a_few_pixels_counts_as_a_flick(self):
        """A finger counts as moving after 8 px; from there any last sample faster than 0.5 px/ms turns the page.
        A tap whose finger slipped 9 or 12 px is a 'quick flick'. (A pager usually asks for a least distance too.)"""
        self.pure_js(r"""
        assert.strictEqual(pageAfter(2,6,9,360,0.6,true),2,'9 px at 0.6 px/ms turned the page');
        assert.strictEqual(pageAfter(2,6,12,360,3,true),2,'12 px at 3 px/ms turned the page');
        """)

    def test_hole_a_row_pulled_far_and_flicked_back_still_turns(self):
        """He pulled the next picture more than a quarter in, changed his mind and flicked it back: the last movement
        is a fast one the other way, and the page turns all the same."""
        self.pure_js(r"""
        assert.strictEqual(pageAfter(2,6,200,360,-3,true),2,'pulled 200 px onward, flicked back at 3 px/ms: it went onward');
        assert.strictEqual(pageAfter(2,6,-200,360,3,true),2,'the same the other way');
        """)

    # ── held ─────────────────────────────────────────────────────────────────

    def test_held_the_place_of_a_page_and_the_page_of_a_place_agree_at_any_width(self):
        self.pure_js(r"""
        for(const rtl of [true,false])for(const w of [412.5,411.43,392.73,360.5,1280,0.5])for(let i=0;i<300;i++)
          assert.strictEqual(pageOf(pageLeft(i,w,rtl),w,300,rtl),i,JSON.stringify([rtl,w,i]));
        // exactly between two pages: the same answer in both directions of writing, and never a negative zero
        assert.deepStrictEqual([pageOf(180,360,6,false),pageOf(-180,360,6,true),pageOf(540,360,6,false),pageOf(-540,360,6,true)],[1,1,2,2]);
        assert.deepStrictEqual([pageOf(179.99,360,6,false),pageOf(-179.99,360,6,true)],[0,0]);
        assert.ok(!Object.is(pageOf(10,360,6,true),-0)&&!Object.is(pageLeft(0,360,true),-0));
        // a place on the wrong side of the first page (the other browser's sign) is the first page
        assert.deepStrictEqual([pageOf(360,360,6,true),pageOf(-360,360,6,false)],[0,0]);
        // nonsense in, a page of the row out
        for(const left of [Infinity,-Infinity,NaN,null,undefined,'abc',1e300,-1e300])for(const w of [360,412.5,0,-5,NaN,1e-300])for(const rtl of [true,false]){
          const p=pageOf(left,w,6,rtl);assert.ok(Number.isInteger(p)&&p>=0&&p<=5,String([left,w,rtl,p]));
        }
        // the browser gives the width as a whole number while the pages are 411.43 px wide: the page is still
        // read right for any thread one can imagine (the first wrong one is the 479th picture)
        for(let i=0;i<400;i++)assert.strictEqual(pageOf(-(i*411.43),411,2000,true),i);
        """)

    def test_held_one_finger_is_read_the_same_at_the_very_edge_of_a_picture(self):
        self.pure_js(r"""
        const whole={left:0,maxX:0,top:0,maxY:0};
        // a fitted picture: sideways turns the page, up and down is nothing, whatever the angle
        for(let a=0;a<360;a+=3){
          const dx=Math.cos(a*Math.PI/180)*20,dy=Math.sin(a*Math.PI/180)*20,mode=dragMode(dx,dy,whole);
          assert.strictEqual(mode,Math.abs(dx)>=Math.abs(dy)?'page':'',String([a,mode]));
        }
        // an enlarged picture: never 'page' for a finger that goes more up than sideways, never '' at all
        const big={left:120,maxX:300,top:40,maxY:200};
        for(let a=0;a<360;a+=3){
          const dx=Math.cos(a*Math.PI/180)*20,dy=Math.sin(a*Math.PI/180)*20;
          assert.strictEqual(dragMode(dx,dy,big),'pan',String(a));
          assert.notStrictEqual(dragMode(dx,dy,{...big,left:0}),'');assert.notStrictEqual(dragMode(dx,dy,{...big,left:300}),'');
          if(Math.abs(dy)>Math.abs(dx)){assert.strictEqual(dragMode(dx,dy,{...big,left:0}),'pan');assert.strictEqual(dragMode(dx,dy,{...big,left:300}),'pan');}
        }
        // a place a fraction of a pixel from the edge is the edge (a browser cannot always reach the whole number)
        assert.strictEqual(dragMode(30,0,{left:0.4,maxX:300}),'page');assert.strictEqual(dragMode(-30,0,{left:299.6,maxX:300}),'page');
        assert.strictEqual(dragMode(-30,0,{left:300.4,maxX:300}),'page');assert.strictEqual(dragMode(30,0,{left:-0.3,maxX:300}),'page');
        assert.strictEqual(dragMode(30,0,{left:0.6,maxX:300}),'pan');assert.strictEqual(dragMode(-30,0,{left:299.4,maxX:300}),'pan');
        // a picture half a pixel larger than its page is a fitted one
        assert.strictEqual(dragMode(30,4,{left:0,maxX:0.4,top:0,maxY:0.4}),'page');assert.strictEqual(dragMode(4,30,{left:0,maxX:0.4,top:0,maxY:0.5}),'');
        // the arrows read the edge the same way
        assert.strictEqual(galleryKey('pan-left',{left:0.4,max:200},true),'next');assert.strictEqual(galleryKey('pan-right',{left:199.6,max:200},true),'prev');
        assert.strictEqual(galleryKey('pan-right',{left:0,max:0.4},true),'prev');assert.strictEqual(galleryKey('pan-right',{left:0,max:0.4},false),'next');
        for(const odd of ['zoom-in',undefined,null,'','pan','pan-','pan-up','pan-down-page'])assert.strictEqual(galleryKey(odd,{left:0,max:0},true),'pan',String(odd));
        """)

    def test_held_a_lifted_finger_moves_the_row_one_page_at_most_and_never_out_of_it(self):
        self.pure_js(r"""
        const nums=[0,1,-1,8,-8,89,90,90.01,-90.01,120,-120,359,360,5000,-5000,0.0001,NaN,Infinity,-Infinity];
        for(const count of [2,3,6,200])for(let at=0;at<count;at+=Math.max(1,Math.floor(count/7)))for(const dx of nums)for(const width of [360,412.5,0,-1,NaN,Infinity])for(const speed of [0,0.4,0.51,-0.51,9,-9,NaN,Infinity,-Infinity])for(const rtl of [true,false]){
          const to=pageAfter(at,count,dx,width,speed,rtl);
          assert.ok(Number.isInteger(to)&&to>=0&&to<count&&Math.abs(to-at)<=1,JSON.stringify([at,count,dx,width,speed,rtl,to]));
          if(!(width>0)||!dx)assert.strictEqual(to,at);
        }
        // exactly a quarter is not yet 'after a quarter'; a hair more is
        assert.strictEqual(pageAfter(2,6,90,360,0,true),2);assert.strictEqual(pageAfter(2,6,90.01,360,0,true),3);
        // a flick the other way than the finger went in all never turns the page by itself
        assert.strictEqual(pageAfter(2,6,40,360,-9,true),2);assert.strictEqual(pageAfter(2,6,-40,360,9,true),2);
        // the direction: in Hebrew a finger that went right asks for the next picture, in English for the one before
        assert.deepStrictEqual([pageAfter(2,6,120,360,0,true),pageAfter(2,6,120,360,0,false),pageAfter(2,6,-120,360,0,true),pageAfter(2,6,-120,360,0,false)],[3,1,1,3]);
        assert.deepStrictEqual([nearPages(-1,6),nearPages(6,6),nearPages(NaN,6),nearPages(0,0),nearPages(0,1),nearPages(199,200)],[[0],[5],[],[],[0],[198,199]]);
        assert.deepStrictEqual([galleryCount(0,2),galleryCount(199,200)],['1 מתוך 2','200 מתוך 200']);
        """)

    def test_held_the_list_of_pictures_takes_nothing_it_should_not(self):
        self.pure_js(r"""
        const P=(file,caption,w,h)=>({file:'uploads/a/'+file,name:file,caption,w,h,bytes:9});
        // a file of another thread, a path that climbs out, a kind that is not a picture: none of them is shown
        assert.deepStrictEqual(galleryOf([{id:'m1',images:[{file:'uploads/b/m1-1.png',name:'x'}]},{id:'m2',images:[{file:'uploads/a/../b/m1-1.png'}]},{id:'m3',images:[{file:'uploads/a/m3-1.svg'}]},{id:'m4',images:[{file:'https://evil.example/m4-1.png'}]}],'a'),[]);
        // nonsense in the state
        for(const bad of [null,undefined,'x',5,{},[null,1,'s',{images:{}},{images:[1,'x',null,[]]},{images:'uploads/a/m1-1.png'}]])assert.deepStrictEqual(galleryOf(bad,'a'),[]);
        // his own pictures still on their way come last, under the address this tab made for them
        const mine=galleryOf([{id:'m1',images:[P('m1-1.png','שרת')]},{cid:'c1',images:[{url:'blob:http://x/1',data:'AAAA',name:'a.png',caption:' שלי '},{url:'blob:http://x/2',data:'AAAA',name:'b.png'}]}],'a');
        assert.deepStrictEqual(mine.map(x=>[x.src.split('/').pop(),x.title,x.mid]),[['m1-1.png','שרת','m1'],['1','שלי',''],['2','b.png','']]);
        // the same picture twice in one message (a carousel may show it twice) is one page
        assert.strictEqual(galleryOf([{id:'m1',images:[P('m1-1.png','א'),P('m1-1.png','ב')]}],'a').length,1);
        // 20,000 pictures are listed at once, in their order
        const big=[];for(let i=0;i<5000;i++)big.push({id:'m'+i,images:[1,2,3,4].map(n=>P('m'+i+'-'+n+'.png',''))});
        const t=Date.now(),all=galleryOf(big,'a');
        assert.strictEqual(all.length,20000);assert.ok(Date.now()-t<1500);
        assert.deepStrictEqual([all[0].src,all[19999].src],['uploads/a/m0-1.png','uploads/a/m4999-4.png']);
        """)


if __name__ == '__main__':
    unittest.main()
