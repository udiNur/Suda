#!/usr/bin/env python3
"""End to end: a diff in a thread is drawn as a diff viewer (the owner, suda-fixes task 12).

An agent posts a ```diff block of two files (and, in another message, a git diff pasted with no fence). The same
harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). What is checked:

  - at 1280 the two sides stand side by side (old on the left, new on the right), with line numbers, red and green
    lines and word marks inside the changed line; at 360 and 750 (the Fold's two screens) the diff is unified and
    the page never scrolls sideways;
  - each file has its own header (name, +/-) and folds and opens at a press;
  - a long run of unchanged lines folds, and "show" opens it in place;
  - copy gives the raw diff exactly; full screen opens it in the reader; it reads left to right in the RTL page;
  - what the diff holds stays text (no markup of it reaches the page).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES

EVIL = '<img src=x onerror="window.__pwned=1">'
DIFF = '\n'.join([
    'diff --git a/src/pay.js b/src/pay.js',
    'index 3b18e51..a9c2f04 100644',
    '--- a/src/pay.js',
    '+++ b/src/pay.js',
    '@@ -10,16 +10,16 @@ function refund(order)',
    ' const order = load(id);',
    '-const total = price * 2;',
    '+const total = price * 3;',
    *[' step(%d);' % i for i in range(10)],
    '-notify(user, "' + EVIL + '");',
    '+notify(user, "done");',
    ' return total;',
    ' }',
    ' // end',
    'diff --git a/docs/NEW.md b/docs/NEW.md',
    'new file mode 100644',
    '--- /dev/null',
    '+++ b/docs/NEW.md',
    '@@ -0,0 +1,2 @@',
    '+# Refunds',
    '+Partial refunds are allowed.',
]) + '\n'
PASTED = '\n'.join(['diff --git a/a.txt b/a.txt', '--- a/a.txt', '+++ b/a.txt', '@@ -1,2 +1,2 @@', ' keep', '-old line', '+new line'])

CARD = '#log .card.diff'
CARD_JS = ('(()=>{const c=[...document.querySelectorAll("#log .card.diff")][%d];if(!c)return null;const v=c.querySelector(".diff-view");'
         'return {layout:v.dataset.layout,dir:getComputedStyle(v).direction,files:c.querySelectorAll(".dfile").length,'
         'names:[...c.querySelectorAll(".dfile-head .dname")].map(n=>n.textContent),'
         'open:[...c.querySelectorAll(".dfile-head")].map(h=>h.getAttribute("aria-expanded")),'
         'split:c.querySelectorAll(".dr").length,unified:c.querySelectorAll(".dl").length,'
         'words:[...c.querySelectorAll(".dw")].map(w=>w.textContent),folds:c.querySelectorAll(".dfold").length,'
         'nums:[...c.querySelectorAll(".dno[data-n]")].length,'
         'cardW:Math.round(c.getBoundingClientRect().width),pageW:document.documentElement.scrollWidth,vw:innerWidth,'
         'imgs:c.querySelectorAll("img").length,text:c.innerText};})()')
STATE = 'JSON.stringify(' + CARD_JS + ')'


class Diff(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-diff'
    TITLE = 'שינוי בשני קבצים'

    def board_with_diff(self):
        if self.TID in self.state()['threads']:
            return
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', self.TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork',
                input='השינוי:\n\n```diff\n' + DIFF + '```\n\nזהו.\n')
        self.ok('say', self.TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork',
                input='Pasted as is:\n' + PASTED + '\n\nאחרי ה-diff.\n')

    def show(self, size):
        self.open_thread(size, self.TID, self.TITLE)
        self.browser.wait('JSON.stringify(document.querySelectorAll(%s).length>=2)' % json.dumps(CARD), what='the two diff cards')
        self.browser.eval('(()=>{document.querySelector(%s).scrollIntoView({block:"start"});return "ok";})()' % json.dumps(CARD))

    def card(self, n=0):
        return self.browser.eval(STATE % n)

    def test_side_by_side_on_a_wide_screen_unified_on_the_phone(self):
        self.board_with_diff()
        for size, layout in ((SIZES[2], 'split'), (SIZES[0], 'unified'), (SIZES[1], 'unified')):
            with self.subTest(size=size[0]):
                self.show(size)
                c = self.browser.wait('JSON.stringify((()=>{const s=%s;return s&&s.layout===%s?s:null;})())' % (CARD_JS % 0, json.dumps(layout)), what=layout)
                self.assertEqual(c['dir'], 'ltr')
                self.assertEqual(c['files'], 2)
                self.assertEqual(c['names'], ['src/pay.js', 'docs/NEW.md'])
                self.assertEqual(c['open'], ['true', 'true'])
                # the word that changed is marked inside its line, on both sides
                self.assertIn('2', c['words'])
                self.assertIn('3', c['words'])
                self.assertGreater(c['nums'], 10)
                if layout == 'split':
                    self.assertGreater(c['split'], 5)
                    self.assertEqual(c['unified'], 0)
                    # old on the left, new on the right
                    sides = self.browser.eval('JSON.stringify((()=>{const r=[...document.querySelectorAll("#log .card.diff .dr")].find(r=>r.querySelector(".dside.del"));'
                                              'const l=r.querySelector(".dside.del").getBoundingClientRect(),a=r.querySelector(".dside.add").getBoundingClientRect();'
                                              'return [l.left<a.left,r.querySelector(".dside.del").innerText.includes("price * 2"),r.querySelector(".dside.add").innerText.includes("price * 3")];})())')
                    self.assertEqual(sides, [True, True, True])
                else:
                    self.assertEqual(c['split'], 0)
                    self.assertGreater(c['unified'], 5)
                    self.assertLessEqual(c['pageW'], c['vw'], 'the page scrolls sideways')
                    self.assertLessEqual(c['cardW'], c['vw'])
                # the colours: a deleted line is red and an added one green (their own background, not the card's)
                colours = self.browser.eval('JSON.stringify((()=>{const c=document.querySelector("#log .card.diff");const bg=s=>getComputedStyle(c.querySelector(s)).backgroundColor;'
                                            'return [bg(".del .dt"),bg(".add .dt"),bg(".diff-view")];})())')
                self.assertEqual(len(set(colours)), 3, colours)
                # the hostile line is text: no picture element, nothing ran
                self.assertEqual(c['imgs'], 0)
                self.assertIn('onerror', c['text'])
                self.assertFalse(self.browser.eval('JSON.stringify(!!window.__pwned)'))

    def test_files_fold_context_opens_copy_and_full_screen(self):
        self.board_with_diff()
        for size in (SIZES[0], SIZES[2]):
            with self.subTest(size=size[0]):
                self.show(size)
                # a file folds at a press on its header, and opens again
                self.browser.eval('(()=>{document.querySelector("#log .card.diff .dfile-head").click();return "ok";})()')
                c = self.card()
                self.assertEqual(c['open'], ['false', 'true'])
                self.assertFalse(self.browser.visible('#log .card.diff .dfile-body'))
                self.browser.eval('(()=>{document.querySelector("#log .card.diff .dfile-head").click();return "ok";})()')
                self.assertEqual(self.card()['open'], ['true', 'true'])
                # ten unchanged lines between two changes: 3 stay on each side, 4 fold; "show" opens them in place
                c = self.card()
                self.assertEqual(c['folds'], 1)
                self.assertNotIn('step(5);', c['text'])
                self.assertIn('4', self.browser.eval('JSON.stringify(document.querySelector("#log .card.diff .dfold").innerText)'))
                self.browser.click('#log .card.diff .dfold')
                c = self.card()
                self.assertEqual(c['folds'], 0)
                for i in range(10):
                    self.assertIn('step(%d);' % i, c['text'])
                # copy gives the diff exactly as the agent wrote it
                self.browser.eval('(()=>{window.__copied=null;Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async t=>{window.__copied=t;}}});return "ok";})()')
                self.browser.click('#log .card.diff .diff-copy')
                self.assertEqual(self.browser.wait('JSON.stringify(window.__copied)', what='the copy'), DIFF)
                # full screen: the reader shows the same diff, and Escape closes it
                self.browser.click('#log .card.diff .diff-full')
                self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&!!document.querySelector("#reader-body .diff-view"))', what='the diff on the full screen')
                inside = self.browser.eval('JSON.stringify((()=>{const v=document.querySelector("#reader-body .diff-view");return [v.querySelectorAll(".dfile").length,getComputedStyle(v).direction,v.innerText.includes("Partial refunds")];})())')
                self.assertEqual(inside, [2, 'ltr', True])
                self.browser.press('Escape')
                self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader to close')

    def test_a_git_diff_pasted_without_a_fence_is_a_diff_too(self):
        self.board_with_diff()
        self.show(SIZES[0])
        c = self.card(1)
        self.assertEqual(c['names'], ['a.txt'])
        self.assertIn('new line', c['text'])
        # the words around it stay words of the message, not lines of the diff
        msg = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].map(m=>m.innerText).find(t=>t.includes("Pasted as is")))')
        self.assertIn('אחרי ה-diff.', msg)
        self.assertNotIn('אחרי ה-diff.', c['text'])
        self.assertNotIn('Pasted as is', c['text'])

    def test_a_very_large_diff_draws_a_part_at_a_time(self):
        """A phone must not freeze on a long diff: a card draws its first DIFF_OPEN lines and offers the rest in parts."""
        tid = 'e2e-diff-big'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'diff גדול', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            body = ['diff --git a/big.txt b/big.txt', '--- a/big.txt', '+++ b/big.txt', '@@ -1,1050 +1,1050 @@']
            body += [('-' if i % 3 == 0 else '+' if i % 3 == 1 else ' ') + 'line %d' % i for i in range(1575)]
            self.ok('say', tid, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork', input='```diff\n' + '\n'.join(body) + '\n```\n')
        self.open_thread(SIZES[0], tid, 'diff גדול')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .card.diff .dmore"))', what='the "show more" of a long diff')
        count = 'JSON.stringify(document.querySelectorAll("#log .card.diff .dl").length)'
        first = self.browser.eval(count)
        self.assertGreater(first, 250)
        self.assertLessEqual(first, 310)
        self.browser.click('#log .card.diff .dmore')
        self.assertLessEqual(self.browser.eval(count), first + 310)
        self.assertGreater(self.browser.eval(count), first + 250)
        # drawing it again from nothing is quick even here (the whole diff is read, a part is drawn)
        ms = self.browser.eval('(()=>{const raw=[...document.querySelectorAll("#log .card.diff")][0]&&%s;const t0=performance.now();'
                               'const card=diffCard(parseDiff(raw),raw);document.body.append(card);card.querySelector(".diff-view").relayout();card.getBoundingClientRect();'
                               'const ms=performance.now()-t0;card.remove();return JSON.stringify(ms);})()' % json.dumps(self.thread(tid)['messages'][0]['text'].split('```diff\n')[1].split('```')[0]))
        self.assertLess(ms, 400)

    def test_a_diff_snippet_opens_in_the_viewer(self):
        """A .diff file sent as a snippet (and his long paste of a git diff, which becomes one) opens as a diff too."""
        tid = 'e2e-diff-snip'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'diff כקטע', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            path = Path(self.tmp.name) / 'change.diff'
            path.write_text(DIFF, encoding='utf-8')
            self.ok('say', tid, '--from', 'fork', 'הקובץ מצורף', '--snippet', str(path), '--state', 'working', '--note', 'בודקים', '--by', 'fork')
        self.open_thread(SIZES[0], tid, 'diff כקטע')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#log .snip-acts .chipbtn")].some(b=>b.innerText.includes("diff")))', what='the diff button of the snippet')
        self.browser.eval('(()=>{[...document.querySelectorAll("#log .snip-acts .chipbtn")].find(b=>b.innerText.includes("diff")).click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden&&document.querySelectorAll("#reader-body .diff-view .dfile").length===2)', what='the snippet in the diff viewer')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#reader-body .diff-view").dataset.layout)'), 'unified')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the reader to close')

    def test_an_opened_fold_draws_in_steps_too(self):
        """Hostile review of fbc79da: "show" on a fold drew all its rows at once (300,000 unchanged lines froze the page).
        An opened fold is drawn in the same steps of 300, with "show more"."""
        tid = 'e2e-diff-fold'
        if tid not in self.state()['threads']:
            self.ok('new', tid, 'קיפול ארוך', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            body = ['--- a/f.txt', '+++ b/f.txt', '@@ -1,902 +1,902 @@', '-a', '+b'] + [' same %d' % i for i in range(900)] + ['-c', '+d']
            self.ok('say', tid, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork', input='```diff\n' + '\n'.join(body) + '\n```\n')
        self.open_thread(SIZES[0], tid, 'קיפול ארוך')
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .card.diff .dfold"))', what='the fold')
        count = 'JSON.stringify(document.querySelectorAll("#log .card.diff .dl").length)'
        before = self.browser.eval(count)
        self.assertLess(before, 20)
        self.browser.click('#log .card.diff .dfold')
        after = self.browser.eval(count)
        self.assertGreater(after, before + 250)
        self.assertLessEqual(after, before + 320)
        self.assertTrue(self.browser.eval('JSON.stringify(!!document.querySelector("#log .card.diff .dmore"))'))
        presses = 0
        while self.browser.eval('JSON.stringify(!!document.querySelector("#log .card.diff .dmore"))') and presses < 5:
            grew = self.browser.eval(count)
            self.browser.click('#log .card.diff .dmore')
            presses += 1
            self.assertLessEqual(self.browser.eval(count), grew + 310)
        self.assertEqual(presses, 2)
        self.assertEqual(self.browser.eval(count), 900 + 4)
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#log .card.diff .dmore"))'))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Diff.__dict__:
        setattr(Diff, _name, None)


if __name__ == '__main__':
    unittest.main()
