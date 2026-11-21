#!/usr/bin/env python3
"""The history of a task (suda-fixes task 34, owner in m151 and m153): every task keeps its own events, oldest
first: created, every status change (with who), text changes, owner changes, moved in a merge, archived and taken
back out. Each writer of a task records its event; the list is bounded (the first event and the newest ones stay);
a task from before this keeps what can be told from what it has (marked derived), and no time is invented.

    task['events'] = [{'ts', 'kind', 'by', 'from'?, 'to'?, 'derived'?}]

A merge moves the done tasks too (as done, with their events), so the target holds the whole list. The summary
the page opens with carries only the last event of each task; the thread's own file carries all of them."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = _paths.APP
CLI = ROOT / 'threads.py'
T0 = 1_800_000_000


def constant(name):
    """A bound of threads.py, read from its source (importing it would read the environment of this test)."""
    import re
    m = re.search(rf'^{name} = (\d+)', CLI.read_text(encoding='utf-8'), re.M)
    assert m, f'{name} is not defined in threads.py'
    return int(m[1])

# What a writer may change on a task, and the kind of event each change must leave.
FIELDS = {'status': 'status', 'text': 'text', 'owner': 'owner', 'archived': ('archived', 'unarchived'), 'moved_to': 'moved'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-taskhist-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.board = root / 'boards/threads'
        recorder = root / 'record.py'
        recorder.write_text("import sys\n")
        self.clock = T0
        self.env = dict(os.environ, BOARDS_DIR=str(root / 'boards'), NOTIFY_RECORD=str(root / 'mail.jsonl'),
                        THREADS_NOTIFY_CMD=shlex.join([sys.executable, str(recorder)]))
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'TUIOS_PANE_ID'):
            self.env.pop(key, None)
        self.cli('new', 'big', 'הנושא הגדול', '--state', 'working', '--note', 'x', '--by', 'a1')
        self.cli('new', 'small', 'נושא קטן', '--state', 'working', '--note', 'x', '--by', 'a2')

    def tick(self, seconds=60):
        self.clock += seconds
        return self.clock

    def cli(self, *args, ok=True, at=None):
        env = dict(self.env, THREADS_NOW=str(at if at is not None else self.tick()))
        r = subprocess.run([sys.executable, str(CLI), *args], env=env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def ingest(self, op, at=None):
        (self.board / 'state').mkdir(exist_ok=True)
        (self.board / 'state/state.json').write_text(json.dumps(op, ensure_ascii=False), encoding='utf-8')
        env = dict(self.env, THREADS_NOW=str(at if at is not None else self.tick()))
        r = subprocess.run([sys.executable, str(CLI), 'ingest'], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def state(self):
        return json.loads((self.board / 'state.json').read_text(encoding='utf-8'))

    def task(self, tid, n):
        return next(k for k in self.state()['threads'][tid]['tasks'] if k['n'] == n)

    def kinds(self, tid, n):
        return [e['kind'] for e in self.task(tid, n).get('events', [])]

    def write_state(self, data):
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


class EveryWriter(Base):
    """Each way a task can change leaves an event of its kind, with its time and who did it."""

    def changed(self, before, after):
        """For every task, the fields that changed and the events it gained."""
        out = []
        for tid in after['threads']:
            old = {k['n']: k for k in before['threads'].get(tid, {}).get('tasks', [])}
            for k in after['threads'][tid]['tasks']:
                was = old.get(k['n'])
                gained = k.get('events', [])[len((was or {}).get('events', [])):] if was else k.get('events', [])
                fields = [f for f in FIELDS if was is not None and was.get(f) != k.get(f)]
                out.append((tid, k['n'], was is None, fields, gained))
        return out

    def assert_recorded(self, run):
        before = self.state()
        run()
        after = self.state()
        moved = False
        for tid, n, new, fields, gained in self.changed(before, after):
            kinds = [e['kind'] for e in gained]
            if new:
                self.assertTrue(kinds and kinds[0] in ('created', 'moved') or 'moved' in kinds,
                                f'{tid} {n}: a new task without a created/moved event: {gained}')
                if 'moved' in kinds:
                    moved = True
                continue
            for f in fields:
                want = FIELDS[f]
                want = want if isinstance(want, tuple) else (want,)
                self.assertTrue(any(k in want for k in kinds), f'{tid} {n}: {f} changed without a {want} event (gained {kinds})')
            for e in gained:
                self.assertIsInstance(e.get('ts'), (int, float), e)
                self.assertTrue(e.get('by'), f'an event without who: {e}')
                self.assertNotIn('derived', e, 'a fresh event is not derived')
        return after, moved

    def test_cli_add_records_created_with_who(self):
        self.assert_recorded(lambda: self.cli('task', 'add', 'small', 'לכתוב בדיקות', '--owner', 'a2'))
        ev = self.task('small', 1)['events']
        self.assertEqual([(e['kind'], e['by']) for e in ev], [('created', 'a2')])
        self.assertEqual(ev[0]['ts'], self.task('small', 1)['ts'])

    def test_cli_set_status_text_owner_each_record_their_event(self):
        self.cli('task', 'add', 'small', 'לכתוב בדיקות', '--owner', 'a2')
        self.assert_recorded(lambda: self.cli('task', 'set', 'small', '1', 'building', '--note', 'בדרך'))
        status = self.task('small', 1)['events'][-1]
        self.assertEqual((status['kind'], status['from'], status['to'], status['by']), ('status', 'todo', 'building', 'a2'))
        self.assert_recorded(lambda: self.cli('task', 'set', 'small', '1', '--text', 'לכתוב בדיקות קודם', '--by', 'a3'))
        text = self.task('small', 1)['events'][-1]
        self.assertEqual((text['kind'], text['from'], text['to'], text['by']), ('text', 'לכתוב בדיקות', 'לכתוב בדיקות קודם', 'a3'))
        self.assert_recorded(lambda: self.cli('task', 'set', 'small', '1', '--owner', 'owner', '--by', 'a2'))
        owner = self.task('small', 1)['events'][-1]
        self.assertEqual((owner['kind'], owner['from'], owner['to'], owner['by']), ('owner', 'a2', 'owner', 'a2'))

    def test_cli_set_to_the_same_status_records_nothing(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'todo', '--note', 'עדיין')
        self.assertEqual(self.kinds('small', 1), ['created'])

    def test_cli_archive_unarchive_and_reopening_an_archived_task(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'done')
        self.assert_recorded(lambda: self.cli('task', 'archive', 'small', '1'))
        self.assertEqual(self.kinds('small', 1)[-1], 'archived')
        self.assert_recorded(lambda: self.cli('task', 'unarchive', 'small', '1'))
        self.assertEqual(self.kinds('small', 1)[-1], 'unarchived')
        self.cli('task', 'archive', 'small', '1')
        self.assert_recorded(lambda: self.cli('task', 'set', 'small', '1', 'todo'))
        self.assertEqual(self.kinds('small', 1)[-2:], ['status', 'unarchived'])

    def test_cli_archive_of_old_done_tasks(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'done')
        self.assert_recorded(lambda: self.cli('task', 'archive', 'small', '--done-older-than', '0'))
        self.assertEqual(self.kinds('small', 1)[-1], 'archived')

    def test_the_sweep_archives_with_an_event_of_its_own(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'done')
        self.assert_recorded(lambda: self.cli('sweep', at=self.tick(13 * 3600)))
        last = self.task('small', 1)['events'][-1]
        self.assertEqual((last['kind'], last['by']), ('archived', 'auto'))

    def test_page_ops_record_with_him_as_who(self):
        self.assert_recorded(lambda: self.ingest({'op': 'task-add', 'thread': 'small', 'text': 'משימה שלי'}))
        self.assertEqual([(e['kind'], e['by']) for e in self.task('small', 1)['events']], [('created', 'owner')])
        self.assert_recorded(lambda: self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'done'}))
        self.assertEqual(self.task('small', 1)['events'][-1], {'ts': self.clock, 'kind': 'status', 'by': 'owner', 'from': 'todo', 'to': 'done'})
        self.assert_recorded(lambda: self.ingest({'op': 'task-archive', 'thread': 'small', 'n': 1, 'on': True}))
        self.assert_recorded(lambda: self.ingest({'op': 'task-archive', 'thread': 'small', 'n': 1, 'on': False}))
        self.assertEqual(self.kinds('small', 1)[-2:], ['archived', 'unarchived'])
        self.assert_recorded(lambda: self.ingest({'op': 'task-archive', 'thread': 'small', 'n': 'done', 'on': True}))
        self.assertEqual(self.kinds('small', 1)[-1], 'archived')
        self.assert_recorded(lambda: self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'working'}))
        self.assertEqual(self.kinds('small', 1)[-2:], ['status', 'unarchived'])
        self.assert_recorded(lambda: self.ingest({'op': 'task-text', 'thread': 'small', 'n': 1, 'text': 'משימה שלי, מתוקנת'}))
        last = self.task('small', 1)['events'][-1]
        self.assertEqual((last['kind'], last['from'], last['to'], last['by']), ('text', 'משימה שלי', 'משימה שלי, מתוקנת', 'owner'))

    def test_a_page_tap_on_the_same_status_records_nothing(self):
        self.ingest({'op': 'task-add', 'thread': 'small', 'text': 'א'})
        self.ingest({'op': 'task', 'thread': 'small', 'n': 1, 'status': 'todo'})
        self.assertEqual(self.kinds('small', 1), ['created'])

    def test_the_cli_and_the_page_merge_record_moves(self):
        for merge in (lambda: self.cli('merge', 'small', '--into', 'big', '--by', 'tower'),
                      lambda: self.ingest({'op': 'merge', 'thread': 'small', 'into': 'big'})):
            with self.subTest(merge=merge):
                self.setUp()
                self.cli('task', 'add', 'small', 'פתוחה', '--owner', 'a2')
                self.cli('task', 'add', 'small', 'גמורה', '--owner', 'a2')
                self.cli('task', 'set', 'small', '2', 'done')
                after, moved = self.assert_recorded(merge)
                self.assertTrue(moved, 'the target gained no moved event')


class Merge(Base):
    """A merge moves the done tasks too, so the target holds the whole list; each keeps its events."""

    def setUp(self):
        super().setUp()
        self.cli('task', 'add', 'big', 'של הגדול', '--owner', 'a1')
        self.cli('task', 'add', 'small', 'פתוחה 1', '--owner', 'a2')
        self.cli('task', 'add', 'small', 'גמורה', '--owner', 'a2')
        self.cli('task', 'add', 'small', 'פתוחה 2', '--owner', 'owner')
        self.cli('task', 'set', 'small', '2', 'done', '--note', 'נעשה')
        self.cli('task', 'set', 'small', '3', 'working', '--note', 'בדרך')

    def test_done_tasks_move_as_done_with_their_events_and_numbers_stay_unique(self):
        before = {k['n']: k for k in self.state()['threads']['small']['tasks']}
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        dst = self.state()['threads']['big']
        src = {k['n']: k for k in self.state()['threads']['small']['tasks']}
        numbers = [k['n'] for k in dst['tasks']]
        self.assertEqual(len(numbers), len(set(numbers)), numbers)
        moved = {k['moved_from']['n']: k for k in dst['tasks'] if k.get('moved_from')}
        self.assertEqual(sorted(moved), [1, 2, 3], 'every task of the source is in the target')
        self.assertEqual((moved[2]['status'], moved[2]['text'], moved[2]['note']), ('done', 'גמורה', 'נעשה'))
        self.assertEqual((moved[1]['status'], moved[3]['status']), ('todo', 'working'))
        for old_n, k in moved.items():
            self.assertEqual(k['events'][:len(before[old_n]['events'])], before[old_n]['events'], 'its events came with it')
            last = k['events'][-1]
            self.assertEqual((last['kind'], last['from'], last['by']), ('moved', {'thread': 'small', 'n': old_n}, 'tower'))
            self.assertEqual(src[old_n]['moved_to'], {'thread': 'big', 'n': k['n']}, 'the source keeps where it went')
            self.assertEqual(src[old_n]['events'][-1]['kind'], 'moved')
            self.assertEqual(src[old_n]['events'][-1]['to'], {'thread': 'big', 'n': k['n']})
        self.assertEqual(src[2]['note'], 'נעשה', 'a done one keeps its own line')
        self.assertEqual(src[2]['status'], 'done')
        # an open one closed in the source by the move: its status change is recorded before the move
        self.assertEqual([e['kind'] for e in src[1]['events']][-2:], ['status', 'moved'])
        block = dst['messages'][-1]
        self.assertEqual(sorted(map(tuple, block['merge']['tasks'])), [(1, moved[1]['n']), (2, moved[2]['n']), (3, moved[3]['n'])])
        self.assertIn('1 of them done', block['text'])      # (the CLI in English: no config.json)

    def test_a_target_said_done_is_not_opened_by_done_tasks_alone(self):
        self.cli('task', 'set', 'small', '1', 'done')
        self.cli('task', 'set', 'small', '3', 'done')
        self.cli('task', 'set', 'big', '1', 'done')
        self.cli('state', 'big', 'done', '--note', 'הכל גמור', '--by', 'a1')
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        self.assertEqual(self.state()['threads']['big']['state'], 'done')

    def test_a_task_that_moved_once_is_not_moved_again(self):
        self.cli('new', 'third', 'שלישי', '--state', 'working', '--note', 'x', '--by', 'a3')
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        self.cli('merge', 'big', '--into', 'third', '--by', 'tower')
        third = self.state()['threads']['third']['tasks']
        froms = [(k['moved_from']['thread'], k['moved_from']['n']) for k in third]
        self.assertEqual(len(froms), len(set(froms)))
        self.assertEqual(len(third), 4, 'big held 4 tasks after the first merge; each arrives once')

    def test_an_archived_done_task_stays_archived_where_it_lands(self):
        self.cli('task', 'archive', 'small', '2')
        self.cli('merge', 'small', '--into', 'big', '--by', 'tower')
        moved = next(k for k in self.state()['threads']['big']['tasks'] if (k.get('moved_from') or {}).get('n') == 2)
        self.assertTrue(moved.get('archived'))


class Bounds(Base):
    def test_the_first_event_and_the_newest_stay(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        data = self.state()
        task = data['threads']['small']['tasks'][0]
        task['events'] = task['events'] + [{'ts': T0 + i, 'kind': 'status', 'by': 'a2', 'from': 'todo', 'to': 'working'} for i in range(500)]
        self.write_state(data)
        self.cli('task', 'set', 'small', '1', 'done')
        ev = self.task('small', 1)['events']
        self.assertLessEqual(len(ev), constant('TASK_EVENTS_MAX'))
        self.assertEqual(ev[0]['kind'], 'created')
        self.assertEqual((ev[-1]['kind'], ev[-1]['to']), ('status', 'done'))

    def test_a_long_text_change_is_cut_in_the_event(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', '--text', 'ב' * 300)
        e = self.task('small', 1)['events'][-1]
        self.assertLessEqual(len(e['to']), constant('TASK_EVENT_TEXT_MAX'))


class OldTasks(Base):
    """A task from before events: what it has tells some of its story; nothing else is made up."""

    def old_board(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'add', 'small', 'ב', '--owner', 'a2')
        data = self.state()
        one, two = data['threads']['small']['tasks']
        for k in (one, two):
            k.pop('events', None)
        one.update(ts=T0 + 10, updated=T0 + 500, status='done', archived=T0 + 900,
                   history=[{'text': 'אאא', 'ts': T0 + 100, 'by': 'a2'}, {'text': 'אא', 'ts': T0 + 200, 'by': 'owner'}])
        two.update(ts=T0 + 20, updated=T0 + 600, status='working')
        self.write_state(data)

    def test_show_json_derives_what_exists_marked_derived(self):
        self.old_board()
        rows = json.loads(self.cli('show', 'small', '--json').stdout)['tasks']
        one, two = rows
        self.assertEqual([(e['kind'], e['ts']) for e in one['events']],
                         [('created', T0 + 10), ('text', T0 + 100), ('text', T0 + 200), ('status', T0 + 500), ('archived', T0 + 900)])
        self.assertTrue(all(e.get('derived') is True for e in one['events']))
        self.assertEqual((one['events'][1]['from'], one['events'][1]['to']), ('אאא', 'אא'))
        self.assertEqual((one['events'][2]['from'], one['events'][2]['to']), ('אא', 'א'))
        self.assertEqual(one['events'][3]['to'], 'done')
        self.assertNotIn('from', one['events'][3], 'what it was before done is not known')
        # a working task: when it started working is not known, so nothing is said about it
        self.assertEqual([e['kind'] for e in two['events']], ['created'])

    def test_the_first_new_event_keeps_the_derived_ones_before_it(self):
        self.old_board()
        self.cli('task', 'set', 'small', '2', 'done')
        ev = self.task('small', 2)['events']
        self.assertEqual([(e['kind'], e.get('derived', False)) for e in ev], [('created', True), ('status', False)])
        self.assertEqual(ev[-1]['from'], 'working')

    def test_a_task_with_no_times_at_all_tells_nothing(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        data = self.state()
        k = data['threads']['small']['tasks'][0]
        for key in ('events', 'ts', 'updated'):
            k.pop(key, None)
        self.write_state(data)
        rows = json.loads(self.cli('tasks', 'small', '--json').stdout)
        self.assertEqual(rows[0]['events'], [])


class Lite(Base):
    """The summary stays small: of every task only its last event; the thread's file has them all."""

    def test_summary_carries_the_last_event_only_and_full_carries_all(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'building')
        self.cli('task', 'set', 'small', '1', 'done')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        task = summary['threads']['small']['tasks'][0]
        self.assertNotIn('events', task)
        self.assertEqual((task['last']['kind'], task['last']['to']), ('status', 'done'))
        whole = json.loads((self.board / 'full/small.json').read_text(encoding='utf-8'))
        self.assertEqual([e['kind'] for e in whole['tasks']['1']], ['created', 'status', 'status'])

    def test_the_thread_file_is_written_again_when_only_a_task_changed(self):
        self.cli('task', 'add', 'small', 'א', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'done')
        whole = json.loads((self.board / 'full/small.json').read_text(encoding='utf-8'))
        self.assertEqual(whole['tasks']['1'][-1]['to'], 'done')
        summary = json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['threads']['small']['trev'], whole['trev'], 'the page can tell its copy of the events is current')


class Show(Base):
    def test_show_prints_each_task_with_its_events(self):
        self.cli('task', 'add', 'small', 'לכתוב בדיקות', '--owner', 'a2')
        self.cli('task', 'set', 'small', '1', 'building')
        out = self.cli('show', 'small').stdout
        self.assertIn('לכתוב בדיקות', out)
        self.assertIn('todo → building', out)
        self.assertIn('created', out)


if __name__ == '__main__':
    unittest.main()
