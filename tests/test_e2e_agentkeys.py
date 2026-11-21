#!/usr/bin/env python3
"""End to end: the agents of the open thread by keyboard (the owner, suda m630; suda-fixes task 8).

"I want to reach the agents on the right with the keyboard too, preferably with the arrows and maybe with Ctrl
and a number." The agents of a thread are the live card under its live chip (fed by live.json). Alt+1..9 (and
Ctrl+1..9 on a Mac and a phone) put the keys on agent N, from the reply box too; Alt+A (or A where he is not
writing) moves the keys into the panel and back; in it up and down walk the agents, Home and End go to the first
and the last, left and right walk a row's own buttons, Enter opens the thread the agent works on, and Esc or A
give the keys back to the reply box.

The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board), with a
live.json of three agents written into the board as test_e2e_live.py does.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES

TUIOS = 'import json,sys\nwith open(sys.argv[1],"a",encoding="utf-8") as f:\n    f.write(json.dumps(sys.argv[2:],ensure_ascii=False)+"\\n")\n'
P1 = 'aaaaaaaa-1111-2222-3333-444444444444'
P2 = 'bbbbbbbb-1111-2222-3333-444444444444'
P3 = 'cccccccc-1111-2222-3333-444444444444'
NAMES = {P1: 'alpha', P2: 'beta', P3: 'gamma'}
# Where the keys are: the reply box, an agent's row, a button of a row, or somewhere else.
WHERE = '''JSON.stringify((()=>{const a=document.activeElement;if(!a||a===document.body)return "nowhere";if(a.id==="input")return "box";
  const row=a.closest&&a.closest("#live-card .lv-row");if(row)return (a===row?"row:":"btn:"+a.dataset.act+":")+row.dataset.pane;
  return (a.tagName||"")+"#"+(a.id||"");})())'''
CARD_OPEN = 'JSON.stringify(!document.querySelector("#live-card").hidden)'
# Every key that reaches the window after the page's own handler: whether the page took it (cancelled its default).
TAKEN_WATCH = '(()=>{window.__taken=[];addEventListener("keydown",e=>window.__taken.push([e.code,e.defaultPrevented]));return "ok";})()'
TAKEN = 'JSON.stringify(window.__taken)'


class AgentKeys(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        cls.tuios_dir = Path(tempfile.mkdtemp(prefix='threads-e2e-tuios-'))
        stub = cls.tuios_dir / 'tuios.py'
        stub.write_text(TUIOS, encoding='utf-8')
        os.environ['THREADS_TUIOS_CMD'] = shlex.join([sys.executable, str(stub), str(cls.tuios_dir / 'asked.jsonl')])
        try:
            super().setUpClass()
        except BaseException:
            os.environ.pop('THREADS_TUIOS_CMD', None)
            shutil.rmtree(cls.tuios_dir, ignore_errors=True)
            raise
        # ak-one: three agents (beta stuck, alpha working on it, gamma working on ak-two and owning a task here).
        # ak-quiet: nobody.
        # ak-ask: a question with answers, and two of them by their tasks (beta first: it is stuck).
        for tid, title in (('ak-one', 'שלושה סוכנים'), ('ak-two', 'הנושא של גמא'), ('ak-quiet', 'נושא שקט'), ('ak-ask', 'שאלה וסוכנים')):
            cls.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('task', 'add', 'ak-one', 'משימה של גמא', '--owner', 'gamma')
        cls.ok('task', 'add', 'ak-ask', 'משימה של אלפא', '--owner', 'alpha')
        cls.ok('task', 'add', 'ak-ask', 'משימה של בטא', '--owner', 'beta')
        cls.ok('ask', 'ak-ask', 'לאיזה כיוון?', '--options', 'ימין,שמאל')

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            os.environ.pop('THREADS_TUIOS_CMD', None)
            shutil.rmtree(cls.tuios_dir, ignore_errors=True)

    def setUp(self):
        self.write_live(self.agents())

    @staticmethod
    def agents(alpha_does='מריץ בדיקות'):
        return [
            {'pane': P1, 'name': 'alpha', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'ak-one', 'by': '', 'what': alpha_does, 'ts': time.time() - 30},
            {'pane': P2, 'name': 'beta', 'session': 'tools', 'state': 'stuck', 'why': 'limit', 'thread': 'ak-one', 'by': '', 'what': '', 'ts': time.time() - 600, 'resets': '3am'},
            {'pane': P3, 'name': 'gamma', 'session': 'demo', 'state': 'working', 'why': '', 'thread': 'ak-two', 'by': '', 'what': 'כותב', 'ts': time.time() - 5},
        ]

    def write_live(self, agents):
        body = json.dumps({'version': 1, 'ts': time.time(), 'agents': agents}, ensure_ascii=False)
        tmp = self.board / '.live.tmp'
        tmp.write_text(body, encoding='utf-8')
        os.replace(tmp, self.board / 'live.json')

    # ── helpers ───────────────────────────────────────────────────────────────

    def where(self):
        return self.browser.eval(WHERE)

    def keys_on(self, want, what):
        return self.browser.wait('JSON.stringify(%s===%s)' % (WHERE[len('JSON.stringify('):-1], json.dumps(want)), timeout=6, what=what)

    def in_box(self, size, tid, title):
        """The thread open, a hardware keyboard in use, the keys in its reply box."""
        self.open_thread(size, tid, title)
        self.browser.press('Shift')                 # a physical key: this device has a keyboard
        if tid == 'ak-one':
            self.browser.wait('JSON.stringify((()=>{const c=document.querySelector("#h-live");return !!c&&!c.hidden})())', what='the live chip')
        self.browser.eval('(()=>{document.querySelector("#input").focus();return "ok";})()')
        self.keys_on('box', 'the keys in the box')

    # ── the scenarios ─────────────────────────────────────────────────────────

    def test_alt_and_a_number_reaches_agent_n_from_the_box_and_the_arrows_walk_the_agents_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.in_box(size, 'ak-one', 'שלושה סוכנים')
                # the order of the card: stuck first, then working here, then working elsewhere
                self.browser.press('Alt+Digit2')
                self.browser.wait(CARD_OPEN, what='the card to open')
                self.keys_on('row:' + P1, 'agent 2 (alpha)')
                rows = self.browser.eval('JSON.stringify([...document.querySelectorAll("#live-card .lv-row")].map(r=>r.dataset.pane))')
                self.assertEqual(rows, [P2, P1, P3])
                self.browser.press('ArrowDown'); self.keys_on('row:' + P3, 'down to gamma')
                self.browser.press('ArrowDown'); self.keys_on('row:' + P2, 'down from the last, round to the first')
                self.browser.press('ArrowUp'); self.keys_on('row:' + P3, 'up from the first, round to the last')
                self.browser.press('Home'); self.keys_on('row:' + P2, 'Home')
                self.browser.press('End'); self.keys_on('row:' + P3, 'End')
                if 'nudge' in self.ops:
                    # left goes on into the row's own buttons (the page reads right to left), right comes back
                    self.browser.press('ArrowLeft'); self.keys_on('btn:open:' + P3, "the row's first button")
                    self.browser.press('ArrowRight'); self.keys_on('row:' + P3, 'back on the row')
                    # up and down from a button go on to the next agent's row
                    self.browser.press('ArrowLeft'); self.browser.press('ArrowUp'); self.keys_on('row:' + P1, 'up from a button')
                self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), 'ak-one', 'the arrows moved to another thread')
                if size[0] == 'desktop':
                    self.browser.run('screenshot', '/tmp/suda-agentkeys-desktop.png')
                elif size[0] == 'cover':
                    self.browser.run('screenshot', '/tmp/suda-agentkeys-cover.png')
                # Esc: the card closes and the keys are back in the reply box
                self.browser.press('Escape')
                self.browser.wait('JSON.stringify(document.querySelector("#live-card").hidden)', what='Esc to close the card')
                self.keys_on('box', 'the keys back in the box after Esc')

    def test_ctrl_and_a_number_on_a_mac_and_a_number_not_on_the_card_is_left_alone(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        if self.browser.eval('JSON.stringify(isMac)'):
            self.browser.press('Control+Digit3')
            self.browser.wait(CARD_OPEN, what='the card to open')
            self.keys_on('row:' + P3, 'Ctrl+3: gamma')
            self.browser.press('Control+Digit1'); self.keys_on('row:' + P2, 'Ctrl+1 inside the panel')
            self.browser.press('Escape'); self.keys_on('box', 'back in the box')
            # with words in the box, Option+digit is a character there (₪ on the Hebrew layout); Ctrl+digit still goes
            self.browser.run('type', '#input', 'מחיר')
            self.browser.press('Alt+Digit2')
            time.sleep(0.4)
            self.assertFalse(self.browser.eval(CARD_OPEN), 'Option+2 was taken from a text he writes')
            self.browser.press('Control+Digit2')
            self.keys_on('row:' + P1, 'Ctrl+2 from a box with words')
            self.browser.press('Escape'); self.keys_on('box', 'back in the box')
            self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#input").value.startsWith("מחיר"))'), 'the words were lost')
            self.browser.fill('#input', '')
        # a fourth agent there is not: the key is not taken (it stays the browser's or the system's), nothing moves
        self.browser.eval(TAKEN_WATCH)
        self.browser.press('Alt+Digit4')
        self.browser.wait('JSON.stringify(window.__taken.length>0)', what='the key to arrive')
        self.assertEqual(self.browser.eval(TAKEN), [['Digit4', False]], 'Alt+4 taken with three agents')
        self.assertFalse(self.browser.eval(CARD_OPEN))
        self.assertEqual(self.where(), 'box')

    def test_a_moves_the_keys_into_the_panel_and_back_and_is_a_letter_while_he_writes(self):
        self.in_box(SIZES[1], 'ak-one', 'שלושה סוכנים')
        self.browser.press('Alt+KeyA')
        self.browser.wait(CARD_OPEN, what='Alt+A to open the card')
        self.keys_on('row:' + P2, 'Alt+A: the first agent')
        self.assertEqual(self.browser.eval('JSON.stringify(document.querySelector("#input").value)'), '', 'Alt+A typed into the box')
        self.browser.press('KeyA')
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").hidden)', what='A to close the card')
        self.keys_on('box', 'A: back in the box')
        # out of the box (Esc), A alone goes into the panel; Esc comes back
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.activeElement!==document.querySelector("#input"))', what='Esc to leave the box')
        self.browser.press('KeyA')
        self.keys_on('row:' + P2, 'A: the first agent')
        self.browser.press('Escape')
        self.keys_on('box', 'Esc: back in the box')
        # in the box A is a letter
        self.browser.run('type', '#input', 'שלום')
        self.browser.eval('(()=>{window.__a=null;addEventListener("keydown",e=>{if(e.code==="KeyA")window.__a={prevented:e.defaultPrevented,box:e.target.id};});return "ok";})()')
        self.browser.press('KeyA')
        self.browser.wait('JSON.stringify(!!window.__a)', what='the key A to arrive')
        self.assertEqual(self.browser.eval('JSON.stringify(window.__a)'), {'prevented': False, 'box': 'input'}, 'A was taken from the box')
        self.assertFalse(self.browser.eval(CARD_OPEN), 'A opened the card while he writes')
        self.assertEqual(self.where(), 'box')
        self.browser.fill('#input', '')

    def test_enter_opens_the_thread_the_agent_works_on(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        # gamma works on another thread: Enter opens it
        self.browser.press('Alt+Digit3')
        self.keys_on('row:' + P3, 'gamma')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(view.ch==="ak-two")', what="gamma's thread to open")
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#live-card").hidden)'))
        self.keys_on('box', "the keys in the box of gamma's thread")
        # alpha works on this one: Enter closes the panel and the keys are in its box
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        self.browser.press('Alt+Digit2')
        self.keys_on('row:' + P1, 'alpha')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").hidden)', what='the card to close')
        self.keys_on('box', 'the keys in the box')
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), 'ak-one')
        # a click on gamma's row does what Enter does
        self.browser.press('Alt+Digit3')
        self.keys_on('row:' + P3, 'gamma again')
        self.browser.click('#live-card .lv-row[data-pane="%s"] .lv-says' % P3)
        self.browser.wait('JSON.stringify(view.ch==="ak-two")', what="a click to open gamma's thread")

    def test_the_keys_stay_on_the_agent_through_a_live_update(self):
        self.in_box(SIZES[0], 'ak-one', 'שלושה סוכנים')
        self.browser.press('Alt+Digit3')
        self.keys_on('row:' + P3, 'gamma')
        self.write_live(self.agents(alpha_does='בונה את הדף מחדש'))
        self.browser.eval('(()=>{liveText=null;pullLive();return "ok"})()')
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").innerText.includes("בונה את הדף מחדש"))', timeout=12, what='the card drawn again')
        self.assertEqual(self.where(), 'row:' + P3, 'a live update took the keys off the agent')
        # a refresh of the state (keysToBox runs after it) does not take them either
        self.browser.eval('(()=>{refresh();return "ok"})()')
        time.sleep(1.2)
        self.assertEqual(self.where(), 'row:' + P3, 'a refresh took the keys to the box')
        self.browser.press('ArrowUp'); self.keys_on('row:' + P1, 'the arrows still walk')
        # the agent the keys are on goes away: the card is drawn without it, the keys go back to the box
        self.write_live([a for a in self.agents() if a['pane'] != P1])
        self.browser.eval('(()=>{liveText=null;pullLive();return "ok"})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#live-card [data-pane=\'%s\']"))' % P1, timeout=12, what='alpha to go')
        self.browser.wait('JSON.stringify(document.activeElement===document.querySelector("#input")||!!(document.activeElement.closest&&document.activeElement.closest("#live-card .lv-row")))', timeout=6,
                          what='the keys somewhere real (the box or an agent)')
        self.browser.press('Escape')
        self.keys_on('box', 'back in the box')

    def test_a_thread_without_agents_leaves_the_keys_alone(self):
        self.in_box(SIZES[2], 'ak-quiet', 'נושא שקט')
        self.browser.eval(TAKEN_WATCH)
        for key in ('Alt+Digit1', 'Alt+KeyA'):
            self.browser.press(key)
        self.browser.wait('JSON.stringify(window.__taken.length>=2)', what='the keys to arrive')
        self.assertEqual(self.browser.eval(TAKEN), [['Digit1', False], ['KeyA', False]], 'a key taken where there is no agent')
        self.assertFalse(self.browser.eval(CARD_OPEN))
        self.assertEqual(self.where(), 'box')

    def test_an_open_question_keeps_its_digits_and_alt_digit_is_the_agent(self):
        self.in_box(SIZES[2], 'ak-ask', 'שאלה וסוכנים')
        self.browser.wait('JSON.stringify(quickAnswers().length===2&&!document.querySelector("#h-live").hidden)', what='the answers and the agents')
        self.browser.press('Alt+Digit1')
        self.keys_on('row:' + P2, 'Alt+1: the first agent, not the first answer')
        self.assertFalse(self.browser.eval('JSON.stringify(!!heldAnswer())'), 'Alt+1 answered the question')
        self.browser.press('Escape')
        self.keys_on('box', 'back in the box')
        self.browser.press('Digit2')
        self.browser.wait('JSON.stringify(!!heldAnswer())', what='2 to answer, as always')
        self.browser.press('Escape')        # taken back in its four seconds
        self.browser.wait('JSON.stringify(!heldAnswer())', what='the answer taken back')

    def test_the_help_and_the_palette_name_the_keys_and_the_agents(self):
        self.in_box(SIZES[2], 'ak-one', 'שלושה סוכנים')
        self.browser.eval('(()=>{showHelp();return "ok";})()')
        help_text = self.browser.eval('JSON.stringify(document.querySelector("#help").innerText)')
        self.assertIn('הסוכנים של הנושא', help_text)
        self.assertIn('סוכן 1 עד 9', help_text)
        self.browser.press('Escape')
        self.keys_on('box', 'back in the box after the help')
        self.browser.press('Meta+KeyK')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette')
        self.browser.fill('#sw-query', 'gamma')
        row = self.browser.wait('JSON.stringify((()=>{const r=[...document.querySelectorAll("#sw-results .sw-row.active")][0];return r&&r.innerText})())', what='a row for gamma')
        self.assertIn('סוכן 3', row)
        self.assertIn('3', row)
        self.browser.press('Enter')
        self.browser.wait(CARD_OPEN, what='the card from the palette')
        self.keys_on('row:' + P3, 'the palette put the keys on gamma')
        self.browser.press('Escape')
        self.keys_on('box', 'back in the box')
        # the panel itself, by its English or Hebrew words
        self.browser.press('Meta+KeyK')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the palette again')
        self.browser.fill('#sw-query', 'agents')
        row = self.browser.wait('JSON.stringify((()=>{const r=[...document.querySelectorAll("#sw-results .sw-row.active")][0];return r&&r.innerText})())', what='the panel command')
        self.assertIn('הסוכנים של הנושא', row)
        self.browser.press('Escape')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AgentKeys.__dict__:
        setattr(AgentKeys, _name, None)


if __name__ == '__main__':
    unittest.main()
