"""The page's DOM-free logic (static/mdv-pure.js, on top of Suda's suda-pure.js) under node."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()

STATIC = _paths.APP / 'mdv' / 'static'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'node is not installed')
class Pure(unittest.TestCase):
    def js(self, script):
        code = ("'use strict';\nconst assert=require('assert');\n" + (STATIC / 'suda-pure.js').read_text()
                + '\n' + (STATIC / 'mdv-pure.js').read_text().replace("'use strict';", '') + '\n' + script)
        r = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_links_to_md_open_here(self):
        self.js(r"""
const B='/mdv/';
assert.strictEqual(viewerHref(B,'~/a b/(x).md'),'/mdv/?path=~%2Fa%20b%2F%28x%29.md');
assert.strictEqual(resolveRel('~/Documents/mds/todo','./plan.md'),'~/Documents/mds/todo/plan.md');
assert.strictEqual(resolveRel('~/Documents/mds/todo','../a%20b.md'),'~/Documents/mds/a b.md');
assert.strictEqual(resolveRel('/x','../../../etc/a.md'),null);
assert.strictEqual(resolveRel('/x','https://e.com/a.md'),null);
assert.strictEqual(resolveRel('/x','javascript:alert(1)//.md'),null);
const out=rewriteLinks('see [the plan](./plan.md) and [web](https://e.com/x.md) and `[not](./code.md)`','~/d',B);
assert.ok(out.includes('[the plan](/mdv/?path=~%2Fd%2Fplan.md)'),out);
assert.ok(out.includes('[web](https://e.com/x.md)'));
assert.ok(out.includes('`[not](./code.md)`'));
assert.strictEqual(rewriteLinks('```\n[a](b.md)\n```','~/d',B),'```\n[a](b.md)\n```');
assert.strictEqual(rewriteLinks('[a](b.txt)','~/d',B),'[a](b.txt)');
// Suda's markdown turns the rewritten link into a plain link to this viewer, never a chip, never a script
const html=markdown(rewriteLinks('[x](../y.md)','~/d',B),'ltr');
assert.ok(html.includes('href="/mdv/?path=~%2Fy.md"'),html);
const evil=markdown(rewriteLinks('[x](./a.md"onmouseover=alert(1)//.md)','~/d',B),'ltr');
assert.ok(!/<a[^>]*onmouseover/.test(evil),evil);
""")

    def test_code_paths(self):
        self.js(r"""
assert.strictEqual(mdPathOf('~/Documents/mds/todo/x.md'),'~/Documents/mds/todo/x.md');
assert.strictEqual(mdPathOf(' /Users/y/a.MD '),'/Users/y/a.MD');
assert.strictEqual(mdPathOf('x.md'),null);
assert.strictEqual(mdPathOf('~/a b.md'),null);
assert.strictEqual(mdPathOf('~/a/../b.md'),null);
assert.strictEqual(mdPathOf('~/a.txt'),null);
""")

    def test_changed_blocks_and_title(self):
        self.js(r"""
assert.deepStrictEqual(changedBlocks(['a','b','c'],['a','B','c','d']),[1,3]);
assert.deepStrictEqual(changedBlocks(['a','a'],['a','a','a']),[2]);
assert.deepStrictEqual(changedBlocks(null,['a']),[0]);
assert.strictEqual(docTitle(['intro','## The **plan**'],'f.md'),'The plan');
assert.strictEqual(docTitle(['```\n# not\n```'],'f.md'),'f.md');
assert.strictEqual(sizeWords(820),'820 B');assert.strictEqual(sizeWords(1434),'1.4 KB');
assert.deepStrictEqual(rememberPath(['b','a','c'],'a',2),['a','b']);
""")

    def test_soft_breaks_join_like_a_document(self):
        self.js(r"""
assert.strictEqual(joinSoftBreaks('Read this first\nand then that.'),'Read this first and then that.');
assert.strictEqual(joinSoftBreaks('- an item\n  that goes on\n- another'),'- an item that goes on\n- another');
assert.strictEqual(joinSoftBreaks('a line  \nhard break'),'a line  \nhard break');
assert.strictEqual(joinSoftBreaks('a\\\nb'),'a\\\nb');
assert.strictEqual(joinSoftBreaks('# Title\ntext'),'# Title\ntext');
assert.strictEqual(joinSoftBreaks('| a | b |\n|---|---|\n| 1 | 2 |'),'| a | b |\n|---|---|\n| 1 | 2 |');
assert.strictEqual(joinSoftBreaks('> quote\n> more'),'> quote\n> more');
assert.strictEqual(joinSoftBreaks('text\n1. one\n2. two'),'text\n1. one\n2. two');
assert.strictEqual(joinSoftBreaks('intro\n```\nx = 1\ny = 2\n```\nafter'),'intro\n```\nx = 1\ny = 2\n```\nafter');
assert.strictEqual(joinSoftBreaks('```\na\nb\n```'),'```\na\nb\n```');
assert.strictEqual(joinSoftBreaks('above\n---'),'above\n---');
// joined, the paragraph is one <p> in Suda's markdown
assert.strictEqual((markdown(joinSoftBreaks('one\ntwo'),'ltr').match(/<p/g)||[]).length,1);
""")

    def test_split_matches_the_server(self):
        import json
        import sys
        from mdv import core
        samples = [p.read_text() for p in SAMPLES.glob('*.md')]
        samples.append('a\n\n```\nx\n\n~~~\ny\n```\n\n~~~\nz\n\n~~~\n\n  ```py\nq\n  ```\nend')
        want = [core.blocks_of(t) for t in samples]
        self.js('const S=%s,W=%s;S.forEach((t,i)=>assert.deepStrictEqual(blocksOf(t),W[i]));' % (json.dumps(samples), json.dumps(want)))

    def test_a_comment_island_in_code(self):
        # round 6: which part of one line of a comment reads right to left (`rtl`), and what stays left to right
        # around it (`lead`: the indentation, and the marker when the comment follows code; `tail`: a closing */)
        self.js(r"""
const I=(p,a)=>codeIsland(p,a);
assert.deepStrictEqual(I('    # בודקים את החיבור',true),{lead:'    ',rtl:'# בודקים את החיבור',tail:''});
assert.deepStrictEqual(I('# הערה',false),{lead:'# ',rtl:'הערה',tail:''});
// a block comment after code keeps its closing marker after its words, outside the island
assert.deepStrictEqual(I('/* הערה */',false),{lead:'/* ',rtl:'הערה',tail:' */'});
// a bracket written right after the marker belongs to the words (it closes on their far side)
assert.deepStrictEqual(I('#(הערה)',false),{lead:'#',rtl:'(הערה)',tail:''});
// a comment whose words start in English is not an island: one Hebrew word in it stays in its place
assert.strictEqual(I('// Returns the user name (שם) or null',true),null);
assert.strictEqual(I(' * @param {string} name שם המשתמש',false),null);
assert.strictEqual(I('# TODO תקן את זה',false),null);
// the * of a block comment's middle line stays on the left, in its column
assert.deepStrictEqual(I(' * שורה באמצע',true),{lead:' * ',rtl:'שורה באמצע',tail:''});
assert.strictEqual(I('# just English',true),null);
assert.strictEqual(I('',true),null);
// the parts always add up to the line
for(const [p,a] of [['  -- הערה.  ',false],['/** שלום */',true],['#!שלום',true]]){const h=I(p,a);assert.strictEqual(h.lead+h.rtl+h.tail,p);}
""")


if __name__ == '__main__':
    unittest.main()
