"""Pictures in a .md (suda-fixes task 45): a README shows its screenshots. `![alt](docs/shot.png)` and the `<img
src="docs/shot.png">` READMEs use, by a path relative to the note (or ~/..., or absolute), are drawn in the viewer;
the picture is served by the viewer from the same folders as the notes (the MDS roots), by the same rules (real
paths, no symlink out, no hidden folder), pictures only. A picture on the web is not fetched (the page loads
nothing from elsewhere): it stays a link."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import http.client
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
MDV = _paths.APP / 'mdv'
sys.path.insert(0, str(MDV))
from mdv import core, server  # noqa: E402
from mdv.testing import free_port, prepare  # noqa: E402
prepare()

NODE = shutil.which('node')


def png(w=3, h=2):
    raw = b''.join(b'\x00' + bytes([200, 30, 30]) * w for _ in range(h))
    chunk = lambda k, d: struct.pack('>I', len(d)) + k + d + struct.pack('>I', zlib.crc32(k + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class Assets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.home = base
        self.root = base / 'root'
        (self.root / 'docs').mkdir(parents=True)
        (self.root / '.hidden').mkdir()
        (self.root / 'docs' / 'shot.png').write_bytes(png())
        (self.root / 'docs' / 'a.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        (self.root / '.hidden' / 'x.png').write_bytes(png())
        (self.root / 'notes.txt').write_text('x')
        (base / 'out').mkdir()
        (base / 'out' / 'secret.png').write_bytes(png())
        self.roots = [self.root]

    def tearDown(self):
        self.tmp.cleanup()

    def no(self, raw, code):
        with self.assertRaises(core.Refused) as c:
            core.resolve_asset(raw, self.roots, self.home)
        self.assertEqual(c.exception.code, code, raw)

    def test_what_may_be_served(self):
        real, root = core.resolve_asset(str(self.root / 'docs' / 'shot.png'), self.roots, self.home)
        self.assertEqual(real, self.root / 'docs' / 'shot.png')
        self.assertEqual(core.resolve_asset('~/root/docs/shot.png', self.roots, self.home)[0], real)
        self.no(str(self.home / 'out' / 'secret.png'), 'outside')
        self.no(str(self.root / 'docs/../../out/secret.png'), 'outside')
        self.no(str(self.root / '.hidden' / 'x.png'), 'hidden')
        self.no(str(self.root / 'notes.txt'), 'not-picture')
        self.no(str(self.root / 'docs' / 'none.png'), 'missing')
        (self.root / 'link.png').symlink_to(self.home / 'out' / 'secret.png')
        self.no(str(self.root / 'link.png'), 'outside')
        (self.root / 'txt.png').symlink_to(self.root / 'notes.txt')
        self.no(str(self.root / 'txt.png'), 'not-picture')
        self.assertEqual(core.picture_type(self.root / 'docs' / 'a.svg'), 'image/svg+xml')
        self.assertEqual(core.picture_type(self.root / 'docs' / 'shot.PNG'), 'image/png')


class Endpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        (cls.root / 'docs').mkdir(parents=True)
        (cls.root / 'docs' / 'shot.png').write_bytes(png())
        (cls.root / 'docs' / 'a.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        (base / 'out').mkdir()
        (base / 'out' / 'secret.png').write_bytes(png())
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

    def get(self, path, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Host': '127.0.0.1:%d' % self.port}
        h.update(headers or {})
        c.request('GET', '/mdv/api/asset?path=' + quote(str(path)), headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def test_a_picture_is_served(self):
        st, h, data = self.get(self.root / 'docs' / 'shot.png')
        self.assertEqual((st, h['Content-Type']), (200, 'image/png'))
        self.assertEqual(data, (self.root / 'docs' / 'shot.png').read_bytes())
        self.assertEqual(h['X-Content-Type-Options'], 'nosniff')

    def test_an_svg_never_runs_as_a_page(self):
        st, h, _ = self.get(self.root / 'docs' / 'a.svg')
        self.assertEqual((st, h['Content-Type']), (200, 'image/svg+xml'))
        self.assertIn('sandbox', h.get('Content-Security-Policy', ''))
        self.assertIn("default-src 'none'", h.get('Content-Security-Policy', ''))

    def test_refusals(self):
        self.assertEqual(self.get(self.base / 'out' / 'secret.png')[0], 403)
        self.assertEqual(self.get(self.root / 'docs' / 'none.png')[0], 404)
        self.assertEqual(self.get('/etc/hosts')[0], 400)
        self.assertEqual(self.get(self.root / 'docs' / 'shot.png', {'Host': 'evil.example.com'})[0], 403)


@unittest.skipUnless(NODE, 'node is not installed')
class Page(unittest.TestCase):
    def js(self, script):
        static = MDV / 'static'
        code = ("'use strict';\nconst assert=require('assert');\n" + (static / 'suda-pure.js').read_text()
                + '\n' + (static / 'mdv-pure.js').read_text().replace("'use strict';", '') + '\n' + script)
        r = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_pictures_become_viewer_addresses(self):
        self.js(r"""
