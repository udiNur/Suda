#!/usr/bin/env python3
"""End to end: every block of a message reads in the direction of its own words (the owner, thread suda m414).

His screenshot of a thread: an English e-mail quoted inside a Hebrew message was laid out right to left.
It was right-aligned, the numbers of its list stood on the right, and its links sat in a broken order. The same
harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). At 360 and 750:

  - the Hebrew paragraphs stay right to left, on the right;
  - the English quote reads left to right: each paragraph starts on the left, "Hi Chris," keeps its comma at the
    end, and the numbers of its list stand on the left of their items;
  - a link chip inside an English item stands between the words around it, in reading order;
  - an English table runs its columns from the left; an English item in a Hebrew list reads left to right with
    its bullet on its own left, inside the bubble.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-dir'
TITLE = 'כיוון לפי התוכן'
TEXT = '''**טיוטה ב-Superhuman, לא נשלחה.** תשובה בשרשור "Card not present".

> Hi Chris,
>
> We've built our card-not-present integration against the sandbox and are ready to test it live. We're blocked on three things:
>
> 1. **Sandbox API user:** please activate (or reset) our API user on platform account 1674.
> 2. **iFrame domains:** please allow our origins. They are https://dev.pay-example.com and localhost for local testing.
> 3. **Hosted Checkout:** how are credentials issued per operator?
>
> Thanks,
> Dana

| Origin | Status |
|---|---|
| dev | 403 |

- approved by the lead.
- אושר על ידי דנה

סוף ההודעה בעברית.
'''

# Where each block of the message stands, as the screen draws it.
PROBE = r'''(()=>{
  const m=[...document.querySelectorAll("#log .msg")].find(n=>n.textContent.includes("Hi Chris"));
  if(!m)return JSON.stringify(null);
  const md=m.querySelector(".md"),q=md.querySelector("blockquote"),box=r=>({l:Math.round(r.left),r:Math.round(r.right),t:Math.round(r.top+r.height/2)});
  const dir=n=>getComputedStyle(n).direction;
  // the box of the first and of the last character of an element's own first text
  const charBox=(node,at)=>{const w=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);const t=w.nextNode();const range=document.createRange();
    const i=at<0?t.data.length+at:at;range.setStart(t,i);range.setEnd(t,i+1);return box(range.getBoundingClientRect());};
  // where a line of a block starts: the box of its first character, against the block's own padding box
  const ps=[...q.querySelectorAll(":scope > p")],hi=ps[0];
  const ol=q.querySelector("ol"),items=[...ol.children],chip=items[1].querySelector("a.chip-link");
  const beforeChip=document.createRange();{const t=chip.previousSibling;beforeChip.setStart(t,t.data.length-4);beforeChip.setEnd(t,t.data.length-1);}
  const afterChip=document.createRange();{const t=chip.nextSibling;afterChip.setStart(t,1);afterChip.setEnd(t,4);}
  const pad=n=>{const s=getComputedStyle(n);return {l:Math.round(n.getBoundingClientRect().left+parseFloat(s.paddingLeft)+parseFloat(s.borderLeftWidth)),r:Math.round(n.getBoundingClientRect().right-parseFloat(s.paddingRight)-parseFloat(s.borderRightWidth))};};
  const he=[...md.querySelectorAll(":scope > p")].filter(p=>/[֐-׿]/.test(p.textContent));
  const ul=md.querySelector(":scope > ul"),en=ul.children[0],heItem=ul.children[1],table=md.querySelector("table");
  const cells=[...table.rows[0].cells].map(c=>box(c.getBoundingClientRect()));
  return JSON.stringify({
    quote:{dir:dir(q),box:pad(q)},
    hi:{dir:dir(hi),H:charBox(hi,0),comma:charBox(hi,-1),box:pad(hi)},
    paras:ps.map(p=>({dir:dir(p),first:charBox(p,0),box:pad(p)})),
    list:{dir:dir(ol),padL:parseFloat(getComputedStyle(ol).paddingLeft),padR:parseFloat(getComputedStyle(ol).paddingRight),items:items.map(li=>({dir:dir(li),first:charBox(li.querySelector("strong")||li,0),box:box(li.getBoundingClientRect())}))},
    chip:{before:box(beforeChip.getBoundingClientRect()),chip:box(chip.getBoundingClientRect()),after:box(afterChip.getBoundingClientRect())},
    hebrew:he.map(p=>({dir:dir(p),last:charBox(p,0),box:pad(p)})),
    table:{dir:dir(table),cells},
    en:{dir:dir(en),first:charBox(en,0),box:box(en.getBoundingClientRect()),bubble:box(md.getBoundingClientRect())},
    heItem:{dir:dir(heItem)},
  });
})()'''


class Direction(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    def with_message(self):
        if TID in self.state()['threads']:
            return
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork', input=TEXT)

    def test_an_english_quote_in_a_hebrew_message_reads_left_to_right(self):
        self.with_message()
        for size in (SIZES[0], SIZES[1]):
            with self.subTest(size=size[0]):
                self.open_thread(size, TID, TITLE)
                self.browser.wait('JSON.stringify(!!document.querySelector("#log .msg blockquote ol"))', what='the quote and its list')
                got = self.browser.eval(PROBE)
                self.assertIsNotNone(got)
                # the quote and everything in it read left to right
                self.assertEqual(got['quote']['dir'], 'ltr', got['quote'])
                for p in got['paras']:
                    self.assertEqual(p['dir'], 'ltr', p)
                    # each paragraph starts at its left edge, not at its right
                    self.assertLessEqual(abs(p['first']['l'] - p['box']['l']), 3, p)
                # "Hi Chris,": the comma after the name, on its right
                hi = got['hi']
                self.assertLess(hi['H']['l'], hi['comma']['l'], hi)
                # the numbers of the list on the left: the list's room for them is on its left, and every item reads left to right
                lst = got['list']
                self.assertEqual(lst['dir'], 'ltr', lst)
                self.assertGreater(lst['padL'], 10, lst)
                self.assertLess(lst['padR'], 4, lst)
                for item in lst['items']:
                    self.assertEqual(item['dir'], 'ltr', item)
                    self.assertLessEqual(abs(item['first']['l'] - item['box']['l']), 4, item)
                # the chip stands between "are" and "and", in reading order
                chip = got['chip']
                # (in reading order: a line above, or on the same line to the left; a narrow screen may give the chip a line of its own)
                def precedes(a, b):
                    return a['t'] < b['t'] - 8 or (abs(a['t'] - b['t']) <= 8 and a['r'] <= b['l'] + 2)
                self.assertTrue(precedes(chip['before'], chip['chip']) and precedes(chip['chip'], chip['after']), chip)
                # Hebrew stays Hebrew, on the right
                self.assertTrue(got['hebrew'])
                for p in got['hebrew']:
                    self.assertEqual(p['dir'], 'rtl', p)
                    self.assertLessEqual(abs(p['last']['r'] - p['box']['r']), 3, p)
                # an English table: its first column on the left
                self.assertEqual(got['table']['dir'], 'ltr', got['table'])
                self.assertLess(got['table']['cells'][0]['l'], got['table']['cells'][1]['l'], got['table'])
                # an English item in a Hebrew list: left to right, its bullet inside the bubble
                en = got['en']
                self.assertEqual((en['dir'], got['heItem']['dir']), ('ltr', 'rtl'), got)
                self.assertGreaterEqual(en['box']['l'] - en['bubble']['l'], 14, en)
                self.assertLessEqual(abs(en['first']['l'] - en['box']['l']), 3, en)
                shots = os.environ.get('E2E_DIR_SHOTS')
                if shots:
                    self.browser.eval('(()=>{[...document.querySelectorAll("#log .msg")].find(n=>n.textContent.includes("Hi Chris")).scrollIntoView({block:"start"});return "ok";})()')
                    self.browser.run('screenshot', os.path.join(shots, 'dir-%s.png' % size[0]))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Direction.__dict__:
        setattr(Direction, _name, None)


if __name__ == '__main__':
    unittest.main()
