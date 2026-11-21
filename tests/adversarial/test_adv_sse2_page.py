#!/usr/bin/env python3
"""Hostile review of sse153, the page's side under node: the pure catchUp/headOf, and the catch-up reading itself
(summaryHead, entryFile, readChanges, taken verbatim from suda.html) against a fake server.

Each test asserts the SAFE outcome: a failure is a real hole.

Run: python3 test_adv_sse2_page.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PAGE = (ROOT / 'suda.html').read_text(encoding='utf-8')
PURE = PAGE.split('// <pure>')[1].split('// </pure>')[0]
SYNC = 'const entryFile=' + PAGE.split('const entryFile=')[1].split('async function fetchState')[0]

# A fake board: summaries by number (each with its mark), the chain of entries, the requests the page made.
FAKE = r"""
let heard=null,heardAt=NaN;
const asked=[];
const board={summary:null,files:{},changes:null,range:true,headFails:false,status:{}};
function respond(status,text){
  const bytes=new TextEncoder().encode(text);let sent=0;
  const body=new ReadableStream({pull(c){if(sent>=bytes.length){c.close();return;}const n=Math.min(16384,bytes.length-sent);c.enqueue(bytes.subarray(sent,sent+n));sent+=n;board.sent=(board.sent||0)+n;}});
  return new Response(status===204?null:body,{status});
}
globalThis.fetch=async(url,opts)=>{
  const name=String(url).split('?')[0],range=opts&&opts.headers&&opts.headers.Range;
  asked.push(name+(range?':head':''));
  if(board.status[name+(range?':head':'')])return respond(board.status[name+(range?':head':'')],'');
  if(name==='summary.json'){
    if(range&&board.headFails){if(typeof board.headFails==='number')board.headFails--;throw new TypeError('network');}
    const text=board.summary===null?null:JSON.stringify(board.summary);
    if(text===null)return respond(404,'');
    if(range&&board.range)return respond(206,text.slice(0,64));
    return respond(200,text);
  }
  if(name==='changes.json')return board.changes?respond(200,JSON.stringify(board.changes)):respond(404,'');
  const m=/^changes\/(\d+)\.json$/.exec(name);
  if(m)return board.files[m[1]]?respond(200,JSON.stringify(board.files[m[1]])):respond(404,'');
  return respond(404,'');
};
// summaries s0..s3: numbers 100,200,300,400; each a thread with a title; the head first, as threads.py writes it
const S=n=>({seq:n*100,mark:('0000000'+n).slice(-8),lite:1,threads:{a:{id:'a',title:'t'+n}}});
const E=n=>({from:(n-1)*100,seq:n*100,threads:{},edit:{a:{set:{title:'t'+n}}},top:{mark:('0000000'+n).slice(-8)}});
"""


class Node(unittest.TestCase):
    def js(self, script, sync=False):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        src = "'use strict';\nconst assert=require('assert');\n" + PURE + '\n' + (FAKE + SYNC if sync else '') + '\n' + script
        r = subprocess.run([node, '-e', src], capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return r.stdout.strip()


class Pure(Node):
    def test_a_base_between_two_entries_is_never_caught_up(self):
        """A page holds a number no entry ends at (lost history, an unnumbered summary given a seq by hand)."""
        self.js(r"""
          const base={seq:150,threads:{a:{id:'a',title:'x'}}};
          const ch={seq:300,entries:[{from:100,seq:200,threads:{}},{from:200,seq:300,threads:{}}]};
          assert.strictEqual(catchUp(base,ch),null);
          assert.strictEqual(catchUp(base,ch,300),null);
        """)

    def test_a_duplicate_or_forked_entry_breaks_the_chain(self):
        self.js(r"""
          const base={seq:100,threads:{a:{id:'a',title:'x'}}};
          const fork={seq:300,entries:[{from:100,seq:200,threads:{}},{from:100,seq:300,threads:{a:null}}]};
          assert.strictEqual(catchUp(base,fork),null);
          const back={seq:300,entries:[{from:100,seq:300,threads:{}},{from:100,seq:200,threads:{}}]};
          assert.strictEqual(catchUp(base,back),null,'an entry going back (seq 200 after 300) is skipped as "had"');
        """)

    def test_catch_up_never_touches_the_base(self):
        self.js(r"""
          const row={id:'a',title:'x',tasks:[1,2,3]};
          const base={seq:100,mark:'00000001',threads:{a:row}};
          const before=JSON.stringify(base);
          const out=catchUp(base,{seq:200,entries:[{from:100,seq:200,edit:{a:{set:{title:'y'},list:{tasks:{n:2,at:[[0,9]]}}}},top:{mark:'00000002'}}]});
          assert.strictEqual(JSON.stringify(base),before);
          assert.deepStrictEqual(out.threads.a,{id:'a',title:'y',tasks:[9,2]});
          assert.strictEqual(out.mark,'00000002');
        """)

    def test_a_head_is_only_the_first_bytes_as_threads_py_writes_them(self):
        self.js(r"""
          assert.strictEqual(headOf('{"lite":1,"seq":5,"mark":"0000abcd"}'),null);
          assert.strictEqual(headOf(' {"seq":5,"mark":"0000abcd"}'),null);
          assert.strictEqual(headOf('{"seq":5,"mark":"0000ABCD"}'),null);
          assert.deepStrictEqual(headOf('{"seq":5,"mark":"0000abcd","lite":1'),{seq:5,mark:'0000abcd'});
          assert.strictEqual(headStands({seq:5,mark:'0000abcd'},{seq:5}),false,'a kept copy with no mark never stands');
        """)


class Sync(Node):
    """readChanges as the page runs it, against the fake board."""

    def test_a_reading_with_a_stale_goal_catches_up_to_what_the_head_says(self):
        """The page comes back (visibilitychange, pageshow, online) and calls refresh(). `heard` is the last word from
        before (within 25 s), so readChanges takes it as the goal: the page's own number. The head it reads beside
        says the board moved on (a later number, with its change file there), and the reading throws that away: the
        page stays behind, with the mark still "fresh" from the old word, until the line speaks again."""
        out = self.js(r"""
          (async()=>{
            board.summary=S(2);board.files['100']=E(2);board.changes={seq:200,mark:'00000002',entries:[E(2)]};
            heard=100;heardAt=Date.now()-5000;               // the last word, from before the sleep
            const at=await readChanges(S(1));
            console.log(JSON.stringify({reached:at&&at.seq,asked}));
          })();
        """, sync=True)
        got = json.loads(out)
        self.assertTrue(got['reached'] in (200, None),
                        'the head said 200 and the page stays at %s (asked %s): a refresh on coming back reads nothing new' % (got['reached'], got['asked']))

    def test_a_failed_head_does_not_cost_the_whole_summary_when_the_chain_reaches_the_goal(self):
        """On a weak link the 64-byte head request fails while the change file arrives. Without the head the chain is
        not vouched for (an unnumbered writer may have rewritten the board under that number), but one failed head must
        not cost the whole summary (about 200 KB) exactly when the link is weak: the head is asked once more. Only when
        it fails again is the whole summary read (the safe way)."""
        out = self.js(r"""
          (async()=>{
            board.summary=S(2);board.files['100']=E(2);board.headFails=1;
            heard=200;heardAt=Date.now();
            const once=await readChanges(S(1)),asked1=[...asked];
            board.headFails=true;asked.length=0;
            const always=await readChanges(S(1));
            console.log(JSON.stringify({reached:once&&once.seq,asked:asked1,always}));
          })();
        """, sync=True)
        got = json.loads(out)
        self.assertEqual(got['reached'], 200, 'a failed 64-byte head throws away a good chain: the whole summary follows (%s)' % got['asked'])
        self.assertEqual(got['asked'].count('summary.json:head'), 2, got['asked'])
        self.assertIsNone(got['always'], 'a chain no head ever vouched for was taken')

    def test_a_page_three_changes_behind_reads_one_file_and_the_head(self):
        """On a slow link every request waits for a connection and a round trip: a page a few changes behind reads
        the one file that holds every change from its number on, beside the head, and nothing else."""
        out = self.js(r"""
          (async()=>{
            board.summary=S(4);board.files['100']={seq:400,entries:[E(2),E(3),E(4)]};
            heard=400;heardAt=Date.now();
            const at=await readChanges(S(1));
            console.log(JSON.stringify({reached:at&&at.seq,title:at&&at.threads.a.title,asked:[...asked].sort()}));
          })();
        """, sync=True)
        got = json.loads(out)
        self.assertEqual(got, {'reached': 400, 'title': 't4', 'asked': ['changes/100.json', 'summary.json:head']})

    def test_a_word_older_than_the_page_is_stale_not_a_board_that_went_back(self):
        """The page caught up past the server's last word (by the head, after a probe found the link): that word is
        older than the page's number, and still within its 25 s. It is a stale word, not a board that went back: the
        head decides, and the page reads only what it lacks."""
        out = self.js(r"""
          (async()=>{
            board.summary=S(3);board.files['200']={seq:300,entries:[E(3)]};
            heard=100;heardAt=Date.now();
            const at=await readChanges(S(2));
            console.log(JSON.stringify({reached:at&&at.seq,asked:[...asked].sort()}));
          })();
        """, sync=True)
        self.assertEqual(json.loads(out), {'reached': 300, 'asked': ['changes/200.json', 'summary.json:head']})

    def test_a_server_without_ranges_is_read_no_further_than_the_head(self):
        out = self.js(r"""
          (async()=>{
            const big=S(2);big.pad='x'.repeat(300000);board.summary=big;board.range=false;
            board.files['100']=E(2);heard=200;heardAt=Date.now();
            const at=await readChanges(S(1));
            console.log(JSON.stringify({reached:at&&at.seq,sent:board.sent,asked}));
          })();
        """, sync=True)
        got = json.loads(out)
        self.assertLessEqual(got['sent'], 65536, got)

    def test_a_416_or_a_missing_summary_is_never_vouched(self):
        out = self.js(r"""
          (async()=>{
            const r=[];
            board.files['100']=E(2);heard=200;heardAt=Date.now();
            board.summary=S(2);board.status['summary.json:head']=416;r.push(await readChanges(S(1)));
            board.status={};board.summary=null;r.push(await readChanges(S(1)));
            console.log(JSON.stringify(r));
          })();
        """, sync=True)
        self.assertEqual(json.loads(out), [None, None])

    def test_an_unnumbered_rewrite_at_the_number_reached_is_read_whole(self):
        """The deltas reach 200, but the summary at 200 was rewritten by an older threads.py (no head)."""
        out = self.js(r"""
          (async()=>{
            const u=S(2);delete u.mark;delete u.seq;board.summary={lite:1,...u,seq:200};
            board.files['100']=E(2);heard=200;heardAt=Date.now();
            const at=await readChanges(S(1));
            console.log(JSON.stringify(at&&at.seq));
          })();
        """, sync=True)
        self.assertEqual(json.loads(out), None)

    def test_a_head_of_another_mark_at_the_number_reached_is_read_whole(self):
        out = self.js(r"""
          (async()=>{
            board.summary={...S(2),mark:'deadbeef'};board.files['100']=E(2);heard=200;heardAt=Date.now();
            const at=await readChanges(S(1));
            console.log(JSON.stringify(at&&at.seq));
          })();
        """, sync=True)
        self.assertEqual(json.loads(out), None)


if __name__ == '__main__':
    unittest.main()
