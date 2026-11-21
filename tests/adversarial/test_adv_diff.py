#!/usr/bin/env python3
"""Hostile review of diffview151: a pasted diff must not move which block a run press names."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_slack


def _base():
    for v in vars(test_slack).values():
        if isinstance(v, type) and issubclass(v, unittest.TestCase) and hasattr(v, 'pure_js'):
            return v
    raise RuntimeError('no pure_js base')


class TestPastedDiffKeepsRunNumbering(unittest.TestCase):
    def test_a_fence_inside_a_pasted_diff_does_not_put_run_on_another_block(self):
        """A pasted diff whose context holds a fence line (" ```", a diff of a README) hides that fence from the page,
        but the server's fencedBlocks still counts it. When the counts still agree, the page puts the run button of
        the server's block 0 ("! rm -rf build", drawn as a paragraph) on its own block 0 ("echo harmless")."""
        base = _base()()
        base.pure_js(r"""
const msg=["The patch:","--- a/README.md","+++ b/README.md","@@ -1,4 +1,4 @@"," Install:"," ```","! rm -rf build"," ```","echo harmless"].join('\n');
const html=markdown(msg);
const pres=[...html.matchAll(/<pre(?: class="([^"]*)")?[^>]*><code>([\s\S]*?)<\/code><\/pre>/g)].filter(x=>!/\bpasted\b/.test(x[1]||''));
const blocks=fencedBlocks(msg);
// The page may offer a run only when its block i is the server's block i.
if(pres.length===blocks.length)pres.forEach((p,i)=>assert.strictEqual(p[2],blocks[i].join('\n'),'page block '+i+' is not the server block '+i));
""")


if __name__ == '__main__':
    unittest.main()
