#!/usr/bin/env python3
"""End to end: the live dot (task 111, thread suda m338 to m342).

Every thread card shows what its agent is doing right now: 🟢 working on this thread (and on what), 🟡 working
on another thread, ⚪ resting, 🔴 stuck (waiting for an approval, at its usage limit, near the end of its
context, an API error). The hook (live_hook.py) writes live.json beside the state; the page reads it while it
is on the screen. The head of a thread has a live chip; a press opens a small card with "open the window" and
"send continue", which reach tuios through the server (op nudge).

The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board). tuios
is stood in for by a script that writes what it was asked to a file.
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
P4 = 'dddddddd-1111-2222-3333-444444444444'
DOT = 'JSON.stringify([...document.querySelectorAll("#channels .ch")].map(b=>[b.dataset.id,(b.querySelector(".live-dot")||{dataset:{}}).dataset.live||""]))'


class Live(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        cls.tuios_dir = Path(tempfile.mkdtemp(prefix='threads-e2e-tuios-'))
        stub = cls.tuios_dir / 'tuios.py'
        stub.write_text(TUIOS, encoding='utf-8')
        cls.asked = cls.tuios_dir / 'asked.jsonl'
        os.environ['THREADS_TUIOS_CMD'] = shlex.join([sys.executable, str(stub), str(cls.asked)])
        try:
            super().setUpClass()
        except BaseException:
            os.environ.pop('THREADS_TUIOS_CMD', None)
            shutil.rmtree(cls.tuios_dir, ignore_errors=True)
            raise
        # T1: two agents on it. T2: its owner works on T1. T3: its agent is at its limit. T4: its owner rests.
        # T5: nobody we know.
        for tid, title in (('lv-one', 'נקודה אחת'), ('lv-two', 'נקודה שתיים'), ('lv-three', 'נקודה שלוש'), ('lv-four', 'נקודה ארבע'), ('lv-five', 'נקודה חמש')):
            cls.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        cls.ok('task', 'add', 'lv-two', 'משימה של בטא', '--owner', 'beta')
        cls.ok('state', 'lv-four', 'working', '--note', 'x', '--by', 'delta')
        cls.ok('task', 'add', 'lv-five', 'משימה של מישהו שלא קיים', '--owner', 'ghost')

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            os.environ.pop('THREADS_TUIOS_CMD', None)
            shutil.rmtree(cls.tuios_dir, ignore_errors=True)

    def setUp(self):
        self.write_live([
            {'pane': P1, 'name': 'alpha', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'lv-one', 'by': '', 'what': 'מריץ בדיקות', 'ts': time.time() - 30},
            {'pane': P2, 'name': 'beta', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'lv-one', 'by': '', 'what': 'עורך suda.html', 'ts': time.time() - 5},
            {'pane': P3, 'name': 'gamma', 'session': 'orbit', 'state': 'stuck', 'why': 'limit', 'thread': 'lv-three', 'by': '', 'what': '', 'ts': time.time() - 600, 'resets': '3am'},
            {'pane': P4, 'name': 'delta', 'session': 'tools', 'state': 'idle', 'why': '', 'thread': '', 'by': '', 'what': '', 'ts': time.time() - 3600},
        ])
        if self.asked.exists():
            self.asked.unlink()
        nudges = Path(self.tmp.name) / '.threads-config' / test_e2e.SLUG / 'nudges.json'
        if nudges.exists():
            nudges.unlink()         # a press of an earlier scenario does not count against this one

    def write_live(self, agents):
        body = json.dumps({'version': 1, 'ts': time.time(), 'agents': agents}, ensure_ascii=False)
        tmp = self.board / '.live.tmp'
        tmp.write_text(body, encoding='utf-8')
        os.replace(tmp, self.board / 'live.json')

    def asks(self):
        return [json.loads(line) for line in self.asked.read_text(encoding='utf-8').splitlines()] if self.asked.is_file() else []

    def dots(self):
        return dict(self.browser.eval(DOT))

    # ── the server: op nudge ─────────────────────────────────────────────────

    def test_the_server_opens_a_window_and_sends_continue_through_tuios(self):
        self.needs('nudge')
        status, result, receipt = self.post({'op': 'nudge', 'pane': P1, 'action': 'open'})
        self.assertEqual((status, receipt.get('ok'), receipt.get('sent')), (200, True, True), result)
        self.assertEqual(self.asks(), [['switch-session', 'tools'], ['focus-window', '-s', 'tools', P1]])
        # continue: only to an agent that is not working, as mail to its own pane, naming the thread it was on
        status, result, receipt = self.post({'op': 'nudge', 'pane': P3, 'action': 'continue', 'thread': 'lv-three'})
        self.assertEqual(receipt.get('ok'), True, result)
        last = self.asks()[-1]
        self.assertEqual(last[:5], ['send-agent-message', '-s', 'orbit', '-w', P3])
        self.assertIn('continue', last[5])
        self.assertIn('lv-three', last[5])
        # a second press within seconds does not send it again
        status, result, receipt = self.post({'op': 'nudge', 'pane': P3, 'action': 'continue', 'thread': 'lv-three'})
        self.assertEqual(receipt.get('ok'), False, result)
        self.assertEqual(len(self.asks()), 3)

    def test_the_server_refuses_what_is_not_a_live_agent_or_not_an_action(self):
        self.needs('nudge')
        for op in ({'op': 'nudge', 'pane': 'eeeeeeee-1111-2222-3333-444444444444', 'action': 'open'},      # not in live.json
                   {'op': 'nudge', 'pane': P1, 'action': 'rm -rf'},
                   {'op': 'nudge', 'pane': '../x', 'action': 'open'},
                   {'op': 'nudge', 'pane': P1, 'action': 'continue'},       # it is working: nothing to continue
                   {'op': 'nudge', 'pane': P4, 'action': 'continue', 'thread': 'Bad id'},
                   {'op': 'nudge', 'action': 'open'}):
            status, result, receipt = self.post(op)
            self.assertEqual(receipt.get('ok'), False, (op, result))
        self.assertEqual(self.asks(), [])
        # the state is never rewritten by a nudge
        before = (self.board / 'state.json').stat().st_mtime_ns
        self.post({'op': 'nudge', 'pane': P4, 'action': 'open'})
        self.assertEqual((self.board / 'state.json').stat().st_mtime_ns, before)

    # ── the page ─────────────────────────────────────────────────────────────

    def test_every_card_shows_its_agents_live_state_at_every_size(self):
        want = {'lv-one': 'here', 'lv-two': 'elsewhere', 'lv-three': 'stuck', 'lv-four': 'idle', 'lv-five': ''}
        for size in SIZES:
            with self.subTest(size=size[0]):
                self.open(size)
                self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot"))', what='the live dots')
                dots = self.dots()
                self.assertEqual({k: dots.get(k) for k in want}, want)
                label = self.browser.eval('JSON.stringify(document.querySelector("#channels .ch[data-id=lv-one]").getAttribute("aria-label"))')
                self.assertIn('alpha', label)
        self.browser.run('screenshot', '/tmp/worker-b-list.png')

    def test_the_dots_follow_live_json_without_a_reload(self):
        self.open(SIZES[2])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-four] .live-dot[data-live=idle]"))', what='the first dots')
        self.browser.eval('(()=>{window.__mark=1;return "ok"})()')
        self.write_live([{'pane': P4, 'name': 'delta', 'session': 'tools', 'state': 'working', 'why': '', 'thread': 'lv-four', 'by': '', 'what': 'כותב', 'ts': time.time()}])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-four] .live-dot[data-live=here]"))', timeout=12, what='the dot to turn green')
        self.assertEqual(self.browser.eval('JSON.stringify(window.__mark)'), 1, 'the page was loaded again')
        self.assertEqual(self.dots().get('lv-one'), '', 'an agent that is gone still shows')

    def test_the_head_of_a_thread_says_who_and_what_and_a_press_opens_the_window_or_sends_continue(self):
        self.needs('nudge')
        self.open_thread(SIZES[0], 'lv-one', 'נקודה אחת')
        chip = self.browser.wait('JSON.stringify((()=>{const c=document.querySelector("#h-live");return c&&!c.hidden&&c.textContent})())', what='the live chip')
        self.assertIn('beta', chip)          # the latest of the two working here comes first
        self.assertIn('עורך suda.html', chip)
        self.browser.click('#h-live')
        self.browser.wait('JSON.stringify(!!document.querySelector("#live-card:not([hidden]) [data-act=open]"))', what='the live card')
        card = self.browser.eval('JSON.stringify(document.querySelector("#live-card").innerText)')
        for words in ('alpha', 'beta', 'מריץ בדיקות'):
            self.assertIn(words, card)
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#live-card [data-act=continue]"))'),
                         'continue offered to agents that are working')
        self.browser.click('#live-card [data-pane="%s"] [data-act=open]' % P2)
        self.until(lambda: any(a[:1] == ['focus-window'] for a in self.asks()), what='tuios to be asked')
        self.assertEqual(self.asks(), [['switch-session', 'tools'], ['focus-window', '-s', 'tools', P2]])
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#live-card").hidden)', what='Esc to close the card')
        # a stuck agent: continue is offered, and a press sends it
        self.open_thread(SIZES[0], 'lv-three', 'נקודה שלוש')
        chip = self.browser.wait('JSON.stringify((()=>{const c=document.querySelector("#h-live");return c&&!c.hidden&&c.dataset.live})())', what='the stuck chip')
        self.assertEqual(chip, 'stuck')
        self.browser.click('#h-live')
        self.browser.wait('JSON.stringify(!!document.querySelector("#live-card:not([hidden]) [data-act=continue]"))', what='continue')
        self.assertIn('מגבלת השימוש', self.browser.eval('JSON.stringify(document.querySelector("#live-card").innerText)'))
        self.browser.run('screenshot', '/tmp/worker-b-card.png')
        self.browser.click('#live-card [data-act=continue]')
        self.until(lambda: any(a[:1] == ['send-agent-message'] for a in self.asks()), what='continue to be sent')
        self.browser.wait('JSON.stringify(document.body.innerText.includes("נשלח"))', what='the page to say it was sent')

    def test_a_dot_never_moves_its_row_and_sits_on_the_number(self):
        """The owner, thread suda m381: the dots blink in and out and make the list jump, and they do not sit
        symmetrically. The dot sits on the corner of the row's number: coming or going it moves nothing, and on
        the next opening the dots are there at once (this browser keeps the last picture)."""
        self.open(SIZES[1])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot"))', what='the dots')
        where = self.browser.eval('JSON.stringify((()=>{const d=document.querySelector("#channels .ch[data-id=lv-one] .live-dot");return d.parentElement.classList.contains("slot")})())')
        self.assertTrue(where, 'the dot is not on the number of its row')
        box = 'JSON.stringify((()=>{const r=document.querySelector("#channels .ch[data-id=%s]");const t=r.querySelector(".ch-title").getBoundingClientRect(),s=r.querySelector(".ch-time").getBoundingClientRect();return [Math.round(t.left),Math.round(t.top),Math.round(s.left),Math.round(s.top),Math.round(r.getBoundingClientRect().height)]})())'
        with_dot = self.browser.eval(box % 'lv-one')
        self.write_live([])         # every agent gone: the dots go, and nothing else moves
        self.browser.wait('JSON.stringify(!document.querySelector("#channels .live-dot"))', timeout=12, what='the dots to go')
        self.assertEqual(self.browser.eval(box % 'lv-one'), with_dot, 'the row moved when its dot went')
        # the next opening shows the last picture this browser saw, also before (or without) reading live.json
        self.setUp()
        self.open(SIZES[1])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot"))', timeout=12, what='the dots again')
        self.browser.run('network', 'route', '**/live.json*', '--abort')
        try:
            self.open(SIZES[1])
            self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot[data-live=here]"))', timeout=6,
                              what='the dots this browser saw last, without live.json')
        finally:
            self.browser.run('network', 'unroute', '**/live.json*', check=False)

    def test_a_failed_read_keeps_the_dots_and_a_long_one_greys_them(self):
        """Control, on thread suda m381: the dots are never cleared between reads. A read that fails (a gateway
        restarting, a server error) keeps the last picture as it was; only when the page has not been able to
        read live.json for a minute are the dots shown grey, as stale. Nothing moves either way."""
        self.open(SIZES[0])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot[data-live=here]"))', what='the dots')
        box = 'JSON.stringify((()=>{const r=document.querySelector("#channels .ch[data-id=lv-three]");const b=r.getBoundingClientRect(),t=r.querySelector(".ch-title").getBoundingClientRect();return [Math.round(b.height),Math.round(t.left),Math.round(t.top)]})())'
        before = self.browser.eval(box)
        self.browser.run('network', 'route', '**/live.json*', '--abort')
        try:
            self.browser.eval('(()=>{liveText="changed";pullLive();return "ok"})()')      # a read that fails
            time.sleep(1.5)
            self.assertEqual(self.dots().get('lv-one'), 'here', 'a failed read cleared the dots')
            self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#channels .live-dot.stale"))'), 'grey after one failed read')
            self.browser.eval('(()=>{liveOkAt-=120000;pullLive();return "ok"})()')      # no good read for two minutes
            self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one] .live-dot.stale"))', timeout=8, what='the stale grey')
            self.assertEqual(self.browser.eval(box), before, 'a row moved')
        finally:
            self.browser.run('network', 'unroute', '**/live.json*', check=False)
        self.browser.eval('(()=>{liveText=null;pullLive();return "ok"})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#channels .live-dot.stale"))', timeout=8, what='the grey to go with a good read')
        self.browser.run('screenshot', '/tmp/suda-dot-phone.png')
        self.browser.viewport(1280, 800)
        self.browser.run('screenshot', '/tmp/suda-dot-desktop.png')

    def test_an_agent_stuck_on_its_context_is_red_and_is_not_sent_continue(self):
        """Thread suda m419: an agent whose prompt no longer fits is red, says so with its real size, and gets no
        "continue" (a mail would not fit either; /compact is done in its window). The server refuses it too."""
        self.write_live([{'pane': P3, 'name': 'gamma', 'session': 'orbit', 'state': 'stuck', 'why': 'context', 'thread': 'lv-three',
                          'by': '', 'what': '', 'ts': time.time() - 60, 'tokens': 951_000}])
        self.open_thread(SIZES[0], 'lv-three', 'נקודה שלוש')
        self.browser.wait('JSON.stringify((()=>{const c=document.querySelector("#h-live");return c&&!c.hidden&&c.dataset.live==="stuck"})())', what='the red chip')
        self.browser.click('#h-live')
        self.browser.wait('JSON.stringify(!!document.querySelector("#live-card:not([hidden]) [data-act=open]"))', what='the card')
        card = self.browser.eval('JSON.stringify(document.querySelector("#live-card").innerText)')
        self.assertIn('הקונטקסט מלא', card)
        self.assertIn('951K', card)
        self.assertFalse(self.browser.eval('JSON.stringify(!!document.querySelector("#live-card [data-act=continue]"))'), 'continue offered')
        if 'nudge' in self.ops:
            status, result, receipt = self.post({'op': 'nudge', 'pane': P3, 'action': 'continue', 'thread': 'lv-three'})
            self.assertEqual(receipt.get('ok'), False, result)
        # only near its end (900K and more, or tuios says near): red, and continue is still offered
        self.browser.press('Escape')
        self.write_live([{'pane': P3, 'name': 'gamma', 'session': 'orbit', 'state': 'stuck', 'why': 'near', 'thread': 'lv-three',
                          'by': '', 'what': '', 'ts': time.time() - 60, 'tokens': 912_000}])
        self.browser.eval('(()=>{liveText=null;pullLive();return "ok"})()')
        self.browser.wait('JSON.stringify(document.querySelector("#h-live").textContent.includes("כמעט מלא"))', timeout=12, what='near')
        self.browser.click('#h-live')
        self.browser.wait('JSON.stringify(!!document.querySelector("#live-card:not([hidden]) [data-act=continue]"))', what='continue for near')

    def test_a_board_without_live_json_shows_no_dots_and_says_nothing(self):
        (self.board / 'live.json').unlink()
        self.open(SIZES[1])
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=lv-one]"))', what='the list')
        time.sleep(1.5)
        self.assertEqual(set(self.dots().values()), {''})
        self.open_thread(SIZES[1], 'lv-one', 'נקודה אחת')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#h-live").hidden)'))


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Live.__dict__:
        setattr(Live, _name, None)


if __name__ == '__main__':
    unittest.main()
