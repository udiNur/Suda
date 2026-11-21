#!/usr/bin/env python3
"""Hostile review, end to end, of the direction change (8317ed6..HEAD). Same harness as test_e2e_dir.py.

Every test asserts the CORRECT outcome: a FAIL is a real hole in the change.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-adv-dir'
TITLE = 'כיוון בדיקה עוינת'
TEXT = '''הנה הטבלה מהספק:

| Device ID | Firmware version | Modem | Last seen | Signal quality | Operator | Notes about it |
|---|---|---|---|---|---|---|
| PHONE-alpha | 4.2.17-release | BG95-M3 | 2026-11-16 12:00 | good enough | Acme Payments | needs reboot soon |

> Hi Chris, the numbers per region:
>
> | Region | Count |
> |---|---|
> | East | 12 |
>
> - first point here
>   - nested English point
>   - נקודה בעברית
>     - deeper English point

> ציטוט בעברית מהשרשור הקודם

- פריט ראשון בעברית
  - nested English item one
    - deeper English item two
- פריט אחרון
'''

PROBE = r'''(()=>{
  const m=[...document.querySelectorAll("#log .msg")].find(n=>n.textContent.includes("needs reboot soon"));
  if(!m)return JSON.stringify(null);
  const md=m.querySelector(".md"),B=n=>{const r=n.getBoundingClientRect();return {l:Math.round(r.left),r:Math.round(r.right)};};
  const tables=[...md.querySelectorAll("table")],wide=tables[0],holder=wide.closest(".table"),first=wide.rows[0].cells[0];
  const quotes=[...md.querySelectorAll(":scope > blockquote")],qs=quotes.map(q=>{const s=getComputedStyle(q);return {dir:s.direction,bl:parseFloat(s.borderLeftWidth),br:parseFloat(s.borderRightWidth)};});
  const inner=quotes[0].querySelector("table"),innerCard=inner&&inner.closest(".card");
  const lis=[...md.querySelectorAll("li")].map(li=>({text:li.firstChild.textContent.trim().slice(0,40),dir:getComputedStyle(li).direction,box:B(li)}));
  return JSON.stringify({bubble:B(md),holder:B(holder),first:B(first),firstText:first.textContent,scrollLeft:holder.scrollLeft,
    quotes:qs,innerCard:innerCard?{cls:innerCard.className,box:B(innerCard),bar:!!innerCard.querySelector(".card-top")}:null,lis});
})()'''


class AdvDirection(test_e2e.Suda):

    def with_message(self):
        if TID in self.state()['threads']:
            return
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('say', TID, '--from', 'fork', '-', '--state', 'working', '--note', 'בודקים', '--by', 'fork', input=TEXT)

    def probe(self, size):
        self.with_message()
        self.open_thread(size, TID, TITLE)
        self.browser.wait('JSON.stringify(!!document.querySelector("#log .msg .sheet table"))', what='the dressed table')
        got = self.browser.eval(PROBE)
        self.assertIsNotNone(got)
        return got

    def test_a_wide_english_table_in_a_hebrew_message_opens_on_its_first_column(self):
        """The table is dir=ltr but its scroller (div.table) inherits rtl: an rtl scroller opens at its right edge,
        so a wide English table opens on its LAST columns and its first column (the row's name) is off screen."""
        for size in (SIZES[0], SIZES[1]):
            with self.subTest(size=size[0]):
                got = self.probe(size)
                self.assertEqual(got['firstText'], 'Device ID')
                self.assertTrue(got['holder']['l'] - 1 <= got['first']['l'] and got['first']['r'] <= got['holder']['r'] + 1,
                                'first column off screen: %r' % {k: got[k] for k in ('holder', 'first', 'scrollLeft')})

    def test_quote_border_side_and_table_inside_a_quote(self):
        for size in (SIZES[0], SIZES[1]):
            with self.subTest(size=size[0]):
                got = self.probe(size)
                en, he = got['quotes']
                self.assertEqual((en['dir'], en['bl'], en['br']), ('ltr', 3, 0), en)
                self.assertEqual((he['dir'], he['bl'], he['br']), ('rtl', 0, 3), he)
                card = got['innerCard']
                self.assertIsNotNone(card, 'the table in the quote is not dressed')
                self.assertTrue(card['bar'], card)
                self.assertTrue(got['bubble']['l'] - 1 <= card['box']['l'] and card['box']['r'] <= got['bubble']['r'] + 1, (card, got['bubble']))

    def test_mixed_nested_items_keep_their_marker_room_inside_the_bubble(self):
        """Every item has at least 14px between its marker side and the bubble's edge (the marker sits there)."""
        for size in (SIZES[0], SIZES[1]):
            with self.subTest(size=size[0]):
                got = self.probe(size)
                bub = got['bubble']
                for li in got['lis']:
                    room = li['box']['l'] - bub['l'] if li['dir'] == 'ltr' else bub['r'] - li['box']['r']
                    self.assertGreaterEqual(room, 14, li)
                    self.assertTrue(bub['l'] - 1 <= li['box']['l'] and li['box']['r'] <= bub['r'] + 1, li)
                # nesting stays visible: a sub-item stands inward of its parent on the list's own start side
                by = {li['text']: li for li in got['lis']}
                for parent, child, side in (('פריט ראשון בעברית', 'nested English item one', 'r'),
                                            ('first point here', 'נקודה בעברית', 'l')):
                    p, c = by[parent]['box'], by[child]['box']
                    inward = p['r'] - c['r'] if side == 'r' else c['l'] - p['l']
                    self.assertGreaterEqual(inward, 14, 'sub-item %r not nested under %r: %r %r' % (child, parent, p, c))
                shots = os.environ.get('E2E_DIR_SHOTS')
                if shots:
                    self.browser.eval('(()=>{[...document.querySelectorAll("#log .msg")].find(n=>n.textContent.includes("needs reboot")).scrollIntoView({block:"start"});return "ok";})()')
                    self.browser.run('screenshot', os.path.join(shots, 'adv-%s.png' % size[0]))


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvDirection.__dict__:
        setattr(AdvDirection, _name, None)


if __name__ == '__main__':
    unittest.main()
