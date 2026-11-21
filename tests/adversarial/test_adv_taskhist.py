#!/usr/bin/env python3
"""A hostile review of task history (suda-fixes task 34). Each test asserts the SAFE outcome; each fails on the
code under review for the reason its docstring gives."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test_taskhist import Base, T0

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'


class Who(Base):
    """An event says who did it. The CLI is never the owner: an agent's write must not read as his on the page."""

    def test_agent_status_change_on_his_task_is_not_recorded_as_him(self):
        """task set with no --by takes `by` from the task's owner: an agent finishing a task owned by the owner
        records `by: owner`, and the page says "you" did it."""
        self.cli('task', 'add', 'small', 'his task', '--owner', 'owner')
        self.cli('task', 'set', 'small', '1', 'done')
        last = self.task('small', 1)['events'][-1]
        self.assertEqual(last['kind'], 'status')
        self.assertNotEqual(last['by'], 'owner', f'an agent CLI write recorded as the owner: {last}')

    def test_agent_creating_a_task_for_him_is_not_recorded_as_him(self):
        """task add --owner owner records created `by: owner` (the owner, not the writer)."""
        self.cli('task', 'add', 'small', 'for him', '--owner', 'owner')
        first = self.task('small', 1)['events'][0]
        self.assertEqual(first['kind'], 'created')
        self.assertNotEqual(first['by'], 'owner', f'an agent CLI create recorded as the owner: {first}')

    def test_handing_a_task_to_him_is_not_recorded_as_him(self):
        """task set --owner owner (no --by): by = a.owner = 'owner', so the hand over reads as his own act."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', '--owner', 'owner')
        last = self.task('small', 1)['events'][-1]
        self.assertEqual(last['kind'], 'owner')
        self.assertNotEqual(last['by'], 'owner', f'an agent hand over recorded as the owner: {last}')

    def test_owner_change_is_not_credited_to_the_new_owner(self):
        """task set --owner a3 on a task of a2 (no --by) records the owner event `by: a3`, who did nothing."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', '--owner', 'a3')
        last = self.task('small', 1)['events'][-1]
        self.assertEqual(last['kind'], 'owner')
        self.assertNotEqual(last['by'], 'a3', f'the new owner is named as who handed it over: {last}')

    def test_merge_by_cannot_read_as_him(self):
        """merge --by checks only the exact 'owner'/'auto'; 'Owner' passes and the page (case insensitive
        HUMAN_OWNER) shows the moved events as his."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        r = self.cli('merge', 'small', '--into', 'big', '--by', 'Owner', ok=None) if False else None
        env = dict(self.env, THREADS_NOW=str(self.tick()))
        r = subprocess.run([sys.executable, str(ROOT / 'threads.py'), 'merge', 'small', '--into', 'big', '--by', 'Owner'],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return          # refused: safe
        moved = [e for e in self.task('big', 1)['events'] if e['kind'] == 'moved']
        self.assertFalse(any(e['by'].casefold() == 'owner' for e in moved), f'an agent merge recorded as the owner: {moved}')

    def test_task_set_by_auto_cannot_pose_as_the_sweep(self):
        """task set --by auto is accepted; the page shows 'automatically' for an agent's change."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        env = dict(self.env, THREADS_NOW=str(self.tick()))
        r = subprocess.run([sys.executable, str(ROOT / 'threads.py'), 'task', 'set', 'small', '1', 'done', '--by', 'auto'],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return
        self.assertNotEqual(self.task('small', 1)['events'][-1].get('by'), 'auto')


class DerivedLies(Base):
    """The first real event of a task from before events materialises its derived ones. They are taken from the
    task AFTER part of the write has already happened, so they invent times or duplicate the new event."""

    def old_task(self, **fields):
        self.cli('task', 'add', 'small', 'old words', '--owner', 'a2')
        data = self.state()
        k = data['threads']['small']['tasks'][0]
        k.pop('events', None)
        k.update(ts=T0 + 10, updated=T0 + 500, **fields)
        self.write_state(data)

    def test_page_tap_done_on_old_task_records_one_status_event(self):
        """ingest 'task' updates status and `updated` before task_event, so derived_events sees a done task updated
        now and adds a derived 'status -> done' at the tap's time beside the real one: two done events."""
        self.old_task(status='todo')
        at = self.clock + 1000
        self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'done'}, at=at)
        ev = self.task('small', 1)['events']
        done = [e for e in ev if e['kind'] == 'status' and e.get('to') == 'done']
        self.assertEqual(len(done), 1, f'one tap, two done events: {ev}')

    def test_cli_reopen_of_old_done_task_keeps_its_done_time(self):
        """task set sets `updated` before task_event, so the derived 'done' (taken from updated) is stamped NOW,
        not at T0+500 when it was done: an invented time."""
        self.old_task(status='done')
        self.cli('task', 'set', 'small', '1', 'todo')
        ev = self.task('small', 1)['events']
        derived_done = [e for e in ev if e.get('derived') and e['kind'] == 'status']
        self.assertTrue(all(e['ts'] == T0 + 500 for e in derived_done), f'a derived done at an invented time: {ev}')

    def test_cli_text_edit_on_old_task_with_history_invents_no_text_event(self):
        """task set --text appends to task['history'] in place before task_event, so derived_events reads the new
        entry and adds a derived text event at now whose from and to are the same old words."""
        self.old_task(history=[{'text': 'older words', 'ts': T0 + 100, 'by': 'a2'}])
        self.cli('task', 'set', 'small', '1', '--text', 'new words', '--by', 'a3')
        ev = self.task('small', 1)['events']
        text = [e for e in ev if e['kind'] == 'text']
        self.assertFalse(any(e.get('from') == e.get('to') for e in text), f'a text event that changed nothing: {ev}')
        self.assertEqual(len(text), 2, f'one derived (T0+100) and one real: {ev}')

    def test_page_text_edit_on_old_task_with_history_invents_no_text_event(self):
        """The same in the page's task-text op."""
        self.old_task(history=[{'text': 'older words', 'ts': T0 + 100, 'by': 'a2'}])
        self.ingest({'op': 'task-text', 'thread': 'small', 'n': 1, 'text': 'new words'})
        ev = self.task('small', 1)['events']
        text = [e for e in ev if e['kind'] == 'text']
        self.assertFalse(any(e.get('from') == e.get('to') for e in text), f'a text event that changed nothing: {ev}')


