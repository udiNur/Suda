#!/usr/bin/env python3
"""The files beside the board (links.json, places.json, live.json, drafts.json) are asked "changed since?" instead
of read in full each time (suda-fixes 16, savings164). The page keeps the last body with the response's
Last-Modified and Date; it sends If-Modified-Since only when that copy was at least 2 s old when it was read (the
server's times are whole seconds: a write in the same second as the copy cannot hide behind a 304), and reads in
full at least once a minute (a file put back with an older time is not hidden for longer). On a 304 the kept body
is the answer; on anything else the new body is taken.

  - askSince, the rule (pure, under node);
  - sideFetch against a fake server (under node): a 304 gives the kept body, a 200 to If-Modified-Since gives the
    new one, a 304 for nothing kept reads in full, a failure keeps nothing;
  - end to end, against the real board server (the harness of test_e2e): a write in the same second as the read is
    never hidden; an unchanged old file costs a 304 and no body; a changed one is read again.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_side_reads.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import email.utils
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest

ROOT = _paths.APP
PAGE = (ROOT / 'suda.html').read_text(encoding='utf-8')
PURE = PAGE.split('// <pure>')[1].split('// </pure>')[0]
SIDE = PAGE.split('// <side>')[1].split('// </side>')[0] if '// <side>' in PAGE else ''
NODE = shutil.which('node')


def node(script):
    r = subprocess.run([NODE, '-e', "'use strict';\n" + script], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return r.stdout


@unittest.skipUnless(NODE, 'node is not installed')
class Rule(unittest.TestCase):
    def test_ask_only_for_a_copy_that_was_old_enough_and_recent_enough(self):
        node(PURE + r"""
        const assert=require('assert');
        const T=Date.parse('Fri, 20 Nov 2026 01:36:54 GMT'),http=ms=>new Date(ms).toUTCString();
        const held=(lmMs,dateMs,fullAgo,now)=>({lm:http(lmMs),date:http(dateMs),full:now-fullAgo});
        const now=1_000_000_000;
        assert.deepStrictEqual([SIDE_AGE,SIDE_FULL_EVERY],[2000,60000]);
        // read 10 s after it was written: ask "changed since" its Last-Modified
        assert.strictEqual(askSince(held(T,T+10000,5000,now),now),http(T));
        assert.strictEqual(askSince(held(T,T+2000,5000,now),now),http(T));
        // read in the same second it was written (or the one after): a later write may have the same second
        assert.strictEqual(askSince(held(T,T,5000,now),now),'');
        assert.strictEqual(askSince(held(T,T+1000,5000,now),now),'');
        // a Last-Modified after the Date (another clock): never trusted
        assert.strictEqual(askSince(held(T+5000,T,5000,now),now),'');
        // read in full more than a minute ago: read in full again
        assert.strictEqual(askSince(held(T,T+10000,60001,now),now),'');
        assert.strictEqual(askSince(held(T,T+10000,59000,now),now),http(T));
        // nothing kept, or headers that are not dates
        for(const bad of [null,undefined,{},{lm:'x',date:http(T),full:now},{lm:http(T),date:'',full:now},{lm:http(T),date:http(T+9000)},
                          {lm:http(T),date:http(T+9000),full:NaN},{lm:5,date:http(T+9000),full:now}])
          assert.strictEqual(askSince(bad,now),'',JSON.stringify(bad));
        """)


FAKE = r"""
const assert=require('assert');
const asked=[];let answer=null;
globalThis.fetch=async(url,opts)=>{
  const ims=opts&&opts.headers&&opts.headers['If-Modified-Since']||'';
  asked.push([String(url).split('?')[0],ims]);
  const a=answer(String(url).split('?')[0],ims);
  return new Response(a.status===304?null:a.body,{status:a.status,headers:a.headers||{}});
};
const OLD='Fri, 20 Nov 2026 01:00:00 GMT',LATER='Fri, 20 Nov 2026 01:00:30 GMT';
"""


@unittest.skipUnless(NODE, 'node is not installed')
class Helper(unittest.TestCase):
    def run_js(self, body):
        self.assertTrue(SIDE, 'suda.html has no // <side> block')
        return json.loads(node(PURE + FAKE + SIDE + '\n(async()=>{' + body + '})().catch(e=>{console.error(e);process.exit(1);});'))

    def test_a_304_gives_the_kept_body_and_a_200_the_new_one(self):
        got = self.run_js(r"""
          answer=(path,ims)=>ims?{status:304}:{status:200,body:'{"v":1}',headers:{'Last-Modified':OLD,'Date':LATER}};
          const a=await (await sideFetch('links.json')).text();
          const b=await (await sideFetch('links.json')).text();
          // the server says it changed (a 200 to If-Modified-Since): the new body is taken, and kept
          answer=(path,ims)=>({status:200,body:'{"v":2}',headers:{'Last-Modified':'Fri, 20 Nov 2026 01:00:20 GMT','Date':LATER}});
          const c=await (await sideFetch('links.json')).text();
          answer=(path,ims)=>ims?{status:304}:{status:500};
          const d=await (await sideFetch('links.json')).text();
          console.log(JSON.stringify({a,b,c,d,asked}));
        """)
        self.assertEqual((got['a'], got['b'], got['c'], got['d']), ('{"v":1}', '{"v":1}', '{"v":2}', '{"v":2}'))
        self.assertEqual(got['asked'], [['links.json', ''], ['links.json', 'Fri, 20 Nov 2026 01:00:00 GMT'],
                                        ['links.json', 'Fri, 20 Nov 2026 01:00:00 GMT'], ['links.json', 'Fri, 20 Nov 2026 01:00:20 GMT']])

    def test_a_304_for_nothing_kept_reads_in_full_and_a_failure_keeps_nothing(self):
        got = self.run_js(r"""
          // a 304 the page did not ask for (nothing kept): read in full
          let n=0;answer=(path,ims)=>(n++===0?{status:304}:{status:200,body:'{"w":1}',headers:{'Last-Modified':OLD,'Date':LATER}});
          const first=await sideFetch('places.json');
          // a failure: nothing kept, the next read is whole
          answer=(path,ims)=>({status:503,body:'busy'});
          const bad=await sideFetch('live.json');
          answer=(path,ims)=>(ims?{status:304}:{status:200,body:'{"x":1}',headers:{'Last-Modified':OLD,'Date':LATER}});
          const after=await (await sideFetch('live.json')).text();
          console.log(JSON.stringify({first:first.status,firstText:await first.text(),bad:bad.status,after,asked}));
        """)
        self.assertEqual((got['first'], got['firstText']), (200, '{"w":1}'))
        self.assertEqual([a for a in got['asked'] if a[0] == 'places.json'], [['places.json', ''], ['places.json', '']])
        self.assertEqual(got['bad'], 503)
        self.assertEqual(got['after'], '{"x":1}')
        self.assertEqual([a for a in got['asked'] if a[0] == 'live.json'], [['live.json', ''], ['live.json', '']])

    def test_a_copy_without_dates_is_never_asked_about(self):
        got = self.run_js(r"""
          answer=(path,ims)=>ims?{status:304}:{status:200,body:'{"v":1}'};
          await sideFetch('drafts.json');await sideFetch('drafts.json');
          console.log(JSON.stringify({asked}));
        """)
        self.assertEqual(got['asked'], [['drafts.json', ''], ['drafts.json', '']])


if os.environ.get('SIDE_E2E', '1') == '1':
    import test_e2e
    from test_e2e import SIZES

    ASK = r"""(async()=>{const r=await sideFetch(%s);return JSON.stringify({status:r.status,text:await r.text()});})()"""
    # what the page's own reads of a file were: the status of each response the browser had
    STATUSES = r"""JSON.stringify(performance.getEntriesByType('resource').filter(e=>new URL(e.name).pathname.endsWith('/'+%s)).map(e=>e.responseStatus))"""

    class Server(test_e2e.Suda):
        TID = 'side-reads'

        def setUp(self):
            if self.TID not in self.state()['threads']:
                self.ok('new', self.TID, 'קבצים לצד הלוח', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')

        def put(self, name, text, mtime):
            path = self.board / name
            path.write_text(text, encoding='utf-8')
            os.utime(path, (mtime, mtime))

        def ask(self, name):
            return self.browser.eval(ASK % json.dumps(name))

        def open_page(self):
            self.open_thread(SIZES[2], self.TID, 'קבצים לצד הלוח')
            self.browser.eval('(()=>{performance.setResourceTimingBufferSize(5000);performance.clearResourceTimings();return "ok";})()')

        def test_a_write_in_the_same_second_as_the_read_is_never_hidden(self):
            """The file is read in the very second it was written; it is written again in that same second (the same
            whole-second time, as the server says it). The next read must give the new body."""
            self.open_page()
            name = 'side-same-second.json'
            second = int(time.time())
            self.put(name, '{"v":"first"}', second)
            self.assertEqual(self.ask(name)['text'], '{"v":"first"}')
            self.put(name, '{"v":"second, same second"}', second)
            self.assertEqual(self.ask(name)['text'], '{"v":"second, same second"}')

        def test_an_unchanged_old_file_costs_a_304_and_a_changed_one_is_read(self):
            self.open_page()
            name = 'side-old.json'
            old = int(time.time()) - 30
            self.put(name, '{"v":"old"}', old)
            self.assertEqual(self.ask(name)['text'], '{"v":"old"}')
            self.assertEqual(self.ask(name)['text'], '{"v":"old"}')
            statuses = self.browser.eval(STATUSES % json.dumps(name))
            self.assertEqual(statuses[-1], 304, statuses)
            # the server answers 200 to If-Modified-Since (the file changed): the page takes the new body
            self.put(name, '{"v":"new"}', old + 10)
            self.assertEqual(self.ask(name)['text'], '{"v":"new"}')
            self.assertEqual(self.browser.eval(STATUSES % json.dumps(name))[-1], 200)

        def test_the_side_files_go_through_it(self):
            """links, places, live and drafts: each asked "changed since" once its copy is old enough."""
            for name in ('links.json', 'places.json', 'live.json', 'drafts.json'):
                path = self.board / name
                if not path.exists():
                    path.write_text('{}', encoding='utf-8')
                os.utime(path, (time.time() - 30, time.time() - 30))
            self.open_page()
            self.browser.eval('(()=>{pullLinks();pullPlaces();pullLive();pullDrafts();return "ok";})()')
            time.sleep(1.5)
            self.browser.eval('(()=>{pullLinks();pullPlaces();pullLive();pullDrafts();return "ok";})()')
            time.sleep(1.5)
            for name in ('links.json', 'places.json', 'live.json', 'drafts.json'):
                statuses = self.browser.eval(STATUSES % json.dumps(name))
                self.assertIn(304, statuses, '%s was never asked "changed since": %s' % (name, statuses))

    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in Server.__dict__:
            setattr(Server, _name, None)


if __name__ == '__main__':
    unittest.main()
