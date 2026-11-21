"""Links between notes in the MD Viewer (suda-fixes task 73, suda m760, m385: "the file's name as it is").

A note links to another by a Markdown link (`[x](01-positioning.md)`), by its name alone in inline code
(`01-positioning.md`, relative to the note's folder) or by its full path; a tap opens it here. Safe: what opens is
decided by the server by the rule that opens notes (inside the roots once symlinks are followed, no hidden folder,
.md only), and the page asks it which links open (/mdv/api/exists), so a link that does not open is marked before
the tap and does not open, and the answer says no more than opening each would (outside and missing are the same
false). A #heading in a link scrolls to that heading."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
MDV = _paths.APP / 'mdv'
sys.path.insert(0, str(MDV))
from mdv import server  # noqa: E402
from mdv.testing import free_port, prepare  # noqa: E402
prepare()

NODE = shutil.which('node')


class Exists(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        (cls.root / 'kit').mkdir(parents=True)
        (cls.root / '.hidden').mkdir()
        (cls.root / 'kit' / '00-index.md').write_text('# Index\n')
        (cls.root / 'kit' / '01-positioning.md').write_text('# Positioning\n')
        (cls.root / '.hidden' / 'x.md').write_text('# x\n')
        (cls.root / 'kit' / 'notes.txt').write_text('x')
        (base / 'out').mkdir()
        (base / 'out' / 'secret.md').write_text('# secret\n')
        (cls.root / 'kit' / 'link.md').symlink_to(base / 'out' / 'secret.md')
        (base / 'roots.json').write_text('{"roots": []}')
        cls.base = base
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, server.Config(base / 'roots.json', [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def ask(self, paths, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Host': '127.0.0.1:%d' % self.port}
        h.update(headers or {})
        c.request('GET', '/mdv/api/exists?' + '&'.join('p=' + quote(str(p), safe='') for p in paths), headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data.startswith(b'{') else data)

    def test_which_links_open(self):
        kit = self.root / 'kit'
        st, got = self.ask([kit / '01-positioning.md', kit / 'none.md', self.base / 'out' / 'secret.md',
                            kit / '../../out/secret.md', kit / 'link.md', self.root / '.hidden' / 'x.md',
                            kit / 'notes.txt', '/etc/hosts', '~/root/kit/00-index.md'])
        self.assertEqual(st, 200)
        # only the notes that open: missing, outside, a symlink out, hidden, not a note are all the same false
        self.assertEqual(got['here'], [True, False, False, False, False, False, False, False, True])

    def test_bounds_and_guards(self):
        self.assertEqual(self.ask([self.root / 'kit' / '00-index.md'] * 201)[0], 400)
        self.assertEqual(self.ask(['/' + 'a' * 5000 + '.md'])[0], 400)
        self.assertEqual(self.ask([])[1]['here'], [])
        self.assertEqual(self.ask([self.root / 'kit' / '00-index.md'], {'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.ask([self.root / 'kit' / '00-index.md'], {'Host': 'evil.example.com'})[0], 403)


@unittest.skipUnless(NODE, 'node is not installed')
class Pure(unittest.TestCase):
    def js(self, script):
        static = MDV / 'static'
        code = ("'use strict';\nconst assert=require('assert');\n" + (static / 'suda-pure.js').read_text()
                + '\n' + (static / 'mdv-pure.js').read_text().replace("'use strict';", '') + '\n' + script)
        r = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_names_headings_and_anchors(self):
        self.js(r"""