class MovedMark(Base):
    """moved_to is a field every writer must record. Opening a moved task again drops it in silence."""

    def test_reopening_a_moved_task_records_the_lost_mark(self):
        """ingest 'task' (and task set) pop moved_to with only a status event: nothing says it is no longer the one
        that went to the other thread, and the next merge moves it a second time."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        self.cli('reopen', 'small')
        before = self.task('small', 1)
        self.assertIn('moved_to', before)
        self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'todo'})
        after = self.task('small', 1)
        self.assertNotIn('moved_to', after)
        gained = [e['kind'] for e in after['events'][len(before['events']):]]
        self.assertIn('moved', gained, f'moved_to dropped without an event (gained {gained})')


class PageFetch(unittest.TestCase):
    """historyFor / wantHistory, run under node with a fake clock and fetch."""

    def run_page(self, file_ok, thread_trev, seconds=60):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        page = PAGE.read_text(encoding='utf-8')
        pure = page.split('// <pure>')[1].split('// </pure>')[0]
        block = 'const taskHistOpen=' + page.split('const taskHistOpen=')[1].split('function renderTasks(t){')[0]
        stub = """
let fakeNow=1.8e12;Date.now=()=>fakeNow;
const timers=[];globalThis.setTimeout=(f,ms)=>{timers.push({at:fakeNow+(ms||0),f});return timers.length;};
let fetches=0;
globalThis.fetch=async()=>{fetches++;return FILE_OK?{ok:true,status:200,json:async()=>({id:'big',trev:'X',tasks:{'1':[{ts:1800000000,kind:'created',by:'a2'}]},messages:[]})}:{ok:false,status:404,json:async()=>({})};};
const view={ch:'big'};let tasksSignature='';
const T={id:'big',trev:TREV,tasks:[{n:1,text:'a',status:'todo'}]};
function thread(id){return id==='big'?T:null;}
function $(){return {querySelector:()=>null};}
function renderTasks(t){historyFor(t,t.tasks[0]);}
""".replace('FILE_OK', 'true' if file_ok else 'false').replace('TREV', json.dumps(thread_trev) if thread_trev is not None else 'undefined')
        driver = """
(async()=>{
  taskHistOpen.add('big:1');renderTasks(T);
  const end=fakeNow+%d*1000;
  for(let i=0;i<10000;i++){
    for(let j=0;j<20;j++)await null;
    timers.sort((a,b)=>a.at-b.at);
    const next=timers.shift();if(!next||next.at>end)break;
    fakeNow=Math.max(fakeNow,next.at);next.f();
  }
  console.log(JSON.stringify({fetches}));
})();
""" % seconds
        r = subprocess.run([node, '-e', "'use strict';\n" + pure + '\n' + stub + '\n' + block + '\n' + driver],
                           capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])['fetches']

    def test_state_json_mode_reads_the_thread_file_once(self):
        """A page that read state.json (no summary: no trev) and opens an old task's history: the file's trev never
        equals the page's undefined trev, so the whole conversation file is fetched again every 2 s forever."""
        fetches = self.run_page(file_ok=True, thread_trev=None, seconds=60)
        self.assertLessEqual(fetches, 2, f'{fetches} reads of full/big.json in 60 s with nothing changed')

    def test_missing_thread_file_is_not_polled_every_two_seconds(self):
        """A missing full/<id>.json leaves a failed entry without trev; it never matches, and the page fetches again
        every 2 s while the history stays open."""
        fetches = self.run_page(file_ok=False, thread_trev='abc', seconds=60)
        self.assertLessEqual(fetches, 6, f'{fetches} reads of a missing file in 60 s')


class Damaged(Base):
    """Hostile data in state.json must not crash the readers."""

    def test_show_survives_an_event_with_a_time_out_of_range(self):
        """showing() prints every event whose ts is a number: time.localtime(1e20) raises, `threads show` dies."""
        self.cli('task', 'add', 'small', 'x', '--owner', 'a2')
        data = self.state()
        data['threads']['small']['tasks'][0]['events'] = [{'ts': 1e20, 'kind': 'created', 'by': 'a2'}]
        self.write_state(data)
        env = dict(self.env, THREADS_NOW=str(self.tick()))
        r = subprocess.run([sys.executable, str(ROOT / 'threads.py'), 'show', 'small'], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])

    def test_page_rejects_an_event_time_no_date_can_hold(self):
        """taskEventsOf keeps any finite ts > 0; renderTasks then calls new Date(ts*1000).toISOString(), which throws
        RangeError and stops drawing the task list."""
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        script = ("const kept=taskEventsOf([{ts:1e20,kind:'created'}]);"
                  "for(const e of kept)new Date(e.ts*1000).toISOString();")
        r = subprocess.run([node, '-e', "'use strict';\n" + pure + '\n' + script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])


if __name__ == '__main__':
    unittest.main()
