#!/usr/bin/env python3
"""Hostile review of agentkeys150: the agent keys must not break what he is typing elsewhere.

The first two scenarios are the reviewer's (a rename in the middle). The rest are the other holes it found: the
find bar, Option+A as a character while he writes (the reply box with words, the snippet dialog), a double click on
a word of an agent's row. The same harness as test_e2e_agentkeys.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e_agentkeys as ak
from test_e2e import SIZES

RENAMING = 'JSON.stringify((()=>{const r=document.querySelector("#rename-box")||renameBox;return {open:!r.hidden,focused:document.activeElement===r,value:r.value,card:!document.querySelector("#live-card").hidden};})())'
DOUBLE_CLICK = r'''(()=>{const says=document.querySelector('#live-card .lv-row[data-pane="%s"] .lv-says');
  const r=says.getBoundingClientRect(),at={bubbles:true,cancelable:true,clientX:r.left+20,clientY:r.top+5,button:0};
  says.dispatchEvent(new MouseEvent("click",{...at,detail:1}));
  const range=document.createRange();range.selectNodeContents(says);getSelection().removeAllRanges();getSelection().addRange(range);
  says.dispatchEvent(new MouseEvent("click",{...at,detail:2}));says.dispatchEvent(new MouseEvent("dblclick",{...at,detail:2}));return "ok";})()'''


class AdvAgentKeys(ak.AgentKeys):
    def _rename(self):
        self.in_box(SIZES[0], 'ak-one', 'שלושה סוכנים')
        self.browser.eval('(()=>{startRename(view.ch,false);renameBox.value="שם חדש באמצע";return "ok";})()')
        self.assertEqual(self.browser.eval(RENAMING)['focused'], True)

    def _key(self, init):
        # a synthetic keydown at the rename box, as the browser would send it; the page's handlers decide
        return self.browser.eval('(()=>{const e=new KeyboardEvent("keydown",Object.assign({bubbles:true,cancelable:true},%s));renameBox.dispatchEvent(e);return JSON.stringify(e.defaultPrevented);})()' % json.dumps(init))

    def _key_at(self, selector, init):
        return self.browser.eval('(()=>{const e=new KeyboardEvent("keydown",Object.assign({bubbles:true,cancelable:true},%s));document.querySelector(%s).dispatchEvent(e);return JSON.stringify(e.defaultPrevented);})()'
                                 % (json.dumps(init), json.dumps(selector)))

    def test_alt_a_in_the_rename_box_keeps_the_rename(self):
        self._rename()
        self._key({'code': 'KeyA', 'key': 'å', 'altKey': True})
        state = self.browser.eval(RENAMING)
        self.assertEqual(state, {'open': True, 'focused': True, 'value': 'שם חדש באמצע', 'card': False}, 'Alt+A in the rename box threw the rename away')

    def test_agent_digit_in_the_rename_box_keeps_the_rename(self):
        self._rename()
        mac = self.browser.eval('JSON.stringify(isMac)')
        self._key({'code': 'Digit1', 'key': '1', 'ctrlKey': True} if mac else {'code': 'Digit1', 'key': '1', 'altKey': True})
        state = self.browser.eval(RENAMING)
        self.assertEqual(state, {'open': True, 'focused': True, 'value': 'שם חדש באמצע', 'card': False}, 'the agent digit in the rename box threw the rename away')

    def test_agent_keys_in_the_find_bar_stay_in_the_search(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        self.browser.eval('(()=>{openFind();const q=document.querySelector("#find-q");q.value="בודקים";q.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()')
        self.browser.wait('JSON.stringify(document.activeElement===document.querySelector("#find-q"))', what='the find bar')
        mac = self.browser.eval('JSON.stringify(isMac)')
        for init in ({'code': 'KeyA', 'key': 'å', 'altKey': True}, {'code': 'Digit1', 'key': '1', 'altKey': True},
                     {'code': 'Digit2', 'key': '2', 'ctrlKey': True} if mac else {'code': 'Digit2', 'key': '2', 'altKey': True}):
            prevented = self._key_at('#find-q', init)
            state = self.browser.eval('JSON.stringify({keys:document.activeElement.id,value:document.querySelector("#find-q").value,card:!document.querySelector("#live-card").hidden})')
            self.assertEqual(state, {'keys': 'find-q', 'value': 'בודקים', 'card': False}, init)
            self.assertFalse(prevented, init)

    def test_alt_a_types_its_character_in_a_box_with_words_and_in_the_snippet_text(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        self.browser.eval('(()=>{const i=document.querySelector("#input");i.value="שלום";i.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()')
        self.assertFalse(self._key_at('#input', {'code': 'KeyA', 'key': 'å', 'altKey': True}), 'Alt+A taken from a box with words')
        self.assertFalse(self.browser.eval(ak.CARD_OPEN))
        self.browser.eval('(()=>{const i=document.querySelector("#input");i.value="";i.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()')
        # the empty box: the panel key
        self.assertTrue(self._key_at('#input', {'code': 'KeyA', 'key': 'å', 'altKey': True}), 'Alt+A not taken from the empty box')
        self.keys_on('row:' + ak.P2, 'Alt+A from the empty box')
        self.browser.press('Escape')
        self.keys_on('box', 'back in the box')
        # the snippet dialog's text: Alt+A and Alt+digit are its characters
        self.browser.eval('(()=>{openSnip(false);return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#snip").hidden)', what='the snippet dialog')
        self.browser.eval('(()=>{const t=document.querySelector("#snip-text");t.focus();t.value="לוג";return "ok";})()')
        for init in ({'code': 'KeyA', 'key': 'å', 'altKey': True}, {'code': 'Digit1', 'key': '¡', 'altKey': True}):
            self.assertFalse(self._key_at('#snip-text', init), init)
        self.assertFalse(self.browser.eval(ak.CARD_OPEN))
        self.browser.press('Escape')

    def test_a_double_click_on_a_word_of_an_agent_row_stays_in_the_thread(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        self.browser.press('Alt+Digit3')
        self.keys_on('row:' + ak.P3, 'gamma')
        self.browser.eval(DOUBLE_CLICK % ak.P3)
        time.sleep(0.8)
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), 'ak-one', "a double click on a word opened the agent's thread")
        self.browser.eval('(()=>{getSelection().removeAllRanges();return "ok";})()')
        # one click still opens it
        self.browser.click('#live-card .lv-row[data-pane="%s"] .lv-says' % ak.P3)
        self.browser.wait('JSON.stringify(view.ch==="ak-two")', what='one click to open the thread')


# Only the scenarios of this file: those of test_e2e and test_e2e_agentkeys run there.
for _name in dir(ak.AgentKeys):
    if _name.startswith('test') and _name not in AdvAgentKeys.__dict__:
        setattr(AdvAgentKeys, _name, None)


if __name__ == '__main__':
    unittest.main()
