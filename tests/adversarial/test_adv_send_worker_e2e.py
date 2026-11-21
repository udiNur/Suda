#!/usr/bin/env python3
"""Hostile review of a9b8304..e40e44e, in a real browser: the worker from BEFORE the rule hands a page over to the
worker with the rule.

Every board that is installed today has the old worker (no rules: every request of the page waits for it). The
change reaches such a board as a new sw.js beside an already open page. One scenario is played once (old worker
in charge, a reply; the new worker is published and takes the open page over; a reply from that same page; the
page is opened again; a reply), and the tests read what was seen at each step.

A test named `test_held_...` is an attack the code withstood; any other test asserts the correct outcome of a
suspected hole, so a FAILING test is a real hole. The harness is test_e2e.py's own: headless Chrome through
agent-browser, the real board server on 127.0.0.1 and a free port, a temp board inside this worktree, a mail
recorder. Only that temp board's copy of sw.js is replaced; nothing of the repository is written. The new worker
is published there as the repository's sw.js with two lines before it (PROBE) that list the requests its fetch
event was given: a listener of its own, ahead of the worker's (respondWith() ends the event for the listeners
after it), which changes nothing of what the worker answers or of its rule. Run:

    THREADS_NOTIFY=0 python3 -m unittest test_adv_send_worker_e2e -v
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import subprocess
import time
import unittest

import test_e2e
from test_e2e import SIZES

BEFORE = 'a9b8304'
TID, TITLE = 'e2e-handover', 'מה-worker הישן לחדש'
OLD_WORDS, TAKEN_WORDS, LOADED_WORDS = 'הודעה דרך ה-worker הישן', 'הודעה אחרי שה-worker הוחלף', 'הודעה אחרי פתיחה מחדש'
# the way the last request to an address took: [the rule that matched, who answered, did it wait for the worker]
ROUTE = ('JSON.stringify(performance.getEntriesByType("resource").filter(e=>new URL(e.name).pathname.endsWith(%s)).map(e=>[e.workerMatchedSourceType,e.workerFinalSourceType,e.workerStart>0]).slice(-1)[0]||null)')
# what the worker's fetch event was given since it was last asked (see PROBE); null when the worker did not answer
PROBE = ("'use strict';\nself.__adv=[];self.addEventListener('fetch',e=>{self.__adv.push(e.request.method+' '+new URL(e.request.url).pathname);});"
         "self.addEventListener('message',e=>{if(e.data==='adv-seen'&&e.source)e.source.postMessage({kind:'adv-seen',seen:self.__adv.splice(0)});});\n")
OWN = ('GET /%s/suda.html' % test_e2e.SLUG, 'HEAD /%s/suda.html' % test_e2e.SLUG)       # the page's own file: the worker's business
GIVEN = ('(async()=>{const got=new Promise(done=>{const hear=e=>{if(e.data&&e.data.kind==="adv-seen"){navigator.serviceWorker.removeEventListener("message",hear);done(e.data.seen);}};'
         'navigator.serviceWorker.addEventListener("message",hear);});navigator.serviceWorker.controller.postMessage("adv-seen");'
         'return JSON.stringify(await Promise.race([got,new Promise(done=>setTimeout(()=>done(null),8000))]));})()')
# every page action the page sends from now on, and how it ended
WATCH = r"""(()=>{
  window.__page=1;window.__changes=0;window.__posts=[];
  navigator.serviceWorker.addEventListener('controllerchange',()=>{window.__changes++;});
  const real=window.fetch.bind(window);
  window.fetch=async(url,opts)=>{
    if(!String(url).startsWith('/api/state'))return real(url,opts);
    let op='?';try{op=JSON.parse(opts.body).state.op;}catch{}
    const row={op,at:Math.round(performance.now()),end:'pending'};window.__posts.push(row);
    try{const r=await real(url,opts);row.end=r.status;return r;}catch(e){row.end='failed: '+e;throw e;}
  };
  return 'ok';
})()"""


class Handover(test_e2e.Suda):
    """Only the scenario of this file: the ones inherited from test_e2e run there."""

    seen = None

    @classmethod
    def setUpClass(cls):
        old = subprocess.run(['git', 'show', BEFORE + ':sw.js'], cwd=test_e2e.ROOT, capture_output=True, text=True)
        if old.returncode != 0 or 'addRoutes' in old.stdout:
            raise unittest.SkipTest('the worker from before the change is not in this checkout')
        super().setUpClass()
        cls.new_worker = (cls.board / 'sw.js').read_text(encoding='utf-8')
        assert 'addRoutes' in cls.new_worker
        (cls.board / 'sw.js').write_text(old.stdout, encoding='utf-8')        # the temp board as an installed board is today

    def write(self, text):
        self.browser.fill('#input', text)
        self.browser.click('#send')

    def his(self, text):
        return [m for m in self.thread(TID)['messages'] if m['from'] == 'owner' and m['text'] == text]

    def arrived(self, text):
        self.until(lambda: self.his(text), timeout=40, what='the reply on the server')
        self.browser.wait('(()=>{const row=[...document.querySelectorAll("#log .msg.own")].find(r=>r.innerText.includes(%s));'
                          'return JSON.stringify(!!row&&!row.classList.contains("failed")&&!/לא נשלח|מנסה שוב|שולח/.test(row.innerText));})()' % json.dumps(text),
                          timeout=40, what='the reply shown as received')
        time.sleep(1.5)

    def scenario(self):
        """Played once for the class; gives back what was seen."""
        cls = type(self)
        if cls.seen is not None:
            if isinstance(cls.seen, str):
                self.skipTest(cls.seen)
            return cls.seen
        seen = {}
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[0], TID, TITLE)
        if not self.browser.eval('JSON.stringify("serviceWorker" in navigator&&window.isSecureContext)'):
            cls.seen = 'this browser allows no worker on a loopback page'
            self.skipTest(cls.seen)
        self.browser.wait('(async()=>{await navigator.serviceWorker.ready;return JSON.stringify(!!navigator.serviceWorker.controller);})()', timeout=30, what='the old worker in charge of the page')
        if not self.browser.eval('JSON.stringify("workerMatchedSourceType" in PerformanceResourceTiming.prototype)'):
            cls.seen = 'this browser does not say which way a request of a worker\'s page took'
            self.skipTest(cls.seen)
        # 1. a load the OLD worker is in charge of from its start
        self.open_thread(SIZES[0], TID, TITLE)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!navigator.serviceWorker.controller)', what='the state on a page of the old worker')
        self.write(OLD_WORDS)
        self.arrived(OLD_WORDS)
        seen['old'] = self.browser.eval(ROUTE % json.dumps('/api/state'))
        seen['browser'] = self.browser.eval('JSON.stringify((navigator.userAgent.match(/(?:Headless)?Chrome\\/[\\d.]+|Firefox\\/[\\d.]+|Version\\/[\\d.]+ Safari/)||[navigator.userAgent])[0])')
        # 2. the new worker is published beside the open page, and the browser finds it
        self.browser.eval(WATCH)
        (self.board / 'sw.js').write_text(PROBE + self.new_worker, encoding='utf-8')
        # (asked for, not awaited: what follows is polled for)
        self.browser.eval('(()=>{window.__update="asked";navigator.serviceWorker.getRegistration().then(r=>r.update()).then(()=>{window.__update="done";},e=>{window.__update="failed: "+e;});return "ok";})()')
        try:
            self.browser.wait('(async()=>{const r=await navigator.serviceWorker.getRegistration();'
                              'return JSON.stringify(window.__changes>=1&&!!r&&!r.installing&&!r.waiting&&!!r.active&&r.active.state==="activated"&&navigator.serviceWorker.controller===r.active);})()',
                              timeout=60, what='the new worker in charge of the open page')
        finally:
            seen['update'] = self.browser.eval('JSON.stringify([window.__update,window.__changes,window.__page||0])')
        # 3. the same page, never loaded again, under the new worker
        self.browser.eval('(()=>{performance.clearResourceTimings();return "ok";})()')
        self.browser.eval(GIVEN)
        self.write(TAKEN_WORDS)
        self.arrived(TAKEN_WORDS)
        seen['taken'] = self.browser.eval(ROUTE % json.dumps('/api/state'))
        # (a request is listed once its answer was read to the end)
        self.browser.eval('(async()=>{performance.clearResourceTimings();await (await fetch("summary.json?t="+Date.now(),{cache:"no-store"})).text();'
                          'await (await fetch(location.pathname,{cache:"no-store"})).text();await new Promise(done=>setTimeout(done,300));return "ok";})()')
        seen['taken given'] = self.browser.eval(GIVEN)
        seen['taken state'] = self.browser.eval(ROUTE % json.dumps('/summary.json'))
        seen['taken own'] = self.browser.eval(ROUTE % json.dumps('/suda.html'))
        seen['taken page'] = self.browser.eval('JSON.stringify([window.__page||0,window.__changes,document.querySelector("#newer").hidden])')
        seen['posts'] = self.browser.eval('JSON.stringify(window.__posts)')
        # 4. the next opening, and what that page sends
        self.open_thread(SIZES[0], TID, TITLE)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!navigator.serviceWorker.controller)', what='the state on a page of the new worker')
        seen['nav'] = self.browser.eval('(()=>{const n=performance.getEntriesByType("navigation")[0];return JSON.stringify([n.workerStart>0,n.workerMatchedSourceType||""]);})()')
        seen['kept'] = self.browser.eval('(async()=>{const kept=await (await caches.open("suda-shell-1")).match(location.pathname);return JSON.stringify(kept?(await kept.text()).length:0);})()')
        self.browser.eval(GIVEN)
        self.write(LOADED_WORDS)
        self.arrived(LOADED_WORDS)
        self.browser.eval('(async()=>{await (await fetch(location.pathname,{cache:"no-store"})).text();return "ok";})()')
        seen['loaded given'] = self.browser.eval(GIVEN)
        seen['loaded'] = self.browser.eval(ROUTE % json.dumps('/api/state'))
        seen['loaded state'] = self.browser.eval(ROUTE % json.dumps('/summary.json'))
        seen['stored'] = [m['text'] for m in self.thread(TID)['messages'] if m['from'] == 'owner']
        cls.seen = seen
        return seen

    def test_held_the_new_worker_takes_an_open_page_over_without_loading_it_again_and_no_message_is_lost_or_doubled(self):
        seen = self.scenario()
        self.assertEqual((seen['old'] or [None])[0], '', 'the old worker has no rule: this is the board as it is installed today')
        self.assertEqual(seen['update'][1:], [1, 1], 'the worker changed more than once, or the page was loaded again: %r' % (seen['update'],))
        self.assertEqual(seen['taken page'], [1, 1, True], 'the page was loaded again, or the same build was offered as a newer one')
        self.assertEqual(seen['stored'], [OLD_WORDS, TAKEN_WORDS, LOADED_WORDS])
        self.assertEqual([p for p in seen['posts'] if p['end'] != 200], [], 'a page action was cut when the worker changed')

    def test_held_after_the_next_opening_everything_but_the_pages_own_file_goes_past_the_worker(self):
        seen = self.scenario()
        self.assertEqual(seen['nav'], [True, ''], 'the opening was not answered by the worker')
        self.assertEqual(seen['kept'], len((self.board / 'suda.html').read_text(encoding='utf-8').encode('utf-16-le')) // 2)       # as the browser counts
        self.assertEqual((seen['loaded'] or [])[:2], ['network', 'network'], seen['loaded'])
        self.assertEqual((seen['loaded state'] or [])[:2], ['network', 'network'], seen['loaded state'])
        # the worker itself was given the page's own file, and nothing else
        self.assertIn(OWN[0], seen['loaded given'])
        self.assertEqual(sorted(set(seen['loaded given']) - set(OWN)), [], seen['loaded given'])
        # the page's own reading of its file was the worker's all along
        self.assertEqual((seen['taken own'] or [None])[0], '', seen['taken own'])
        self.assertIn(OWN[0], seen['taken given'])

    # Not fixed, by decision (the reviewer's own word: "none needed in the worker"): a page that an OLDER worker was
    # in charge of keeps passing its requests through the worker until it is loaded again, exactly as before the
    # change and no worse. The new build of the page comes with the new worker, the strip "new version" offers the
    # reload, and from then on only the page's own file reaches the worker (the tests beside this one).
    @unittest.expectedFailure
    def test_a_page_the_new_worker_took_over_sends_past_it_at_once(self):
        """The worker claims the open pages (clients.claim), so the page is "its" page from that moment. The rule
        that came with it must hold for that page too: a board that is installed today gets the new worker beside
        an open page, and on a desktop that page stays open for days. (A page that had NO worker before is fine:
        see FirstVisit. Chrome keeps, for a page an older worker had, the rules of that older worker: here none.)"""
        seen = self.scenario()
        self.assertIsNotNone(seen['taken given'], 'the worker did not say what it was given')
        waited = sorted({asked for asked in seen['taken given'] if asked not in OWN})
        self.assertEqual(waited, [], 'a page the new worker took over still sends these through the worker, until it is loaded again (%s)' % seen['browser'])
        self.assertEqual((seen['taken'] or [])[:2], ['network', 'network'], seen['taken'])
        self.assertEqual((seen['taken state'] or [])[:2], ['network', 'network'], seen['taken state'])


class FirstVisit(test_e2e.Suda):
    """A browser that never had a worker of this board: the page installs the new one and is taken over by it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        worker = (cls.board / 'sw.js').read_text(encoding='utf-8')
        assert 'addRoutes' in worker
        (cls.board / 'sw.js').write_text(PROBE + worker, encoding='utf-8')

    def test_held_the_page_that_installed_the_worker_sends_past_it_at_once(self):
        """The first page of a device had no worker when it loaded; the worker claims it once installed. The rule
        holds for that page from then on (unlike a page that an OLDER worker had: see Handover)."""
        tid, title, words = 'e2e-first', 'ביקור ראשון', 'הודעה מהדף שהתקין את ה-worker'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[0], tid, title)
        if not self.browser.eval('JSON.stringify("serviceWorker" in navigator&&window.isSecureContext)'):
            self.skipTest('this browser allows no worker on a loopback page')
        self.browser.wait('(async()=>{await navigator.serviceWorker.ready;return JSON.stringify(!!navigator.serviceWorker.controller);})()', timeout=30, what='the worker in charge of the page that installed it')
        self.assertFalse(self.browser.eval('JSON.stringify(performance.getEntriesByType("navigation")[0].workerStart>0)'), 'this page was not the one that installed the worker')
        self.browser.eval(GIVEN)
        self.browser.fill('#input', words)
        self.browser.click('#send')
        self.until(lambda: [m for m in self.thread(tid)['messages'] if m['from'] == 'owner' and m['text'] == words], timeout=40, what='the reply on the server')
        time.sleep(1.5)
        given = self.browser.eval(GIVEN)
        self.assertIsNotNone(given, 'the worker did not say what it was given')
        self.assertEqual(sorted({asked for asked in given if asked not in OWN}), [], 'the page that installed the worker still sends these through it, until it is loaded again')


# The scenarios of test_e2e.Suda belong to that file; here the classes only lend its server, board and browser.
for _class in (Handover, FirstVisit):
    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in _class.__dict__:
            setattr(_class, _name, None)
del _class, _name           # a class left under a second name would be loaded, and run, twice


if __name__ == '__main__':
    unittest.main()
