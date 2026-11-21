#!/usr/bin/env python3
"""Hostile review of the direction change (8317ed6..HEAD): markdown() blocks take their direction from their words.

Every test asserts the CORRECT outcome: a FAIL is a real hole in the change.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_slack


class AdvDir(test_slack.SlackPageTests):

    # ── direction: realistic Hebrew agent lines must stay Hebrew ─────────────

    def test_hebrew_line_heavy_with_identifiers_stays_rtl(self):
        """A Hebrew sentence that names several files / services / paths (very common in agents' status lines) has
        more Latin letters than 4x its Hebrew ones, so blockDir calls it English: dir="ltr", left-aligned, its
        closing Hebrew word and punctuation on the wrong side. Before the change any Hebrew kept it RTL."""
        self.pure_js(r"""
        const lines=['suda.html, test_slack.py ו-test_e2e_dir.py עודכנו.',
          'worker-a, threads-worker, tuios ו-tower: הכל ירוק.',
          '~/Projects/threads/suda.html עודכן.',
          'chris@example.com ו-dana@example.org בעותק.',
          'git push origin feature/suda-direction נכשל.',
          'test_slack.py: 412 tests OK, test_e2e_dir.py: OK \u2014 הכל עובר.',
          'PHONE-1, dev.example.app, adb tcpip \u2014 עובד.'];
        const wrong=lines.filter(line=>markdown(line).slice(0,3)!=='<p>');
        assert.deepStrictEqual(wrong,[],'Hebrew sentences laid left to right:\n'+wrong.map(l=>markdown(l)).join('\n'));
        """)

    def test_hebrew_list_item_and_heading_heavy_with_identifiers_stay_rtl(self):
        self.pure_js(r"""
        const ul=markdown('- worker-a, threads-worker \u2014 רצים\n- tower \u2014 למטה');
        assert.ok(!ul.includes('dir="ltr"'),ul);
        const h=markdown('## worker-a, threads-worker, tuios: סטטוס');
        assert.ok(!h.includes('dir="ltr"'),h);
        """)

    # ── time: the quote's recursion re-runs a quadratic trim ─────────────────

    def test_a_quoted_line_of_spaces_does_not_stall_the_page(self):
        """`.replace(/\\s+$/,'')` is quadratic on a long run of spaces that is not at the end (pre-existing at depth 0,
        ~0.55 s for 20k spaces). The quote path now runs it again on the joined body at every level, ~4x more."""
        self.pure_js(r"""
        const started=Date.now();markdown('> > > a'+' '.repeat(20000)+'b');
        const took=Date.now()-started;assert.ok(took<1000,'a quoted line of 20k spaces took '+took+' ms');
        """)

    # ── what held ────────────────────────────────────────────────────────────

    def test_held_fuzzed_quotes_tables_lists_emit_only_whitelisted_balanced_tags(self):
        self.pure_js(r"""
        const okTag=tag=>/^<\/?(p|br|strong|code|pre|ul|ol|li|blockquote|hr|table|tr|td|th|div|span)( (class|dir|value)="[\w -]*")*>$/.test(tag)
         ||/^<a href="(https?:\/\/|\/(?!\/))[^"<>\s]*"( dir="ltr")? target="_blank" rel="noopener">$/.test(tag)||tag==='</a>'
         ||/^<a class="chip-link" data-kind="(pr|issue|commit|file|repo|thread|board|page|web)"( data-thread="[a-z0-9-]+"( data-msg="m\d+")?)? href="(https?:\/\/|\/(?!\/))[^"<>\s]*" title="(https?:\/\/|\/(?!\/))[^"<>\s]*" target="_blank" rel="noopener">$/.test(tag)
         ||['<span class="chip-kind">','</span>','<bdi class="chip-text">','</bdi>','<svg class="chip-icon" viewBox="0 0 16 16" aria-hidden="true">','</svg>'].includes(tag)
         ||/^<use href="#i-(pr|issue|commit|file|thread|board|web)"\/>$/.test(tag);
        const atoms=['>','> ','>>','|',' | ','-','- ','1. ','  ','\n','```','```mermaid','<','"',"'",'&','a','א','‎','‏','‮','[x](https://e.x/a"b)','https://e.x/<b>','**','`','#','---','\t','<script>','x="1"',']','(','/a.html','&lt;'];
        let seed=7;const rnd=n=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed%n;};
        for(let i=0;i<40000;i++){
          let s='';const n=1+rnd(30);for(let j=0;j<n;j++)s+=atoms[rnd(atoms.length)];
          const html=markdown(s),stack=[];
          for(const tag of html.match(/<[^>]*>/g)||[]){
            assert.ok(okTag(tag),JSON.stringify(s)+' → '+tag);
            const m=/^<(\/?)([a-z]+)/.exec(tag);if(['use','br','hr'].includes(m[2]))continue;
            if(!m[1])stack.push(m[2]);else assert.strictEqual(stack.pop(),m[2],JSON.stringify(s)+' → '+html);
          }
          assert.strictEqual(stack.length,0,JSON.stringify(s));
        }
        """)

    def test_held_the_page_counts_code_blocks_as_the_server_does_with_quotes_around(self):
        self.pure_js(r"""
        const texts=['> ```sh\n> ! ls\n> ```\n```sh\n! pwd\n```','```\n> not a quote\n```\n> ```\n> x','> q\n```\n! a\n```\n> ```',
          '- a\n> ```\n```\n! b\n```','> > ```\n> > x\n> > ```','>```\n```\nz\n```','> ```\n```\n> ```\n```'];
        for(const t of texts){const pres=(markdown(t).match(/<pre/g)||[]).length;assert.strictEqual(pres,fencedBlocks(t).length,t+' → '+markdown(t));}
        // a quote with only a fence keeps its text
        assert.strictEqual(markdown('> ```\n> ls\n> ```'),'<blockquote dir="ltr"><p>```</p><p>ls</p><p>```</p></blockquote>');
        """)

    def test_held_huge_inputs_render_fast(self):
        self.pure_js(r"""
        const t=Date.now();
        markdown('> hello world א\n'.repeat(100000));markdown('> > > > - item\n'.repeat(50000));markdown(' >'.repeat(300000));
        markdown('|'+' a |'.repeat(200000));markdown('> | a | b |\n'.repeat(50000));markdown('> - a\n>   - b\n>     - c\n'.repeat(30000));
        assert.ok(Date.now()-t<5000,'slow: '+(Date.now()-t)+' ms');
        // the depth is bounded: at most three quotes inside each other
        assert.strictEqual((markdown('> > > > > > x').match(/<blockquote/g)||[]).length,3);
        """)

    def test_held_structure_around_quotes(self):
        self.pure_js(r"""
        assert.strictEqual(markdown('> q\n- a'),'<blockquote dir="ltr"><p>q</p></blockquote><ul dir="ltr"><li>a</li></ul>');
        assert.strictEqual(markdown('- א\n> ש\nטקסט'),'<ul><li>א</li></ul><blockquote><p>ש</p></blockquote><p>טקסט</p>');
        assert.strictEqual(markdown('> - one\n> continued here'),'<blockquote dir="ltr"><ul><li>one</li></ul><p>continued here</p></blockquote>');
        assert.strictEqual(markdown('>\n>\n'),'<blockquote></blockquote>');
        assert.strictEqual(markdown('> 13:45'),'<blockquote><p>13:45</p></blockquote>');
        """)


# Only the tests of this file: the ones inherited from test_slack run there.
for _name in dir(test_slack.SlackPageTests):
    if _name.startswith('test') and _name not in AdvDir.__dict__:
        setattr(AdvDir, _name, None)


if __name__ == '__main__':
    unittest.main()
