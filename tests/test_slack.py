#!/usr/bin/env python3
"""Tests for suda.html (Suda), the Slack-like front end of the threads board.

The page keeps its DOM-free logic between `// <pure>` and `// </pure>`; that
part runs here under node. What needs a browser (layout, sending, the phone
navigation) is checked by hand with agent-browser.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'      # the page; slack.html is its old address and only redirects



def he_table():
    """The Hebrew table as `threads install` writes it for an installation in Hebrew (locales/he.json and its parts):
    the page's tests describe the owner's own board, which is in Hebrew."""
    import glob
    table = {}
    for name in [str(ROOT / 'locales/he.json')] + sorted(n for n in glob.glob(str(ROOT / 'locales/he.*.json')) if not n.endswith('he.cli.json')):
        try:
            table.update(json.loads(Path(name).read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
    return {k: v for k, v in table.items() if not k.startswith('_')}


def in_hebrew(pure):
    return pure.replace("var LANG='en',L10N={};", "var LANG='he',L10N=" + json.dumps(he_table(), ensure_ascii=False) + ";", 1)

class SlackPageTests(unittest.TestCase):
    def page(self):
        return PAGE.read_text(encoding='utf-8')

    def node(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        return node

    def pure_js(self, script):
        """Run the page's DOM-free logic under node, in UTC so clock times are fixed."""
        pure = in_hebrew(self.page().split('// <pure>')[1].split('// </pure>')[0])
        r = subprocess.run([self.node(), '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr)

    # ── the file as a whole ────────────────────────────────────────────────

    def test_every_word_of_the_pages_second_half_has_his_hebrew(self):
        """The page speaks English; his installation is Hebrew. Every tr('...') of the script from the pictures of a
        thread on (galleryFor to the end) is in the Hebrew table, with the same {names}, and the words the source
        used to hold in Hebrew come out exactly as they did."""
        page = self.page()
        tail = page[page.index('function galleryFor(of,src){'):]
        table = he_table()
        said = set()
        for m in re.finditer(r"\btr\('((?:[^'\\]|\\.)*)'", tail):
            said.add(json.loads('"' + m.group(1).replace('"', '\\"').replace("\\'", "'") + '"'))
        self.assertGreater(len(said), 300)
        missing = sorted(text for text in said if text not in table)
        self.assertEqual(missing, [], 'English words with no Hebrew in locales/he.*.json')
        for text in said:
            self.assertEqual(sorted(set(re.findall(r'\{(\w+)\}', text))), sorted(set(re.findall(r'\{(\w+)\}', table[text]))), text)
        for english, hebrew in (('The picture did not load · Try again', 'התמונה לא נטענה · נסה שוב'), ('Try now', 'נסה עכשיו'), ('Try again', 'נסה שוב'),
                                ('▶ Run the command from message {id}', '▶ הרץ את הפקודה מהודעה {id}'), ('Paste a picture from the clipboard', 'הדבקת תמונה מהלוח'),
                                ('Microphone for recording', 'מיקרופון להקלטה'), ('Split into a new topic', 'פצל לנושא חדש'), ('Split into the topic: {id}', 'פוצל לנושא: {id}'),
                                ('Stop reading aloud', 'עצור את ההקראה'), ('Read aloud', 'הקרא בקול'), ('Reading: {text}', 'מקריא: {text}'), ('Stop', 'עצור'),
                                ('Open this topic there', 'פתח את הנושא הזה שם'), ('Go there', 'עבור לשם'),
                                ('The browser allows notifications only from a secure address (https).', 'הדפדפן מתיר התראות רק מכתובת מאובטחת (https).'),
                                ('Appearance', 'מראה'), ('Appearance: {label}', 'מראה: {label}'), ('Picture {n}', 'תמונה {n}'),
                                ('Quick answer to the open question (when there are several: the newest of them)', 'תשובה מהירה לשאלה הפתוחה (כשיש כמה: לחדשה מביניהן)'),
                                ('Recommended', 'מומלץ'), ('No line wrap', 'בלי גלישת שורות'),
                                ('A picture or diagram full screen: zoom in / zoom out / fit the screen / full size. The arrows move it (with Shift: a page), the wheel with {key} zooms, a double click zooms in, Esc closes',
                                 'תמונה או דיאגרמה במסך מלא: הגדלה / הקטנה / התאמה למסך / גודל מלא. החיצים מזיזים (עם Shift: עמוד), גלגלת עם {key} מגדילה, לחיצה כפולה מקרבת, Esc סוגר')):
            self.assertEqual(table.get(english), hebrew, english)
        # the pages' table, locales/he.json: one pair a line, not escaped, in order
        own = (ROOT / 'locales/he.json').read_text(encoding='utf-8')
        pairs = json.loads(own)
        self.assertEqual(list(pairs), sorted(pairs))
        self.assertNotIn('\\u05', own)

    def test_no_two_functions_share_a_name(self):
        """Two top-level functions with one name: the later one wins in silence. closeTopic was both the thread's
        close and the new-topic dialog's, so C, the details button and the palette closed no thread."""
        import collections
        names = collections.Counter(re.findall(r'^function\s+(\w+)\s*\(', self.page(), re.M))
        self.assertEqual([n for n, k in names.items() if k > 1], [])

    def test_the_style_sheet_has_no_stray_brace(self):
        """The owner, suda m436 ("the HTML is limited again, and broken"): a stray "}" left by folding an @media block
        onto one line made the browser drop the rule after it, `.canvas iframe{display:block;width:100%...}`,
        so an agent's page in a message was drawn 300 px wide. Every brace of the style sheet closes one it opened."""
        page = self.page()
        css = re.sub(r'/\*.*?\*/', '', page[page.index('>', page.index('<style')) + 1:page.index('</style>')], flags=re.S)
        depth = 0
        for n, line in enumerate(css.split('\n'), 1):
            for ch in line:
                depth += {'{': 1, '}': -1}.get(ch, 0)
                self.assertGreaterEqual(depth, 0, 'a "}" that closes nothing, at line %d of the style sheet: %r' % (n, line[:80]))
        self.assertEqual(depth, 0)
        self.assertIn('.canvas iframe{display:block;width:100%', css)

    def test_the_page_names_the_owner_as_the_installation_says(self):
        """The page names nobody: it ships calling him "Me" ("אני" in Hebrew), and `threads install` writes the installation's
        owner_name (config.json). Whatever the name holds, the script still parses and the name is only text."""
        import json
        import sys
        import tempfile
        self.node()
        self.pure_js(r"""
        assert.strictEqual(OWNER_NAME,'Me');assert.strictEqual(whoName('owner'),'אני');
        assert.strictEqual(mineTask({status:'todo',owner:'owner'}),true);assert.strictEqual(mineTask({status:'on-owner',owner:'fork'}),true);
        assert.strictEqual(shownStatus({status:'todo',owner:'Owner'}),'on-owner');assert.strictEqual(mineTask({status:'todo',owner:'dana'}),false);
        """)
        with tempfile.TemporaryDirectory(prefix='.threads-test-', dir=ROOT) as tmp:
            private = Path(tmp) / '.threads-config/threads'
            private.mkdir(parents=True)
            name = 'דנה</script><script>alert(1)//'
            (private / 'config.json').write_text(json.dumps({'owner_name': name, 'lang': 'he'}), encoding='utf-8')
            r = subprocess.run([sys.executable, str(ROOT / 'threads.py'), 'install'], capture_output=True, text=True,
                               env={**os.environ, 'BOARDS_DIR': str(Path(tmp) / 'boards'), 'THREADS_NOTIFY': '0'})
            self.assertEqual(r.returncode, 0, r.stderr)
            for page in ('suda.html',):
                check = ("const s=require('fs').readFileSync(process.argv[1],'utf8')"
                         ".match(/<script>([\\s\\S]*?)<\\/script>/)[1];new Function(s)")
                done = subprocess.run([self.node(), '-e', check, str(Path(tmp) / 'boards/threads' / page)], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, page + done.stderr)
            installed = (Path(tmp) / 'boards/threads/suda.html').read_text(encoding='utf-8')
            pure = installed.split('// <pure>')[1].split('// </pure>')[0]
            done = subprocess.run([self.node(), '-e', "'use strict';\nconst assert=require('assert');\n" + pure
                                   + '\nassert.strictEqual(whoName("owner"),process.argv[1]);assert.strictEqual(whoName("tower"),"מגדל");', name],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_script_parses(self):
        check = ("const s=require('fs').readFileSync(process.argv[1],'utf8')"
                 ".match(/<script>([\\s\\S]*?)<\\/script>/)[1];new Function(s)")
        r = subprocess.run([self.node(), '-e', check, str(PAGE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_picture_that_did_not_load_says_so_and_is_asked_for_again(self):
        """The owner, thread suda m404: "the picture on the right did not load, I do not know why". A picture whose
        download failed stayed an empty place for as long as the page lived. Now its place holds a tile that says
        so; the page asks for it twice more by itself, then at his press on the tile, and at once when the line is
        back (the server's line opened, the browser is online, he is on the page again)."""
        page = self.page()
        for part in ("const watch=watchPicture(img,small,frame,open,shown.length===1?pic:null),fit=shown.length>1;", "if(watch.failed()){if(pic.thumb){seePicture(pic.src);fullWanted.add(pic.src);watch.from(pic.src);if(hd)hd.remove();}watch.again();}else{seePicture(pic.src);openReader(",
                     "if(tries<PIC_TRIES.length)timer=setTimeout(again,PIC_TRIES[tries]);", "tile=el('span','shot-retry',tr('The picture did not load · Try again'));",
                     "function askMissingPics(){for(const again of [...missingPics])again();}", ".failed>img,.failed>.shot-open>img{display:none}"):
            self.assertIn(part, page)
        self.pure_js(r"""
        // asked again at the same file, with a mark that makes the browser really ask; a picture that lives only in this browser keeps its address
        assert.strictEqual(retrySrc('uploads/a/m1-1.png',1),'uploads/a/m1-1.png?again=1');assert.strictEqual(retrySrc('uploads/a/m1-1.png?v=2',3),'uploads/a/m1-1.png?v=2&again=3');
        assert.strictEqual(retrySrc('uploads/a/m1-1.png#x',2),'uploads/a/m1-1.png?again=2');
        assert.strictEqual(retrySrc('blob:https://x/abc',2),'blob:https://x/abc');assert.strictEqual(retrySrc('data:image/png;base64,AAA',2),'data:image/png;base64,AAA');
        // twice by itself, within a few seconds; then it is his press, or the line coming back
        assert.strictEqual(PIC_TRIES.length,2);assert.ok(PIC_TRIES.every(ms=>ms>=1000)&&PIC_TRIES.reduce((a,b)=>a+b,0)<=8000);
        """)

    def test_the_pictures_of_a_thread_open_as_a_gallery(self):
        """The owner, thread suda m395: "when you send pictures I always want to be able to move between them by
        scrolling; but mind that scrolling is not mixed up with the state in which I enlarge and move with my
        finger". A picture opens among all the pictures of its thread: a row of pages that the browser itself
        scrolls and stops on (one finger), each page holding its own picture, which the browser scrolls inside
        its page once it is larger than the page. So a finger moves the enlarged picture until its edge, and
        only then the row. Two fingers enlarge, and while they are down the row does not move.
        (The fingers are the page's own to read: left to the browser, two fingers on an enlarged picture were
        taken as a scroll and the pinch died. A mouse wheel and a trackpad still scroll as the browser does.)"""
        page = self.page()
        for part in ("gallery:galleryFor(t,pic.src)", "if(r.image&&r.photo&&r.gallery){", "const step=galleryKey(action,{left:pane.scrollLeft,max:pane.scrollWidth-pane.clientWidth},rtl);",
                     ".pager{", "scroll-snap-type:x mandatory", "overscroll-behavior-x:auto", ".pager .pic-pane{box-sizing:border-box;height:100%;padding:12px;overflow:auto;direction:ltr;text-align:center;cursor:grab;touch-action:none;",
                     "const mode=dragMode(dx,dy,owner.room());",
                     "moveTo(taken?at:pageAfter(at,list.length,dx,width(),speed,rtl),!calm)", "whole(){if(scale<fitOf()||",
                     "if(readerGallery&&action.startsWith('pan-'))readerGallery.key(action);"):
            self.assertIn(part, page)
        self.pure_js(r"""
        // every picture of the thread, in the order of its messages, each once
        const P=(file,caption,w,h)=>({file:'uploads/a/'+file,name:file,caption,w,h,bytes:9});
        const msgs=[{id:'m1',from:'fork',images:[P('m1-1.png','ראשונה',640,400)]},{id:'m2',from:'owner',text:'בלי תמונה'},
          {id:'m3',from:'fork',images:[P('m3-1.png','',300,900),P('m3-2.png','שלישית',1600,500)]},{id:'m4',from:'fork',images:'x'},{id:'m5',from:'fork',images:[P('m1-1.png','שוב',640,400),null]}];
        const list=galleryOf(msgs,'a');
        assert.deepStrictEqual(list.map(x=>[x.mid,x.src.split('/').pop(),x.title]),[['m1','m1-1.png','ראשונה'],['m3','m3-1.png','m3-1.png'],['m3','m3-2.png','שלישית']]);
        assert.deepStrictEqual([list[2].w,list[2].h,list[2].name],[1600,500,'m3-2.png']);
        assert.deepStrictEqual(galleryOf([],'a'),[]);assert.deepStrictEqual(galleryOf([{id:'m1'}],'a'),[]);
        // which page is on the screen. In Hebrew the first page is at the right and the row's place counts down from 0.
        assert.strictEqual(pageOf(0,360,6,true),0);assert.strictEqual(pageOf(-360,360,6,true),1);assert.strictEqual(pageOf(-899,360,6,true),2);assert.strictEqual(pageOf(-5000,360,6,true),5);
        assert.strictEqual(pageOf(720,360,6,false),2);assert.strictEqual(pageOf(-10,360,6,false),0);assert.strictEqual(pageOf(100,0,6,true),0);assert.strictEqual(pageOf(NaN,360,0,true),0);
        assert.strictEqual(pageLeft(2,360,true),-720);assert.strictEqual(pageLeft(2,360,false),720);assert.strictEqual(pageLeft(0,360,true),0);
        for(const rtl of [true,false])for(let i=0;i<6;i++)assert.strictEqual(pageOf(pageLeft(i,412,rtl),412,6,rtl),i);
        // an arrow moves over a picture that is larger than its page, and turns the page where the picture ends
        // (or does not move at all). Onward is to the left in Hebrew, to the right in English.
        const fit={left:0,max:0},mid={left:50,max:200},atLeft={left:0,max:200},atRight={left:200,max:200};
        assert.strictEqual(galleryKey('pan-left',fit,true),'next');assert.strictEqual(galleryKey('pan-right',fit,true),'prev');
        assert.strictEqual(galleryKey('pan-left',fit,false),'prev');assert.strictEqual(galleryKey('pan-right',fit,false),'next');
        assert.strictEqual(galleryKey('pan-left',mid,true),'pan');assert.strictEqual(galleryKey('pan-right',mid,true),'pan');
        assert.strictEqual(galleryKey('pan-left',atLeft,true),'next');assert.strictEqual(galleryKey('pan-right',atLeft,true),'pan');
        assert.strictEqual(galleryKey('pan-right',atRight,true),'prev');assert.strictEqual(galleryKey('pan-left',atRight,true),'pan');
        assert.strictEqual(galleryKey('pan-left-page',fit,true),'next');
        for(const up of ['pan-up','pan-down','pan-up-page'])assert.strictEqual(galleryKey(up,fit,true),'pan');
        // only the picture on the screen and the ones beside it are loaded
        assert.deepStrictEqual(nearPages(0,6),[0,1]);assert.deepStrictEqual(nearPages(3,6),[2,3,4]);assert.deepStrictEqual(nearPages(5,6),[4,5]);assert.deepStrictEqual(nearPages(0,1),[0]);
        assert.strictEqual(galleryCount(2,6),'3 מתוך 6');
        // What one finger that started to move is doing. Over a picture that fits its page: sideways it turns the
        // page, up and down it does nothing. Over an enlarged picture it moves the picture, and turns the page
        // only when the picture has nowhere left to go that way. (dx > 0: the finger moves right, and the
        // picture with it, so there must be more of the picture to its left.)
        const whole={left:0,maxX:0,top:0,maxY:0},big={left:100,maxX:300,top:50,maxY:200},bigL={left:0,maxX:300,top:50,maxY:200},bigR={left:300,maxX:300,top:50,maxY:200};
        assert.strictEqual(dragMode(30,4,whole),'page');assert.strictEqual(dragMode(-30,4,whole),'page');assert.strictEqual(dragMode(3,30,whole),'');assert.strictEqual(dragMode(3,-30,whole),'');
        assert.strictEqual(dragMode(30,4,big),'pan');assert.strictEqual(dragMode(-30,4,big),'pan');assert.strictEqual(dragMode(4,30,big),'pan');assert.strictEqual(dragMode(4,-30,big),'pan');
        assert.strictEqual(dragMode(30,4,bigL),'page','at its left edge a finger that pulls right turns the page');assert.strictEqual(dragMode(-30,4,bigL),'pan');
        assert.strictEqual(dragMode(-30,4,bigR),'page');assert.strictEqual(dragMode(30,4,bigR),'pan');
        assert.strictEqual(dragMode(4,30,bigL),'pan','up and down never turn the page');
        assert.strictEqual(dragMode(20,4,{left:0,maxX:0,top:40,maxY:300}),'page','a tall picture: sideways there is nowhere to go');
        // where the row comes to rest when the finger is lifted: the next page after a quarter of the width or a
        // quick flick, the same page otherwise. In Hebrew a finger that moved right asks for the next one.
        assert.strictEqual(pageAfter(2,6,120,360,0,true),3);assert.strictEqual(pageAfter(2,6,-120,360,0,true),1);assert.strictEqual(pageAfter(2,6,120,360,0,false),1);assert.strictEqual(pageAfter(2,6,-120,360,0,false),3);
        assert.strictEqual(pageAfter(2,6,60,360,0,true),2,'a short pull goes back');assert.strictEqual(pageAfter(2,6,40,360,0.9,true),3,'a flick turns it');assert.strictEqual(pageAfter(2,6,40,360,-0.9,true),2,'a flick the other way does not');
        assert.strictEqual(pageAfter(5,6,300,360,2,true),5);assert.strictEqual(pageAfter(0,6,-300,360,-2,true),0);assert.strictEqual(pageAfter(2,6,0,360,0,true),2);assert.strictEqual(pageAfter(2,6,500,0,0,true),2);
        """)

    def test_while_he_records_the_voice_is_drawn_as_it_is_heard(self):
        """The owner, thread suda m377: "like WhatsApp: beside the meter of the level, the history of the wave of the
        voice, to see the sound waves being built in real time". A row of bars beside the meter: one bar for every
        short stretch of time (its loudest moment), the newest at the edge where the writing goes on, the older
        ones sliding away from it. A fixed number of bars is kept, however long he records."""
        page = self.page()
        for part in ('<canvas id="rec-wave" class="rec-wave" aria-hidden="true"></canvas>', "const level=waveLevel(wave),at=performance.now(),whole=waveStep(me.wave,level,at);",
                     "for(const [x,y,bw,bh] of waveRects(wave.bars,wave.peak,calm?1:(at-wave.last)/WAVE_EVERY,w,h,box.rtl))pen.fillRect(x,y,bw,bh);",
                     "me.wave={bars:[],peak:0,last:0};", "cancelAnimationFrame(me.frame);", ".rec-wave{",
                     # the hostile review: the meter outlives a picture that cannot be drawn; the picture follows the screen and the theme; one end for one recording
                     "if(paint)try{paint(at,whole);}catch{}", "const pen=canvas.getContext('2d');if(!pen)return null;", "if(w!==box.w||h!==box.h||dense!==box.dense){",
                     "if(me.over)return;me.over=true;", "else if(!me.stopping)closeRec(me);", ".rec.full .rec-level,.rec.full .rec-wave{display:none}"):
            self.assertIn(part, page)
        self.assertEqual(page.count('requestAnimationFrame(draw)'), 1)          # one loop for the meter and the wave
        self.pure_js(r"""
        // how loud a moment is: nothing, half, and as loud as the meter shows
        const tone=(n,swing)=>Uint8Array.from({length:n},(_,i)=>128+(i%2?swing:-swing));
        assert.strictEqual(waveLevel(tone(256,0)),0);assert.strictEqual(waveLevel(tone(256,20)),0.5);assert.strictEqual(waveLevel(tone(256,40)),1);assert.strictEqual(waveLevel(tone(256,90)),1);
        assert.strictEqual(waveLevel([]),0);
        // one bar for every stretch of time, as high as its loudest moment
        const w={bars:[],peak:0,last:0};
        assert.strictEqual(waveStep(w,0.2,1000),false);assert.deepStrictEqual([w.bars,w.peak,w.last],[[],0.2,1000],'the first moment only starts the clock');
        assert.strictEqual(waveStep(w,0.7,1000+WAVE_EVERY-1),false);assert.strictEqual(waveStep(w,0.4,1000+WAVE_EVERY),true);
        assert.deepStrictEqual([w.bars,w.peak,w.last],[[0.7],0,1000+WAVE_EVERY]);
        assert.strictEqual(waveStep(w,0.1,1000+2*WAVE_EVERY),true);assert.deepStrictEqual(w.bars,[0.7,0.1]);
        // a page that slept (the tab was hidden) adds one bar for the gap, not one for every stretch it missed
        assert.strictEqual(waveStep(w,0.3,1000+50*WAVE_EVERY),true);assert.strictEqual(w.bars.length,3);
        // however long he records, a fixed number of bars is kept: the oldest go
        for(let i=0;i<WAVE_MAX+50;i++)waveStep(w,i/1000,2000000+i*WAVE_EVERY);
        assert.strictEqual(w.bars.length,WAVE_MAX);assert.ok(WAVE_MAX<=600&&WAVE_MAX*(WAVE_BAR+WAVE_GAP)>=1100,'enough for the widest bar, and no more');
        for(const junk of [NaN,-1,7,'x',undefined]){const k={bars:[],peak:0,last:1};waveStep(k,junk,1+WAVE_EVERY);assert.ok(k.bars[0]>=0&&k.bars[0]<=1,String(junk));}
        // where the bars stand. The newest is at the edge where the writing goes on (right in English, left in
        // Hebrew); the ones before it stand a step apart, and slide away from the edge until the next bar is whole.
        const slot=WAVE_BAR+WAVE_GAP,W=100,H=28;
        let ltr=waveRects([0.5,1],0.25,0,W,H,false);
        assert.deepStrictEqual(ltr.map(r=>r[0]),[W-WAVE_BAR,W-WAVE_BAR,W-WAVE_BAR-slot],'the one being heard now, the last whole one in its place, the one before it a step away');
        assert.deepStrictEqual(ltr.map(r=>r[3]),[Math.max(2,Math.round(0.25*H)),H,Math.round(0.5*H)]);
        for(const [x,y,w_,h] of ltr){assert.strictEqual(w_,WAVE_BAR);assert.strictEqual(y,(H-h)/2,'a bar stands on the middle line');}
        ltr=waveRects([0.5,1],0,0.5,W,H,false);
        assert.deepStrictEqual(ltr.map(r=>r[0]),[W-WAVE_BAR,W-WAVE_BAR-0.5*slot,W-WAVE_BAR-1.5*slot],'half way to the next bar: half a step away');
        const rtl=waveRects([0.5,1],0.25,0.5,W,H,true);
        assert.deepStrictEqual(rtl.map(r=>r[0]),[0,0.5*slot,1.5*slot],'in Hebrew the same picture from the other side');
        // silence is a line of dots, never nothing; only what fits is drawn, however long the history
        assert.deepStrictEqual(waveRects([0,0],0,0,W,H,false).map(r=>r[3]),[2,2,2]);
        const many=waveRects(Array.from({length:500},()=>0.5),0.5,0.3,W,H,false);
        assert.ok(many.length<=Math.ceil(W/slot)+2,String(many.length));
        for(const [x] of many)assert.ok(x>-WAVE_BAR&&x<W,'a bar outside the picture: '+x);
        assert.deepStrictEqual(waveRects([],0,0,0,H,false),[]);assert.deepStrictEqual(waveRects([0.5],0.5,0,W,0,false),[]);
        // the way to the next bar is never less than nothing or more than a step
        assert.deepStrictEqual(waveRects([1],0,-0.4,W,H,false).map(r=>r[0]),[W-WAVE_BAR,W-WAVE_BAR]);assert.deepStrictEqual(waveRects([1],0,7,W,H,false).map(r=>r[0]),[W-WAVE_BAR,W-WAVE_BAR-slot]);
        // where he asked for less motion the whole bars stand a step from the edge: the one being heard is never behind one of them
        assert.deepStrictEqual(waveRects([0.5,1],0.1,1,W,H,true).map(r=>r[0]),[0,slot,2*slot]);
        """)

    def test_a_message_that_did_not_get_through_goes_again_by_itself(self):
        """The owner, thread suda m332: "several times in the last hour I sent a message, it was not sent, and I had
        to try again". On his phone Snap takes the page's renderer away the moment the screen goes dark (the
        phone's log: power key, 0.3 s later "parked: renderer released"), and a send on its way is cut. The page
        showed "not sent" and waited for his press. Now a try that got no answer is tried again by the page; the
        server's own refusal stays his to decide; every try carries the same cid, so the server stores one."""
        page = self.page()
        for part in ("going=post(state,false,{first:!msg.tries,progress:sentSoFar(msg)});\n  }catch(e){going=Promise.reject(e);}\n  try{persistOutbox();}catch{}\n  try{render();}catch{}\n  try{\n    const receipt=await going;", "keepalive:!!leaving||(small&&!!care.first)",
                     "const body=JSON.stringify({board:slug,state},(key,value)=>wellFormed(value)),bytes=care?utf8Bytes(body):0,small=!!care&&bytes<=SEND_SMALL;",
                     "timer=care&&stop?setTimeout(()=>stop.abort(),sendLimit(bytes)):0;",
                     "if(fault)throw Object.assign(Error(typeof receipt.error==='string'?receipt.error:''),{again:fault==='again',heard:status>0,said:true});",
                     "if(e&&e.again&&retries(msg,now())){msg.tries=(msg.tries||0)+1;msg.delivery='waiting';msg.due=Date.now()+retryIn(msg.tries);}",
                     "else{msg.delivery='failed';msg.final=true;msg.error=reason(e)||(e&&e.heard?tr('The server did not accept the message. It is kept here'):tr('No answer from the server. The message is kept here'));}",
                     "msg.inFlight=true;msg.auto=true;msg.delivery='sending';", "if(m.delivery==='waiting'||m.inFlight)break;", "msg.delivery='waiting';msg.auto=true;msg.due=0;", "if(m.delivery==='received')open=true;", "msg.delivery='holding';msg.auto=true;persistOutbox();", "for(const list of optimistic.values())for(const m of list)if(m.held&&m.go)m.go();",
                     "const back=unsentAtLoad(m,now());", "events.onopen=()=>{beatAt=null;numbered=false;lineFails=0;const back=everOpen;everOpen=true;connection(true);if(back)lineBack();checkBuild(BUILD_SOON);sendAgain(true);askMissingPics();};",
                     "addEventListener('online',()=>{inDoubt();paintFresh();lineBack();listen();refresh();sendAgain(true);askMissingPics();});", "awayNews=false;listen();refresh();checkBuild(BUILD_SOON);sendAgain(true);askMissingPics();",
                     "trayBack=true;sendAgain(true);", "if(answers||lateFor)holdThenSend(t.id,msg);else dispatch(t.id,msg);",
                     "if(m.delivery==='waiting'&&!m.inFlight&&m.behind!=='failed'&&m.behind!=='holding')line.append(button(tr('Try now'),'text-btn',()=>sendAgain(true)));",
                     "if(m.delivery==='failed'&&!lostPart(m))line.append(button(tr('Try again'),'text-btn',()=>dispatch(t.id,m)));",
                     # the hostile review: his order, another tab's delete, the form of what is sent, a message the server cannot take
                     "if(m.inFlight||m.delivery==='sending')break;", "if(lostPart(m)&&!trayBack)break;", "if(msg.auto&&leftOutbox(msg)){letGo(id,msg);render();planAgain();return;}",
                     "else if(e.key===PREFIX+'slack-outbox')outboxChanged(e.newValue);", "const autoReady=()=>loaded&&(synced||Date.now()>=bootAt+RESTORE_WAIT);",
                     "if(m.delivery!=='holding'&&!m.inFlight&&t&&t.messages.some(x=>x.cid&&x.cid===m.cid)){letGo(id,m);persistOutbox();render();continue;}", "if(readsOk===was||msg.delivery!=='waiting'||!(optimistic.get(id)||[]).includes(msg))return;",
                     "setTimeout(()=>{if(!trayBack)restoreTray();},6000);", "    dispatch(t.id,msg);\n  };", "newLine.ts=null;dispatch(t.id,msg);"):
            self.assertIn(part, page)
        self.assertEqual(page.count("fetch('/api/state"), 1)             # every page action goes through the one place that says how it ended
        self.pure_js(r"""
        const OK={ok:true,applied:true},R={ok:true,thread:'a',msg_id:'m1'};
        // what a POST came to
        assert.strictEqual(postFault(200,OK,R),'');
        for(const status of [0,408,425,429,500,502,503,504])assert.strictEqual(postFault(status,OK,R),'again','status '+status);
        for(const status of [400,403,404,413])assert.strictEqual(postFault(status,null,{}),'no','status '+status);
        assert.strictEqual(postFault(200,null,{}),'again','an answer that is not the board server\'s (a gateway\'s page)');
        assert.strictEqual(postFault(200,{},{}),'again');
        assert.strictEqual(postFault(200,{ok:false,applied:false,code:1},{ok:false,error:'השרשור סגור'}),'no','the server refused, with its reason');
        assert.strictEqual(postFault(200,{ok:false,applied:false,code:1},{ok:false,error:'לא ניתן לקרוא או לשמור את ההודעה',again:true}),'again','the server could not just now (its lock was not free)');
        assert.strictEqual(postFault(200,{ok:false,applied:false,code:1},{ok:false,error:'לא ניתן לקרוא או לשמור את ההודעה'}),'no','a request the server cannot read: not again');
        assert.strictEqual(postFault(200,{ok:false,applied:false,code:1},{}),'no','a hook that broke says nothing: his to send again');
        assert.strictEqual(postFault(200,{ok:true,applied:false},{}),'no','a board with no hook');
        assert.strictEqual(postFault(200,OK,{ok:false,error:'x'}),'no');
        // the waits between tries grow, then stay
        assert.deepStrictEqual([0,1,2,3,4,5,6,40].map(retryIn),[1500,1500,4000,10000,20000,30000,30000,30000]);
        // the page sends by itself what he wrote in the last half day, unless the server keeps saying it cannot
        const at=1000000;
        assert.strictEqual(retries({ts:at-5},at),true);assert.strictEqual(retries({ts:at-RETRY_FOR+1},at),true);assert.strictEqual(retries({ts:at-RETRY_FOR},at),false);
        assert.strictEqual(retries({ts:at,heard:RETRY_HEARD-1},at),true);assert.strictEqual(retries({ts:at,heard:RETRY_HEARD},at),false);
        assert.strictEqual(retries({ts:'x'},at),false);assert.strictEqual(retries({},at),false);
        // a press on "run" asks the tower to run a command on the Mac: minutes later it is his to press again
        assert.strictEqual(retries({ts:at-RETRY_RUN_FOR+1,run:{msg_id:'m1'}},at),true);assert.strictEqual(retries({ts:at-RETRY_RUN_FOR,run:{msg_id:'m1'}},at),false);
        assert.ok(RETRY_RUN_FOR<=900);
        // a message that alone gets no answer while the server answers everything else is not tried without end
        assert.strictEqual(retries({ts:at,deaf:RETRY_DEAF-1},at),true);assert.strictEqual(retries({ts:at,deaf:RETRY_DEAF},at),false);
        // a message found in the browser's store at a load
        const M=(delivery,extra)=>Object.assign({cid:'c1',from:'owner',text:'שלום',ts:at-10,delivery,inFlight:true,due:99},extra);
        // it was on its way, or between tries, when the page went away: nobody knows whether it arrived, so it goes again
        for(const was of ['sending','waiting'])
          assert.deepStrictEqual(unsentAtLoad(M(was,{auto:true,tries:4,heard:5,error:''}),at),
            {cid:'c1',from:'owner',text:'שלום',ts:at-10,delivery:'waiting',inFlight:false,due:0,auto:true,tries:0,heard:0,deaf:0,final:false,error:''},was);
        // what a page from before this change left (it never marked a message as the page's to send again) was shown
        // to him as "not sent": he may have written it again since, so it stays his, whatever it says
        for(const was of ['sending','failed','waiting'])
          assert.deepStrictEqual(unsentAtLoad(M(was,{error:'אין תשובה מהשרת. ההודעה שמורה כאן'}),at),
            {cid:'c1',from:'owner',text:'שלום',ts:at-10,delivery:'failed',inFlight:false,due:0,final:true,error:'אין תשובה מהשרת. ההודעה שמורה כאן'},was);
        assert.strictEqual(unsentAtLoad(M('sending'),at).error,UNSURE);
        // an answer he chose with one press, inside its four seconds: leaving the page sends it at once, and a page
        // that was taken away had no chance to, so it goes when the page is back (never one an older page left)
        assert.deepStrictEqual(unsentAtLoad(M('holding',{auto:true,held:7,answers:'m3'}),at),
          {cid:'c1',from:'owner',text:'שלום',ts:at-10,delivery:'waiting',inFlight:false,due:0,held:0,auto:true,answers:'m3',tries:0,heard:0,deaf:0,final:false,error:''});
        // an entry with no time (a damaged store) is drawn with this moment and is never the page's to send; a
        // "run" pressed long ago is his to press again
        for(const ts of [undefined,null,'x',NaN]){const back=unsentAtLoad(M('sending',{auto:true,ts}),at);assert.deepStrictEqual([back.ts,back.delivery,back.final],[at,'failed',true],String(ts));}
        assert.strictEqual(unsentAtLoad(M('sending',{auto:true,ts:at-RETRY_RUN_FOR-1,run:{msg_id:'m1'}}),at).delivery,'failed');
        assert.strictEqual(unsentAtLoad(M('sending',{auto:true,ts:at-RETRY_RUN_FOR+5,run:{msg_id:'m1'}}),at).delivery,'waiting');
        assert.deepStrictEqual(unsentAtLoad(M('holding',{held:7}),at),{cid:'c1',from:'owner',text:'שלום',ts:at-10,delivery:'failed',inFlight:false,due:0,held:0,final:true,error:UNSURE});
        // the messages of a thread go one after another, in his order: only the first that is not with the server
        // yet says when the next try is; one on its way, and one whose pictures are still coming back from the
        // device's store, hold everything behind them
        const W=(due,extra)=>Object.assign({delivery:'waiting',due},extra);
        assert.strictEqual(headDue([W(900),W(100)],true),900);assert.strictEqual(headDue([{delivery:'received'},{delivery:'failed',run:{msg_id:'m1'}},W(300),W(0)],true),300);assert.strictEqual(headDue([{delivery:'failed'},W(300)],true),Infinity,'a failed one holds what came after it (suda-fixes 54)');assert.strictEqual(headDue([{delivery:'holding'},W(300)],true),Infinity,'and so does an answer inside its undo');
        assert.strictEqual(headDue([W(0)],true),0);assert.strictEqual(headDue([],true),Infinity);assert.strictEqual(headDue([{delivery:'failed'}],true),Infinity);
        assert.strictEqual(headDue([{delivery:'sending',inFlight:true},W(0)],true),Infinity,'one on its way: the next look is when it lands');
        assert.strictEqual(headDue([W(5,{inFlight:true}),W(0)],true),Infinity);
        const pic=W(0,{images:[{name:'a',lost:true}]});
        assert.strictEqual(headDue([pic,W(0)],false),Infinity,'its pictures are not back: the words written after it do not pass it');assert.strictEqual(headDue([pic,W(0)],true),0);
        assert.strictEqual(headDue([W(7),pic],false),7);
        // a message waits behind an earlier one of its thread that is not with the server yet
        const E=(delivery,extra)=>Object.assign({cid:delivery,delivery},extra),me={cid:'me'};
        assert.strictEqual(waitsBehind([E('waiting'),me],me),true);assert.strictEqual(waitsBehind([E('sending',{tries:2,inFlight:true}),me],me),true);
        assert.strictEqual(waitsBehind([E('sending',{inFlight:true}),me],me),true,'a first try on its way: a reply written after it must not arrive before it');
        // what he sent arrives in the order he sent it (suda-fixes 54): an answer inside its four seconds and one that
        // failed hold what he wrote after them; what the server took does not, nor a run request (it goes apart)
        assert.strictEqual(waitsBehind([E('received'),me],me),false);
        for(const other of ['failed','holding'])assert.strictEqual(waitsBehind([E(other),me],me),true,other);
        assert.strictEqual(waitsBehind([E('failed',{run:{msg_id:'m1'}}),me],me),false,'a run request goes apart from his words');
        assert.strictEqual(waitsBehind([me,E('waiting')],me),false,'what was written after it does not hold it');assert.strictEqual(waitsBehind([me],me),false);
        // what is cut by length is still whole characters, and what goes out never holds half a pair
        const face='\ud83d\ude00';
        assert.strictEqual(cutWhole('ab'+face+'cd',3),'ab');assert.strictEqual(cutWhole('ab'+face+'cd',4),'ab'+face);assert.strictEqual(cutWhole('abc',5),'abc');assert.strictEqual(cutWhole('ab'+face,4),'ab'+face);
        for(const cut of [excerptOf('x'.repeat(EXCERPT_MAX-2)+face+'עוד'),captionOf('y'.repeat(CAPTION_MAX-1)+face+'עוד'),tempTitle('z'.repeat(59)+face+'עוד מילים')])
          assert.strictEqual(wellFormed(cut),cut,'cut through the middle of a character: '+JSON.stringify(cut.slice(-3)));
        assert.strictEqual(wellFormed('ab\ud83d'),'ab\ufffd');assert.strictEqual(wellFormed('\ude00ab'),'\ufffdab');assert.strictEqual(wellFormed('a'+face+'b'),'a'+face+'b');
        assert.strictEqual(wellFormed(7),7);assert.strictEqual(wellFormed(null),null);
        {const plain=String.prototype.isWellFormed;delete String.prototype.isWellFormed;      // a browser from before these two
          try{assert.strictEqual(wellFormed('ab\ud83d'),'ab\ufffd');assert.strictEqual(wellFormed('\ude00a'+face),'\ufffda'+face);}finally{String.prototype.isWellFormed=plain;}}
        assert.strictEqual(JSON.parse(JSON.stringify({a:{b:['x\ud83d']}},(key,value)=>wellFormed(value))).a.b[0],'x\ufffd');
        // the ids a stored outbox holds; nothing to read is not "it holds none"
        assert.deepStrictEqual([...outboxCids(JSON.stringify([['a',[{cid:'c1'},{cid:'c2'}]],['b',[{cid:'c3'},null,{}]]]))],['c1','c2','c3']);
        assert.deepStrictEqual([...outboxCids('[]')],[]);
        for(const none of [null,undefined,'','{','7','{"a":1}'])assert.strictEqual(outboxCids(none),null,String(none));
        // the row says where the message stands
        assert.strictEqual(deliveryLine({delivery:'sending'}),'שולח…');assert.strictEqual(deliveryLine({delivery:'sending',tries:2}),'שולח שוב…');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:1}),'⚠️ עוד לא נשלח: אין תשובה מהשרת. מנסה שוב לבד');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:2,heard:1}),'⚠️ עוד לא נשלח: השרת לא זמין כרגע. מנסה שוב לבד');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0}),'עוד לא נשלח. נשלח לבד בעוד רגע','not tried yet: it waits its turn, or the page has just come back');
        assert.strictEqual(deliveryLine({delivery:'failed',error:'השרשור סגור'}),'⚠️ לא נשלח: השרשור סגור');assert.strictEqual(deliveryLine({delivery:'failed'}),'⚠️ לא נשלח');
        assert.strictEqual(deliveryLine({delivery:'holding'}),'נשלח בעוד רגע. אפשר עוד לבטל.');assert.strictEqual(deliveryLine({delivery:'received',status:'pending'}),'');
        // a part the browser could not keep whole
        assert.strictEqual(lostPart({text:'x'}),false);assert.strictEqual(lostPart({images:[{name:'a',data:'x'}]}),false);
        assert.strictEqual(lostPart({images:[{name:'a',lost:true}]}),true);assert.strictEqual(lostPart({voice:{lost:true}}),true);assert.strictEqual(lostPart({snippet:{lost:true}}),true);
        assert.ok(SEND_SMALL<64*1024,'the browser lets 64KB of requests outlive a page');
        // every reply has a limit, by its size: a dead line never leaves "sending…" without end
        assert.strictEqual(sendLimit(200),SEND_LIMIT);assert.strictEqual(sendLimit(SEND_SMALL),SEND_LIMIT);assert.strictEqual(sendLimit(80000),SEND_LIMIT+10000);
        assert.strictEqual(sendLimit(4000000),SEND_LIMIT+500000);assert.strictEqual(sendLimit(50000000),SEND_LIMIT_MAX);
        """)

    def test_the_app_can_be_installed_and_notifies_from_a_worker(self):
        import json
        page, sw = self.page(), (ROOT / 'sw.js').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['name'], manifest['start_url'], manifest['display'], manifest['dir']), ('Suda', 'suda.html', 'standalone', 'ltr'))        # the repo's copy is English; install writes the installation's
        for icon in manifest['icons']:
            self.assertTrue((ROOT / icon['src']).is_file(), icon['src'])
            self.assertTrue((ROOT / icon['src']).read_bytes().startswith(b'\x89PNG'))
        self.assertIn('<link rel="manifest" href="manifest.json">', page)
        # the worker is registered only where a browser allows one, and the page speaks the agreed ops
        for part in ("navigator.serviceWorker.register('sw.js')", "window.isSecureContext&&'serviceWorker' in navigator", "refresh().then(restoreTray,restoreTray);\nworker();", "if(workable()&&navigator.serviceWorker.controller)setTimeout(()=>{buildChecked=0;checkBuild(0);},1200);",
                     "if(e.data&&e.data.kind==='shell-updated'){buildChecked=0;checkBuild(0);return;}", "if(events&&events.readyState!==2)return;", "addEventListener('pageshow',e=>{if(e.persisted){inDoubt();paintFresh();listen();refresh();}else paintFresh();});", "{op:'push-subscribe',sub:sub.toJSON()}",
                     "{op:'push-unsubscribe',endpoint}", "{op:'seen',thread:id,last}", "const same=!!sent&&sent.last===last&&sent.stamp===stamp;", "if(!sent.done||sent.tries>=3)return;", "if(view.ch){wantThread(view.ch);tellSeen(view.ch);}", "{op:'mute',thread:t.id,on:!t.mute}", "{op:'quiet',off:true}", "'push.json?t='"):
            self.assertIn(part, page)
        # the worker: no payload is trusted or needed, nothing comes from outside. The one thing it keeps is the
        # page's own file (so that an opening does not wait for the server): never the state, a message or a picture
        self.assertIsNone(re.search(r'https?://', sw))
        self.assertEqual(sw.count('cache.put('), 1)
        # what the page sends and reads does not wait for the worker to start: only the page's own file is the worker's
        self.assertIn("try{if(typeof event.addRoutes==='function')event.waitUntil(Promise.resolve(event.addRoutes(pastWorker(path))).catch(()=>{}));}catch{}", sw)
        for part in ("await cache.put(path,fresh.clone());", "if(!path)return;", "event.respondWith(request.mode==='navigate'?openShell(event,path):readShell(path,null,request.headers.get('If-Modified-Since')||''));",
                     "if(old!==null&&old!==now)await tellPages({kind:'shell-updated'});", "for(const name of ['summary.json','state.json']){"):
            self.assertIn(part, sw)
        self.assertNotIn('event.data', sw.split("addEventListener('push'")[1].split("addEventListener('notificationclick'")[0])
        self.assertIn("renotify:t.fresh,silent:!t.fresh", sw)
        pure = sw.split('// <pure>')[1].split('// </pure>')[0]
        # the worker as `threads install` writes it for the owner's installation, in Hebrew (locales/he.cli.json)
        cli = json.loads((ROOT / 'locales/he.cli.json').read_text(encoding='utf-8'))
        assert "var LANG='en',DIR='ltr',L10N={};" in pure
        pure = pure.replace("var LANG='en',DIR='ltr',L10N={};", "var LANG='he',DIR='rtl',L10N=" + json.dumps({k: cli[k] for k in ('Your turn: {title}', 'There is an update in the threads')}) + ';')
        script = r"""
        const T=(id,extra)=>Object.assign({id,title:'נושא '+id,status:'open',state:'on-owner',note:'לאשר',slot:1,messages:[{id:'m1',from:'fork'}]},extra);
        const due=state=>dueThreads(state).map(t=>t.id);
        assert.deepStrictEqual(due({threads:{a:T('a',{slot:2}),b:T('b',{slot:1})}}),['b','a']);
        assert.deepStrictEqual(dueThreads({threads:{a:T('a')}})[0],{id:'a',title:'עליך: נושא a',body:'לאשר',slot:1,fresh:true});
        // not his turn, asleep, muted, closed, or already seen: nothing
        assert.deepStrictEqual(due({threads:{a:T('a',{state:'working'}),b:T('b',{snooze:{until:9}}),c:T('c',{mute:true}),d:T('d',{status:'closed'}),e:T('e',{seen:{msg:'m1',ts:1}})}}),[]);
        // on him right after his own message (an agent set it so, or his reply left the question open): due, whoever wrote last
        assert.deepStrictEqual(due({threads:{f:T('f',{messages:[{id:'m1',from:'fork'},{id:'m2',from:'owner'}]})}}),['f']);
        assert.deepStrictEqual(due({threads:{f:T('f',{seen:{msg:'m2'},messages:[{id:'m1',from:'fork'},{id:'m2',from:'owner'}]})}}),[]);
        // seen an older message, a newer one came: due again
        assert.deepStrictEqual(due({threads:{a:T('a',{seen:{msg:'m1'},messages:[{id:'m1',from:'fork'},{id:'m2',from:'tower'}]})}}),['a']);
        // a thread with no message: seen is the empty id
        assert.deepStrictEqual(due({threads:{n:T('n',{messages:[]})}}),['n']);assert.deepStrictEqual(due({threads:{n:T('n',{messages:[],seen:{msg:''}})}}),[]);
        // one push is about what is new: only the threads with the newest stamp sound again
        const fresh=state=>Object.fromEntries(dueThreads(state).map(t=>[t.id,t.fresh]));
        assert.deepStrictEqual(fresh({threads:{a:T('a',{alert:{pushed:100}}),b:T('b',{alert:{pushed:250}}),c:T('c',{alert:{pushed:250}}),d:T('d')}}),{a:false,b:true,c:true,d:false});
        assert.deepStrictEqual(fresh({threads:{a:T('a'),b:T('b')}}),{a:true,b:true},'a server that stamps nothing: all of them, as before');
        for(const bad of [null,{},{threads:null},{threads:{x:null,y:7}}])assert.deepStrictEqual(dueThreads(bad),[]);
        // the summary is enough for a push: of an open thread it carries the last messages whole
        assert.deepStrictEqual(due({lite:1,threads:{a:T('a',{seen:{msg:'m8'},stamps:[['m8','fork',1,'x'],['m9','fork',2,'y']],messages:[{id:'m8',from:'fork'},{id:'m9',from:'fork'}]})}}),['a']);
        // the one request the worker answers is the page itself, in its own folder, whatever stands after "?"
        const S='https://suda.example/threads/';
        assert.strictEqual(shellPath(S+'suda.html',S),'/threads/suda.html');assert.strictEqual(shellPath(S+'suda.html?s=1&n=2',S),'/threads/suda.html');
        for(const other of [S+'board.html',S+'state.json',S+'summary.json',S+'full/a.json',S+'uploads/a/m1-1.png',S+'x/suda.html','https://suda.example/other/suda.html','https://evil.example/threads/suda.html','','x',null])
          assert.strictEqual(shellPath(other,S),'',String(other));
        assert.strictEqual(shellPath(S+'suda.html','not a url'),'');
        assert.deepStrictEqual(pastWorker('/threads/suda.html'),[{condition:{not:{urlPattern:'/threads/suda.html'}},source:'network'}]);
        assert.strictEqual(pastWorker('/a(b)/x*y/suda.html')[0].condition.not.urlPattern,'/a\\(b\\)/x\\*y/suda.html','a folder name is never read as a pattern');
        """
        r = subprocess.run([self.node(), '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.pure_js(r"""
        assert.deepStrictEqual([...pushKey('AQID_-8')],[1,2,3,255,239]);assert.strictEqual(pushKey('BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U').length,65);
        assert.strictEqual(quietLabel({from:'22:00',to:'07:00'}),'שקט מ-22:00 עד 07:00');
        for(const none of [null,undefined,{},{from:'25:00',to:'07:00'},{from:'22:00'}])assert.strictEqual(quietLabel(none),'בלי שעות שקט');
        """)

    def test_diagrams_are_drawn_in_a_sandbox_from_a_vendored_library(self):
        import hashlib
        page, frame = self.page(), (ROOT / 'diagram.html').read_text(encoding='utf-8')
        # the frame may run scripts and nothing else: never same-origin, so a diagram cannot reach the page
        self.assertIn("frame.setAttribute('sandbox','allow-scripts')", page)
        for text in (page, frame):
            self.assertNotIn('allow-same-origin', text)
        # the page shows the answer as an image (no script runs there) and never as markup of its own
        self.assertIn("'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(out.svg)", page)
        # the frame takes work only from the page that embeds it, draws in strict mode, and loads nothing from outside
        for part in ("event.source!==parent", "securityLevel:'strict'", "script.src='vendor/mermaid.min.js'"):
            self.assertIn(part, frame)
        self.assertIsNone(re.search(r'https?://', frame))
        # the library is the file that was vendored, byte for byte
        digest = hashlib.sha256((ROOT / 'vendor' / 'mermaid.min.js').read_bytes()).hexdigest()
        self.assertIn('file sha256 ' + digest, (ROOT / 'vendor' / 'README').read_text())

    def test_the_hebrew_table_says_what_the_page_said(self):
        """The page speaks English and his installation reads it in Hebrew (locales/he.json and its parts): every
        part that has an English text gives it the same Hebrew, a template keeps its {names} in both languages, the
        English has no dash of the long kinds, and the words the page used to write are still what he reads."""
        import glob
        seen = {}
        for name in [str(ROOT / 'locales/he.json')] + sorted(glob.glob(str(ROOT / 'locales/he.*.json'))):
            for en, he in json.loads(Path(name).read_text(encoding='utf-8')).items():
                if en.startswith('_'):
                    continue
                self.assertEqual(seen.setdefault(en, he), he, en)
                self.assertEqual(sorted(re.findall(r'\{(\w+)\}', en)), sorted(re.findall(r'\{(\w+)\}', he)), en)
                self.assertNotRegex(en, '[\u2013\u2014]', en)
        table = he_table()
        for en, he in (('Show all', 'הצג הכול'), ('Scroll sideways', 'גלילה לצדדים'), ('Diagram', 'דיאגרמה'), ('Fit to the screen (0)', 'התאמה למסך (0)'),
                       ('Full size (1)', 'גודל מלא (1)'), ('Table', 'טבלה'), ('Chosen: {text}', 'נבחר: {text}'), ('Undo', 'בטל'),
                       ('An answer in words', 'תשובה במילים'), ('Archive: completed', 'ארכיון: הושלמו'), ('Take out of the archive', 'הוצא מהארכיון'),
                       ('To the archive', 'לארכיון'), ('Recommended', 'מומלץ'), ('Full screen', 'מסך מלא'), ('New version · refresh', 'גרסה חדשה · רענן'),
                       ('The server did not accept the message. It is kept here', 'השרת לא קיבל את ההודעה. היא שמורה כאן'),
                       ('No answer from the server. The message is kept here', 'אין תשובה מהשרת. ההודעה שמורה כאן'), ('Me', 'אני')):
            self.assertEqual(table.get(en), he, en)

    def test_the_old_address_redirects_and_keeps_the_thread(self):
        stub = (ROOT / 'slack.html').read_text(encoding='utf-8')
        self.assertIn("location.replace('suda.html'+location.search+location.hash)", stub)
        self.assertLess(len(stub), 1000)
        self.assertIsNone(re.search(r'''(?:src|href)=["']https?://''', stub))

    def test_page_is_self_contained_and_rtl(self):
        page = self.page()
        # the repo's copy is English, left to right; `threads install` writes his Hebrew and right to left
        self.assertIn('<html lang="en" dir="ltr">', page)
        # Nothing is fetched from another host: no fonts, scripts or styles from outside.
        self.assertIsNone(re.search(r'''(?:src|href)=["']https?://|@import|url\(\s*["']?https?://''', page))
        # The phone keyboard must shrink the layout, so the composer stays above it.
        self.assertIn('interactive-widget=resizes-content', page)

    def test_page_uses_the_board_api(self):
        page = self.page()
        for part in ("'/api/state'", "'/events?board='", "'state.json?t='", "op:'reply'", "'close'", "'reopen'",
                     "'keep'", "'done'", "op:'sweep'"):
            self.assertIn(part, page)
        # v2 contract: "read, nothing to add" and "close" name the last message on his screen, so the server can
        # refuse when a newer one arrived; a typed reply names the question that was on his screen (or null).
        for part in ("state.last=", "msg.under=", "state.under=msg.under", "store.set('visited','1')", "act(id,'done',null,true)"):
            self.assertIn(part, page)
        # It serves whatever board folder it sits in: a staging copy must not post to the live board.
        self.assertNotIn("board:'threads'", page)
        self.assertNotIn('board=threads', page)

    def test_only_rendered_markdown_reaches_innerhtml(self):
        lines = [line for line in self.page().splitlines() if '.innerHTML' in line]
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r'\.innerHTML\s*=\s*markdown\(', line)
        self.assertNotIn('insertAdjacentHTML', self.page())
        self.assertNotIn('document.write', self.page())

    # ── markdown ───────────────────────────────────────────────────────────

    def test_markdown_escapes_everything(self):
        self.pure_js(r"""
        const bad=[
         '<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '[x](javascript:alert(1))',
         '[x](data:text/html,<b>)', '**<i>x</i>**', '`<b>`', '```\n</code></pre><script>alert(1)</script>\n```',
         'https://x.example/"onmouseover="alert(1)', "https://x.example/'onmouseover='alert(1)",
         '[a"b](https://x.example/?q="><svg onload=alert(1)>)', '> <iframe src=//evil.example>',
         '| <b>a</b> | b |\n|---|---|\n| <img src=x> | 2 |', '# <u>t</u>', '1. <s>x</s>', '- <a href=x>y</a>',
         '[x](//evil.example/a.html)', '//evil.example/a.html', '[x](/ok.html" onclick="alert(1))'];
        for(const text of bad){
         const html=markdown(text);
         // Every tag in the output is one the renderer wrote itself.
         for(const tag of html.match(/<[^>]*>/g)||[])
          assert.ok(/^<\/?(p|br|strong|code|pre|ul|ol|li|blockquote|hr|table|tr|td|th|div|span)( (class|dir|value)="[\w -]*")*>$/.test(tag)
           ||/^<a href="(https?:\/\/|\/(?!\/))[^"<>\s]*"( dir="ltr")? target="_blank" rel="noopener">$/.test(tag)||tag==='</a>'
           // a link that says what it is: fixed words, and the address once more as its title
           ||/^<a class="chip-link" data-kind="(pr|issue|commit|file|repo|thread|board|page|web)"( data-thread="[a-z0-9-]+"( data-msg="m\d+")?)? href="(https?:\/\/|\/(?!\/))[^"<>\s]*" title="(https?:\/\/|\/(?!\/))[^"<>\s]*" target="_blank" rel="noopener">$/.test(tag)
           ||['<span class="chip-kind">','</span>','<bdi class="chip-text">','</bdi>','<svg class="chip-icon" viewBox="0 0 16 16" aria-hidden="true">','</svg>'].includes(tag)
           ||/^<use href="#i-(pr|issue|commit|file|thread|board|web)"\/>$/.test(tag),text+' → '+tag);
         assert.ok(!/javascript:|data:text/i.test((html.match(/href="[^"]*"/g)||[]).join(' ')),text);
        }
        assert.ok(!markdown('[x](//evil.example/a.html) //evil.example/a.html').includes('<a '));
        // a browser reads a backslash as a slash: "/\\host" would leave this server
        for(const text of ['[x](/\\evil.example/a.html)','/\\evil.example/a.html','[x](/a\\..\\b.html)'])assert.ok(!markdown(text).includes('<a '),text);
        // one huge line must not stall the page: the label of a link is bounded
        const started=Date.now();markdown('['.repeat(200000));markdown('[a]('.repeat(60000));markdown('**'.repeat(100000));markdown('`'.repeat(200001));
        assert.ok(Date.now()-started<3000,'slow markdown: '+(Date.now()-started)+' ms');
        """)

    def test_markdown_inline(self):
        self.pure_js(r"""
        assert.strictEqual(markdown('א **b** `c*d` ה'),'<p>א <strong>b</strong> <code>c*d</code> ה</p>');
        assert.strictEqual(markdown('[דף](https://x.example/a?b=1&c=2)'),
         '<p><a href="https://x.example/a?b=1&amp;c=2" target="_blank" rel="noopener">דף</a></p>');
        // a bare address stops before the punctuation that ends the sentence
        assert.strictEqual(markdown('ראה http://192.0.2.10:8767/threads/assets/x.html.'),
         '<p>ראה <a class="chip-link" data-kind="web" href="http://192.0.2.10:8767/threads/assets/x.html" title="http://192.0.2.10:8767/threads/assets/x.html" target="_blank" rel="noopener"><span class="chip-kind"><svg class="chip-icon" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-web"/></svg></span><bdi class="chip-text">192.0.2.10:8767/…/x.html</bdi></a>.</p>');
        // a page on this server, written as a path
        assert.strictEqual(markdown('לוח: /acme/sim-lab-spot/board.html.'),
         '<p>לוח: <a class="chip-link" data-kind="board" href="/acme/sim-lab-spot/board.html" title="/acme/sim-lab-spot/board.html" target="_blank" rel="noopener"><span class="chip-kind"><svg class="chip-icon" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-board"/></svg>לוח</span><bdi class="chip-text">sim-lab-spot</bdi></a>.</p>');
        // a file path is text, never a link
        for(const path of ['~/PG/brain/reports/a.html','~/.snap','a/b/c.html','partner_machine_type','/Users/alice/Documents/a.html','/tmp/x/report.html','/private/var/a.html'])
         assert.ok(!markdown('קובץ '+path+' כאן').includes('<a '),path);
        assert.strictEqual(markdown('`https://x.example`'),'<p dir="ltr"><code>https://x.example</code></p>');
        """)

    def test_markdown_blocks(self):
        self.pure_js(r"""
        assert.strictEqual(markdown('שורה א\nשורה ב\n\nפסקה'),'<p>שורה א</p><p>שורה ב</p><p class="gap">פסקה</p>');
        assert.strictEqual(markdown('- א\n  - ב\n- ג'),'<ul><li>א</li><li class="l2">ב</li><li>ג</li></ul>');
        // the numbers stay as written, also when the list is cut by other lines
        assert.strictEqual(markdown('1. א\n2. ב\nטקסט\n4. ד'),
         '<ol><li value="1">א</li><li value="2">ב</li></ol><p>טקסט</p><ol><li value="4">ד</li></ol>');
        assert.strictEqual(markdown('> Hi, two SIMs\n> stuck'),'<blockquote dir="ltr"><p>Hi, two SIMs</p><p>stuck</p></blockquote>');
        assert.strictEqual(markdown('```sh\nls -la\n```\nאחרי'),'<pre class="lang-sh"><code>ls -la</code></pre><p>אחרי</p>');
        // the language of a block is kept as a plain class, and only when it is a plain word
        assert.strictEqual(markdown('```TypeScript\nx\n```'),'<pre class="lang-typescript"><code>x</code></pre>');
        assert.strictEqual(markdown('```c++ onload=x\ny\n```'),'<pre><code>y</code></pre>');assert.strictEqual(markdown('```js"><b\nz\n```'),'<pre><code>z</code></pre>');
        assert.strictEqual(markdown('```\nלא נסגר'),'<pre><code>לא נסגר</code></pre>');
        // a diagram block is marked for drawing; its text is escaped like any code, and no other language is marked
        assert.strictEqual(markdown('```mermaid\ngraph TD;A-->B["<b>x</b>"]\n```'),'<pre class="mermaid"><code>graph TD;A--&gt;B[&quot;&lt;b&gt;x&lt;/b&gt;&quot;]</code></pre>');
        assert.strictEqual(markdown('```Mermaid\nA\n```\n```js\nB\n```'),'<pre class="mermaid"><code>A</code></pre><pre class="lang-js"><code>B</code></pre>');
        assert.strictEqual(markdown('```mermaid onclick=x\nA\n```'),'<pre><code>A</code></pre>');
        assert.strictEqual(markdown('## כותרת'),'<p class="h h2">כותרת</p>');assert.strictEqual(markdown('# Top'),'<p class="h h1" dir="ltr">Top</p>');assert.strictEqual(markdown('##### עמוק'),'<p class="h h3">עמוק</p>');
        assert.strictEqual(markdown('א\n---\nב'),'<p>א</p><hr><p>ב</p>');
        assert.strictEqual(markdown('| שם | ערך |\n|---|---|\n| א | **1** |'),
         '<div class="table"><table><tr><th>שם</th><th>ערך</th></tr><tr><td>א</td><td><strong>1</strong></td></tr></table></div>');
        // direction per line: Hebrew anywhere keeps the page direction, a Latin-only line reads left to right
        assert.strictEqual(markdown('D1 ו-D2 לא ירוצו'),'<p>D1 ו-D2 לא ירוצו</p>');
        assert.strictEqual(markdown('approved by lead'),'<p dir="ltr">approved by lead</p>');
        assert.strictEqual(markdown('13:45'),'<p>13:45</p>');
        // an English item in a Hebrew list reads left to right, its bullet on its own left (m414)
        assert.strictEqual(markdown('- approved by lead.\n- אושר'),'<ul><li dir="ltr">approved by lead.</li><li>אושר</li></ul>');
        assert.strictEqual(markdown(''),'');assert.strictEqual(markdown('  \n\n'),'');
        """)

    def test_a_chip_alone_follows_its_place(self):
        """The owner, suda m609 (a screenshot): a list item that is only a pull request (a chip) was laid out left to
        right, and so were the Hebrew items under it. An address or a link alone has no words of its own: it follows
        the place it stands in. Code alone is still read left to right."""
        self.pure_js(r"""
        for(const alone of ['https://github.com/acme/orbit/pull/1644','<https://github.com/acme/orbit/pull/1644>','[orbit #1644](https://github.com/acme/orbit/pull/1644)',
                            'https://github.com/acme/orbit/pull/1644 https://github.com/acme/kub/pull/34','**https://x.example/a**'])
          assert.strictEqual(blockDir(alone),'',alone);
        assert.strictEqual(blockDir('`ls -la`'),'ltr');
        assert.strictEqual(blockDir('See https://x.example/a for the logs'),'ltr');      // English words around it: English
        assert.strictEqual(blockDir('ראה https://x.example/a'),'rtl');
        const html=markdown('**שני ה-PR מוכנים כטיוטה.**\n\n- https://github.com/acme/orbit/pull/1644\n  - קריאת הסודות לפי שדות מ-env.\n  - יש גם סקריפט שמעתיק ל-SSM\n- https://github.com/acme/kub/pull/34\n  - התקנת External Secrets דרך ArgoCD\n- **סקירה עוינת על שניהם:** נמצאו ותוקנו 2 חמורות');
        assert.ok(!/dir="ltr"/.test(html),html);
        """)

    def test_markdown_every_block_takes_its_direction_from_its_own_words(self):
        """The owner, thread suda m414 (a screenshot of another thread): an English e-mail quoted in a Hebrew message
        was laid right to left: right-aligned, the numbers of its list on the right. Every block (a paragraph, a list
        and its items, a quote, a table and its cells, a heading) now takes its direction from its own words; a
        block written inside one of another direction says its own. A Hebrew line that opens with an English word
        (a product, an agent's name) stays Hebrew; an English line with a Hebrew word in it stays English."""
        self.pure_js(r"""
        // the e-mail of m18, shortened: the quote, its paragraphs and its numbered list read left to right
        assert.strictEqual(markdown('**טיוטה ב-Superhuman, לא נשלחה.**\n\n> Hi Chris,\n>\n> We are blocked on three things:\n>\n> 1. **Sandbox API user:** please activate it.\n> 2. **iFrame domains:** please allow https://dev.pay-example.com, plus localhost.\n>\n> Thanks,\n> Dana'),
         '<p><strong>טיוטה ב-Superhuman, לא נשלחה.</strong></p><blockquote dir="ltr"><p>Hi Chris,</p><p class="gap">We are blocked on three things:</p>'
         +'<ol><li value="1"><strong>Sandbox API user:</strong> please activate it.</li><li value="2"><strong>iFrame domains:</strong> please allow '
         +'<a class="chip-link" data-kind="web" href="https://dev.pay-example.com" title="https://dev.pay-example.com" target="_blank" rel="noopener"><span class="chip-kind"><svg class="chip-icon" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-web"/></svg></span><bdi class="chip-text">dev.pay-example.com</bdi></a>, plus localhost.</li></ol>'
         +'<p class="gap">Thanks,</p><p>Dana</p></blockquote>');
        // a list: all English is an English list (its numbers on the left); in a Hebrew list an English item says so itself
        assert.strictEqual(markdown('- approved by lead.\n- merged'),'<ul dir="ltr"><li>approved by lead.</li><li>merged</li></ul>');
        assert.strictEqual(markdown('1. one\n2. 13:45'),'<ol dir="ltr"><li value="1">one</li><li value="2">13:45</li></ol>');
        // a Hebrew item inside an English quote says it is Hebrew
        assert.strictEqual(markdown('> - first item here\n> - second item here\n> - פריט'),'<blockquote dir="ltr"><ul><li>first item here</li><li>second item here</li><li dir="rtl">פריט</li></ul></blockquote>');
        // a quote that is mostly Hebrew stays Hebrew; its English line says so
        assert.strictEqual(markdown('> Hi\n> שלום לכולם, הנה העדכון'),'<blockquote><p dir="ltr">Hi</p><p>שלום לכולם, הנה העדכון</p></blockquote>');
        // a Hebrew line that opens with an English word stays Hebrew
        for(const line of ['Ghostty ו-tmux עובדים יחד','worker-a בודק למה','PR #1614 מוזג לענף הראשי','https://x.example/a/b/c/d ראה כאן','`threads install --force` ואז לרענן'])
         assert.strictEqual(markdown(line).slice(0,3),'<p>',line);
        // an English line with one Hebrew word in it stays English
        assert.strictEqual(markdown('Please print the word שלום on the receipt for the test').slice(0,16),'<p dir="ltr">Ple');
        // a line that opens with a mark of direction (agents write one before an English name in a Hebrew line) keeps it
        assert.strictEqual(markdown('‏Sarah, Noam').slice(0,3),'<p>');
        assert.strictEqual(markdown('‎שלום world').slice(0,13),'<p dir="ltr">');
        // a table of English is an English table (its first column on the left); a Hebrew table says it for an English cell
        assert.strictEqual(markdown('| Name | Value |\n|---|---|\n| a | 1 |'),'<div class="table" dir="ltr"><table><tr><th>Name</th><th>Value</th></tr><tr><td>a</td><td>1</td></tr></table></div>');
        assert.strictEqual(markdown('| שם | ערך |\n|---|---|\n| Chris | 1 |'),'<div class="table"><table><tr><th>שם</th><th>ערך</th></tr><tr><td dir="ltr">Chris</td><td>1</td></tr></table></div>');
        // a heading
        assert.strictEqual(markdown('## Draft for Chris'),'<p class="h h2" dir="ltr">Draft for Chris</p>');
        // quotes inside quotes end somewhere: deep ones are text
        const deep=markdown('>'.repeat(40)+' x');assert.ok((deep.match(/<blockquote/g)||[]).length<=4,deep);
        """)

    # ── whose turn, and the sidebar ────────────────────────────────────────

    def test_turn_and_note(self):
        self.pure_js(r"""
        const m=(from,text,extra)=>Object.assign({from,text,ts:1},extra);
        // v2 records say it themselves
        assert.strictEqual(turnOf({status:'open',state:'working',messages:[]}),'working');
        assert.strictEqual(turnOf({status:'open',state:'done',messages:[m('fork','x')]}),'done');
        assert.strictEqual(turnOf({status:'closed',state:'on-owner',messages:[]}),'done');
        assert.strictEqual(noteOf({status:'open',state:'on-owner',note:'לאשר מיזוג',messages:[]}),'לאשר מיזוג');
        // a v1 record has no state: the conversation decides, the same way the v2 migration does
        assert.strictEqual(turnOf({status:'open',messages:[]}),'on-owner');
        assert.strictEqual(turnOf({status:'open',state:'weird',messages:[]}),'on-owner');
        assert.strictEqual(turnOf({status:'open',messages:[m('owner','x',{status:'acked'}),m('fork','y')]}),'on-owner');
        assert.strictEqual(turnOf({status:'open',messages:[m('fork','y'),m('owner','x',{status:'acked'})]}),'working');
        assert.strictEqual(turnOf({status:'open',messages:[m('owner','x',{status:'pending'}),m('tower','y')]}),'working');
        assert.strictEqual(turnOf({status:'closed',messages:[m('fork','y')]}),'done');
        assert.strictEqual(noteOf({status:'open',messages:[]}),'נושא חדש, לקרוא');
        assert.strictEqual(noteOf({status:'open',messages:[m('owner','a',{status:'acked'}),m('fork','**קיבלתי** את\nהאישור')]}),'לקרוא: קיבלתי את האישור');
        assert.strictEqual(noteOf({status:'open',messages:[m('owner','כן מתיר',{status:'pending'})]}),'ענית: «כן מתיר», ממתין לאיסוף');
        assert.strictEqual(noteOf({status:'open',messages:[m('owner','כן מתיר',{status:'acked'})]}),'ענית: «כן מתיר», סוכן עובד על זה');
        assert.strictEqual(noteOf({status:'closed',messages:[m('fork','y')]}),'');
        assert.strictEqual(preview('a  **b**\n`c` '+'x'.repeat(50),12),'a b c xxxxx…');
        """)

    def test_a_thread_that_waits_on_nobody_says_so(self):
        self.pure_js(r"""
        const T=(state,extra)=>Object.assign({id:'x',status:'open',state,note:'',messages:[]},extra);
        // an agent works: whose hands it is in, and that there is nothing for him to do
        let s=standing(T('working',{note:'ממזג ל-66bbb4f',state_by:'builder'}));
        assert.deepStrictEqual([s.turn,s.label,s.line,s.row],['working','בעבודה אצל builder','אין מה לעשות מצדך · ממזג ל-66bbb4f','אצל builder · ממזג ל-66bbb4f']);
        s=standing(T('working',{note:'בודק webhooks',state_by:'fork'}));
        assert.deepStrictEqual([s.label,s.row],['בעבודה אצל סוכן','אצל סוכן · בודק webhooks']);
        s=standing(T('working',{note:'רץ'}));assert.deepStrictEqual([s.label,s.line,s.row],['בעבודה','אין מה לעשות מצדך · רץ','רץ']);
        // a note that already says it is not repeated
        s=standing(T('working',{note:'builder ממזג; אין מה לעשות מצדך',state_by:'builder'}));
        assert.strictEqual(s.line,'builder ממזג; אין מה לעשות מצדך');
        // the line the CLI writes after his own reply already names who has it
        s=standing(T('working',{note:'ענית: «כן», סוכן עובד על זה',state_by:'fork',auto:true}));
        assert.deepStrictEqual([s.label,s.row],['בעבודה אצל סוכן','ענית: «כן», סוכן עובד על זה']);
        // done: nothing waits on anyone
        s=standing(T('done',{note:'הדוח נשלח'}));assert.deepStrictEqual([s.turn,s.label,s.line,s.row],['done','הושלם','אין מה לעשות מצדך · הדוח נשלח','הדוח נשלח']);
        s=standing(T('done'));assert.deepStrictEqual([s.label,s.line,s.row],['הושלם','אין מה לעשות מצדך','אין מה לעשות מצדך']);
        // three ways to be finished, as the old board.html named them: an agent resolved it, an agent stated an outcome,
        // or he read a plain report and there was nothing to do
        s=standing(T('done',{note:'מוזג',resolved:true}));assert.deepStrictEqual([s.label,s.line],['נפתר','אין מה לעשות מצדך · מוזג']);
        s=standing(T('done',{note:'קראת, אין המשך פתוח',auto:true}));assert.deepStrictEqual([s.label,s.line,s.row],['אין מה לעשות','קראת, אין המשך פתוח','קראת, אין המשך פתוח']);
        s=standing(T('done',{auto:true}));assert.deepStrictEqual([s.label,s.line],['אין מה לעשות','אין מה לעשות מצדך']);
        // a plain report is his only to read: no request, no question; anything else needs a real answer
        const report=T('on-owner',{auto:true,note:'לקרוא: סיימתי'});
        assert.strictEqual(plainReport(report),true);assert.strictEqual(plainReport(T('on-owner',{auto:false,note:'לאשר'})),false);
        assert.strictEqual(plainReport({...report,question:{id:'m2',text:'?'}}),false);assert.strictEqual(plainReport({...report,status:'closed'}),false);
        assert.strictEqual(plainReport(T('working',{auto:true})),false);assert.strictEqual(plainReport(T('done',{auto:true})),false);
        assert.strictEqual(plainReport({id:'v1',status:'open',messages:[{from:'fork',ts:1,text:'x'}]}),false);   // a v1 record states nothing: never dismissed
        // on him: his line is what he must do, with nothing added
        s=standing(T('on-owner',{note:'לאשר מיזוג',state_by:'fork'}));assert.deepStrictEqual([s.turn,s.label,s.line,s.row],['on-owner','עליך','לאשר מיזוג','לאשר מיזוג']);
        // closed
        s=standing(T('done',{status:'closed',note:'רצה ב-production'}));assert.deepStrictEqual([s.turn,s.label,s.line],['closed','סגור','רצה ב-production']);
        // the sections say it too
        assert.deepStrictEqual(sidebar([]).sections.map(x=>x.hint),['','אין מה לעשות מצדך','אין המשך פתוח']);
        """)

    def test_a_section_is_ordered_as_he_chose_and_urgent_comes_first(self):
        """The owner, suda m501/m505: inside a section, by the place numbers (as always) or what moved last on top;
        what he marked urgent is first either way, the one marked first on top."""
        self.pure_js(r"""
        const r=(id,slot,extra)=>({t:Object.assign({id,messages:[],updated:0},extra),slot});
        const rows=[r('a',1,{updated:100}),r('b',2,{updated:300}),r('c',3,{updated:50,messages:[{ts:400}]}),r('d',4,{updated:200})];
        const ids=list=>list.map(x=>x.t.id).join('');
        assert.strictEqual(ids(sectionOrder(rows,'slot')),'abcd');
        assert.strictEqual(ids(sectionOrder(rows,'recent')),'cbda');        // c's last message is the newest
        const hot=[r('a',1),r('b',2,{urgent:20}),r('c',3),r('d',4,{urgent:10})];
        assert.strictEqual(ids(sectionOrder(hot,'slot')),'dbac');           // marked first, first
        assert.strictEqual(ids(sectionOrder(hot,'recent')).slice(0,2),'db');
        // nonsense in the mark is no mark
        assert.strictEqual(ids(sectionOrder([r('a',1),r('b',2,{urgent:'x'}),r('c',3,{urgent:null})],'slot')),'abc');
        // the order of the rows given is not changed in place
        const copy=rows.slice();sectionOrder(rows,'recent');assert.deepStrictEqual(rows,copy);
        // by the LAST MESSAGE, the time each row shows (the owner, suda-fixes m4: "I turned it on and it did not
        // work"): a thread read, tapped or swept moves its `updated`, not its place
        const shown=[r('x',1,{updated:900,messages:[{ts:100}]}),r('y',2,{updated:200,messages:[{ts:300}]}),r('z',3,{updated:950,messages:[{ts:50},{ts:200}]})];
        assert.strictEqual(ids(sectionOrder(shown,'recent')),'yzx');
        // a thread with no message yet: the time its row shows (its last change)
        assert.strictEqual(ids(sectionOrder([r('p',1,{created:10,updated:999}),r('q',2,{created:20,messages:[{ts:15}]})],'recent')),'pq');
        assert.strictEqual(lastShown({messages:[{ts:5},{ts:7}],updated:99}),7);assert.strictEqual(lastShown({messages:[],updated:0,created:3}),3);
        // the owner, suda-fixes m8: all three, each device its own choice. 'moved': what changed last, any change
        // (a read, a task, a state) as before; 'recent' stays the last message
        assert.strictEqual(ids(sectionOrder(shown,'moved')),'zxy');
        assert.strictEqual(ids(sectionOrder(rows,'moved')),'cbda');
        assert.deepStrictEqual(LIST_ORDERS.map(o=>o[0]),['recent','moved','slot']);
        assert.ok(LIST_ORDERS.every(o=>typeof o[1]==='string'&&o[1].length>3));
        """)

    def test_sidebar_sections_keep_slot_order(self):
        self.pure_js(r"""
        globalThis.store={get:(key,fallback)=>key==='list-order'?'slot':fallback};      // this device chose the place numbers (the default is the last message)
        const T=(id,slot,state,extra)=>Object.assign({id,slot,state,status:'open',created:slot,updated:slot,messages:[]},extra);
        const shape=s=>s.sections.map(x=>x.key+':'+x.rows.map(r=>r.slot+r.t.id).join(','));
        let rows=[T('c',3,'on-owner'),T('a',1,'on-owner'),T('d',4,'working'),T('b',2,'done'),T('e',5,'on-owner')];
        assert.deepStrictEqual(sidebar(rows).sections.map(s=>s.label),['עליך','בעבודה','הושלם']);
        assert.deepStrictEqual(shape(sidebar(rows)),['on-owner:1a,3c,5e','working:4d','done:2b']);
        // new activity never reorders: the place is the slot, not `updated`
        rows[0].updated=999;rows[4].updated=0;
        assert.deepStrictEqual(shape(sidebar(rows)),['on-owner:1a,3c,5e','working:4d','done:2b']);
        // a turn change moves the channel to its section, at its slot's place
        rows[3].state='on-owner';
        assert.deepStrictEqual(shape(sidebar(rows)),['on-owner:1a,2b,3c,5e','working:4d','done:']);
        // closed threads leave the sections, newest closed first
        rows.push(T('x',6,'done',{status:'closed',closed_ts:50}),T('y',7,'done',{status:'closed',closed_ts:90}),T('z',8,'done',{status:'closed',updated:70}));
        assert.deepStrictEqual(sidebar(rows).closed.map(t=>t.id),['y','z','x']);
        assert.deepStrictEqual(shape(sidebar(rows)),['on-owner:1a,2b,3c,5e','working:4d','done:']);
        // a v1 file has no slots: oldest first, and a duplicate slot never hides a thread
        rows=[{id:'n2',status:'open',created:2,messages:[]},{id:'n1',status:'open',created:1,messages:[]},T('dup',1,'done',{created:9}),T('a',1,'done',{created:0})];
        assert.deepStrictEqual(slotOrder(rows).map(r=>r.slot+r.t.id),['1a','2n1','3n2','4dup']);
        assert.deepStrictEqual(slotOrder([]),[]);
        // the tower's own thread stands above the sections whatever its turn, and keeps its slot on record
        rows=[T('a',1,'on-owner'),T('tower',2,'working'),T('b',3,'working')];
        assert.deepStrictEqual(sidebar(rows).top.map(r=>r.t.id),['tower']);assert.deepStrictEqual(shape(sidebar(rows)),['on-owner:1a','working:3b','done:']);
        rows[1].status='closed';assert.deepStrictEqual(sidebar(rows).top,[]);assert.deepStrictEqual(sidebar(rows).closed.map(t=>t.id),['tower']);
        assert.deepStrictEqual(sidebar([]).top,[]);
        assert.deepStrictEqual(sidebar([]).sections.map(s=>s.rows.length),[0,0,0]);
        """)

    def test_unread_and_waiting_counts(self):
        self.pure_js(r"""
        const m=(from,ts,extra)=>Object.assign({from,ts,text:'x'},extra);
        const t={messages:[m('fork',1),m('owner',2,{status:'acked'}),m('fork',3),m('tower',4)]};
        assert.strictEqual(unreadCount(t,0),3);assert.strictEqual(unreadCount(t,3),1);assert.strictEqual(unreadCount(t,4),0);
        assert.strictEqual(unreadCount(t,NaN),3);                       // a broken stored value reads as "never seen"
        assert.strictEqual(waitingCount(t),2);                          // what came after his last message
        assert.strictEqual(waitingCount({messages:[m('fork',1),m('owner',2)]}),0);
        assert.strictEqual(waitingCount({messages:[m('fork',1),m('fork',2)]}),2);
        assert.strictEqual(waitingCount({messages:[]}),0);
        assert.strictEqual(lastAgentTs(t),4);assert.strictEqual(lastAgentTs({messages:[m('owner',9)]}),0);
        """)

    def test_damaged_state_is_survivable(self):
        self.pure_js(r"""
        const raw={version:2,threads:{ok:{id:'ok',title:'נושא',status:'open',messages:[{id:'m1',from:'fork',text:'x',ts:5},null,{from:'fork'},{from:'fork',ts:'7'},{id:'m2',from:'tower',ts:9}]},
          'no-messages':{status:'open'},'odd-status':{status:'weird',messages:'x',title:''},broken:null,'BAD ID':{status:'open',messages:[]},text:'x'}};
        const data=normalize(raw);
        assert.deepStrictEqual(Object.keys(data.threads),['ok','no-messages','odd-status']);
        assert.deepStrictEqual(data.threads.ok.messages.map(m=>[m.id,m.text]),[['m1','x'],['m2','']]);
        assert.deepStrictEqual([data.threads['no-messages'].title,data.threads['no-messages'].messages,data.threads['no-messages'].context],['no-messages',[],'']);
        assert.strictEqual(data.threads['odd-status'].status,'closed');assert.strictEqual(data.threads['odd-status'].title,'odd-status');
        // what survives can be drawn: none of the page's readers throws on it
        const rows=Object.values(data.threads);
        sidebar(rows);for(const t of rows){turnOf(t);noteOf(t);waitingCount(t);unreadCount(t,0);timeline(t.messages,0,100);}
        for(const bad of [null,undefined,7,'x',{},{threads:null},{threads:[]},{threads:'x'}]){const empty=normalize(bad);assert.strictEqual(empty.version,1);assert.deepStrictEqual(Object.keys(empty.threads),[]);}
        // an id is data: a thread named like something every object has is found only when it exists
        assert.strictEqual(normalize({threads:{}}).threads.constructor,undefined);assert.strictEqual('toString' in normalize({threads:{}}).threads,false);
        const odd=normalize({version:2,threads:{constructor:{status:'open',title:'x',messages:[]}}});
        assert.strictEqual(odd.threads.constructor.title,'x');assert.deepStrictEqual(Object.keys(odd.threads),['constructor']);
        assert.strictEqual(normalize({version:'2',threads:{}}).version,2);
        """)

    def test_outbox_is_merged_not_overwritten(self):
        self.pure_js(r"""
        const m=(cid,extra)=>Object.assign({cid,text:cid},extra);
        // another tab's unsent message stays; this tab's copy of the same message wins; what this tab finished is dropped
        const stored=[['a',[m('1'),m('2',{delivery:'sending'})]],['b',[m('9')]],['broken'],null,['c','x']];
        const mine=new Map([['a',[m('2',{delivery:'failed'}),m('3')]],['d',[]]]);
        assert.deepStrictEqual(mergeOutbox(stored,mine,new Set(['9'])),[['a',[m('1'),m('2',{delivery:'failed'}),m('3')]]]);
        assert.deepStrictEqual(mergeOutbox('junk',new Map([['a',[m('1')]]]),new Set()),[['a',[m('1')]]]);
        assert.deepStrictEqual(mergeOutbox([],new Map(),new Set()),[]);
        """)

    # ── snippets: long text as a file beside the message ───────────────────

    def test_a_big_text_is_cut_into_parts_the_server_can_take(self):
        """The board server takes a request of up to 4 MB: a bigger snippet goes in parts. Joined, the parts are the
        text exactly; each one, as JSON, is at most the limit; none ends inside a character made of two halves."""
        self.pure_js(r"""
        const join=parts=>parts.join('');
        const fits=(parts,max)=>parts.every(p=>p.length>0&&utf8Bytes(JSON.stringify(p))<=max);
        // small: one part
        assert.deepStrictEqual(snippetParts('שלום',100),['שלום']);
        // ascii, hebrew (2 bytes), emoji (4 bytes, two halves in JS), and escapes (a control character is 6 bytes as JSON)
        for(const unit of ['x','א','😀','\u0001','"','a\nב😀\u0002\\']){
          const text=unit.repeat(5000),parts=snippetParts(text,997);
          assert.strictEqual(join(parts),text,unit);
          assert.ok(fits(parts,997),unit);
          assert.ok(parts.every(p=>!/[\uD800-\uDBFF]$/.test(p)&&!/^[\uDC00-\uDFFF]/.test(p)),'a pair cut in two: '+unit);
          assert.ok(parts.length<=Math.ceil(utf8Bytes(JSON.stringify(text))/997)*2+1,'parts too small: '+unit+' '+parts.length);
        }
        // the real size: a 7 MB crash report in parts that each fit a request
        const crash='Thread 0 Crashed:: Dispatch queue: com.apple.main-thread\n'.repeat(130000);
        assert.ok(utf8Bytes(crash)>7000000);
        const parts=snippetParts(crash);
        assert.strictEqual(join(parts),crash);
        assert.ok(fits(parts,PART_BYTES)&&PART_BYTES<=1500000&&parts.length<=10,String(parts.length));
        """)

    def test_long_text_becomes_a_snippet(self):
        self.pure_js(r"""
        const long='שורה בעברית with English 123\n'.repeat(1800);          // ~50,000 chars, mixed
        assert.ok(long.length>50000);
        // a typed text up to 4000 chars goes inline; a longer one travels as a snippet with no inline text
        assert.deepStrictEqual(splitForSend('שלום',null),{text:'שלום',snippet:null,error:''});
        assert.deepStrictEqual(splitForSend('x'.repeat(4000),null),{text:'x'.repeat(4000),snippet:null,error:''});
        let out=splitForSend('x'.repeat(4001),null);assert.deepStrictEqual([out.text,out.snippet.text.length,out.error],['',4001,'']);
        out=splitForSend(long,null);assert.deepStrictEqual([out.text,out.snippet.text===long,out.error],['',true,'']);
        // an attached snippet rides beside the typed message; with nothing typed the text is empty
        out=splitForSend('ראה את הלוג',{text:long,name:'api.log'});assert.deepStrictEqual([out.text,out.snippet.name,out.snippet.text===long,out.error],['ראה את הלוג','api.log',true,'']);
        out=splitForSend('  ',{text:long,name:''});assert.deepStrictEqual([out.text,'name' in out.snippet,out.error],['',false,'']);
        // the limits are said, never cut silently
        assert.ok(splitForSend('x'.repeat(8001),{text:long}).error.includes('8000'));
        // up to 20 MB (a big-file thread, m6: a 7 MB crash report); a big one goes in parts, see snippetParts
        assert.ok(splitForSend('',{text:'א'.repeat(10000001)}).error.includes('20MB'));        // 2 bytes each: over 20,000,000 bytes
        assert.strictEqual(splitForSend('',{text:'א'.repeat(10000000)}).error,'');
        assert.strictEqual(splitForSend('',{text:'x'.repeat(7000000)}).error,'');
        assert.ok(splitForSend('x'.repeat(20000001),null).error.includes('20MB'));
        assert.deepStrictEqual(splitForSend('   ',null),{text:'',snippet:null,error:''});         // nothing to send
        assert.strictEqual(utf8Bytes('aא€😀'),1+2+3+4);
        // the collapsed preview of a snippet that has not reached the server yet
        assert.strictEqual(snippetHead('a\nb'),'a\nb');
        assert.strictEqual(snippetHead(Array.from({length:40},(_,i)=>'שורה '+i).join('\n')).split('\n').length,12);
        assert.ok(snippetHead('x'.repeat(5000)).length<=601);assert.ok(snippetHead('x'.repeat(5000)).endsWith('…'));
        assert.strictEqual(countLines(''),0);assert.strictEqual(countLines('a'),1);assert.strictEqual(countLines('a\nb\n'),2);assert.strictEqual(countLines('a\n\nb'),3);
        assert.strictEqual(snippetSize({chars:51234,lines:812}),'51,234 תווים · 812 שורות');assert.strictEqual(snippetSize({chars:1,lines:1}),'תו אחד · שורה אחת');
        """)

    def test_a_snippet_file_is_fetched_only_from_the_board_folder(self):
        self.pure_js(r"""
        for(const ok of ['snippets/snap-linux/m12.txt','snippets/shopflow/m3.md','snippets/a-1/m9.log'])assert.strictEqual(snippetFile(ok),ok);
        for(const bad of ['/snippets/a/m1.txt','snippets/../state.json','snippets/a/../../x','https://evil.example/x','//evil.example/x','snippets/a/m1.txt?x=1',
                          'snippets\\a\\m1.txt','snippets/a/.hidden','javascript:alert(1)','state.json','snippets/','',null,undefined,7,{}])
         assert.strictEqual(snippetFile(bad),null,String(bad));
        """)

    def test_a_big_unsent_snippet_is_not_pushed_into_local_storage(self):
        self.pure_js(r"""
        const small={cid:'1',text:'x',snippet:{text:'y'.repeat(1000),name:'a.log'}},big={cid:'2',text:'',snippet:{text:'y'.repeat(200001),name:'b.log'}};
        assert.strictEqual(forStorage(small),small);assert.strictEqual(forStorage({cid:'3',text:'x'}).cid,'3');
        const kept=forStorage(big);
        assert.deepStrictEqual(kept,{cid:'2',text:'',snippet:{name:'b.log',chars:200001,lost:true}});assert.strictEqual(big.snippet.text.length,200001);   // the live copy keeps its text
        """)

    def test_page_sends_and_shows_snippets(self):
        page = self.page()
        for part in ('state.snippet=', "getData('text/plain')", 'accept="text/*,.txt,.md,.log', 'snippetFile(', 'unicode-bidi:plaintext', "tr('Show all')", 'download'):
            self.assertIn(part, page)

    # ── code blocks ────────────────────────────────────────────────────────

    def test_code_is_coloured_by_what_each_piece_is(self):
        self.pure_js(r"""
        const show=(code,lang)=>codeTokens(code,lang).map(([type,text])=>type?type+'<'+text+'>':text).join('');
        // the pieces always add up to the code itself, whatever the language
        for(const [code,lang] of [['const a = "x"; // note\nreturn 42;','js'],['def f(x):\n    return x  # ok','python'],['SELECT * FROM t -- all\nWHERE id = 7;','sql'],
          ['echo "hi $USER" # greet\nls -la | rg x','sh'],['{"a": true, "n": 1.5, "s": "t"}','json'],['קוד לא ידוע <b>x</b>',''],['a: 1\n# c\nb: "x"','yaml']])
         assert.strictEqual(codeTokens(code,lang).map(t=>t[1]).join(''),code,lang);
        assert.strictEqual(show('const a = "x"; // note\nreturn 42;','js'),'k<const> a = s<"x">; c<// note>\nk<return> n<42>;');
        assert.strictEqual(show('def f(x):\n    return x  # ok','py'),'k<def> f(x):\n    k<return> x  c<# ok>');
        assert.strictEqual(show('SELECT * FROM t -- all','sql'),'k<SELECT> * k<FROM> t c<-- all>');
        assert.strictEqual(show('echo "hi" # greet','bash'),'k<echo> s<"hi"> c<# greet>');
        assert.strictEqual(show('{"a": true, "n": 1.5}','json'),'{s<"a">: k<true>, s<"n">: n<1.5>}');
        // a comment sign inside a string is part of the string; an unknown language is left plain
        assert.strictEqual(show('x = "a # b"','py'),'x = s<"a # b">');assert.strictEqual(show('const x = 1','klingon'),'const x = 1');
        // a diff is read by its lines
        assert.strictEqual(show('@@ -1 +1 @@\n-old\n+new\n same','diff'),'k<@@ -1 +1 @@>\nd<-old>\na<+new>\n same');
        // very long code is shown as it is: colouring must never make the page wait
        assert.deepStrictEqual(codeTokens('x'.repeat(60001),'js'),[['','x'.repeat(60001)]]);
        assert.deepStrictEqual(codeTokens('','js'),[]);
        """)

    # ── images and agent HTML ──────────────────────────────────────────────

    def test_only_this_threads_uploads_are_shown(self):
        self.pure_js(r"""
        for(const ok of ['uploads/snap-linux/m12-1.jpg','uploads/snap-linux/m3-4.webp','uploads/snap-linux/m3-2.png','uploads/snap-linux/m9-1.gif'])assert.strictEqual(imageFile(ok,'snap-linux'),ok);
        for(const bad of ['uploads/other/m1-1.jpg','uploads/snap-linux/m1-1.svg','uploads/snap-linux/m1.jpg','uploads/snap-linux/../x/m1-1.jpg','/uploads/snap-linux/m1-1.jpg',
                          'https://evil.example/m1-1.jpg','uploads/snap-linux/m1-1.jpg?x','uploads/snap-linux/m1-1.html','snippets/snap-linux/m1.txt','',null,7])
         assert.strictEqual(imageFile(bad,'snap-linux'),null,String(bad));
        // an agent's HTML is only ever the text file the server made of it
        assert.strictEqual(htmlFile('uploads/a-1/m7.html.txt','a-1'),'uploads/a-1/m7.html.txt');
        for(const bad of ['uploads/a-1/m7.html','uploads/b/m7.html.txt','uploads/a-1/m7-1.html.txt','https://x/m7.html.txt','uploads/a-1/../m7.html.txt',null])assert.strictEqual(htmlFile(bad,'a-1'),null,String(bad));
        // a photo is made smaller before it is sent: longest side 1600, never enlarged
        assert.deepStrictEqual(fitInside(4000,3000,1600),{w:1600,h:1200});assert.deepStrictEqual(fitInside(3000,4000,1600),{w:1200,h:1600});
        assert.deepStrictEqual(fitInside(800,600,1600),{w:800,h:600});assert.deepStrictEqual(fitInside(1601,1,1600),{w:1600,h:1});
        // what one message may carry: four pictures, 2,000,000 bytes each, 2,800,000 together (the request limit)
        const pic=bytes=>({bytes});
        assert.strictEqual(picturesFit([pic(900000),pic(900000),pic(900000)]),'');
        assert.ok(picturesFit([pic(1),pic(1),pic(1),pic(1),pic(1)]).includes('4'));assert.ok(picturesFit([pic(2000001)]).includes('2MB'));
        assert.ok(picturesFit([pic(1500000),pic(1500000)]).includes('יחד'));assert.strictEqual(picturesFit([]),'');
        // what goes into the stored outbox never holds picture bytes
        const kept=forStorage({cid:'1',text:'x',images:[{name:'a.jpg',type:'image/jpeg',data:'AAAA',url:'blob:x',w:1,h:1}]});
        assert.deepStrictEqual(kept,{cid:'1',text:'x',images:[{name:'a.jpg',lost:true}]});
        // a frame for an agent's HTML: no way out to the network, whatever the HTML says
        assert.ok(canvasDoc('<p>hi</p>').startsWith('<meta http-equiv="Content-Security-Policy"'));assert.ok(canvasDoc('<p>hi</p>').includes('<p>hi</p><scr'+'ipt>'));assert.ok(canvasDoc('<p>hi</p>').endsWith('</scr'+'ipt>'));
        // the frame says one thing to the page around it, its height, and that number is kept within limits
        // a diagram fills the width of its card: it may shrink to 60% of its own size before the card scrolls, and grow to 150% at most
        assert.ok(diagramStartsRight('flowchart RL\n  A --> B'));assert.ok(diagramStartsRight('%% note\n graph RL\nA-->B'));assert.ok(!diagramStartsRight('flowchart LR\nA-->B'));assert.ok(!diagramStartsRight('sequenceDiagram\nA->>B: x'));assert.ok(!diagramStartsRight('flowchart RLX'));
        assert.deepStrictEqual(diagramBox(936,76),{w:936,h:76,min:562,max:1404});assert.deepStrictEqual(diagramBox(1200,720),{w:1200,h:720,min:720,max:1800});assert.strictEqual(diagramBox(0,10),null);assert.strictEqual(diagramBox(undefined,undefined),null);
        assert.strictEqual(canvasHeight(40),120);assert.strictEqual(canvasHeight(300.4),300);assert.strictEqual(canvasHeight(99999),560);assert.strictEqual(canvasHeight('x'),380);assert.strictEqual(canvasHeight(undefined),380);assert.strictEqual(canvasHeight(-5),120);
        assert.ok(/connect-src 'none'/.test(canvasDoc('')));assert.ok(!/https?:/.test(canvasDoc('').split('>')[0]));
        """)

    def test_a_diagram_fills_its_card_and_scrolls_from_the_left(self):
        page = self.page()
        # the picture is laid out left to right (a wide one is cut on the far side, never on the first one), fills the card's
        # width and keeps its own shape; the floor and the cap of its size come from diagramBox
        self.assertIn('.diagram-body{direction:ltr;', page)
        self.assertIn('.diagram-pic{display:block;width:100%;height:auto;', page)
        for part in ("img.style.minWidth=box.min+'px'", "img.style.maxWidth=box.max+'px'", "scrollWatch.observe(body)", "figure.classList.toggle('scrolls',", "tr('Scroll sideways')",
                     "if(diagramStartsRight(code)&&body.scrollWidth>body.clientWidth){auto=true;body.scrollLeft=body.scrollWidth;}"):
            self.assertIn(part, page)
        # the full-screen reader shows it at its own size still
        self.assertIn("openReader({title:tr('Diagram'),image:pic.url,code,w:pic.w,h:pic.h})", page)
        # an SVG with only a viewBox has no size of its own in the browser's eyes: the reader takes the card's numbers first
        self.assertIn("nat={w:Number(r.w)||img.naturalWidth||0,h:Number(r.h)||img.naturalHeight||0};", page)
        # on a wide screen a card or the pictures take the whole column, while the text keeps its readable width
        self.assertIn('.msg{container-type:inline-size}', page)
        self.assertIn('@media (min-width:1280px){.md>.card,.content>.card,.content>.pics{width:max(100%,calc(100cqw - 86px));max-width:none}}', page)
        # pictures beside a message grow on a wide screen
        self.assertRegex(page, r'@media \(min-width:1280px\)\{[^}]*\.shot\{max-width:min\(100%,5\d0px\)\}')
        self.assertRegex(page, r'@media \(min-width:1600px\)\{[^}]*\.shot\{max-width:min\(100%,6\d0px\)\}')

    def test_a_picture_on_the_whole_screen_answers_the_keys_and_the_fingers(self):
        self.pure_js(r"""
        // the ladder of sizes: the next step up or down, from a size that may sit between steps; the ends hold
        assert.strictEqual(zoomStep(1,1),1.25);assert.strictEqual(zoomStep(1,-1),0.75);assert.strictEqual(zoomStep(0.71,1),0.75);assert.strictEqual(zoomStep(0.71,-1),0.67);
        assert.strictEqual(zoomStep(4,1),4);assert.strictEqual(zoomStep(0.25,-1),0.25);assert.strictEqual(zoomStep(0.5,1),0.67);assert.strictEqual(zoomStep('x',1),1.25);
        // a fit below the ladder (a wide drawing on a phone) stays where it is on −, and never jumps up; past the top the same
        assert.strictEqual(zoomStep(0.165,-1),0.165);assert.strictEqual(zoomStep(0.165,1),0.25);assert.strictEqual(zoomStep(6,1),6);assert.strictEqual(zoomStep(6,-1),4);
        // fit: the whole picture on the screen; a photo is never blown up, a drawing at most three times
        assert.ok(Math.abs(fitScale(1333,247,950,600,false)-950/1333)<1e-9);assert.strictEqual(fitScale(200,100,950,600,false),3);assert.strictEqual(fitScale(4000,3000,950,600,true),0.2);
        assert.strictEqual(fitScale(400,300,950,600,true),1);assert.strictEqual(fitScale(0,0,950,600,false),1);assert.strictEqual(fitScale(100,100,0,0,false),1);
        // a big drawing opens whole when that is still readable, else at its own size, to move over
        assert.strictEqual(startScale(0.71),0.71);assert.strictEqual(startScale(0.25),1);assert.strictEqual(startScale(0.5),0.5);assert.strictEqual(startScale(2.5),2.5);
        // the scroll that keeps the point under the finger (or the centre) where it was while the size changes
        assert.strictEqual(zoomKeep(0,150,1,2),150);assert.strictEqual(zoomKeep(150,150,2,1),0);assert.strictEqual(zoomKeep(100,50,1,1),100);
        // the keys, through the one key map, only while the reader shows a picture and he is not writing
        const k=(code,extra)=>Object.assign({code,key:''},extra||{}),inPic={typing:false,options:3,mac:true,reader:true},plain={typing:false,options:3,mac:true};
        assert.strictEqual(keyAction(k('ArrowLeft'),inPic),'pan-left');assert.strictEqual(keyAction(k('ArrowDown'),inPic),'pan-down');assert.strictEqual(keyAction(k('ArrowUp',{shiftKey:true}),inPic),'pan-up-page');
        assert.strictEqual(keyAction(k('Equal'),inPic),'zoom-in');assert.strictEqual(keyAction(k('Equal',{shiftKey:true}),inPic),'zoom-in');assert.strictEqual(keyAction(k('NumpadAdd'),inPic),'zoom-in');
        assert.strictEqual(keyAction(k('Minus'),inPic),'zoom-out');assert.strictEqual(keyAction(k('NumpadSubtract'),inPic),'zoom-out');
        assert.strictEqual(keyAction(k('Digit0'),inPic),'zoom-fit');assert.strictEqual(keyAction(k('Numpad0'),inPic),'zoom-fit');assert.strictEqual(keyAction(k('Digit1'),inPic),'zoom-100');
        assert.strictEqual(keyAction(k('Escape'),inPic),'escape');
        // the browser keeps its own zoom; the digits of the answers do not fire from the reader; nothing changes outside it
        assert.strictEqual(keyAction(k('Equal',{metaKey:true}),inPic),null);assert.strictEqual(keyAction(k('Digit2'),inPic),'answer-2');
        assert.strictEqual(keyAction(k('Equal'),plain),null);assert.strictEqual(keyAction(k('Digit0'),plain),null);assert.strictEqual(keyAction(k('Digit1'),plain),'answer-1');assert.strictEqual(keyAction(k('ArrowLeft'),plain),null);
        assert.strictEqual(keyAction(k('Equal'),{typing:true,options:0,mac:true,reader:true}),null);
        """)
        page = self.page()
        script = page.split('<script>')[1]
        for part in ("reader:!!readerPic&&!$('reader').hidden", "readerPic[action.startsWith('pan-')?'pan':'zoom'](action)", "function picturePane(body,img,r)",
                     "if(r.code&&diagramStartsRight(r.code))body.scrollLeft=body.scrollWidth;", "addEventListener('wheel'", "addEventListener('dblclick'", "pointerType==='mouse'",
                     ".reader-body.pic{direction:ltr;", "touch-action:pan-x pan-y", "tr('Fit to the screen (0)')", "tr('Full size (1)')"):
            self.assertIn(part, page, part)
        self.assertRegex(page, r"\[\[\['\+'\],\['−'\],\['0'\],\['1'\]\],tr\('A picture or diagram full screen")

    def test_esc_inside_an_agents_frame_reaches_the_page(self):
        page = self.page()
        # the tail the page adds to an agent's HTML says one more word: Esc; the page acts on that exact word only
        self.assertIn('addEventListener("keydown",function(e){if(e.key==="Escape"||e.code==="Escape"){e.preventDefault();try{parent.postMessage({kind:"suda-canvas",key:"Escape"},"*")}catch(e){}}})', page)
        self.assertIn("if(e.data.key==='Escape'){", page)
        self.assertIn("if(!$('reader').hidden&&$('reader').contains(frame))closeReader();", page)
        self.assertIn("const row=frame.closest('#log .msg');if(row){if(row.dataset.key!==cursor){cursor=row.dataset.key;paintCursor();}row.focus({preventScroll:true});}", page)
        # every window and popup closes on Esc, in the order of what is on top; the toasts last
        chain = page.split('function stepBack(){')[1].split('return true;')[0]
        for part in ('held.undo()', 'hideCard()', 'closeHelp()', 'closeRun()', 'closeNotify()', 'closeAnswer()', 'closeReader()', 'closeSheet()', 'closeSnip()', 'closeTopic()', 'closeSwitcher()', 'closeFind()', 'closeDetails()', 'foldTasks()', 'dismissToasts()'):
            self.assertIn(part, chain, part)
        self.assertLess(chain.index('hideCard()'), chain.index('closeHelp()'))
        self.assertGreater(chain.index('dismissToasts()'), chain.index('foldTasks()'))

    def test_several_pictures_each_with_its_own_caption(self):
        self.pure_js(r"""
        // a caption is one line of plain text, at most 500 characters
        assert.strictEqual(captionOf('  המסך\n אחרי   העדכון  '),'המסך אחרי העדכון');assert.strictEqual(captionOf(null),'');assert.strictEqual(captionOf(7),'');
        assert.strictEqual(captionOf('x'.repeat(600)).length,500);
        // the order before sending: one step earlier or later, never off the ends, and his list itself is not touched
        const list=[{name:'a'},{name:'b'},{name:'c'}],names=l=>l.map(p=>p.name).join('');
        assert.strictEqual(names(movePicture(list,2,-1)),'acb');assert.strictEqual(names(movePicture(list,0,1)),'bac');
        assert.strictEqual(movePicture(list,0,-1),list);assert.strictEqual(movePicture(list,2,1),list);assert.strictEqual(movePicture(list,7,-1),list);assert.strictEqual(movePicture(list,1,0),list);
        assert.strictEqual(names(list),'abc');
        // what is sent: each picture with its own caption, in his order; no caption field where he wrote none
        assert.deepStrictEqual(picturesForSend([{name:'a.jpg',type:'image/jpeg',data:'AA',url:'blob:1',bytes:2,w:1,h:1,caption:' לפני '},{name:'b.png',type:'image/png',data:'BB',caption:'  '},{name:'c.png',type:'image/png',data:'CC'}]),
          [{name:'a.jpg',type:'image/jpeg',data:'AA',caption:'לפני'},{name:'b.png',type:'image/png',data:'BB'},{name:'c.png',type:'image/png',data:'CC'}]);
        // what is shown: the files the server stored for this thread, or his own on their way, each with its caption
        const m={images:[{file:'uploads/t1/m4-1.jpg',name:'a.jpg',w:10,h:5,caption:'לפני'},{file:'uploads/other/m4-2.jpg',caption:'x'},{file:'uploads/t1/m4-3.png',caption:7},null,'x',{url:'blob:9',data:'AA',name:'c.jpg',caption:'בדרך'},{url:'https://evil.example/x.jpg',name:'d.jpg'}]};
        assert.deepStrictEqual(picturesOf(m,'t1'),[{src:'uploads/t1/m4-1.jpg',name:'a.jpg',w:10,h:5,caption:'לפני'},{src:'uploads/t1/m4-3.png',name:'',w:0,h:0,caption:''},{src:'blob:9',name:'c.jpg',w:0,h:0,caption:'בדרך'}]);
        assert.deepStrictEqual(picturesOf({images:'x'},'t1'),[]);assert.deepStrictEqual(picturesOf({},'t1'),[]);assert.deepStrictEqual(picturesOf(null,'t1'),[]);
        // the stored outbox keeps the captions he wrote, never the bytes
        assert.deepStrictEqual(forStorage({cid:'1',text:'',images:[{name:'a.jpg',data:'AAAA',caption:'לפני'},{name:'b.jpg',data:'BBBB',caption:''}]}).images,[{name:'a.jpg',caption:'לפני',lost:true},{name:'b.jpg',lost:true}]);
        """)

    def test_a_caption_reaches_the_page_only_as_text(self):
        # A caption is written by him or by an agent; it is shown as text, never as markup.
        self.assertIn("el('figcaption','',pic.caption)", self.page())
        self.assertNotIn('figcaption.innerHTML', self.page())

    def test_message_text_can_be_selected_and_a_tap_shows_the_actions(self):
        # A long press belongs to the phone (it selects text); the page only acts on a short tap and on a sideways drag.
        self.pure_js(r"""
        const touch=more=>Object.assign({dragging:false,plain:true,picked:false,ms:120,moved:2},more);
        assert.strictEqual(tapOf(touch()),true);
        assert.strictEqual(tapOf(touch({ms:350})),false,'a long press is not a tap');assert.strictEqual(tapOf(touch({moved:10})),false);
        assert.strictEqual(tapOf(touch({picked:true})),false,'a tap that only clears a selection');
        assert.strictEqual(tapOf(touch({plain:false})),false,'a picture or a code block has its own tap');assert.strictEqual(tapOf(touch({dragging:true})),false);
        """)
        page = self.page()
        import re
        for rule in re.findall(r'[^{}\n]*\.msg[^{}\n]*\{[^}]*user-select:\s*none[^}]*\}', page):
            self.assertRegex(rule.split('{')[0], r'msg-acts|hover-time', rule)      # only the bar and the clock stay out of a selection
        self.assertNotIn('touch-callout:none;user-select:none', page.split('.ch{')[0])
        self.assertNotIn("openSheet('msg',mid);}\n    },500)", page)
        self.assertIn(".coarse .msg{touch-action:pan-y}", page)

    def test_rows_show_when_the_last_message_came_and_a_quiet_tower_is_an_icon(self):
        self.pure_js(r"""
        const at=(y,mo,d,h,mi)=>new Date(y,mo-1,d,h,mi).getTime()/1000,now=at(2026,11,16,14,0);
        assert.strictEqual(agoShort(now-20,now),'עכשיו');assert.strictEqual(agoShort(now+50,now),'עכשיו');
        assert.strictEqual(agoShort(now-60,now),'1 דק׳');assert.strictEqual(agoShort(now-59*60-59,now),'59 דק׳');
        assert.strictEqual(agoShort(now-3600,now),'1 שע׳');assert.strictEqual(agoShort(at(2026,11,15,23,0),now),'15 שע׳');
        assert.strictEqual(agoShort(at(2026,11,15,13,0),now),'אתמול');assert.strictEqual(agoShort(at(2026,11,13,9,0),now),'3 ימים');
        assert.strictEqual(agoShort(at(2026,11,9,9,0),now),'09/11');assert.strictEqual(agoShort(at(2026,3,4,9,0),now),'04/03');
        // the tower's thread is only an icon while nothing in it waits for him and nothing in it is new
        const tower=more=>Object.assign({id:'tower',status:'open',state:'working',messages:[],tasks:[]},more);
        assert.strictEqual(towerQuiet(tower(),0),true);assert.strictEqual(towerQuiet(tower(),2),false);
        assert.strictEqual(towerQuiet(tower({state:'on-owner'}),0),false);assert.strictEqual(towerQuiet(tower({reminder:{ts:1,until:2}}),0),false);
        assert.strictEqual(towerQuiet(null,0),false);assert.strictEqual(towerQuiet(tower({status:'closed'}),0),false);
        """)
        page = self.page()
        for part in ('id="tower-go"', 'class="side-tools"', "go.hidden=!quiet;", "agoShort(lastAt,now())"):
            self.assertIn(part, page)

    def test_his_tasks_stand_apart_from_the_agents(self):
        self.pure_js(r"""
        const tasks=[{n:1,text:'a',status:'working',owner:'worker-a'},{n:2,text:'b',status:'todo',owner:'owner'},{n:3,text:'c',status:'on-owner',owner:'tower'},
                     {n:4,text:'d',status:'done',owner:'Owner'},{n:5,text:'e',status:'done',owner:'fork'},{n:6,text:'f',status:'blocked',owner:' human '},{n:7,text:'g',status:'todo'}];
        // his: the ones he owns, and the ones that wait for him
        assert.deepStrictEqual(tasks.filter(mineTask).map(k=>k.n),[2,3,4,6]);
        assert.strictEqual(mineTask({status:'todo',owner:'owner-bot'}),false);assert.strictEqual(mineTask(null),false);assert.strictEqual(mineTask({status:'todo',owner:'me'}),true);
        const groups=taskGroups(tasks);
        assert.deepStrictEqual([groups.mine.map(k=>k.n),groups.theirs.map(k=>k.n)],[[2,3,4,6],[1,5,7]]);
        assert.deepStrictEqual(taskGroups(null),{mine:[],theirs:[]});
        // in the bar and in words an open task of his is "on him", whatever state it carries; a done one is done
        const stats=taskStats(tasks),seg=Object.fromEntries(stats.segments.map(s=>[s.status,s.n]));
        assert.deepStrictEqual(seg,{done:2,working:1,'on-owner':3,todo:1});
        assert.ok(stats.line.startsWith('3 עליך'));assert.ok(stats.line.includes('2 הושלמו'));assert.ok(stats.line.endsWith('(מתוך 7)'));
        
        // the chips: whose tasks (his, the agents', or both) and in what order; one choice for every list
        const stamped=tasks.map((k,i)=>({...k,ts:100+i})),shape=prefs=>taskView(stamped,prefs).map(part=>part.label+':'+part.tasks.map(k=>k.n).join(','));
        const both={mine:true,agents:true,order:'status'};
        assert.deepStrictEqual(shape(both),['עליך:2,3,6','בעבודה:1','לביצוע:7','הושלם:4,5']);
        assert.deepStrictEqual(shape({...both,agents:false}),['עליך:2,3,6','הושלם:4']);
        assert.deepStrictEqual(shape({...both,mine:false}),['בעבודה:1','לביצוע:7','הושלם:5']);
        assert.deepStrictEqual(shape({...both,order:'recent'}),[':7,6,5,4,3,2,1']);assert.deepStrictEqual(shape({mine:true,agents:false,order:'recent'}),[':6,4,3,2']);
        assert.deepStrictEqual(shape(undefined),shape(both));
        assert.deepStrictEqual(taskView([{n:1,text:'a',status:'strange'}],both).map(p=>p.key),['todo']);assert.deepStrictEqual(taskView(null,both),[]);
        assert.deepStrictEqual(taskView([{n:1,text:'a',status:'todo',owner:'fork'}],{...both,agents:false}),[]);
        assert.deepStrictEqual(taskView([{n:2,text:'b',status:'todo'},{n:9,text:'c',status:'todo'}],{...both,order:'recent'})[0].tasks.map(k=>k.n),[9,2]);
        // the choice as it is kept; an old or broken value reads as "both, by state"
        assert.deepStrictEqual(taskPrefs(''),both);assert.deepStrictEqual(taskPrefs('{'),both);assert.deepStrictEqual(taskPrefs('owner'),both);
        assert.deepStrictEqual(taskPrefs('recent'),{...both,order:'recent'});assert.deepStrictEqual(taskPrefs('{"mine":false,"agents":false,"order":"x"}'),both);
        assert.deepStrictEqual(taskPrefs('{"mine":false,"order":"recent"}'),{mine:false,agents:true,order:'recent'});
        // a press on a chip; the last one standing brings the other back instead of leaving nothing
        assert.deepStrictEqual(toggleWho(both,'mine'),{...both,mine:false});assert.deepStrictEqual(toggleWho({...both,mine:false},'mine'),both);
        assert.deepStrictEqual(toggleWho({...both,mine:false},'agents'),both);assert.deepStrictEqual(toggleWho({...both,agents:false},'mine'),both);
        """)
        page = self.page()
        for part in ("taskView(t.tasks,mode)", "store.set('tasks-view',JSON.stringify(next))", "toggleWho(mode,'mine')", ".task.mine{", ".tasks.open{position:relative;z-index:1;background:var(--panel)", 'id="tasks-views"'):
            self.assertIn(part, page)

    def test_the_question_at_the_top_can_be_put_away_and_never_takes_the_room(self):
        page = self.page()
        # put away with the questions open then (a new question shows again; see pinAway), by the ✕ or a sideways pull;
        # the copy in the messages stays
        for part in ("pinAway(store.get('pin-off:'+t.id),qs.map(x=>x.id))", "store.set('pin-off:'+id,openQuestions(thread(id)).map(q=>q.id).join(' '))",
                     "Math.abs(e.clientX-pull.x)>=PULL_AWAY", "button('','icon pin-x',()=>dismissPin(t.id))",
                     ".pin{flex:none;max-height:calc(var(--app-h,100dvh)*.36);overflow-y:auto;"):
            self.assertIn(part, page)

    def test_a_copied_command_starts_with_its_own_first_character(self):
        # He copied "! ultra install …" from a block inside a list and it reached Termux with spaces before the "!".
        self.pure_js(r"""
        // a block written inside a list item is indented with it: its lines lose the fence's own indent
        const html=markdown('1. שלב ראשון:\n   ```sh\n   $ adb connect 192.0.2.54:5555\n   ! ultra logs --tail 50\n     --follow\n   ```\nסוף');
        assert.ok(html.includes('<pre class="lang-sh"><code>$ adb connect 192.0.2.54:5555\n! ultra logs --tail 50\n  --follow</code></pre>'),html);
        assert.ok(markdown('```\n! ultra install -r a.apk\n```').includes('<code>! ultra install -r a.apk</code>'));
        assert.ok(markdown('```py\ndef f():\n    return 1\n```').includes('def f():\n    return 1'),'a block that is not indented keeps the indentation inside it');
        // what reaches the clipboard from code: no shared indent, no spaces at the ends, no empty lines around, no hidden marks
        assert.strictEqual(cleanCopy('   $ adb connect x\n   ! ultra logs  \n',true),'$ adb connect x\n! ultra logs');
        assert.strictEqual(cleanCopy('\n\n  ! ultra install -r a.apk \n\n',true),'! ultra install -r a.apk');
        assert.strictEqual(cleanCopy('\u200f! ultra\u00a0install\u200e \u2066-r\u2069\ufeff',true),'! ultra install -r');
        assert.strictEqual(cleanCopy('def f():\n    return 1\n\n    # x',true),'def f():\n    return 1\n\n    # x');
        assert.strictEqual(cleanCopy('\tif x:\r\n\t\ty()\r\n',true),'if x:\n\ty()');
        assert.strictEqual(cleanCopy('',true),'');assert.strictEqual(cleanCopy(null,true),'');assert.strictEqual(cleanCopy('  \n \n',true),'');
        // from prose: the ends are trimmed and the marks go; the words stay as written
        assert.strictEqual(cleanCopy(' \u200fworker-a אחראי על הכפתור. \n',false),'worker-a אחראי על הכפתור.');
        assert.strictEqual(cleanCopy('שורה א\n  שורה ב',false),'שורה א\n  שורה ב');
        for(const mark of ['\u200e','\u200f','\u202a','\u202b','\u202c','\u202d','\u202e','\u2066','\u2067','\u2068','\u2069','\u200b','\u061c'])assert.strictEqual(cleanCopy(mark+'! x',true),'! x',mark.codePointAt(0).toString(16));
        """)
        page = self.page()
        for part in ("copyText(cleanCopy(code,true))", "document.addEventListener('copy',e=>{", "!node.closest('#log,.md')", "cleanCopy(selection.toString(),!!node.closest('pre,code'))"):
            self.assertIn(part, page)

    def test_the_page_names_its_icons_for_whoever_reads_it_without_running_it(self):
        # A launcher that makes a web app of Suda reads the HTML and the manifest; it runs no script.
        for name in ('suda.html', 'slack.html'):
            html = (ROOT / name).read_text(encoding='utf-8').split('<style>')[0]
            links = re.findall(r'<link rel="(icon|apple-touch-icon)"[^>]*href="([^"]+)"', html)
            self.assertTrue(any(rel == 'icon' for rel, _ in links), name)
            # the old address is still what some launchers hold: it names the same manifest and the same icons
            for line in ('<link rel="manifest" href="manifest.json">', '<link rel="apple-touch-icon" sizes="180x180" href="icons/suda2-180.png">',
                         '<link rel="icon" type="image/png" sizes="512x512" href="icons/suda2-512.png">', '<link rel="icon" type="image/png" sizes="192x192" href="icons/suda2-192.png">'):
                self.assertIn(line, html, name)
            for _, href in links:
                self.assertIsNone(re.match(r'[a-z]+:|/', href), href)        # beside the page, so the https address serves it
                self.assertTrue((ROOT / href).is_file(), href)
        self.assertEqual((ROOT / 'favicon.ico').read_bytes()[:4], b'\x00\x00\x01\x00')
        # the icon he chose, under the old names (for whoever still asks for them) and the new ones alike
        for size in ('32', '180', '192', '512', 'maskable-512'):
            self.assertEqual((ROOT / f'icons/suda-{size}.png').read_bytes(), (ROOT / f'icons/suda2-{size}.png').read_bytes(), size)
        self.assertIn('<circle cx="256" cy="150" r="70" fill="#d4456b"/>', (ROOT / 'icons/suda.svg').read_text(encoding='utf-8'))
        touch = (ROOT / 'icons/suda2-180.png').read_bytes()
        self.assertEqual((touch[:4], touch[16:24], touch[25]), (b'\x89PNG', (180).to_bytes(4, 'big') * 2, 2))   # 180×180, no transparency
        self.assertIn('<link rel="apple-touch-icon" sizes="180x180" href="icons/suda2-180.png">', self.page())

    # ── asking the tower to run a command it wrote ─────────────────────────

    def test_only_an_exact_plain_command_of_the_tower_can_be_asked_to_run(self):
        self.pure_js(r"""
        const crypto=require('crypto'),real=text=>crypto.createHash('sha256').update(text,'utf8').digest('hex');
        // the hash is the real SHA-256, on the classic vectors and on every length around the block edges
        assert.strictEqual(sha256(''),'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
        assert.strictEqual(sha256('abc'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
        for(let n=0;n<=200;n++){const text='! ultra install -r ~/a.apk '.repeat(9).slice(0,n);assert.strictEqual(sha256(text),real(text),'length '+n);}
        for(const text of ['שלום עולם','a'.repeat(5000),'! x\n! y','\u{1F600} emoji'])assert.strictEqual(sha256(text),real(text),text.slice(0,20));
        // the blocks of a text, numbered as the renderer finds them
        const text='להתקנה:\n```\n! ultra install -r ~/a.apk\n```\nואז:\n1. שלב\n   ```sh\n   ! adb devices\n   ! ultra logs --tail 50\n\n   ```\n```mermaid\ngraph TD;A-->B\n```\nסוף\n```\n! tail';
        assert.deepStrictEqual(fencedBlocks(text).map(b=>b.length),[1,3,1,1]);
        assert.strictEqual(fencedBlocks(text).length,(markdown(text).match(/<pre/g)||[]).length,'the page shows exactly as many blocks');
        assert.deepStrictEqual(fencedBlocks(''),[]);assert.deepStrictEqual(fencedBlocks(null),[]);assert.deepStrictEqual(fencedBlocks('```'),[[]]);
        const tower={id:'m14',from:'tower',text};
        assert.strictEqual(runnable(tower,0),'! ultra install -r ~/a.apk');
        assert.strictEqual(runnable(tower,1),'! adb devices\n! ultra logs --tail 50','inside a list: no indent, no empty line');
        assert.strictEqual(runnable(tower,2),'','a diagram is not a command');assert.strictEqual(runnable(tower,3),'! tail');assert.strictEqual(runnable(tower,4),'');
        for(const bad of [-1,1.5,'0',null,undefined])assert.strictEqual(runnable(tower,bad),'',String(bad));
        // never from anyone but the tower, never without the "! " at the start of every line
        for(const from of ['fork','owner','Tower','',undefined])assert.strictEqual(runnable({id:'m1',from,text},0),'',String(from));
        assert.strictEqual(runnable({from:'tower',text},0),'','a message the server has not numbered yet');
        const one=body=>runnable({id:'m1',from:'tower',text:'```\n'+body+'\n```'},0);
        assert.strictEqual(one('! ls -la'),'! ls -la');assert.strictEqual(one('  ! ls -la  '),'! ls -la');
        for(const bad of ['ls -la','$ ls','!ls','! ','!  ','! ls\nrm -rf x','rm -rf x\n! ls','#! ls',''])assert.strictEqual(one(bad),'',JSON.stringify(bad));
        // never anything he cannot see exactly: marks that change direction, no-break spaces, tabs, other alphabets
        for(const bad of ['! ls ‮-la','! ls -la','‏! ls','! ls\t-la','! ls а.txt','! echo שלום','! ls ​','! café','! ls\u007f'])assert.strictEqual(one(bad),'',JSON.stringify(bad));
        assert.strictEqual(one(Array.from({length:10},(_,i)=>'! echo '+i).join('\n')).split('\n').length,10);
        assert.strictEqual(one(Array.from({length:11},(_,i)=>'! echo '+i).join('\n')),'');assert.strictEqual(one('! '+'a'.repeat(1999)),'');assert.strictEqual(one('! '+'a'.repeat(1998)).length,2000);
        // the same bytes as the server: a fence after spaces and tabs only; a line loses spaces, tabs and \r at its ends, nothing else
        const whole=text=>runnable({id:'m1',from:'tower',text},0);
        assert.strictEqual(whole(' ```\n! a\n```'),'','a no-break space before the backticks is not a fence');assert.strictEqual(whole('\f```\n! a\n```'),'');
        assert.strictEqual(whole(' \t```sh\r\n! a\r\n```'),'! a');assert.deepStrictEqual(fencedBlocks(' \t```sh\r\n! a\r\n```'),[['! a\r']]);
        assert.strictEqual(one('! ls\r'),'! ls');assert.strictEqual(one('\t ! ls \t'),'! ls');
        for(const bad of ['﻿! ls',' ! ls','! ls ','\x0c! ls','! ls\x1c',' ! ls','! ls\x85'])assert.strictEqual(one(bad),'',JSON.stringify(bad));
        // one request at a time for a block: while his reply is still waiting, it is not asked again
        const ask=more=>Object.assign({from:'owner',run:{msg_id:'m14',block_index:0,sha256:'x'}},more);
        assert.strictEqual(runAsked([ask({status:'pending'})],'m14',0),true);assert.strictEqual(runAsked([ask({delivery:'sending'})],'m14',0),true);
        assert.strictEqual(runAsked([ask({status:'acked'})],'m14',0),false);assert.strictEqual(runAsked([ask({delivery:'failed'})],'m14',0),false);
        assert.strictEqual(runAsked([ask({status:'pending'})],'m14',1),false);assert.strictEqual(runAsked([ask({status:'pending'})],'m15',0),false);
        assert.strictEqual(runAsked([ask({status:'pending',from:'tower'})],'m14',0),false);assert.strictEqual(runAsked(null,'m14',0),false);
        """)

    def test_the_page_asks_and_never_runs(self):
        page = self.page()
        # what is sent names the block and carries no command; the server is asked only through the usual reply
        for part in ("run:{msg_id:ask.msg,block_index:ask.index,sha256:sha256(ask.command)}", "state.run={msg_id:msg.run.msg_id,block_index:msg.run.block_index,sha256:msg.run.sha256}",
                     "text:tr('▶ Run the command from message {id}',{id:ask.msg})", "if(m.from==='tower'&&m.id&&t.status==='open'&&has('run')){", "pres.length===fencedBlocks(m.text).length",
                     "runnable(m,ask.index)!==ask.command", "if(typeof msg.last==='string')state.last=msg.last;", "last:t.messages.length?t.messages.at(-1).id:''", "command.split('\\n').map(line=>el('div','run-line',line))", 'role="alertdialog"'):
            self.assertIn(part, page)
        script = page.split('<script>')[1]
        for never in ('eval(', 'new Function', 'importScripts', 'child_process', 'ask.command}'):
            self.assertNotIn(never, script)
        # agreeing is a press on the button itself: no key sends it
        self.assertNotIn("sendRun();}", script.split("if(!$('run').hidden){")[1].split("return;")[0])

    # ── a video an agent attached ──────────────────────────────────────────

    def test_a_video_plays_only_this_threads_own_file_in_a_box_of_its_own_shape(self):
        self.pure_js(r"""
        for(const ok of ['uploads/snap-linux/m12-v1.mp4','uploads/snap-linux/m3-v2.webm'])assert.strictEqual(videoFile(ok,'snap-linux'),ok);
        for(const bad of ['uploads/other/m1-v1.mp4','uploads/snap-linux/m1-v1.mov','uploads/snap-linux/m1-1.mp4','uploads/snap-linux/m1.webm','uploads/snap-linux/../x/m1-v1.mp4',
                          '/uploads/snap-linux/m1-v1.mp4','https://evil.example/m1-v1.mp4','uploads/snap-linux/m1-v1.mp4?x','/Users/x/out/demo.mp4','file:///Users/x/demo.mp4',null,7,{}])
          assert.strictEqual(videoFile(bad,'snap-linux'),null,String(bad));
        // the box takes the video's own shape; an unknown or a strange one is held in bounds
        assert.strictEqual(clipRatio(1920,1080),1920/1080);assert.strictEqual(clipRatio(1080,1920),1080/1920);
        assert.strictEqual(clipRatio(0,0),16/9);assert.strictEqual(clipRatio('x',5),16/9);assert.strictEqual(clipRatio(10000,10),4);assert.strictEqual(clipRatio(10,10000),0.25);
        // what a message plays: the poster only when it is the one stored beside the video
        assert.deepStrictEqual(videosOf({videos:[{file:'uploads/t1/m4-v1.mp4',poster:'uploads/t1/m4-v1.jpg',name:'demo.mp4',caption:'  ההדגמה  ',w:320,h:180,seconds:1.5}]},'t1'),
          [{src:'uploads/t1/m4-v1.mp4',poster:'uploads/t1/m4-v1.jpg',name:'demo.mp4',caption:'ההדגמה',ratio:320/180,seconds:1.5}]);
        assert.deepStrictEqual(videosOf({videos:[{file:'uploads/t1/m4-v1.webm',poster:'https://evil.example/x.jpg'},{file:'/Users/x/demo.mp4'},null,'x']},'t1'),
          [{src:'uploads/t1/m4-v1.webm',poster:'',name:'',caption:'',ratio:16/9,seconds:0}]);
        assert.deepStrictEqual(videosOf({videos:[{file:'uploads/t1/m4-v1.mp4',poster:'uploads/t1/m5-v1.jpg'}]},'t1')[0].poster,'');
        assert.deepStrictEqual(videosOf({},'t1'),[]);assert.deepStrictEqual(videosOf(null,'t1'),[]);
        """)

    def test_a_video_never_plays_by_itself_and_its_player_keeps_the_finger_and_the_menu(self):
        page = self.page()
        node = page.split('function clipVideo(clip){')[1].split('\nfunction ')[0]        # the player is made here; clipNode places it (or holds it on a slow link)
        self.assertNotIn('.play()', page.split('function clipNode(clip,bytes){')[1].split('\nfunction ')[0])
        self.assertIn("video.preload='metadata'", node)
        self.assertIn('video.autoplay=false', node)
        self.assertIn("setAttribute('playsinline','')", node)
        self.assertNotIn('.play()', node)
        self.assertNotIn('muted', node)
        self.assertIn('.clip-box{direction:ltr', page)          # the timeline runs left to right inside the Hebrew page
        self.assertIn(".snip-body,video'))return;", page.split("log.addEventListener('pointerdown'")[1].split('});')[0])
        self.assertIn(".snip-body,video')", page.split("log.addEventListener('contextmenu'")[1].split('});')[0])

    # ── a voice message ────────────────────────────────────────────────────

    def test_a_voice_message_is_held_locked_or_thrown_away_like_in_whatsapp(self):
        self.pure_js(r"""
        // where the finger went while it holds the mic: up locks, far to either side throws away, the rest keeps recording
        assert.strictEqual(micMove(0,0),'hold');assert.strictEqual(micMove(10,-30),'hold');assert.strictEqual(micMove(4,-56),'lock');assert.strictEqual(micMove(-20,-90),'lock');
        assert.strictEqual(micMove(90,4),'cancel');assert.strictEqual(micMove(-120,-30),'cancel');assert.strictEqual(micMove(60,0),'hold');
        assert.strictEqual(micMove(100,-100),'lock','straight up-and-aside reads as up');assert.strictEqual(micMove(0,80),'hold','down is nothing');
        assert.strictEqual(clockOf(0),'0:00');assert.strictEqual(clockOf(7.9),'0:07');assert.strictEqual(clockOf(75),'1:15');assert.strictEqual(clockOf(600),'10:00');assert.strictEqual(clockOf(-3),'0:00');assert.strictEqual(clockOf('x'),'0:00');
        // only this thread's own recording is ever played
        for(const ok of ['uploads/snap-linux/m12.webm','uploads/snap-linux/m3.m4a','uploads/snap-linux/m3.ogg','uploads/snap-linux/m9.mp4'])assert.strictEqual(voiceFile(ok,'snap-linux'),ok);
        for(const bad of ['uploads/other/m1.webm','uploads/snap-linux/m1.mp3','uploads/snap-linux/m1-1.webm','uploads/snap-linux/../x/m1.webm','/uploads/snap-linux/m1.webm','https://evil.example/m1.webm','uploads/snap-linux/m1.webm?x','uploads/snap-linux/m1.html',null,7])
          assert.strictEqual(voiceFile(bad,'snap-linux'),null,String(bad));
        // what a message plays, and where its words stand
        assert.deepStrictEqual(voiceOf({voice:{file:'uploads/t1/m4.webm',seconds:12.4,state:'transcribing'}},'t1'),{src:'uploads/t1/m4.webm',seconds:12,state:'transcribing'});
        assert.deepStrictEqual(voiceOf({voice:{file:'uploads/t1/m4.webm',seconds:3,state:'failed'}},'t1'),{src:'uploads/t1/m4.webm',seconds:3,state:'failed'});
        assert.deepStrictEqual(voiceOf({voice:{file:'uploads/t1/m4.webm'}},'t1'),{src:'uploads/t1/m4.webm',seconds:0,state:'done'});
        assert.deepStrictEqual(voiceOf({voice:{data:'AA',url:'blob:http://x/1',seconds:5}},'t1'),{src:'blob:http://x/1',seconds:5,state:'sending'});
        for(const bad of [{voice:{file:'uploads/other/m4.webm'}},{voice:{data:'AA',url:'https://evil.example/a.webm'}},{voice:'x'},{voice:null},{},null,{voice:{lost:true,seconds:3}}])assert.strictEqual(voiceOf(bad,'t1'),null,JSON.stringify(bad));
        // the stored outbox never holds the audio itself
        assert.deepStrictEqual(forStorage({cid:'1',text:'',voice:{type:'audio/webm',data:'AAAA',seconds:7,bytes:3,url:'blob:x'}}),{cid:'1',text:'',voice:{type:'audio/webm',seconds:7,lost:true}});
        """)
        page = self.page()
        # the page records and sends; the key and the transcription never come near it
        for part in ("state.voice={type:msg.voice.type,data:msg.voice.data,seconds:msg.voice.seconds}", "const voice=empty&&!!t&&t.status==='open'&&has('voice');", "audioBitsPerSecond:32000",
                     "trayStore.put(sentKey(msg.cid),{voice:{type,data,seconds,bytes:me.blob.size}})", "if(seconds>=VOICE_MAX){me.full=true;finishRec('hold');}", 'id="mic"', 'id="rec-cancel"', 'id="rec-send"'):
            self.assertIn(part, page)
        for never in ('soniox', 'Soniox', 'api_key', 'apiKey'):
            self.assertNotIn(never, page)

    # ── files he pastes, drops or picks; the microphone ────────────────────

    def test_a_pasted_or_dropped_file_is_taken_by_what_it_is(self):
        self.pure_js(r"""
        // by the type the browser gives, and by the name when it gives none (a paste inside an app's own browser)
        for(const [name,type] of [['a.png','image/png'],['shot','image/jpeg'],['IMG_1.HEIC',''],['x.webp',''],['pasted',"image/svg+xml"],['a.JPG','application/octet-stream']])assert.strictEqual(fileKind(name,type),'image',name+' '+type);
        for(const [name,type] of [['a.txt','text/plain'],['server.log',''],['data.json','application/json'],['x','text/csv'],['deploy.sh',''],['conf.yaml','application/x-yaml'],['q.SQL',''],['a.py','application/octet-stream'],['fix.patch','']])assert.strictEqual(fileKind(name,type),'text',name+' '+type);
        for(const [name,type] of [['a.pdf','application/pdf'],['a.zip','application/zip'],['movie.mp4','video/mp4'],['noext',''],['a.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document'],[null,null]])assert.strictEqual(fileKind(name,type),'other',name+' '+type);
        // a file whose name and type say nothing is text when its bytes read as text
        const bytes=text=>new TextEncoder().encode(text);
        assert.strictEqual(textLike(bytes('2026-11-16 12:00 ERROR שגיאה בשרת\n\tat line 4\r\n')),true);
        assert.strictEqual(textLike(new Uint8Array([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0,0,0,13])),false);assert.strictEqual(textLike(new Uint8Array([0x25,0x50,0x44,0x46,0x2d,0x31,0x00,0xff])),false);
        assert.strictEqual(textLike(new Uint8Array(0)),false);assert.strictEqual(textLike(null),false);
        assert.strictEqual(textLike(bytes('שלום עולם').subarray(0,7)),true,'a letter cut at the end of the sample');
        // why a picture could not be read, in words he can act on
        assert.ok(pictureError({name:'a.png',type:'image/png',size:0}).includes('0 בתים'));assert.ok(pictureError({name:'IMG.heic',type:'',size:9}).includes('HEIC'));assert.ok(pictureError({name:'x',type:'image/heif',size:9}).includes('HEIC'));
        assert.strictEqual(pictureError({name:'a.png',type:'image/png',size:2400000}),'לא ניתן לקרוא את התמונה a.png (image/png, 2.4MB).');
        assert.ok(pictureError({name:'',type:'',size:512}).includes('סוג לא ידוע'));assert.ok(pictureError(null).includes('0 בתים'));
        assert.strictEqual(bytesLabel(999),'999 בתים');assert.strictEqual(bytesLabel(15300),'15KB');assert.strictEqual(bytesLabel(3200000),'3.2MB');
        // the microphone: inside an app's own browser the advice is about the app, not about site settings
        const wv='Mozilla/5.0 (Linux; Android 16; SM-F966B Build/X; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.0.0 Mobile Safari/537.36';
        const chrome='Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36',mac='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
        assert.strictEqual(inWebView(wv),true);assert.strictEqual(inWebView(chrome),false);assert.strictEqual(inWebView(mac),false);assert.strictEqual(inWebView(''),false);assert.strictEqual(inWebView(null),false);
        assert.ok(micAdvice('denied',true).steps.join(' ').includes('Snap'));assert.ok(micAdvice('denied',true).steps.some(step=>step.includes('Chrome')));
        assert.ok(micAdvice('prompt',true).line.includes('אפליקציה אחרת'));assert.ok(micAdvice('denied',false).steps.some(step=>step.includes('הרשאות')));
        assert.deepStrictEqual(micAdvice('granted',true).steps,[]);assert.deepStrictEqual(micAdvice('prompt',false).steps,[]);assert.ok(micAdvice('insecure',false).line.includes('https'));
        for(const state of ['granted','prompt','denied','insecure','missing','x'])for(const inside of [true,false])assert.ok(micAdvice(state,inside).line.length>8,state);
        """)
        page = self.page()
        self.assertIn("function sameFile(list,file){return list.some(f=>f===file||(f.name===file.name&&f.size===file.size&&f.type===file.type));}", page)
        for part in ("carriedFiles(data)", "navigator.clipboard.read()", "menuItem('copy',tr('Paste a picture from the clipboard'),'',()=>pastePictures([]))", "const clipboardAsk=()=>window.isSecureContext&&!!navigator.clipboard&&!!navigator.clipboard.read&&!inWebView(navigator.userAgent);", "}catch{clipRefused=true;}", "clipboardAsk()&&!clipRefused?", "document.addEventListener('drop',async e=>{",
                     "if(kind!=='text'){toast(", "micTrouble('denied')", "block(tr('Microphone for recording'),...nodes);", "else if(foldTasks()){}"):
            self.assertIn(part, page)

    # ── rich blocks: one frame for code, tables, diagrams and an agent's page ──

    def test_a_table_goes_to_a_spreadsheet_as_it_reads(self):
        self.pure_js(r"""
        const rows=[['מכונה','סוג','עלות לריצה'],['#1 c8a','on-demand','$1.68'],['#3 c8a','Spot, "זול"','$0.40'],['  רווחים ‏ סביב ','שורה\nשנייה','']];
        // CSV: quotes only where a cell needs them, doubled inside; one line per row; no hidden marks
        assert.strictEqual(tableText(rows,false),'מכונה,סוג,עלות לריצה\r\n#1 c8a,on-demand,$1.68\r\n#3 c8a,"Spot, ""זול"'+'"",$0.40\r\nרווחים סביב,שורה שנייה,');
        // for a paste into a spreadsheet: tabs between cells
        assert.strictEqual(tableText(rows.slice(0,2),true),'מכונה\tסוג\tעלות לריצה\n#1 c8a\ton-demand\t$1.68');
        // a cell a spreadsheet would run as a formula is handed over as text
        assert.strictEqual(tableText([['=1+1','+972','-5','@x','a=b']],false),"\"'=1+1\",\"'+972\",\"'-5\",\"'@x\",a=b");
        assert.strictEqual(tableText([],false),'');assert.strictEqual(tableText(null,true),'');assert.strictEqual(tableText([[null,7]],false),',7');
        // the name an agent's page gives itself
        assert.strictEqual(canvasTitle('<!doctype html><title> עלות ריצה &amp; זמן </title><h1>x</h1>'),'עלות ריצה & זמן');
        assert.strictEqual(canvasTitle('<body><h3 class="a">עלות <b>ריצה</b>, לפי סוג מכונה</h3>'),'עלות ריצה, לפי סוג מכונה');assert.strictEqual(canvasTitle('<h1>שורה<br>שנייה</h1>'),'שורה שנייה');
// a heading written inside the page's code is not its name
        assert.strictEqual(canvasTitle('<body><div id="app"></div><script>el.innerHTML=`<h2>${esc(name)} ${ts.length}</h2>`;</scr'+'ipt></body>'),'');
        assert.strictEqual(canvasTitle('<style>h1{color:red}</style><script>const t="<title>x</title>"</scr'+'ipt><h2>משימות הפיתוח</h2>'),'משימות הפיתוח');
        assert.strictEqual(canvasTitle('<!-- <title>ישן</title> --><title>חדש</title>'),'חדש');assert.strictEqual(canvasTitle('<script>var a="<h1>x</h1>"'),'');
                assert.strictEqual(canvasTitle('<p>בלי כותרת</p>'),'');assert.strictEqual(canvasTitle(null),'');assert.strictEqual(canvasTitle('<title>'+'x'.repeat(200)+'</title>').length,80);
        """)
        page = self.page()
        for part in ("dressTables(body);", "el('div','card code')", "el('figure','card diagram')", "el('div','card canvas')", "openReader({title:tr('Table'),table:holder.cloneNode(true),rows:rows()})",
                     ".md th{position:sticky;top:0;", ".md tr:nth-child(odd) td{", "row.classList.add('fresh')", "@media (prefers-reduced-motion:reduce){.msg.fresh{animation:none}}"):
            self.assertIn(part, page)
        # an agent's page never opens as a page of its own: only inside the sandboxed frame
        self.assertNotIn("window.open(", page)

    def test_the_switcher_lists_what_needs_him_first_when_nothing_is_typed(self):
        self.pure_js(r"""
        const row=(id,turn,unread,last)=>({id,turn,unread,last});
        const rows=[row('old-work','working',false,100),row('read-on-me','on-owner',false,300),row('new-report','working',true,200),row('new-on-me','on-owner',true,150),
                    row('fresh-work','working',false,900),row('asleep','snoozed',true,950),row('archived','closed',false,990),row('done-recent','done',false,500),row('new-on-me-2','on-owner',true,400)];
        assert.deepStrictEqual(switchOrder(rows).map(r=>r.id),['new-on-me-2','new-on-me','new-report','read-on-me','fresh-work','done-recent','old-work','asleep','archived']);
        assert.deepStrictEqual(rows.map(r=>r.id)[0],'old-work','the list it was given is not touched');
        assert.deepStrictEqual(switchOrder([row('a','working',false,5),row('b','working',false,5)]).map(r=>r.id),['a','b'],'equal ones keep their places');
        assert.deepStrictEqual(switchOrder([]),[]);assert.deepStrictEqual(switchOrder(null),[]);
        """)
        self.assertIn("...switchOrder(rows),...split.rest.map(a=>({act:a}))];", self.page())

    def test_a_message_becomes_a_new_topic_with_its_words_quoted_and_linked(self):
        # The owner m183 (task 56): "פצל לנושא חדש". The form is filled from the message and he confirms; the topic links to the source.
        self.pure_js(r"""
        const t={id:'snap-linux',title:'Snap Linux \u2014 מיזוג'},m={id:'m12',from:'tower',text:'שורה א\nשורה ב'};
        const plain=splitForm(t,m,false,'/threads/suda.html');
        assert.strictEqual(plain.text,'> שורה א\n> שורה ב\n\n');assert.strictEqual(plain.links,'מקור: Snap Linux \u2014 מיזוג=/threads/suda.html#snap-linux/m12');
        assert.strictEqual(plain.split,null);assert.strictEqual(plain.title,'');assert.strictEqual(plain.context,'');
        // once the server keeps the quote itself (split_from), the page sends where the topic came from and no quote
        const known=splitForm(t,m,true,'/threads-demo/slack.html');
        assert.strictEqual(known.text,'');assert.deepStrictEqual(known.split,{thread:'snap-linux',msg:'m12'});assert.ok(known.links.endsWith('=/threads-demo/suda.html#snap-linux/m12'),known.links);
        // the label fits a link line; the first words of the quote stand in for the title, without the quote marks
        assert.ok(splitForm({id:'x',title:'כ'.repeat(80)},m,false,'/threads/suda.html').links.split('=')[0].length<=40);
        assert.strictEqual(topicCheck({title:'',text:plain.text,context:'',links:plain.links},[]).op.title,'שורה א');
        assert.strictEqual(topicCheck({title:'',text:plain.text,context:'',links:plain.links},[]).op.title_pending,true);
        assert.deepStrictEqual(topicCheck({title:'',text:plain.text,context:'',links:plain.links},[]).op.links,[{label:'מקור: Snap Linux \u2014 מיזוג',url:'/threads/suda.html#snap-linux/m12'}]);
        // with the server keeping the quote, the form may be empty: the message it cuts out stands in for the words and the title
        const cut=topicCheck({title:'',text:'',context:'',links:known.links,split:known.split},[]);
        assert.strictEqual(cut.error,'');assert.deepStrictEqual(cut.op.split,{thread:'snap-linux',msg:'m12'});assert.strictEqual(cut.op.title_pending,true);assert.strictEqual(cut.op.text,'');
        assert.strictEqual(topicCheck({title:'',text:'',context:'',links:'',split:null},[]).field,'text','without a split an empty form still needs words');
        // a line the server wrote: where it points comes from its fields, and a crafted thread id points nowhere
        assert.deepStrictEqual(systemLine({from:'system',text:'פוצל לנושא חדש',split_to:{thread:'new-1',title:'חדש'}}),{text:'פוצל לנושא חדש',thread:'new-1',title:'חדש'});
        assert.deepStrictEqual(systemLine({from:'system',text:'x',split_to:{thread:'../etc',title:'y'}}),{text:'x',thread:'',title:'y'});
        assert.deepStrictEqual(systemLine({from:'system',text:'x'}),{text:'x',thread:'',title:''});assert.strictEqual(systemLine({from:'tower',text:'x'}),null);
        """)
        page = self.page()
        for part in ("menuItem('expand',tr('Split into a new topic'),'',()=>splitTopic(t,m))", "...(topicSplit&&has('split')?{split:topicSplit}:{})", "topicCid=null;topicSplit=null;",
                     "node:m.from==='system'?systemNode(m,t):messageNode(", "node.append(splitFromNode(t.split_from))", "button(tr('Split into the topic: {id}',{id:to}),'split-to',()=>openChannel(to))",
                     "line.setAttribute('role','note')"):
            self.assertIn(part, page)

    def test_a_message_is_read_aloud_in_hebrew_without_its_marks(self):
        # The owner m183 (task 58): "הקראה בקול". The browser's voice, Hebrew when it has one; code is named, links by their words.
        self.pure_js(r"""
        assert.strictEqual(speakable('**חשוב:** לבדוק את `ultra logs`\n- פריט א\n- פריט ב\n```sh\n! ls\n```\nסוף'),'חשוב: לבדוק את ultra logs. פריט א. פריט ב. קטע קוד. סוף.');
        assert.strictEqual(speakable('ראה [את ה-PR](https://x.example/1) וגם https://y.example/2 עכשיו'),'ראה את ה-PR וגם קישור עכשיו.');
        assert.strictEqual(speakable('# כותרת\n> ציטוט\n1. ראשון\n2) שני'),'כותרת. ציטוט. ראשון. שני.');
        assert.strictEqual(speakable('‏שלום 👍 עולם ✅'),'שלום עולם.');
        assert.strictEqual(speakable('| א | ב |\n|---|---|'),'א ב. ---  ---.'.replace('---  ---.','--- ---.'));
        assert.strictEqual(speakable(''),'');assert.strictEqual(speakable(null),'');assert.strictEqual(speakable('   \n\n'),'');
        assert.strictEqual(speakable('שאלה?'),'שאלה?');
        const v=(lang,name)=>({lang,name});
        assert.strictEqual(hebrewVoice([v('en-US','Alex'),v('he-IL','Carmit'),v('he','Other')]).name,'Carmit');
        assert.strictEqual(hebrewVoice([v('en-US','Alex'),v('he_IL','Google עברית')]).name,'Google עברית');
        assert.strictEqual(hebrewVoice([v('en-US','Alex'),v('iw-IL','Hebrew Israel')]).name,'Hebrew Israel');
        assert.strictEqual(hebrewVoice([v('en-US','Alex')]),null);assert.strictEqual(hebrewVoice(null),null);assert.strictEqual(hebrewVoice([]),null);
        """)
        page = self.page()
        for part in ("menuItem('play',speaking()?tr('Stop reading aloud'):tr('Read aloud'),'',()=>readAloud(m))", "u.lang='he-IL'", "const voice=hebrewVoice(speechSynthesis.getVoices());",
                     "toast(tr('Reading: {text}',{text:preview(words,50)}),tr('Stop'),stopReading)", "if(speaking()){stopReading();"):
            self.assertIn(part, page)

    def test_a_plain_http_page_points_at_the_same_thread_on_the_secure_address(self):
        self.pure_js(r"""
        const at=(href)=>{const u=new URL(href);return {protocol:u.protocol,hostname:u.hostname,pathname:u.pathname,search:u.search,hash:u.hash};};
        const H='https://suda.example.com';      // the installation's secure address (threads install writes it)
        assert.strictEqual(secureAddress(at('http://192.0.2.10:8767/threads/suda.html#x'),''),'');     // none configured: nowhere to point
        // the tailnet address of the threads board: the same page, the same thread, on the secure address
        assert.strictEqual(secureAddress(at('http://192.0.2.10:8767/threads/suda.html#snap-linux'),H),'https://suda.example.com/threads/suda.html#snap-linux');
        assert.strictEqual(secureAddress(at('http://192.0.2.10:8767/threads/suda.html?x=1#suda/m12'),H),'https://suda.example.com/threads/suda.html?x=1#suda/m12');
        assert.strictEqual(secureAddress(at('http://mac.example.ts.net:8767/threads/slack.html'),H),'https://suda.example.com/threads/slack.html');
        // already secure: https, and this Mac's own loopback
        for(const here of ['https://suda.example.com/threads/suda.html#x','http://127.0.0.1:8767/threads/suda.html#x','http://localhost:8767/threads/suda.html','http://[::1]:8767/threads/suda.html'])assert.strictEqual(secureAddress(at(here)),'',here);
        // another board has no secure address to point at
        assert.strictEqual(secureAddress(at('http://192.0.2.10:8767/worker-a-demo/suda.html#x'),H),'');assert.strictEqual(secureAddress(at('http://192.0.2.10:8767/other/board.html'),H),'');
        assert.strictEqual(secureAddress(null),'');assert.strictEqual(secureAddress({}),'');
        """)
        page = self.page()
        for part in ('id="secure-bar"', "$('secure-go').href=address;", "secureLink(view.ch?tr('Open this topic there'):tr('Go there'))", "else if(touch.matches)toast(tr('The browser allows notifications only from a secure address (https).'));"):
            self.assertIn(part, page)

    def test_selected_words_can_be_answered_as_they_are(self):
        page = self.page()
        for part in ("if(has('quote'))state.quote=msg.quote;else if(!msg.voice&&!msg.answer)state.text=quotedText(msg.quote,state.text);", "document.addEventListener('selectionchange',",
                     "startReply(pick.mid,pick.text)", 'id="pick-chip"', 'id="picking-reply"', "e.closest('#log .msg .body')", "if(picked&&t&&t.status==='open')replyPicked();"):
            self.assertIn(part, page)

    def test_light_or_dark_is_the_systems_choice_or_his_own(self):
        self.pure_js(r"""
        assert.deepStrictEqual(['dark','light','system',null,'','x'].map(themeOf),['dark','light','system','system','system','system']);
        assert.strictEqual(darkOn('dark',false),true);assert.strictEqual(darkOn('light',true),false);assert.strictEqual(darkOn('system',true),true);assert.strictEqual(darkOn('system',false),false);
        assert.deepStrictEqual(THEMES.map(([key])=>key),['system','light','dark']);
        """)
        page = self.page()
        css = page.split('<style>')[1].split('</style>')[0]
        # the same dark colours by the system's choice and by his own; his "light" wins over a dark system
        by_system = css.split('@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){')[1].split('}}')[0]
        by_choice = css.split(':root[data-theme="dark"]{')[1].split('}')[0]
        self.assertEqual(by_system.strip(), by_choice.replace('color-scheme:dark;', '').strip())
        self.assertIn('--bg:#1a1d21', by_system)
        self.assertIn(':root[data-theme="light"]{color-scheme:light}', css)
        # applied before the page is drawn, and never touching anything but the one key
        self.assertIn('<script id="theme-first">try{var kept=localStorage.getItem("suda-theme");if(kept==="dark"||kept==="light")document.documentElement.dataset.theme=kept;}catch(e){}</script>', page)
        for part in ("const theme=darkNow()?'dark':'default'", "block(tr('Appearance'),chips);", "add(tr('Appearance: {label}',{label}),'',()=>setTheme(key),'theme:'+key)"):
            self.assertIn(part, page)

    def test_short_notices_appear_where_he_chose_and_by_default_away_from_the_composer(self):
        self.pure_js(r"""
        assert.deepStrictEqual(['', null, 'x', 'top-left', 'top-center', 'bottom', 'top-right'].map(toastPlace),['top-right','top-right','top-right','top-left','top-center','bottom','top-right']);
        assert.deepStrictEqual(TOAST_PLACES.map(([key])=>key),['top-right','top-left','top-center','bottom']);
        """)
        page = self.page()
        for part in ('id="float-toasts"', "const host=$('float-toasts'),head=phone.matches&&view.ch?document.querySelector('.head'):null;", "if(have.some(other=>other.data===pic.data)){", '#float-toasts[data-at="top-right"]{right:8px}', "store.set('toast-at',key)"):
            self.assertIn(part, page)

    def test_pictures_stand_side_by_side_with_their_captions_under_them(self):
        page = self.page()
        for part in (".tray-strip{display:flex;gap:10px;overflow-x:auto;", ".tray-row{flex:0 0 168px;min-width:0;display:flex;flex-direction:column;", "row.append(frame,caption);", ".pics.many .shot{width:min(220px,calc(50% - 4px))}",
                     "thumb.onclick=()=>openReader({title:captionOf(pic.caption)||pic.name||tr('Picture {n}',{n}),image:pic.url,photo:true,name:pic.name});"):
            self.assertIn(part, page)

    def test_answers_are_chosen_from_the_keyboard_and_can_be_taken_back(self):
        page = self.page()
        for part in ("emptyBox:target===input&&!input.value", "else if(action==='opt-next'||action==='opt-prev'){", "msg.delivery='holding';", "msg.held=setTimeout(go,UNDO_MS)",
                     "toast(tr('Chosen: {text}',{text:preview(msg.text,60)}),tr('Undo'),", "const UNDO_MS=4000;", ".opt:focus-visible,.btn.option:focus-visible", "if(m.held&&m.go)m.go();", "row.querySelectorAll('.opts .opt:not(:disabled)')"):
            self.assertIn(part, page)

    def test_his_done_says_what_it_closed_and_what_it_left(self):
        # suda-fixes m426: his /done always works; its toast says what it closed and what stays
        self.pure_js(r"""
        assert.strictEqual(doneSaid({ok:true,asks:[],tasks:[],unseen:[]}),'סיימת: הנושא ירד מ"עליך"');
        assert.strictEqual(doneSaid({ok:true}),'סיימת: הנושא ירד מ"עליך"');           // an older server says nothing more
        assert.strictEqual(doneSaid({asks:['m2'],tasks:[1]}),'סיימת: הנושא ירד מ"עליך" · השאלה הפתוחה נסגרה בלי תשובה · משימה פתוחה אחת נשארה כמו שהיא');
        assert.strictEqual(doneSaid({asks:['m2','m4'],tasks:[1,2,3]}),'סיימת: הנושא ירד מ"עליך" · 2 שאלות פתוחות נסגרו בלי תשובה · 3 משימות פתוחות נשארו כמו שהן');
        assert.strictEqual(doneSaid(null),'סיימת: הנושא ירד מ"עליך"');
        """)

    def test_a_question_he_never_answered_stays_answerable(self):
        # An agent that writes again with a state of its own makes the server forget the open question; the
        # buttons under it must not die on a question that still stands.
        self.pure_js(r"""
        const q=(id,more)=>Object.assign({id,from:'fork',text:'?',ts:1,q:true,options:['כן','לא']},more),say=(id,from,more)=>Object.assign({id,from,text:'x',ts:2},more);
        const thread=(messages,question)=>({id:'t',status:'open',question:question||null,messages});
        assert.strictEqual(lateQuestion(thread([q('m44'),say('m45','tower')])),'m44','asked, then the agent wrote again: still answerable');
        assert.strictEqual(lateQuestion(thread([q('m44')],{id:'m44'})),null,'the open question is answered the usual way');
        assert.strictEqual(lateQuestion(thread([q('m44'),say('m45','tower'),say('m46','owner')])),null,'he wrote after it: he has answered in his own words');
        assert.strictEqual(lateQuestion(thread([q('m44',{q_closed:{ts:3,by:'owner'}}),say('m45','tower')])),null,'he finished the topic over it (/done): put away by him');
        assert.strictEqual(lateQuestion(thread([q('m44'),say('m45','owner',{re:{q:'m44'}}),say('m46','fork')])),null);
        assert.strictEqual(lateQuestion(thread([q('m12'),say('m13','fork'),q('m20'),say('m21','tower')])),'m20','only the last question');
        assert.strictEqual(lateQuestion(thread([q('m12'),say('m13','owner'),q('m20'),say('m21','owner')])),null);
        assert.strictEqual(lateQuestion(thread([q('m44',{multi:true,groups:[]}),say('m45','tower')])),null,'ticks need the form of an open question');
        assert.strictEqual(lateQuestion(thread([q('m44',{options:[]}),say('m45','tower')])),null);assert.strictEqual(lateQuestion(thread([say('m1','fork')])),null);
        assert.strictEqual(lateQuestion({id:'t',status:'closed',question:null,messages:[q('m44')]}),null);assert.strictEqual(lateQuestion(null),null);
        """)
        page = self.page()
        for part in ("late?send(option,null,m.id):send(option,m.id)", "if(lateFor){msg.reply_to=lateFor;msg.late=lateFor;}", "if(lateFor&&(lateQuestion(t)!==lateFor||list.some(m=>m.late===lateFor&&m.delivery!=='failed')))return false;"):
            self.assertIn(part, page)

    def test_several_questions_are_open_at_once_and_each_answers_by_itself(self):
        """The owner, suda m508: "when there are two questions, one cancels the other". A thread keeps every open
        question (`questions`, oldest first; `question` is the newest of them). The page reads them all, from a
        server that keeps one too; the digits answer the newest; the form of ticks opens for its own question."""
        self.pure_js(r"""
        const a={id:'m1',text:'א?',options:['כן','לא']},b={id:'m2',text:'ב?',options:['x','y']};
        const t=(more)=>Object.assign({id:'t',status:'open',state:'on-owner',auto:false,messages:[]},more);
        assert.deepStrictEqual(openQuestions(t({questions:[a,b],question:b})).map(q=>q.id),['m1','m2']);
        assert.deepStrictEqual(openQuestions(t({question:a})).map(q=>q.id),['m1'],'a server from before keeps one');
        assert.deepStrictEqual(openQuestions(t({question:null})),[]);assert.deepStrictEqual(openQuestions(null),[]);
        assert.deepStrictEqual(openQuestions(t({questions:[a,null,{id:5},b],question:b})).map(q=>q.id),['m1','m2'],'what is not a question is skipped');
        assert.deepStrictEqual(openQuestions(t({questions:[],question:null})),[]);
        assert.strictEqual(newestQuestion(t({questions:[a,b],question:b})).id,'m2');assert.strictEqual(newestQuestion(t({})),null);
        assert.strictEqual(openQuestion(t({questions:[a,b],question:b}),'m1'),a);assert.strictEqual(openQuestion(t({questions:[a,b],question:b}),'m3'),null);
        assert.strictEqual(openQuestion(t({questions:[a,b],question:b}),null),null);
        // the last question of the thread, still open, is never "late"; nor is an older open one
        const q=(id)=>({id,from:'fork',text:'?',ts:1,q:true,options:['כן','לא']}),say=(id,from)=>({id,from,text:'x',ts:2});
        assert.strictEqual(lateQuestion(t({messages:[q('m1'),q('m2'),say('m3','fork')],questions:[a,b],question:b})),null);
        assert.strictEqual(lateQuestion(t({messages:[q('m1'),q('m2'),say('m3','fork')],questions:[a],question:a})),'m2','the newest went with a done: still answerable late');
        // a plain report with any question open is a real ask
        assert.strictEqual(plainReport(t({auto:true,questions:[a],question:a})),false);assert.strictEqual(plainReport(t({auto:true,questions:[],question:null})),true);
        // the strip he put away stays away while every open question is one he put away; a new one brings it back
        assert.strictEqual(pinAway('m1 m2',['m1','m2']),true);assert.strictEqual(pinAway('m1 m2',['m1']),true,'he answered the newest: still away');
        assert.strictEqual(pinAway('m1 m2',['m1','m3']),false,'a new question');assert.strictEqual(pinAway('m2',['m2']),true,'an id kept by an older page');
        assert.strictEqual(pinAway('',['m1']),false);assert.strictEqual(pinAway(null,['m1']),false);assert.strictEqual(pinAway('m1',[]),false);
        """)
        page = self.page()
        for part in ("qs.forEach((x,k)=>parts.push(pinQuestion(t,x,k===0,going(x),qs.length>1)));",
                     "if(newest&&i<9){const num=el('kbd','num',String(i+1));",                               # digits on the newest only
                     "newest=pin.hidden?null:pin.querySelector('.pin-q.newest')",                           # and they press the newest's buttons
                     "const digits=live&&(late||(newestQuestion(t)||{}).id===m.id);",
                     "if(openQuestion(now_,m.id))send(option,m.id);",
                     "()=>openAnswer(q.id)", "()=>openAnswer(m.id)", "answerFor&&answerFor.thread===t.id?openQuestion(t,answerFor.q):newestQuestion(t)",
                     "const reply=button(tr('An answer in words'),'btn other-answer',()=>startReply(q.id));",
                     "tr('Quick answer to the open question (when there are several: the newest of them)')",
                     "    if(msg.answers)state.q=msg.answers;\n    if('under' in msg)state.under=msg.under;"):
            self.assertIn(part, page)

    def test_an_option_may_be_a_picture(self):
        self.pure_js(r"""
        for(const ok of ['uploads/suda/m192-o1.png','uploads/suda/m192-o10.webp','uploads/suda/m7-3.jpg'])assert.strictEqual(optionImage(ok,'suda'),ok);
        for(const bad of ['uploads/other/m1-o1.png','uploads/suda/m1-o1.svg','uploads/suda/../x/m1-o1.png','https://evil.example/m1-o1.png','/uploads/suda/m1-o1.png','uploads/suda/m1.png',null,{}])assert.strictEqual(optionImage(bad,'suda'),null,String(bad));
        // a single choice: a map from the label to its picture
        const q={id:'m5',options:['S עם נקודה','בועה','בלי תמונה'],option_images:{'S עם נקודה':{file:'uploads/suda/m5-o1.png',w:512,h:512},'בועה':'uploads/suda/m5-o2.png','זר':{file:'uploads/other/m5-o3.png'},'רע':{file:'javascript:x'}}};
        assert.deepStrictEqual([...optionPics(q,'suda')],[['S עם נקודה',{src:'uploads/suda/m5-o1.png',w:512,h:512}],['בועה',{src:'uploads/suda/m5-o2.png',w:0,h:0}]]);
        // ticks in groups: the picture rides on the item
        const g={id:'m6',multi:true,groups:[{title:'אייקון',items:[{text:'1. S',image:{file:'uploads/suda/m6-o1.png',w:96,h:96}},{text:'2. בועה'},'3. טקסט',{text:'4. זר',image:{file:'uploads/x/m6-o4.png'}}]}]};
        assert.deepStrictEqual([...optionPics(g,'suda').keys()],['1. S']);
        assert.strictEqual(optionPics(null,'suda').size,0);assert.strictEqual(optionPics({option_images:'x',groups:'y'},'suda').size,0);assert.strictEqual(optionPics({options:['a','b']},'suda').size,0);
        """)
        page = self.page()
        for part in ("const pics=optionPics(m,t.id);if(pics.size)opts.classList.add('tiles');", ".opts.tiles{display:grid;", "row.classList.add('tile');row.append(optionPicture(shown,at),line);", "qpics=optionPics(q,t.id),qshown="):
            self.assertIn(part, page)

    def test_a_link_says_what_it_leads_to(self):
        self.pure_js(r"""
        const chip=href=>{const c=linkChip(href);return c?c.kind+'|'+c.tag+'|'+c.label:null;};
        assert.strictEqual(chip('https://github.com/acme/orbit/pull/1620'),'pr|PR|#1620 · orbit');assert.strictEqual(chip('https://github.com/acme/orbit/pull/1620/files#diff-1'),'pr|PR|#1620 · orbit');
        assert.strictEqual(chip('https://github.com/a/b/issues/7'),'issue|Issue|#7 · b');assert.strictEqual(chip('https://github.com/a/b/commit/3f41634aa01bcd'),'commit|commit|3f41634 · b');
        assert.strictEqual(chip('https://github.com/a/b/blob/main/src/recorder.ts#L10-L20'),'file|קובץ|recorder.ts · b');assert.strictEqual(chip('https://github.com/a/b'),'repo|repo|a/b');
        assert.strictEqual(chip('https://linear.app/acme/issue/ENG-412/refund-flow'),'issue|Linear|ENG-412');
        assert.strictEqual(chip('/threads/suda.html#snap-linux'),'thread|נושא|snap-linux');assert.strictEqual(chip('https://suda.example.com/threads/suda.html#suda/m12'),'thread|נושא|suda · m12');
        assert.deepStrictEqual([linkChip('/threads/board.html#shopflow/m3').thread,linkChip('/threads/board.html#shopflow/m3').msg],['shopflow','m3']);
        assert.strictEqual(chip('/acme/sim-lab-spot/board.html'),'board|לוח|sim-lab-spot');assert.strictEqual(chip('/threads/assets/chatgpt-rich-research.html'),'page|דף|chatgpt-rich-research');
        assert.strictEqual(chip('https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-interruptions.html?x=1'),'web||docs.aws.amazon.com/…/spot-interruptions.html');assert.strictEqual(chip('https://www.example.com/'),'web||example.com');
        assert.strictEqual(chip('https://github.com/a/b/pull/x'),null);assert.strictEqual(chip('https://github.com/a/b/commit/zzz'),null);assert.strictEqual(chip('mailto:x@y'),null);assert.strictEqual(chip(''),null);assert.strictEqual(chip(null),null);
        // in a message: a bare address becomes a chip; a link the writer named keeps its name
        assert.ok(markdown('ראה https://github.com/a/b/pull/7 עכשיו').includes('<use href="#i-pr"/></svg>PR</span><bdi class="chip-text">#7 · b</bdi>'));
        assert.ok(markdown('[התיקון להחזרים](https://github.com/a/b/pull/7)').includes('<use href="#i-pr"/></svg>PR</span><bdi class="chip-text">התיקון להחזרים</bdi>'));
        assert.strictEqual(markdown('[דף](https://x.example/a)'),'<p><a href="https://x.example/a" target="_blank" rel="noopener">דף</a></p>','a named link to an ordinary site stays a link');
        // a thread named with a message: the whole of it is the link
        const there=markdown('ראה /threads/suda.html#snap-linux/m12 שם');
        assert.ok(there.includes('data-thread="snap-linux" data-msg="m12" href="/threads/suda.html#snap-linux/m12"'),there);assert.ok(there.endsWith('</a> שם</p>'),there);
        // whatever the address holds, the chip adds no markup of its own making
        const odd=markdown('https://github.com/a/b/pull/7?x=<img src=x onerror=1>&"q"');
        assert.ok(!/<img|onerror=1>|"q"/.test(odd.replace(/&lt;|&gt;|&quot;/g,'')),odd);
        """)
        page = self.page()
        for part in ("dressLinks(body);", "text.textContent=preview(t.title,42)", ".md a.chip-link{"):
            self.assertIn(part, page)

    def test_a_link_to_the_md_viewer_opens_it_in_a_panel(self):
        # suda-fixes m190: a .md opens in the MD Viewer INSIDE Suda (a large panel over the thread, as the mockup
        # showed), not as a separate page. Which links do: the viewer's address on this very server, with a path.
        self.pure_js(r"""
        const O='https://suda.example.com';
        assert.strictEqual(mdvTarget('/mdv/?path=~%2FDocuments%2Fmds%2Fplan.md',O),'~/Documents/mds/plan.md');
        assert.strictEqual(mdvTarget('https://suda.example.com/mdv/?path=~/Documents/mds/a%20b.md&mode=both',O),'~/Documents/mds/a b.md');
        assert.strictEqual(mdvTarget('/mdv/?mode=tr&path=%2FUsers%2Fy%2Fx.md',O),'/Users/y/x.md');
        // another server, another page of this one, no path: not the panel's
        assert.strictEqual(mdvTarget('http://192.0.2.10:8767/mdv/?path=~/a.md',O),null);
        assert.strictEqual(mdvTarget('/mdv/',O),null);assert.strictEqual(mdvTarget('/mdv/?path=',O),null);
        assert.strictEqual(mdvTarget('/mdvx/?path=~/a.md',O),null);assert.strictEqual(mdvTarget('/threads/suda.html#x',O),null);
        assert.strictEqual(mdvTarget('javascript:alert(1)',O),null);assert.strictEqual(mdvTarget('',O),null);assert.strictEqual(mdvTarget(null,O),null);
        // the address the panel loads: the same file, embedded, with its mode kept; and the one "open in a new page" opens
        assert.strictEqual(mdvFrameSrc('~/Documents/mds/a b.md','both'),'/mdv/?path=~%2FDocuments%2Fmds%2Fa%20b.md&mode=both&embed=1');
        assert.strictEqual(mdvFrameSrc('~/x.md',''),'/mdv/?path=~%2Fx.md&embed=1');
        assert.strictEqual(mdvFrameSrc('~/x.md','evil'),'/mdv/?path=~%2Fx.md&embed=1');
        // a full address of the viewer on this server (as the tower writes it) is a file chip that says the file's name
        SELF_ORIGIN.value='https://suda.example.com';
        const chip=href=>{const c=linkChip(href);return c?c.kind+'|'+c.tag+'|'+c.label:null;};
        assert.strictEqual(chip('https://suda.example.com/mdv/?path=~/Documents/mds/2026-11-03-network-move.md'),'file|קובץ|2026-11-03-network-move.md');
        assert.strictEqual(chip('/mdv/?path=~%2FDocuments%2Fmds%2Ftower-skill-he.md'),'file|קובץ|tower-skill-he.md');
        assert.strictEqual(chip('https://suda.example.com/mdv/?path=%E0%A4%A'),'file|קובץ|%A');      // (a broken escape: what is left of it)
        assert.strictEqual(chip('https://suda.example.com/mdv/?path=%E0%A4'),'file|קובץ|מסמך');
        assert.strictEqual(chip('https://elsewhere.example/mdv/?path=~/a.md').split('|')[0],'web');
        const html=markdown('המדריך: https://suda.example.com/mdv/?path=~/Documents/mds/net.md');
        assert.ok(html.includes('data-kind="file"')&&html.includes('<bdi class="chip-text">net.md</bdi>'),html);
        """)
        page = self.page()
        # the panel is a window over a thread, as the reader is: its own entry on a phone, so Back closes it
        for part in ('id="mdv-panel"', 'function openMdv(', 'function closeMdv(', "if(view.mdv&&mdvFor)showMdv();else hideMdv();",
                     'mdv:!!next.mdv&&!!next.ch', "navigate({ch:view.ch,mdv:true,mdvAt:0,under:'self'},true)"):
            self.assertIn(part, page)

    def test_a_markdown_file_named_by_its_path_opens_in_the_md_viewer(self):
        # md-viewer thread: a .md path an agent writes (in `code`, or as a link's target) is a file chip that opens
        # the file in the MD Viewer on this server, /mdv/?path=...
        self.pure_js(r"""
        const one=markdown('התוכנית ב-`~/Documents/mds/todo/plan-2026.md` מוכנה');
        assert.ok(one.includes('href="/mdv/?path=~%2FDocuments%2Fmds%2Ftodo%2Fplan-2026.md"'),one);
        assert.ok(one.includes('data-kind="file"')&&one.includes('<bdi class="chip-text">plan-2026.md</bdi>'),one);
        assert.ok(one.includes('title="~/Documents/mds/todo/plan-2026.md"'),one);
        assert.ok(markdown('`/Users/ada/notes/reports/x.MD`').includes('href="/mdv/?path=%2FUsers%2Fada%2Fnotes%2Freports%2Fx.MD"'));
        const named=markdown('[הדוח](/Users/ada/notes/r.md)');
        assert.ok(named.includes('href="/mdv/?path=%2FUsers%2Fada%2Fnotes%2Fr.md"')&&named.includes('<bdi class="chip-text">הדוח</bdi>'),named);
        // only a full path to a .md: anything else stays code (or the link it was)
        for(const code of ['plan.md','~/a b.md','~/x/../y.md','~/notes.txt','https://e.com/a.md','~/a.md;rm','~/"a".md'])
          assert.ok(markdown('`'+code+'`').includes('<code>'),code);
        assert.ok(markdown('[a](/acme/x/board.html)').includes('href="/acme/x/board.html"'));
        assert.strictEqual(mdFilePath(' ~/a/b.md '),'~/a/b.md');assert.strictEqual(mdFilePath('~/a/b.markdown'),'~/a/b.markdown');assert.strictEqual(mdFilePath('a/b.md'),'');
        """)

    def test_an_agent_may_put_buttons_in_a_message_of_three_fixed_kinds(self):
        self.pure_js(r"""
        const acts=text=>actionsOf(text).map(a=>a.kind+'|'+a.label+'|'+a.value);
        assert.deepStrictEqual(acts('reply: למזג עכשיו\nreply:   לחכות   ליום שלישי \nopen: PR #1620 | https://github.com/a/b/pull/1620\nopen: הלוח | /acme/x/board.html\ncopy: העתק פקודה | ultra install -r a.apk'),
          ['reply|למזג עכשיו|למזג עכשיו','reply|לחכות ליום שלישי|לחכות ליום שלישי','open|PR #1620|https://github.com/a/b/pull/1620','open|הלוח|/acme/x/board.html','copy|העתק פקודה|ultra install -r a.apk']);
        // what a reply button sends is what is written on it, also when the line holds a bar
        assert.deepStrictEqual(acts('reply: כן | rm -rf /'),['reply|כן | rm -rf /|כן | rm -rf /']);
        // nothing but the three kinds, and no address that is not a web address or a page of this server
        for(const bad of ['run: ls','exec: x | y','javascript: x','open: x | javascript:alert(1)','open: x | //evil.example/a','open: x | data:text/html,x','open: x | /\\evil','open: בלי כתובת','copy: בלי טקסט','reply:','open: | https://x.example','סתם טקסט','open: '+'א'.repeat(41)+' | https://x.example','reply: '+'א'.repeat(201)])
          assert.deepStrictEqual(actionsOf(bad),[],bad);
        assert.strictEqual(actionsOf(Array.from({length:9},(_,i)=>'reply: אפשרות '+i).join('\n')).length,6);
        assert.deepStrictEqual(acts('REPLY: כן\n  Open :  דף  |  https://x.example/a?b=1  '),['reply|כן|כן','open|דף|https://x.example/a?b=1']);
        assert.deepStrictEqual(acts('reply: \u200fכן\u200e'),['reply|כן|כן'],'hidden marks do not ride on the words he sends');
        assert.deepStrictEqual(actionsOf(null),[]);assert.deepStrictEqual(actionsOf(''),[]);
        // the block is an ordinary fenced block for the renderer
        assert.ok(markdown('```actions\nreply: כן\n```').startsWith('<pre class="lang-actions"><code>reply: כן</code></pre>'));
        """)
        page = self.page()
        for part in ("dressActions(body,t,m);drawDiagrams(body);", "const acts=m&&m.id&&m.from!=='owner'?actionsOf(pre.textContent):[];", "from:'owner',text:words,ts:now(),delivery:'holding',reply_to:mid,act:mid,", "function holdThenSend(id,msg){"):
            self.assertIn(part, page)

    # ── a new topic from the page ──────────────────────────────────────────

    def test_a_new_topic_is_checked_before_it_is_sent(self):
        self.pure_js(r"""
        const open=[{id:'shopflow',title:'Shopflow \u2014 זרימת רכישה',status:'open'},{id:'old',title:'ישן',status:'closed'}];
        // the least he can write: a title; it is then also the first message, so the tower always hears of it
        assert.deepStrictEqual(topicCheck({title:'  לבדוק   את הלוגים של DKM ',text:'',context:'',links:''},open),
          {field:'',error:'',warn:'',op:{op:'new',title:'לבדוק את הלוגים של DKM',text:'לבדוק את הלוגים של DKM'}});
        // everything filled in
        const full=topicCheck({title:'OTA 2.8.2',text:' תתחיל ב-3 מכשירים\nואז תמשיך ',context:'12 מכשירים בקבוצה',links:'PR=https://github.com/x/y/pull/7?a=b\n\n/threads/board.html\n~/PG/brain/ota.md'},open);
        assert.deepStrictEqual(full.op,{op:'new',title:'OTA 2.8.2',text:'תתחיל ב-3 מכשירים\nואז תמשיך',context:'12 מכשירים בקבוצה',
          links:[{label:'PR',url:'https://github.com/x/y/pull/7?a=b'},{label:'board.html',url:'/threads/board.html'},{label:'ota.md',url:'~/PG/brain/ota.md'}]});
        // what stops him, and at which field
        // a title is optional: without one the first words stand in, and the op says a real title is still owed
        assert.deepStrictEqual(topicCheck({title:'   ',text:' תבדוק למה יש 502 ב-DKM מאתמול בלילה ותכתוב לי מה מצאת\nועוד שורה '},open).op,
          {op:'new',title:'תבדוק למה יש 502 ב-DKM מאתמול בלילה…',title_pending:true,text:'תבדוק למה יש 502 ב-DKM מאתמול בלילה ותכתוב לי מה מצאת\nועוד שורה'});
        assert.deepStrictEqual(topicCheck({text:'קצר'},open).op,{op:'new',title:'קצר',title_pending:true,text:'קצר'});
        assert.ok(!('title_pending' in topicCheck({title:'יש כותרת',text:'x'},open).op));
        assert.strictEqual(tempTitle('\n\n## **לבדוק** את `api`\nשורה שנייה'),'לבדוק את api');assert.strictEqual(tempTitle('- [ ] 1. משימה ראשונה'),'משימה ראשונה');
        assert.ok(tempTitle('מילהארוכהמאוד'.repeat(3)+' '+'עודמילהארוכהמאוד '.repeat(6)).length<=61);assert.strictEqual(tempTitle('  \n '),'');assert.strictEqual(tempTitle(null),'');
        // nothing written at all, or only marks: that is what stops him
        assert.strictEqual(topicCheck({title:'   ',text:'  '},open).field,'text');assert.ok(!topicCheck({title:'',text:''},open).op);assert.strictEqual(topicCheck({text:'***'},open).field,'text');
        assert.ok(topicCheck({text:'Shopflow \u2014 זרימת רכישה'},open).op,'a temporary title is not checked against the open threads');
        assert.strictEqual(topicCheck({title:'x'.repeat(121)},open).field,'title');assert.ok(topicCheck({title:'x'.repeat(120)},open).op);
        const twice=topicCheck({title:' shopflow \u2014  זרימת רכישה'},open);
        assert.deepStrictEqual([twice.field,twice.same,!!twice.op],['title','shopflow',false]);
        assert.ok(topicCheck({title:'ישן'},open).op,'a closed thread does not hold its title');
        assert.strictEqual(topicCheck({title:'a',text:'x'.repeat(8001)},open).field,'text');assert.strictEqual(topicCheck({title:'a',context:'x'.repeat(4001)},open).field,'context');
        assert.strictEqual(topicCheck({title:'a',links:'javascript:alert(1)'},open).field,'links');
        // links: only http(s), a path on the board server, or a file under his home folder
        for(const bad of ['javascript:alert(1)','x=javascript:alert(1)','//evil.example/x','data:text/html,x','ftp://x/y','שם=','https://a b','/\\evil.example','name=file:///etc/passwd','a'.repeat(41)+'=https://x.example'])
          assert.ok(topicLinks(bad).error,bad);
        assert.ok(topicLinks('https://x.example\n'.repeat(9)).error.includes('8'));
        assert.deepStrictEqual(topicLinks('  \n https://www.github.com/a/b?x=1 \n').links,[{label:'github.com',url:'https://www.github.com/a/b?x=1'}]);
        assert.ok(topicLinks('ok=https://x.example\nbad line').error.includes('שורה 2'));
        // a long board: a warning, and he may still open the topic
        const many=Array.from({length:15},(_,i)=>({id:'t'+i,title:'נושא '+i,status:'open'}));
        const crowded=topicCheck({title:'עוד אחד'},many);
        assert.ok(crowded.warn.includes('15'));assert.ok(crowded.op);assert.strictEqual(topicCheck({title:'עוד אחד'},many.slice(1)).warn,'');
        assert.ok(topicCheck({title:''},many).warn,'the warning shows whatever else is wrong');
        // the form as it is kept between visits
        assert.deepStrictEqual(topicDraftOf('{"title":"a","text":"b","context":7,"x":"y"}'),{title:'a',text:'b',context:'',links:''});
        for(const junk of ['','null','[]','{','"text"',undefined])assert.ok(topicEmpty(topicDraftOf(junk)),String(junk));
        assert.ok(!topicEmpty({title:'',text:' x ',context:'',links:''}));
        // the keys: N when not typing, Alt+N anywhere, and Cmd/Ctrl+N where the browser hands it to the page
        const k=(code,more)=>Object.assign({code,key:'',metaKey:false,ctrlKey:false,altKey:false,shiftKey:false,isComposing:false,keyCode:0},more);
        const idle={typing:false,options:0,mac:true},busy={typing:true,options:0,mac:true};
        assert.strictEqual(keyAction(k('KeyN'),idle),'new-topic');assert.strictEqual(keyAction(k('KeyN'),busy),null);
        assert.strictEqual(keyAction(k('KeyN',{altKey:true}),busy),'new-topic');assert.strictEqual(keyAction(k('KeyN',{metaKey:true}),busy),'new-topic');
        assert.strictEqual(keyAction(k('KeyN',{ctrlKey:true}),busy),null);assert.strictEqual(keyAction(k('KeyN',{ctrlKey:true}),{typing:true,options:0,mac:false}),'new-topic');
        assert.strictEqual(keyAction(k('KeyN',{metaKey:true,shiftKey:true}),idle),null);
        """)

    def test_the_new_topic_form_goes_through_the_agreed_op(self):
        page = self.page()
        for part in ("post({...check.op,cid:topicCid,...(topicSplit&&has('split')?{split:topicSplit}:{})})", "{op:'draft',thread:'_new',text}", "$('new-topic').hidden=!has('new')", 'id="topic-title"', 'id="topic-text"',
                     'id="topic-context"', 'id="topic-links"', "raw.drafts._new", "if(view.topic)showTopic();else hideTopic(true);"):
            self.assertIn(part, page)

    # ── answers with several choices, in groups ────────────────────────────

    def test_a_grouped_answer_keeps_the_structure_of_the_question(self):
        self.pure_js(r"""
        const q={id:'m3',text:'אילו חלונות לסגור?',multi:true,options:['alpha-tool','beta-tool','gamma-pr','delta-srv'],
          groups:[{title:'tools',items:[{text:'alpha-tool'},{text:'beta-tool',recommended:true}]},{title:'orbit',items:[{text:'gamma-pr',recommended:true},{text:'delta-srv'}]}]};
        // the groups as the form shows them; a flat --multi question is one group without a title
        assert.deepStrictEqual(groupsOf(q).map(g=>g.title+':'+g.items.map(i=>i.text+(i.recommended?'*':'')).join(',')),['tools:alpha-tool,beta-tool*','orbit:gamma-pr*,delta-srv']);
        assert.deepStrictEqual(groupsOf({id:'m1',multi:true,options:['a','b']}).map(g=>[g.title,g.items.map(i=>i.text)]),[['',['a','b']]]);
        assert.deepStrictEqual(groupsOf({id:'m1',options:['כן','לא']}),[]);            // a single-choice question keeps its buttons
        assert.deepStrictEqual(groupsOf({id:'m1',multi:true,groups:'x',options:null}),[]);
        // what is sent: only ticked items, only of groups that exist, in the question's own order; empty groups left out
        const picked=new Set(['orbit\u0000delta-srv','tools\u0000beta-tool','tools\u0000alpha-tool','gone\u0000x']);
        assert.deepStrictEqual(answerOf(q,picked),{tools:['alpha-tool','beta-tool'],orbit:['delta-srv']});
        assert.deepStrictEqual(answerOf(q,new Set()),{});
        // it can go when something is ticked or a note is written
        assert.strictEqual(answerReady(answerOf(q,picked),''),true);assert.strictEqual(answerReady({},'  '),false);assert.strictEqual(answerReady({},'אף אחד'),true);
        // how his answer reads until the server's own rendering arrives
        assert.strictEqual(answerText({tools:['alpha-tool','beta-tool'],orbit:['delta-srv']},'את השאר להשאיר'),'**tools:** alpha-tool, beta-tool\n**orbit:** delta-srv\nהערה: את השאר להשאיר');
        assert.strictEqual(answerText({'':['a','b']},''),'a, b');assert.strictEqual(answerText({},'רק הערה'),'הערה: רק הערה');
        // "everything in the group", and the recommended ones
        assert.deepStrictEqual([...tickGroup(new Set(),q.groups[0],true)].sort(),['tools\u0000alpha-tool','tools\u0000beta-tool']);
        assert.deepStrictEqual([...tickGroup(new Set(['tools\u0000alpha-tool','orbit\u0000gamma-pr']),q.groups[0],false)],['orbit\u0000gamma-pr']);
        assert.deepStrictEqual([...recommendedOf(q)].sort(),['orbit\u0000gamma-pr','tools\u0000beta-tool']);
        """)

    # ── snooze ─────────────────────────────────────────────────────────────

    def test_a_snoozed_thread_waits_in_its_own_section_until_it_wakes(self):
        self.pure_js(r"""
        const T=(id,slot,state,extra)=>Object.assign({id,slot,state,status:'open',created:slot,messages:[]},extra);
        const rows=[T('a',1,'on-owner'),T('b',2,'on-owner',{snooze:{until:5000,set:100}}),T('c',3,'working',{snooze:{until:2000,set:100}}),T('d',4,'done')];
        const sb=sidebar(rows);
        // asleep: out of "on him" and "working", listed by who wakes first, each still with its own slot
        assert.deepStrictEqual(sb.sections.map(x=>x.key+':'+x.rows.map(r=>r.t.id).join(',')),['on-owner:a','working:','done:d']);
        assert.deepStrictEqual(sb.snoozed.map(r=>r.slot+r.t.id),['3c','2b']);
        assert.deepStrictEqual(sidebar([]).snoozed,[]);
        // a record without a proper time is not asleep; a closed one is in the archive
        assert.deepStrictEqual(sidebar([T('x',1,'working',{snooze:{}}),T('y',2,'working',{snooze:'tomorrow'})]).snoozed,[]);
        assert.deepStrictEqual(sidebar([T('z',1,'done',{status:'closed',snooze:{until:9}})]).snoozed,[]);
        // waking: the reminder is news even when the thread was already on him
        const before={a:T('a',1,'on-owner'),b:T('b',2,'working',{snooze:{until:5}})},after={a:T('a',1,'on-owner',{reminder:{ts:9,until:5}}),b:T('b',2,'on-owner',{reminder:{ts:9,until:5}})};
        assert.deepStrictEqual(turnedOnYou(before,after),['a','b']);assert.deepStrictEqual(turnedOnYou(after,after),[]);
        """)

    def test_snooze_presets_are_real_clock_times(self):
        self.pure_js(r"""
        const at=(y,m,d,h,min)=>new Date(y,m-1,d,h,min||0).getTime()/1000,show=list=>list.map(p=>p.label+'='+new Date(p.until*1000).toISOString().slice(0,16));
        // Monday 16.11.2026, 10:30 (the tests run in UTC)
        assert.deepStrictEqual(show(snoozePresets(at(2026,11,16,10,30))),['בעוד שעה=2026-11-16T11:30','הערב 20:00=2026-11-16T20:00','מחר 09:00=2026-11-17T09:00','בשבוע הבא (יום ראשון 09:00)=2026-11-22T09:00']);
        // late in the evening "this evening" is over; on a Sunday "next week" is the Sunday after
        assert.deepStrictEqual(show(snoozePresets(at(2026,11,16,19,45))),['בעוד שעה=2026-11-16T20:45','מחר 09:00=2026-11-17T09:00','בשבוע הבא (יום ראשון 09:00)=2026-11-22T09:00']);
        assert.strictEqual(show(snoozePresets(at(2026,11,22,8,0)))[3],'בשבוע הבא (יום ראשון 09:00)=2026-11-29T09:00');
        // the wake time in a row
        const now=at(2026,11,16,10,30);
        assert.strictEqual(wakeLabel(at(2026,11,16,20,0),now),'היום 20:00');assert.strictEqual(wakeLabel(at(2026,11,17,9,0),now),'מחר 09:00');
        assert.strictEqual(wakeLabel(at(2026,11,22,9,0),now),'יום ראשון 09:00');assert.strictEqual(wakeLabel(at(2026,12,3,9,0),now),'03/12 09:00');
        // a time typed by hand: only the future, and not beyond a year
        assert.strictEqual(customSnooze('2026-11-17T09:00',now),at(2026,11,17,9,0));
        for(const bad of ['2026-11-16T10:00','','nonsense','2028-01-01T00:00',null])assert.strictEqual(customSnooze(bad,now),null,String(bad));
        """)

    # ── replying to one message ────────────────────────────────────────────

    def test_a_reply_quotes_the_message_it_answers(self):
        self.pure_js(r"""
        const list=[{id:'m1',from:'fork',text:'**סיימתי** את הבדיקה.\nפרטים למטה',ts:1},{id:'m2',from:'owner',text:'מה עם staging?',ts:2},
                    {id:'m3',from:'tower',text:'x',ts:3,snippet:{file:'snippets/a/m3.log',name:'api.log',only:true,head:'0001 ERROR',chars:9000,lines:80}}];
        // the stored shape: the server already wrote who and what
        assert.deepStrictEqual(quoteOf({id:'m1',from:'fork',text:'סיימתי את הבדיקה.'},list),{id:'m1',who:'סוכן',text:'סיימתי את הבדיקה.',excerpt:false});
        // an unsent reply only knows the id: the page finds the message itself
        assert.deepStrictEqual(quoteOf('m1',list),{id:'m1',who:'סוכן',text:'סיימתי את הבדיקה. פרטים למטה',excerpt:false});
        assert.deepStrictEqual(quoteOf('m2',list),{id:'m2',who:'אני',text:'מה עם staging?',excerpt:false});
        assert.deepStrictEqual(quoteOf('m3',list),{id:'m3',who:'מגדל',text:'api.log',excerpt:false});            // a message that is only a snippet: its name
        assert.strictEqual(quoteOf('m9',list),null);assert.strictEqual(quoteOf(null,list),null);assert.strictEqual(quoteOf({from:'fork'},list),null);
        assert.ok(quoteOf({id:'m1',from:'fork',text:'x'.repeat(500)},list).text.length<=140);
        // answering only the words he selected: the quote is those words, his own on their way or the ones the server stored
        assert.deepStrictEqual(quoteOf('m1',list,'פרטים למטה'),{id:'m1',who:'סוכן',text:'«פרטים למטה»',excerpt:true});
        assert.deepStrictEqual(quoteOf({id:'m1',from:'fork',text:'סיימתי את הבדיקה.',quote:'את הבדיקה'},list),{id:'m1',who:'סוכן',text:'«את הבדיקה»',excerpt:true});
        assert.strictEqual(quoteOf('m9',list,'x'),null);assert.strictEqual(quoteOf('m1',list,'').excerpt,false);
        // the excerpt: no hidden marks, even spaces, six lines and 500 characters at most
        assert.strictEqual(excerptOf('  ‏העלות   ירדה ב-55%  \n\n  אחרי המעבר ל-Spot \n'),'העלות ירדה ב-55%\nאחרי המעבר ל-Spot');
        assert.strictEqual(excerptOf(Array.from({length:9},(_,i)=>'שורה '+i).join('\n')),'שורה 0\nשורה 1\nשורה 2\nשורה 3\nשורה 4\nשורה 5…');
        assert.strictEqual(excerptOf('x'.repeat(900)).length,500);assert.ok(excerptOf('x'.repeat(900)).endsWith('…'));assert.strictEqual(excerptOf(''),'');assert.strictEqual(excerptOf(null),'');
        // what he is replying to, as it is kept between visits
        assert.deepStrictEqual(replyRef('m12'),{id:'m12',quote:''});assert.deepStrictEqual(replyRef(''),{id:'',quote:''});assert.deepStrictEqual(replyRef(null),{id:'',quote:''});
        assert.deepStrictEqual(replyRef('{"id":"m3","quote":"  שתי   מילים "}'),{id:'m3',quote:'שתי מילים'});assert.deepStrictEqual(replyRef('{"id":7}'),{id:'',quote:''});assert.deepStrictEqual(replyRef('{broken'),{id:'',quote:''});
        // for a server without a field for it, the excerpt stands at the top of his words as a quote
        assert.strictEqual(quotedText('שורה א\nשורה ב','ומה עם זה?'),'> שורה א\n> שורה ב\n\nומה עם זה?');assert.strictEqual(quotedText('קטע',''),'> קטע');assert.strictEqual(quotedText('','רק טקסט'),'רק טקסט');
        // a sideways drag of a finger is a reply only when it is clearly sideways and long enough
        assert.strictEqual(swipeOf(70,5),'reply');assert.strictEqual(swipeOf(-90,-12),'reply');
        assert.strictEqual(swipeOf(40,0),'drag');assert.strictEqual(swipeOf(-20,3),'drag');
        assert.strictEqual(swipeOf(8,2),'none');assert.strictEqual(swipeOf(30,40),'scroll');assert.strictEqual(swipeOf(70,60),'scroll');assert.strictEqual(swipeOf(0,20),'scroll');
        // reactions, whatever shape they arrive in
        assert.deepStrictEqual(reactionsOf({reactions:{'👍':{by:'owner',ts:1},'❓':{by:'tower',ts:2}}}),[{emoji:'👍',mine:true},{emoji:'❓',mine:false}]);
        assert.deepStrictEqual(reactionsOf({reactions:{'✅':true,'🤖':{by:'owner'},'👍':null}}),[{emoji:'✅',mine:true}]);
        assert.deepStrictEqual(reactionsOf({}),[]);assert.deepStrictEqual(reactionsOf({reactions:'x'}),[]);
        // R answers the chosen message, M copies it: bare keys, so never while typing
        const idle={typing:false,options:0,mac:true};
        assert.strictEqual(keyAction({code:'KeyM',key:'צ'},idle),'copy-message');assert.strictEqual(keyAction({code:'KeyM'},{typing:true,options:0,mac:true}),null);
        """)

    # ── tasks ──────────────────────────────────────────────────────────────

    def test_tasks_add_up_to_a_bar_and_a_line(self):
        self.pure_js(r"""
        const T=(n,status,extra)=>Object.assign({n,text:'משימה '+n,status},extra);
        // his five-item message: two in work, one being built, two done
        let st=taskStats([T(1,'working'),T(2,'done'),T(3,'building'),T(4,'working'),T(5,'done')]);
        assert.strictEqual(st.total,5);assert.strictEqual(st.line,'2 בעבודה · 1 בבנייה · 2 הושלמו (מתוך 5)');
        // the bar: finished first, then what moves, then what waits; only what exists
        assert.deepStrictEqual(st.segments,[{status:'done',n:2},{status:'building',n:1},{status:'working',n:2}]);
        st=taskStats([T(1,'todo'),T(2,'on-owner'),T(3,'blocked'),T(4,'todo')]);
        assert.strictEqual(st.line,'1 עליך · 1 חסומות · 2 לביצוע · 0 הושלמו (מתוך 4)');
        assert.deepStrictEqual(st.segments,[{status:'on-owner',n:1},{status:'blocked',n:1},{status:'todo',n:2}]);
        // the same words in parts: a narrow screen shows whole parts only, his own first
        assert.deepStrictEqual(st.parts,[{status:'on-owner',n:1,text:'1 עליך'},{status:'blocked',n:1,text:'1 חסומות'},{status:'todo',n:2,text:'2 לביצוע'},{status:'done',n:0,text:'0 הושלמו'}]);
        assert.strictEqual(st.parts.map(part=>part.text).join(' · ')+' (מתוך '+st.total+')',st.line);
        assert.strictEqual(taskStats([T(1,'done')]).line,'1 הושלמו (מתוך 1)');
        assert.deepStrictEqual(taskStats([]),{total:0,segments:[],parts:[],line:'',archived:0});assert.strictEqual(taskStats(undefined).total,0);
        // The owner, thread suda m256: "completed tasks should move to a kind of archive, so that the colour bar
        // reflects only the current state". A task with `archived` is out of the bar, the counts and the sections.
        const A=(n,when)=>T(n,'done',{archived:when});
        const mixed=[T(1,'working'),A(2,500),T(3,'done'),A(4,900),T(5,'on-owner'),A(6,900)];
        st=taskStats(mixed);
        assert.strictEqual(st.total,3);assert.strictEqual(st.archived,3);assert.strictEqual(st.line,'1 עליך · 1 בעבודה · 1 הושלמו (מתוך 3)');
        assert.deepStrictEqual(st.segments,[{status:'done',n:1},{status:'working',n:1},{status:'on-owner',n:1}]);
        assert.deepStrictEqual(taskParts(mixed).live.map(k=>k.n),[1,3,5]);
        assert.deepStrictEqual(taskParts(mixed).archived.map(k=>k.n),[6,4,2]);          // the last put away first
        assert.deepStrictEqual(taskView(mixed,taskPrefs('')).map(part=>[part.key,part.tasks.map(k=>k.n)]),[['on-owner',[5]],['working',[1]],['done',[3]]]);
        assert.deepStrictEqual(taskView(mixed,taskPrefs('recent'))[0].tasks.map(k=>k.n).sort(),[1,3,5]);
        assert.deepStrictEqual([taskGroups(mixed).mine.length,taskGroups(mixed).theirs.length],[1,2]);
        // everything put away: no bar, and the line says where the tasks are
        st=taskStats([A(1,5),A(2,6)]);
        assert.deepStrictEqual(st,{total:0,segments:[],parts:[],line:'אין משימות פתוחות · 2 בארכיון',archived:2});
        for(const odd of [0,null,undefined,'',NaN,-4])assert.strictEqual(isArchived(T(1,'done',{archived:odd})),false);
        assert.strictEqual(isArchived(A(1,1794800000)),true);assert.strictEqual(isArchived(null),false);
        assert.deepStrictEqual(taskParts(null),{live:[],archived:[]});
        // the board's data: the stamp is kept only on a done task, as a number
        const kept=normalize({version:2,threads:{a:{id:'a',title:'א',status:'open',messages:[],tasks:[{n:1,text:'x',status:'done',archived:77},{n:2,text:'y',status:'working',archived:77},{n:3,text:'z',status:'done',archived:'soon'},{n:4,text:'w',status:'done'}]}}}).threads.a.tasks;
        assert.deepStrictEqual(kept.map(k=>k.archived),[77,0,0,0]);
        assert.strictEqual(taskLabel('building'),'בבנייה');assert.strictEqual(taskLabel('todo'),'לביצוע');assert.strictEqual(taskLabel('on-owner'),'עליך');
        // one tap on the box: done, and back to "to do" from done
        assert.strictEqual(tapStatus('working'),'done');assert.strictEqual(tapStatus('todo'),'done');assert.strictEqual(tapStatus('blocked'),'done');assert.strictEqual(tapStatus('done'),'todo');
        // a damaged record is dropped or mended; the page never throws on it
        const data=normalize({version:2,threads:{a:{status:'open',messages:[],tasks:[T(1,'working',{owner:'fork',note:'בודק',from:'m3'}),null,{n:'x',text:'y'},{n:2,text:'',status:'done'},T(3,'weird'),{n:4,text:7,status:'todo'},T(1,'done')]},b:{status:'open',messages:[],tasks:'x'}}});
        assert.deepStrictEqual(data.threads.a.tasks.map(k=>[k.n,k.status,k.owner,k.note,k.from]),[[1,'working','fork','בודק','m3'],[3,'todo','','',null]]);
        assert.deepStrictEqual(data.threads.b.tasks,[]);
        """)

    # ── renaming, drafts ───────────────────────────────────────────────────

    def test_a_new_title_is_one_clean_line(self):
        self.pure_js(r"""
        assert.deepStrictEqual(titleFor('  Snap Linux \u2014\n  מיזוג  '),{title:'Snap Linux \u2014 מיזוג',error:''});
        assert.deepStrictEqual(titleFor('x'.repeat(120)),{title:'x'.repeat(120),error:''});
        assert.ok(titleFor('x'.repeat(121)).error.includes('120'));assert.ok(titleFor('   \n ').error);assert.ok(titleFor(null).error);
        // F2 renames the open channel, and like every bare key only when he is not typing
        assert.strictEqual(keyAction({code:'F2',key:'F2'},{typing:false,options:0,mac:true}),'rename');
        assert.strictEqual(keyAction({code:'F2',key:'F2'},{typing:true,options:0,mac:true}),null);
        assert.strictEqual(keyAction({code:'F2',key:'F2',metaKey:true},{typing:false,options:0,mac:true}),null);
        """)

    def test_a_draft_from_another_device_never_costs_him_text(self):
        self.pure_js(r"""
        const L=(text,ts,dirty)=>({text,ts,dirty}),R=(text,ts)=>({text,ts});
        const out=(l,r)=>{const m=mergeDraft(l,r);return [m.text,m.ts,m.dirty,m.took];};
        // nothing newer on the server: what is here stays as it is
        assert.deepStrictEqual(out(L('כאן',10,true),null),['כאן',10,true,'none']);assert.deepStrictEqual(out(L('כאן',10,false),R('שם',10)),['כאן',10,false,'none']);
        assert.deepStrictEqual(out(L('כאן',10,false),R('ישן',5)),['כאן',10,false,'none']);
        // he has not typed here since the last sync: the server's newer copy comes in, also when it is empty (sent or cleared there)
        assert.deepStrictEqual(out(L('ישן',10,false),R('חדש ממכשיר אחר',20)),['חדש ממכשיר אחר',20,false,'remote']);
        assert.deepStrictEqual(out(L('נשלח כבר',10,false),R('',20)),['',20,false,'remote']);
        assert.deepStrictEqual(out(L('',0,false),R('מהמחשב',5)),['מהמחשב',5,false,'remote']);
        // both changed since they last agreed: both are kept, his first
        assert.deepStrictEqual(out(L('כתבתי כאן',10,true),R('כתבתי שם',20)),['כתבתי כאן\n\nכתבתי שם',20,true,'both']);
        // cleared there while he is still writing here: his text stays, and still needs saving
        assert.deepStrictEqual(out(L('עוד כותב',10,true),R('',20)),['עוד כותב',20,true,'none']);
        // the same text on both sides is simply in sync
        assert.deepStrictEqual(out(L('זהה',10,true),R('זהה',20)),['זהה',20,false,'none']);
        // a damaged record never erases anything
        for(const bad of [{text:'x'},{text:7,ts:99},{ts:99},'x',7])assert.deepStrictEqual(out(L('כאן',10,true),bad),['כאן',10,true,'none']);
        assert.deepStrictEqual(out({},R('מהשרת',3)),['מהשרת',3,false,'remote']);
        """)

    def test_enter_continues_a_list_in_the_composer(self):
        self.pure_js(r"""
        const at=(text)=>{const i=text.indexOf('|');return [text.replace('|',''),i];};       // "|" marks the caret
        const show=r=>r?r.text.slice(0,r.caret)+'|'+r.text.slice(r.caret):null;
        const enter=text=>{const [v,c]=at(text);return show(continueList(v,c,c));};
        const back=text=>{const [v,c]=at(text);return show(endListItem(v,c,c));};
        // a numbered item is followed by the next number, Hebrew or not
        assert.strictEqual(enter('1. לבדוק את הלוג|'),'1. לבדוק את הלוג\n2. |');
        assert.strictEqual(enter('הקדמה\n9. check logs|'),'הקדמה\n9. check logs\n10. |');
        assert.strictEqual(enter('1) א|'),'1) א\n2) |');assert.strictEqual(enter('  3. מוזח|'),'  3. מוזח\n  4. |');
        // a bullet is followed by the same bullet
        assert.strictEqual(enter('- א|'),'- א\n- |');assert.strictEqual(enter('* a|'),'* a\n* |');assert.strictEqual(enter('• א|'),'• א\n• |');
        // in the middle of an item the rest moves to the new one, and the numbers below move up by one
        assert.strictEqual(enter('1. ראשון| והמשך\n2. שני\n3. שלישי\nסוף'),'1. ראשון\n2. | והמשך\n3. שני\n4. שלישי\nסוף');
        assert.strictEqual(enter('1. א|\n2. ב\n5. לא ברצף'),'1. א\n2. |\n3. ב\n5. לא ברצף');
        // Enter on an empty item ends the list: the marker goes, the caret stays on that line
        assert.strictEqual(enter('1. א\n2. |'),'1. א\n|');assert.strictEqual(enter('- א\n- |'),'- א\n|');assert.strictEqual(enter('  - |'),'|');
        // Backspace on an empty item does the same; anywhere else it is an ordinary Backspace
        assert.strictEqual(back('1. א\n2. |'),'1. א\n|');assert.strictEqual(back('- |'),'|');
        assert.strictEqual(back('1. א|'),null);assert.strictEqual(back('2. |טקסט'),null);assert.strictEqual(back('טקסט|'),null);
        // not a list: nothing special
        for(const plain of ['שורה רגילה|','1.בלי רווח|','15.11 בערב|','|','2026. |x'])assert.strictEqual(enter(plain),null,plain);
        // a selection is not a caret
        assert.strictEqual(continueList('1. אבג',3,5),null);assert.strictEqual(endListItem('1. ',0,3),null);
        """)

    # ── keyboard ───────────────────────────────────────────────────────────

    def test_the_composers_arrows_scroll_a_short_text_and_home_end_keep_to_the_line(self):
        # m245: in the composer, up and down scroll the conversation unless the text has several lines; m246: Home and
        # End go to the logical start and end of the line (a Hebrew line reads the browser's visual ones backwards).
        self.pure_js(r"""
        const k=(code,extra)=>Object.assign({code},extra),box=(value,at,to,dir)=>({value,selectionStart:at,selectionEnd:to===undefined?at:to,selectionDirection:dir||'none'});
        const none={options:0},asked={options:3};
        // one line, or nothing: the arrows scroll, a step per press; PageUp/PageDown a page
        assert.deepStrictEqual(composerKey(k('ArrowDown'),box('',0),none),{act:'scroll',dir:1,page:false});
        assert.deepStrictEqual(composerKey(k('ArrowUp'),box('שורה אחת',3),none),{act:'scroll',dir:-1,page:false});
        assert.deepStrictEqual(composerKey(k('PageDown'),box('שורה אחת',3),none),{act:'scroll',dir:1,page:true});
        assert.deepStrictEqual(composerKey(k('PageUp'),box('',0),none),{act:'scroll',dir:-1,page:true});
        // several lines: the caret moves as usual, and scrolls only from the first (up) or the last (down) line
        const two='ראשונה\nשנייה';
        assert.strictEqual(composerKey(k('ArrowUp'),box(two,9),none),null);
        assert.deepStrictEqual(composerKey(k('ArrowUp'),box(two,3),none),{act:'scroll',dir:-1,page:false});
        assert.strictEqual(composerKey(k('ArrowDown'),box(two,3),none),null);
        assert.deepStrictEqual(composerKey(k('ArrowDown'),box(two,9),none),{act:'scroll',dir:1,page:false});
        assert.strictEqual(composerKey(k('PageDown'),box(two,3),none),null);
        // an open question's answers take the arrows from the EMPTY box only; a word in the box scrolls again
        assert.strictEqual(composerKey(k('ArrowDown'),box('',0),asked),null);
        assert.deepStrictEqual(composerKey(k('ArrowDown'),box('מילה',2),asked),{act:'scroll',dir:1,page:false});
        // selecting and the system's own chords stay the browser's
        for(const extra of [{shiftKey:true},{metaKey:true},{ctrlKey:true},{altKey:true},{isComposing:true}])assert.strictEqual(composerKey(k('ArrowDown',extra),box('',0),none),null,JSON.stringify(extra));
        // Home and End: the logical start and end of the caret's line, in Hebrew and in English alike
        assert.deepStrictEqual(composerKey(k('Home'),box('שלום עולם',4),none),{act:'caret',start:0,end:0,direction:'none'});
        assert.deepStrictEqual(composerKey(k('End'),box('שלום עולם',4),none),{act:'caret',start:9,end:9,direction:'none'});
        assert.deepStrictEqual(composerKey(k('Home'),box('hello world',4),none),{act:'caret',start:0,end:0,direction:'none'});
        assert.deepStrictEqual(composerKey(k('End'),box(two,9),none),{act:'caret',start:12,end:12,direction:'none'});
        assert.deepStrictEqual(composerKey(k('Home'),box(two,9),none),{act:'caret',start:7,end:7,direction:'none'});
        assert.deepStrictEqual(composerKey(k('End'),box(two,2),none),{act:'caret',start:6,end:6,direction:'none'});
        // Shift+Home / Shift+End extend the selection from where it was anchored
        assert.deepStrictEqual(composerKey(k('Home',{shiftKey:true}),box('שלום עולם',4),none),{act:'caret',start:0,end:4,direction:'backward'});
        assert.deepStrictEqual(composerKey(k('End',{shiftKey:true}),box('שלום עולם',2,4,'forward'),none),{act:'caret',start:2,end:9,direction:'forward'});
        assert.deepStrictEqual(composerKey(k('Home',{shiftKey:true}),box('שלום עולם',2,4,'backward'),none),{act:'caret',start:0,end:4,direction:'backward'});
        // an empty box has no line: Home and End are the conversation's (keyAction), with ⌘/Ctrl they are the browser's
        assert.strictEqual(composerKey(k('Home'),box('',0),none),null);
        assert.strictEqual(composerKey(k('End',{metaKey:true}),box('שלום',2),none),null);
        assert.deepStrictEqual(caretLine('א\nבג\nד',3),{start:2,end:4,first:false,last:false});
        """)

    def test_shortcuts_follow_the_key_position_not_the_letter(self):
        self.pure_js(r"""
        const idle={typing:false,options:0,mac:true},typing={typing:true,options:0,mac:true};
        const k=(code,extra)=>Object.assign({code,key:'?'},extra);
        // With the Hebrew layout the same keys produce other letters; only `code` may decide.
        assert.strictEqual(keyAction(k('KeyR',{key:'ר'}),idle),'reply');
        assert.strictEqual(keyAction(k('KeyE',{key:'ק'}),idle),'read');assert.strictEqual(keyAction(k('KeyE',{key:'E',shiftKey:true}),idle),'read-all');
        assert.strictEqual(keyAction(k('KeyC',{key:'ב'}),idle),'close');assert.strictEqual(keyAction(k('KeyI',{key:'ן'}),idle),'details');
        assert.strictEqual(keyAction(k('KeyL',{key:'ך'}),idle),'copy-link');
        // Shift+T: the tower, from anywhere (tower m333); T alone stays the tasks; not while he types
        assert.strictEqual(keyAction(k('KeyT',{key:'T',shiftKey:true}),idle),'tower');assert.strictEqual(keyAction(k('KeyT',{key:'א',shiftKey:true}),idle),'tower');
        assert.strictEqual(keyAction(k('KeyT',{key:'t'}),idle),'tasks');assert.strictEqual(keyAction(k('KeyT',{key:'T',shiftKey:true}),typing),null);
        assert.strictEqual(keyAction(k('Slash',{key:'.'}),idle),'find');assert.strictEqual(keyAction(k('Slash',{key:'?',shiftKey:true}),idle),'help');
        assert.strictEqual(keyAction(k('KeyQ',{key:'/'}),idle),null);              // the Hebrew "/" sits on Q: not a shortcut
        assert.strictEqual(keyAction(k('KeyK',{key:'ל',metaKey:true}),typing),'switcher');assert.strictEqual(keyAction(k('KeyK',{key:'ל',ctrlKey:true}),typing),'switcher');
        // Nothing without ⌘ or ⌥ fires while he types; Esc always leaves.
        for(const code of ['KeyR','KeyE','KeyC','KeyI','KeyL','Slash','Digit1','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'])
         assert.strictEqual(keyAction(k(code),{typing:true,options:9,mac:true}),null,code);
        assert.strictEqual(keyAction(k('Escape'),typing),'escape');assert.strictEqual(keyAction(k('Escape'),idle),'escape');
        // …and the ones with ⌘ or ⌥ do.
        assert.strictEqual(keyAction(k('KeyF',{metaKey:true}),typing),'find');assert.strictEqual(keyAction(k('Slash',{metaKey:true}),typing),'help');
        assert.strictEqual(keyAction(k('Enter',{metaKey:true}),typing),'send');assert.strictEqual(keyAction(k('NumpadEnter',{ctrlKey:true}),idle),'send');
        assert.strictEqual(keyAction(k('ArrowDown',{altKey:true}),typing),'next-channel');assert.strictEqual(keyAction(k('ArrowUp',{altKey:true}),typing),'prev-channel');
        assert.strictEqual(keyAction(k('ArrowDown',{altKey:true,shiftKey:true}),typing),'next-attention');assert.strictEqual(keyAction(k('ArrowUp',{altKey:true,shiftKey:true}),idle),'prev-attention');
        // A system shortcut is never taken: ⌘C copies, ⌘R reloads, ⌘L goes to the address bar.
        for(const code of ['KeyC','KeyR','KeyL','KeyE','KeyI'])for(const mod of ['metaKey','ctrlKey','altKey'])
         assert.strictEqual(keyAction(k(code,{[mod]:true}),{typing:false,options:9,mac:true}),null,code+'+'+mod);
        assert.strictEqual(keyAction(k('Digit1',{metaKey:true}),{typing:false,options:9,mac:true}),null,'⌘1 is the browser\'s first tab');
        assert.strictEqual(keyAction(k('Digit1',{ctrlKey:true}),{typing:false,options:9,mac:false}),null,'Ctrl+1 is the browser\'s first tab off a Mac');
        assert.strictEqual(keyAction(k('KeyC',{shiftKey:true}),idle),null);assert.strictEqual(keyAction(k('KeyR',{shiftKey:true}),idle),null);
        // On a Mac, Ctrl+F and Ctrl+/ stay the text field's own; elsewhere Ctrl is the modifier.
        assert.strictEqual(keyAction(k('KeyF',{ctrlKey:true}),typing),null);assert.strictEqual(keyAction(k('KeyF',{ctrlKey:true}),{typing:true,options:0,mac:false}),'find');
        assert.strictEqual(keyAction(k('Slash',{ctrlKey:true}),{typing:true,options:0,mac:false}),'help');assert.strictEqual(keyAction(k('KeyF',{metaKey:true,shiftKey:true}),idle),null);
        // 1 to 9 answer only while that many quick answers are on screen.
        const asked={typing:false,options:3,mac:true};
        assert.strictEqual(keyAction(k('Digit1',{key:'1'}),asked),'answer-1');assert.strictEqual(keyAction(k('Numpad3'),asked),'answer-3');
        assert.strictEqual(keyAction(k('Digit4'),asked),null);assert.strictEqual(keyAction(k('Digit1'),idle),null);assert.strictEqual(keyAction(k('Digit0'),asked),null);
        assert.strictEqual(keyAction(k('Digit1',{shiftKey:true}),asked),null);
        // reading without a mouse
        assert.strictEqual(keyAction(k('ArrowUp'),idle),'msg-prev');assert.strictEqual(keyAction(k('ArrowDown'),idle),'msg-next');
        // an open question with answers: digits choose, also from the empty composer. Up and down walk its answers from
        // the empty composer and from an answer itself (never left and right); elsewhere they choose messages, as always.
        assert.strictEqual(keyAction(k('ArrowDown'),asked),'msg-next');assert.strictEqual(keyAction(k('ArrowUp'),asked),'msg-prev');
        const onOption={typing:false,onOption:true,options:3,mac:true};
        assert.strictEqual(keyAction(k('ArrowDown'),onOption),'opt-next');assert.strictEqual(keyAction(k('ArrowUp'),onOption),'opt-prev');
        assert.strictEqual(keyAction(k('ArrowLeft'),onOption),null);assert.strictEqual(keyAction(k('ArrowRight'),onOption),null);
        assert.strictEqual(keyAction(k('Digit2'),onOption),'answer-2');
        const emptyBox={typing:true,emptyBox:true,options:2,mac:true},writing={typing:true,emptyBox:false,options:2,mac:true};
        assert.strictEqual(keyAction(k('Digit2'),emptyBox),'answer-2');assert.strictEqual(keyAction(k('Digit3'),emptyBox),null);assert.strictEqual(keyAction(k('ArrowDown'),emptyBox),'opt-next');
        // the empty composer: Home and End go to the start and the end of the conversation
        assert.strictEqual(keyAction(k('End'),emptyBox),'latest');assert.strictEqual(keyAction(k('Home'),emptyBox),'top');assert.strictEqual(keyAction(k('End'),writing),null);
        // inside the chosen message the side arrows walk its buttons: left on (the page reads right to left), right back
        const inMessage={typing:false,inMessage:true,options:0,mac:true};
        assert.strictEqual(keyAction(k('ArrowLeft'),inMessage),'item-next');assert.strictEqual(keyAction(k('ArrowRight'),inMessage),'item-prev');
        assert.strictEqual(keyAction(k('ArrowLeft'),idle),null);assert.strictEqual(keyAction(k('ArrowLeft',{shiftKey:true}),inMessage),null);
        assert.strictEqual(keyAction(k('ArrowLeft'),{typing:true,inMessage:true,options:0,mac:true}),null,'a caret moves in a text box');
        // a notice with a button: G presses it from anywhere he is not writing, the empty composer included; never mid-word
        const bubble={typing:false,bubble:true,options:0,mac:true};
        assert.strictEqual(keyAction(k('KeyG',{key:'ע'}),bubble),'bubble');assert.strictEqual(keyAction(k('KeyG'),{typing:true,emptyBox:true,bubble:true,options:0,mac:true}),'bubble');
        assert.strictEqual(keyAction(k('KeyG'),{typing:true,emptyBox:false,bubble:true,options:0,mac:true}),null);assert.strictEqual(keyAction(k('KeyG'),idle),null);
        assert.strictEqual(keyAction(k('KeyG',{shiftKey:true}),bubble),null);assert.strictEqual(keyAction(k('KeyG',{metaKey:true}),bubble),null);
        assert.strictEqual(keyAction(k('KeyR'),emptyBox),null,'a letter in the composer is a letter');assert.strictEqual(keyAction(k('KeyE'),emptyBox),null);
        assert.strictEqual(keyAction(k('Digit2'),writing),null,'once he writes, a digit is a digit');assert.strictEqual(keyAction(k('ArrowDown'),writing),null);
        assert.strictEqual(keyAction(k('Digit1'),{typing:true,emptyBox:true,options:0,mac:true}),null);assert.strictEqual(keyAction(k('ArrowDown'),{typing:true,emptyBox:true,options:0,mac:true}),null);
        assert.strictEqual(keyAction(k('Digit1',{shiftKey:true}),emptyBox),null);
        assert.strictEqual(keyAction(k('PageUp'),idle),'page-up');assert.strictEqual(keyAction(k('PageDown'),idle),'page-down');
        assert.strictEqual(keyAction(k('Home'),idle),'top');assert.strictEqual(keyAction(k('End'),idle),'latest');
        // an input method that is still composing owns the key; an unknown key is nothing
        assert.strictEqual(keyAction(k('KeyR',{isComposing:true}),idle),null);assert.strictEqual(keyAction(k('KeyR',{keyCode:229}),idle),null);
        for(const code of ['KeyX','toString','constructor','',undefined])assert.strictEqual(keyAction(k(code),idle),null,String(code));
        // Esc is Esc whatever the keyboard is in the middle of, and whether or not the key has a place
        const inBox={typing:true,options:0,mac:true};
        assert.strictEqual(keyAction(k('Escape',{isComposing:true}),inBox),'escape');assert.strictEqual(keyAction(k('Escape',{keyCode:229}),inBox),'escape');
        assert.strictEqual(keyAction(k('',{key:'Escape'}),inBox),'escape');assert.strictEqual(keyAction(k('Escape',{metaKey:true}),idle),'escape');
        assert.strictEqual(keyAction(k('KeyZ',{key:'ז'}),idle),'snooze');
        """)

    def test_the_agents_of_the_thread_are_reached_by_keys_that_clash_with_none(self):
        """The owner, suda m630 (suda-fixes task 8): the agents of the open thread (the live card) by keyboard. Alt+1..9
        puts the keys on agent N from anywhere, the reply box included (Option+digit on a Mac: Ctrl+digits are the
        browser's tabs off a Mac, and on a Mac they are taken too, as he asked, since its tabs are Cmd+digits; so on a
        phone). Alt+A, or A where he is not writing, moves the keys into the panel and back. In the panel the arrows
        walk the agents (up and down) and a row's own buttons (left on, right back, as the page reads), Home and End go
        to the first and the last, Enter on a row opens the agent's thread. Nothing that was there moves: the digits
        still answer, J/K, Alt+arrows, Shift+T and Esc are what they were."""
        self.pure_js(r"""
        const k=(code,extra)=>Object.assign({code,key:'?'},extra);
        const idle={typing:false,options:0,mac:true},box={typing:true,inBox:true,emptyBox:true,options:0,mac:true},writing={typing:true,inBox:true,emptyBox:false,options:0,mac:true};
        const pc={typing:false,options:0,mac:false},phone={typing:true,inBox:true,emptyBox:false,options:0,mac:false,ctrlDigits:true};
        // another text field (the rename box, the find bar, a dialog's text): never taken from there, whatever the system
        const field={typing:true,options:0,mac:true},pcField={typing:true,options:0,mac:false},phoneField={typing:true,options:0,mac:false,ctrlDigits:true};
        // agent N: Alt+1..9 from anywhere, the empty reply box included, whatever the layout (only the place of the key counts)
        for(let n=1;n<=9;n++){
          assert.strictEqual(keyAction(k('Digit'+n,{altKey:true,key:'¡'}),box),'agent-'+n);
          assert.strictEqual(keyAction(k('Digit'+n,{altKey:true}),idle),'agent-'+n);
          assert.strictEqual(keyAction(k('Digit'+n,{altKey:true}),pc),'agent-'+n);
          assert.strictEqual(keyAction(k('Digit'+n,{altKey:true}),{...pc,typing:true,inBox:true}),'agent-'+n,'off a Mac Alt+digit types nothing');
          for(const at of [field,pcField,phoneField])for(const mod of ['altKey','ctrlKey'])
            assert.strictEqual(keyAction(k('Digit'+n,{[mod]:true}),at),null,'taken from another text field: '+mod+' '+JSON.stringify(at));
          // on a Mac, Option+digit in a text he is writing is a character (₪, ¡, ™): it stays his; Ctrl+digit is there
          assert.strictEqual(keyAction(k('Digit'+n,{altKey:true,key:'₪'}),writing),null);
          assert.strictEqual(keyAction(k('Digit'+n,{ctrlKey:true}),writing),'agent-'+n);
          // Alt with the digits of the number pad is how Windows types a character by its code: never taken
          assert.strictEqual(keyAction(k('Numpad'+n,{altKey:true}),pc),null);
        }
        assert.strictEqual(keyAction(k('Digit0',{altKey:true}),idle),null);
        assert.strictEqual(keyAction(k('Digit1',{altKey:true,shiftKey:true}),idle),null);
        // Ctrl+1..9 where the browser leaves them free: a Mac (its tabs are Cmd+digits) and a phone; never off a Mac in a browser
        assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true}),writing),'agent-3');assert.strictEqual(keyAction(k('Numpad9',{ctrlKey:true}),idle),'agent-9');
        assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true}),phone),'agent-3');
        assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true}),pc),null);assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true}),{...pc,typing:true}),null);
        assert.strictEqual(keyAction(k('Digit3',{metaKey:true}),idle),null);assert.strictEqual(keyAction(k('Digit3',{metaKey:true,ctrlKey:true}),idle),null);
        assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true,shiftKey:true}),idle),null);
        assert.strictEqual(keyAction(k('Digit3',{ctrlKey:true,altKey:true}),idle),null,'AltGr+digit types a character');
        // into the panel and back: A where he is not writing, Alt+A from anywhere
        assert.strictEqual(keyAction(k('KeyA',{key:'ש'}),idle),'agents');assert.strictEqual(keyAction(k('KeyA'),box),null,'a letter in the box is a letter');
        assert.strictEqual(keyAction(k('KeyA',{altKey:true,key:'å'}),box),'agents');assert.strictEqual(keyAction(k('KeyA',{altKey:true}),pc),'agents');
        // Alt+A is a character while he writes (å on a Mac): taken only from the empty reply box or outside a text field
        assert.strictEqual(keyAction(k('KeyA',{altKey:true,key:'å'}),writing),null);assert.strictEqual(keyAction(k('KeyA',{altKey:true}),{...pc,typing:true,inBox:true,emptyBox:false}),null);
        for(const at of [field,pcField,phoneField,{...field,emptyBox:false}])assert.strictEqual(keyAction(k('KeyA',{altKey:true}),at),null,JSON.stringify(at));
        assert.strictEqual(keyAction(k('KeyA',{shiftKey:true}),idle),null);assert.strictEqual(keyAction(k('KeyA',{metaKey:true}),idle),null,'⌘A selects all');
        assert.strictEqual(keyAction(k('KeyA',{ctrlKey:true}),pc),null,'Ctrl+A selects all');
        // in the panel: on a row, or on one of its buttons
        const row={typing:false,options:0,mac:true,agents:'row'},btn={typing:false,options:0,mac:true,agents:'button'},head={typing:false,options:0,mac:true,agents:'card'};
        for(const at of [row,btn,head]){
          assert.strictEqual(keyAction(k('ArrowDown'),at),'agent-next');assert.strictEqual(keyAction(k('ArrowUp'),at),'agent-prev');
          assert.strictEqual(keyAction(k('Home'),at),'agent-first');assert.strictEqual(keyAction(k('End'),at),'agent-last');
          assert.strictEqual(keyAction(k('KeyA'),at),'agents');assert.strictEqual(keyAction(k('Escape'),at),'escape');
          assert.strictEqual(keyAction(k('ArrowDown',{shiftKey:true}),at),null);
        }
        assert.strictEqual(keyAction(k('Enter'),row),'agent-open');assert.strictEqual(keyAction(k('NumpadEnter'),row),'agent-open');
        assert.strictEqual(keyAction(k('Enter'),btn),null,'Enter on a button is its own press');assert.strictEqual(keyAction(k('Space'),row),null);
        assert.strictEqual(keyAction(k('ArrowLeft'),row),'agent-item-next');assert.strictEqual(keyAction(k('ArrowRight'),btn),'agent-item-prev');
        assert.strictEqual(keyAction(k('ArrowLeft'),{...row,inMessage:true}),'agent-item-next','a chosen message does not take the panel\'s arrows');
        // no clash: what the keys did before, they still do, in the panel too
        assert.strictEqual(keyAction(k('Digit2'),{...row,options:3}),'answer-2');assert.strictEqual(keyAction(k('Digit2',{altKey:true}),{...row,options:3}),'agent-2');
        assert.strictEqual(keyAction(k('Digit2'),{typing:false,options:3,mac:true}),'answer-2');assert.strictEqual(keyAction(k('Digit2'),{...box,options:3}),'answer-2');
        assert.strictEqual(keyAction(k('ArrowDown',{altKey:true}),row),'next-channel');assert.strictEqual(keyAction(k('ArrowUp',{altKey:true,shiftKey:true}),row),'prev-attention');
        assert.strictEqual(keyAction(k('KeyT',{shiftKey:true}),row),'tower');assert.strictEqual(keyAction(k('KeyK',{metaKey:true}),row),'switcher');
        assert.strictEqual(keyAction(k('KeyN',{altKey:true}),writing),'new-topic');
        assert.strictEqual(keyAction(k('ArrowDown'),idle),'msg-next');assert.strictEqual(keyAction(k('Home'),idle),'top');assert.strictEqual(keyAction(k('KeyJ'),idle),null);
        assert.strictEqual(keyAction(k('ArrowDown'),{...row,typing:true}),null,'a text field keeps its arrows');
        """)

    def test_page_keeps_drafts_and_renames_through_the_agreed_ops(self):
        page = self.page()
        for part in ("state.images=picturesForSend(msg.images)", 'capture="environment"', 'id="pic-file" type="file" accept="image/jpeg,image/png,image/gif,image/webp" multiple', "frame.srcdoc=canvasDoc(", "picturesOf(m,t.id)", "trayStore.put(sentKey(msg.cid)", "htmlFile(m.html.file,t.id)",
                     "{op:'reply',thread:id,cid:msg.cid,answer:msg.answer}", 'id="answer"', "{op:'snooze',thread:id,until:Math.round(until)}", "act(t.id,'unsnooze')", 'id="remind"', "<title>Suda</title>", "state.reply_to=msg.reply_to", "{op:'react',thread:id,msg:mid,emoji,on:!!on}", 'id="sheet"', "swipeOf(dx,dy)", 'touch-action:pan-y',
                     "{op:'task',thread:id,n,status}", 'id="tasks"', "{op:'draft',thread:id,text:sent}", "sideFetch('drafts.json')", "mergeDraft(d,copy)", "{op:'rename',thread:id,title}", "'pagehide'",
                     "continueList(value,from,to)", "endListItem(value,from,to)", "keepalive:!!leaving"):
            self.assertIn(part, page)

    def test_notices_have_their_own_line_and_cover_nothing(self):
        page = self.page()
        for part in ('id="toasts"', 'id="side-toasts"', 'id="over-toasts"', 'function toastHost()'):
            self.assertIn(part, page)
        # only the slot used over a dialog floats; the two in the page are part of its layout
        self.assertIsNone(re.search(r'\.toasts\{[^}]*position:fixed', page))
        self.assertRegex(page, r'#over-toasts\{position:fixed')

    def test_keyboard_is_wired_through_the_one_key_map(self):
        page = self.page()
        for part in ('keyAction(e,{typing', 'id="help"', 'id="find"', 'id="read-all"', 'id="bell"', "turnedOnYou(previous.threads,data.threads)",
                     'position:sticky', "copyLink(mid)", "paletteRank([...rows,"):
            self.assertIn(part, page)

    def test_no_shortcut_compares_a_typed_character(self):
        # `key` is the letter the layout produces; a shortcut that tested it would die on the Hebrew layout.
        self.assertIsNone(re.search(r"""\.key\s*={2,3}\s*['"][^'"]['"]""", self.page()))
        self.assertNotIn('.key.toLowerCase', self.page())

    def test_switcher_finds_a_channel_typed_in_the_wrong_layout(self):
        self.pure_js(r"""
        assert.strictEqual(swapLayout('דמשפ'),'snap');assert.strictEqual(swapLayout('snap'),'דמשפ');assert.strictEqual(swapLayout('SNAP'),'דמשפ');
        assert.strictEqual(swapLayout('akuo'),'שלום');assert.strictEqual(swapLayout('שלום'),'akuo');assert.strictEqual(swapLayout('תמלול'),',nkuk');
        assert.strictEqual(swapLayout('18:49 ✓'),'18:49 ✓');assert.strictEqual(swapLayout(''),'');
        assert.strictEqual(matches('Snap Linux \u2014 מיזוג snap-linux','דמשפ'),true);      // meant "snap", keyboard was on Hebrew
        assert.strictEqual(matches('הקלטת 18:49 \u2014 תמלול recording-1849',',nkuk'),true);   // meant "תמלול", keyboard was on English
        assert.strictEqual(matches('הקלטת 18:49 \u2014 תמלול','תמל'),true);assert.strictEqual(matches('Snap Linux','SNLX'),true);
        assert.strictEqual(matches('Snap Linux','zzz'),false);assert.strictEqual(matches('x',''),true);
        """)

    def test_the_palette_finds_a_command_by_its_hebrew_or_english_words_in_any_order(self):
        """The owner, suda m507: "⌘K is missing lots of things like settings, make it more usable". A command is found
        by the words of its label and by the words it is known by in both languages ("settings", "theme", "urgent",
        "snooze"), by a word's beginning, in any order, with a letter left out, and with the keyboard on the other
        language. A Hebrew word is found also behind its prefix letters (ה, ו, ב, ל, מ, ש)."""
        self.pure_js(r"""
        const hay=label=>label+' '+cmdWords(label);
        // English and Hebrew words a label is known by
        for(const [label,q] of [['מראה: כהה','theme'],['מראה: כהה','dark'],['מראה: כהה','ערכת נושא'],['הנושא הזה: סמן כדחוף (ראשון בקטע)','urgent'],
            ['נודניק: בעוד שעה','snooze'],['נודניק: בעוד שעה','remind'],['התראות: הפעל במכשיר הזה','notifications'],['שעות שקט: הפעל, 22:00 עד 07:00','quiet'],
            ['הנושא הזה: השתק (בלי התראות)','mute'],['קיצורי מקלדת','shortcuts'],['קיצורי מקלדת','help'],['סגירת הנושא','close'],['פתיחת הנושא מחדש','reopen'],
            ['שינוי שם הנושא','rename'],['מעבר למגדל','tower'],['מעבר למרחב «תמיכה»','space'],['רשימת הנושאים: רחבה יותר','sidebar'],
            ['קטעי קוד: גלישת שורות ארוכות','wrap'],['סדר בתוך קטע: ההודעה האחרונה למעלה','sort'],['סדר בתוך קטע: מה שזז אחרון למעלה','order'],['סדר בתוך קטע: מה שזז אחרון למעלה','moved'],['סדר בתוך קטע: מה שזז אחרון למעלה','activity'],['סדר בתוך קטע: לפי מספר המקום','slot'],['סדר בתוך קטע: לפי מספר המקום','place'],['סדר בתוך קטע: ההודעה האחרונה למעלה','latest'],['הגדרות: התראות, שעות שקט, מראה, התקנה כאפליקציה','settings']])
          assert.ok(cmdScore(hay(label),q)>0,label+' / '+q);
        // a word's beginning, any order, a letter left out, the other layout, a prefix letter
        assert.ok(cmdScore(hay('מראה: כהה'),'כהה מראה')>0);
        assert.ok(cmdScore(hay('מראה: כהה'),'dark theme')>0);
        assert.ok(cmdScore(hay('הגדרות: התראות'),'הגד')>0);
        assert.ok(cmdScore(hay('הגדרות: התראות'),'הגדרת')>0,'a letter left out');
        assert.ok(cmdScore(hay('הגדרות: התראות'),'setings')>0,'a letter left out, in English');
        assert.ok(cmdScore(hay('הגדרות: התראות'),swapLayout('settings'))>0,'typed on the Hebrew layout');
        assert.ok(cmdScore(hay('נודניק: בעוד שעה'),'snoz')>0);
        assert.ok(cmdScore('סימון כל הנושאים כנקראו','נושאים')>0,'behind the prefix letter ה');
        assert.ok(cmdScore('בהגדרות שלך','הגדרות')>=cmdScore('הגדרות','הגדרות')-1,'ב is a prefix');
        // what does not fit
        assert.strictEqual(cmdScore(hay('מראה: כהה'),'zzz'),0);
        assert.strictEqual(cmdScore(hay('מראה: כהה'),'כהה zzz'),0);
        // a whole word beats a beginning, a beginning beats a letter left out, and that beats letters strewn over the text
        assert.ok(cmdScore('theme dark','theme')>cmdScore('themes dark','them'));
        assert.ok(cmdScore('themes','them')>cmdScore('themes','thms'));
        assert.ok(cmdScore('themes','thms')>cmdScore('the long text with many letters','thms'));
        assert.ok(cmdScore('the long text with many letters','thms')>0,'the old forgiving match still finds it');
        assert.strictEqual(cmdScore('x',''),1);
        """)

    def test_the_palette_puts_the_command_he_meant_above_a_thread_that_only_holds_its_letters(self):
        """A thread whose text happens to hold the letters of "הגדרות" in order used to stand above the settings: any
        thread was ranked over any command. Now what fits best is first; a thread wins only a tie, and a place
        number typed is that thread, first."""
        self.pure_js(r"""
        const rows=[{hay:'הגדרות: התראות '+cmdWords('הגדרות: התראות'),act:true,name:'settings'},
          {hay:'הודעה גדולה בדרך רחוקה עם תשובות snap-linux',name:'strewn',slot:4},
          {hay:'הגדרות חדשות לסודה suda-settings',name:'named',slot:12},
          {hay:'מראה: כהה '+cmdWords('מראה: כהה'),act:true,name:'dark'}];
        const names=q=>paletteRank(rows,q).map(r=>r.name);
        assert.deepStrictEqual(names('הגדרות'),['named','settings','strewn']);
        assert.deepStrictEqual(names('settings')[0],'named');assert.ok(names('settings').includes('settings'));
        assert.deepStrictEqual(names('theme'),['dark']);
        assert.deepStrictEqual(names('12')[0],'named');
        assert.deepStrictEqual(names('4')[0],'strewn');
        assert.deepStrictEqual(names('qqq'),[]);
        """)

    def test_the_palette_remembers_the_last_commands_on_this_device(self):
        """With nothing typed the commands he used last come first, the newest on top, each once; a short list.
        A command that cannot run now (another thread, a closed one) is left out, never a dead row."""
        self.pure_js(r"""
        assert.deepStrictEqual(recentPush([],'theme:dark'),['theme:dark']);
        assert.deepStrictEqual(recentPush(['a','b','c'],'b'),['b','a','c']);
        let list=[];for(const id of ['a','b','c','d','e','f','g','h'])list=recentPush(list,id);
        assert.deepStrictEqual(list,['h','g','f','e','d','c']);
        assert.deepStrictEqual(recentPush(list,'x',3),['x','h','g']);
        assert.deepStrictEqual(recentPush('not a list','a'),['a']);
        assert.deepStrictEqual(recentPush([1,null,'a'],'b'),['b','a'],'what is not an id is dropped');
        const acts=[{id:'read'},{id:'theme:dark'},{id:'mute'},{id:'help'}];
        const split=recentFirst(acts,['help','gone','read'],4);
        assert.deepStrictEqual(split.recent.map(a=>a.id),['help','read']);
        assert.deepStrictEqual(split.rest.map(a=>a.id),['theme:dark','mute']);
        assert.deepStrictEqual(recentFirst(acts,['help','read','mute'],2).recent.map(a=>a.id),['help','read']);
        assert.deepStrictEqual(recentFirst(acts,'junk',4),{recent:[],rest:acts});
        """)

    def test_enter_on_an_empty_palette_still_opens_the_top_thread(self):
        """⌘K and Enter with nothing typed opened the thread that waits for him first; his hand knows it. The commands
        he used last stand above the threads, but the row Enter acts on is still the first thread (the arrows reach
        the commands). With no thread, the first row that is not a recent command; with nothing else, the first."""
        self.pure_js(r"""
        const R={act:{id:'a'},recent:true},T={t:{id:'x'}},A={act:{id:'b'}};
        assert.strictEqual(firstChoice([R,R,T,A]),2);
        assert.strictEqual(firstChoice([T,A]),0);
        assert.strictEqual(firstChoice([R,A]),1);
        assert.strictEqual(firstChoice([R,R]),0);
        assert.strictEqual(firstChoice([]),0);
        """)

    def test_the_highlighted_row_is_kept_by_what_it_is_not_by_its_place(self):
        """Hostile review of m507: a live update drew the palette again and the highlight stayed on the same NUMBER;
        a recent command that went away (the thread was closed: no "urgent" any more) moved every row up, and Enter
        opened another thread. The highlight is now the row itself, found again after each drawing; only when it
        is gone does the first choice take over."""
        self.pure_js(r"""
        const R=id=>({act:{id},recent:true}),T=id=>({t:{id}}),A=id=>({act:{id}});
        assert.strictEqual(paletteKey(T('x')),'t:x');assert.strictEqual(paletteKey(A('mute')),'a:mute');assert.strictEqual(paletteKey(null),'');
        const before=[R('urgent'),R('mute'),R('details'),T('waits'),T('other'),A('help')];
        const after=[R('details'),T('waits'),T('other'),A('help')];
        assert.strictEqual(paletteChoice(after,paletteKey(before[3])),1,'the same thread, at its new place');
        assert.strictEqual(paletteChoice(after,paletteKey(before[5])),3);
        assert.strictEqual(paletteChoice(after,paletteKey(before[0])),1,'gone: the first choice');
        assert.strictEqual(paletteChoice(after,''),1);
        assert.strictEqual(paletteChoice([],'t:x'),0);
        """)

    def test_a_few_more_words_of_the_palette(self):
        """Hostile review of m507: "new space" found nothing, and "קראתי" did not find the command that marks the
        thread read. A Hebrew prefix letter is taken off only when three letters or more are left, so a short
        word is not read as the root of a longer one."""
        self.pure_js(r"""
        const hay=l=>l+' '+cmdWords(l);
        assert.ok(cmdScore(hay('מרחב חדש…'),'new space')>0);assert.ok(cmdScore(hay('מרחב חדש…'),'create space')>0);
        assert.ok(cmdScore(hay('סימון הנושא כנקרא'),'קראתי')>0);
        assert.strictEqual(cmdScore('בית','ית'),2+1,'no prefix taken off "בית": "ית" is only inside it');
        assert.strictEqual(cmdScore('הנושאים','נושאים'),4+1);
        """)

    def test_every_thread_row_of_the_palette_says_how_long_ago_it_last_changed(self):
        """suda m642: a thread's row in the palette shows the time its sidebar row shows (its last message, else its
        last change), as short as the sidebar's; a command shows none."""
        self.pure_js(r"""
        const now=Date.UTC(2026,10,16,14,0)/1000;
        assert.strictEqual(paletteAgo({t:{messages:[{ts:now-30*60},{ts:now-12*60}],updated:now-60,created:now-9e5}},now),'12 דק׳','the last message, not the newer change');
        assert.strictEqual(paletteAgo({t:{messages:[],updated:now-3*3600,created:now-9e5}},now),'3 שע׳','no message: its last change');
        assert.strictEqual(paletteAgo({t:{messages:[],updated:0,created:now-3*86400}},now),'3 ימים','nothing else: when it was opened');
        assert.strictEqual(paletteAgo({t:{messages:[{ts:now-5}]},turn:'closed'},now),'עכשיו');
        const t={messages:[{ts:now-7200}],updated:now-60};
        assert.strictEqual(paletteAgo({t},now),agoShort(lastShown(t),now),'the very words of the sidebar row');
        assert.strictEqual(paletteAgo({act:{label:'נושא חדש',key:'N'}},now),'','a command has no time');
        assert.strictEqual(paletteAgo({act:{label:'x'},recent:true},now),'');
        assert.strictEqual(paletteAgo({t:{messages:[],updated:0,created:0}},now),'','no time known: none shown');
        """)

    def test_links_to_a_message(self):
        self.pure_js(r"""
        assert.deepStrictEqual(parseHash('#snap-linux'),{ch:'snap-linux',msg:null});
        assert.deepStrictEqual(parseHash('#snap-linux/m4'),{ch:'snap-linux',msg:'m4'});
        assert.deepStrictEqual(parseHash('snap-linux/m12'),{ch:'snap-linux',msg:'m12'});
        for(const bad of ['','#','#Bad','#a/b','#a/m','#a/m4/x','#a b','#%E0%A4%A','#../x',null,undefined])assert.deepStrictEqual(parseHash(bad),{ch:null,msg:null},String(bad));
        assert.strictEqual(linkTo('http://h:1','/threads/slack.html','snap-linux','m4'),'http://h:1/threads/slack.html#snap-linux/m4');
        assert.strictEqual(linkTo('http://h:1','/threads/slack.html','snap-linux',null),'http://h:1/threads/slack.html#snap-linux');
        assert.deepStrictEqual(parseHash(new URL(linkTo('http://h:1','/t/slack.html','a-1','m9')).hash),{ch:'a-1',msg:'m9'});
        """)

    def test_a_new_build_of_the_page_is_told_from_the_same_page_published_again(self):
        """The owner, thread suda m232: "when there's an update because you pushed something, have a button at the
        top that refreshes". The page asks the server for the file's date; only another build shows the button."""
        self.pure_js(r"""
        const a=buildOf('1:a 2:b 3:c',400),same=buildOf('1:a 2:b 3:c',400),other=buildOf('1:a 2:b 3:d',400);
        assert.strictEqual(newerBuild(a,same),false);                 // published again, the very same page
        assert.strictEqual(newerBuild(a,other),true);
        assert.strictEqual(newerBuild(a,buildOf('1:a 2:b 3:c',401)),true);        // the same marks, another size
        assert.strictEqual(newerBuild(buildOf('1:a 2:b 3:c',0),buildOf('1:a 2:b 3:c',401)),false);   // the browser did not say this page's size
        // what could not be read never cries wolf
        for(const [x,y] of [[a,null],[null,a],[a,buildOf('',0)],[buildOf('',5),a],[undefined,undefined]])assert.strictEqual(newerBuild(x,y),false);
        assert.deepStrictEqual(buildOf(null,-3),{source:'',bytes:0});
        // a mark: the length and a hash; one letter more or another letter is another mark
        assert.strictEqual(textMark(''),'0:811c9dc5');assert.strictEqual(textMark(null),'0:811c9dc5');
        assert.notStrictEqual(textMark('שלום'),textMark('שלומ'));assert.notStrictEqual(textMark('ab'),textMark('ba'));
        assert.strictEqual(textMark('x'.repeat(300000)),textMark('x'.repeat(300000)));assert.ok(/^300000:[0-9a-f]{1,8}$/.test(textMark('x'.repeat(300000))));
        // the file's date: as the server writes it, and as the browser says the page's own (local time; UTC here)
        assert.strictEqual(stampOf('Mon, 16 Nov 2026 14:22:50 GMT'),1794838970);assert.strictEqual(stampOf('11/16/2026 14:22:50'),1794838970);
        for(const odd of ['',null,undefined,'soon'])assert.strictEqual(stampOf(odd),0);
        // his place: the end, or the first message still on the screen with how far its top is above the edge
        // and the last message that reached his screen (700 tall here)
        const R=[{id:'m1',top:-900,bottom:-40},{id:'m2',top:-30,bottom:210},{id:'m3',top:210,bottom:650},{id:'m4',top:650,bottom:900},{id:'m5',top:900,bottom:1200}];
        assert.deepStrictEqual(placeOf(R,false,700),{bottom:false,at:'m2',off:-30,seen:'m4'});
        assert.deepStrictEqual(placeOf([{id:'m1',top:12,bottom:90}],false,700),{bottom:false,at:'m1',off:12,seen:'m1'});
        assert.deepStrictEqual(placeOf(R.slice(0,2),true,700),{bottom:true,at:'m2',off:0,seen:'m2'});
        assert.deepStrictEqual(placeOf([],false,700),{bottom:true,at:'',off:0,seen:''});assert.deepStrictEqual(placeOf(null,false),{bottom:true,at:'',off:0,seen:''});
        assert.deepStrictEqual(placeOf([{id:'',top:0,bottom:50},{id:'m7',top:50.4,bottom:300}],false,700),{bottom:false,at:'m7',off:50,seen:'m7'});
        assert.deepStrictEqual(placeOf(R,false),{bottom:false,at:'m2',off:-30,seen:'m5'});        // no height given: everything counts as shown
        // The owner, thread suda m240: his place in every chat follows him across devices. A place the server keeps
        // is taken when it is newer than this device's own last word, and names a message of the thread.
        const M=[{id:'m1',ts:100},{id:'m2',ts:200},{id:'m3',ts:300}];
        assert.deepStrictEqual(placeToApply({seen:'m3',at:'m2',bottom:false,ts:50},M,40),{at:'m2',bottom:false,off:0});
        assert.deepStrictEqual(placeToApply({seen:'m3',at:'m2',bottom:true,ts:50},M,0),{at:'m2',bottom:true,off:0});
        assert.strictEqual(placeToApply({seen:'m3',at:'m2',bottom:false,ts:50},M,50),null);       // this device's own word
        assert.strictEqual(placeToApply({seen:'m3',at:'m9',bottom:false,ts:50},M,0),null);        // not a message of the thread
        for(const odd of [null,undefined,'x',{at:'m2'},{at:'m2',ts:'5'},{ts:5}])assert.strictEqual(placeToApply(odd,M,0),null);
        assert.strictEqual(placeToApply({at:'m2',bottom:'yes',ts:5},M,0).bottom,false);
        // what he saw anywhere: this device's own mark, the server's seen mark and the place's, whichever is latest
        assert.strictEqual(seenFrom({messages:M},150,null),150);
        assert.strictEqual(seenFrom({messages:M,seen:{msg:'m2'}},150,null),200);
        assert.strictEqual(seenFrom({messages:M,seen:{msg:'m2'}},150,{seen:'m3'}),300);
        assert.strictEqual(seenFrom({messages:M,seen:{msg:'m1'}},250,{seen:'m2'}),250);
        assert.strictEqual(seenFrom({messages:M,seen:{msg:'m9'}},10,{seen:''}),10);assert.strictEqual(seenFrom(null,7,{seen:'m3'}),7);assert.strictEqual(seenFrom({messages:M},'x',null),0);
        """)
        page = self.page()
        for part in ('<button id="newer" class="newer" type="button" data-key="G" aria-keyshortcuts="G" hidden>', '<span data-t>New version · refresh</span><kbd aria-hidden="true">G</kbd>',
                     "const OWN_SOURCE=buildSource(document,markupOf(document.body));", "r=await fetch(location.pathname,{cache:'no-store',...(since?{headers:{'If-Modified-Since':since}}:{})})",
                     "if(stamp&&stamp===buildStamp){r.body&&r.body.cancel().catch(()=>{});return;}", "if(newerBuild(ownBuild,theirs)){strip.hidden=false;paintSecure();}",
                     "if(e.data!=='changed')return;\n    checkBuild(BUILD_SOON);wordAt=Date.now();", "setInterval(()=>checkBuild(BUILD_EVERY),BUILD_EVERY);",
                     "const back=landAt(placeKept(t.id));", "if(!chosen&&has('place')&&book.mine&&wholeOf(t).some(m=>m.id===book.mine.at))landAt(book.mine);", "book.hold=chosen;applyPlace(t.id);notePlace();", "store.set('place:'+id,JSON.stringify({...book.mine,told:book.told}));", "post({op:'place',thread:id,seen:p.seen,at:p.at,bottom:p.bottom},leaving)",
                     "sideFetch('places.json')", "if(his){ownTop=-1;scrolledAt=Date.now();notePlace();}", "const top=scroller.scrollTop,own=Math.abs(top-ownTop)<=1,his=!own&&(top<knownTop-1||!pinned);", "if(his){pinned=nearBottom();if(!pinned)followUntil=0;}", "const seenOf=id=>seenFrom(thread(id),Number(store.get('seen:'+id,'0'))||0,places[id]);", "#newer:not([hidden])[data-key],.toast button[data-key]", "sessionStorage.setItem(FRESH_KEY,"):
            self.assertIn(part, page)
        # the page's own build is taken before any of its code runs: the line right under 'use strict'
        self.assertIn("<script>\n'use strict';\n// What this build of the page is known by", page)

    def test_the_archive_of_done_tasks_is_offered_only_by_a_server_that_has_it(self):
        page = self.page()
        for part in ("filing=has('task-archive')", "filedOnWay.set(id+':'+k.n,way);", "if(failed)filedOnWay.delete(id+':'+k.n);else way.after=fetchSequence;", "for(const [key,way] of filedOnWay){", "post({op:'task-archive',thread:id,n,on},false,{})", "archiveTasks(t.id,'done',true)", "archiveTasks(t.id,task.n,!away)",
                     "if(filing&&live&&task.status==='done'){", "if(filed.length||(filing&&live&&doneNow)){", "box.hidden=!t.tasks.length;", "tr('Archive: completed')", "tr('Take out of the archive'):tr('To the archive')"):
            self.assertIn(part, page)

    def test_a_pull_request_chip_says_its_state(self):
        """The owner, thread suda m249: "the git chips themselves should show whether it's merged or not". The
        server asks GitHub (local gh) and keeps what it learns in links.json; the page only reads that file."""
        self.pure_js(r"""
        const K='https://github.com/acme/orbit/pull/1614';
        // one entry per PR, under its plain address: a link into its files or to a comment is the same PR
        assert.strictEqual(prKey(K),K);assert.strictEqual(prKey(K+'/files'),K);assert.strictEqual(prKey(K+'#issuecomment-5'),K);assert.strictEqual(prKey(K+'?w=1'),K);
        assert.strictEqual(prKey('http://github.com/a/b/pull/7/'),'https://github.com/a/b/pull/7');
        for(const odd of ['',null,'https://github.com/a/b/pull/x','https://github.com/a/b/issues/7','https://evil.example/github.com/a/b/pull/7','https://github.com/a/b/pull/77abc'])assert.strictEqual(prKey(odd),'',String(odd));
        const raw={version:1,links:{
          [K]:{kind:'pr',repo:'acme/orbit',number:1614,title:'  Fix   invoice\nrounding ',state:'merged',author:'dana',base:'main',head:'fix/x',ci:'pass',review:'approved',updated:100,checked:200},
          'https://github.com/a/b/pull/2':{kind:'pr',state:'open',ci:'fail',review:'nonsense',title:7,number:'2',updated:'x'},
          'https://github.com/a/b/pull/3':{kind:'pr',state:'draft',ci:'pending'},
          'https://github.com/a/b/pull/4':{kind:'pr',state:'closed',ci:'pass'},
          'https://github.com/a/b/pull/5':{kind:'pr',state:'',error:true,checked:50},
          'https://github.com/a/b/pull/6':{kind:'pr',state:'<img src=x>'},              // a state the page does not know
          'https://github.com/a/b/pull/7/files':{kind:'pr',state:'open'},               // not a plain address
          'https://github.com/a/b/pull/8':{kind:'commit',state:'open'},
          'https://github.com/a/b/pull/9':null,
          '__proto__':{kind:'pr',state:'open'}}};
        const known=linksOf(raw);
        assert.deepStrictEqual(Object.keys(known).sort(),[K,'https://github.com/a/b/pull/2','https://github.com/a/b/pull/3','https://github.com/a/b/pull/4','https://github.com/a/b/pull/5'].sort());
        assert.deepStrictEqual({...known[K]},{state:'merged',title:'Fix invoice rounding',repo:'acme/orbit',number:1614,author:'dana',base:'main',head:'fix/x',ci:'pass',review:'approved',updated:100,checked:200});
        assert.deepStrictEqual({...known['https://github.com/a/b/pull/2']},{state:'open',title:'',repo:'',number:0,author:'',base:'',head:'',ci:'fail',review:'',updated:0,checked:0});
        assert.strictEqual(Object.getPrototypeOf(known),null);
        for(const odd of [null,undefined,7,'x',{},{links:null},{links:[]}])assert.deepStrictEqual(Object.keys(linksOf(odd)),[]);
        // the chip: the state in a word; the checks as a dot only while the PR is still open
        assert.deepStrictEqual(prChip(known[K]),{state:'merged',label:'מוזג',ci:'',ciLabel:'',says:'מוזג · Fix invoice rounding'});
        assert.deepStrictEqual(prChip(known['https://github.com/a/b/pull/2']),{state:'open',label:'פתוח',ci:'fail',ciLabel:'הבדיקות נכשלו',says:'פתוח · הבדיקות נכשלו'});
        assert.strictEqual(prChip(known['https://github.com/a/b/pull/3']).label,'טיוטה');assert.strictEqual(prChip(known['https://github.com/a/b/pull/3']).ci,'pending');
        assert.deepStrictEqual([prChip(known['https://github.com/a/b/pull/4']).label,prChip(known['https://github.com/a/b/pull/4']).ci],['נסגר','']);
        // a PR the server could not read, or does not know: the chip stays as it is
        assert.strictEqual(prChip(known['https://github.com/a/b/pull/5']),null);assert.strictEqual(prChip(undefined),null);assert.strictEqual(prChip(null),null);
        // the PRs of a thread, each once; and which of them the server should look at when the thread is opened
        const msgs=[{text:'ראה '+K+' וגם '+K+'/files'},{text:'https://github.com/a/b/pull/2 ו-https://github.com/a/b/pull/5, ועוד https://github.com/new/one/pull/1.'},{text:null},null];
        assert.deepStrictEqual(prLinksOf(msgs),[K,'https://github.com/a/b/pull/2','https://github.com/a/b/pull/5','https://github.com/new/one/pull/1']);
        assert.deepStrictEqual(prLinksOf(null),[]);
        known['https://github.com/a/b/pull/2'].checked=1000;
        assert.deepStrictEqual(prsToAsk(msgs,known,1000+59),['https://github.com/new/one/pull/1']);              // merged: never again; an error: the server's own business
        assert.deepStrictEqual(prsToAsk(msgs,known,1000+61),['https://github.com/a/b/pull/2','https://github.com/new/one/pull/1']);
        assert.deepStrictEqual(prsToAsk(msgs,null,5),prLinksOf(msgs));
        // the card (the owner, m234): the name and the details, each line only when the server has it
        const NOW=1794838970,full=linksOf({links:{[K]:{kind:'pr',repo:'acme/orbit',number:1614,title:'Fix invoice rounding',state:'open',author:'dana',base:'main',head:'fix/x',ci:'fail',review:'changes',updated:NOW-300,checked:NOW}}})[K];
        assert.deepStrictEqual(prCard(full,NOW),{state:'open',label:'פתוח',where:'acme/orbit #1614',title:'Fix invoice rounding',author:'dana',branches:'main ← fix/x',
          ci:{kind:'fail',label:'הבדיקות נכשלו'},review:'התבקשו שינויים',updated:'עודכן לפני 5 דק׳'});
        // merged or closed: the checks and the review are history, and are not said
        const done=prCard({...full,state:'merged',updated:NOW-3*3600},NOW);
        assert.deepStrictEqual([done.label,done.ci,done.review,done.updated],['מוזג',null,'','עודכן לפני 3 שע׳']);
        const bare=prCard(linksOf({links:{[K]:{kind:'pr',state:'draft'}}})[K],NOW);
        assert.deepStrictEqual(bare,{state:'draft',label:'טיוטה',where:'',title:'',author:'',branches:'',ci:null,review:'',updated:''});
        assert.strictEqual(prCard(known['https://github.com/a/b/pull/5'],NOW),null);assert.strictEqual(prCard(null,NOW),null);
        assert.strictEqual(prCard({...full,updated:NOW-20},NOW).updated,'עודכן עכשיו');
        assert.deepStrictEqual(['עכשיו','אתמול','5 דק׳','3 ימים','05/11'].map(agoWords),['עכשיו','אתמול','לפני 5 דק׳','לפני 3 ימים','ב-05/11']);
        """)
        page = self.page()
        for part in ("sideFetch('links.json')", "post({op:'link-meta',thread:id})", "if(!t||!synced||!has('link-meta')||now()-(linksAsked.get(id)||0)<60)return;",
                     "a.dataset.state=chip.state;word.textContent=chip.label;", "render();pullLinks();", '<div id="link-card" class="link-card" role="tooltip" hidden></div>',
                     "if(!a||Date.now()-lastTouch>1500)return;", "if(a&&a.matches(':focus-visible'))showCard(a,false);", "else if(!linkCard.hidden)hideCard();", '.md a.chip-link[data-state="merged"],.link-card[data-state="merged"]{--chip:#8250df}'):
            self.assertIn(part, page)
        # the page itself never talks to GitHub
        self.assertNotIn('api.github.com', page)

    def test_the_recommended_answer_of_a_single_choice_is_marked_not_moved(self):
        """The owner, thread suda m212: options keep their natural order, and the recommended one is marked."""
        self.pure_js(r"""
        assert.strictEqual(recommendedOption({options:['א','ב','ג'],recommended:'ב'}),'ב');
        assert.strictEqual(recommendedOption({options:['א','ב','ג'],recommended:'ד'}),'');        // not one of the options
        for(const odd of [null,undefined,{},{options:['א']},{options:['א'],recommended:true},{options:null,recommended:'א'},{recommended:'א'}])assert.strictEqual(recommendedOption(odd),'');
        """)
        page = self.page()
        for part in ("b.append(option);if(option===recommendedOption(q))b.append(el('em','advised',tr('Recommended')));", "b.append(option);if(option===recommendedOption(m))b.append(el('em','advised',tr('Recommended')));"):
            self.assertIn(part, page)
        # what is sent is the option as written, never the mark
        self.assertIn("()=>send(option,q.id)", page)

    def test_the_conversation_moves_with_the_keyboard(self):
        """The owner, thread suda m269: "when the keyboard opens the scroll position moves... I don't see what was
        above". The log's window gets shorter from below; the log moves by as much, and back when it grows."""
        self.pure_js(r"""
        // the keyboard takes 300 of 583: what stood above the composer still stands above it
        assert.strictEqual(topForHeight(5000,583,283),5300);
        // and it comes back to the very same place when the keyboard goes down
        assert.strictEqual(topForHeight(topForHeight(5000,583,283),283,583),5000);
        // the composer grows by a line, a strip opens above: the same rule, by as much as the window lost
        assert.strictEqual(topForHeight(5000,583,561),5022);assert.strictEqual(topForHeight(5000,583,583),5000);
        // near the start there is nothing above to bring down
        assert.strictEqual(topForHeight(120,283,583),0);
        // a window that was not on the screen (the list on the phone, a hidden pane) has no height to compare with
        for(const [was,now] of [[0,583],[583,0],[0,0],[undefined,583],[NaN,583],[583,null],[-5,583]])assert.strictEqual(topForHeight(5000,was,now),5000);
        assert.strictEqual(topForHeight(undefined,583,283),300);
        """)
        page = self.page()
        # only two things move the log this way: the on-screen keyboard (a new height on a touch screen) and his own
        # typing; anything else that changes the window's height leaves the log where the page put it
        for part in ("function keepEdge(was){", "if(pinned){toBottom();return;}", "const top=topForHeight(scroller.scrollTop,was,tall);", "scroller.scrollTop=top;ownScroll();pinned=nearBottom();syncJump();",
                     "was=root.style.getPropertyValue('--app-h')!==next&&root.classList.contains('touch')?scroller.clientHeight:0;", "if(was)keepEdge(was);",
                     "input.addEventListener('input',()=>{const was=scroller.clientHeight;growInput();keepEdge(was);keepDraft(view.ch,input.value);});",
                     "new ResizeObserver(()=>{heardScroll();if(pinned&&view.ch)toBottom();}).observe(scroller);",
                     'content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content"'):
            self.assertIn(part, page)
        self.assertEqual(page.count('keepEdge('), 3, 'the log is moved with the window from somewhere else too')

    def test_an_open_microphone_records_whatever_the_browser_says_about_the_permission(self):
        """A diagnosis from another app: inside an app's own browser the permission always reads
        "ask", also right after the microphone was handed over, and the page stopped every recording there."""
        self.pure_js(r"""
        const held={up:false,type:'touch'},lifted={up:true,type:'touch'},clicked={up:true,type:'mouse'},mouseDown={up:false,type:'mouse'};
        // Snap's browser: "ask" before and "ask" after, and the microphone is open: it records
        assert.strictEqual(micStep('prompt','prompt',held),'held');
        assert.strictEqual(micStep('prompt','',held),'held');assert.strictEqual(micStep('','',held),'held');       // a browser with no answer at all
        // allowed from before: as always
        assert.strictEqual(micStep('granted','granted',held),'held');
        assert.strictEqual(micStep('granted','granted',lifted),'hint');             // a tap: he is told to hold
        assert.strictEqual(micStep('granted','granted',clicked),'locked');          // a click records until "send"
        assert.strictEqual(micStep('granted','granted',mouseDown),'held');
        assert.strictEqual(micStep('granted','granted',null),'locked');             // Enter or Space on the button
        // the browser asked him during this press (not allowed before, allowed now): the press answered it
        for(const press of [held,lifted,clicked,null])assert.strictEqual(micStep('prompt','granted',press),'asked');
        assert.strictEqual(micStep('','granted',held),'asked');assert.strictEqual(micStep('denied','granted',held),'asked');
        // Snap's browser after the system's own question took the finger away: the hint, and the next press records
        assert.strictEqual(micStep('prompt','prompt',lifted),'hint');
        assert.strictEqual(micStep('prompt','prompt',clicked),'locked');assert.strictEqual(micStep('prompt','prompt',null),'locked');
        """)
        page = self.page()
        for part in ("let after='';try{after=(await navigator.permissions.query({name:'microphone'})).state;}catch{}", "const step=micStep(allowed,after,press);",
                     "if(step==='asked'){stop();micPress=null;toast(", "startRec(t.id,stream,step==='locked');", "micSeen='granted';",
                     "return micSeen==='granted'&&state!=='denied'?'granted':micSeen==='denied'&&state!=='granted'?'denied':state||'prompt';"):
            self.assertIn(part, page)
        # a live microphone is never closed just because the permission does not read "granted"
        self.assertNotIn("if(allowed!=='granted'){", page)

    def test_the_page_says_whether_he_is_looking_at_suda(self):
        """The owner, thread suda m282: a notice goes to his phone through Snap at once, unless he is focused on
        Suda. Every open page tells the server whether it is looked at (op presence)."""
        self.pure_js(r"""
        // on the screen and with the keys; on a touch screen (Snap's own browser) being on the screen is enough
        assert.strictEqual(lookingAt(true,true,false),true);assert.strictEqual(lookingAt(true,false,false),false);
        assert.strictEqual(lookingAt(false,true,false),false);assert.strictEqual(lookingAt(false,true,true),false);
        assert.strictEqual(lookingAt(true,false,true),true);assert.strictEqual(lookingAt(false,false,true),false);
        // said at once when it changes; again every 20 seconds while yes; a no is said once
        assert.strictEqual(presenceDue(null,false,0),true);assert.strictEqual(presenceDue(null,true,0),true);
        assert.strictEqual(presenceDue({focused:true,at:1000},true,1000+19999),false);
        assert.strictEqual(presenceDue({focused:true,at:1000},true,1000+20000),true);
        assert.strictEqual(presenceDue({focused:true,at:1000},false,1001),true);
        assert.strictEqual(presenceDue({focused:false,at:1000},false,1000+3600000),false);
        assert.strictEqual(presenceDue({focused:false,at:1000},true,1001),true);
        assert.ok(PRESENCE_EVERY*2<45000);                    // two beats fit in the time the server believes a yes
        // the op
        assert.deepStrictEqual(presenceOp('abcdef012345',true,'suda',7400),{op:'presence',page:'abcdef012345',focused:true,thread:'suda',idle:7});
        assert.deepStrictEqual(presenceOp('abcdef012345',false,'suda',7400),{op:'presence',page:'abcdef012345',focused:false,thread:'',idle:7});
        assert.deepStrictEqual(presenceOp('p',true,null,-5),{op:'presence',page:'p',focused:true,thread:'',idle:0});
        assert.strictEqual(presenceOp('p',1,'t','x').idle,0);
        """)
        page = self.page()
        for part in ("if(!synced||!has('presence'))return;", "const lookingNow=()=>lookingAt(document.visibilityState==='visible',document.hasFocus(),touch.matches);",
                     "post(presenceOp(pageId,focused,view.ch||'',at-lastInput),leaving)", "addEventListener('pagehide',()=>sayPresence(true));", "for(const kind of ['keydown','pointerdown','pointermove','wheel','touchstart','touchmove'])addEventListener(kind,()=>{lastInput=Date.now();},{capture:true,passive:true});",
                     "addEventListener('focus',changed);addEventListener('blur',changed);addEventListener('pageshow',changed);", "render();pullLinks();pullPlaces();sayPresence(false);"):
            self.assertIn(part, page)

    def test_the_list_at_the_side_is_as_wide_as_he_made_it_and_its_sections_fold(self):
        """The owner, thread suda m295: "I want to be able to change and drag the size of the toolbar on the right,
        kept per browser. And to minimise a category, the done one for example"."""
        self.pure_js(r"""
        // the width: what he asked for, never narrower than 200, never more than half the window or 560
        assert.strictEqual(sideWidth(420,1280),420);assert.strictEqual(sideWidth(120,1280),200);assert.strictEqual(sideWidth(900,1280),560);
        assert.strictEqual(sideWidth(500,800),400);assert.strictEqual(sideWidth(500,300),200);     // a narrow window: half of it, but readable
        assert.strictEqual(sideWidth('436',1280),436);assert.strictEqual(sideWidth(436.4,1280),436);
        for(const none of [0,-5,null,undefined,'','wide',NaN])assert.strictEqual(sideWidth(none,1280),0);   // no choice: the page's own width
        assert.strictEqual(sideWidth(420,0),420);assert.strictEqual(sideWidth(420,undefined),420);
        // the keys on its edge: in this right-to-left page the edge is the list's left side, so left is wider
        assert.strictEqual(sideKey('ArrowLeft',300,1280,true,false),316);assert.strictEqual(sideKey('ArrowRight',300,1280,true,false),284);
        assert.strictEqual(sideKey('ArrowLeft',300,1280,true,true),364);assert.strictEqual(sideKey('ArrowRight',300,1280,true,true),236);
        assert.strictEqual(sideKey('ArrowRight',300,1280,false,false),316);assert.strictEqual(sideKey('ArrowLeft',300,1280,false,false),284);
        assert.strictEqual(sideKey('ArrowRight',205,1280,true,false),200);assert.strictEqual(sideKey('ArrowLeft',556,1280,true,false),560);
        assert.strictEqual(sideKey('Home',300,1280,true,false),200);assert.strictEqual(sideKey('End',300,1280,true,false),560);assert.strictEqual(sideKey('End',300,800,true,false),400);
        assert.strictEqual(sideKey('Enter',420,1280,true,false),0);
        for(const other of ['ArrowUp','ArrowDown','a',' ','Tab','Escape'])assert.strictEqual(sideKey(other,300,1280,true,false),null);
        // the folds: the sleeping and the archived start folded, the rest open; what he chose is read back
        assert.deepStrictEqual(foldsOf(''),{'on-owner':false,working:false,done:false,snoozed:true,merged:true,closed:true});
        assert.deepStrictEqual(foldsOf('{"done":true,"closed":false}'),{'on-owner':false,working:false,done:true,snoozed:true,merged:true,closed:false});
        for(const odd of [null,undefined,'x','[]','7','{"done":"yes","other":true}','{"__proto__":{"done":true}}'])assert.deepStrictEqual(foldsOf(odd),foldsOf(''),String(odd));
        // a folded section still shows the topic that is open now, and nothing else
        assert.deepStrictEqual(foldedRows(['a','b','c'],false,'b'),['a','b','c']);
        assert.deepStrictEqual(foldedRows(['a','b','c'],true,'b'),['b']);assert.deepStrictEqual(foldedRows(['a','b','c'],true,'z'),[]);assert.deepStrictEqual(foldedRows(['a'],true,null),[]);
        // stepping through the list goes over what is on the screen; the step to "what needs me" reaches folded open topics too
        const R=id=>({t:{id}}),sb={top:[R('tower')],sections:[{key:'on-owner',rows:[R('y1'),R('y2')]},{key:'working',rows:[R('w1'),R('w2')]},{key:'done',rows:[R('d1')]}],snoozed:[R('s1')],closed:[{id:'c1'},{id:'c2'}],merged:[{id:'m1'}]};
        assert.deepStrictEqual(sideOrder(sb,foldsOf(''),'w1',false),['tower','y1','y2','w1','w2','d1']);
        assert.deepStrictEqual(sideOrder(sb,foldsOf('{"working":true,"done":true}'),'w2',false),['tower','y1','y2','w2']);
        assert.deepStrictEqual(sideOrder(sb,foldsOf('{"on-owner":true,"working":true}'),'d1',true),['tower','y1','y2','w1','w2','d1']);
        // merged threads (task 113) have their own section, before the archive, folded at first
        assert.deepStrictEqual(sideOrder(sb,foldsOf('{"merged":false,"closed":false}'),'w1',false),['tower','y1','y2','w1','w2','d1','m1','c1','c2']);
        assert.deepStrictEqual(sideOrder(sb,foldsOf('{"snoozed":false,"closed":false}'),null,false),['tower','y1','y2','w1','w2','d1','s1','c1','c2']);
        assert.deepStrictEqual(sideOrder(sb,foldsOf(''),'c2',false),['tower','y1','y2','w1','w2','d1','c2']);
        """)
        page = self.page()
        for part in ('.side{flex:0 0 clamp(200px,var(--side-w,300px),min(560px,50vw));', '<div id="side-size" class="side-size" role="separator" aria-orientation="vertical" tabindex="0"',
                     '<script id="side-first">try{var wide=parseInt(localStorage.getItem("suda-side-w"),10);if(wide>0)document.documentElement.style.setProperty("--side-w",wide+"px");}catch(e){}</script>',
                     "localStorage.setItem(SIDE_KEY,String(wide));", "sideEdge.addEventListener('dblclick',()=>setSide(0,true));", "store.set('side-folds',JSON.stringify(folds));",
                     "head.setAttribute('aria-expanded',String(!folded));", "let ids=sideOrder(sidebar(Object.values(data.threads)),folds,view.ch,!!attention);", "  .side-size{display:none}"):
            self.assertIn(part, page)

    def test_line_wrapping_is_one_choice_for_every_block(self):
        """The owner, thread suda m311: "if I change something about line wrapping, make it the default for the next
        things that render too, so that it is not always only on the last one"."""
        self.pure_js(r"""
        // '1' and '0' are his choices; anything else is the place's own start (code: unwrapped; a long text: wrapped)
        assert.strictEqual(wrapChoice('1',false),true);assert.strictEqual(wrapChoice('0',true),false);
        assert.strictEqual(wrapChoice('1',true),true);assert.strictEqual(wrapChoice('0',false),false);
        for(const none of [null,undefined,'','true','yes',1,0,'01'])assert.deepStrictEqual([wrapChoice(none,false),wrapChoice(none,true)],[false,true],String(none));
        """)
        page = self.page()
        for part in ("const WRAP_CODE='suda-wrap-code',WRAP_TEXT='suda-wrap-text';", "let wrapCode=keptChoice(WRAP_CODE,false),wrapText=keptChoice(WRAP_TEXT,true);",
                     "const wrap=button(null,'wrap-toggle',()=>setWrapCode(!wrapCode,wrap));", "wrap.setAttribute('aria-pressed',String(wrapCode));",
                     "document.documentElement.classList.toggle('wrap-code',wrapCode);", ".wrap-code .md .code pre code{white-space:pre-wrap;overflow-wrap:anywhere}",
                     "set('mono',mono);set('nowrap',!wrapText);", "const noWrap=button(tr('No line wrap'),'chipbtn nowrap-toggle',()=>setWrapText(!wrapText));",
                     "else if(e.key===WRAP_CODE){wrapCode=wrapChoice(e.newValue,false);paintWrapCode();}", "()=>setWrapCode(!wrapCode),'wrap-code');", "()=>setWrapText(!wrapText),'wrap-text');"):
            self.assertIn(part, page)
        # no block keeps a wrapping of its own any more
        self.assertNotIn("pre.classList.toggle('wrap')", page)
        self.assertNotIn('pre.wrap code', page)

    def test_the_state_in_two_cuts_fills_a_threads_stamps_with_the_whole_messages_it_holds(self):
        """The owner approved the speed plan (thread suda m317): the page opens from a small summary (of every message
        only a stamp; the last few of an open thread whole) and reads one thread's whole conversation when it
        needs it. A message's mark `v` says whether the copy the page holds still stands."""
        self.pure_js(r"""
        const W=(id,v,extra)=>({id,from:'fork',ts:Number(id.slice(1)),v,text:'טקסט '+id,...extra});
        const stamps=[['m1','fork',1,'a1'],['m2','owner',2,'a2'],['m3','fork',3,'a3'],['m4','fork',4,'a4']];
        // only the tail is here: the older ones are light (id, sender, time and nothing else), and counted as missing
        let cut=threadMessages(stamps,null,[W('m3','a3'),W('m4','a4')]);
        assert.strictEqual(cut.missing,2);
        assert.deepStrictEqual(cut.messages.map(m=>[m.id,!!m.light,m.text]),[['m1',true,''],['m2',true,''],['m3',false,'טקסט m3'],['m4',false,'טקסט m4']]);
        assert.deepStrictEqual(cut.messages[1],{id:'m2',from:'owner',ts:2,v:'a2',text:'',light:true});
        // with what the page held before, all of it is whole, in the order of the stamps whatever the lists' order
        cut=threadMessages(stamps,[W('m2','a2'),W('m1','a1')],[W('m4','a4'),W('m3','a3')]);
        assert.strictEqual(cut.missing,0);assert.deepStrictEqual(cut.messages.map(m=>m.id),['m1','m2','m3','m4']);
        // a held message whose mark is no longer the stamp's has changed on the server: it is not used
        cut=threadMessages([['m1','fork',1,'NEW'],...stamps.slice(1)],[W('m1','a1'),W('m2','a2')],[W('m3','a3'),W('m4','a4')]);
        assert.strictEqual(cut.missing,1);assert.strictEqual(cut.messages[0].light,true);
        // the newer copy of the same message (another mark) is the one taken when the stamp names it
        cut=threadMessages([['m1','fork',1,'NEW']],[W('m1','a1')],[W('m1','NEW',{text:'אחרי עריכה'})]);
        assert.strictEqual(cut.messages[0].text,'אחרי עריכה');
        // a light message is never taken for a whole one; a message with no mark is not known to stand
        cut=threadMessages([['m1','fork',1,'a1']],[{id:'m1',from:'fork',ts:1,v:'a1',text:'',light:true}],[{id:'m1',from:'fork',ts:1,text:'x'}]);
        assert.strictEqual(cut.missing,1);
        // a message that is not among the stamps is not in the thread (it was removed, or the summary is older than it)
        assert.deepStrictEqual(threadMessages(stamps.slice(0,2),[W('m1','a1'),W('m2','a2'),W('m9','a9')]).messages.map(m=>m.id),['m1','m2']);
        // stamps that are not stamps are skipped; no stamps, no messages
        assert.deepStrictEqual(threadMessages([null,'x',['m1'],['m1','fork','soon','a'],[7,'fork',1,'a'],['m2','fork',2]],[]).messages.map(m=>[m.id,m.v]),[['m2','']]);
        for(const none of [null,undefined,'x',{}])assert.deepStrictEqual(threadMessages(none,[W('m1','a1')]),{messages:[],missing:0});
        // normalize: a summary's thread is its stamps filled from what the page holds; `partial` says the rest is to be read
        const raw={version:2,lite:1,threads:{a:{id:'a',title:'א',status:'open',stamps,rev:'r1',messages:[W('m3','a3'),W('m4','a4')]},
          b:{id:'b',title:'ב',status:'open',stamps:[['m1','tower',5,'b1']],rev:'r2',messages:[{id:'m1',from:'tower',ts:5,v:'b1',text:'שלם'}]},
          c:{id:'c',title:'ג',status:'closed',stamps:[],messages:[]}}};
        let data=normalize(raw);
        assert.deepStrictEqual([data.threads.a.partial,data.threads.b.partial,data.threads.c.partial],[true,false,false]);
        assert.strictEqual(data.threads.a.messages.length,4);assert.strictEqual(data.threads.a.rev,'r1');
        data=normalize(raw,new Map([['a',[W('m1','a1'),W('m2','a2')]]]));
        assert.strictEqual(data.threads.a.partial,false);assert.deepStrictEqual(data.threads.a.messages.map(m=>!!m.light),[false,false,false,false]);
        // what counts messages by sender and time is right before the conversation is read: the light ones are counted
        data=normalize(raw);
        assert.strictEqual(unreadCount(data.threads.a,0),3);assert.strictEqual(unreadCount(data.threads.a,3),1);assert.strictEqual(lastAgentTs(data.threads.a),4);
        assert.strictEqual(waitingCount(data.threads.a),2);
        // a state from a server without the summary is taken as it always was: whole messages, nothing partial
        const old=normalize({version:2,threads:{a:{id:'a',title:'א',status:'open',messages:[{id:'m1',from:'fork',ts:1,text:'x'},{id:'m2',from:'fork',ts:'soon'},null]}}});
        assert.deepStrictEqual([old.threads.a.partial,old.threads.a.messages.length,old.threads.a.messages[0].light],[false,1,undefined]);
        assert.deepStrictEqual(wholeMessages([{id:'m1',from:'fork',ts:1},{from:'fork'},7,null,{id:'m2',from:'x',ts:2,text:5}]).map(m=>[m.id,m.text]),[['m1',''],['m2','']]);
        assert.deepStrictEqual(wholeMessages(null),[]);
        // what a message is known by: the server's by its mark (cheap), the page's own by all of it, without a picture's bytes
        assert.strictEqual(messageSig(W('m3','a3')),'m3:a3');
        const own={cid:'c1',from:'owner',text:'שלי',ts:9,delivery:'sending',images:[{data:'AAAA'}]},short=(key,value)=>key==='data'?value.length:value;
        assert.strictEqual(messageSig(own,short),JSON.stringify(own,short));assert.ok(!messageSig(own,short).includes('AAAA'));
        assert.notStrictEqual(messageSig({...own,delivery:'sent'},short),messageSig(own,short));
        // news: only what stands after the last message the page already had; the rest of a conversation that arrives later is not news
        const keyOf=m=>m.cid||m.id,all=['m1','m2','m3','m4','m5'].map(id=>({id}));
        assert.deepStrictEqual(newsOf(all,new Set(['m3','m4']),keyOf).map(m=>m.id),['m5']);
        assert.deepStrictEqual(newsOf(all,new Set(['m4','m5']),keyOf),[]);                       // m1..m3 arrived: older, not news
        assert.deepStrictEqual(newsOf(all,new Set(['m1','m2','m3','m4','m5']),keyOf),[]);
        assert.deepStrictEqual(newsOf(all,new Set(),keyOf).map(m=>m.id),['m1','m2','m3','m4','m5']);
        assert.deepStrictEqual(newsOf([...all,{cid:'c9'}],new Set(['m5']),keyOf).map(keyOf),['c9']);
        """)
        page = self.page()
        for part in ("const r=await fetch('summary.json?t='+Date.now(),{cache:'no-store',signal:readSignal()});", "else if(r.status!==404)throw Error();", "const r=await fetch('state.json?t='+Date.now(),{cache:'no-store',signal:readSignal()});if(!r.ok)throw Error();",
                     "const r=await fetch('full/'+encodeURIComponent(id)+'.json?t='+Date.now(),{cache:'no-store'});", "data=normalize(raw,held);", "if(raw.lite)keptStore.put('summary',got.keep||raw);", "if(!reading){reading=readState().finally(()=>{reading=null;setTimeout(keysToBox,0);});return reading;}",
                     "return readNext||(readNext=reading.then(()=>{readNext=null;return refresh();}));", "await keptRead(id);",
                     "const all=[...wholeOf(t),...localOf(t)],slot=slots().get(t.id);", "const added=first?all:newsOf(all,before,keyOf);", "paintKept();\nrefresh().then(restoreTray,restoreTray);\nworker();",
                     "indexedDB.open('suda-kept',1)", "if(painted&&view.ch)relandFor=view.ch;"):
            self.assertIn(part, page)
        # before the server has answered, the page says nothing to it on its own account
        for part in ("if(!t||document.hidden||!has('seen')||!synced)return;", "if(!synced||!v2()||now()-lastSweep<=60)return;", "if(!synced||!has('place')||!t||t.status!=='open'||logFor!==id||(!leaving&&document.hidden))return;",
                     "const reading=()=>synced&&view.ch===id&&v2()&&plainReport(thread(id))"):
            self.assertIn(part, page)

    def test_a_long_conversation_is_drawn_from_its_end_first_unless_he_lands_further_up(self):
        """The tower, thread suda m322: opening a thread, going back and switching must be as fast and smooth as
        possible, with minimal jumps. A long conversation is drawn in two steps; never when that would show him
        one place and then take him to another."""
        self.pure_js(r"""
        // short conversations are drawn at once
        assert.strictEqual(drawFrom(0,[]),0);assert.strictEqual(drawFrom(90,[]),0);
        // a long one: its last fifty first
        assert.strictEqual(drawFrom(91,[]),41);assert.strictEqual(drawFrom(320,[]),270);assert.strictEqual(drawFrom(320,null),270);
        // he lands near the end (the first unread message, the message he stood at): still its end first
        assert.strictEqual(drawFrom(320,[300]),270);assert.strictEqual(drawFrom(320,[278,319]),270);
        // he lands further up, or right at the edge of what would be drawn: all of it at once, so nothing moves under him
        assert.strictEqual(drawFrom(320,[100]),0);assert.strictEqual(drawFrom(320,[277]),0);assert.strictEqual(drawFrom(320,[300,12]),0);assert.strictEqual(drawFrom(320,[0]),0);
        // what is not a place does not count
        assert.strictEqual(drawFrom(320,[-1,null,'x',2.5]),270);
        """)
        page = self.page()
        for part in ("const kept=rowsOf(t.id);rowCache=kept.rows;keptTop=rowCache.size?kept.top:null;", "const whole=!logSignature||find.open;", "while(rowCaches.size>ROWS_KEPT)rowCaches.delete(rowCaches.keys().next().value);",
                     "if(previous&&logFor===previous&&rowCaches.has(previous)){const kept=rowCaches.get(previous);kept.top=scroller.scrollTop;kept.end=nearBottom();}", "else if(!chosen&&first&&keptTop!==null&&!short){scroller.scrollTop=keptTop;ownScroll();syncJump();}", "logFrom=!find.open&&!fresh&&!away&&(grown||logHolds!==t.id)?drawFrom(all.length,targets):0;",
                     "const grown=!first&&logShort!==t.id&&all.length-[...rowCache.keys()].filter(key=>key[0]!=='\\u0000').length>SHORT_OVER;", "logShort=logFrom>0?t.id:null;", "logFrom=Math.max(0,from-SHORT_STEP);",
                     "function showMessage(mid){if(!rowOf('mid',mid))drawRest();return flashRow(rowOf('mid',mid));}",
                     "if(logShort!==id||logFrom!==from)return;", "if(logFrom>0&&!find.open){const now_=thread(id);if(now_)renderLog(now_);return;}", "logShort=null;logFrom=0;relandFor=id;render();",
                     "if(!ahead||!synced||document.hidden||!online||aheadTried.size>=AHEAD_MAX||(navigator.connection&&navigator.connection.saveData))return;", "setTimeout(readAhead,2500);"):
            self.assertIn(part, page)

    def test_finding_text_in_a_channel(self):
        self.pure_js(r"""
        assert.deepStrictEqual(findAll('Soniox ו-soniox וגם SONIOX','soniox'),[0,9,20]);
        assert.deepStrictEqual(findAll('אאא','אא'),[0]);                 // hits do not overlap
        assert.deepStrictEqual(findAll('מיזוג ל-main','מיזוג'),[0]);assert.deepStrictEqual(findAll('abc',''),[]);
        assert.deepStrictEqual(findAll('abc','x'),[]);assert.deepStrictEqual(findAll('',' '),[]);
        """)

    def test_a_thread_that_turns_on_him_is_announced_once(self):
        self.pure_js(r"""
        const T=(id,state,extra)=>Object.assign({id,title:id,status:'open',state,messages:[]},extra);
        const before={a:T('a','working'),b:T('b','on-owner'),c:T('c','done'),d:T('d','working')};
        const after={a:T('a','on-owner'),b:T('b','on-owner'),c:T('c','done'),d:T('d','on-owner',{status:'closed'}),e:T('e','on-owner')};
        // a moved to him; b already was; d is closed; e is new and on him
        assert.deepStrictEqual(turnedOnYou(before,after),['a','e']);
        assert.deepStrictEqual(turnedOnYou(after,after),[]);assert.deepStrictEqual(turnedOnYou({},{}),[]);
        // a v1 file: the turn is read from the conversation
        const m=(from,status)=>({from,status,ts:1,text:'x'});
        assert.deepStrictEqual(turnedOnYou({x:{id:'x',status:'open',messages:[m('owner','acked')]}},{x:{id:'x',status:'open',messages:[m('owner','acked'),m('fork')]}}),['x']);
        """)

    # ── the conversation ───────────────────────────────────────────────────

    def test_timeline_groups_messages(self):
        self.pure_js(r"""
        const DAY=86400, base=Date.UTC(2026,10,15,10,0,0)/1000, now=base+3600;
        const m=(id,from,ts,extra)=>Object.assign({id,from,ts,text:id},extra);
        const show=items=>items.map(i=>i.kind==='day'?'day:'+i.label:i.kind==='new'?'new':(i.lead?'+':'')+i.m.id);
        let list=[m('a','fork',base-DAY),m('b','fork',base-DAY+60),m('c','owner',base),m('d','owner',base+30),m('e','owner',base+30+301),m('f','tower',base+400),m('g','tower',base+410)];
        // same sender within five minutes joins the group above it; a new day, sender or a long gap starts one
        assert.deepStrictEqual(show(timeline(list,null,now)),['day:אתמול','+a','b','day:היום','+c','d','+e','+f','g']);
        // the "new" line stands before the first agent message he has not seen, and starts a group
        assert.deepStrictEqual(show(timeline(list,base+400,now)),['day:אתמול','+a','b','day:היום','+c','d','+e','+f','new','+g']);
        assert.deepStrictEqual(show(timeline(list,base-DAY+60,now)),['day:אתמול','+a','b','day:היום','+c','d','+e','new','+f','g']);
        // his own messages are never "new"; nothing unseen means no line
        assert.deepStrictEqual(show(timeline(list,base+410,now)).includes('new'),false);
        assert.deepStrictEqual(show(timeline([m('a','owner',base)],0,now)),['day:היום','+a']);
        // a question always starts its own group, and so does what follows it
        list=[m('a','fork',base),m('q','fork',base+5,{q:true}),m('r','fork',base+9)];
        assert.deepStrictEqual(show(timeline(list,null,now)),['day:היום','+a','+q','+r']);
        assert.deepStrictEqual(timeline([],0,now),[]);
        assert.strictEqual(dayLabel(base,now),'היום');assert.strictEqual(dayLabel(base-DAY,now),'אתמול');
        assert.ok(/15/.test(dayLabel(base,now+9*DAY)),dayLabel(base,now+9*DAY));
        assert.strictEqual(clock(base+5*60),'10:05');
        assert.strictEqual(moment(base+5*60,now),'היום 10:05');assert.strictEqual(moment(base-DAY,now),'אתמול 10:00');assert.strictEqual(moment(base,now+9*DAY),'15/11 10:00');
        assert.strictEqual(stamp(base+5*60,now),'10:05');assert.strictEqual(stamp(base-DAY,now),'אתמול');assert.strictEqual(stamp(base,now+9*DAY),'15/11');
        """)

    def test_helpers(self):
        self.pure_js(r"""
        for(const ok of ['https://x.example/a?b=1','http://192.0.2.10:8767/t/board.html','/acme/board.html'])assert.strictEqual(linkKind(ok),'url',ok);
        for(const bad of ['javascript:alert(1)','JaVaScript:alert(1)','data:text/html,x','//evil.example/x','/\\evil.example/x','/a\\b',' https://x','~/notes/a.md','','/a b',null,undefined,7])assert.strictEqual(linkKind(bad),'path',String(bad));
        assert.strictEqual(span(20),'פחות מדקה');assert.strictEqual(span(34*60),'34 דק׳');assert.strictEqual(span(90*60),'1.5 שע׳');
        assert.strictEqual(span(3*3600),'3 שע׳');assert.strictEqual(span(30*3600),'יום');assert.strictEqual(span(50*3600),'יומיים');assert.strictEqual(span(72*3600),'3 ימים');
        assert.strictEqual(fuzzy('Snap Linux \u2014 מיזוג snap-linux','snlx'),true);assert.strictEqual(fuzzy('Snap Linux','LINUX'),true);
        assert.strictEqual(fuzzy('Snap Linux','xl'),false);assert.strictEqual(fuzzy('הקלטת 18:49','הקל 18'),true);assert.strictEqual(fuzzy('x',''),true);
        assert.strictEqual(isClosing({status:'open',soon_at:50},60),true);assert.strictEqual(isClosing({status:'open',soon_at:null},60),false);
        assert.strictEqual(isClosing({status:'closed',soon_at:50},60),false);assert.strictEqual(isClosing({status:'open'},60),false);
        // Enter at a computer: it sends, Shift+Enter breaks the line
        const key=(extra)=>Object.assign({key:'Enter',code:'Enter',keyCode:13},extra),desk={touch:false,keyboardUp:false};
        assert.strictEqual(enterSends(key(),desk),true);assert.strictEqual(enterSends(key({shiftKey:true}),desk),false);
        assert.strictEqual(enterSends(key({metaKey:true,shiftKey:true}),desk),true);assert.strictEqual(enterSends(key({altKey:true}),desk),false);
        assert.strictEqual(enterSends(key({isComposing:true}),desk),false);assert.strictEqual(enterSends(key({keyCode:229}),desk),false);
        assert.strictEqual(enterSends({key:'a'},desk),false);assert.strictEqual(enterSends(key({code:''}),desk),true);assert.strictEqual(enterSends(key(),undefined),true);
        // on a touch screen it depends on where this very key came from
        const phone={touch:true,keyboardUp:false},typing={touch:true,keyboardUp:true};
        assert.strictEqual(enterSends(key(),phone),true,'a physical keyboard: the event names its key');
        assert.strictEqual(enterSends(key({code:'NumpadEnter'}),phone),true);assert.strictEqual(enterSends(key({shiftKey:true}),phone),false);
        assert.strictEqual(enterSends(key({code:''}),typing),false,'the on-screen keyboard names no key: a new line');
        assert.strictEqual(enterSends(key({code:''}),phone),false);assert.strictEqual(enterSends({key:'Enter',keyCode:13},typing),false);
        assert.strictEqual(enterSends(key(),typing),false,'a named key while the on-screen keyboard shows is not trusted');
        assert.strictEqual(enterSends(key({ctrlKey:true,code:''}),typing),true);assert.strictEqual(enterSends(key({keyCode:229,code:''}),typing),false);
        assert.deepStrictEqual([key(),key({code:''}),key({shiftKey:true}),key({ctrlKey:true}),{key:'a'}].map(e=>enterKind(e,phone)),['physical','screen','line','chord','none']);
        assert.strictEqual(enterKind(key(),typing),'unsure');assert.strictEqual(enterKind(key(),desk),'computer');
        // the on-screen keyboard is up when the page is much shorter than it has been at this width
        assert.strictEqual(keyboardUp(780,470),true);assert.strictEqual(keyboardUp(780,724),false,'the address bar coming and going');
        assert.strictEqual(keyboardUp(780,780),false);assert.strictEqual(keyboardUp(0,470),false);assert.strictEqual(keyboardUp(NaN,470),false);
        assert.strictEqual(whoName('tower'),'מגדל');assert.strictEqual(whoName('fork'),'סוכן');assert.strictEqual(whoName('owner'),'אני');
        assert.strictEqual(whoName('builder'),'builder');assert.strictEqual(whoName(''),'');
        for(const odd of ['constructor','toString','__proto__','hasOwnProperty'])assert.strictEqual(whoName(odd),odd);   // a name is data, never a lookup into Object
        // the board this copy serves is the folder it sits in
        assert.strictEqual(slugOf('/threads/slack.html'),'threads');assert.strictEqual(slugOf('/threads-demo/slack.html'),'threads-demo');
        assert.strictEqual(slugOf('/slack.html'),'threads');assert.strictEqual(slugOf('/threads/'),'threads');
        // the whole folder path, as suda.html reads it: a copy under another folder is another board, never the live one
        assert.strictEqual(slugOf('/staging/threads/slack.html'),'staging/threads');assert.strictEqual(slugOf('//threads//slack.html'),'threads');
        """)


class CatchUpTests(unittest.TestCase):
    """The board's changes by their numbers (sse153). The page applies the entries of changes.json from its own
    number on, all of them to a copy and in order, or none: on a gap, a reorder, an entry it cannot read, a number
    older than the ones held, or a target beyond them, it reads the whole summary (catchUp gives null)."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    BASE = r"""
    const row=(id,extra)=>({id,title:'t '+id,status:'open',messages:[],stamps:[],rev:'r0',...extra});
    const base=()=>({version:2,lite:1,policy:{idle_hours:4},seq:10,threads:{a:row('a'),b:row('b',{stamps:[['m1','fork',1,'x'],['m2','fork',2,'y']]})}});
    const e11={from:10,seq:11,threads:{c:row('c')},top:{}};
    const e12={from:11,seq:12,threads:{},top:{policy:{idle_hours:5}},edit:{b:{set:{rev:'r1',title:'new b'},list:{stamps:{n:3,from:[[0,1]],at:[[1,['m3','fork',3,'z']],[2,['m4','fork',4,'w']]]}}}}};
    const e13={from:12,seq:13,threads:{a:null},top:{},drop:['lite']};
    const changes=(...entries)=>({seq:entries.length?entries.at(-1).seq:10,entries});
    """

    def test_entries_in_order_are_all_applied_to_a_copy(self):
        self.pure_js(self.BASE + r"""
        const b=base(),before=JSON.stringify(b);
        const got=catchUp(b,changes(e11,e12,e13));
        assert.strictEqual(JSON.stringify(b),before,'the summary the page holds is never touched');
        assert.strictEqual(got.seq,13);
        assert.deepStrictEqual(Object.keys(got.threads),['b','c']);         // a removed, c added
        assert.deepStrictEqual(got.threads.b.stamps,[['m2','fork',2,'y'],['m3','fork',3,'z'],['m4','fork',4,'w']]);
        assert.strictEqual(got.threads.b.title,'new b');assert.strictEqual(got.threads.b.rev,'r1');
        assert.deepStrictEqual(got.policy,{idle_hours:5});                  // a top-level change
        assert.strictEqual('lite' in got,false);                           // a top-level key gone
        // entries the page already has (<= its number) are skipped: a duplicate is no gap
        assert.strictEqual(catchUp({...b,seq:11,threads:{...b.threads,c:row('c')}},changes(e11,e12)).seq,12);
        // the page's own number: nothing to do, the same summary
        assert.strictEqual(catchUp(b,changes()),b);
        assert.strictEqual(catchUp(b,{seq:10,entries:[]}),b);
        // up to a target inside what is held
        assert.strictEqual(catchUp(b,changes(e11,e12,e13),12).seq,12);
        """)

    def test_anything_doubtful_reads_the_whole_summary(self):
        self.pure_js(self.BASE + r"""
        const b=base();
        // a gap: 11 is missing (changes.json was cut, or a page far behind)
        assert.strictEqual(catchUp(b,changes(e12,e13)),null);
        // a reorder
        assert.strictEqual(catchUp(b,{seq:13,entries:[e11,e13,e12]}),null);
        // the same number twice inside what is still to apply
        assert.strictEqual(catchUp(b,{seq:12,entries:[e11,e11,e12]}),null);
        // a target beyond what the file holds (the server said 14; the file stops at 13)
        assert.strictEqual(catchUp(b,changes(e11,e12,e13),14),null);
        // a number older than the page's (the board was set back): a whole read decides
        assert.strictEqual(catchUp(b,{seq:9,entries:[]}),null);
        assert.strictEqual(catchUp(b,changes(e11),9),null);
        // a file that says less than its entries, or entries it cannot read
        assert.strictEqual(catchUp(b,{seq:12,entries:[e11]}),null);
        for(const bad of [{from:10,seq:11,threads:{c:7},top:{}},{from:10,seq:11,threads:{'Bad Id':row('x')},top:{}},{from:10,seq:11,threads:{},top:[]},
                          {from:10,seq:11,threads:{},top:{seq:99}},{from:10,seq:11,threads:{},top:{threads:{}}},{from:10,seq:11,threads:{},top:{},drop:[3]},
                          {from:10,seq:11,threads:{},top:{},edit:{zz:{set:{}}}},{from:10,seq:11,threads:{},top:{},edit:{b:{list:{stamps:{n:-1}}}}},
                          {from:10,seq:11,threads:{},top:{},edit:{b:{list:{stamps:{n:2,from:[[0,5]]}}}}},{from:10,seq:11,threads:{},top:{},edit:{b:{list:{stamps:{n:2,at:[[2,1]]}}}}},
                          {from:10,seq:11,threads:{},top:{},edit:{b:{list:{title:{n:1}}}}},{from:10,seq:'11',threads:{},top:{}},null,
                          {seq:11,threads:{},top:{}},{from:'10',seq:11,threads:{},top:{}},{from:11,seq:11,threads:{},top:{}},
                          JSON.parse('{"from":10,"seq":11,"threads":{},"top":{"__proto__":{"x":1}}}'),JSON.parse('{"from":10,"seq":11,"threads":{},"top":{},"edit":{"b":{"set":{"__proto__":{"x":1}}}}}')])
          assert.strictEqual(catchUp(b,{seq:11,entries:[bad]}),null,JSON.stringify(bad));
        // what is not a summary with a number, or not a changes file
        for(const [x,y] of [[null,changes(e11)],[{threads:{}},changes(e11)],[{seq:1.5,threads:{}},changes(e11)],[b,null],[b,{seq:11}],[b,{entries:[]}]])
          assert.strictEqual(catchUp(x,y),null);
        // nothing leaks into the page's own copy on a failure half way
        const before=JSON.stringify(b);catchUp(b,changes(e11,{from:11,seq:12,threads:{q:5},top:{}}));assert.strictEqual(JSON.stringify(b),before);
        """)

    def test_numbers_need_not_follow_each_other_each_entry_names_the_one_before(self):
        """A number is never below the clock (a board put back from a backup never gives a number again), so numbers
        jump. Each entry says the number it starts from (`from`): the chain, not the arithmetic, is what is checked."""
        self.pure_js(self.BASE + r"""
        const b=base();
        const x={from:10,seq:1700000000000,threads:{c:row('c')},top:{}},y={from:1700000000000,seq:1700000000450,threads:{a:null},top:{}};
        const got=catchUp(b,{seq:y.seq,entries:[x,y]});
        assert.strictEqual(got.seq,1700000000450);assert.deepStrictEqual(Object.keys(got.threads).sort(),['b','c']);
        assert.strictEqual(catchUp(b,{seq:y.seq,entries:[x,y]},x.seq).seq,x.seq);
        // an entry that starts from another number than the one reached is a break in the chain, whatever its own number
        assert.strictEqual(catchUp(b,{seq:y.seq,entries:[x,{...y,from:1699999999999}]}),null);
        // a page that holds a number of a history that was lost (a backup put back): the entries start from another
        assert.strictEqual(catchUp({...b,seq:1700000000100},{seq:y.seq,entries:[x,y]}),null);
        // a target between two entries is no number the board ever had
        assert.strictEqual(catchUp(b,{seq:y.seq,entries:[x,y]},1700000000200),null);
        """)

    def test_the_head_of_the_summary_names_its_number_and_mark(self):
        """summary.json starts with its number and the mark of its content, in that order: the page reads the first
        bytes (a Range request) to know that the summary under its number is still the one it holds. A summary
        written by a writer that does not number has no such head."""
        self.pure_js(r"""
        assert.deepStrictEqual(headOf('{"seq":1795125403506,"mark":"0a1b2c3d","lite":1,"threads":{'),{seq:1795125403506,mark:'0a1b2c3d'});
        assert.deepStrictEqual(headOf('{"seq":7,"mark":"ffffffff"'),{seq:7,mark:'ffffffff'});
        for(const bad of ['{"version":2,"seq":7,"mark":"0a1b2c3d"','{"seq":7,"lite":1','{"seq":7,"mark":"0A1B2C3D"','{"seq":"7","mark":"0a1b2c3d"',
                          '{"seq":7,"mark":"0a1b2c3"}',' {"seq":7,"mark":"0a1b2c3d"','{"seq":12345678901234567,"mark":"0a1b2c3d"','','not json',null,undefined])
          assert.strictEqual(headOf(bad),null,String(bad));
        // does the head vouch for what the page holds? the same number and the same mark
        const held={seq:7,mark:'0a1b2c3d',threads:{}};
        assert.strictEqual(headStands({seq:7,mark:'0a1b2c3d'},held),true);
        assert.strictEqual(headStands({seq:7,mark:'00000000'},held),false);       // another content under the same number
        assert.strictEqual(headStands(null,held),false);                          // a summary with no head: an unnumbered writer
        assert.strictEqual(headStands({seq:7,mark:'0a1b2c3d'},{seq:7,threads:{}}),false);   // a copy from before the marks
        assert.strictEqual(headStands({seq:8,mark:'0a1b2c3d'},held),false);
        """)

    def test_the_freshness_mark_is_honest(self):
        """"מעודכן" only when the server said, within 25 seconds, that its number is the page's; behind otherwise;
        "לא מחובר" with no line, or no word for that long."""
        self.pure_js(r"""
        const t=1_000_000,s=(o)=>({open:true,legacy:false,applied:5,heard:5,heardAt:t-1000,openedAt:t-60000,...o});
        assert.strictEqual(freshness(s({}),t),'fresh');
        assert.strictEqual(freshness(s({heard:6}),t),'behind');                  // the server has more
        assert.strictEqual(freshness(s({heard:4}),t),'behind');                  // the server has less: a whole read is on its way
        assert.strictEqual(freshness(s({applied:null}),t),'behind');
        assert.strictEqual(freshness(s({heardAt:t-25001}),t),'off');             // no word for 25 seconds: a line that is not there
        assert.strictEqual(freshness(s({heardAt:t-24000}),t),'fresh');
        assert.strictEqual(freshness(s({open:false}),t),'off');                  // the line is down: never fresh, whatever was heard
        assert.strictEqual(freshness(s({open:false,heard:6}),t),'off');
        assert.strictEqual(freshness(s({heardAt:NaN,openedAt:t-2000}),t),'behind');   // just opened: on its way
        assert.strictEqual(freshness(s({heardAt:NaN,openedAt:t-9000}),t),'off');
        assert.strictEqual(freshness(s({legacy:true,heardAt:NaN}),t),'legacy');  // a server without numbers: the old mark
        assert.strictEqual(freshness(s({legacy:true,open:false}),t),'off');
        assert.strictEqual(freshness(null,t),'off');
        // in doubt (back on the page, the page's own number said again, a reading that failed, the device's copy):
        // never fresh until a reading that began after it vouched for the screen
        assert.strictEqual(freshness(s({doubt:true}),t),'behind');
        assert.strictEqual(freshness(s({doubt:true,heard:6}),t),'behind');
        assert.strictEqual(freshness(s({doubt:true,open:false}),t),'off');
        assert.strictEqual(freshness(s({doubt:false}),t),'fresh');
        assert.deepStrictEqual([tr(FRESH_TEXT.fresh),tr(FRESH_TEXT.behind),tr(FRESH_TEXT.off)],['מעודכן','מתעדכן…','לא מחובר']);
        """)

    def test_a_reply_is_not_deaf_just_after_the_line_came_back(self):
        """A reply that got no answer counts against itself only when the line was up, and had been for a while, when
        it left, and nothing about the line changed before the next reading answered (owner's guarantee 4)."""
        self.pure_js(r"""
        const t=1_000_000,left=o=>({up:true,upSince:t-60000,flaps:3,at:t,...o});
        assert.strictEqual(deafCounts(left({}),{up:true,flaps:3}),true);
        assert.strictEqual(deafCounts(left({upSince:t-1000}),{up:true,flaps:3}),false);     // the line had just come back
        assert.strictEqual(deafCounts(left({up:false}),{up:true,flaps:3}),false);           // it left with the line down
        assert.strictEqual(deafCounts(left({}),{up:true,flaps:4}),false);                   // the line went or came meanwhile
        assert.strictEqual(deafCounts(left({}),{up:false,flaps:3}),false);
        assert.strictEqual(deafCounts(left({upSince:NaN}),{up:true,flaps:3}),false);
        assert.strictEqual(deafCounts(null,{up:true,flaps:3}),false);
        """)

    def test_the_page_follows_the_numbers(self):
        """The wiring: the line asks from the page's number, a "changed" with an id or an "alive" that differs reads,
        the same number in a "changed" checks the summary's head, an older one reads the whole summary, the changes are
        read before the summary, waiting replies go after a reading that follows a break, and the deaf mark asks
        deafCounts."""
        page = self.page()
        for part in ("events=new EventSource('/events?board='+encodeURIComponent(slug)+(isSeq(appliedNumber)?'&since='+appliedNumber:''));",
                     "events.addEventListener('alive',e=>{",
                     "if(mine!==null&&n<mine)wholeNext=true;refresh();",
                     # the page's own number again (a touched pulse): a reading, which checks the summary's head
                     "if(n===appliedNumber){heard=n;heardAt=Date.now();inDoubt();refresh();paintFresh();return;}",
                     "else if(opening){inDoubt();refresh();}",
                     "if(doubtSeq===doubted)doubt=false;", "readFailed=true;linkFlaps++;inDoubt();paintFresh();",
                     "const head=summaryHead().catch(()=>summaryHead());head.catch(()=>{});",
                     "if(h.seq>at.seq){at=await catchTo(at,h.seq);if(!at)return null;}",
                     "if(!h||h.seq<from.seq)return null;",
                     "if(h.seq===at.seq&&!headStands(h,at))return null;",
                     # back on the page: the mark first, before anything else is drawn
                     "if(document.hidden)return;\n  inDoubt();paintFresh();",
                     "addEventListener('pageshow',e=>{if(e.persisted){inDoubt();paintFresh();",
                     "const next=await readChanges(from);",
                     "if(!deafCounts(left,{up:online,flaps:linkFlaps}))return;",
                     "if(!first&&waitingReplies())sendAgain(back);",
                     "<span id=\"h-fresh\" class=\"h-fresh\" role=\"status\" hidden></span>"):
            self.assertIn(part, page)


    def test_a_silent_or_stuck_line_is_opened_again_soon(self):
        """The server speaks every 10 s ("alive"). A line that said nothing for 1.5 times that is dead without knowing
        it (a phone that lost its link, a socket the network dropped): it is opened again at once. A line that tries
        to open for more than 3 s is tried again, so that the line is back about 3 s after the link is."""
        self.pure_js(r"""
        const t=1_000_000,s=o=>({state:1,numbered:true,wordAt:t-1000,openedAt:t-60000,startedAt:t-60000,...o});
        assert.strictEqual(SILENT_MS,15000);assert.strictEqual(CONNECT_MS,3000);
        assert.strictEqual(lineAction(s({}),t),'');
        assert.strictEqual(lineAction(s({wordAt:t-14000}),t),'');
        assert.strictEqual(lineAction(s({wordAt:t-15001}),t),'reopen');                 // silent past 15 s
        assert.strictEqual(lineAction(s({wordAt:NaN,openedAt:t-16000}),t),'reopen');   // opened, never a word
        assert.strictEqual(lineAction(s({wordAt:NaN,openedAt:t-2000}),t),'');
        assert.strictEqual(lineAction(s({numbered:false,wordAt:t-60000}),t),'');        // a server without numbers has no heartbeat to miss
        assert.strictEqual(lineAction(s({state:0,startedAt:t-3001}),t),'reopen');       // trying to open for too long
        assert.strictEqual(lineAction(s({state:0,startedAt:t-1000}),t),'');
        // each attempt that did not open waits longer (3, 6, 12, 24, then 30 s): a slow link gets its line, a server
        // that is down is not asked every 3 s for ever
        assert.deepStrictEqual([0,1,2,3,4,9].map(connectLimit),[3000,6000,12000,24000,30000,30000]);
        assert.strictEqual(lineAction(s({state:0,startedAt:t-4500,fails:1}),t),'');
        assert.strictEqual(lineAction(s({state:0,startedAt:t-6001,fails:1}),t),'reopen');
        assert.strictEqual(lineAction(s({state:2}),t),'open');                           // closed: open one
        assert.strictEqual(lineAction(null,t),'open');
        """)

    def test_while_the_line_is_down_a_small_probe_finds_the_link_back_within_seconds(self):
        """Everything on its way when a link drops silently waits for TCP's retransmissions, which back off (1, 3, 7,
        15, 31 s): the line and the reply that left just before the link came back stay stuck long after it. A small
        request (the summary's head), one at a time, every 3 s while the line is down (every 15 s after two minutes),
        each given up after 3 s, finds the link back; then what waits goes on fresh connections."""
        self.pure_js(r"""
        const t=1_000_000,s=o=>({open:false,hidden:false,offline:false,downSince:t-10000,lastProbe:t-3500,probing:false,...o});
        assert.deepStrictEqual([PROBE_GAP,PROBE_WAIT,PROBE_SLOW,PROBE_FAST_FOR],[3000,3000,15000,120000]);
        assert.strictEqual(probeDue(s({}),t),true);
        assert.strictEqual(probeDue(s({lastProbe:t-2000}),t),false);
        assert.strictEqual(probeDue(s({probing:true}),t),false);                       // one at a time
        assert.strictEqual(probeDue(s({open:true}),t),false);                          // the line is there: nothing to find
        assert.strictEqual(probeDue(s({hidden:true}),t),false);
        assert.strictEqual(probeDue(s({offline:true}),t),false);                       // the browser says no network: its own event comes
        assert.strictEqual(probeDue(s({downSince:t-200000,lastProbe:t-5000}),t),false); // a long outage: every 15 s
        assert.strictEqual(probeDue(s({downSince:t-200000,lastProbe:t-15001}),t),true);
        assert.strictEqual(probeDue(s({downSince:NaN}),t),false);
        // once a probe answered, the link is alive (only slow): no more probes until the line goes down again
        assert.strictEqual(probeDue(s({alive:true}),t),false);
        // a probe that got no answer waits longer before the next (3, 6, 12 s): a slow link's probe gets through
        assert.deepStrictEqual([0,1,2,5].map(probeWait),[3000,6000,12000,12000]);
        // only the board server's own answer says the link is back: a gateway's 502 says the server is down
        assert.deepStrictEqual([200,206,404,416,502,503,504,500,0].map(linkAnswer),[true,true,true,true,false,false,false,false,false]);
        // a line the server refused (closed) is opened again after its wait, not on every tick
        assert.strictEqual(lineAction({state:2,startedAt:t-1000,fails:1},t),'');
        assert.strictEqual(lineAction({state:2,startedAt:t-6001,fails:1},t),'open');
        """)
        page = self.page()
        for part in ("function probeLink(){", "if(!probeDue({open:linkOpen,", "if(!linkAnswer(r.status)){probeFails++;return;}", "linkAlive=true;lineBack();"):
            self.assertIn(part, page)

    def test_a_silent_line_frees_the_connections_its_reads_hold(self):
        """A browser opens at most 6 connections to one server. When a link drops silently, the reads on their way
        (places, drafts, conversations, the board) hold all six until TCP retransmits, and the probe, the line and the
        reply then wait in the browser's own queue. Every read of this page can be cut: a silent line cuts the reads
        that left before it (not the replies), and the line's return cuts what is still stuck (none twice in a row)."""
        page = self.page()
        for part in ("function cutStuck(back,age=1000){", "if(!back&&way.cid)continue;",
                     "if(back){if(cutOnce.has(way.key)||(way.moving&&way.moving()))continue;cutOnce.add(way.key);}",
                     "const stop=new AbortController(),way=wayOut(stop,null,'get:'+u.pathname);",
                     "if(act==='reopen'&&events&&events.readyState===1)cutStuck(false);", "else if(!linkOpen&&Number.isFinite(downSince)&&!linkAlive)cutStuck(false,probeWait(probeFails));",
                     "const quiet=!leaving&&!!state&&QUIET_POSTS.includes(state.op);", "const QUIET_POSTS=['seen','place','presence','draft'];",
                     "function lineBack(){\n  cutStuck(true);"):
            self.assertIn(part, page)

    def test_requests_from_before_the_line_came_back_go_again_on_a_fresh_connection(self):
        """A request that left on a connection the network dropped waits for a long time. When the line is back, every
        reading and every reply still on its way from before goes again at once (a reply by its cid: never twice)."""
        page = self.page()
        for part in ("function lineBack(){", "for(const way of onTheWay){", "way.cut=true;way.stop.abort();",
                     "events.onopen=()=>{beatAt=null;numbered=false;lineFails=0;const back=everOpen;everOpen=true;connection(true);if(back)lineBack();",
                     "addEventListener('online',()=>{inDoubt();paintFresh();lineBack();",
                     "const reply=!!state&&typeof state.cid==='string'&&(state.op==='reply'||state.op==='snippet-part');",
                     "const way=!stop?null:reply?wayOut(stop,state.cid):quiet?wayOut(stop,null,'post:'+state.op):null;", "const way=cid?wayOut({abort:()=>x.abort()},cid):null;",
                     "if(back){if(cutOnce.has(way.key)||(way.moving&&way.moving()))continue;cutOnce.add(way.key);}"):
            self.assertIn(part, page)

    def test_only_the_server_says_the_board_is_up_to_date(self):
        """The server's number is set only by what the server says on the line (a "changed" with an id, or "alive"),
        never by a reading: a missing changes file (404) is no word that the board stands where the page is."""
        page = self.page()
        code = page[page.index('<script'):]
        sets = re.findall(r'(?<![.\w])heard=n;heardAt=', code)
        self.assertEqual(len(sets), 2, 'heard is set in onNumber and on a "changed" with the page\'s number, nowhere else')
        self.assertEqual(len(re.findall(r'(?<![.\w])heard=(?!null,)', code)), 2)      # (besides its declaration)
        self.assertNotIn('heardNumber', code)


class RichBlockTests(unittest.TestCase):
    """A fenced block an agent writes as JSON (chart, widget, carousel, status) or as SVG is drawn by the page's own
    code. Nothing an agent writes runs in the page: the JSON is validated, a formula is read by a tiny parser, an
    SVG is shown as a picture."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_a_rich_block_is_known_by_its_fence_and_refused_with_a_reason(self):
        self.pure_js(r"""
        assert.strictEqual(richBlock('js','x'),null);assert.strictEqual(richBlock('','x'),null);assert.strictEqual(richBlock('mermaid','graph TD'),null);
        for(const lang of ['chart','Chart','widget','carousel','svg','status']){const r=richBlock(lang,'');assert.ok(r&&r.kind===lang.toLowerCase()&&r.error,lang);}
        // a wrong JSON says so in Hebrew and keeps the kind, so the card shows the code with the reason
        const bad=richBlock('chart','{"type":"bar",');assert.strictEqual(bad.kind,'chart');assert.ok(/JSON/.test(bad.error),bad.error);
        // a block too big for a message card is refused before it is parsed
        const big=richBlock('chart','{"x":"'+'a'.repeat(RICH_MAX)+'"}');assert.ok(big.error&&/גדול/.test(big.error));
        assert.strictEqual(RICH_KINDS.chart,'גרף');assert.strictEqual(RICH_KINDS.widget,'מחשבון');assert.strictEqual(RICH_KINDS.carousel,'קרוסלה');assert.strictEqual(RICH_KINDS.svg,'SVG');assert.strictEqual(RICH_KINDS.status,'סטטוס');
        """)

    def test_a_chart_is_checked_before_it_is_drawn(self):
        self.pure_js(r"""
        const ok=richBlock('chart',JSON.stringify({type:'bar',title:'עלות',labels:['א','ב','ג'],series:[{name:'on-demand',values:[4766,2100,95]},{name:'Spot',values:[0,900,40]}],prefix:'$'}));
        assert.ok(!ok.error,ok.error);const m=ok.model;
        assert.strictEqual(m.type,'bar');assert.strictEqual(m.title,'עלות');assert.deepStrictEqual(m.labels,['א','ב','ג']);assert.strictEqual(m.series.length,2);assert.deepStrictEqual(m.series[1].values,[0,900,40]);assert.strictEqual(m.prefix,'$');assert.strictEqual(m.suffix,'');
        // the type defaults to bars; numbers as labels are fine; a series without a name is named by its number
        const d=richBlock('chart','{"labels":[2024,2025],"series":[{"values":[1,2]}]}');assert.ok(!d.error,d.error);assert.strictEqual(d.model.type,'bar');assert.deepStrictEqual(d.model.labels,['2024','2025']);assert.strictEqual(d.model.series[0].name,'סדרה 1');
        const no=(json,why)=>{const r=richBlock('chart',typeof json==='string'?json:JSON.stringify(json));assert.ok(r.error,JSON.stringify(json));assert.ok(why.test(r.error),r.error+' !~ '+why);};
        no({type:'area',labels:['a'],series:[{values:[1]}]},/type/);
        no({labels:[],series:[{values:[]}]},/labels/);
        no({labels:['a'],series:[]},/series/);
        no({labels:['a'],series:[{values:['לא מספר']}]},/מספר/);
        no({labels:['a','b'],series:[{values:[1]}]},/label/);
        no({labels:Array.from({length:61},(_,i)=>'l'+i),series:[{values:Array(61).fill(1)}]},/labels/);
        no({labels:['a'],series:Array.from({length:9},()=>({values:[1]}))},/series/);
        no({type:'pie',labels:['a','b'],series:[{values:[1,2]},{values:[3,4]}]},/pie|עוגה/);
        no({type:'pie',labels:['a','b'],series:[{values:[1,-2]}]},/שלילי/);
        no('[1,2]',/JSON|אובייקט/);
        no({labels:['a'],series:[{values:[1]}],decimals:9},/decimals/);
        """)

    def test_numbers_and_ticks_read_well(self):
        self.pure_js(r"""
        assert.strictEqual(fmtNum(1125000,{prefix:'$'}),'$1,125,000');assert.strictEqual(fmtNum(2.5,{decimals:1,prefix:'$'}),'$2.5');assert.strictEqual(fmtNum(0.5,{decimals:2}),'0.50');
        assert.strictEqual(fmtNum(-5,{prefix:'$'}),'-$5');assert.strictEqual(fmtNum(12,{suffix:' שנ׳'}),'12 שנ׳');assert.strictEqual(fmtNum(NaN,{}),'-');assert.strictEqual(fmtNum(Infinity,{}),'-');
        assert.strictEqual(fmtNum(1234.5678,{}),'1,234.57');assert.strictEqual(fmtNum(1000,{}),'1,000');assert.strictEqual(fmtNum(0.1+0.2,{}),'0.3');assert.strictEqual(fmtNum(3,{decimals:0}),'3');assert.strictEqual(fmtNum(2.6,{decimals:0}),'3');
        // ticks: round numbers that cover the data, zero always among them when the data is on one side of it
        assert.deepStrictEqual(niceTicks(0,4766,5),[0,1000,2000,3000,4000,5000]);assert.deepStrictEqual(niceTicks(0,95,4),[0,50,100]);assert.deepStrictEqual(niceTicks(35,180,5),[0,50,100,150,200]);
        assert.deepStrictEqual(niceTicks(-50,120,5),[-50,0,50,100,150]);assert.deepStrictEqual(niceTicks(0,0,5),[0,1]);assert.deepStrictEqual(niceTicks(7,7,5),[0,2,4,6,8]);assert.deepStrictEqual(niceTicks(0,0.9,5),[0,0.2,0.4,0.6,0.8,1]);
        """)

    def test_chart_geometry_is_computed_from_the_data(self):
        self.pure_js(r"""
        const bar=richBlock('chart',JSON.stringify({type:'bar',labels:['א','ב','ג'],series:[{name:'x',values:[100,50,0]},{name:'y',values:[25,75,10]}]})).model;
        const L=chartLayout(bar,600);
        assert.ok(L.w===600&&L.h>=180&&L.h<=360,JSON.stringify([L.w,L.h]));
        assert.strictEqual(L.bars.length,6);assert.strictEqual(L.lines.length,0);assert.strictEqual(L.slices.length,0);assert.deepStrictEqual(L.legend.map(l=>l.name),['x','y']);
        // every bar stands inside the plot on its baseline; a taller value is a taller bar, in proportion; a zero is flat
        const inside=b=>b.x>=L.plot.x-0.01&&b.x+b.w<=L.plot.x+L.plot.w+0.01&&b.y>=L.plot.y-0.01&&b.y+b.h<=L.plot.y+L.plot.h+0.01;
        assert.ok(L.bars.every(inside),JSON.stringify(L.bars));
        const of=(s,i)=>L.bars.find(b=>b.s===s&&b.i===i);
        assert.ok(Math.abs(of(0,0).h-2*of(0,1).h)<0.01);assert.strictEqual(of(0,2).h,0);assert.ok(Math.abs(of(1,1).h-3*of(1,0).h)<0.01);
        assert.ok(L.bars.every(b=>Math.abs(b.y+b.h-(L.plot.y+L.plot.h))<0.01),'bars stand on the baseline');
        // bars of one label are side by side with a gap, and the categories read in order from the left
        assert.ok(of(0,0).x<of(1,0).x&&of(1,0).x<of(0,1).x);assert.ok(of(1,0).x>of(0,0).x+of(0,0).w);
        assert.deepStrictEqual(L.cats.map(c=>c.label),['א','ב','ג']);assert.ok(L.cats[0].x<L.cats[1].x);
        assert.ok(L.ticks.length>=3&&L.ticks[0].value===0&&L.ticks.at(-1).value>=100);assert.ok(L.ticks.every(t=>t.y>=L.plot.y-0.01&&t.y<=L.plot.y+L.plot.h+0.01));
        // stacked: the second series sits on the first
        const st=chartLayout(richBlock('chart',JSON.stringify({type:'bar',stack:true,labels:['א'],series:[{values:[10]},{values:[30]}]})).model,400);
        const a=st.bars.find(b=>b.s===0),b=st.bars.find(b=>b.s===1);assert.ok(Math.abs(a.y-(b.y+b.h))<0.01&&Math.abs(b.h-3*a.h)<0.01,JSON.stringify(st.bars));
        // a line per series, a point per label, the first point on the left
        const line=chartLayout(richBlock('chart',JSON.stringify({type:'line',labels:['א','ב','ג','ד'],series:[{values:[1,2,3,4]},{values:[4,3,2,1]}]})).model,500);
        assert.strictEqual(line.lines.length,2);assert.strictEqual(line.lines[0].points.length,4);assert.ok(line.lines[0].points[0].x<line.lines[0].points[3].x);assert.ok(line.lines[0].points[0].y>line.lines[0].points[3].y);
        assert.ok(Math.abs(line.lines[0].points[0].y-line.lines[1].points[3].y)<0.01);
        // a pie: shares that add up to one, each slice with a path and a place for its label; a zero slice is left out
        const pie=chartLayout(richBlock('chart',JSON.stringify({type:'pie',labels:['א','ב','ג'],series:[{values:[75,25,0]}]})).model,360);
        assert.strictEqual(pie.slices.length,2);assert.ok(Math.abs(pie.slices.reduce((t,s)=>t+s.share,0)-1)<1e-9);assert.ok(pie.slices[0].d.startsWith('M')&&/A/.test(pie.slices[0].d));assert.strictEqual(pie.slices[0].label,'א');assert.ok(pie.slices[0].share===0.75);
        // a single full slice still draws (an arc of 360 degrees is drawn as two)
        const one=chartLayout(richBlock('chart',JSON.stringify({type:'pie',labels:['א','ב'],series:[{values:[5,0]}]})).model,360);assert.strictEqual(one.slices.length,1);assert.ok((one.slices[0].d.match(/A/g)||[]).length>=2);
        // negatives: the baseline moves up and the bar hangs under it
        const neg=chartLayout(richBlock('chart',JSON.stringify({labels:['א','ב'],series:[{values:[-20,40]}]})).model,400);
        const down=neg.bars.find(b=>b.i===0),up=neg.bars.find(b=>b.i===1);assert.ok(Math.abs(down.y-(up.y+up.h))<0.01&&Math.abs(up.h-2*down.h)<0.01,JSON.stringify(neg.bars));
        // on a phone the layout keeps room for the labels still, and never goes outside its width
        const small=chartLayout(bar,280);assert.ok(small.plot.x+small.plot.w<=280&&small.plot.w>120,JSON.stringify(small.plot));
        """)

    def test_a_formula_is_read_by_the_page_never_run(self):
        self.pure_js(r"""
        const run=(text,vars)=>evalExpr(parseExpr(text),vars||{});
        assert.strictEqual(run('1+2*3'),7);assert.strictEqual(run('(1+2)*3'),9);assert.strictEqual(run('-2^2'),-4);assert.strictEqual(run('2^3^2'),512);assert.strictEqual(run('10/4'),2.5);assert.strictEqual(run('7%3'),1);
        assert.strictEqual(run('machines*tx*avg*30',{machines:1000,tx:15,avg:2.5}),1125000);assert.strictEqual(run('min(a,b)+max(a,b)',{a:3,b:9}),12);assert.strictEqual(run('round(2.5)+floor(2.9)+ceil(2.1)+abs(-4)+sqrt(16)'),16);
        assert.strictEqual(run(' a + 1.5e2 ',{a:1}),151);assert.strictEqual(run('round(x,2)',{x:3.14159}),3.14);assert.strictEqual(run('a*(1-fee/100)',{a:200,fee:1.5}),197);
        // an unknown name or a division by zero is no number, never a crash
        assert.ok(Number.isNaN(run('a+b',{a:1})));assert.ok(!Number.isFinite(run('1/0')));
        // what is not a formula is refused with a reason: no words, no dots, no brackets, no assignments, no strings
        for(const bad of ['a.b','a["x"]','a=1','a;b','"x"','x++','a ? b : c','foo(1)','1 +','(1','sqrt','a b','1,2','a &&b','`x`','a=>1','new X','this','window.x'])
          assert.throws(()=>parseExpr(bad),Error,bad);
        assert.throws(()=>parseExpr('('.repeat(60)+'1'+')'.repeat(60)),/עמוק/);assert.throws(()=>parseExpr('1+'.repeat(300)+'1'),/ארוכ/);
        assert.deepStrictEqual([...exprVars(parseExpr('a*b+min(c,2)'))].sort(),['a','b','c']);
        """)

    def test_a_widget_is_sliders_and_formulas_checked_together(self):
        self.pure_js(r"""
        const w=richBlock('widget',JSON.stringify({title:'סימולטור הכנסות',note:'דוגמה',inputs:[{id:'machines',label:'מספר מכונות',min:100,max:5000,step:100,value:1000},{id:'tx',label:'עסקאות ביום',min:1,max:40,value:15},{id:'avg',label:'עסקה ממוצעת',min:0.5,max:10,step:0.5,value:2.5,prefix:'$',decimals:1}],outputs:[{label:'מחזור חודשי',formula:'machines*tx*avg*30',prefix:'$',decimals:0,note:'לפני עמלות'},{label:'עמלה',formula:'machines*tx*avg*30*0.015',prefix:'$'}]}));
        assert.ok(!w.error,w.error);const m=w.model;
        assert.strictEqual(m.title,'סימולטור הכנסות');assert.strictEqual(m.inputs.length,3);assert.strictEqual(m.inputs[1].step,1);assert.strictEqual(m.inputs[2].prefix,'$');assert.strictEqual(m.outputs.length,2);
        // the outputs for a set of values, as text
        assert.deepStrictEqual(widgetOutputs(m,{machines:1000,tx:15,avg:2.5}).map(o=>o.text),['$1,125,000','$16,875']);
        assert.deepStrictEqual(widgetOutputs(m,{machines:2000,tx:15,avg:2.5}).map(o=>o.text),['$2,250,000','$33,750']);
        assert.strictEqual(widgetOutputs(m,{}).map(o=>o.text)[0],'-');
        // the values start where the agent put them, inside the range, on the step
        assert.deepStrictEqual(widgetStart(m),{machines:1000,tx:15,avg:2.5});
        assert.deepStrictEqual(widgetStart(richBlock('widget',JSON.stringify({inputs:[{id:'a',label:'a',min:0,max:10,value:99},{id:'b',label:'b',min:5,max:10}],outputs:[{label:'x',formula:'a+b'}]})).model),{a:10,b:5});
        // the text of an input's value, with its own prefix and decimals
        assert.strictEqual(inputText(m.inputs[2],2.5),'$2.5');assert.strictEqual(inputText(m.inputs[0],1000),'1,000');
        const no=(json,why)=>{const r=richBlock('widget',JSON.stringify(json));assert.ok(r.error,JSON.stringify(json));assert.ok(why.test(r.error),r.error+' !~ '+why);};
        no({inputs:[],outputs:[{label:'x',formula:'1'}]},/inputs/);
        no({inputs:[{id:'a',label:'a',min:0,max:10}],outputs:[]},/outputs/);
        no({inputs:[{id:'a',label:'a',min:10,max:0}],outputs:[{label:'x',formula:'a'}]},/min|max/);
        no({inputs:[{id:'a',label:'a',min:0,max:10,step:0}],outputs:[{label:'x',formula:'a'}]},/step/);
        no({inputs:[{id:'a b',label:'a',min:0,max:10}],outputs:[{label:'x',formula:'a'}]},/id/);
        no({inputs:[{id:'a',label:'a',min:0,max:10},{id:'a',label:'b',min:0,max:10}],outputs:[{label:'x',formula:'a'}]},/id/);
        no({inputs:[{id:'a',label:'a',min:0,max:10}],outputs:[{label:'x',formula:'a*zzz'}]},/zzz/);
        no({inputs:[{id:'a',label:'a',min:0,max:10}],outputs:[{label:'x',formula:'a.b'}]},/formula/);
        no({inputs:[{id:'a',min:0,max:10}],outputs:[{label:'x',formula:'a'}]},/label/);
        no({inputs:Array.from({length:9},(_,i)=>({id:'v'+i,label:'v',min:0,max:1})),outputs:[{label:'x',formula:'v0'}]},/inputs/);
        """)

    def test_a_carousel_a_status_and_an_svg_are_checked_too(self):
        self.pure_js(r"""
        const c=richBlock('carousel',JSON.stringify({slides:[{title:'א',text:'ראשון',image:1},{text:'שני',image:2},{title:'סיכום'}]}));
        assert.ok(!c.error,c.error);assert.strictEqual(c.model.slides.length,3);assert.strictEqual(c.model.slides[0].image,1);assert.strictEqual(c.model.slides[2].image,0);assert.strictEqual(c.model.slides[1].title,'');
        const no=(kind,json,why)=>{const r=richBlock(kind,typeof json==='string'?json:JSON.stringify(json));assert.ok(r.error,JSON.stringify(json));assert.ok(why.test(r.error),r.error+' !~ '+why);};
        no('carousel',{slides:[]},/slides/);no('carousel',{slides:[{}]},/שקופית/);no('carousel',{slides:[{image:'a.png'}]},/image/);no('carousel',{slides:[{image:5}]},/image/);
        no('carousel',{slides:Array.from({length:21},()=>({title:'x'}))},/slides/);
        // a status card: a title, a state from the known few, lines with their own states, a share done
        const s=richBlock('status',JSON.stringify({title:'PR #1620',state:'running',lines:[{label:'CI',value:'רץ',state:'running'},{label:'סקירה',value:'2/2',state:'ok'},{label:'מיזוג',value:'מחכה'}],progress:0.6,note:'יעודכן'}));
        assert.ok(!s.error,s.error);assert.strictEqual(s.model.state,'running');assert.strictEqual(s.model.lines.length,3);assert.strictEqual(s.model.lines[2].state,'');assert.strictEqual(s.model.progress,0.6);assert.strictEqual(s.model.note,'יעודכן');
        assert.strictEqual(richBlock('status','{"title":"x"}').model.state,'running');assert.strictEqual(richBlock('status','{"title":"x","progress":7}').model.progress,1);assert.strictEqual(richBlock('status','{"title":"x"}').model.progress,-1);
        no('status',{state:'ok'},/title/);no('status',{title:'x',state:'burning'},/state/);no('status',{title:'x',lines:[{value:'v'}]},/label/);no('status',{title:'x',lines:Array.from({length:13},()=>({label:'a',value:'b'}))},/lines/);
        assert.deepStrictEqual(Object.keys(STATUS_STATES),['todo','waiting','running','ok','done','failed','blocked']);
        // an SVG becomes a picture: it gets its namespace, its size from the viewBox, and never carries script
        const v=richBlock('svg','<svg viewBox="0 0 320 120"><rect width="10" height="10"/></svg>');
        assert.ok(!v.error,v.error);assert.deepStrictEqual([v.model.w,v.model.h],[320,120]);assert.ok(v.model.url.startsWith('data:image/svg+xml;charset=utf-8,'));assert.ok(/xmlns="http:\/\/www.w3.org\/2000\/svg"/.test(v.model.code));
        const sized=richBlock('svg','<?xml version="1.0"?>\n<!-- a -->\n<svg xmlns="http://www.w3.org/2000/svg" width="200px" height="50"><circle r="4"/></svg>');assert.ok(!sized.error,sized.error);assert.deepStrictEqual([sized.model.w,sized.model.h],[200,50]);assert.strictEqual((sized.model.code.match(/xmlns="http:\/\/www.w3.org\/2000\/svg"/g)||[]).length,1);
        assert.deepStrictEqual([richBlock('svg','<svg><g/></svg>').model.w,richBlock('svg','<svg><g/></svg>').model.h],[0,0]);
        no('svg','<div>x</div>',/svg/);no('svg','<svg><script>alert(1)</script></svg>',/script/);no('svg','<svg><a href="javascript:alert(1)"><text>x</text></a></svg>',/script/);no('svg','<svg><foreignObject><div>x</div></foreignObject></svg>',/foreignObject/);
        no('svg','<svg onload="alert(1)"></svg>',/on/);no('svg','<svg><image href="http://x/y.png"/></svg>',/רשת|http/);
        """)

    def test_rich_blocks_are_drawn_by_the_page_in_its_own_code(self):
        page = self.page()
        # the hook: after the markdown, before the code blocks are dressed; a rich card keeps its source but is not a code card
        self.assertIn('dressActions(body,t,m);drawDiagrams(body);const taken=dressRich(body,t,m,pics);dressDiffs(body);dressCode(body,t,m);dressTables(body);dressLinks(body);', page)
        self.assertIn('const shown=pics.filter((pic,n)=>!taken.has(n+1));', page)
        self.assertIn("pre.closest('.code,.rich')", page)
        script = page.split('<script>')[1]
        # a chart is SVG built node by node; a widget is sliders (native range inputs: the keyboard moves them); an
        # agent's SVG is a picture, not markup; the status card knows its states
        for part in ("createElementNS(SVG_NS,", "input.type='range'", "img.src=model.url", "STATUS_STATES[model.state]", "scrollWatch.observe(", "tr('Table')", "'PNG'", "tr('Full screen')"):
            self.assertIn(part, script)
        self.assertNotIn('innerHTML', script.split('function dressRich(')[1].split('\n// ── ')[0])
        # the series colours are the page's own variables, in light and in dark
        for n in range(1, 9):
            self.assertEqual(page.count('--series-%d:' % n), 3, n)



class DiffTests(unittest.TestCase):
    """A ```diff block, or a git diff pasted as it is, is drawn as a diff viewer (the owner;
    suda-fixes task 12): files, hunks, old and new line numbers, word marks inside a changed line. The reading is
    pure and tested here; the drawing puts every piece of the diff in the page as text, never as markup."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    TWO = r"""
const TWO=['diff --git a/src/app.js b/src/app.js','index 3b18e51..a9c2f04 100644','--- a/src/app.js','+++ b/src/app.js',
 '@@ -1,4 +1,5 @@ function start()',' const a=1;','-const b=2;','+const b=3;','+const c=4;',' const d=5;',' const e=6;',
 '@@ -20,3 +21,2 @@',' x();','-y();',' z();',
 'diff --git a/README.md b/README.md','--- a/README.md','+++ b/README.md','@@ -1 +1 @@','-Hello world','+Hello there world',''].join('\n');
"""

    def test_a_diff_of_two_files_is_read_into_files_hunks_and_numbered_lines(self):
        self.pure_js(self.TWO + r"""
        const d=parseDiff(TWO);assert.ok(d&&!d.loose);assert.strictEqual(d.files.length,2);
        const [a,b]=d.files;
        assert.deepStrictEqual([a.old,a.new,a.status,a.adds,a.dels],['src/app.js','src/app.js','modified',2,2]);
        assert.deepStrictEqual([b.old,b.new,b.adds,b.dels],['README.md','README.md',1,1]);
        assert.deepStrictEqual([d.adds,d.dels],[3,3]);
        assert.strictEqual(a.hunks.length,2);
        const h=a.hunks[0];assert.deepStrictEqual([h.oldStart,h.oldCount,h.newStart,h.newCount,h.section],[1,4,1,5,'function start()']);
        // each line keeps its text without the sign, and its numbers on each side (none on the side it is not on)
        assert.deepStrictEqual(h.lines.map(l=>[l.kind,l.text,l.old,l.new]),[
          [' ','const a=1;',1,1],['-','const b=2;',2,null],['+','const b=3;',null,2],['+','const c=4;',null,3],[' ','const d=5;',3,4],[' ','const e=6;',4,5]]);
        assert.deepStrictEqual(a.hunks[1].lines.map(l=>[l.kind,l.old,l.new]),[[' ',20,21],['-',21,null],[' ',22,22]]);
        // "@@ -1 +1 @@": a count left out is one
        assert.deepStrictEqual([b.hunks[0].oldCount,b.hunks[0].newCount],[1,1]);
        """)

    def test_new_deleted_renamed_and_binary_files(self):
        self.pure_js(r"""
        const d=parseDiff(['diff --git a/new.txt b/new.txt','new file mode 100644','index 0000000..e69de29','--- /dev/null','+++ b/new.txt','@@ -0,0 +1,2 @@','+one','+two',
          'diff --git a/old.txt b/old.txt','deleted file mode 100644','--- a/old.txt','+++ /dev/null','@@ -1 +0,0 @@','-gone',
          'diff --git a/a dir/x.py b/b dir/y.py','similarity index 90%','rename from a dir/x.py','rename to b dir/y.py','--- a/a dir/x.py','+++ b/b dir/y.py','@@ -3 +3 @@','-v=1','+v=2',
          'diff --git a/same.txt b/moved/same.txt','similarity index 100%','rename from same.txt','rename to moved/same.txt',
          'diff --git a/logo.png b/logo.png','index 1..2 100644','Binary files a/logo.png and b/logo.png differ',
          'diff --git a/run.sh b/run.sh','old mode 100644','new mode 100755',
          'diff --git a/pic.gif b/pic.gif','new file mode 100644','GIT binary patch','literal 12','zcmV+ABCDEFGHIJ','','literal 0','HcmV?d00001','',
          'diff --git "a/caf\\303\\251 \\"q\\".txt" "b/caf\\303\\251 \\"q\\".txt"','--- "a/caf\\303\\251 \\"q\\".txt"','+++ "b/caf\\303\\251 \\"q\\".txt"','@@ -1 +1 @@','-a','+b'].join('\n'));
        const f=d.files;assert.strictEqual(f.length,8);
        assert.deepStrictEqual([f[0].status,f[0].old,f[0].new,f[0].adds],['added','/dev/null','new.txt',2]);
        assert.deepStrictEqual(f[0].hunks[0].lines.map(l=>l.new),[1,2]);
        assert.deepStrictEqual([f[1].status,f[1].old,f[1].new,f[1].dels],['deleted','old.txt','/dev/null',1]);
        assert.deepStrictEqual([f[2].status,f[2].old,f[2].new],['renamed','a dir/x.py','b dir/y.py']);
        assert.deepStrictEqual([f[3].status,f[3].old,f[3].new,f[3].hunks.length],['renamed','same.txt','moved/same.txt',0]);
        assert.deepStrictEqual([f[4].binary,f[4].old,f[4].new,f[4].hunks.length],[true,'logo.png','logo.png',0]);
        assert.deepStrictEqual([f[5].mode,f[5].hunks.length],['100644 → 100755',0]);
        // the binary patch's data is not read as lines of the file, and the next file is still found after it
        assert.deepStrictEqual([f[6].binary,f[6].status,f[6].hunks.length],[true,'added',0]);
        assert.deepStrictEqual([f[7].old,f[7].new,f[7].adds],['café "q".txt','café "q".txt',1]);
        // the names a reader is shown: the new name, the old one for a deleted file, both for a rename
        assert.deepStrictEqual(f.slice(0,4).map(diffLabel),[{name:'new.txt',from:''},{name:'old.txt',from:''},{name:'b dir/y.py',from:'a dir/x.py'},{name:'moved/same.txt',from:'same.txt'}]);
        """)

    def test_no_newline_at_end_of_file_marks_the_line_and_counts_as_none(self):
        self.pure_js(r"""
        const d=parseDiff(['--- a/x.txt','+++ b/x.txt','@@ -1,2 +1,2 @@',' keep','-last','\\ No newline at end of file','+last','\\ No newline at end of file',
          '--- a/y.txt','+++ b/y.txt','@@ -1 +1 @@','-q','+r','\\ Kein Zeilenumbruch am Dateiende.'].join('\n'));
        assert.strictEqual(d.files.length,2);
        assert.deepStrictEqual(d.files[0].hunks[0].lines.map(l=>[l.kind,l.text,l.noEol]),[[' ','keep',false],['-','last',true],['+','last',true]]);
        assert.deepStrictEqual(d.files[1].hunks[0].lines.map(l=>l.noEol),[false,true]);      // in any language
        // plain diff -u names lose their dates; with no a/ b/ the names stay as they are
        const u=parseDiff('--- x.c.orig\t2024-01-01 10:00:00.000 +0200\n+++ x.c\t2024-01-02 10:00:00.000 +0200\n@@ -1 +1 @@\n-1\n+2\n');
        assert.deepStrictEqual([u.files[0].old,u.files[0].new],['x.c.orig','x.c']);
        """)

    def test_the_numbers_of_a_hunk_decide_where_it_ends(self):
        self.pure_js(r"""
        // a deleted line "-- a" and an added line "++ b" inside the counts are lines, not the header of another file
        const d=parseDiff(['--- a/m.sql','+++ b/m.sql','@@ -1,2 +1,2 @@','--- a','+++ b',' x'].join('\n'));
        assert.strictEqual(d.files.length,1);assert.deepStrictEqual(d.files[0].hunks[0].lines.map(l=>[l.kind,l.text]),[['-','-- a'],['+','++ b'],[' ','x']]);
        // an empty line inside the counts is an empty line of context (a paste loses the space)
        const e=parseDiff(['--- a/p','+++ b/p','@@ -1,3 +1,3 @@',' a','','-b','+c'].join('\n'));
        assert.deepStrictEqual(e.files[0].hunks[0].lines.map(l=>[l.kind,l.old,l.new]),[[' ',1,1],[' ',2,2],['-',3,null],['+',null,3]]);
        // a git format-patch mail: its words before the diff are kept, its signature is not read as a deleted line
        const mail=parseDiff(['From 1234 Mon Sep 17 00:00:00 2001','Subject: [PATCH] fix','','---',' a.txt | 2 +-','','diff --git a/a.txt b/a.txt','--- a/a.txt','+++ b/a.txt','@@ -1 +1 @@','-x','+y','-- ','2.39.0'].join('\n'));
        assert.strictEqual(mail.files.length,1);assert.deepStrictEqual(mail.pre.slice(0,2),['From 1234 Mon Sep 17 00:00:00 2001','Subject: [PATCH] fix']);
        assert.deepStrictEqual([mail.files[0].adds,mail.files[0].dels],[1,1]);
        // a hunk whose numbers are wrong (written by hand) still shows its lines, numbered on
        const w=parseDiff(['--- a/q','+++ b/q','@@ -1,1 +1,1 @@','-a','+b','+c',' d'].join('\n'));
        assert.deepStrictEqual(w.files[0].hunks[0].lines.map(l=>[l.kind,l.old,l.new]),[['-',1,null],['+',null,1],['+',null,2],[' ',2,3]]);
        """)

    def test_a_block_written_by_hand_without_headers_is_still_a_diff(self):
        self.pure_js(r"""
        const d=parseDiff('-const a = 1;\n+const a = 2;\n console.log(a);');
        assert.ok(d.loose);assert.strictEqual(d.files.length,1);const h=d.files[0].hunks[0];
        assert.strictEqual(h.numbered,false);assert.deepStrictEqual(h.lines.map(l=>[l.kind,l.text,l.old,l.new]),[['-','const a = 1;',null,null],['+','const a = 2;',null,null],[' ','console.log(a);',null,null]]);
        // "@@" with no numbers starts a hunk too; "--- / +++" with no hunk header goes straight to its lines
        const at=parseDiff('@@ the config @@\n-on: true\n+on: false');assert.deepStrictEqual([at.files[0].hunks[0].section,at.files[0].adds],['the config',1]);
        const named=parseDiff('--- a/x\n+++ b/x\n-1\n+2');assert.deepStrictEqual([named.files[0].new,named.files[0].adds,named.files[0].dels],['x',1,1]);
        // no change at all is not a diff: the block stays a plain block of code
        assert.strictEqual(parseDiff('just some text\nand more'),null);assert.strictEqual(parseDiff(''),null);
        """)

    def test_a_pasted_git_diff_is_found_in_the_text_and_ends_where_the_diff_does(self):
        self.pure_js(self.TWO + r"""
        const lines=('Look at this:\n'+TWO.trimEnd()+'\n\nThat is all.').split('\n');
        assert.strictEqual(diffRun(lines,0),0);          // a line of prose starts no diff
        const end=diffRun(lines,1);assert.strictEqual(lines[end],'');assert.strictEqual(lines[end-1],'+Hello there world');
        // only a real start counts: "diff --git", or "---" with "+++" and a numbered hunk
        assert.strictEqual(diffRun(['--- just a rule','text'],0),0);assert.strictEqual(diffRun(['--- a','+++ b','not a hunk'],0),0);
        assert.strictEqual(diffRun(['--- a/x','+++ b/x','@@ -1 +1 @@','-1','+2','- a list item'],0),5);       // strict: the counts end it
        assert.ok(wholeDiff(TWO));assert.ok(wholeDiff('\n'+TWO));assert.ok(!wholeDiff('intro\n'+TWO));assert.ok(!wholeDiff('-a\n+b'));
        // the page's markdown keeps a pasted diff whole (its "-" lines are not a list) and the text around it as text
        const html=markdown('Look at this:\n'+TWO.trimEnd()+'\n\nThat is all.');
        assert.strictEqual((html.match(/<pre class="lang-diff pasted">/g)||[]).length,1);assert.ok(!/<ul>|<li/.test(html),html);
        assert.ok(html.includes('<p dir="ltr">Look at this:</p>')||html.includes('Look at this:'));assert.ok(html.endsWith('That is all.</p>'));
        // inside a fence it stays the fence's block
        assert.strictEqual((markdown('```\n'+TWO+'```').match(/<pre/g)||[]).length,1);
        """)

    def test_a_pasted_diff_never_hides_a_fence_from_the_page(self):
        """Hostile review of fbc79da: a context line " ```" (a diff of a README) went into the pasted diff, so the page
        saw one fence less than the server's fencedBlocks and could put a run button on another block. A run that holds
        a fence line is not a pasted diff: page and server count the same fences."""
        self.pure_js(r"""
        const msg=['The patch:','--- a/README.md','+++ b/README.md','@@ -1,4 +1,4 @@',' Install:',' ```','! rm -rf build',' ```','echo harmless'].join('\n');
        assert.strictEqual(diffRun(msg.split('\n'),1),1);
        const html=markdown(msg);assert.ok(!html.includes('pasted'));
        assert.strictEqual((html.match(/<pre/g)||[]).length,fencedBlocks(msg).length);
        // a fence line anywhere in the run (as the server reads one: spaces or a tab, then three backticks)
        const run=last=>['diff --git a/r b/r','--- a/r','+++ b/r','@@ -1,2 +1,2 @@',' x',last];
        for(const fence of ['\t```',' ```',' ```js']){const end=diffRun(run(fence),0);assert.ok(end<=5,fence+' '+end);assert.strictEqual((markdown(run(fence).join('\n')).match(/<pre/g)||[]).length-(end?1:0),1,fence);}
        // a removed or an added fence line is no fence for the server either: that diff stays a diff
        for(const line of ['-```','+```js']){assert.strictEqual(fencedBlocks(run(line).join('\n')).length,0);assert.strictEqual(diffRun(run(line),0),6,line);}
        """)

    def test_finding_a_pasted_diff_is_quick_and_stops_where_the_diff_does(self):
        self.pure_js(r"""
        // many "diff --git" lines with no hunks: read once, not once per line
        const many=Array(20000).fill('diff --git a/x b/x').join('\n');let t0=Date.now();markdown(many);assert.ok(Date.now()-t0<1500,Date.now()-t0);
        // a hunk whose numbers are far too big does not swallow the text after the diff: a blank line and then a line
        // that is not an unchanged line of code end it
        const lines=['--- a/x','+++ b/x','@@ -1,999 +1,999 @@',' keep','-a','+b','','- item one','- item two'];
        assert.strictEqual(diffRun(lines,0),6);
        const html=markdown(lines.join('\n'));assert.ok(/<ul[^>]*><li>item one<\/li><li>item two<\/li><\/ul>$/.test(html),html);assert.strictEqual((html.match(/<pre/g)||[]).length,1);
        // a blank line followed by an unchanged line (its space lost in a paste) is still part of the diff
        assert.strictEqual(diffRun(['--- a/x','+++ b/x','@@ -1,3 +1,3 @@','-a','+b','',' c'],0),7);
        """)

    def test_word_marks_inside_a_changed_line(self):
        self.pure_js(r"""
        const w=wordDiff('const total = price * 2;','const total = price * 3;');
        assert.deepStrictEqual(w.old,[[false,'const total = price * '],[true,'2'],[false,';']]);
        assert.deepStrictEqual(w.new,[[false,'const total = price * '],[true,'3'],[false,';']]);
        // whole words, in Hebrew too; a space alone between two changes goes with them
        const h=wordDiff('שלום עולם יפה','שלום לכולם יפה');assert.deepStrictEqual(h.new,[[false,'שלום '],[true,'לכולם'],[false,' יפה']]);
        const two=wordDiff('the red big dog sat here','the blue small dog sat here');assert.deepStrictEqual(two.old,[[false,'the '],[true,'red big'],[false,' dog sat here']]);
        // the pieces add up to the lines exactly
        const x=wordDiff('if (a && b) { run(1); }','if (a || b) { run(2, true); }');
        assert.strictEqual(x.old.map(p=>p[1]).join(''),'if (a && b) { run(1); }');assert.strictEqual(x.new.map(p=>p[1]).join(''),'if (a || b) { run(2, true); }');
        // lines with too little in common, the same line, and very long lines get no word marks (the whole line is marked)
        assert.strictEqual(wordDiff('alpha beta gamma','zeta eta theta'),null);assert.strictEqual(wordDiff('same','same'),null);
        assert.strictEqual(wordDiff('a'.repeat(WORD_MAX+1),'b'+'a'.repeat(WORD_MAX)),null);
        // a long line with many words is still quick (the table is bounded)
        const many=Array.from({length:240},(_,i)=>'w'+i).join(' ');const t0=Date.now();wordDiff(many.slice(0,WORD_MAX),many.slice(0,WORD_MAX).replace('w7 ','w7x '));assert.ok(Date.now()-t0<200);
        """)

    def test_rows_pair_changed_lines_and_long_context_folds(self):
        self.pure_js(r"""
        const d=parseDiff(['--- a/f','+++ b/f','@@ -1,19 +1,18 @@',...Array.from({length:8},(_,i)=>' top'+i),'-old one','-old two','+new one',...Array.from({length:8},(_,i)=>' mid'+i),'-x','+y'].join('\n'));
        const rows=hunkRows(d.files[0].hunks[0]);
        // a run of deleted lines and the added run after it are one change; its lines are paired in order for word marks
        const change=rows.find(r=>r.kind==='change');assert.strictEqual(change.words,null);assert.deepStrictEqual([change.dels.length,change.adds.length,changeWords(change).length],[2,1,1]);
        assert.deepStrictEqual(changeWords(change)[0],{old:[[true,'old'],[false,' one']],new:[[true,'new'],[false,' one']]});
        // context at the start keeps the 3 lines next to the change and folds the 5 before them; 8 lines between two
        // changes keep 3 on each side, and 2 hidden lines are too few to fold
        const items=foldRows(rows),folds=items.filter(i=>i.kind==='fold');
        assert.deepStrictEqual(folds.map(f=>f.rows.map(r=>r.line.text)),[['top0','top1','top2','top3','top4']]);
        assert.strictEqual(items.filter(i=>i.kind==='same').length,3+8);
        // ten lines between two changes: 3, a fold of 4, 3
        const e=parseDiff(['--- a/f','+++ b/f','@@ -1,12 +1,12 @@','-a','+b',...Array.from({length:10},(_,i)=>' c'+i),'-d','+e'].join('\n'));
        assert.deepStrictEqual(foldRows(hunkRows(e.files[0].hunks[0])).map(i=>i.kind==='fold'?'fold'+i.rows.length:i.kind),['change','same','same','same','fold4','same','same','same','change']);
        // the sizes: files open in order while the first lines fit, the first always; the layout follows the width
        const f=n=>({hunks:[{lines:Array(n)}]});
        assert.deepStrictEqual(diffOpen([f(500),f(10)],300),[true,false]);assert.deepStrictEqual(diffOpen([f(100),f(150),f(100),f(1)],300),[true,true,false,false]);
        assert.strictEqual(diffLayout(360),'unified');assert.strictEqual(diffLayout(700),'unified');assert.strictEqual(diffLayout(DIFF_SPLIT),'split');assert.strictEqual(diffLayout(1000),'split');
        // what "copy" gives: the diff as it was written, with its last newline (so git apply takes it)
        assert.strictEqual(diffCopy('a\n+b'),'a\n+b\n');assert.strictEqual(diffCopy('a\n+b\n'),'a\n+b\n');
        """)

    def test_hostile_content_stays_text(self):
        self.pure_js(r"""
        const evil='<img src=x onerror=alert(1)>';
        const d=parseDiff(['diff --git a/'+evil+' b/'+evil,'--- a/'+evil,'+++ b/'+evil,'@@ -1 +1 @@ <script>alert(2)</script>','-'+evil,'+<b>'+evil+'</b>'].join('\n'));
        assert.strictEqual(d.files[0].new,evil);assert.strictEqual(d.files[0].hunks[0].section,'<script>alert(2)</script>');
        assert.strictEqual(d.files[0].hunks[0].lines[1].text,'<b>'+evil+'</b>');
        // markdown escapes it like any code; the page builds the viewer from the escaped block's text
        const html=markdown('```diff\n-'+evil+'\n+'+evil+'x\n```');assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));
        // a huge diff is not read at all (the block stays code) and a big one is read quickly
        assert.strictEqual(parseDiff('-a\n+b\n'.repeat(DIFF_MAX/4)),null);
        const big=['--- a/big','+++ b/big','@@ -1,20000 +1,20000 @@',...Array.from({length:20000},(_,i)=>(i%3?' ':i%2?'+':'-')+'line '+i)].join('\n');
        const t0=Date.now();const p=parseDiff(big);assert.ok(p.files[0].hunks[0].lines.length===20000);assert.ok(Date.now()-t0<800,Date.now()-t0);
        """)

    def test_the_page_draws_the_viewer_with_text_nodes_only(self):
        page = self.page()
        script = page.split('<script>')[1]
        # the hook: after the rich blocks, before the plain code blocks, in a message and in a thread's context
        self.assertIn('const taken=dressRich(body,t,m,pics);dressDiffs(body);dressCode(body,t,m);', page)
        self.assertIn('dressDiffs(context);dressCode(context);', page)
        drawing = script.split('// ── a diff in the page ──')[1].split('\n// ── ')[0]
        self.assertNotIn('innerHTML', drawing)
        self.assertNotIn('insertAdjacentHTML', drawing)
        for part in ("diffCopy(raw)", "openReader({title:", "diffWatch.observe(", "'wrap-toggle'", "'card diff'"):
            self.assertIn(part, drawing)
        self.assertIn('if(r.diff){', script)
        # the viewer reads left to right inside the right-to-left page, in both themes
        self.assertIn('.diff-view{direction:ltr', page)
        for name in ('--diff-add:', '--diff-del:'):
            self.assertEqual(page.count(name), 3, name)


class SlashTests(unittest.TestCase):
    """Slash commands in the reply box (suda m555, m633, m635, m637, m640, m651): the pure logic. Every command has
    an English name and a Hebrew one (the first Hebrew one is the one shown)."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    NOW = "const NOW=Date.UTC(2026,10,19,10,0)/1000;\n"       # Thursday 19.11.2026 10:00 (the tests run in UTC)

    def test_the_table_has_every_command_with_its_hebrew_name(self):
        self.pure_js(self.NOW + r"""
        const all=slashCommands(),by=Object.fromEntries(all.map(c=>[c.name,c]));
        assert.deepStrictEqual(all.map(c=>c.name),['status','explain','run','s','done','review','urgent','close','rename','mute','task','help','prs','merge','draft','install','split']);
        assert.deepStrictEqual(all.filter(c=>c.round===2).map(c=>c.name),['prs','merge','draft','install','split']);
        assert.deepStrictEqual(all.filter(c=>c.confirm).map(c=>c.name),['merge','draft','install','split']);
        const he={status:'מצב',explain:'הסבר',run:'הרץ',s:'סנוז',done:'סיים',review:'סקירה',urgent:'דחוף',close:'סגור',rename:'שם',mute:'השתק',task:'משימה',help:'עזרה',prs:'פרים',merge:'מזג',draft:'טיוטה',install:'התקן',split:'פצל'};
        for(const c of all){
          assert.strictEqual(c.aliases[0],he[c.name],c.name);
          assert.ok(HEBREW.test(c.about)&&c.about.length>3,c.name+': '+c.about);
          assert.ok(HEBREW.test(c.short)&&c.short.length<=16,c.name+': '+c.short);     // two words on a phone chip
          assert.strictEqual(typeof c.args,'string');
        }
        assert.deepStrictEqual(by.s.names,['s','snooze']);
        // no two commands answer to the same word
        const words=all.flatMap(c=>[...c.names,...c.aliases].map(w=>w.toLowerCase()));
        assert.strictEqual(new Set(words).size,words.length);
        """)

    def test_a_line_is_a_command_only_when_it_names_one(self):
        self.pure_js(self.NOW + r"""
        const t={id:'x',status:'open',tasks:[{n:1,text:'Write docs',status:'todo'},{n:2,text:'Old',status:'done',archived:5}],messages:[]};
        const p=text=>parseSlash(text,{now:NOW,thread:t});
        // not a command: a normal message
        for(const text of ['hello','/Users/x/file.txt','/ hello','hello /status',' /status','/etc is a folder','/שלום לכולם','','/','//status','/tmp/a b'])
          assert.strictEqual(p(text),null,text);
        // as the approved mockup (m651): a lone word that names nothing is a message (/tmp, /xyz, a mistyped one too);
        // the start of a command's name is not a command yet: Enter completes it (`partial`, with what goes in the box)
        for(const text of ['/stauts','/מצבב','/tmp','/xyz','/סטטוס'])assert.strictEqual(p(text),null,text);
        assert.deepStrictEqual([p('/st').partial,p('/st').cmd,p('/st').insert],[true,'','/status ']);
        assert.deepStrictEqual([p('/c').partial,p('/c').insert,p('/d').insert,p('/ס').insert],[true,'/close','/done','/סנוז ']);
        assert.strictEqual(p('/s').cmd,'s');assert.ok(!p('/s').partial);              // a whole short name is the command itself
        // a text of more than one line is always a message
        for(const text of ['/status\nmore','/done\n','/s 2h\nand more','/c\nx'])assert.strictEqual(p(text.replace(/\n$/,'\nx')),null,text);
        // the agents' commands: the words after them go as they are
        assert.deepStrictEqual([p('/status').cmd,p('/status').kind,p('/status').args.words,p('/status').round],['status','agent','',1]);
        assert.deepStrictEqual([p('/מצב').cmd,p('/STATUS').cmd,p('/Explain  the   cache ').args.words,p('/הסבר את המטמון').cmd],['status','status','the cache','explain']);
        assert.strictEqual(p('/הסבר את המטמון').text,'/הסבר את המטמון');
        assert.match(p('/explain '+'x'.repeat(301)).error,/300/);
        assert.deepStrictEqual([p('/done').cmd,p('/סיים').cmd,p('/close').cmd,p('/סגור').cmd,p('/help').cmd,p('/run').kind],['done','done','close','close','help','run']);
        for(const text of ['/done now','/close it','/run 2','/help me','/prs all'])assert.match(p(text).error,/./,text);
        // /s: the times the server reads, his words for today and tomorrow, and a number of hours alone
        const until=text=>{const got=p(text);assert.ok(!got.error,text+': '+got.error);assert.strictEqual(got.cmd,'s');return got.args.until;};
        assert.strictEqual(until('/s 2h'),NOW+7200);assert.strictEqual(until('/s +2h'),NOW+7200);assert.strictEqual(until('/snooze 30m'),NOW+1800);
        assert.strictEqual(until('/סנוז 2 שעות'),NOW+7200);assert.strictEqual(until('/s 1d'),NOW+86400);assert.strictEqual(until('/s 1.5h'),NOW+5400);
        assert.strictEqual(until('/s 12h'),NOW+12*3600);assert.strictEqual(until('/נודניק 3ש'),NOW+3*3600);
        assert.strictEqual(until('/s tomorrow 09:00'),Date.UTC(2026,10,20,9,0)/1000);assert.strictEqual(until('/סנוז מחר 09:00'),Date.UTC(2026,10,20,9,0)/1000);
        assert.strictEqual(until('/s מחר'),Date.UTC(2026,10,20,9,0)/1000);assert.strictEqual(until('/s היום 20:00'),Date.UTC(2026,10,19,20,0)/1000);
        assert.strictEqual(until('/s 16.11 09:00'),Date.UTC(2027,10,16,9,0)/1000);         // passed this year: next year
        assert.strictEqual(until('/s 21/11 09:00'),Date.UTC(2026,10,21,9,0)/1000);assert.strictEqual(until('/s 2026-11-22 08:30'),Date.UTC(2026,10,22,8,30)/1000);
        assert.strictEqual(until('/s 18:00'),Date.UTC(2026,10,19,18,0)/1000);assert.strictEqual(until('/s 08:00'),Date.UTC(2026,10,20,8,0)/1000);
        for(const text of ['/s','/s someday','/s +400d','/s 31.02 09:00','/s 25:00','/s היום 09:00','/s 0h','/s today'])assert.match(p(text).error,/./,text);
        // on and off, in either language
        assert.deepStrictEqual(['/urgent','/urgent on','/urgent off','/דחוף','/דחוף כן','/דחוף לא','/השתק כבה','/mute הפעל','/דחוף off'].map(x=>p(x).args.on),[true,true,false,true,true,false,false,true,false]);
        assert.match(p('/urgent maybe').error,/on/);
        // a new name
        assert.strictEqual(p('/שם   שם  חדש ').args.title,'שם חדש');assert.match(p('/rename').error,/./);assert.match(p('/rename '+'x'.repeat(121)).error,/120/);
        // tasks: add one, set its state, give it new words
        assert.deepStrictEqual(p('/task Write the docs').args,{action:'add',text:'Write the docs'});
        assert.deepStrictEqual(p('/task 3 screens to fix').args,{action:'add',text:'3 screens to fix'});
        assert.deepStrictEqual(p('/task 1 done').args,{action:'state',n:1,status:'done'});
        assert.deepStrictEqual(p('/משימה 1 בוצע').args,{action:'state',n:1,status:'done'});
        assert.deepStrictEqual(p('/task #1 on-owner').args,{action:'state',n:1,status:'on-owner'});
        assert.deepStrictEqual(p('/task 1 עליי').args,{action:'state',n:1,status:'on-owner'});
        assert.deepStrictEqual(p('/task 1 = Better words').args,{action:'text',n:1,text:'Better words'});
        assert.deepStrictEqual(p('/משימה 2=מילים').args,{action:'text',n:2,text:'מילים'});
        for(const text of ['/task','/task 1','/task 1 donee','/task 9 done','/task 1 =','/task '+'x'.repeat(301)])assert.match(p(text).error,/./,text);
        // the second round is known, and asks to confirm
        assert.deepStrictEqual([p('/merge 12 main').args,p('/מזג #12').args,p('/מיזוג 12').args,p('/merge').args,p('/merge').round,p('/merge').confirm],[{pr:12,base:'main'},{pr:12,base:''},{pr:12,base:''},{pr:null,base:''},2,true]);
        assert.match(p('/merge soon').error,/./);
        assert.deepStrictEqual([p('/split A new topic').args.title,p('/פצל נושא').cmd,p('/split').error?1:0],['A new topic','split',1]);
        // every message the parser gives is in Hebrew (the page is)
        for(const text of ['/done now','/s','/s someday','/urgent maybe','/task','/task 1','/task 9 done','/task 1 =','/merge soon','/explain '+'x'.repeat(301)])
          assert.ok(HEBREW.test(p(text).error),text+': '+p(text).error);
        """)

    def test_suggestions_while_he_types(self):
        self.pure_js(self.NOW + r"""
        const t={id:'x',status:'open',urgent:NOW-60,tasks:[{n:1,text:'Write docs',status:'todo'},{n:2,text:'Ship',status:'working'},{n:3,text:'Old',status:'done',archived:5}],
          messages:[{id:'m1',from:'fork',text:'https://github.com/o/r/pull/12 and https://github.com/o/r/pull/7 and https://github.com/o/r/pull/30'}]};
        const links=linksOf({links:{'https://github.com/o/r/pull/12':{kind:'pr',state:'open',title:'Fix the cache',number:12,base:'main',head:'fix',ci:'pass'},
          'https://github.com/o/r/pull/7':{kind:'pr',state:'merged',title:'Old',number:7,base:'main'},
          'https://github.com/o/r/pull/30':{kind:'pr',state:'draft',title:'Docs',number:30,base:'release',ci:'pending'}}});
        const s=text=>slashSuggest(text,{now:NOW,thread:t,links});
        for(const x of s('/'))for(const k of ['label','insert','hint','he','en','about','short'])assert.strictEqual(typeof x[k],'string',k);
        // the name: every command, in Hebrew first, the first round first
        const all=s('/');
        assert.strictEqual(all.length,17);assert.strictEqual(all[0].insert,'/מצב ');assert.ok(all.every(x=>HEBREW.test(x.insert)),JSON.stringify(all.map(x=>x.insert)));
        assert.deepStrictEqual(all.map(x=>x.round),[1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2]);
        assert.deepStrictEqual([all.find(x=>x.en==='s').he,all.find(x=>x.en==='s').en],['סנוז','s']);
        assert.deepStrictEqual(s('/ס').map(x=>x.insert.trim()),['/סנוז','/סיים','/סקירה','/סגור']);
        assert.deepStrictEqual(s('/s').map(x=>x.insert.trim()),['/s','/status','/split']);
        assert.deepStrictEqual(s('/sn').map(x=>x.insert.trim()),['/snooze']);
        assert.deepStrictEqual(s('/sn').map(x=>[x.cmd,x.en,x.he]),[['s','snooze','סנוז']]);
        assert.deepStrictEqual(s('/נוד').map(x=>[x.insert,x.en]),[['/נודניק ','s']]);
        assert.strictEqual(s('/done')[0].insert,'/done');                                  // nothing follows it: no space
        assert.deepStrictEqual(s('/').filter(x=>x.go).map(x=>x.en),['run','done','close','help','prs']);   // nothing to add: chosen, it runs
        assert.deepStrictEqual([s('hello'),s('/xyz'),s('/status\n'),s('/run '),s('/Users/x')],[[],[],[],[],[]]);
        // the keyboard left in Hebrew: "/דאש" is "/sta", and finds /status (said so)
        assert.deepStrictEqual(s('/דאש').map(x=>[x.en,x.wrong,x.insert]),[['status',true,'/מצב ']]);
        assert.ok(s('/ס').every(x=>!x.wrong));
        // the short words in the row itself: /s with 2h, tomorrow 09:00, 12h; /urgent and /mute with on and off, the one in force marked
        const row=name=>all.find(x=>x.en===name);
        assert.deepStrictEqual(row('s').quick.map(q=>[q.label,q.insert]),[['2h','/סנוז 2h'],['מחר 09:00','/סנוז מחר 09:00'],['12h','/סנוז 12h']]);
        assert.deepStrictEqual(row('urgent').quick.map(q=>[q.label,q.insert,!!q.now]),[['on','/דחוף on',true],['off','/דחוף off',false]]);
        assert.deepStrictEqual(row('mute').quick.map(q=>[q.label,!!q.now]),[['on',false],['off',true]]);
        assert.deepStrictEqual(s('/s').find(x=>x.en==='s').quick.map(q=>q.insert),['/s 2h','/s מחר 09:00','/s 12h']);
        for(const x of all)for(const q of x.quick){const got=parseSlash(q.insert,{now:NOW,thread:t});assert.ok(got&&!got.error,q.insert);}
        assert.ok(all.filter(x=>!['s','urgent','mute'].includes(x.en)).every(x=>!x.quick.length));
        // /s: the same three as chips, each a time the parser reads back, and a time he typed himself first
        const times=s('/s ');
        assert.deepStrictEqual(times.map(x=>x.label),['2h','מחר 09:00','12h']);
        assert.ok(times.every(x=>x.go&&HEBREW.test(x.hint)));
        assert.deepStrictEqual(times.map(x=>parseSlash(x.insert,{now:NOW,thread:t}).args.until),[NOW+7200,Date.UTC(2026,10,20,9,0)/1000,NOW+12*3600]);
        assert.ok(s('/סנוז ').every(x=>x.insert.startsWith('/סנוז ')));
        assert.deepStrictEqual(s('/s מח').map(x=>x.insert),['/s מחר 09:00']);
        assert.deepStrictEqual(s('/s 3h').map(x=>x.insert),['/s 3h']);
        assert.deepStrictEqual(s('/s 2h').map(x=>x.insert),['/s 2h']);
        assert.deepStrictEqual(s('/s 1').map(x=>x.insert),['/s 12h']);
        assert.deepStrictEqual(s('/s someday'),[]);
        // on and off
        assert.deepStrictEqual(s('/דחוף ').map(x=>[x.insert,!!x.now,x.go]),[['/דחוף on',true,true],['/דחוף off',false,true]]);
        assert.deepStrictEqual(s('/mute ל').map(x=>x.insert),['/mute לא']);
        assert.deepStrictEqual(s('/mute o').map(x=>x.insert),['/mute on','/mute off']);
        // the thread's tasks (not the archived ones), then their states, then their words
        assert.deepStrictEqual(s('/task ').map(x=>[x.label,x.insert,x.go]),[['#1 Write docs','/task 1 ',false],['#2 Ship','/task 2 ',false]]);
        assert.deepStrictEqual(s('/משימה 2').map(x=>x.insert),['/משימה 2 ']);
        const states=s('/task 1 ');
        assert.ok(states.some(x=>x.insert==='/task 1 בוצע'&&x.go)&&states.some(x=>x.insert==='/task 1 = Write docs'&&!x.go),JSON.stringify(states));
        assert.ok(states.filter(x=>!x.insert.includes('=')).every(x=>parseSlash(x.insert,{now:NOW,thread:t}).args.action==='state'));
        assert.deepStrictEqual(s('/task 1 =').map(x=>x.insert),['/task 1 = Write docs']);
        assert.deepStrictEqual(s('/task Write th'),[]);                                  // the words of a new task: nothing to offer
        // /merge: the thread's open pull requests (number, title, base, checks), then the branches to merge into
        const prs=s('/merge ');
        assert.deepStrictEqual(prs.map(x=>x.insert),['/merge 12 ','/merge 30 ']);
        assert.ok(prs[0].label.includes('#12')&&prs[0].label.includes('Fix the cache')&&prs[0].hint.includes('main')&&prs[0].hint.includes(PR_CI.pass),JSON.stringify(prs[0]));
        assert.deepStrictEqual(s('/merge 3').map(x=>x.insert),['/merge 30 ']);
        assert.deepStrictEqual(s('/merge 30 ').map(x=>x.insert),['/merge 30 release','/merge 30 main']);
        assert.deepStrictEqual(s('/merge 12 ').map(x=>x.insert),['/merge 12 main','/merge 12 release']);
        assert.deepStrictEqual(slashSuggest('/merge ',{now:NOW,thread:t,links:{}}),[]);
        """)

    def test_the_help_and_the_last_run_block(self):
        self.pure_js(self.NOW + r"""
        const help=slashHelp();
        assert.strictEqual(help.length,12);                 // the first round: what works now
        assert.ok(help[0].label.startsWith('/מצב')&&HEBREW.test(help[0].hint)&&help[0].en==='/status');
        const t={messages:[{id:'m1',from:'tower',text:'```\n! echo one\n```\n```\n! echo two\n```\n```\nnot a command\n```'},{id:'m2',from:'fork',text:'```\n! rm -rf /\n```'},{id:'m3',from:'owner',text:'ok'}]};
        assert.deepStrictEqual(lastRunBlock(t),{msg:'m1',index:1,command:'! echo two'});
        // only a block of the tower's newest message: one it spoke past ("do not run that") is not offered
        assert.strictEqual(lastRunBlock({messages:[...t.messages,{id:'m4',from:'tower',text:'אל תריץ את זה'}]}),null);
        assert.strictEqual(lastRunBlock({messages:[{id:'m1',from:'fork',text:'```\n! ls\n```'}]}),null);
        assert.strictEqual(lastRunBlock(null),null);
        """)

    def test_the_page_draws_the_list_in_the_reply_box(self):
        """The list itself (m651): a 30px row per command, six in sight, the keys in the thin row at the top."""
        page = self.page()
        self.assertIn('<div id="slash" class="slash" hidden></div>', page)
        self.assertIn('.sl-row{', page)
        self.assertRegex(page, r'\.sl-row\{[^}]*height:30px')
        self.assertRegex(page, r'\.sl-list\{[^}]*max-height:calc\(6 \* 30px')
        script = page.split('<script>')[-1]
        self.assertIn('if(slashKey(e))return;', script)          # the reply box's keys go to the list first while it is open
        self.assertIn('if(slashSubmit())return;', script)        # Enter on a whole command does it instead of sending it
        self.assertIn("state.command=", script)                  # and a command for the agents goes with its name


class BulkTests(unittest.TestCase):
    """Several threads chosen at once in the list, and one action for all of them (the owner, suda m644 and
    suda-fixes m50: "choose many chats and apply an action to them"). The choice itself is pure: a toggle, a
    range in the order the list shows, and what is left of it when the list is drawn again."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_a_thread_is_chosen_and_let_go_by_a_toggle(self):
        self.pure_js(r"""
        assert.deepStrictEqual(pickToggle([],'a'),['a']);
        assert.deepStrictEqual(pickToggle(['a','b'],'a'),['b']);
        assert.deepStrictEqual(pickToggle(['a'],'b'),['a','b'],'in the order he chose them');
        const was=['a'];pickToggle(was,'b');assert.deepStrictEqual(was,['a'],'a new choice, the old one untouched');
        // only an open thread of his: never the tower, never a closed or merged one, never one that is not there
        assert.strictEqual(pickable({id:'a',status:'open'}),true);
        assert.strictEqual(pickable({id:'a',status:'open',snooze:{until:9e9}}),true,'one asleep can be chosen too');
        assert.strictEqual(pickable({id:TOWER_ID,status:'open'}),false);
        assert.strictEqual(pickable({id:'a',status:'closed'}),false);
        assert.strictEqual(pickable({id:'a',status:'closed',merged_into:'b'}),false);
        assert.strictEqual(pickable(null),false);assert.strictEqual(pickable(undefined),false);
        """)

    def test_shift_chooses_the_range_between_the_last_one_and_this_one_in_the_order_shown(self):
        self.pure_js(r"""
        const order=['a','b','c','d','e'];
        assert.deepStrictEqual(pickRange(['b'],order,'b','d'),['b','c','d']);
        assert.deepStrictEqual(pickRange(['d'],order,'d','b'),['d','b','c'],'upwards too');
        assert.deepStrictEqual(pickRange(['a','e'],order,'e','c'),['a','e','c','d'],'what was chosen stays chosen');
        assert.deepStrictEqual(pickRange(['b'],order,'b','b'),['b']);
        // no anchor in the list (none yet, or its row is gone): only the row he pressed
        assert.deepStrictEqual(pickRange([],order,null,'c'),['c']);
        assert.deepStrictEqual(pickRange(['x'],order,'x','c'),['x','c']);
        // a row that is not in the list (a stale press) changes nothing
        assert.deepStrictEqual(pickRange(['a'],order,'a','zz'),['a']);
        """)

    def test_a_live_refresh_keeps_the_choice_and_drops_only_the_rows_that_went(self):
        self.pure_js(r"""
        const threads={a:{id:'a',status:'open'},b:{id:'b',status:'closed'},c:{id:'c',status:'open'},m:{id:'m',status:'closed',merged_into:'c'},[TOWER_ID]:{id:TOWER_ID,status:'open'}};
        assert.deepStrictEqual(pickPrune(['a','b','c','gone','m',TOWER_ID],threads),['a','c']);
        assert.deepStrictEqual(pickPrune([],threads),[]);
        // and only what the list shows now (another space): the caller says which
        assert.deepStrictEqual(pickPrune(['a','c'],threads,t=>t.id!=='a'),['c']);
        """)

    def test_what_an_action_on_many_says_when_it_is_done(self):
        self.pure_js(r"""
        assert.strictEqual(bulkSaid('close',3,[]),'3 נושאים נסגרו');
        assert.strictEqual(bulkSaid('close',1,[]),'נושא אחד נסגר');
        assert.strictEqual(bulkSaid('snooze',2,[],'מחר 09:00'),'נודניק ל-2 נושאים: חוזרים מחר 09:00');
        assert.strictEqual(bulkSaid('merge',2,[],'יעד'),'2 נושאים מוזגו לתוך «יעד»');
        assert.strictEqual(bulkSaid('reopen',2,[]),'2 נושאים נפתחו מחדש');
        // what the server refused is said with its reason, and stays chosen
        assert.strictEqual(bulkSaid('close',1,[{id:'b',title:'בית',why:'הגיעה הודעה חדשה'}]),'נושא אחד נסגר. «בית» לא: הגיעה הודעה חדשה');
        assert.strictEqual(bulkSaid('close',0,[{id:'a',title:'א',why:'x'},{id:'b',title:'ב',why:''}]),'לא נסגר אף נושא. «א» לא: x; «ב» לא: הפעולה לא בוצעה');
        """)

    def test_the_list_wires_the_choice_into_its_rows(self):
        page = self.page()
        row = page.split('function rowNode(t,slot,turn){')[1].split('\nfunction ')[0]
        self.assertIn("b.setAttribute('aria-selected'", row)
        self.assertIn("b.classList.toggle('picked'", row)
        self.assertIn('b.onclick=e=>rowClick(e,t.id);', row)
        # the phone's long press chooses; a mouse held on a row still renames it
        self.assertIn("heldRow={id:row.dataset.id,x:e.clientX,y:e.clientY,finger:e.pointerType!=='mouse'};", page)
        self.assertIn("if(heldRow.finger&&pickable(thread(heldRow.id))){bulkHold(heldRow.id);heldRow=null;return;}", page)
        # Esc lets go of the choice after every window above it has closed
        back = page.split('function stepBack(){')[1].split('\nfunction ')[0]
        self.assertLess(back.index('closeSwitcher()'), back.index('bulkEsc()'))
        # the help and Cmd+K say how
        self.assertIn('Choose several topics in the list', page.split('const SHORTCUTS=[')[1].split('];')[0])
        self.assertIn('bulkActions(add);', page.split('function actions(){')[1].split('\nfunction ')[0])
        self.assertIn("'bulk-help'", page.split('function bulkActions(add){')[1].split('\nfunction ')[0])
        # every action goes through the page's own ops, one request per thread, as for one thread
        bulk = page.split('// ── several threads at once: the list and its panel ──')[1].split('\n// ── ')[0]
        for op in ("op:'snooze'", "op:'close'", "op:'merge'", 'markSectionRead('):
            self.assertIn(op, bulk)


class SlowLinkTests(unittest.TestCase):
    """A slow link: heavy media waits for his tap (the owner, slow mode). The decision is pure and tested here."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_slow_link_is_decided_from_the_setting_the_browser_and_the_pages_own_reads(self):
        """The owner: "on a very slow link, diagrams may still load, but heavy things like images do not load by
        default; a 'tap to load' button instead". Slow is what the browser says (Save-Data, a 2G or 3G link), or the
        page's own reads of the summary and the whole thread being slow; it does not flap; his choice wins both ways."""
        self.pure_js(r"""
        const off={on:false,why:'',at:0},T=1000000;
        const S=(bytes,ms)=>({bytes,ms});
        // the three choices, kept per device; anything else is "auto"
        assert.deepStrictEqual(SLOW_CHOICES.map(([k])=>k),['auto','load','tap']);
        assert.strictEqual(slowChoice('tap'),'tap');assert.strictEqual(slowChoice('load'),'load');assert.strictEqual(slowChoice('x'),'auto');assert.strictEqual(slowChoice(null),'auto');
        // no information at all: media loads
        assert.strictEqual(slowLink('auto',null,[],off,T).on,false);assert.strictEqual(slowLink('auto',{},[],null,T).on,false);
        // the browser's own signals
        assert.deepStrictEqual(slowLink('auto',{saveData:true,effectiveType:'4g'},[],off,T),{on:true,why:'save-data',at:T});
        for(const type of ['slow-2g','2g','3g'])assert.deepStrictEqual(slowLink('auto',{effectiveType:type},[],off,T),{on:true,why:'type',at:T});
        assert.strictEqual(slowLink('auto',{effectiveType:'4g',saveData:false},[],off,T).on,false);
        // his choice beats every signal, both ways
        assert.strictEqual(slowLink('load',{saveData:true,effectiveType:'2g'},[S(100000,9000),S(100000,9000),S(100000,9000)],off,T).on,false);
        assert.deepStrictEqual(slowLink('tap',{effectiveType:'4g'},[],off,T),{on:true,why:'tap',at:T});
        // the page's own reads: the median of the last few; a small read says only how long it took
        const fast=[S(4000,80),S(60000,300),S(5000,90)],slowBig=[S(200000,6000),S(150000,5000),S(4000,200)],slowSmall=[S(3000,3500),S(3000,4200),S(3000,3100)];
        assert.strictEqual(slowLink('auto',{},fast,off,T).on,false);
        assert.deepStrictEqual(slowLink('auto',{},slowBig,off,T),{on:true,why:'measured',at:T});      // 33 KB/s on the big ones
        assert.deepStrictEqual(slowLink('auto',null,slowSmall,off,T),{on:true,why:'measured',at:T});  // over 3 s each
        assert.strictEqual(slowLink('auto',{},[S(3000,9000),S(3000,9000)],off,T).on,false);          // two reads are not enough to judge
        assert.strictEqual(slowLink('auto',{},[S(3000,400),S(3000,300),S(3000,500)],off,T).on,false); // small and quick: no speed is read from them
        // only the last few count
        assert.strictEqual(slowLink('auto',{},[...slowSmall,...fast,...fast],off,T).on,false);
        // hysteresis: once slow it stays so in the middle band, and for a minute at least after it is fast again
        const was=slowLink('auto',{},slowBig,off,T),mid=[S(100000,1000),S(100000,1100),S(100000,1000)];  // 100 KB/s, about 1 s
        assert.strictEqual(slowLink('auto',{},mid,off,T).on,false);                                      // not slow enough to turn on
        assert.deepStrictEqual(slowLink('auto',{},mid,was,T+SLOW_HOLD*5),was);                           // nor fast enough to turn off
        const quick=[S(300000,500),S(300000,400),S(300000,600)];
        assert.deepStrictEqual(slowLink('auto',{},quick,was,T+1000),was);                               // too soon
        assert.deepStrictEqual(slowLink('auto',{},quick,was,T+SLOW_HOLD),{on:false,why:'',at:T+SLOW_HOLD});
        // a link that swings between 3g and 4g does not turn the mode on and off with it
        const by3g=slowLink('auto',{effectiveType:'3g'},[],off,T);
        assert.strictEqual(slowLink('auto',{effectiveType:'4g'},[],by3g,T+5000).on,true);
        assert.strictEqual(slowLink('auto',{effectiveType:'4g'},[],by3g,T+SLOW_HOLD).on,false);
        assert.strictEqual(slowLink('auto',{effectiveType:'4g'},mid,by3g,T+SLOW_HOLD).on,true);          // the reads are not plainly fast
        // his own choice is not held: from "always tap" back to auto on a good link, media loads at once
        const tapped=slowLink('tap',{},[],off,T);
        assert.strictEqual(slowLink('auto',{effectiveType:'4g'},[],tapped,T+1).on,false);
        // staying on keeps the moment it turned on
        assert.strictEqual(slowLink('auto',{saveData:true},[],was,T+50).at,T);
        // what is measured: the page's own reads only, from the browser's resource timing
        const e=(name,o)=>Object.assign({name,transferSize:0,encodedBodySize:0,startTime:100,requestStart:0,responseEnd:0},o);
        assert.deepStrictEqual(linkSample(e('http://h/b/summary.json?t=1',{transferSize:5000,requestStart:200,responseEnd:700})),{bytes:5000,ms:500});
        assert.deepStrictEqual(linkSample(e('http://h/b/state.json?t=1',{encodedBodySize:9000,responseEnd:600})),{bytes:9000,ms:500});
        assert.deepStrictEqual(linkSample(e('http://h/b/full/a-b.json?t=2',{transferSize:80000,requestStart:150,responseEnd:1150})),{bytes:80000,ms:1000});
        for(const name of ['http://h/b/uploads/a/m1-1.png','http://h/b/live.json?t=1','http://h/b/diagram.html','http://h/b/drafts.json?t=1','http://h/b/x/summary.json.bak'])
          assert.strictEqual(linkSample(e(name,{transferSize:5000,responseEnd:900})),null,name);
        assert.strictEqual(linkSample(e('http://h/b/summary.json',{transferSize:0,responseEnd:900})),null);  // nothing came over the line
        assert.strictEqual(linkSample(e('http://h/b/summary.json',{transferSize:10})),null);                  // not finished
        assert.strictEqual(linkSample(null),null);assert.strictEqual(linkSample({}),null);
        """)

    def test_a_picture_with_a_small_copy_shows_it_and_opens_the_picture_itself(self):
        """suda-fixes task 31 (m120 #4, approved m130): the server keeps a small copy beside a big picture."""
        self.pure_js(r"""
        // the small copy is trusted only as the picture's own: same thread, same message and place, .thumb.jpg or .png
        assert.strictEqual(thumbFile({file:'uploads/t1/m4-1.thumb.jpg'},'uploads/t1/m4-1.png','t1'),'uploads/t1/m4-1.thumb.jpg');
        assert.strictEqual(thumbFile({file:'uploads/t1/m4-o2.thumb.png'},'uploads/t1/m4-o2.png','t1'),'uploads/t1/m4-o2.thumb.png');
        for(const bad of ['uploads/t2/m4-1.thumb.jpg','uploads/t1/m4-2.thumb.jpg','uploads/t1/m5-1.thumb.jpg','uploads/t1/m4-1.thumb.gif','uploads/t1/m4-1.thumb.jpg?x','../m4-1.thumb.jpg','uploads/t1/m4-1.jpg',7,null])
          assert.strictEqual(thumbFile({file:bad},'uploads/t1/m4-1.png','t1'),null,String(bad));
        assert.strictEqual(thumbFile(null,'uploads/t1/m4-1.png','t1'),null);assert.strictEqual(thumbFile('uploads/t1/m4-1.thumb.jpg','uploads/t1/m4-1.png','t1'),null);
        // a message: the small copy beside the picture, with its own size; none where the server kept none
        const m={images:[{file:'uploads/t1/m4-1.png',name:'a.png',w:2000,h:1000,bytes:900000,thumb:{file:'uploads/t1/m4-1.thumb.jpg',w:720,h:360,bytes:40000}},
                         {file:'uploads/t1/m4-2.jpg',w:10,h:5,thumb:{file:'uploads/t9/m4-2.thumb.jpg',bytes:1}}]};
        assert.deepStrictEqual(picturesOf(m,'t1'),[{src:'uploads/t1/m4-1.png',name:'a.png',w:2000,h:1000,caption:'',thumb:'uploads/t1/m4-1.thumb.jpg'},
                                                   {src:'uploads/t1/m4-2.jpg',name:'',w:10,h:5,caption:''}]);
        // its bytes are known by its own address (what a held tile says it costs)
        assert.deepStrictEqual([...mediaBytes(m,'t1')],[['uploads/t1/m4-1.png',900000],['uploads/t1/m4-1.thumb.jpg',40000]]);
        // the gallery: each picture with its small copy, to stand in until the picture itself is there
        assert.deepStrictEqual(galleryOf([{id:'m4',...m}],'t1').map(p=>[p.src,p.thumb||'']),[['uploads/t1/m4-1.png','uploads/t1/m4-1.thumb.jpg'],['uploads/t1/m4-2.jpg','']]);
        // the picture of an option too
        const q={option_images:{'א':{file:'uploads/t1/m5-o1.png',w:900,h:900,thumb:{file:'uploads/t1/m5-o1.thumb.jpg',w:720,h:720,bytes:30000}}}};
        assert.deepStrictEqual([...optionPics(q,'t1')],[['א',{src:'uploads/t1/m5-o1.png',w:900,h:900,thumb:'uploads/t1/m5-o1.thumb.jpg'}]]);
        """)

    def test_a_picture_sent_smaller_says_how_big_its_original_was(self):
        """m198: his page names the original's sides of a picture it sent smaller; the server keeps them."""
        self.pure_js(r"""
        assert.deepStrictEqual(picturesForSend([{name:'a.jpg',type:'image/jpeg',data:'AA',shrunk:{w:4000,h:3000}},{name:'b.jpg',type:'image/jpeg',data:'BB',shrunk:{w:'x',h:3}}]),
          [{name:'a.jpg',type:'image/jpeg',data:'AA',shrunk:{w:4000,h:3000}},{name:'b.jpg',type:'image/jpeg',data:'BB'}]);
        const m={images:[{file:'uploads/t1/m4-1.jpg',w:1280,h:960,shrunk:{w:4000,h:3000}},{file:'uploads/t1/m4-2.jpg',w:10,h:5,shrunk:{w:-1,h:3}}]};
        assert.deepStrictEqual(picturesOf(m,'t1').map(p=>p.shrunk||null),[{w:4000,h:3000},null]);
        """)

    def test_a_hebrew_comment_in_code_is_an_island_right_to_left_in_its_line(self):
        """suda-fixes 25 and 51: every line stays left to right (indentation, scrolling, trees); the Hebrew words of a
        comment read right to left. One function for Suda and the MD viewer (which takes Suda's pure section)."""
        self.pure_js(r"""
        const I=(p,a)=>codeIsland(p,a);
        assert.deepStrictEqual(I('    # בודקים את החיבור',true),{lead:'    ',rtl:'# בודקים את החיבור',tail:''});
        assert.deepStrictEqual(I('# הערה',false),{lead:'# ',rtl:'הערה',tail:''});
        assert.deepStrictEqual(I('/* הערה */',false),{lead:'/* ',rtl:'הערה',tail:' */'});          // its closing marker after its words
        assert.deepStrictEqual(I('#(הערה)',false),{lead:'#',rtl:'(הערה)',tail:''});                // a bracket closes on the words' far side
        assert.strictEqual(I('// Returns the user name (שם) or null',true),null);                 // English words first: no island
        assert.strictEqual(I(' * @param {string} name שם המשתמש',false),null);
        assert.strictEqual(I('# TODO תקן את זה',false),null);
        assert.deepStrictEqual(I(' * שורה באמצע',true),{lead:' * ',rtl:'שורה באמצע',tail:''});
        assert.strictEqual(I('# just English',true),null);assert.strictEqual(I('',true),null);
        for(const [p,a] of [['  -- הערה.  ',false],['/** שלום */',true],['#!שלום',true]]){const h=I(p,a);assert.strictEqual(h.lead+h.rtl+h.tail,p);}
        // a whole block: the pieces always add up to the code, and only Hebrew words are set apart
        const P=(code,lang)=>codePieces(code,lang),text=ps=>ps.map(p=>p.nl?'\n':p.k==='s'&&p.q?p.q+p.rtl+p.q:(p.lead||'')+(p.rtl||'')+(p.tail||'')+(p.t||'')).join('');
        const islands=ps=>ps.filter(p=>p.rtl!==undefined).map(p=>p.rtl);
        for(const [code,lang] of [['x = 1; /* הערה */ y = 2;','js'],['curl https://example.com/page#top # מוריד את הדף','sh'],
                                  ['// Returns the user name (שם) or null\n/**\n * @param {string} name שם המשתמש\n */','js'],['const a = ["שלום", "עולם"];','js'],
                                  ['def f():\n    # בודקים\n    return 1','python'],['├── src\n│   └── קובץ.py','']])
          assert.strictEqual(text(P(code,lang)),code,code);
        assert.deepStrictEqual(islands(P('x = 1; /* הערה */ y = 2;','js')),['הערה']);
        assert.deepStrictEqual(islands(P('curl https://example.com/page#top # מוריד את הדף','sh')),['מוריד את הדף']);   // a # inside a word is code
        assert.deepStrictEqual(islands(P('// Returns the user name (שם) or null\n/**\n * @param {string} name שם המשתמש\n */','js')),[]);
        assert.deepStrictEqual(P('const a = ["שלום", "עולם"];','js').filter(p=>p.k==='s').map(p=>[p.q,p.rtl]),[['"','שלום'],['"','עולם']]);   // each string its own island
        assert.deepStrictEqual(islands(P('├── src\n│   └── קובץ.py','')),[]);
        """)

    def test_the_md_viewer_draws_code_with_suda_s_own_island_logic(self):
        """suda-fixes 51: one source for code direction. The viewer takes codeIsland() and codePieces() from Suda's pure
        section (mdv/mdv/sync.py); it defines neither, and its codeNodes() is Suda's, character for character."""
        import re
        root = _paths.APP
        page = (root / 'suda.html').read_text(encoding='utf-8')
        pure = page.split('// <pure>', 1)[1].split('// </pure>', 1)[0]
        for name in ('codeIsland', 'codePieces'):
            self.assertIn('function %s(' % name, pure, name + ' is in the pure section the viewer takes')
            for f in ('mdv/static/mdv-pure.js', 'mdv/static/app.js'):
                self.assertNotRegex((root / f).read_text(encoding='utf-8'), r'function\s+%s\s*\(' % name, '%s defines its own %s' % (f, name))
        body = lambda text: re.search(r'function codeNodes\(code,lang\)\{\n[\s\S]*?\n\}\n', text).group(0)
        app = (root / 'mdv/static/app.js').read_text(encoding='utf-8')
        self.assertEqual(body(app), body(page), 'the two pages draw the pieces alike')
        self.assertEqual(len(re.findall(r'function\s+codeNodes\s*\(', app)), 1, 'no second codeNodes() in the viewer that would win silently')
        for name in ('codePieces', 'codeIsland', 'codeNodes'):
            self.assertNotRegex(app, r'(window\.)?%s\s*=' % name, 'nothing in the viewer replaces ' + name)
        helper = lambda text: re.search(r'^function el\(tag,cls,text\)\{.*\}$', text, re.M).group(0)
        self.assertEqual(helper(app), helper(page), 'the mapper builds its nodes with the same el() on both pages')

    def test_a_hebrew_line_of_steps_joined_by_arrows_reads_right_to_left(self):
        """suda-fixes 71 (m363, the text of m360): in a Hebrew message the steps 'A ← B ← C' read right to left even
        when they are English labels; each arrow stands between its steps (a mark of direction on each side), and a
        bracket around such a chain closes on the right side. English paragraphs, code and URLs are untouched."""
        self.pure_js(r"""
        const steps='github.com/udiNur/Suda ← Settings ← Pages ← Source: **Deploy from a branch** ← Branch **main**, תיקייה **/docs** ← Save.';
        assert.strictEqual(blockDir(steps),'rtl');
        assert.strictEqual(blockDir('github.com/settings/pages ← **Add a domain** ← getsuda.dev. GitHub ייתן רשומת TXT. מוסיפים אותה ב-Cloudflare (שלב 3), וחוזרים ל-**Verify**.'),'rtl');
        // the rule of suda m414 stays: an English line with one Hebrew word, an English mail, are English
        assert.strictEqual(blockDir('Please open the תיקייה folder and run the tests again'),'ltr');
        assert.strictEqual(blockDir('Settings -> Pages -> Save'),'ltr');
        assert.strictEqual(blockDir('Settings ← Pages ← Save'),'ltr');           // no Hebrew: an English line
        // the arrows of a right to left block get a mark of direction on each side, in its words only
        const R='\u200F';
        assert.strictEqual(rtlArrows('a ← b'),'a '+R+'←'+R+' b');
        assert.strictEqual(rtlArrows('<code>a ← b</code> ← <a href="x?←">c ← d</a>'),'<code>a ← b</code> '+R+'←'+R+' <a href="x?←">c '+R+'←'+R+' d</a>');
        assert.strictEqual(rtlArrows('no arrows'),'no arrows');
        // in a message: the line of steps is right to left with its marks; an English paragraph keeps ltr
        const html=markdown(steps+'\n\nPlease open the folder and run the tests again.');
        assert.ok(!/<p dir="ltr">github/.test(html),html);
        assert.ok(html.includes('Suda '+R+'←'+R+' Settings'),html);
        assert.ok(/<p( class="gap")? dir="ltr">Please open/.test(html),html);
        // what he copies has no marks
        assert.strictEqual(cleanCopy('a '+R+'←'+R+' b',false),'a ← b');
        """)

    def test_a_very_long_message_is_folded_from_the_threshold_he_chose(self):
        """suda-fixes 74 (suda-connectivity m3): only really long messages fold; the threshold is his, per device."""
        self.pure_js(r"""
        assert.strictEqual(longAtOf(null),3000);assert.strictEqual(longAtOf(''),3000);assert.strictEqual(longAtOf('abc'),3000);
        assert.strictEqual(longAtOf('1500'),1500);assert.strictEqual(longAtOf('6000'),6000);assert.strictEqual(longAtOf('0'),0);
        assert.strictEqual(longAtOf('2999'),3000);                      // only one of his choices
        assert.strictEqual(isLong('x'.repeat(2999),3000),false);assert.strictEqual(isLong('x'.repeat(3000),3000),true);
        assert.strictEqual(isLong('x'.repeat(90000),0),false);           // never
        assert.strictEqual(isLong(null,3000),false);
        """)

    def test_the_list_of_saved_messages_comes_from_the_summary_when_the_server_gives_it(self):
        """saved179 with the store: the summary's `saved` covers the threads closed long ago (no row there)."""
        self.pure_js(r"""
        const list=[{thread:'old',title:'ישן',msg:'m1',from:'tower',ts:5,saved:10,text:'רשימה'},{thread:'now',title:'x',msg:'m2',from:'fork',ts:6,saved:20,text:'b'},
                    {thread:'bad',msg:'m1'},null,{thread:'y',msg:3,saved:1}];
        const rows=savedFromSummary(list,id=>id==='now'?'פתוח עכשיו':null);
        assert.deepStrictEqual(rows.map(r=>[r.tid,r.mid,r.title,r.text]),[['now','m2','פתוח עכשיו','b'],['old','m1','ישן','רשימה']]);
        assert.deepStrictEqual(savedFromSummary(null),[]);
        """)

    def test_saved_messages_are_listed_from_every_thread_the_last_saved_first(self):
        """suda m787 (suda-fixes 77): a whole message or a stamp of one (with when it was saved and the start of its words)."""
        self.pure_js(r"""
        const cut=threadMessages([['m1','fork',10,'a'],['m2','fork',20,'b',99,'תחילת המילים'],['m3','fork',30,'c']],[{id:'m3',v:'c',text:'שלמה',saved:50}]);
        assert.deepStrictEqual(cut.messages.map(m=>[m.id,m.saved||null,m.savedText||null]),[['m1',null,null],['m2',99,'תחילת המילים'],['m3',50,null]]);
        const rows=savedOf([{id:'a',title:'נושא א',messages:cut.messages},{id:'b',title:'נושא ב',messages:[{id:'m1',from:'tower',ts:5,text:'x',saved:120}]},null,{id:'c'}]);
        assert.deepStrictEqual(rows.map(r=>[r.tid,r.mid,r.text]),[['b','m1','x'],['a','m2','תחילת המילים'],['a','m3','שלמה']]);
        assert.deepStrictEqual(savedOf(null),[]);
        """)

    def test_a_held_picture_or_video_says_what_it_is_and_how_big(self):
        self.pure_js(r"""
        // its size, as known: the picture's sides and bytes; a video's length and bytes
        assert.strictEqual(mediaSize({w:1600,h:900,bytes:240000}),'1600×900 · 240KB');
        assert.strictEqual(mediaSize({w:1600,h:900,bytes:2400000,seconds:75}),'1:15 · 1600×900 · 2.4MB');
        assert.strictEqual(mediaSize({w:0,h:0,bytes:0}),'');assert.strictEqual(mediaSize({}),'');assert.strictEqual(mediaSize({bytes:900}),'900 בתים');
        // the bytes of each stored file of a message, by its address (only this thread's own files)
        const m={images:[{file:'uploads/t1/m4-1.jpg',bytes:1200},{file:'uploads/x/m4-2.jpg',bytes:5},null],videos:[{file:'uploads/t1/m4-v1.mp4',bytes:900000},{file:'/etc/passwd',bytes:1}]};
        assert.deepStrictEqual([...mediaBytes(m,'t1')],[['uploads/t1/m4-1.jpg',1200],['uploads/t1/m4-v1.mp4',900000]]);
        assert.deepStrictEqual([...mediaBytes(null,'t1')],[]);assert.deepStrictEqual([...mediaBytes({images:'x'},'t1')],[]);
        // the thread a stored file belongs to ("load all in the thread")
        assert.strictEqual(mediaThread('uploads/t1/m4-1.jpg'),'t1');assert.strictEqual(mediaThread('uploads/a-b/m4-v1.mp4?again=2'),'a-b');
        assert.strictEqual(mediaThread('blob:x'),'');assert.strictEqual(mediaThread(''),'');assert.strictEqual(mediaThread(null),'');
        // what the settings say about the mode, and why it is on
        assert.ok(slowWords({on:true,why:'tap'}).startsWith('קליטה איטית: מדיה בלחיצה'));
        for(const why of ['save-data','type','measured','tap'])assert.notStrictEqual(slowWords({on:true,why}),slowWords({on:true,why:'other'}),why);
        assert.ok(!slowWords({on:false,why:''}).includes('בלחיצה'));
        """)

    def test_heavy_media_goes_through_the_hold_and_diagrams_do_not(self):
        """Every place a picture or a video of a thread is drawn asks holdMedia first: the message's pictures, a
        carousel's slides, the gallery's pages, an option's picture, the tiles of a question, and the videos. A
        voice message keeps preload=none (its own player reads the audio only on play); a diagram is drawn as before."""
        page = self.page()
        script = page.split('<script>')[1]
        for part in ("const held=holdMedia(small,{w:pic.w,h:pic.h,bytes:sizes.get(small),name:img.alt},()=>{img.hidden=false;img.src=small;open.setAttribute('aria-label',seeing);if(hd)hd.hidden=false;},true);",   # a message's pictures (its small copy when it has one)
                     "holdMedia(small,{w:pic.w,h:pic.h,name:img.alt},()=>{img.hidden=false;img.src=small;})",                                                    # a slide
                     "holdMedia(first,{w:pic.w,h:pic.h,name:img.alt},()=>{img.hidden=false;img.src=first;})",                                                    # a gallery page
                     "holdMedia(clip.src,{kind:'video',ratio:clip.ratio,bytes,seconds:clip.seconds,name:clip.caption||clip.name},",                 # a video and its poster
                     "audio.preload='none';", "if(!audio.src)audio.src=src;"):
            self.assertTrue(part in script, part)
        self.assertGreaterEqual(script.count('holdMedia('), 7)
        self.assertNotIn('holdMedia', script.split('function drawDiagrams')[1].split('\nfunction ')[0])
        # the setting: three choices, per device, in the settings and in Cmd+K; "load all" in the thread
        for part in ("store.set('slow-media',", "'slow:'+key", "'slow-load-all'", "block(tr('Pictures and videos'),", "tr('Load all in this thread')", "new PerformanceObserver("):
            self.assertTrue(part in script, part)


class BadLinkTests(unittest.TestCase):
    """A bad link that is not 2G (suda-fixes 20, the owner's m59): in a restaurant his speed test said latency 84 ms
    idle and 952 ms under load (jitter 676), 1.75 Mbps down, 0.2 Mbps up, no loss. The mode that only read download
    speed stayed off there. The page now also reads the time to the first byte of its own small reads, how late the
    server's heartbeat comes against its 10 s rhythm, and how fast his own uploads go; with hysteresis, and a hold
    that grows when the link swings, so it does not flap. No request is added to measure."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_his_restaurant_numbers_turn_it_on_and_say_why(self):
        self.pure_js(r"""
        const T=10000000,off={on:false,why:'',at:0},S=(bytes,ms)=>({bytes,ms});
        // his downloads: 1.75 Mbps is about 218 KB/s; a 200 KB read takes a second of transfer plus the wait
        const reads=[S(4000,1000),S(200000,1900),S(6000,300),S(180000,1700),S(5000,1100)];
        // what the old decision makes of them: off (this is what happened in the restaurant)
        assert.strictEqual(slowLink('auto',{effectiveType:'4g'},reads,off,T).on,false);
        // the time to the first byte of the page's small reads: 84 ms idle, 952 +- 676 ms while something else loads
        const waits=[84,952,110,1628,952,276];
        const byWait=linkState('auto',{effectiveType:'4g'},{reads,waits},off,T);
        assert.strictEqual(byWait.on,true,JSON.stringify(byWait));assert.strictEqual(byWait.why,'wait');assert.deepStrictEqual(byWait.whys,['wait']);
        // his upload: a picture of 300 KB at 0.2 Mbps (25 KB/s) took 12 s to go up
        const ups=[{bytes:300000,ms:12000,t:T-1000}];
        const byUp=linkState('auto',{effectiveType:'4g'},{reads,ups},off,T);
        assert.strictEqual(byUp.on,true,JSON.stringify(byUp));assert.strictEqual(byUp.why,'up');assert.strictEqual(byUp.up,true);
        // the heartbeat, every 10 s from the server (and up to a second later, it looks once a second), comes late
        const beats=[10000,12900,9300,11000,13200,8800];
        const byBeat=linkState('auto',{effectiveType:'4g'},{reads,beats},off,T);
        assert.strictEqual(byBeat.on,true,JSON.stringify(byBeat));assert.strictEqual(byBeat.why,'beat');
        // all of it together: every reason is named, the first one leads
        const all=linkState('auto',{effectiveType:'4g'},{reads,waits,beats,ups},off,T);
        assert.deepStrictEqual(all.whys,['wait','beat','up']);assert.strictEqual(all.why,'wait');assert.strictEqual(all.at,T);
        // and what he is told
        assert.match(slowWords(all),/השהיה גבוהה/);assert.match(slowWords(all),/העלאה איטית/);assert.match(slowWords(all),/מוקטנות/);
        assert.match(slowMarkText(byWait),/השהיה גבוהה/);assert.match(slowMarkText(byUp),/העלאה איטית/);
        assert.strictEqual(slowMarkText({on:true,why:'tap',whys:['tap']}),'קליטה איטית: מדיה בלחיצה');
        // his choice still wins both ways
        assert.strictEqual(linkState('load',{},{reads,waits,beats,ups},off,T).on,false);
        assert.strictEqual(linkState('tap',{},{},off,T).why,'tap');
        """)

    def test_a_good_link_stays_off_even_with_a_hiccup(self):
        self.pure_js(r"""
        const T=10000000,off={on:false,why:'',at:0},S=(bytes,ms)=>({bytes,ms});
        const reads=[S(4000,40),S(200000,120),S(6000,30)],waits=[20,30,25,40,35,28],beats=[10000,10400,10900,10200,10050,10600];
        const ups=[{bytes:300000,ms:200,t:T-1000}];
        const got=linkState('auto',{effectiveType:'4g'},{reads,waits,beats,ups},off,T);
        assert.strictEqual(got.on,false,JSON.stringify(got));assert.strictEqual(got.up,false);assert.deepStrictEqual(got.whys,[]);
        // one or two slow answers (the server busy for a moment) are not a slow link
        assert.strictEqual(linkState('auto',{},{waits:[30,30,1500,30,30,30]},off,T).on,false);
        assert.strictEqual(linkState('auto',{},{waits:[30,2400,1500,30,30,30]},off,T).on,false);
        // one late heartbeat (the laptop busy) is not either
        assert.strictEqual(linkState('auto',{},{beats:[10000,10100,16000,10300,10000,10100]},off,T).on,false);
        // too few to judge
        assert.strictEqual(linkState('auto',{},{waits:[900,900]},off,T).on,false);
        // a picture of 120 KB on a good line, with a server that took 2 s to store it, is not a slow upload
        assert.strictEqual(linkState('auto',{},{ups:[upSample(120000,upTime(2100,[]),T)]},off,T).on,false);
        // an upload is judged only while it is fresh: a slow one from half an hour ago says nothing now
        assert.strictEqual(linkState('auto',{},{ups:[{bytes:300000,ms:12000,t:T-30*60000}]},off,T).on,false);
        // a small body says nothing of the speed
        assert.strictEqual(linkState('auto',{},{ups:[{bytes:2000,ms:2000,t:T}]},off,T).on,false);
        // the old API is the same as before
        assert.deepStrictEqual(slowLink('auto',{saveData:true},[],off,T),{on:true,why:'save-data',at:T});
        """)

    def test_it_does_not_flap(self):
        self.pure_js(r"""
        const T=10000000,off={on:false,why:'',at:0};
        const high=[900,1200,80,1500,950,90],calm=[60,80,70,90,85,75],mid=[400,800,300,900,500,450];
        // the middle band keeps what was: on stays on, off stays off
        const on=linkState('auto',{},{waits:high},off,T);
        assert.strictEqual(linkState('auto',{},{waits:mid},on,T+SLOW_HOLD*20).on,true);
        assert.strictEqual(linkState('auto',{},{waits:mid},off,T).on,false);
        // calm turns it off, but not before the hold, counted from the last moment it was slow; a hold of latency is
        // the long one (what made it calm may be the mode itself: the media waits, the line is idle)
        assert.strictEqual(on.slowAt,T);
        assert.strictEqual(linkState('auto',{},{waits:calm},on,T+SLOW_HOLD).on,true);
        const still=linkState('auto',{},{waits:high},on,T+WAIT_HOLD-1000);
        assert.strictEqual(still.slowAt,T+WAIT_HOLD-1000);
        assert.strictEqual(linkState('auto',{},{waits:calm},still,T+WAIT_HOLD).on,true,'slow a moment ago: held from then');
        const offAgain=linkState('auto',{},{waits:calm},on,T+WAIT_HOLD);
        assert.strictEqual(offAgain.on,false);assert.strictEqual(offAgain.offAt,T+WAIT_HOLD);
        // a link that swings every 30 s between loaded and idle, for half an hour: the hold grows each time it comes
        // back soon, so it turns a few times, not 60
        let s=off,turns=0,lastFlip=T,stretches=[];
        for(let t=T;t<T+30*60000;t+=5000){
          const loaded=Math.floor((t-T)/30000)%2===0;
          const next=linkState('auto',{},{waits:loaded?high:calm},s,t);
          if(next.on!==s.on){turns++;if(!next.on)stretches.push(t-lastFlip);lastFlip=t;}
          s=next;
        }
        assert.ok(turns<=9,'turned '+turns+' times');
        for(let i=1;i<stretches.length;i++)assert.ok(stretches[i]>=stretches[i-1],'the time on grows: '+stretches);
        // a link that stays bad turns on once
        let b=off,bt=0;for(let t=T;t<T+30*60000;t+=5000){const n=linkState('auto',{},{waits:high},b,t);if(n.on!==b.on)bt++;b=n;}
        assert.strictEqual(bt,1);
        // and after a long good stretch the hold is the short one again
        const later=linkState('auto',{},{waits:high},{...s,on:false,offAt:T,holds:4},T+60*60000);
        assert.strictEqual(later.holds,0);
        const soon=linkState('auto',{},{waits:high},{on:false,why:'',at:T,offAt:T,holds:1},T+60000);
        assert.strictEqual(soon.holds,2);
        assert.strictEqual(slowHold(0),SLOW_HOLD);assert.strictEqual(slowHold(1),SLOW_HOLD*2);assert.strictEqual(slowHold(20),SLOW_HOLD_MAX);
        assert.strictEqual(slowHold(0,['wait']),WAIT_HOLD);assert.strictEqual(slowHold(1,['up','beat']),WAIT_HOLD*2);assert.strictEqual(slowHold(5,['wait']),SLOW_HOLD_MAX);
        assert.strictEqual(slowHold(0,['up']),SLOW_HOLD);
        // a heartbeat-only and an upload-only mode turn off too, when their measure is calm again
        const beatOn=linkState('auto',{},{beats:[10000,13000,10000,13500,10000,10000]},off,T);
        assert.strictEqual(beatOn.on,true);
        assert.strictEqual(linkState('auto',{},{beats:[10000,10200,10400,10100,10000,10300]},beatOn,T+WAIT_HOLD).on,false);
        const upOn=linkState('auto',{},{ups:[{bytes:300000,ms:12000,t:T}]},off,T);
        assert.strictEqual(linkState('auto',{},{ups:[{bytes:300000,ms:12000,t:T},{bytes:300000,ms:3750,t:T+1000}]},upOn,T+SLOW_HOLD).on,true,'80 KB/s: not fast enough to call it over');
        const upOff=linkState('auto',{},{ups:[{bytes:300000,ms:12000,t:T},{bytes:300000,ms:900,t:T+1000},{bytes:300000,ms:800,t:T+2000}]},upOn,T+SLOW_HOLD);
        assert.strictEqual(upOff.on,false);assert.strictEqual(upOff.up,false);
        """)

    def test_what_is_measured_and_from_where(self):
        self.pure_js(r"""
        const e=(name,o)=>Object.assign({name,transferSize:0,encodedBodySize:0,startTime:100,requestStart:0,responseStart:0,responseEnd:0},o);
        // how long the page's own small reads take, from the request to the last byte: for a few hundred bytes (a
        // change file) that is the latency, whether it shows before the first byte or after it (Chrome's emulation,
        // a service worker in the way)
        assert.strictEqual(waitSample(e('http://h/b/changes/12.json?t=3',{transferSize:900,requestStart:200,responseStart:1150,responseEnd:1160})),960);
        assert.strictEqual(waitSample(e('http://h/b/changes/12.json?t=3',{transferSize:900,requestStart:200,responseStart:205,responseEnd:1160})),960);
        assert.strictEqual(waitSample(e('http://h/b/summary.json?t=1',{transferSize:5000,requestStart:200,responseStart:290,responseEnd:700})),500);
        // a big read's time is its transfer: it says how fast, not how late (the old measure reads it)
        assert.strictEqual(waitSample(e('http://h/b/full/a-b.json?t=2',{transferSize:80000,requestStart:150,responseStart:400,responseEnd:1150})),null);
        // from the browser's cache, or not the board's reads, or not finished: nothing
        assert.strictEqual(waitSample(e('http://h/b/changes/12.json',{transferSize:0,encodedBodySize:900,requestStart:200,responseStart:201,responseEnd:202})),null);
        for(const name of ['http://h/b/uploads/a/m1-1.png','http://h/api/state','http://h/b/events?since=3','http://h/b/diagram.html','http://h/b/changes/x.json','http://h/b/changes.json'])
          assert.strictEqual(waitSample(e(name,{transferSize:500,requestStart:100,responseStart:900,responseEnd:950})),null,name);
        assert.strictEqual(waitSample(e('http://h/b/changes/12.json',{transferSize:900,requestStart:200})),null);
        assert.strictEqual(waitSample(null),null);
        // across a stretch the page was away: nothing
        assert.strictEqual(waitSample(e('http://h/b/changes/12.json',{transferSize:900,requestStart:200,responseStart:5000,responseEnd:5001}),[[300,4000]]),null);
        // the change files are reads of the board too, for the old measure
        assert.deepStrictEqual(linkSample(e('http://h/b/changes/7.json?t=3',{transferSize:900,requestStart:200,responseEnd:1200})),{bytes:900,ms:1000});
        // the heartbeat: the time since the one before, unless the page was away in between or there was none
        assert.strictEqual(beatGap(1000,11500,[]),10500);assert.strictEqual(beatGap(null,11500,[]),null);
        assert.strictEqual(beatGap(1000,11500,[[3000,4000]]),null);assert.strictEqual(beatGap(1000,11500,[[200,900]]),10500);
        assert.strictEqual(beatGap(1000,1000+BEAT_LOST+1,[]),null,'a line that stood still that long is another matter (the header says so)');
        // an upload: its body over the time it took to go up; a small one is not a sample
        assert.deepStrictEqual(upSample(300000,12000,5),{bytes:300000,ms:12000,t:5});
        assert.strictEqual(upSample(2000,900,5),null);assert.strictEqual(upSample(300000,0,5),null);
        // the time it took to go up: until the server answered, less what a small send of his takes (the line's wait
        // and the server's own work), not until the browser handed the last byte to its socket (the phone's send
        // buffer takes a whole picture at once)
        assert.strictEqual(upTime(12000,[1100,900,1000]),11000);
        assert.strictEqual(upTime(12000,[]),12000-SERVER_GUESS,'no small send yet: the server is guessed at a second');
        assert.strictEqual(upTime(300,[1100,900,1000]),UP_FLOOR,'quicker than a small one: as quick as can be told');
        assert.strictEqual(upTime(0,[]),0);assert.strictEqual(upTime(NaN,[]),0);
        """)

    def test_pictures_shrink_harder_on_a_slow_link_and_hardest_on_a_slow_upload(self):
        self.pure_js(r"""
        assert.deepStrictEqual(shrinkPlan({on:false}),{side:1600,quality:0.82});
        assert.deepStrictEqual(shrinkPlan(null),{side:1600,quality:0.82});
        assert.deepStrictEqual(shrinkPlan({on:true,why:'wait'}),{side:1280,quality:0.7});
        assert.deepStrictEqual(shrinkPlan({on:true,why:'up',up:true}),{side:1024,quality:0.6});
        assert.deepStrictEqual(shrinkPlan({on:false,up:true}),{side:1024,quality:0.6});
        // "always load" is about what comes down, not what he sends: a measured slow upload still shrinks
        """)

    def test_his_pictures_go_full_size_when_he_says_so(self):
        """The owner (suda-fixes m195): "let me choose, but by default what I chose". A setting on this device:
        his own pictures go as on a good link (no slow-link shrink) even on a slow upload. Unset, it follows his
        choice for media: "always load" means full size too; "auto" and "always tap" keep the shrink."""
        self.pure_js(r"""
        assert.strictEqual(ownFull(null,'load'),true);assert.strictEqual(ownFull(null,'auto'),false);assert.strictEqual(ownFull(null,'tap'),false);
        assert.strictEqual(ownFull('on','auto'),true);assert.strictEqual(ownFull('off','load'),false);
        assert.strictEqual(ownFull('x','load'),true,'anything else: the default');assert.strictEqual(ownFull(undefined,undefined),false);
        const slowUp={on:true,why:'up',up:true};
        assert.deepStrictEqual(shrinkPlan(slowUp,true),{side:PICTURE_SIDE,quality:0.82});
        assert.deepStrictEqual(shrinkPlan({on:true,why:'wait'},true),{side:PICTURE_SIDE,quality:0.82});
        assert.deepStrictEqual(shrinkPlan(slowUp,false),{side:1024,quality:0.6});
        assert.deepStrictEqual(shrinkPlan(slowUp),{side:1024,quality:0.6});
        // and the settings do not say his pictures are shrunk when they are not
        assert.ok(!/מוקטנות/.test(slowWords(slowUp,true)),slowWords(slowUp,true));assert.match(slowWords(slowUp,false),/מוקטנות/);
        """)

    def test_a_picture_sent_smaller_says_how_big_the_original_was(self):
        """The owner (m198): a picture shown at reduced quality can be upgraded to full, later too. One the page sent
        smaller has no full copy on the server: the page says the original's sides (images[].shrunk = {w, h}, the
        field of hd160, which keeps it and says "full quality was not sent" instead of a dead button)."""
        self.pure_js(r"""
        const p={name:'a.jpg',type:'image/jpeg',data:'AAAA',caption:'',w:1280,h:853,bytes:4};
        assert.deepStrictEqual(picturesForSend([{...p,shrunk:{w:1920,h:1280}}])[0],{name:'a.jpg',type:'image/jpeg',data:'AAAA',shrunk:{w:1920,h:1280}});
        assert.deepStrictEqual(picturesForSend([p])[0],{name:'a.jpg',type:'image/jpeg',data:'AAAA'});
        for(const bad of [null,{w:0,h:5},{w:1.5,h:2},{w:'9',h:9},'x',{w:-1,h:3}])assert.strictEqual(sidesOf(bad),null,JSON.stringify(bad));
        assert.deepStrictEqual(sidesOf({w:3,h:4,x:1}),{w:3,h:4});
        """)

    def test_a_big_send_is_cut_only_when_nothing_moves(self):
        self.pure_js(r"""
        // a small one: as before
        assert.strictEqual(sendDeadline(2000,0,0),SEND_LIMIT);
        // a big one: its own time, and while it still moves, SEND_LIMIT after the last step of progress
        assert.strictEqual(sendDeadline(400000,0,0),sendLimit(400000));
        assert.strictEqual(sendDeadline(400000,0,100000),100000+SEND_LIMIT);
        assert.strictEqual(sendDeadline(400000,0,SEND_LIMIT_MAX*2),SEND_LIMIT_MAX*2+SEND_LIMIT,'one that still moves is never cut');
        assert.strictEqual(sendDeadline(50000000,0,0),SEND_LIMIT_MAX,'one that never moved: its own time, at most the most');
        """)

    def test_the_line_under_his_message_says_honestly_what_waits(self):
        self.pure_js(r"""
        assert.strictEqual(deliveryLine({delivery:'sending',sent:[120000,300000]}),'שולח… 40% (120KB מתוך 300KB)');
        assert.strictEqual(deliveryLine({delivery:'sending',tries:1,sent:[0,300000]}),'שולח שוב… 0% (0 בתים מתוך 300KB)');
        // all of it handed to the network is not all of it on the server: on 0.2 Mbps the phone's send buffer holds
        // a whole picture, and it says so
        assert.strictEqual(deliveryLine({delivery:'sending',sent:[300000,300000]}),'נמסר לרשת. מחכה לאישור מהשרת…');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0,behind:true}),'ממתין לשליחה: יישלח אחרי ההודעה הקודמת');
        // what was before stays
        assert.strictEqual(deliveryLine({delivery:'sending'}),'שולח…');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0}),'עוד לא נשלח. נשלח לבד בעוד רגע');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:1,behind:true}),deliveryLine({delivery:'waiting',tries:1}),'once tried, it says why it waits');
        """)


class KeptOnTheDeviceTests(unittest.TestCase):
    """The page and the diagram library kept on the phone (suda-fixes 30, the owner's m130)."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_the_build_check_and_the_library_are_named_by_date_and_version(self):
        self.pure_js(r"""
        assert.strictEqual(sinceOf(1795132528),new Date(1795132528000).toUTCString());
        assert.match(sinceOf(1795132528),/GMT$/);
        assert.strictEqual(sinceOf(0),'');assert.strictEqual(sinceOf(NaN),'');assert.strictEqual(sinceOf(undefined),'');
        assert.strictEqual(stampOf(sinceOf(1795132528)),1795132528,'the server reads back the date it wrote');
        assert.strictEqual(vendorCache('12.3.0'),'suda-vendor-12.3.0-'+MERMAID_SHA.slice(0,12));
        assert.deepStrictEqual(staleVendor(['suda-shell-1','suda-vendor-11.0.0',vendorCache('12.3.0'),'suda-vendor-12.3.0','other',7],'12.3.0'),['suda-vendor-11.0.0','suda-vendor-12.3.0']);
        assert.strictEqual(hexOf(new Uint8Array([0,15,255]).buffer),'000fff');
        assert.deepStrictEqual(staleVendor(null,'12.3.0'),[]);
        """)

    def test_the_library_version_is_the_one_in_vendor(self):
        """A new mermaid in vendor/ must be read again: the page's version names its cache."""
        readme = (ROOT / 'vendor' / 'README').read_text(encoding='utf-8')
        version = re.match(r'mermaid (\S+),', readme).group(1)
        self.assertIn("MERMAID_V='%s'" % version, self.page())
        # and the file's own hash: what is not this file is never kept (a reading cut short by an install)
        import hashlib
        sha = re.search(r'file sha256 ([0-9a-f]{64})', readme).group(1)
        self.assertEqual(hashlib.sha256((ROOT / 'vendor' / 'mermaid.min.js').read_bytes()).hexdigest(), sha)
        self.assertIn("MERMAID_SHA='%s'" % sha, self.page())

    def test_the_worker_asks_with_a_date_only_when_no_write_can_hide_behind_it(self):
        """The worker's reading of the page carries If-Modified-Since only for a kept copy read 2 s or more after its
        Last-Modified (whole seconds): an install still writing it in that second would be answered 304 for good."""
        sw = (ROOT / 'sw.js').read_text(encoding='utf-8')
        pure = sw.split('// <pure>')[1].split('// </pure>')[0]
        script = r"""
        const LM='Fri, 20 Nov 2026 01:00:00 GMT',LATER='Fri, 20 Nov 2026 01:00:05 GMT',SAME='Fri, 20 Nov 2026 01:00:01 GMT';
        assert.strictEqual(askSince('',LM,LATER),LM);
        assert.strictEqual(askSince('',LM,SAME),'','read within a second or two of its writing: read it whole');
        assert.strictEqual(askSince('',LM,null),'');assert.strictEqual(askSince('',null,null),'');assert.strictEqual(askSince('','x','y'),'');
        // the page's own date: as it is, unless it is the kept copy's own and that one cannot be trusted
        assert.strictEqual(askSince(LM,LM,LATER),LM);assert.strictEqual(askSince(LM,LM,SAME),'');
        assert.strictEqual(askSince(LM,null,null),LM);assert.strictEqual(askSince(LATER,LM,SAME),LATER);
        """
        r = subprocess.run([self.node(), '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_frame_is_given_the_library(self):
        frame = (ROOT / 'diagram.html').read_text(encoding='utf-8')
        self.assertNotIn('<script src="vendor/mermaid.min.js"></script>', frame)
        self.assertIn("if(location.hash==='#given'&&self.origin==='null'&&home&&home!=='null'){", frame)      # only sandboxed: no origin of its own
        self.assertIn("event.origin!==home", frame)                                                       # and from the board's own address
        self.assertIn("script.src='vendor/mermaid.min.js';script.onload=ready;", frame)       # (board.html: no #given)
        self.assertIn("event.source!==parent", frame.split("location.hash==='#given'")[1])
        self.assertIn("frame.src='diagram.html#given'", self.page())
        self.assertFalse((ROOT / 'board.html').exists(), 'board.html is gone from the product (suda m620)')
        # the page's check for a newer build is one request, with the build's date, never a HEAD
        page = self.page()
        self.assertNotIn("method:'HEAD'", page)
        self.assertIn("'If-Modified-Since':since", page)
        worker = (ROOT / 'sw.js').read_text(encoding='utf-8')
        self.assertIn("headers:{'If-Modified-Since':date}", worker)


class TaskHistoryTests(unittest.TestCase):
    """The history of a task (suda-fixes task 34, m151/m153)."""
    page = SlackPageTests.page
    node = SlackPageTests.node
    pure_js = SlackPageTests.pure_js

    def test_a_task_tells_when_its_last_thing_happened_and_what_each_event_was(self):
        """Each task in a thread shows when its last thing happened (as the list rows do), and an arrow opens its
        own history: created, every status change and by whom, its words corrected, moved in a merge, archived."""
        self.pure_js(r"""
        // the last event: from the thread's file (all events) or the summary (only the last one); else its last change
        assert.deepStrictEqual(taskLast({events:[{ts:5,kind:'created'},{ts:9,kind:'status',from:'todo',to:'done'}]}),{ts:9,kind:'status',from:'todo',to:'done'});
        assert.deepStrictEqual(taskLast({last:{ts:7,kind:'archived'}}),{ts:7,kind:'archived'});
        assert.strictEqual(taskLast({}),null);assert.strictEqual(taskLast(null),null);
        assert.strictEqual(taskLastAt({last:{ts:7,kind:'archived'},updated:3}),7);
        assert.strictEqual(taskLastAt({updated:3}),3,'an old task: its last change');
        assert.strictEqual(taskLastAt({}),0);
        // damaged events are dropped, never thrown on
        assert.deepStrictEqual(taskEventsOf([null,7,{ts:'x',kind:'created'},{ts:4,kind:'nonsense'},{ts:4,kind:'created'}]),[{ts:4,kind:'created'}]);
        assert.deepStrictEqual(taskEventsOf('x'),[]);
        assert.strictEqual(taskLast({events:'x',last:{ts:2,kind:'text'}}).kind,'text');
        // what each event says
        assert.strictEqual(taskEventWords({kind:'created'}),'נוצרה');
        assert.strictEqual(taskEventWords({kind:'status',from:'todo',to:'building'}),'לביצוע ← בבנייה');
        assert.strictEqual(taskEventWords({kind:'status',to:'done'}),'סומנה: הושלם','a derived one: what it was before is not known');
        assert.strictEqual(taskEventWords({kind:'text',from:'א',to:'ב'}),'הנוסח תוקן');
        assert.strictEqual(taskEventWords({kind:'owner',from:'fork',to:'owner'}),'הועברה אליך');
        assert.strictEqual(taskEventWords({kind:'owner',from:'',to:'tower'}),'הועברה למגדל');
        assert.strictEqual(taskEventWords({kind:'moved',from:{thread:'small',n:2}}),'הגיעה במיזוג מ-small (משימה 2)');
        assert.strictEqual(taskEventWords({kind:'moved',to:{thread:'big',n:5}}),'עברה במיזוג ל-big (משימה 5)');
        assert.strictEqual(taskEventWords({kind:'moved',to:{thread:'<b>x',n:5}}),'הועברה במיזוג','a strange thread name is not shown');
        assert.strictEqual(taskEventWords({kind:'moved',back:{thread:'big',n:5}}),'נפתחה שוב כאן: כבר לא זו שעברה ל-big (משימה 5)');
        assert.deepStrictEqual(taskEventsOf([{ts:1e20,kind:'created'}]),[],'a time no date can hold is dropped');
        assert.strictEqual(taskEventWords({kind:'archived'}),'לארכיון');
        assert.strictEqual(taskEventWords({kind:'unarchived'}),'הוצאה מהארכיון');
        assert.strictEqual(taskEventWords({kind:'other'}),'');assert.strictEqual(taskEventWords(null),'');
        // and who: he is "you", the sweep is "automatically", an agent by its name
        assert.strictEqual(taskEventWho({by:'owner'}),'אתה');assert.strictEqual(taskEventWho({by:'auto'}),'אוטומטית');
        assert.strictEqual(taskEventWho({by:'tower'}),'מגדל');assert.strictEqual(taskEventWho({by:'a2'}),'a2');
        assert.strictEqual(taskEventWho({}),'');assert.strictEqual(taskEventWho({by:7}),'');
        // the list he opens: oldest first, as the server keeps it
        const list=taskHistory({events:[{ts:9,kind:'status',from:'todo',to:'done',by:'owner'},{ts:5,kind:'created',by:'a2'}]});
        assert.deepStrictEqual(list.map(e=>e.ts),[5,9]);
        """)

    def test_each_task_row_carries_its_time_and_the_arrow_of_its_history(self):
        page = self.page()
        script = page[page.index('function renderTasks('):page.index('function foldTasks(')]
        for part in ("'task-when'", "agoShort(taskLastAt(task),now())", "'task-hist'", "aria-expanded", "taskHistOpen",
                     "'task-events'", "taskEventWords(", "taskEventWho(", "moment(e.ts,now())"):
            self.assertIn(part, script, part)
        # the relative time moves on by itself: the list is drawn again each minute while it is open
        self.assertIn('Math.floor(now()/60)', script)
        # the summary carries one event per task: the whole history comes from the thread's own file, on demand
        self.assertIn("'full/'+encodeURIComponent(", page[page.index('function wantHistory('):page.index('function wantHistory(') + 800])

class SendOrderTests(unittest.TestCase):
    """What he sent arrives in the order he sent it (suda-fixes 54, the owner's guarantee). An answer inside its
    four seconds of undo holds what he wrote after it until it goes (or he takes it back); a message that failed
    holds what he wrote after it until he sends it again or deletes it, and the ones behind it say why."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_an_answer_in_its_undo_and_a_failed_one_hold_what_came_after(self):
        self.pure_js(r"""
        const W=(due,extra)=>Object.assign({delivery:'waiting',due,tries:1},extra);
        const held={delivery:'holding'},failed={delivery:'failed',final:true,error:'x'},run={delivery:'failed',run:{msg_id:'m1'}};
        // the next try of a thread: none while the first that is not with the server is held or failed
        assert.strictEqual(headDue([held,W(0)],true),Infinity);
        assert.strictEqual(headDue([failed,W(0)],true),Infinity);
        assert.strictEqual(headDue([{delivery:'received'},failed,W(0)],true),Infinity);
        assert.strictEqual(headDue([run,W(5)],true),5,'a run request does not hold his words');
        assert.strictEqual(headDue([{delivery:'received'},W(5)],true),5);
        // why one waits: the first earlier message that holds it
        const me={cid:'me',delivery:'waiting',tries:0};
        assert.strictEqual(waitReason([failed,me],me),'failed');
        assert.strictEqual(waitReason([held,me],me),'holding');
        assert.strictEqual(waitReason([W(0),me],me),'queue');
        assert.strictEqual(waitReason([{delivery:'sending',inFlight:true},me],me),'queue');
        assert.strictEqual(waitReason([W(0),failed,me],me),'queue','the first one decides');
        assert.strictEqual(waitReason([failed,W(0),me],me),'failed');
        assert.strictEqual(waitReason([{delivery:'received'},me],me),'');assert.strictEqual(waitReason([me],me),'');
        assert.strictEqual(waitReason([run,me],me),'');
        """)

    def test_the_line_under_a_waiting_message_says_what_it_waits_for(self):
        self.pure_js(r"""
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0,behind:'failed'}),'ממתין: ההודעה שלפניה לא נשלחה. שלח אותה שוב או מחק אותה, ואז זו תישלח');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0,behind:'holding'}),'ממתין לתשובה שבחרת: יישלח מיד אחריה');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0,behind:'queue'}),'ממתין לשליחה: יישלח אחרי ההודעה הקודמת');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:0,behind:true}),'ממתין לשליחה: יישלח אחרי ההודעה הקודמת');
        // one that was tried says why it waits, as before; and behind a failed one, that it waits for that one too
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:2,behind:'failed'}),'ממתין: ההודעה שלפניה לא נשלחה. שלח אותה שוב או מחק אותה, ואז זו תישלח');
        assert.strictEqual(deliveryLine({delivery:'waiting',tries:2,behind:'queue'}),deliveryLine({delivery:'waiting',tries:2}));
        """)


class StuckMarkTests(unittest.TestCase):
    """Outside the thread (the list row, the phone's list, the tab's title): a message of his that failed, and the
    ones it holds behind it, are said (suda-fixes 55). Nothing else changes the mark."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_what_a_thread_has_stuck(self):
        self.pure_js(r"""
        const F={cid:'f',delivery:'failed',final:true,error:'x'},W=c=>({cid:c,delivery:'waiting',tries:0}),R={cid:'r',delivery:'received'};
        assert.strictEqual(stuckOf([]),null);assert.strictEqual(stuckOf(null),null);assert.strictEqual(stuckOf([R,W('a')]),null,'waiting for the line is not stuck');
        assert.deepStrictEqual(stuckOf([F]),{failed:1,held:0});
        assert.deepStrictEqual(stuckOf([F,W('a'),W('b')]),{failed:1,held:2});
        assert.deepStrictEqual(stuckOf([F,{cid:'h',delivery:'holding'}]),{failed:1,held:1},'an answer chosen behind it is held too');
        assert.deepStrictEqual(stuckOf([W('a'),F,W('b')]),{failed:1,held:1},'only what is behind a failed one');
        assert.strictEqual(stuckOf([{cid:'run',delivery:'failed',run:{msg_id:'m1'}}]),null,'a run request is his to press again, it holds nothing');
        // what the row and the tab say
        assert.strictEqual(stuckWords({failed:1,held:0}),'הודעה שלך לא נשלחה');
        assert.strictEqual(stuckWords({failed:1,held:1}),'הודעה שלך לא נשלחה, והודעה אחת מחכה אחריה');
        assert.strictEqual(stuckWords({failed:2,held:3}),'2 הודעות שלך לא נשלחו, ו-3 מחכות אחריהן');
        assert.strictEqual(stuckWords(null),'');
        assert.strictEqual(tabTitle(0,false),'Suda');assert.strictEqual(tabTitle(3,false),'(3) Suda');
        assert.strictEqual(tabTitle(0,true),'⚠️ Suda');assert.strictEqual(tabTitle(3,true),'⚠️ (3) Suda');
        """)


class LineDeltaTests(unittest.TestCase):
    """The change itself on the line (suda-fixes 61, m270): the server sends `event: delta` before "changed", with
    the change file the page would read and the summary's head, so an update takes no read of its own."""
    page, node, pure_js = SlackPageTests.page, SlackPageTests.node, SlackPageTests.pure_js

    def test_a_delta_from_the_line_is_read_strictly(self):
        self.pure_js(r"""
        const run={seq:9,entries:[{from:7,seq:9,threads:{},top:{mark:'0000000b'}}]};
        const ok=deltaOf(JSON.stringify({head:'{"seq":9,"mark":"0000000b","threads":{',run}));
        assert.strictEqual(ok.seq,9);assert.deepStrictEqual(ok.head,{seq:9,mark:'0000000b'});assert.deepStrictEqual(ok.run,run);
        for(const bad of ['', 'x', '[]', '{}', JSON.stringify({head:7,run}), JSON.stringify({head:'{"seq":9,"mark":"0000000b"',run:{seq:'9',entries:[]}}),
                          JSON.stringify({head:'{"seq":9,"mark":"0000000b"',run:{seq:9}}), JSON.stringify({head:'nothing',run}), JSON.stringify({head:'{"seq":8,"mark":"0000000a"',run})])
          assert.strictEqual(deltaOf(bad),null,bad);
        assert.strictEqual(deltaOf('{"head":"'+'x'.repeat(40000)+'"}'),null,'too big to be one');
        """)

    def test_the_page_takes_it_only_when_it_leads_from_what_it_holds_to_the_number_said(self):
        self.pure_js(r"""
        const base={seq:7,mark:'00000007',threads:{a:{id:'a',title:'A'}}};
        const d=deltaOf(JSON.stringify({head:'{"seq":9,"mark":"0000000b"',run:{seq:9,entries:[{from:7,seq:9,threads:{},top:{mark:'0000000b'},edit:{a:{set:{title:'B'}}}}]}}));
        const next=fromLine(base,d,9);
        assert.strictEqual(next.seq,9);assert.strictEqual(next.threads.a.title,'B');
        assert.strictEqual(fromLine(base,d,10),null,'the server said another number');
        assert.strictEqual(fromLine({...base,seq:6},d,9),null,'it does not start where the page is');
        assert.strictEqual(fromLine(base,null,9),null);assert.strictEqual(fromLine(base,d,null),null);
        """)

    def test_an_update_from_the_line_still_measures_the_link_now_and_then(self):
        """Slow mode learns the latency from the page's small board reads (waitSample). With the change on the line
        the page reads nothing for an update, so it would never learn that his loaded link is slow: an update taken
        from the line asks for the summary's head (64 bytes) when the newest latency sample is older than
        MEASURE_GAP (MEASURE_SLOW while the mode is already on), never while idle."""
        self.pure_js(r"""
        const T=1e6;
        assert.strictEqual(measureDue([],T,false),true,'no sample yet');
        assert.strictEqual(measureDue(null,T,false),true);
        assert.strictEqual(measureDue([{ms:900,t:T-MEASURE_GAP-1}],T,false),true,'the newest is old');
        assert.strictEqual(measureDue([{ms:900,t:T-MEASURE_GAP-1},{ms:800,t:T-100}],T,false),false,'one a moment ago');
        assert.strictEqual(measureDue([{ms:900,t:T-MEASURE_GAP-1}],T,true),false,'the mode on: less often');
        assert.strictEqual(measureDue([{ms:900,t:T-MEASURE_SLOW-1}],T,true),true);
        assert.ok(MEASURE_GAP>=1000&&MEASURE_GAP<=3000&&MEASURE_SLOW>MEASURE_GAP);
        """)

    def test_the_update_from_the_line_asks_for_the_measure(self):
        """(wired: the reading that takes the delta asks for the head when a measure is due, and does not wait for it)"""
        page = self.page()
        at = page.index('if(near&&headStands(d.head,near))')
        line = page[at:page.index('\n', at)]
        self.assertIn('measureDue(linkWaits,Date.now(),slowState.on)', line)
        self.assertIn('measureLink()', line)
        self.assertNotIn('await', line)
        body = page[page.index('function measureLink(){'):]
        body = body[:body.index('\n}\n')]
        self.assertIn('if(measuring||', body, 'one measure at a time')
        self.assertIn('document.hidden', body, 'not while hidden')
        self.assertIn("wayOut(new AbortController(),null,'measure')", body, 'on its own way, so cutStuck stops it')


if __name__ == '__main__':
    unittest.main()