// a note's name alone, as the PR kit's index writes it, relative to the note's folder
assert.strictEqual(mdNameOf('01-positioning.md'),'01-positioning.md');
assert.strictEqual(mdNameOf(' docs/plan.markdown '),'docs/plan.markdown');
assert.strictEqual(mdNameOf('../other.md'),'../other.md');
for(const no of ['notes.txt','a b.md','~/x.md','/x.md','https://e.com/a.md','javascript:x.md','x.md|y','']) assert.strictEqual(mdNameOf(no),null,no);
assert.strictEqual(resolveRel('~/Documents/mds/suda-launch-pr',mdNameOf('01-positioning.md')),'~/Documents/mds/suda-launch-pr/01-positioning.md');
// a heading's address, as GitHub makes it, Hebrew kept
assert.strictEqual(headingSlug('Show HN: the title'),'show-hn-the-title');
assert.strictEqual(headingSlug('מחירים ותנאים'),'מחירים-ותנאים');
// a link keeps its #heading, encoded, for the note it opens
const out=rewriteLinks('see [prices](./02-show-hn.md#Rules%20for%20the%20day) and [x](b.md)','~/d','/mdv/');
assert.ok(out.includes('[prices](/mdv/?path=~%2Fd%2F02-show-hn.md#Rules%20for%20the%20day)'),out);
assert.ok(out.includes('[x](/mdv/?path=~%2Fd%2Fb.md)'),out);
assert.strictEqual(anchorOf('#%E0%A4'),'');
assert.strictEqual(anchorOf('#'),'');
// the page's markdown draws the link with its anchor as a plain link, never markup from the heading's words
const html=markdown(rewriteLinks('[a](b.md#"><img src=x onerror=y>)','~/d','/mdv/'),'ltr');
assert.ok(!/<img/.test(html),html);
""")


AB = shutil.which('agent-browser')


@unittest.skipUnless(AB, 'agent-browser is not installed')
class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_mdv_e2e import Browser
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        (cls.root / 'kit').mkdir(parents=True)
        (base / 'out').mkdir()
        (base / 'out' / 'secret.md').write_text('# secret\n')
        (cls.root / 'kit' / '00-index.md').write_text(
            '# Index\n\n| File | What |\n|---|---|\n| `01-positioning.md` | the line |\n| `09-none.md` | not written |\n\n'
            'Also [the rules](02-show-hn.md#rules-for-the-day), [gone](03-gone.md), [out](../../out/secret.md) '
            'and `README.md` in code.\n')
        (cls.root / 'kit' / '01-positioning.md').write_text('# Positioning\n\nShort.\n')
        (cls.root / 'kit' / '02-show-hn.md').write_text('# Show HN\n\n' + 'Text.\n\n' * 80 + '## Rules for the day\n\nBe there.\n')
        (base / 'roots.json').write_text('{"roots": []}')
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, server.Config(base / 'roots.json', [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.b = Browser('mdv-links-%d' % os.getpid())
        try:
            cls.b.run('open', 'about:blank', timeout=120)
        except Exception as e:
            cls.srv.shutdown()
            raise unittest.SkipTest('agent-browser could not open a browser: ' + str(e)[:200])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.b.run('close', timeout=60)
        except Exception:
            pass
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def open(self, name, w=360, h=840):
        self.b.run('set', 'viewport', str(w), str(h))
        self.b.run('open', 'http://127.0.0.1:%d/mdv/?path=%s' % (self.port, quote(str(self.root / 'kit' / name), safe='')))
        self.b.wait('document.querySelectorAll("#doc .blk").length>0', what='the note')

    def links(self):      # (a Markdown link is drawn as a chip: its kind, then its words in .chip-text)
        return self.b.eval('JSON.stringify([...document.querySelectorAll("#doc a.md-link")].map(a=>[(a.querySelector(".chip-text")||a).textContent,'
                           'a.classList.contains("md-broken"),!!a.dataset.maybe]))')

    def test_a_names_links_and_broken_ones(self):
        self.open('00-index.md')
        # the server has answered: no name waits any more
        got = self.b.wait('(()=>{const l=[...document.querySelectorAll("#doc a.md-link")];'
                          'return l.length&&!l.some(a=>a.dataset.maybe)&&l.some(a=>a.classList.contains("md-broken"))?1:0})()',
                          what='the links checked')
        got = dict((t, (broken, maybe)) for t, broken, maybe in self.links())
        self.assertEqual(got.get('01-positioning.md'), (False, False), got)     # a name alone: a link
        self.assertNotIn('09-none.md', got, 'a name of a note that is not there stays code, not a broken link')
        self.assertNotIn('README.md', got)
        self.assertEqual(got.get('the rules'), (False, False), got)
        self.assertEqual(got.get('gone'), (True, False), got)                    # a link to a missing note: marked
        self.assertEqual(got.get('out'), (True, False), got)                     # outside the roots: the same mark
        # a broken link does not open
        self.b.eval('(()=>{[...document.querySelectorAll("#doc a.md-link")].find(a=>(a.querySelector(".chip-text")||a).textContent==="gone").click();return 1})()')
        self.assertIn('00-index.md', self.b.eval('location.search'))
        # the name opens its note
        self.b.eval('(()=>{[...document.querySelectorAll("#doc a.md-link")].find(a=>(a.querySelector(".chip-text")||a).textContent==="01-positioning.md").click();return 1})()')
        self.b.wait('document.getElementById("h-title").textContent==="Positioning"', what='the named note')

    def test_b_a_heading_in_the_link_is_scrolled_to(self):
        self.open('00-index.md')
        self.b.wait('!!document.querySelector("#doc a.md-link")', what='the links')
        self.b.eval('(()=>{[...document.querySelectorAll("#doc a.md-link")].find(a=>(a.querySelector(".chip-text")||a).textContent==="the rules").click();return 1})()')
        self.b.wait('document.getElementById("h-title").textContent==="Show HN"', what='the linked note')
        self.b.wait('(()=>{const h=[...document.querySelectorAll("#doc p.h")].find(n=>n.textContent==="Rules for the day");'
                    'if(!h)return 0;const r=h.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight?1:0})()',
                    what='the heading on the screen')


if __name__ == '__main__':
    unittest.main()
