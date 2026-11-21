#!/usr/bin/env python3
"""End to end: the page says whether he is looking at Suda (the owner, thread suda m282).

"If I'm not focused on Suda, then at once": a thread that turns to him is announced on his phone through Snap
immediately, unless some page of his is looked at. Every open page therefore tells the server (op presence)
whether it is on the screen with the keys: at once when that changes, every twenty seconds while it is, and once
when it is not. The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary
board). A headless page cannot be given or denied the keys by a person, so the test says what the browser would
(document.hasFocus, visibilityState) and fires the browser's own events.

The scenarios:
  - what the page sends, and when (the server's answers are stood in for, so this runs before the server has the op);
  - with a server that has the op: its receipt, and that his looking never rewrites the state;
  - the whole road with a stand-in for his phone: while a page has his eyes the phone waits, once none has it
    rings (once, opening Suda on that thread), and a page in front that nobody touches does not count as him.
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

# His phone, stood in for: the command the server would run to ring it (`snap notify …`) writes its words to a
# file instead. A board that is not the real one reaches nobody's phone unless such a stand-in is named.
PHONE = 'import json,sys\nwith open(sys.argv[1],"a",encoding="utf-8") as f:\n    f.write(json.dumps(sys.argv[2:],ensure_ascii=False)+"\\n")\n'

# The page under a hand the test controls: whether it has the keys and is on the screen, and every presence op it
# sends (answered here as the server would). A state that does not list the op yet is read as if it did.
STAND_IN = r'''(()=>{
  window.__keys=true;window.__vis='visible';window.__sent=[];
  document.hasFocus=()=>window.__keys;
  Object.defineProperty(document,'visibilityState',{get:()=>window.__vis,configurable:true});
  const real=window.fetch.bind(window);
  window.fetch=async(url,opts)=>{
    const at=String(url);
    if(at.startsWith('/api/state')&&opts&&opts.body){
      const body=JSON.parse(opts.body);
      if(body.state&&body.state.op==='presence'){
        window.__sent.push({...body.state,keepalive:!!opts.keepalive,t:Math.round(performance.now())});
        return new Response(JSON.stringify({ok:true,applied:true,code:0,out:JSON.stringify({ok:true,op:'presence',ts:Date.now()/1000})}),{status:200,headers:{'Content-Type':'application/json'}});
      }
    }
    const r=await real(url,opts);
    if(at.startsWith('state.json')&&r.ok){const raw=await r.json();raw.ops=[...new Set([...(raw.ops||[]),'presence'])];return new Response(JSON.stringify(raw),{status:200,headers:{'Content-Type':'application/json'}});}
    return r;
  };
  return 'ok';
})()'''
SENT = 'JSON.stringify(window.__sent)'


class Presence(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    TID = 'e2e-presence'
    TITLE = 'האם הוא מסתכל'

    @classmethod
    def setUpClass(cls):
        cls.phone_dir = Path(tempfile.mkdtemp(prefix='threads-e2e-phone-'))
        stub = cls.phone_dir / 'phone.py'
        stub.write_text(PHONE, encoding='utf-8')
        cls.rang = cls.phone_dir / 'rings.jsonl'
        os.environ['THREADS_SNAP_CMD'] = shlex.join([sys.executable, str(stub), str(cls.rang)])      # before the server starts: its hook inherits it
        try:
            super().setUpClass()
        except BaseException:
            os.environ.pop('THREADS_SNAP_CMD', None)
            shutil.rmtree(cls.phone_dir, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            os.environ.pop('THREADS_SNAP_CMD', None)
            shutil.rmtree(cls.phone_dir, ignore_errors=True)

    def rings(self):
        return [json.loads(line) for line in self.rang.read_text(encoding='utf-8').splitlines()] if self.rang.is_file() else []

    def on_suda(self):
        return json.loads(self.ok('notify'))['on_suda']

    def fire(self, js):
        self.browser.eval('(()=>{%s;return "ok";})()' % js)

    def sent(self, n, what):
        """Wait until the page has sent `n` presence ops; give them back."""
        self.browser.wait('JSON.stringify(window.__sent.length>=%d)' % n, timeout=12, what=what)
        return self.browser.eval(SENT)

    def test_the_page_says_when_he_looks_at_it_and_when_he_stops(self):
        self.ok('new', self.TID, self.TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], self.TID, self.TITLE)
        self.browser.eval(STAND_IN)
        self.fire('presenceLast=null;refresh()')        # whatever the page said before the test took its hand: it says it again
        # 1. the page is on the screen with the keys: it says so once, with its own name, the thread and how long since he touched it
        first = self.sent(1, 'the first word about his presence')[0]
        self.assertEqual((first['op'], first['focused'], first['thread'], first['keepalive']), ('presence', True, self.TID, False))
        self.assertRegex(first['page'], r'^[0-9a-z]{12}$')
        self.assertIsInstance(first['idle'], int)
        self.assertEqual(set(first) - {'keepalive', 't'}, {'op', 'page', 'focused', 'thread', 'idle'})
        # 2. it is not said again while nothing changed (the next beat is twenty seconds away)
        time.sleep(6.5)
        self.assertEqual(len(self.browser.eval(SENT)), 1, 'a second word within a few seconds')
        # 3. twenty seconds on, still looked at: the beat (the clock is moved instead of waited for)
        self.fire('presenceLast.at-=20000')
        beat = self.sent(2, 'the beat while he looks')[1]
        self.assertEqual((beat['focused'], beat['page']), (True, first['page']))
        # 4. the keys go elsewhere: said at once, with no thread, and then nothing more
        self.fire('window.__keys=false;window.dispatchEvent(new Event("blur"))')
        gone = self.sent(3, 'the word that he stopped looking')[2]
        self.assertEqual((gone['focused'], gone['thread'], gone['page']), (False, '', first['page']))
        self.fire('presenceLast.at-=60000')
        time.sleep(6.5)
        self.assertEqual(len(self.browser.eval(SENT)), 3, 'a page that is not looked at went on talking')
        # 5. back: said at once
        self.fire('window.__keys=true;window.dispatchEvent(new Event("focus"))')
        back = self.sent(4, 'the word that he is back')[3]
        self.assertEqual((back['focused'], back['thread']), (True, self.TID))
        # 6. the page goes off the screen (another tab, the phone's home): no, at once
        self.fire('window.__vis="hidden";document.dispatchEvent(new Event("visibilitychange"))')
        hidden = self.sent(5, 'the word that the page is off the screen')[4]
        self.assertFalse(hidden['focused'])
        self.fire('window.__vis="visible";document.dispatchEvent(new Event("visibilitychange"))')
        self.assertTrue(self.sent(6, 'the word that the page is on the screen again')[5]['focused'])
        # 7. the page is closing: its last word is "no", sent so that it survives the page
        self.fire('window.dispatchEvent(new Event("pagehide"))')
        last = self.sent(7, 'the last word of a closing page')[6]
        self.assertEqual((last['focused'], last['keepalive']), (False, True))
        # 8. his hand on the page is counted: the seconds since he last touched it grow while he rests, and start
        #    again with a key, a finger, a mouse that moves (the server stops counting a page left untouched)
        said = lambda before: self.browser.eval('(()=>{%s;window.__sent.length=0;presenceLast=null;sayPresence(false);return JSON.stringify(window.__sent[0]);})()' % before)
        rested = said('lastInput=Date.now()-90000')
        self.assertTrue(rested['focused'] and 89 <= rested['idle'] <= 92, rested)
        for event in ('new KeyboardEvent("keydown",{key:"Shift",bubbles:true})', 'new PointerEvent("pointermove",{bubbles:true})', 'new Event("touchmove",{bubbles:true})', 'new WheelEvent("wheel",{bubbles:true})'):
            touched = said('lastInput=Date.now()-90000;document.body.dispatchEvent(%s)' % event)
            self.assertLessEqual(touched['idle'], 1, event)
        # a scroll the page made itself is not his hand
        still = said('lastInput=Date.now()-90000;scroller.dispatchEvent(new Event("scroll"))')
        self.assertGreaterEqual(still['idle'], 89)

    def test_a_page_says_nothing_to_a_server_that_does_not_have_the_op(self):
        if 'presence' in self.ops:
            self.skipTest('this server has the op')
        self.ok('new', 'e2e-presence-old', 'שרת בלי presence', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-presence-old', 'שרת בלי presence')
        self.browser.eval('(()=>{window.__posts=[];const real=window.fetch.bind(window);window.fetch=(url,opts)=>{if(String(url).startsWith("/api/state")&&opts&&opts.body)window.__posts.push(JSON.parse(opts.body).state.op);return real(url,opts);};'
                          'document.hasFocus=()=>true;window.dispatchEvent(new Event("focus"));return "ok";})()')
        time.sleep(6.5)
        self.assertNotIn('presence', self.browser.eval('JSON.stringify(window.__posts)'))

    def test_the_server_takes_what_the_page_says(self):
        """With a server that has the op. What it keeps is its own business (a private file, not served): the page
        only learns that its word was taken, from the receipt."""
        self.needs('presence')
        self.ok('new', 'e2e-presence-real', 'presence מול השרת', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-presence-real', 'presence מול השרת')
        # the page's own first words about the thread (it has seen it) are on the server before the state is watched
        self.until(lambda: self.thread('e2e-presence-real').get('seen') is not None, what='the server to hear that he saw the thread')
        self.browser.wait('JSON.stringify(seenOnWay.size===0||[...seenOnWay.values()].every(x=>x.done))', what='nothing of the page on its way')
        time.sleep(1)
        state_before = (self.board / 'state.json').stat().st_mtime_ns
        # every presence op of the page, with the server's own answer to it
        self.browser.eval(r'''(()=>{
          window.__keys=true;window.__answers=[];document.hasFocus=()=>window.__keys;
          const real=window.fetch.bind(window);
          window.fetch=async(url,opts)=>{
            const r=await real(url,opts);
            if(String(url).startsWith('/api/state')&&opts&&opts.body){
              const state=JSON.parse(opts.body).state;
              if(state&&state.op==='presence'){const body=await r.clone().json();let receipt=null;try{receipt=JSON.parse(String(body.out).trim().split('\n').pop());}catch{}
                window.__answers.push({sent:state,status:r.status,ok:body.ok,applied:body.applied,receipt});}
            }
            return r;
          };
          presenceLast=null;window.dispatchEvent(new Event('focus'));return 'ok';
        })()''')
        answers = lambda n, what: (self.browser.wait('JSON.stringify(window.__answers.length>=%d)' % n, timeout=20, what=what), self.browser.eval('JSON.stringify(window.__answers)'))[1]
        yes = answers(1, 'the server\'s answer to "he looks"')[0]
        self.assertEqual((yes['status'], yes['ok'], yes['applied']), (200, True, True), yes)
        self.assertEqual((yes['sent']['focused'], yes['sent']['thread']), (True, 'e2e-presence-real'))
        self.assertEqual((yes['receipt'].get('ok'), yes['receipt'].get('op'), yes['receipt'].get('focused')), (True, 'presence', True), yes)
        self.browser.eval('(()=>{window.__keys=false;window.dispatchEvent(new Event("blur"));return "ok";})()')
        no = answers(2, 'the server\'s answer to "he stopped looking"')[1]
        self.assertEqual((no['ok'], no['applied'], no['receipt'].get('focused')), (True, True, False), no)
        # his looking and not looking never rewrites the board's state, and is not served to any page
        self.assertEqual((self.board / 'state.json').stat().st_mtime_ns, state_before, 'a presence op rewrote the state')
        self.assertFalse((self.board / 'presence.json').exists(), 'what the server knows about his presence is in the served folder')

    def test_his_phone_waits_while_a_page_has_his_eyes_and_rings_when_none_has(self):
        """The whole road: the real page, the real server, and a stand-in for his phone."""
        self.needs('presence')
        self.assertIn(str(self.rang), self.env.get('THREADS_SNAP_CMD', ''), 'the phone is not stood in for: this test would ring a real one')
        self.ok('notify', '--snap', 'on', '--url', self.url)
        self.addCleanup(self.ok, 'notify', '--snap', 'off')
        self.ok('new', 'e2e-eyes-here', 'הנושא שהוא מסתכל עליו', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.ok('new', 'e2e-eyes-far', 'נושא אחר שפונה אליו', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-eyes-here', 'הנושא שהוא מסתכל עליו')
        # he looks at Suda: the page has the keys and his hand was just on it
        self.browser.eval('(()=>{window.__keys=true;document.hasFocus=()=>window.__keys;lastInput=Date.now();presenceLast=null;window.dispatchEvent(new Event("focus"));return "ok";})()')
        self.until(lambda: self.on_suda() is True, what='the server to know that he is on Suda')
        # 1. something lands on him in another thread: while a page has his eyes the phone waits
        self.ok('ask', 'e2e-eyes-far', 'להמשיך עם התוכנית?', '--options', 'כן,לא')
        self.ok('sweep')
        time.sleep(2)
        self.ok('sweep')
        self.assertEqual(self.rings(), [], 'his phone rang while he was looking at Suda')
        # 2. he stops looking: the phone gets it at the server's next look (the minutely timer; here a sweep)
        self.browser.eval('(()=>{window.__keys=false;window.dispatchEvent(new Event("blur"));return "ok";})()')
        self.until(lambda: self.on_suda() is False, what='the server to know that he left Suda')
        self.ok('sweep')
        ring = self.until(lambda: next(iter(self.rings()), None), what='his phone to ring once he left')
        self.assertIn('נושא אחר שפונה אליו', ' '.join(ring), ring)
        self.assertIn('url:%s#e2e-eyes-far' % self.url, ring, ring)          # the alert opens Suda on that thread
        # 3. once: the same thing does not ring again
        self.ok('sweep')
        time.sleep(1)
        self.assertEqual(len(self.rings()), 1, self.rings())
        # 4. a page in front that nobody touches is a window before an empty chair: it does not count as him
        self.browser.eval('(()=>{window.__keys=true;lastInput=Date.now();window.dispatchEvent(new Event("focus"));return "ok";})()')
        self.until(lambda: self.on_suda() is True, what='the server to know that he is back')
        self.browser.eval('(()=>{lastInput=Date.now()-10*60000;presenceLast=null;sayPresence(false);return "ok";})()')
        self.until(lambda: self.on_suda() is False, what='the server to stop counting a page nobody touched for ten minutes')
        self.assertTrue(self.browser.eval('JSON.stringify(presenceLast.focused)'), 'the page itself still says it is in front')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Presence.__dict__:
        setattr(Presence, _name, None)


if __name__ == '__main__':
    unittest.main()
