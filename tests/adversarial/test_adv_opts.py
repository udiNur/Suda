#!/usr/bin/env python3
"""Hostile review of the option pictures (suda m453/m454): every test asserts the CORRECT outcome; a FAIL is a hole.

Same harness as test_e2e_optpics.py (headless Chrome, the real board server on loopback, a temporary board).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES
from test_e2e_optpics import OptionPictures, OPTIONS, TITLE, READER

GAL_BTN = '[...document.querySelectorAll("#reader-tools button")].find(b=>b.textContent.includes("את זו"))'
LOCAL = '(()=>JSON.stringify((optimistic.get(%s)||[]).map(m=>({answers:m.answers||null,late:m.late||null,text:m.text,delivery:m.delivery}))))()'


class HostileOptionPictures(OptionPictures):

    def local(self, tid):
        return self.browser.eval(LOCAL % json.dumps(tid))

    def open_gallery_from_log(self, size, tid, index=1):
        self.open_at(size, tid)
        self.browser.eval('(()=>{[...document.querySelectorAll("#log .opts.tiles .opt-card")][%d].querySelector(".opt-pic").click();return "ok";})()' % index)
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body .pager"))', what='the gallery of the options')

    def open_gallery_from_form(self, size, tid, index=1):
        self.ask(tid, multi=True)
        self.open_thread(size, tid, TITLE)
        self.browser.wait('JSON.stringify(synced&&!thread(%s).partial&&!!thread(%s).question)' % (json.dumps(tid), json.dumps(tid)), what='the question')
        self.browser.eval('(()=>{openAnswer();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#answer").hidden&&document.querySelectorAll("#answer .pick.tile").length===3)', what='the form of ticks')
        self.browser.eval('(()=>{document.querySelectorAll("#answer .pick.tile")[%d].querySelector(".opt-pic").click();return "ok";})()' % index)
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body .pager"))', what='the gallery from the form')

    # ── a question that is no longer open ──
    def test_gallery_button_does_not_answer_a_question_replaced_while_it_was_open(self):
        """The gallery's 'בחר את זו' closure is built at render time; the agent asks a new question while the
        gallery is open. Pressing it must not answer the old question (the log's own buttons are disabled by now)."""
        tid = 'adv-opts-stale'
        self.ask(tid)
        self.open_gallery_from_log(SIZES[2], tid)
        old = self.browser.eval('JSON.stringify(thread(%s).question.id)' % json.dumps(tid))
        self.ok('ask', tid, 'שאלה חדשה?', '--options', 'כן,לא', '--replace', old)      # suda m508: only --replace takes one back
        self.browser.wait('JSON.stringify(thread(%s).question&&thread(%s).question.id!==%s)' % (json.dumps(tid), json.dumps(tid), json.dumps(old)), what='the new question')
        time.sleep(0.5)
        state = self.browser.eval('JSON.stringify({open:!document.querySelector("#reader").hidden,btn:!!(%s)})' % GAL_BTN)
        if state['open'] and state['btn']:
            self.browser.eval('(()=>{%s.click();return "ok";})()' % GAL_BTN)
            time.sleep(0.3)
        sent = [m for m in self.local(tid) if m['answers'] == old]
        self.assertFalse(sent, 'the gallery answered a question that is no longer open: %s (reader %s)' % (sent, state))

    # ── answering twice ──
    def test_phone_double_tap_on_the_tick_button_in_the_gallery_keeps_it_ticked(self):
        """On a phone closeReader() is history.back(): the gallery stays on screen until popstate, so a quick
        second tap on 'סמן את זו' runs again and toggles the tick back off."""
        tid = 'adv-opts-dbl'
        self.open_gallery_from_form(SIZES[0], tid)
        got = self.browser.eval('(()=>{const b=%s;b.click();const still=b.isConnected&&!document.querySelector("#reader").hidden;if(still)b.click();return JSON.stringify(still);})()' % GAL_BTN)
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the gallery closed')
        time.sleep(0.8)
        after = self.browser.eval('JSON.stringify({second:%s,form:!document.querySelector("#answer").hidden,view:view,ticked:[...ticksOf(%s,thread(%s).question.id).ticked]})' % (json.dumps(got), json.dumps(tid), json.dumps(tid)))
        self.assertTrue(after['form'] and len(after['ticked']) == 1, 'a double tap on the gallery button: %s' % after)

    def test_phone_double_tap_in_the_gallery_sends_one_answer(self):
        tid = 'adv-opts-dbl1'
        self.ask(tid)
        self.open_gallery_from_log(SIZES[0], tid)
        self.browser.eval('(()=>{const b=%s;b.click();if(b.isConnected)b.click();return "ok";})()' % GAL_BTN)
        self.browser.wait('JSON.stringify(document.querySelector("#reader").hidden)', what='the gallery closed')
        mine = [m for m in self.local(tid) if m['answers']]
        self.assertEqual(len(mine), 1, mine)
        self.assertEqual(mine[0]['text'], OPTIONS[1])

    # ── keyboard in the gallery over the form (desktop: both overlays at once) ──
    def test_escape_in_the_gallery_over_the_form_closes_only_the_gallery(self):
        tid = 'adv-opts-esc'
        self.open_gallery_from_form(SIZES[2], tid)
        self.browser.eval('(()=>{document.querySelectorAll("#answer .pick.tile input")[0].click();return "ok";})()')
        self.browser.eval('(()=>{(document.querySelector("#reader-tools button")||document.body).focus();return "ok";})()')
        self.browser.press('Escape')
        time.sleep(0.4)
        got = self.browser.eval('JSON.stringify({reader:!document.querySelector("#reader").hidden,form:!document.querySelector("#answer").hidden,tick0:!!(document.querySelectorAll("#answer .pick.tile input")[0]||{}).checked})')
        self.assertEqual(got, {'reader': False, 'form': True, 'tick0': True}, 'Esc in the gallery over the form: %s' % got)

    def test_arrows_in_the_gallery_over_the_form_move_the_gallery(self):
        tid = 'adv-opts-arrow'
        self.open_gallery_from_form(SIZES[2], tid)
        self.browser.eval('(()=>{(document.querySelector("#reader-tools button")||document.body).focus();return "ok";})()')
        self.browser.press('ArrowLeft')
        time.sleep(0.8)
        got = self.browser.eval(READER)
        self.assertEqual(got['count'], '3 מתוך 3', 'the arrow did not move the gallery opened from the form: %s' % got)

    def test_tab_in_the_gallery_over_the_form_stays_in_the_gallery(self):
        tid = 'adv-opts-tab'
        self.open_gallery_from_form(SIZES[2], tid)
        self.browser.eval('(()=>{(%s).focus();return "ok";})()' % GAL_BTN)
        self.browser.press('Tab')
        time.sleep(0.2)
        inside = self.browser.eval('JSON.stringify(!!document.activeElement.closest("#reader"))')
        self.assertTrue(inside, 'Tab left the gallery for the form behind it: %s' % self.browser.eval('JSON.stringify(document.activeElement.outerHTML.slice(0,120))'))

    # ── another thread ──
    def test_the_gallery_closes_when_another_thread_opens(self):
        tid, other = 'adv-opts-ch', 'adv-opts-other'
        self.ok('new', other, 'שרשור אחר', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ask(tid)
        self.open_gallery_from_log(SIZES[2], tid)
        self.browser.eval('(()=>{navigate({ch:%s});return "ok";})()' % json.dumps(other))
        time.sleep(0.6)
        got = self.browser.eval('JSON.stringify({ch:view.ch,reader:!document.querySelector("#reader").hidden,btn:!!((%s)||{}).offsetParent})' % GAL_BTN)
        self.assertEqual((got['ch'], got['reader'], got['btn']), (other, False, False), got)

    # ── the strip at the top: a tap on a picture answers there ──
    def test_a_tap_on_a_picture_in_the_strip_does_not_answer(self):
        """In the log a tap on an option's picture enlarges it; in the strip at the top the same picture is part of
        the answer button, so the same gesture answers by surprise."""
        tid = 'adv-opts-pin'
        self.ask(tid)
        self.open_at(SIZES[2], tid)
        has = self.browser.eval('JSON.stringify(!document.querySelector("#pin").hidden&&!!document.querySelector("#pin button.option img"))')
        if not has:
            self.skipTest('no picture in the strip at this size')
        self.browser.eval('(()=>{document.querySelectorAll("#pin button.option img")[0].click();return "ok";})()')
        time.sleep(0.3)
        mine = [m for m in self.local(tid) if m['answers']]
        self.assertFalse(mine, 'a tap on the picture in the strip answered: %s' % mine)

    # ── digits ──
    def test_digit_two_chooses_the_second_card(self):
        tid = 'adv-opts-digit'
        self.ask(tid)
        self.open_at(SIZES[2], tid)
        self.browser.eval('(()=>{document.activeElement&&document.activeElement.blur();return "ok";})()')
        self.browser.press('2')
        time.sleep(0.4)
        mine = [m['text'] for m in self.local(tid) if m['answers']]
        self.assertEqual(mine, [OPTIONS[1]])

    # ── layout ──
    def test_cards_never_overflow_the_bubble(self):
        tid = 'adv-opts-wide'
        self.ok('new', tid, TITLE, '--state', 'working', '--note', 'x', '--by', 'e2e')
        from test_e2e import png
        from pathlib import Path
        files = []
        for i, (w, h) in enumerate(((2400, 60), (60, 2400), (320, 240))):
            p = Path(self.tmp.name) / ('shape-%d.png' % i)
            p.write_bytes(png(w, h, shade=60 + i * 60))
            files.append(p)
        opts = ['רחבה', 'גבוהה', 'סוףסוףסוףסוףסוףסוףסוףסוףסוףסוףסוףסוףסוף']
        args = ['ask', tid, 'איזו?', '--options', ','.join(opts)]
        for label, path in zip(opts, files):
            args += ['--option-image', '%s=%s' % (label, path)]
        self.ok(*args)
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open_at(size, tid)
                got = self.browser.eval('''(()=>{const row=[...document.querySelectorAll("#log .msg")].pop(),bub=row.querySelector(".opts").parentElement.getBoundingClientRect(),
                  out=[...row.querySelectorAll(".opt-card, .opt-card img, .opt-card .opt, .opt-label")].map(n=>{const r=n.getBoundingClientRect();return {c:n.className||n.tagName,l:Math.round(r.left-bub.left),r:Math.round(bub.right-r.right),h:Math.round(r.height)};}).filter(x=>x.l<-1||x.r<-1||x.h>innerHeight*.75);
                  return JSON.stringify({out,vw:innerWidth,doc:document.documentElement.scrollWidth});})()''')
                self.assertEqual(got['out'], [], got)
                self.assertLessEqual(got['doc'], got['vw'], got)


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in HostileOptionPictures.__dict__:
        setattr(HostileOptionPictures, _name, None)
for _name in OptionPictures.__dict__:
    if _name.startswith('test') and _name not in HostileOptionPictures.__dict__:
        setattr(HostileOptionPictures, _name, None)


if __name__ == '__main__':
    unittest.main()