const B='/mdv/',D='~/Projects/app';
const out=rewriteImages('Look: ![the screen](docs/shot.png) and ![](../x/y.PNG "title")',D,B);
assert.ok(out.includes('[the screen](/mdv/api/asset?path=~%2FProjects%2Fapp%2Fdocs%2Fshot.png&img=1)'),out);
assert.ok(out.includes('[y.PNG](/mdv/api/asset?path=~%2FProjects%2Fx%2Fy.PNG&img=1)'),out);
assert.ok(!out.includes('!['),out);
// a README's own <img> tag (it escapes in Markdown otherwise), alt and width kept out, the path taken
const tag=rewriteImages('<p align="center"><img src="docs/logo.svg" alt="Logo" width="120"></p>',D,B);
assert.ok(tag.includes('[Logo](/mdv/api/asset?path=~%2FProjects%2Fapp%2Fdocs%2Flogo.svg&img=1&w=120)'),tag);
// the wrappers READMEs put around a picture are not shown as text, and its width is kept (in pixels, to 2000)
const wrapped=rewriteImages('<p align="center">\n  <a href="https://x.dev"><img src="docs/logo.png" width="120" alt="Logo"></a><br/>\n</p>',D,B);
assert.ok(!/<\/?(p|a|br)\b/i.test(wrapped),wrapped);
assert.ok(wrapped.includes('[Logo](/mdv/api/asset?path=~%2FProjects%2Fapp%2Fdocs%2Flogo.png&img=1&w=120)'),wrapped);
assert.ok(!rewriteImages('<img src="a.png" width="99999">',D,B).includes('&w='));
// a block with no picture keeps its tags as text (Suda shows them escaped, as before)
assert.strictEqual(rewriteImages('<p align="center">just text</p>',D,B),'<p align="center">just text</p>');
// ~/ and absolute paths are taken as they are; a picture on the web is not fetched: it stays a link to it
assert.ok(rewriteImages('![a](~/pics/a.jpg)',D,B).includes('path=~%2Fpics%2Fa.jpg&img=1'));
assert.ok(rewriteImages('![a](/Users/y/a.webp)',D,B).includes('path=%2FUsers%2Fy%2Fa.webp&img=1'));
assert.strictEqual(rewriteImages('![remote](https://e.com/a.png)',D,B),'[remote](https://e.com/a.png)');
// not a picture, inside code, or climbing above /: left as it was
assert.strictEqual(rewriteImages('![x](notes.txt)',D,B),'![x](notes.txt)');
assert.strictEqual(rewriteImages('`![x](a.png)`',D,B),'`![x](a.png)`');
assert.strictEqual(rewriteImages('```\n![x](a.png)\n```',D,B),'```\n![x](a.png)\n```');
assert.strictEqual(rewriteImages('![x](../../../../a.png)','/a',B),'![x](../../../../a.png)');
// Suda's markdown draws the result as a plain link, never a chip: the page turns it into the picture
const html=markdown(rewriteImages('![shot](docs/shot.png)',D,B),'ltr');
assert.ok(/<a href="\/mdv\/api\/asset\?path=[^"]+&amp;img=1"/.test(html)||/<a href="\/mdv\/api\/asset\?path=[^"]+&img=1"/.test(html),html);
assert.ok(!html.includes('chip-link'),html);
// an alt or a path that tries to leave its attribute stays text
const evil=markdown(rewriteImages('![a" onerror="x](a.png)',D,B)+' '+rewriteImages('<img src="a.png\" onerror=x>',D,B),'ltr');
assert.ok(!/<[^>]+onerror/.test(evil),evil);
""")


if __name__ == '__main__':
    unittest.main()
