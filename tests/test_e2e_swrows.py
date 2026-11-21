#!/usr/bin/env python3
"""End to end: the rows of the palette never draw one thing over another (the owner, thread suda m511/m513 with a
screenshot: in ⌘K, a row of a thread from another space had its space's tag over its "עליך" chip, and a long
title ran under both). The title ends with "…" before the chips; the chips stand side by side. At 360, 750, 1280.
The same harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import unittest

import test_e2e
from test_e2e import SIZES

LONG = 'Dana / Orchard Snacks (8353): קורא הכרטיסים לא מזוהה ביחידה חדשה אחרי החלפת לוח ראשי ועדכון קושחה'
GEO = r'''(()=>{const rows=[...document.querySelectorAll("#sw-results .sw-row[data-id^=sup-]")];
  const box=e=>{const r=e.getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom};};
  const hit=(a,b)=>a.l<b.r-0.5&&b.l<a.r-0.5&&a.t<b.b-0.5&&b.t<a.b-0.5;
  return JSON.stringify(rows.map(row=>{const title=row.querySelector(".sw-title"),text=row.querySelector(".sw-text");
    const parts=[...row.querySelectorAll(".chip,.sw-space,.badge")].map(box),tb=box(title),xb=box(text);
    return {id:row.dataset.id,clipped:title.scrollWidth>title.clientWidth+1?title.clientWidth<=xb.r-xb.l+1:true,
      inside:tb.l>=xb.l-1&&tb.r<=xb.r+1,overlap:parts.some((p,i)=>parts.some((q,j)=>i<j&&hit(p,q))),
      under:parts.some(p=>hit(p,tb)),wide:Math.round(tb.r-tb.l)};}));})()'''


class SwitcherRows(test_e2e.Suda):
    def test_rows_of_another_space_lay_out_without_overlap(self):
        for tid in ('sup-149', 'sup-160'):
            if tid not in self.state()['threads']:
                self.ok('new', tid, LONG, '--state', 'on-owner', '--note', 'לשלוח ל-Dana את האישור?')
        if not any(s['id'] == 'support' for s in self.state().get('spaces', [])):
            self.ok('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        try:
            for size in (SIZES[0], SIZES[1], SIZES[2]):
                with self.subTest(size=size[0]):
                    self.browser.eval('(()=>{try{localStorage.clear()}catch(e){};return "ok"})()')
                    self.open(size)
                    self.browser.wait('JSON.stringify(synced&&spacesAll().length===2)', what='two spaces')
                    self.browser.eval('(()=>{openSwitcher();return "ok"})()')
                    self.browser.wait('JSON.stringify(document.querySelectorAll("#sw-results .sw-row[data-id^=sup-]").length>=2)', what='the rows of the other space')
                    got = self.browser.eval(GEO)
                    shots = os.environ.get('SWROWS_SHOTS')
                    if shots:
                        self.browser.run('screenshot', os.path.join(shots, 'sw-%s.png' % size[0]))
                    for row in got:
                        self.assertTrue(row['inside'], ('the title runs out of its place', size[0], row))
                        self.assertFalse(row['under'], ('the title runs under a chip', size[0], row))
                        self.assertFalse(row['overlap'], ('chips drawn over each other', size[0], row))
                    self.browser.press('Escape')
        finally:
            self.cli('space', 'rm', 'support')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in SwitcherRows.__dict__:
        setattr(SwitcherRows, _name, None)


if __name__ == '__main__':
    unittest.main()
