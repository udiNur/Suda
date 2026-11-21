#!/usr/bin/env python3
"""End to end: options that are pictures are big, chosen with a button, and enlarged in the gallery (the owner,
thread suda m453 and m454).

"When the options of a choice are pictures, I need a way to choose from a picture or to enlarge it" and "better
that they are a bit bigger, then I need to enlarge less". Before, each option was one small square button (about
100 px): a tap anywhere on it sent the answer, so there was no way to look closer first. The same harness as
test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). What is checked:

  - the pictures are big: one in a row on the cover screen (360), two in a row on the inner screen (750);
  - under each picture a button chooses it, at least 44 px tall;
  - a tap on a picture does not answer: it opens the option pictures in the gallery on that one, with a button
    "בחר את זו" that answers with the option on the screen (after a swipe too), and closes the gallery;
  - the same in the form of ticks: a tap on a picture opens the gallery, and its button ticks that item.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import time
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES, png

TID = 'e2e-optpics'
TITLE = 'בחירה בין תמונות'
OPTIONS = ['ריבוע', 'פס צר', 'תפריט']

CARDS = r'''(()=>{const row=[...document.querySelectorAll("#log .msg")].pop(),opts=row.querySelector(".opts.tiles");
  if(!opts)return JSON.stringify(null);
  const cards=[...opts.querySelectorAll(".opt-card")].map(c=>{const img=c.querySelector("img").getBoundingClientRect(),pick=c.querySelector("button.opt").getBoundingClientRect(),r=c.getBoundingClientRect();
    return {top:Math.round(r.top),w:Math.round(r.width),img:Math.round(img.width),pickH:Math.round(pick.height),pickText:c.querySelector("button.opt").textContent,label:c.textContent};});
  return JSON.stringify({width:Math.round(opts.getBoundingClientRect().width),cards});})()'''
READER = ('(()=>{const box=document.querySelector("#reader");return JSON.stringify({open:!box.hidden,gallery:!!document.querySelector("#reader-body .pager"),'
          'count:(document.querySelector("#reader-tools .gal-count")||{}).textContent||"",'
          'choose:[...document.querySelectorAll("#reader-tools button")].map(b=>b.textContent).filter(t=>t.includes("את זו"))});})()')


class OptionPictures(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def files(self):
        real = [f for f in os.environ.get('OPTPICS_IMAGES', '').split(',') if f]
        if real:
            return [Path(f) for f in real[:3]]
        out = []
        for i, shade in enumerate((30, 120, 200)):
            path = Path(self.tmp.name) / ('opt-%d.png' % i)
            path.write_bytes(png(320, 240, shade=shade))
            out.append(path)
        return out

    def ask(self, tid, multi=False):
        self.ok('new', tid, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        args = ['ask', tid, 'איזה עיצוב?', '--options', ','.join(OPTIONS)] + (['--multi'] if multi else [])
        for label, path in zip(OPTIONS, self.files()):
            args += ['--option-image', '%s=%s' % (label, path)]
        self.ok(*args)

    def open_at(self, size, tid):
        self.open_thread(size, tid, TITLE)
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&[...document.querySelectorAll("#log .opts.tiles img")].filter(i=>i.complete&&i.naturalWidth).length>=3)' % json.dumps(tid),
                          timeout=30, what='the option pictures')

    def shot(self, name):
        where = os.environ.get('OPTPICS_SHOTS')
        if where:
            if name.startswith('cards'):
                self.browser.eval('(()=>{[...document.querySelectorAll("#log .msg")].pop().querySelector(".opts").scrollIntoView({block:"start"});return "ok";})()')
                time.sleep(0.6)
            self.browser.run('screenshot', os.path.join(where, name + '.png'))

    def test_the_pictures_are_big_and_each_has_a_button_that_chooses_it(self):
        self.ask(TID)
        for size, per_row in ((SIZES[0], 1), (SIZES[1], 2)):
            with self.subTest(size=size[0]):
                self.open_at(size, TID)
                got = self.browser.eval(CARDS)
                self.assertIsNotNone(got, 'no picture options')
                cards = got['cards']
                self.assertEqual(len(cards), 3, got)
                tops = sorted({c['top'] for c in cards})
                self.assertEqual(len([c for c in cards if c['top'] == tops[0]]), per_row, got)
                for c in cards:
                    self.assertGreaterEqual(c['img'], got['width'] / per_row - 40, 'the picture is not big: %s' % got)
                    self.assertGreaterEqual(c['pickH'], 44, c)
                    self.assertIn('בחר', c['pickText'], c)
                self.shot('cards-%s' % size[0])

    def test_a_tap_on_a_picture_opens_the_gallery_and_its_button_answers(self):
        tid = TID + '-tap'
        self.ask(tid)
        self.open_at(SIZES[0], tid)
        # a tap on the second picture: nothing is sent, the gallery opens on it
        self.browser.eval('(()=>{[...document.querySelectorAll("#log .opts.tiles .opt-card")][1].querySelector(".opt-pic").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body .pager"))', what='the gallery of the options')
        got = self.browser.eval(READER)
        self.assertEqual((got['open'], got['gallery'], got['count']), (True, True, '2 מתוך 3'), got)
        self.assertEqual(len(got['choose']), 1, got)
        self.shot('gallery-cover')
        time.sleep(0.5)
        self.assertFalse([r for r in self.pending() if r.get('thread') == tid], 'a tap on the picture answered')
        # on to the third, and choose it there
        self.browser.press('ArrowLeft')
        self.browser.wait('JSON.stringify(document.querySelector("#reader-tools .gal-count").textContent==="3 מתוך 3")', what='the third picture')
        self.browser.eval('(()=>{[...document.querySelectorAll("#reader-tools button")].find(b=>b.textContent.includes("את זו")).click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the gallery closed')
        row = self.until(lambda: next((r for r in self.pending() if r.get('thread') == tid), None), what='the answer')
        self.assertEqual(row['text'], OPTIONS[2])

    def test_the_button_under_a_picture_answers(self):
        tid = TID + '-btn'
        self.ask(tid)
        self.open_at(SIZES[1], tid)
        self.browser.eval('(()=>{[...document.querySelectorAll("#log .opts.tiles .opt-card")][0].querySelector("button.opt").click();return "ok";})()')
        row = self.until(lambda: next((r for r in self.pending() if r.get('thread') == tid), None), what='the answer')
        self.assertEqual(row['text'], OPTIONS[0])

    def test_in_the_form_of_ticks_a_picture_opens_the_gallery_and_its_button_ticks(self):
        tid = TID + '-multi'
        self.ask(tid, multi=True)
        self.open_thread(SIZES[0], tid, TITLE)
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&!!thread(%s).question)' % (json.dumps(tid), json.dumps(tid)), what='the question')
        self.browser.eval('(()=>{openAnswer();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#answer").hidden&&document.querySelectorAll("#answer .pick.tile").length===3)', what='the form of ticks')
        self.browser.eval('(()=>{document.querySelectorAll("#answer .pick.tile")[1].querySelector(".opt-pic").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body .pager"))', what='the gallery from the form')
        got = self.browser.eval(READER)
        self.assertEqual((got['count'], len(got['choose'])), ('2 מתוך 3', 1), got)
        self.assertFalse(self.browser.eval('JSON.stringify(document.querySelectorAll("#answer .pick.tile input")[1].checked)'), 'the tap on the picture ticked it')
        self.browser.eval('(()=>{[...document.querySelectorAll("#reader-tools button")].find(b=>b.textContent.includes("את זו")).click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the gallery closed')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelectorAll("#answer .pick.tile input")[1].checked)'), 'the button in the gallery did not tick it')
        self.assertFalse(self.browser.eval('JSON.stringify(document.querySelector("#answer").hidden)'), 'the form closed')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in OptionPictures.__dict__:
        setattr(OptionPictures, _name, None)


if __name__ == '__main__':
    unittest.main()
