#!/usr/bin/env python3
"""Hostile review of the page's automatic re-sending (suda.html, a9b8304..e40e44e): the DOM-free part, under node.

Every test states the CORRECT behaviour, so a FAIL is a hole. Nothing here touches a board, a server or a browser.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'


class AdvSendPure(unittest.TestCase):
    def pure_js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    # ── a hole ───────────────────────────────────────────────────────────────

    def test_what_the_page_before_this_kept_as_refused_by_the_server_is_not_sent_by_the_new_page(self):
        """The page before this change kept every failure as {delivery:'failed', error} with no `final`. One of those
        whose error is the SERVER's own reason was refused: it is his to send again, never the page's. (The two
        texts the old page wrote when nobody answered are another matter: those may go again.)"""
        self.pure_js(r"""
        const at=1000000,old=(error)=>({cid:'c1',from:'owner',text:'שלום',ts:at-600,delivery:'failed',inFlight:false,error});
        for(const refusal of ['השרשור סגור','השאלה הזאת כבר לא פתוחה','ההודעה ארוכה מדי']){
          const back=unsentAtLoad(old(refusal),at);
          assert.strictEqual(back.delivery,'failed','the old page showed "לא נשלח: '+refusal+'": the new page must not send it by itself, got '+back.delivery);
          assert.strictEqual(back.error,refusal);
        }
        """)

    def test_what_the_page_cuts_for_a_reply_is_never_cut_through_the_middle_of_a_character(self):
        """An excerpt, a caption and a temporary title are cut by UTF-16 units. A cut that lands inside an emoji
        leaves half of it, and the board server cannot write such a string (see the end-to-end test of this:
        test_adv_send_page ... test_a_reply_the_server_can_never_take_...): the reply never gets an answer."""
        self.pure_js(r"""
        const E='\u{1F600}',whole=s=>typeof s.isWellFormed==='function'?s.isWellFormed():!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);
        const bad=[];
        if(!whole(excerptOf('a'.repeat(498)+E+' ועוד מילים אחריו')))bad.push('excerptOf');
        if(!whole(captionOf('b'.repeat(499)+E)))bad.push('captionOf');
        if(!whole(tempTitle('c'.repeat(59)+E+E)))bad.push('tempTitle');
        assert.deepStrictEqual(bad,[],'cut through the middle of a character: '+bad.join(', '));
        """)

    # ── what held ────────────────────────────────────────────────────────────

    def test_held_every_outcome_of_a_post_is_classified(self):
        self.pure_js(r"""
        const OK={ok:true,applied:true},R={ok:true,thread:'a',msg_id:'m1'};
        // nothing answered, or a server in trouble: again
        for(const s of [0,undefined,null,NaN,408,425,429,500,501,502,503,504,520,599])assert.strictEqual(postFault(s,OK,R),'again','status '+s);
        // an answer that is a refusal of the request itself: never again by itself
        for(const s of [100,101,301,302,304,400,401,403,404,405,409,410,413,415,422,451])assert.strictEqual(postFault(s,OK,R),'no','status '+s);
        // 2xx whose body is not the board server's
        for(const body of [null,undefined,0,'',[],{},{ok:1},{ok:'true'},{ok:null},'<html>'])assert.strictEqual(postFault(200,body,R),'again',JSON.stringify(body));
        // 2xx from the board server
        assert.strictEqual(postFault(200,OK,R),'');assert.strictEqual(postFault(201,OK,R),'');
        assert.strictEqual(postFault(200,OK,null),'no');assert.strictEqual(postFault(200,OK,{}),'no');
        assert.strictEqual(postFault(200,{ok:true,applied:false},R),'no');
        assert.strictEqual(postFault(200,{ok:false,applied:false},{ok:false}),'no','a server from before `again`: a refusal');
        // only the server's own `again:true` asks for another try
        for(const again of ['true',1,'yes',{},[]])assert.strictEqual(postFault(200,{ok:false,applied:false},{ok:false,error:'x',again}),'no',JSON.stringify(again));
        assert.strictEqual(postFault(200,{ok:false,applied:false},{ok:false,error:'x',again:true}),'again');
        // a receipt that says "again" on a success is still a success
        assert.strictEqual(postFault(200,OK,{ok:true,again:true}),'');
        """)

    def test_held_the_cap_and_the_half_day_cannot_be_talked_round(self):
        self.pure_js(r"""
        const at=2000000;
        // heard: text from the store counts as a number; rubbish counts as none
        assert.strictEqual(retries({ts:at,heard:String(RETRY_HEARD)},at),false);assert.strictEqual(retries({ts:at,heard:'x'},at),true);
        assert.strictEqual(retries({ts:at,heard:RETRY_HEARD+50},at),false);
        // ts: missing, text, null, an object: never the page's to send
        for(const ts of [undefined,'x',null,{},[1,2],NaN])assert.strictEqual(retries({ts},at),false,String(ts));
        assert.strictEqual(retries({ts:String(at-5)},at),true);
        // the waits never shrink and never go under a second
        let last=0;for(let n=0;n<60;n++){const w=retryIn(n);assert.ok(w>=1000&&w>=last&&w<=RETRY_SLOW,n+': '+w);last=w;}
        for(const n of [NaN,undefined,null,-3,'x'])assert.ok(retryIn(n)>=1000,String(n));
        // a load: never "in flight", never "sending", the entry itself untouched
        // (`auto`: the page had begun to send it. Decided after this review: an entry without that mark is what a
        // page from before left, shown to him as "not sent", and stays his.)
        const m={cid:'c',from:'owner',text:'x',ts:at-9,delivery:'sending',auto:true,inFlight:true,due:5,tries:3,heard:5,held:77},kept=JSON.stringify(m);
        const back=unsentAtLoad(m,at);
        assert.strictEqual(JSON.stringify(m),kept);assert.strictEqual(back.inFlight,false);assert.strictEqual(back.delivery,'waiting');assert.strictEqual(back.due,0);
        // refused, or given up on: stays his at every later load, however often the page loads
        let f={cid:'c',text:'x',ts:at-9,delivery:'failed',final:true,error:'השרשור סגור',heard:6,tries:6};
        for(let i=0;i<5;i++)f=JSON.parse(JSON.stringify(unsentAtLoad(f,at+i)));
        assert.strictEqual(f.delivery,'failed');assert.strictEqual(f.final,true);assert.strictEqual(f.error,'השרשור סגור');
        // received stays received; older than half a day, or with no time, is never sent by the page
        assert.strictEqual(unsentAtLoad({cid:'c',ts:at-9,delivery:'received',id:'m3'},at).delivery,'received');
        for(const ts of [at-RETRY_FOR,at-RETRY_FOR-1,undefined,'x',null])for(const delivery of ['sending','waiting','holding','failed',undefined])
          assert.strictEqual(unsentAtLoad({cid:'c',text:'x',ts,delivery},at).delivery,'failed',ts+' '+delivery);
        """)

    def test_held_the_stored_outbox_keeps_the_marks_and_drops_only_what_is_finished(self):
        self.pure_js(r"""
        const a={cid:'a',text:'1',ts:5,delivery:'failed',final:true,error:'השרשור סגור',heard:2,tries:3},b={cid:'b',text:'2',ts:6,delivery:'waiting',tries:1,due:99};
        const big={cid:'p',text:'',ts:7,delivery:'waiting',images:[{name:'x.png',type:'image/png',data:'AAAA',caption:'כיתוב'}],voice:{type:'audio/webm',data:'BBBB',seconds:3}};
        // what goes to the store: the marks whole, the bytes not
        assert.deepStrictEqual(forStorage(a),a);
        const kept=forStorage(big);
        assert.strictEqual(kept.delivery,'waiting');assert.ok(lostPart(kept));assert.ok(!lostPart(big));assert.ok(!JSON.stringify(kept).includes('AAAA')&&!JSON.stringify(kept).includes('BBBB'));
        // another tab's entries stay, this tab's replace their own, what is finished leaves
        const stored=[['t1',[a,b]],['t2',[{cid:'z',text:'9',ts:1,delivery:'sending'}]]];
        const mine=new Map([['t1',[{...b,delivery:'sending',inFlight:true}]]]);
        assert.deepStrictEqual(mergeOutbox(stored,mine,new Set()).map(r=>[r[0],r[1].map(m=>m.cid+':'+m.delivery)]),[['t1',['a:failed','b:sending']],['t2',['z:sending']]]);
        assert.deepStrictEqual(mergeOutbox(stored,new Map(),new Set(['a','z'])).map(r=>[r[0],r[1].map(m=>m.cid)]),[['t1',['b']]]);
        // a store that is not a list of rows is read as empty, and never throws
        for(const bad of [null,{},'x',5,[5],[[1,2]],[['t',null]],[['t',[null,{},{text:'no cid'}]]]])assert.deepStrictEqual(mergeOutbox(bad,new Map(),new Set()),[],JSON.stringify(bad));
        """)


if __name__ == '__main__':
    unittest.main()
