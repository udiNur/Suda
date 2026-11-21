"""Hostile review, round 5 (suda-fixes task 45): rewriteImages in mdv-pure.js, under node.

- A block is left alone only when it STARTS with a fence. A fence after a line of text in the same block (core's
  split keeps "Usage:" and the ```html under it together when no blank line parts them) is rewritten: the wrapper
  tags are deleted from the code and its <img> and ![]() become viewer links, so a README's own HTML sample is shown
  changed.
- The wrapper removal runs over the whole block once it holds an <img>, and `<a\\b[^>]*>` (and p, span, div) runs to
  the next ">" across words and lines: prose like "x <a and y > 3" loses its words.
- The src is found by `\\bsrc=`, which also matches inside data-src: `<img data-src="other.png" src="shot.png">`
  shows other.png.
Safe outcomes asserted below."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = _paths.APP / 'mdv' / 'static'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'node is not installed')
class Rewrite(unittest.TestCase):
    def js(self, script):
        code = ("'use strict';\nconst assert=require('assert');\n"
                + (STATIC / 'mdv-pure.js').read_text().replace("'use strict';", '') + '\n' + script)
        r = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_code_after_text_in_the_same_block_is_left_as_it_is(self):
        self.js(r"""
const code='```html\n<p align="center"><img src="logo.png" width="200"></p>\n![shot](docs/shot.png)\n```';
const block='The header of a README:\n'+code;
const out=rewriteImages(block,'~/d','/mdv/');
assert.ok(out.endsWith(code),'the code sample was changed:\n'+out);
""")

    def test_prose_around_a_picture_keeps_its_words(self):
        self.js(r"""
const out=rewriteImages('<img src="a.png"> When x <a and y > 3, or the <span of words> here, we stop.','~/d','/mdv/');
for (const w of ['and y','of words']) assert.ok(out.includes(w),'"'+w+'" was eaten: '+out);
""")

    def test_data_src_is_not_the_src(self):
        self.js(r"""
const out=rewriteImages('<img data-src="other.png" src="shot.png">','~/d','/mdv/');
assert.ok(out.includes(encodeURIComponent('~/d/shot.png')),'the picture shown is not its src: '+out);
""")


if __name__ == '__main__':
    unittest.main()
