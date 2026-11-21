#!/usr/bin/env python3
"""Hostile review of the task-press overlay (taskOnWay / keepTasksOnWay, suda m455) and its siblings.

Each test asserts the CORRECT outcome: a failure is a real hole. Same harness as test_e2e_tasks.py.

A "slow read" is a board read the page begins BEFORE a save reaches the server, whose answer (the old copy)
only arrives after the save's own answer came back: the exact race the change is about. It is made with a
fetch wrapper: the GET goes out at once (so the server answers with the copy before the save), and its answer is
held back for SLOW ms.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

TITLE = 'ביקורת עוינת משימות'
SLOW = 3000

# window.__slow: while true, a board read started now is answered SLOW ms late (with what the server said now).
SLOW_READS = r'''(()=>{if(window.__slowSet)return "ok";window.__slowSet=1;window.__slow=false;window.__log=[];
  const tk=takeState;takeState=raw=>{try{const t=raw.threads[%s];window.__log.push(['take',performance.now()|0,fetchSequence,appliedSequence,t&&t.tasks.map(k=>k.status+'/'+(k.archived||0))]);}catch(e){}return tk(raw);};const real=window.fetch;
  window.fetch=(url,opts)=>{const u=String(url);
    if(window.__slow&&/(summary|state)\.json/.test(u)){const p=real(url,opts),gate=window.__gate;window.__log.push(['gated',performance.now()|0]);return p.then(r=>gate.then(()=>{window.__log.push(['delivered',performance.now()|0]);return r;}));}
    return real(url,opts);};
  window.__post=post;
  // a read begun now, answered only SLOW ms after the save `s` has answered
  window.__racy=async s=>{let open;window.__gate=new Promise(d=>open=d);window.__log.push(['busy',!!reading,fetchSequence]);window.__slow=true;refresh();window.__slow=false;
    try{return await window.__post(s);}finally{window.__log.push(['saved',performance.now()|0,fetchSequence]);setTimeout(open,%d);}};
  return "ok";})()'''.replace('%s','__TID__') % SLOW

# Every 15 ms, and after every render (a copy taken is drawn at once, also when the next one follows in 5 ms on
# loopback; on a phone the next read is a round trip away): what `probe` says.
WATCH = r'''(()=>{window.__seen=[];const t0=performance.now();clearInterval(window.__watch);
  const look=()=>{try{window.__seen.push([Math.round(performance.now()-t0),(%s)]);}catch(e){}};
  if(!window.__render){window.__render=render;render=(...a)=>{const r=window.__render(...a);if(window.__look)window.__look();return r;};}
  window.__look=look;window.__watch=setInterval(look,15);return "ok";})()'''
STOP = '(()=>{clearInterval(window.__watch);window.__look=null;return JSON.stringify(window.__seen);})()'


class AdvTasks(test_e2e.Suda):

    def with_tasks(self, tid, count, status='on-owner'):
        self.ok('new', tid, TITLE, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        for i in range(1, count + 1):
            self.ok('task', 'add', tid, 'משימה %d' % i, '--owner', 'owner')
            self.ok('task', 'set', tid, str(i), status, '--note', 'לבדוק')

    def page(self, tid, ready):
        self.open_thread(SIZES[0], tid, TITLE)
        self.browser.wait('JSON.stringify(synced&&!!thread(%s)&&(%s))' % (json.dumps(tid), ready), what='the thread')
        self.browser.eval(SLOW_READS.replace('__TID__', json.dumps(tid)))

    def tearDown(self):
        if self.browser:
            try:
                self.browser.eval('(()=>{clearInterval(window.__watch);if(window.__post)post=window.__post;window.__slow=false;return "ok";})()')
            except Exception:
                pass

    # ── the change itself, under the exact race: should hold ─────────────────────────────────────────────────

    def test_control_a_press_survives_a_copy_read_before_its_save(self):
        tid = 'adv-t-control'
        self.with_tasks(tid, 1)
        self.page(tid, 'thread(%s).tasks.length===1' % json.dumps(tid))
        # his press: a read begins just before the save goes, and its (old) answer lands after the save's answer
        self.browser.eval('(()=>{post=async s=>{return s.op==="task"?window.__racy(s):window.__post(s);};return "ok";})()')
        self.browser.eval(WATCH % ('thread(%s).tasks[0].status' % json.dumps(tid)))
        self.browser.eval('(()=>{setTask(%s,1,"done");return "ok";})()' % json.dumps(tid))
        self.until(lambda: self.thread(tid)['tasks'][0]['status'] == 'done', what='the save')
        time.sleep(SLOW / 1000 + 2)
        seen = self.browser.eval(STOP)
        after = [s for _, s in seen[next(i for i, (_, s) in enumerate(seen) if s == 'done'):]]
        self.assertEqual([s for s in after if s != 'done'], [], 'the press jumped back')

    # ── 1. a save that never answers: the press hides the server's truth for good ────────────────────────────

    def test_a_press_whose_save_never_answers_does_not_hide_the_agents_change_for_good(self):
        """The POST hangs (a stalled connection on a phone; `post` has no time limit for this op). The press was
        never saved; the agent then sets the task to 'working'. The page must come round to the server's truth;
        with the overlay it shows 'done' (a state the server never had) for as long as the request hangs."""
        tid = 'adv-t-hang'
        self.with_tasks(tid, 1)
        self.page(tid, 'thread(%s).tasks.length===1' % json.dumps(tid))
        self.browser.eval('(()=>{post=s=>s.op==="task"?new Promise(()=>{}):window.__post(s);return "ok";})()')
        self.browser.eval('(()=>{setTask(%s,1,"done");return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify(thread(%s).tasks[0].status==="done")' % json.dumps(tid), what='the press shown')
        self.ok('task', 'set', tid, '1', 'working', '--note', 'הסוכן לקח')
        end, got = time.monotonic() + 40, None
        while time.monotonic() < end:
            self.browser.eval('(()=>{refresh();return "ok";})()')
            time.sleep(2)
            got = self.browser.eval('JSON.stringify(thread(%s).tasks[0].status)' % json.dumps(tid))
            if got == 'working':
                break
        self.assertEqual(self.thread(tid)['tasks'][0]['status'], 'working')
        self.assertEqual(got, 'working', 'the page still shows his unsaved press over the server\'s state after 40s')

    # ── 2. a refused second press drops the first press's cover while its old copy is still coming ──────────

    def test_a_refused_second_press_does_not_bring_back_the_state_before_the_first(self):
        """Press 1 (done) is saved, but a read begun before its save is still on its way. Press 2 on the same task
        (back to todo) is refused: the page puts back 'done', but press 1's cover is gone (replaced by press 2's,
        then deleted), so the old copy shows the task as it was before press 1 though the server has 'done'."""
        tid = 'adv-t-refused'
        self.with_tasks(tid, 1)
        self.page(tid, 'thread(%s).tasks.length===1' % json.dumps(tid))
        self.browser.eval('''(()=>{post=async s=>{if(s.op==="task"){
            if(s.status==="done")return window.__racy(s);
            throw Object.assign(Error("לא"),{heard:true});}
          return window.__post(s);};return "ok";})()''')
        self.browser.eval('''(async()=>{await setTask(%s,1,"done");%s;await setTask(%s,1,"todo");return "ok";})()'''
                          % (json.dumps(tid), WATCH % ('thread(%s).tasks[0].status' % json.dumps(tid)), json.dumps(tid)))
        time.sleep(SLOW / 1000 + 2.5)
        seen = self.browser.eval(STOP)
        self.assertEqual(self.thread(tid)['tasks'][0]['status'], 'done')
        self.assertTrue(seen)
        # 'todo' is press 2 shown for the moment before its refusal; the state before press 1 must never come back
        self.assertEqual([x for x in seen if x[1] == 'on-owner'], [], 'the saved press showed its old state again')

    # ── 3. the same bug class, still open: putting a done task away ──────────────────────────────────────────

    def test_archiving_a_done_task_survives_a_copy_read_before_its_save(self):
        """archiveTasks drops filedOnWay as soon as the post answers, not once a read begun after it lands: an old
        copy that arrives after the answer shows the task back among the current ones until the next read."""
        tid = 'adv-t-archive'
        self.with_tasks(tid, 1, status='done')
        self.needs('task-archive')
        self.page(tid, 'thread(%s).tasks[0].status==="done"&&!isArchived(thread(%s).tasks[0])' % (json.dumps(tid), json.dumps(tid)))
        self.browser.eval('(()=>{post=async s=>{return s.op==="task-archive"?window.__racy(s):window.__post(s);};return "ok";})()')
        self.browser.eval(WATCH % ('isArchived(thread(%s).tasks[0])' % json.dumps(tid)))
        self.browser.eval('(()=>{archiveTasks(%s,1,true);return "ok";})()' % json.dumps(tid))
        self.until(lambda: self.thread(tid)['tasks'][0].get('archived'), what='the archive saved')
        time.sleep(SLOW / 1000 + 2)
        seen = self.browser.eval(STOP)
        first = next(i for i, (_, s) in enumerate(seen) if s)
        self.assertEqual([x for x in seen[first:] if not x[1]], [], 'the archived task came back among the current ones')

    # ── 4. the same bug class: two renames in a row ──────────────────────────────────────────────────────────

    def test_a_second_rename_stays_while_its_save_is_on_its_way(self):
        """commitRename deletes pendingTitles[id] after its own read, also when a later rename of the same thread
        put its title there: a read in between shows the first title again until the second save lands."""
        tid = 'adv-t-rename'
        self.with_tasks(tid, 1)
        self.page(tid, 'true')
        self.browser.eval('(()=>{post=async s=>{if(s.op==="rename"&&s.title==="שם ב"){await new Promise(d=>setTimeout(d,%d));}return window.__post(s);};return "ok";})()' % (SLOW + 2000))
        self.browser.eval(WATCH % ('thread(%s).title' % json.dumps(tid)))
        js = '(()=>{renaming={id:%s,was:thread(%s).title};renameBox.value=%s;commitRename();return "ok";})()'
        self.browser.eval(js % (json.dumps(tid), json.dumps(tid), json.dumps('שם א')))
        self.browser.eval(js % (json.dumps(tid), json.dumps(tid), json.dumps('שם ב')))
        self.until(lambda: self.thread(tid)['title'] == 'שם א', what='the first rename')
        for _ in range(4):                       # the board's copies that come meanwhile (a pulse, the poll)
            time.sleep(0.6)
            self.browser.eval('(()=>{refresh();return "ok";})()')
        self.until(lambda: self.thread(tid)['title'] == 'שם ב', timeout=20, what='the second rename')
        time.sleep(1.5)
        seen = self.browser.eval(STOP)
        first = next(i for i, (_, s) in enumerate(seen) if s == 'שם ב')
        self.assertEqual(sorted({s for _, s in seen[first:] if s != 'שם ב'}), [], 'the second title was replaced by the first meanwhile')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvTasks.__dict__:
        setattr(AdvTasks, _name, None)


if __name__ == '__main__':
    unittest.main()
