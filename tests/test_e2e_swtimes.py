#!/usr/bin/env python3
"""End to end: every thread row of the ⌘K palette says how long ago it last changed (suda m642), in the short words
of the sidebar row ("12 דק׳", "3 שע׳", "3 ימים"); a command row says nothing. The time is small, at the row's end,
on one line, and never pushes the title (m649: a compact palette), at 360, 750 and 1280 wide. While the palette is
open the times move on by themselves, and the chosen row and the scroll stay where they were.
The same harness as test_e2e.py.

SWTIMES_SHOTS=<dir> also takes a picture of the palette at each size.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest

import test_e2e
from test_e2e import SIZES

MIN, HOUR, DAY = 60, 3600, 86400
TIMES = 'JSON.stringify(Object.fromEntries([...document.querySelectorAll("#sw-results .sw-row[data-id]")].map(r=>[r.dataset.id,(r.querySelector(".sw-time")||{}).textContent||""])))'
# Every row laid out: nothing wider than the row, the time on one line at the row's end (the left, right to left),
# the title on one line.
LAYOUT = r'''JSON.stringify((()=>{
  const bad=[];
  for(const r of document.querySelectorAll("#sw-results .sw-row")){
    const box=r.getBoundingClientRect(),name=r.dataset.id||r.innerText.trim().slice(0,20);
    if(r.scrollWidth>r.clientWidth+1)bad.push(name+": the row overflows "+r.scrollWidth+">"+r.clientWidth);
    const title=r.querySelector(".sw-title"),tm=r.querySelector(".sw-time");
    if(title){const h=parseFloat(getComputedStyle(title).lineHeight)||20;if(title.getBoundingClientRect().height>h*1.5)bad.push(name+": the title wraps");}
    if(!tm)continue;
    const t=tm.getBoundingClientRect(),fs=parseFloat(getComputedStyle(tm).fontSize),ts=parseFloat(getComputedStyle(title).fontSize);
    if(t.left<box.left-0.5||t.right>box.right+0.5)bad.push(name+": the time leaves the row");
    if(t.height>fs*1.9)bad.push(name+": the time wraps ("+t.height+")");
    if(!(fs<ts))bad.push(name+": the time is not smaller than the title");
    for(const c of r.children)if(c!==tm&&c.getBoundingClientRect().width&&c.getBoundingClientRect().left<t.right-0.5)bad.push(name+": "+c.className+" stands after the time or over it");
    if(t.width<4)bad.push(name+": the time is not shown");
  }
  return bad;
})())'''


class SwitcherTimes(test_e2e.Suda):
    def at(self, seconds_ago, *args):
        """The CLI as if it ran `seconds_ago` before now."""
        r = self.cli_at(time.time() - seconds_ago, *args)
        self.assertEqual(r.returncode, 0, (args, r.stderr))

    def cli_at(self, when, *args):
        import subprocess
        import sys
        return subprocess.run([sys.executable, str(test_e2e.CLI), *args], env=dict(self.env, THREADS_NOW=repr(when)),
                              capture_output=True, text=True)

    def palette(self, text=''):
        self.browser.eval('(()=>{if(!switcher.hidden)closeSwitcher();return "ok";})()')
        self.browser.wait('JSON.stringify(switcher.hidden)', what='the palette closed')
        self.browser.press('Control+k')
        self.browser.wait('JSON.stringify(!switcher.hidden&&!!document.querySelector("#sw-results .sw-row"))', what='the palette')
        if text:
            self.browser.fill('#sw-query', text)
        return self.browser.eval(TIMES)

    def setUp(self):
        threads = self.state()['threads']
        if 'e2e-swt-min' not in threads:
            self.at(3 * DAY + 600, 'new', 'e2e-swt-min', 'נושא של דקות', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            self.at(12 * MIN + 5, 'say', 'e2e-swt-min', '--from', 'fork', 'הודעה לפני שתים עשרה דקות', '--state', 'working', '--note', 'בונה')
            self.at(3 * DAY + 600, 'new', 'e2e-swt-hour', 'נושא של שעות', '--state', 'on-owner', '--note', 'מחכה', '--by', 'e2e')
            self.at(3 * HOUR + 300, 'say', 'e2e-swt-hour', '--from', 'fork', 'הודעה לפני שלוש שעות', '--state', 'on-owner', '--note', 'מחכה')
            self.at(3 * DAY + 600, 'new', 'e2e-swt-days', 'נושא של ימים', '--state', 'working', '--note', 'שקט', '--by', 'e2e')
            self.at(3 * DAY, 'say', 'e2e-swt-days', '--from', 'fork', 'הודעה לפני שלושה ימים', '--state', 'working', '--note', 'שקט')
            self.at(2 * HOUR, 'new', 'e2e-swt-long', 'נושא עם שם ארוך מאוד מאוד שלא נגמר אף פעם ונמשך ונמשך עד קצה המסך ועוד הלאה',
                    '--state', 'working', '--note', 'הערה ארוכה מאוד שגם היא לא נגמרת ונמשכת ונמשכת עד הקצה', '--by', 'e2e')

    def check_times(self, times):
        self.assertIn(times.get('e2e-swt-min'), ('12 דק׳', '13 דק׳'), times)
        self.assertEqual(times.get('e2e-swt-hour'), '3 שע׳', times)
        self.assertEqual(times.get('e2e-swt-days'), '3 ימים', times)
        self.assertEqual(times.get('e2e-swt-long'), '2 שע׳', times)
        # every thread row has its time, the very words of the page's own rule (the sidebar's)
        same = self.browser.eval('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row[data-id]")].filter(r=>(r.querySelector(".sw-time")||{}).textContent!==agoShort(lastShown(thread(r.dataset.id)),now())).map(r=>r.dataset.id))')
        self.assertEqual(same, [])
        # and the sidebar row of the same thread says the same
        side = self.browser.eval('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row[data-id]")].map(r=>{const s=document.querySelector(\'#channels .ch[data-id="\'+CSS.escape(r.dataset.id)+\'"] .ch-time\');return s?[r.dataset.id,s.textContent,r.querySelector(".sw-time").textContent]:null;}).filter(x=>x&&x[1]!==x[2]))')
        self.assertEqual(side, [])

    def test_every_thread_row_says_how_long_ago_and_a_command_says_nothing_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open(size, 'e2e-swt-min')
                times = self.palette('')
                self.check_times(times)
                # a command row has no time, nothing typed or typed
                self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll("#sw-results .sw-act .sw-time").length)'), 0)
                self.assertGreater(self.browser.eval('JSON.stringify(document.querySelectorAll("#sw-results .sw-act").length)'), 3)
                self.assertEqual(self.browser.eval(LAYOUT), [], size)
                # found by a word: the same time
                self.palette('נושא של')
                self.check_times(self.browser.eval(TIMES))
                self.palette('settings')
                self.assertEqual(self.browser.eval('JSON.stringify(document.querySelectorAll("#sw-results .sw-act .sw-time").length)'), 0)
                # a long title is cut before the time, which stays whole
                self.palette('ארוך מאוד')
                self.assertEqual(self.browser.eval(TIMES).get('e2e-swt-long'), '2 שע׳')
                self.assertEqual(self.browser.eval(LAYOUT), [], size)
                cut = self.browser.eval('JSON.stringify((()=>{const t=document.querySelector(\'#sw-results .sw-row[data-id="e2e-swt-long"] .sw-title\');return t.scrollWidth>t.clientWidth;})())')
                self.assertTrue(cut, 'the long title is cut with an ellipsis')
                shots = os.environ.get('SWTIMES_SHOTS')
                if shots:
                    os.makedirs(shots, exist_ok=True)
                    self.palette('')
                    self.browser.run('screenshot', os.path.join(shots, 'swtimes-%d.png' % size[1]))
                self.browser.eval('(()=>{closeSwitcher();return "ok";})()')

    def test_the_times_move_on_while_the_palette_is_open_and_the_choice_stays(self):
        self.open(SIZES[2], 'e2e-swt-min')
        self.assertEqual(self.browser.eval('JSON.stringify(swTickMs)'), 30000, 'every 30 seconds')
        self.browser.eval('(()=>{swTickMs=300;return "ok";})()')
        try:
            self.palette('')
            self.browser.press('ArrowDown', 2)
            before = self.browser.eval('JSON.stringify((()=>{const a=document.querySelector("#sw-results .sw-row.active");a.dataset.mark="kept";return {i:switchIndex,id:a.dataset.id||a.innerText.trim(),top:results.scrollTop};})())')
            # two hours later on this clock
            self.browser.eval('(()=>{window.__realNow=window.__realNow||Date.now;const real=window.__realNow;Date.now=()=>real.call(Date)+2*3600e3;return "ok";})()')
            self.browser.wait('JSON.stringify((document.querySelector(\'#sw-results .sw-row[data-id="e2e-swt-min"] .sw-time\')||{}).textContent==="2 שע׳")', what='the time moved on')
            self.assertEqual(self.browser.eval(TIMES).get('e2e-swt-hour'), '5 שע׳')
            after = self.browser.eval('JSON.stringify((()=>{const a=document.querySelector("#sw-results .sw-row.active");return {i:switchIndex,id:a.dataset.id||a.innerText.trim(),top:results.scrollTop,kept:a.dataset.mark==="kept"};})())')
            self.assertEqual({k: after[k] for k in ('i', 'id', 'top')}, before)
            self.assertTrue(after['kept'], 'the rows were not drawn again under his choice')
            # closed, it stops
            self.browser.eval('(()=>{closeSwitcher();return "ok";})()')
            self.browser.wait('JSON.stringify(switcher.hidden&&!swTick)', what='the clock of the palette stopped')
        finally:
            self.browser.eval('(()=>{if(window.__realNow)Date.now=window.__realNow;swTickMs=30000;return "ok";})()')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in SwitcherTimes.__dict__:
        setattr(SwitcherTimes, _name, None)


if __name__ == '__main__':
    unittest.main()
