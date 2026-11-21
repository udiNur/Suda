#!/usr/bin/env python3
"""Hostile review of sse153, fourth pass, under node: probeDue (pure), and the page's cuttable window.fetch taken
verbatim from suda.html, against a fake fetch. Each test asserts the SAFE outcome: a failure is a real hole.

Run: python3 test_adv_sse4_page.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PAGE = (ROOT / 'suda.html').read_text(encoding='utf-8')
PURE = PAGE.split('// <pure>')[1].split('// </pure>')[0]
WRAP = 'const onTheWay=new Set();' + PAGE.split('const onTheWay=new Set();')[1].split('// The head of summary.json')[0]
STUB = r"""
const location={href:'http://127.0.0.1:9/threads/suda.html',origin:'http://127.0.0.1:9'};
const seen=[];
const window={fetch:(url,opts)=>{seen.push({url,opts});return Promise.resolve({ok:true});}};
"""


class Node(unittest.TestCase):
    def js(self, script, wrap=False):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        src = "'use strict';\nconst assert=require('assert');\n" + PURE + '\n' + (STUB + WRAP if wrap else '') + '\n' + script
        r = subprocess.run([node, '-e', src], capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return r.stdout.strip()


class Probe(Node):
    def test_no_probe_with_the_line_up_hidden_offline_or_one_on_its_way(self):
        self.js(r"""
          const s={open:false,hidden:false,offline:false,downSince:0,lastProbe:NaN,probing:false};
          assert.strictEqual(probeDue(s,5000),true);
          for(const k of ['open','hidden','offline','probing'])assert.strictEqual(probeDue({...s,[k]:true},5000),false,k);
          assert.strictEqual(probeDue({...s,downSince:NaN},5000),false);
          assert.strictEqual(probeDue({...s,lastProbe:3000},5000),false);
          assert.strictEqual(probeDue({...s,lastProbe:200000-14000},200000),false,'slow after two minutes');
          assert.strictEqual(probeDue({...s,lastProbe:200000-15000},200000),true);
        """)


class Wrapper(Node):
    def test_a_post_given_as_a_request_object_is_never_made_cuttable(self):
        """fetch(new Request(url, {method: 'POST', body})) has no `opts`: the wrapper reads only opts.method, takes it
        for a GET, and gives it a signal that a line return or a silent line aborts (a POST, maybe a reply)."""
        out = self.js(r"""
          const req=new Request('http://127.0.0.1:9/api/state',{method:'POST',body:'{}'});
          window.fetch(req);
          console.log(JSON.stringify({cuttable:!!(seen[0].opts&&seen[0].opts.signal),ways:[...onTheWay].map(w=>w.key)}));
        """, wrap=True)
        self.assertEqual(out, '{"cuttable":false,"ways":[]}', out)

    def test_a_request_with_its_own_signal_keeps_it(self):
        """fetch(new Request(url, {signal})) with no opts: the wrapper passes {signal: its own}, which replaces the
        Request's: the caller can no longer stop its own read."""
        out = self.js(r"""
          const mine=new AbortController();
          window.fetch(new Request('http://127.0.0.1:9/threads/x.json',{signal:mine.signal}));
          const used=seen[0].opts&&seen[0].opts.signal;
          mine.abort();
          console.log(JSON.stringify({kept:!used||used.aborted}));
        """, wrap=True)
        self.assertEqual(out, '{"kept":true}', out)

    def test_opts_with_a_signal_a_post_or_another_origin_pass_through(self):
        self.js(r"""
          const s=new AbortController().signal;
          window.fetch('x.json',{signal:s});window.fetch('/api/state',{method:'POST'});window.fetch('https://example.com/a');
          window.fetch('/events?board=x');
          assert.strictEqual(onTheWay.size,0);
          window.fetch('x.json',{cache:'no-store'});
          assert.deepStrictEqual([...onTheWay].map(w=>w.key),['get:/threads/x.json']);
        """, wrap=True)


if __name__ == '__main__':
    unittest.main()
