#!/usr/bin/env python3
"""Hostile review of sse153 (every change numbered, pages catch up by deltas, a freshness mark).

Each test asserts the SAFE outcome: a failure is a real hole. The owner's guarantees: he never misses an update,
never sees "up to date" when it is not, never sees a half-updated screen.

  - a board put back from a backup (every file older) must never give a number a page already holds to other content;
  - a writer without numbers (an older threads.py, still on disk in other worktrees) must not change what the pages
    show under the number they hold;
  - a property fuzz: hundreds of random command sequences; the page's own catchUp (suda.html under node), from every
    intermediate summary to every later one, must give the real summary exactly;
  - change_entry and the "same" check use Python equality, where True == 1;
  - the page: coming back to a tab that slept must not show "up to date" from before the sleep.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 test_adv_sse.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = _paths.APP
CLI = ROOT / 'threads.py'
BOARDLIB = os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board'))
NODE = shutil.which('node')
PURE = (ROOT / 'suda.html').read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]


def norm(value):
    """A JSON value as a page holds it: an integral float is the same number as the int; a bool is not a number."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return ('num', int(value))
    if isinstance(value, (int, float)):
        return ('num', value)
    if isinstance(value, list):
        return [norm(v) for v in value]
    return {k: norm(v) for k, v in value.items()}


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.adv-sse-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), THREADS_NOTIFY='0', THREADS_BOARDLIB_DIR=BOARDLIB)
        self.env.pop('TUIOS_PANE_ID', None)

    def cli(self, *args, script=CLI):
        r = subprocess.run([sys.executable, str(script), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def summary(self):
        return json.loads((self.board / 'summary.json').read_text(encoding='utf-8'))

    def pulse(self):
        return int((self.board / '.pulse').read_text())

    def test_a_board_put_back_from_a_backup_never_reuses_a_number_for_other_content(self):
        """The whole board folder is put back from a backup (Time Machine, a copy before an experiment). A page (or the
        device copy in IndexedDB) still holds a later number of the lost history. The next saves must not give that
        number to other content: else the page hears its own number, shows the lost content and says "up to date"."""
        self.cli('new', 'a', 'נושא', '--state', 'working', '--note', 'x')
        self.cli('say', 'a', '--from', 'fork', 'לפני הגיבוי')
        backup = self.root / 'backup'
        shutil.copytree(self.board, backup)
        self.cli('say', 'a', '--from', 'fork', 'אחרי הגיבוי, יאבד')
        held = self.summary()                         # what a page holds: this number, this content
        shutil.rmtree(self.board)
        shutil.copytree(backup, self.board)           # the board is put back
        self.cli('say', 'a', '--from', 'fork', 'תוכן אחר לגמרי')
        now = self.summary()
        if now['seq'] == held['seq']:
            self.assertEqual(now, held, 'number %d now names other content: a page holding it says "up to date" '
                             'over the lost history' % held['seq'])
        # and nothing later either: the page's number must stay below every new number
        self.assertGreater(now['seq'], held['seq'], 'the board went back under the number a page holds')

    def test_an_unnumbered_writer_does_not_change_the_board_under_the_pages_number(self):
        """An older threads.py (no seq; other worktrees on disk still have one, and agents run them) saves the live
        board: state.json and summary.json get new content but keep the seq, and the pulse is only touched. The server
        then says "changed" with the SAME id, and the page, whose number that is, reads nothing and says "up to date"
        until the next numbered save."""
        old = self.root / 'old_threads.py'
        old.write_text(subprocess.run(['git', '-C', str(ROOT), 'show', '60586da:threads.py'], capture_output=True, text=True, check=True).stdout)
        self.cli('new', 'a', 'נושא', '--state', 'working', '--note', 'x')
        self.cli('say', 'a', '--from', 'fork', 'ממוספר')
        held = self.summary()
        pulse = self.pulse()
        self.assertEqual(pulse, held['seq'])
        self.cli('say', 'a', '--from', 'fork', 'מגרסה ישנה', script=old)
        after = self.summary()
        self.assertNotEqual({k: v for k, v in after.items() if k != 'seq'}, {k: v for k, v in held.items() if k != 'seq'},
                            'the old writer changed nothing (the test is void)')
        # the safe outcome: the number the server will say is not the page's, or the content under it did not change,
        # or the summary under it no longer vouches for itself (its head: the number and the mark of its content, which
        # the page checks whenever it hears its own number again). An older writer only touches the pulse, so its
        # number cannot change: the head is what tells.
        said = self.pulse() if (self.board / '.pulse').read_text().strip().isdigit() else None
        text = (self.board / 'summary.json').read_text(encoding='utf-8')
        vouches = text.startswith('{"seq":%d,"mark":"%s"' % (held['seq'], held.get('mark')))
        self.assertTrue(said != held['seq'] or after == held or not vouches,
                        'the server still says %s, the number the page holds, over new content that vouches for it: the page '
                        'shows "up to date" and misses the change' % said)
        # and the next numbered save never describes its change against the content the page does not hold
        self.cli('say', 'a', '--from', 'fork', 'שוב ממוספר')
        self.assertGreater(self.summary()['seq'], held['seq'])
        entries = json.loads((self.board / 'changes.json').read_text(encoding='utf-8'))['entries']
        self.assertFalse([e for e in entries if e.get('from') == held['seq']], entries)

    def test_a_value_that_turns_from_1_to_true_is_a_change(self):
        """change_entry, row_edit, list_patch and the "same" check compare with Python ==, where True == 1 == 1.0.
        A value that turns from 1 to true (or back) is not in the entry: the page keeps 1, the summary says true."""
        r = subprocess.run([sys.executable, '-c', r'''
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import threads
old = {"lite": 1, "seq": 5, "flag": 1, "threads": {"a": {"id": "a", "x": 1, "stamps": [["m1", "fork", 10, "aa"], 1]}}}
new = {"lite": 1, "flag": True, "threads": {"a": {"id": "a", "x": True, "stamps": [["m1", "fork", 10, "aa"], True]}}}
print(json.dumps(threads.change_entry(old, new, 6)))
''', str(ROOT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = json.loads(r.stdout)
        ref = __import__('test_threads').apply_entry
        old = {"lite": 1, "seq": 5, "flag": 1, "threads": {"a": {"id": "a", "x": 1, "stamps": [["m1", "fork", 10, "aa"], 1]}}}
        new = {"lite": 1, "seq": 6, "flag": True, "threads": {"a": {"id": "a", "x": True, "stamps": [["m1", "fork", 10, "aa"], True]}}}
        self.assertEqual(norm(ref(old, entry)), norm(new), entry)


DRIVER = r'''
import contextlib, io, json, os, random, shutil, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import threads
seed, runs, steps = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
IDS = ['a', 'b', 'c', 'd']
REQUEST = threads.BOARD / 'state/state.json'

def call(argv, now, body=None):
    os.environ['THREADS_NOW'] = repr(now)
    threads.migrated_from, threads.mended = None, False
    if body is not None:
        REQUEST.parent.mkdir(parents=True, exist_ok=True)
        REQUEST.write_text(json.dumps(body), encoding='utf-8')
    sys.argv = ['threads.py'] + list(argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return threads.main()
    except SystemExit as exc:
        return exc.code
    except Exception as exc:
        return 'CRASH ' + repr(exc)

def pick(r, data):
    tid = r.choice(IDS)
    t = data['threads'].get(tid) if data else None
    other = r.choice([i for i in IDS if i != tid])
    text = r.choice(['עדכון', 'x' * r.randint(1, 300), 'שאלה?', '**b** `c`'])
    n = t['next'] if t else 2
    mid = 'm%d' % r.randint(1, max(1, n))
    ops = [
        (8, ['new', tid, 'כותרת ' + tid, '--state', 'working', '--note', 'n']),
        (14, ['say', tid, '--from', r.choice(['fork', 'tower']), text] + r.choice([[], ['--state', 'working', '--note', 'עובד'], ['--state', 'on-owner', '--note', 'שאלה']])),
        (6, ['say', tid, '--from', 'owner', text]),
        (4, ['ask', tid, 'כן?', '--options', 'כן,לא']),
        (5, ['task', 'add', tid, 'משימה ' + text[:20], '--owner', 'fork']),
        (5, ['task', 'set', tid, str(r.randint(1, 3)), r.choice(['todo', 'working', 'done', 'blocked'])] + r.choice([[], ['--note', 'הערה']])),
        (4, ['react', tid, mid, r.choice(['👍', '✅', '❓'])] + r.choice([[], ['--off']])),
        (3, ['close', tid]), (3, ['reopen', tid]),
        (2, ['merge', tid, '--into', other]),
        (3, ['rename', tid, 'שם ' + str(r.randint(1, 99))]),
        (3, ['snooze', tid, '--until', '+2h']), (2, ['unsnooze', tid]),
        (4, ['state', tid, r.choice(['working', 'on-owner', 'done']), '--note', r.choice(['א', 'ב', 'ג'])]),
        (3, ['set', tid, '--summary', r.choice(['סיכום', 'אחר'])]),
        (2, ['update', tid, mid, 'עודכן ' + text[:10], '--from', 'fork']),
        (2, ['urgent', tid]), (1, ['mute', tid]),
        (1, ['rm', tid, '--yes']),
        (1, ['policy', '--idle-hours', r.choice(['1', '5', '30'])]),
        (2, ['sweep']),
    ]
    page = [(6, {'op': 'reply', 'thread': tid, 'text': text, 'cid': 'c%d' % r.randint(1, 10 ** 6)}),
            (2, {'op': 'done', 'thread': tid}), (2, {'op': 'close', 'thread': tid}), (1, {'op': 'reopen', 'thread': tid})]
    total = sum(w for w, _ in ops) + sum(w for w, _ in page)
    x = r.uniform(0, total)
    for w, argv in ops:
        x -= w
        if x <= 0:
            return argv, None
    for w, body in page:
        x -= w
        if x <= 0:
            return ['ingest'], body
    return ['sweep'], None

out = []
for run in range(runs):
    r = random.Random(seed * 1000 + run)
    shutil.rmtree(threads.BOARD, ignore_errors=True)
    now = 1_800_000_000.0
    call(['new', 'a', 'ראשון', '--state', 'working', '--note', 'n'], now)
    snaps, trail = {}, []
    def snap():
        text = (threads.SUMMARY).read_text(encoding='utf-8')
        s = json.loads(text)
        if s['seq'] in snaps and json.loads(snaps[s['seq']]) != s:
            trail.append(['SAME NUMBER, OTHER CONTENT', s['seq']])
        snaps[s['seq']] = text.strip()
    snap()
    for i in range(steps):
        now += r.choice([1, 30, 600, 3600 * 3, 3600 * 30])
        data = json.loads(threads.STATE.read_text(encoding='utf-8'))
        argv, body = pick(r, data)
        code = call(argv, now, body)
        if isinstance(code, str):
            trail.append([argv, code])
        trail.append(argv if body is None else ['ingest', body['op']])
        snap()
    files = {p.stem: p.read_text(encoding='utf-8').strip() for p in (threads.BOARD / 'changes').iterdir() if p.suffix == '.json'}
    out.append({'seed': seed * 1000 + run, 'snaps': snaps, 'changes': threads.CHANGES.read_text(encoding='utf-8'), 'files': files,
                'crash': [t for t in trail if len(t) == 2 and isinstance(t[1], str) and t[1].startswith('CRASH')],
                'reuse': [t for t in trail if t and t[0] == 'SAME NUMBER, OTHER CONTENT'], 'trail': trail[-12:]})
print(json.dumps(out, ensure_ascii=False))
'''

# For every pair (start, target): catchUp from changes.json, and from the small files when target-start <= 3.
NODE_CHECK = r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const res=[];
for(const run of input){
  const snaps=Object.fromEntries(Object.entries(run.snaps).map(([k,v])=>[k,v]));
  const changes=JSON.parse(run.changes);
  const numbers=Object.keys(snaps).map(Number).sort((a,b)=>a-b);
  for(const a of numbers)for(const b of numbers){
    if(b<a)continue;
    const base=JSON.parse(snaps[a]);
    const got=catchUp(base,changes,b);
    const want=JSON.stringify(JSON.parse(snaps[b]));
    res.push({seed:run.seed,a,b,how:'changes',got:got===null?null:JSON.stringify(got),bytes:got!==null&&JSON.stringify(got)===want});
    // the small files, named by the number each starts from: walk at most 3 of them from a to b, as the page does
    if(b>a){
      // each file is a run {seq, entries} from its number on; the entries past b are not wanted here
      const files=[];let at=a;
      for(let step=0;step<3&&at<b;step++){const f=run.files[String(at)];if(f===undefined)break;const es=(JSON.parse(f).entries||[]).filter(e=>e.seq<=b);if(!es.length)break;files.push(...es);at=es[es.length-1].seq;}
      if(at===b){
        const g2=catchUp(JSON.parse(snaps[a]),{seq:b,entries:files});
        res.push({seed:run.seed,a,b,how:'files',got:g2===null?null:JSON.stringify(g2),bytes:g2!==null&&JSON.stringify(g2)===JSON.stringify(JSON.parse(snaps[b]))});
      }
    }
  }
}
process.stdout.write(JSON.stringify(res));
'''


@unittest.skipUnless(NODE, 'node is not installed')
class Fuzz(unittest.TestCase):
    RUNS, STEPS = int(os.environ.get('ADV_SSE_RUNS', '240')), int(os.environ.get('ADV_SSE_STEPS', '30'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.adv-sse-fuzz-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, BOARDS_DIR=str(Path(self.tmp.name) / 'boards'), THREADS_NOTIFY='0', THREADS_BOARDLIB_DIR=BOARDLIB)
        self.env.pop('TUIOS_PANE_ID', None)

    def runs(self, seed, runs):
        r = subprocess.run([sys.executable, '-c', DRIVER, str(ROOT), str(seed), str(runs), str(self.STEPS)],
                           env=self.env, capture_output=True, text=True, timeout=1200)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        return json.loads(r.stdout)

    def test_the_pages_catch_up_from_every_point_gives_the_summary_exactly(self):
        bad, order, nulls, pairs, crashes, reuse, files = [], [], [], 0, [], [], 0
        per = 40
        for seed in range(max(1, self.RUNS // per)):
            out = self.runs(seed + 1, per)
            for run in out:
                crashes += run['crash']
                reuse += run['reuse']
            r = subprocess.run([NODE, '-e', "'use strict';\n" + PURE + '\n' + NODE_CHECK], input=json.dumps(out, ensure_ascii=False),
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            by = {run['seed']: run for run in out}
            for res in json.loads(r.stdout):
                pairs += 1
                files += res['how'] == 'files'
                run = by[res['seed']]
                want = run['snaps'][str(res['b'])]
                entries = json.loads(run['changes'])['entries']
                if res['got'] is None:
                    if res['how'] == 'files':
                        nulls.append((res['seed'], res['a'], res['b'], 'files'))
                    elif res['how'] == 'changes' and entries and res['a'] >= entries[0]['from'] and res['b'] <= entries[-1]['seq'] and res['b'] > res['a']:
                        nulls.append((res['seed'], res['a'], res['b']))
                    continue
                got = json.loads(res['got'])
                if norm(got) != norm(json.loads(want)):
                    bad.append({'seed': res['seed'], 'from': res['a'], 'to': res['b'], 'how': res['how'], 'trail': run['trail'],
                                'diff': [k for k in set(got['threads']) | set(json.loads(want)['threads'])
                                         if norm(got['threads'].get(k)) != norm(json.loads(want)['threads'].get(k))]})
                elif not res['bytes']:
                    order.append((res['seed'], res['a'], res['b'], res['how'], res['got'], want))
        print('\nfuzz: %d pairs checked (%d by the small files), %d wrong, %d key-order-only, %d null inside the window, %d crashes, %d reused numbers'
              % (pairs, files, len(bad), len(order), len(nulls), len(crashes), len(reuse)), file=sys.stderr)
        self.assertGreater(pairs, 1000)
        self.assertGreater(files, 100, 'the small files were hardly walked: the check is void')
        self.assertEqual(reuse, [], 'a number named two different summaries')
        self.assertEqual(bad[:3], [], 'catchUp gave a summary that is not the board')
        self.assertEqual(nulls[:5], [], 'catchUp refused a run the window covers (a needless whole read)')


# ── the page, end to end (agent-browser headless, the harness of test_e2e / test_e2e_resume) ──────────────────
SLEPT = """(()=>{
  heardAt=Date.now()-60000;wordAt=Date.now()-60000;
  document.dispatchEvent(new Event('visibilitychange'));
  return JSON.stringify({mark:live.dataset.fresh,text:live.textContent});
})()"""

if os.environ.get('ADV_SSE_E2E', '1') == '1':
    import test_e2e
    import test_e2e_resume

    class Page(test_e2e_resume.Resume):
        TID = 'adv-sse'
        TITLE = 'בדיקה עוינת'

        def test_a_message_from_an_unnumbered_writer_reaches_the_screen_or_the_mark_says_behind(self):
            """An older threads.py writes the board (it keeps the seq and only touches the pulse). Within two heartbeats
            the page must show the message, or at least stop saying "up to date"."""
            self.open_board()
            # the next numbered save puts the board right again, for the tests after this one
            self.addCleanup(self.say, 'שמירה ממוספרת אחרי הכותב הישן')
            old = Path(self.tmp.name) / 'old_threads.py'
            old.write_text(subprocess.run(['git', '-C', str(ROOT), 'show', '60586da:threads.py'], capture_output=True, text=True, check=True).stdout)
            text = 'מכותב ישן %d' % time.time()
            r = subprocess.run([sys.executable, str(old), 'say', self.TID, '--from', 'fork', text], env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(text, json.dumps(self.summary(), ensure_ascii=False))
            time.sleep(22)
            got = self.browser.eval('JSON.stringify({shown:JSON.stringify(data).includes(%s),mark:live.dataset.fresh,applied:appliedNumber})' % json.dumps(text))
            self.assertTrue(got['shown'] or got['mark'] != 'fresh',
                            'after 22 s the page does not show the message and says "up to date": %s' % got)

        def test_a_reload_after_an_unnumbered_writer_shows_the_board(self):
            """Worse than a live page: he reloads. The device copy (IndexedDB) carries the same number, the line opens
            with since=<that number>, the server sends no "changed", and the page never reads summary.json."""
            self.open_board()
            self.addCleanup(self.say, 'שמירה ממוספרת אחרי הכותב הישן')
            old = Path(self.tmp.name) / 'old_threads.py'
            old.write_text(subprocess.run(['git', '-C', str(ROOT), 'show', '60586da:threads.py'], capture_output=True, text=True, check=True).stdout)
            text = 'מכותב ישן לפני טעינה %d' % time.time()
            r = subprocess.run([sys.executable, str(old), 'say', self.TID, '--from', 'fork', text], env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            test_e2e.Suda.visits += 1
            self.browser.open(self.url + '?s=reload&n=%d#%s' % (test_e2e.Suda.visits, self.TID))
            self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced===true)', what='the page synced')
            time.sleep(12)
            got = self.browser.eval('JSON.stringify({shown:JSON.stringify(data).includes(%s),mark:live.dataset.fresh,applied:appliedNumber})' % json.dumps(text))
            self.assertTrue(got['shown'] or got['mark'] != 'fresh',
                            'after a reload the page still does not show the message and says "up to date": %s' % got)

        def test_coming_back_to_a_tab_that_slept_never_shows_the_mark_from_before(self):
            """A phone puts the tab to sleep: no timer runs, no word from the server. On the way back the first thing on
            the screen is the mark as it was. The visibilitychange handler must not leave "up to date" there when the
            last word from the server is long gone (simulated: the last word set 60 s back, then the page comes back)."""
            self.open_board()
            got = self.browser.eval(SLEPT)
            self.assertNotEqual(got['mark'], 'fresh', 'back from sleep, the mark still says "up to date" from 60 s ago: %s' % got)

    for _name in dir(test_e2e_resume.Resume):
        if _name.startswith('test') and _name not in Page.__dict__:
            setattr(Page, _name, None)


if __name__ == '__main__':
    unittest.main()
