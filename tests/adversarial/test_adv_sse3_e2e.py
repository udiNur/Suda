#!/usr/bin/env python3
"""Hostile review of sse153, third pass (f2e433f: lineAction, lineBack, readSignal, the 1 s line timer), end to end.
Each test asserts the SAFE outcome: a failure is a real hole.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_adv_sse3_e2e.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e_resume
from test_e2e_resume import ASKED, CLEAR

# A fake EventSource that behaves as the browser's does on a given link: it opens after `openAfter` ms, speaks as a
# numbered server ("alive" with the page's number every 10 s), and after an error reconnects by itself 2 s later,
# as the browser does (unless it was closed).
FAKE_ES = r"""(()=>{
  if(!window.__realES)window.__realES=window.EventSource;
  window.__opens=0;window.__made=0;window.__all=[];
  window.EventSource=function(){
    window.__made++;
    const fake={readyState:0,listeners:{},close(){fake.readyState=2;clearInterval(fake.beat);},addEventListener(n,f){fake.listeners[n]=f;}};
    const speak=()=>{if(fake.readyState===1&&fake.listeners.alive)fake.listeners.alive({data:String(appliedNumber)});};
    fake.connect=()=>setTimeout(()=>{if(fake.readyState!==0)return;fake.readyState=1;window.__opens++;fake.onopen&&fake.onopen();speak();fake.beat=setInterval(speak,10000);},window.__openAfter);
    fake.blip=()=>{if(fake.readyState!==1)return;clearInterval(fake.beat);fake.readyState=0;fake.onerror&&fake.onerror();setTimeout(fake.connect,2000-window.__openAfter);};
    window.__all.push(fake);fake.connect();return fake;
  };
  try{events.close();}catch{}events=null;connection(false);listen();return 'ok';})()"""
REAL_ES = '(()=>{if(window.__realES)window.EventSource=window.__realES;try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()'
HIDE = r"""(()=>{
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>!!window.__hidden});
  Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__hidden?'hidden':'visible'});
  window.__hidden=true;document.dispatchEvent(new Event('visibilitychange'));return 'ok';})()"""
SHOW = '(()=>{window.__hidden=false;document.dispatchEvent(new Event("visibilitychange"));return "ok";})()'
# Requests to /api/state whose op matches: they reach the server at once (it does them), and their answer comes back
# `ms` later (a slow link); `late`: the request itself reaches the server only then (a slow upload). The page's abort stops the wait, as it would stop the real request.
SLOW_POST = r"""((ops,ms,late)=>{
  const real=window.__realFetch||(window.__realFetch=window.fetch.bind(window));window.__posts=[];
  window.fetch=(url,opts)=>{
    let op='';try{op=JSON.parse(opts&&opts.body||'{}').state.op;}catch{}
    if(String(url).includes('/api/state')&&ops.includes(op)){
      window.__posts.push({op,t:Date.now()});
      const {signal,...rest}=opts||{};const going=late?null:real(url,rest);
      return new Promise((done,fail)=>{const t=setTimeout(()=>(going||real(url,rest)).then(done,fail),ms);
        if(signal)signal.addEventListener('abort',()=>{clearTimeout(t);fail(new DOMException('aborted','AbortError'));});});
    }
    return real(url,opts);};
  return 'ok';})(%s,%d,%s)"""
REAL_FETCH = '(()=>{if(window.__realFetch)window.fetch=window.__realFetch;return "ok";})()'


class Page(test_e2e_resume.Resume):
    TID = 'adv-sse3'
    TITLE = 'בדיקה עוינת שלישית'

    def test_a_line_that_takes_four_seconds_to_open_opens(self):
        """A weak mobile link, or a relay: opening a connection takes about 4 s (TCP, TLS, the first bytes). lineAction
        reopens anything still connecting after 3 s, with no backoff: every attempt is killed before it can open."""
        self.open_board()
        self.addCleanup(self.browser.eval, REAL_ES)
        self.browser.eval('(()=>{window.__openAfter=4500;return "ok";})()')
        self.browser.eval(FAKE_ES)
        time.sleep(25)
        got = self.browser.eval('JSON.stringify({opens:window.__opens,attempts:window.__made,fresh:live.dataset.fresh})')
        self.assertGreaterEqual(got['opens'], 1, 'in 25 s the line never opened: %s' % got)

    def test_a_blip_in_a_hidden_tab_does_not_lose_the_line(self):
        """A background tab (the desktop, another tab in front). The line errs once (a Wi-Fi change, a server
        restart): the browser's EventSource is in CONNECTING and would reconnect by itself in 2 s. The 1 s timer sees
        a line "connecting" since its listen() long ago, closes it, and does not open one while the tab is hidden: the
        tab hears nothing (no title count, no notification) until he looks at it."""
        self.open_board()
        self.addCleanup(self.browser.eval, REAL_ES)
        self.addCleanup(self.browser.eval, SHOW)
        self.browser.eval('(()=>{window.__openAfter=100;return "ok";})()')
        self.browser.eval(FAKE_ES)
        self.browser.wait('JSON.stringify(window.__opens===1)', what='the fake line open')
        time.sleep(4)
        self.browser.eval(HIDE)
        self.browser.eval('(()=>{window.__all.at(-1).blip();return "ok";})()')
        time.sleep(8)
        got = self.browser.eval('JSON.stringify({open:!!events&&events.readyState===1,opens:window.__opens,made:window.__made})')
        self.assertTrue(got['open'], 'a hidden tab lost its line on one blip, and the browser was not let reconnect it: %s' % got)

    def test_a_slow_reply_lands_on_a_line_that_comes_back_every_few_seconds(self):
        """A reply whose answer takes 7 s on a slow link (a picture, a voice note, a long snippet). The line comes back
        every 5 s (the browser's reconnects on a flapping link). Each lineBack aborts every request that left more than
        1 s before: the reply is aborted and sent from the start again, forever, while the link keeps flapping."""
        self.open_board()
        self.addCleanup(self.browser.eval, REAL_FETCH)
        self.browser.eval(SLOW_POST % (json.dumps(['reply']), 7000, 'true'))
        text = 'תשובה איטית בקו מהבהב %d' % time.time()
        self.browser.fill('#input', text)
        self.browser.click('#send')
        end = time.monotonic() + 30
        while time.monotonic() < end:
            time.sleep(5)
            self.browser.eval('(()=>{try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()')
        got = self.browser.eval('JSON.stringify({m:[...optimistic.values()].flat().map(m=>({d:m.delivery,tries:m.tries,deaf:m.deaf||0,error:m.error||""})),posts:window.__posts.length})')
        self.browser.eval(REAL_FETCH)
        mine = [m for m in got['m']]
        self.assertTrue(any(m['d'] == 'received' for m in mine) or not mine,
                        'after 30 s of a line coming back every 5 s, the 7 s reply never landed on the page: %s' % got)
        # and it is never doubled, whatever the aborts did
        self.until(lambda: [m['text'] for m in self.thread(self.TID)['messages']].count(text) >= 1, timeout=40, what='the reply in the state')
        time.sleep(2)
        self.assertEqual([m['text'] for m in self.thread(self.TID)['messages']].count(text), 1)

    def test_a_task_press_the_server_saved_is_never_called_not_saved(self):
        """He ticks a task; the server does it, its answer is slow. The line comes back meanwhile: lineBack aborts the
        press, the page puts the old state back and says "not saved, the previous state was put back", while the
        board has it saved. Tasks are not sent again."""
        if 'adv-task' not in json.dumps(self.thread(self.TID).get('tasks', []), ensure_ascii=False):
            self.ok('task', 'add', self.TID, 'adv-task משימה')
        self.open_board()
        self.addCleanup(self.browser.eval, REAL_FETCH)
        n = [k['n'] for k in self.thread(self.TID)['tasks'] if 'adv-task' in k['text']][0]
        self.browser.eval(SLOW_POST % (json.dumps(['task']), 4000, 'false'))
        self.browser.eval('(()=>{window.__toasts=[];const real=toast;toast=(t,...r)=>{window.__toasts.push(String(t));return real(t,...r);};'
                          'setTask(%s,%d,"done");return "ok";})()' % (json.dumps(self.TID), n))
        time.sleep(2)
        self.browser.eval('(()=>{try{events.close();}catch{}events=null;connection(false);listen();return "ok";})()')
        time.sleep(5)
        saved = [k['status'] for k in self.thread(self.TID)['tasks'] if k['n'] == n][0]
        toasts = self.browser.eval('JSON.stringify(window.__toasts)')
        said_failed = [t for t in toasts if 'הוחזר' in t]
        self.assertFalse(saved == 'done' and said_failed, 'the server saved the task (%s) and the page said: %s' % (saved, said_failed))

    def test_an_idle_good_link_costs_no_reading_and_no_reopen_in_a_minute(self):
        self.open_board()
        time.sleep(3)
        self.browser.eval(CLEAR)
        self.browser.eval('(()=>{window.__esMade=0;const R=window.EventSource;window.__realES=window.__realES||R;'
                          'window.EventSource=function(...a){window.__esMade++;return new R(...a);};return "ok";})()')
        self.addCleanup(self.browser.eval, '(()=>{window.EventSource=window.__realES;return "ok";})()')
        time.sleep(60)
        asked = self.browser.eval(ASKED)
        made = self.browser.eval('JSON.stringify(window.__esMade)')
        self.assertEqual((asked, made), ([], 0), 'an idle minute on a good link')


for _name in dir(test_e2e_resume.Resume):
    if _name.startswith('test') and _name not in Page.__dict__:
        setattr(Page, _name, None)


if __name__ == '__main__':
    unittest.main()
