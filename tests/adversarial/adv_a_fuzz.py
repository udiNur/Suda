"""Model-based fuzzer for threads.py: a helper of test_adv_a.py (reviewer A).

Run ONLY through the test harness: it refuses to start unless BOARDS_DIR points
inside this repository and notifications are off. It drives the CLI in-process
(threads.main() with a pinned clock), and after every command compares the state
file before and after against the invariants. Prints one JSON object:
{"steps": n, "violations": {kind: [first examples]}, "known": {kind: count}, "coverage": {command: [accepted, refused]}}.

usage: adv_a_fuzz.py SEED STEPS
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import contextlib
import io
import json
import os
from pathlib import Path
import random
import sys

ROOT = _paths.APP
BOARDS = os.environ.get('BOARDS_DIR', '')
if not BOARDS.startswith(str(ROOT) + os.sep) or os.environ.get('THREADS_NOTIFY') != '0':
    sys.exit('adv_a_fuzz: BOARDS_DIR must be a temp dir inside the repository and THREADS_NOTIFY=0')
os.environ['THREADS_NOW'] = '1800000000.0'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import threads  # noqa: E402

assert str(threads.STATE).startswith(BOARDS + os.sep), threads.STATE
STATE = threads.STATE
REQUEST = threads.BOARD / 'state/state.json'
H = 3600.0
IDS = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
AGENTS = ('tower', 'fork')
READS = ('list', 'show', 'pending')


def call(argv, now, request=None):
    os.environ['THREADS_NOW'] = repr(now)
    threads.migrated_from, threads.mended = None, False
    if request is not None:
        REQUEST.parent.mkdir(parents=True, exist_ok=True)
        REQUEST.write_text(json.dumps(request), encoding='utf-8')
    out, err = io.StringIO(), io.StringIO()
    sys.argv = ['threads.py'] + list(argv)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = threads.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:                                   # the real CLI would print a traceback
        code = 'CRASH ' + repr(exc)
    return code, out.getvalue(), err.getvalue()


def read():
    try:
        raw = STATE.read_bytes()
    except FileNotFoundError:
        return b'', {'threads': {}, 'policy': dict(threads.POLICY)}
    return raw, json.loads(raw)


def uid(t):
    return (t['id'], t['created'])


def pending(t):
    return any(m['from'] == 'owner' and m.get('status') == 'pending' for m in t['messages'])


def is_open(t):
    return t is not None and t['status'] == 'open'


class Fuzz:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.now = 1_800_000_000.0
        self.freed = {}            # slot -> (uid, ts, how) of the thread that last left it
        self.cids = {}             # uid -> set of cids accepted
        self.violations = {}
        self.known = {}
        self.step = 0
        self.trail = []
        self.coverage = {}     # command -> [accepted, refused]

    def bad(self, kind, detail):
        self.violations.setdefault(kind, [])
        if len(self.violations[kind]) < 3:
            self.violations[kind].append({'step': self.step, 'detail': detail, 'trail': self.trail[-6:]})

    def note_known(self, kind):
        self.known[kind] = self.known.get(kind, 0) + 1

    # ── one random command ───────────────────────────────────────────────────
    def pick(self, data):
        r = self.rng
        tid = r.choice(IDS)
        t = data['threads'].get(tid)
        text = r.choice(['עדכון קצר', '**סיימתי** את השלב\nעוד שורה', 'x' * r.randint(1, 400), 'שאלה?', '`code` ועוד'])
        note = r.choice(['בונה', 'להחליט A או B', 'נגמר', 'מריץ   בדיקות\nשורה'])
        kind = r.choices(
            ['new', 'say', 'say-state', 'say-y', 'state', 'ask', 'resolve', 'close', 'reopen', 'rm', 'ack', 'set', 'link', 'policy',
             'sweep', 'read', 'p-reply', 'p-close', 'p-reopen', 'p-keep', 'p-done', 'p-sweep'],
            [10, 12, 8, 6, 8, 6, 5, 6, 6, 2, 6, 2, 2, 1, 2, 8, 12, 3, 4, 3, 5, 2])[0]
        if kind == 'new':
            extra = r.choice([[], [], ['--note', note], ['--state', r.choice(threads.STATES), '--note', note], ['--state', 'done'], ['--by', 'lead']])
            return ['new', tid, 'כותרת ' + tid] + extra, None
        if kind == 'say':
            return ['say', tid, '--from', r.choice(AGENTS), text], None
        if kind == 'say-state':
            state = r.choice(threads.STATES)
            return ['say', tid, '--from', r.choice(AGENTS), text, '--state', state] + (['--note', note] if state == 'on-owner' or r.random() < 0.5 else []), None
        if kind == 'say-y':
            return ['say', tid, '--from', 'owner', text], None
        if kind == 'state':
            state = r.choice(threads.STATES)
            return ['state', tid, state] + (['--note', note] if state == 'on-owner' or r.random() < 0.5 else []), None
        if kind == 'ask':
            return ['ask', tid, text] + r.choice([[], ['--options', 'כן,לא'], ['--options', 'A, B ,C']]) + r.choice([[], ['--from', 'tower']]), None
        if kind == 'resolve':
            return ['resolve', tid] + r.choice([[], ['--note', note]]), None
        if kind in ('close', 'reopen'):
            return [kind, tid], None
        if kind == 'rm':
            return ['rm', tid, '--yes'], None
        if kind == 'ack':
            return ['ack', tid, f'm{r.randint(1, max(2, t["next"] if t else 2))}'], None
        if kind == 'set':
            return ['set', tid, '--summary', note], None
        if kind == 'link':
            return ['link', tid, r.choice('xyz'), '/p/' + str(r.randint(1, 9))] if r.random() < 0.8 else ['link', tid, r.choice('xyz'), '--rm'], None
        if kind == 'policy':
            flag = r.choice(['--idle-hours', '--grace-hours', '--resolved-hours', '--slot-cooldown-hours'])
            return ['policy', flag, r.choice(['0', '0.5', '2', '6', '12', '30'])], None
        if kind == 'sweep':
            return ['sweep'], None
        if kind == 'read':
            return r.choice([['list'], ['list', '--json'], ['list', '--open'], ['show', tid], ['show', tid, '--json'], ['pending'], ['policy']]), None
        if kind == 'p-reply':
            body = {'op': 'reply', 'thread': tid, 'text': text, 'cid': f'c{r.randint(1, 30)}'}
            roll = r.random()
            if roll < 0.35 and t and t.get('question'):
                body['q'] = t['question']['id']
            elif roll < 0.5:
                body['q'] = f'm{r.randint(1, 8)}'
            elif roll < 0.85:       # a typed reply names the question on his screen
                body['under'] = t['question']['id'] if t and t.get('question') else None
            elif roll < 0.95:       # … or what a stale tab still shows
                body['under'] = r.choice([None, f'm{r.randint(1, 8)}'])
            # else: an older page, which says nothing
            return ['ingest'], body
        if kind == 'p-sweep':
            return ['ingest'], {'op': 'sweep'}
        body = {'op': kind[2:], 'thread': tid}
        if kind in ('p-done', 'p-close') and r.random() < 0.9:      # "read it" and "close" name the last message on his screen
            last = t['messages'][-1]['id'] if t and t['messages'] else ''
            body['last'] = last if r.random() < 0.85 else f'm{r.randint(1, 8)}'
        return ['ingest'], body

    def tick(self):
        roll = self.rng.random()
        if roll < 0.6:
            self.now += self.rng.uniform(1, 900)
        elif roll < 0.9:
            self.now += self.rng.uniform(0.5, 9) * H
        elif roll < 0.97:
            self.now += self.rng.uniform(10, 40) * H
        elif roll < 0.985:
            self.now -= self.rng.uniform(1, 3) * H            # a clock that steps back
        # else: the same instant twice

    # ── the invariants ───────────────────────────────────────────────────────
    def check(self, argv, body, code, out, raw0, P, raw1, N):
        cmd = argv[0]
        op = body['op'] if body else None
        tid = (body or {}).get('thread') if body else (argv[1] if len(argv) > 1 and cmd != 'policy' else None)
        cooldown = P['policy']['slot_cooldown_hours'] * H
        if not isinstance(code, int):
            self.bad('crash', code)
            return
        if cmd == 'ingest':
            lines = out.strip().splitlines()
            if len(lines) != 1 or json.loads(lines[0]).get('ok') is not (code == 0):
                self.bad('ingest-output', out[:200])
        if code != 0 and raw1 != raw0:
            self.bad('refused-but-wrote', argv)
        Pt, Nt = P['threads'], N['threads']
        archived = [k for k, t in Nt.items() if k in Pt and is_open(Pt[k]) and not is_open(t) and uid(t) == uid(Pt[k]) and t.get('closed_by') == 'auto' and t.get('closed_ts') == self.now]
        explicit_close = code == 0 and ((cmd == 'close') or op == 'close')
        archived = [k for k in archived if not (explicit_close and k == tid)]
        if (cmd in READS or (cmd == 'policy' and len(argv) == 1)) and raw1 != raw0 and not archived:
            self.bad('read-wrote', argv)
        # 2. only an idle `done` thread past its deadline is archived
        for k in archived:
            old = Pt[k]
            if old['state'] != 'done' or pending(old) or old.get('archive_at') is None or old['archive_at'] > self.now:
                self.bad('archived-while-waiting', {'thread': k, 'state': old['state'], 'pending': pending(old), 'archive_at': old.get('archive_at'), 'now': self.now})
        # 3. history
        for k, old in Pt.items():
            new = Nt.get(k)
            if new is None or uid(new) != uid(old):
                if not (code == 0 and cmd == 'rm' and tid == k):
                    self.bad('thread-vanished', {'thread': k, 'cmd': argv})
                if is_open(old):
                    self.freed[old['slot']] = (uid(old), self.now, 'rm')
                elif old['slot'] in self.freed and self.freed[old['slot']][0] == uid(old):
                    self.freed[old['slot']] = (uid(old), self.freed[old['slot']][1], 'rm')
                continue
            for i, m in enumerate(old['messages']):
                if i >= len(new['messages']):
                    self.bad('message-lost', {'thread': k, 'msg': m['id'], 'cmd': argv})
                    break
                same = new['messages'][i]
                if same != m:
                    acked = cmd == 'ack' and code == 0 and argv[2] == m['id'] and {x: y for x, y in same.items() if x not in ('status', 'acked_ts')} == {x: y for x, y in m.items() if x != 'status'}
                    if not acked:
                        self.bad('message-rewritten', {'thread': k, 'msg': m['id'], 'cmd': argv})
            ids = [m['id'] for m in new['messages']]
            if len(set(ids)) != len(ids):
                self.bad('message-id-reused', {'thread': k})
        # 1. slots
        slots = {}
        for k, t in Nt.items():
            if is_open(t):
                if type(t['slot']) is not int or t['slot'] <= 0:
                    self.bad('slot-not-positive-int', {'thread': k, 'slot': t['slot']})
                if t['slot'] in slots:
                    self.bad('slot-duplicate', {'slot': t['slot'], 'threads': [slots[t['slot']], k]})
                slots[t['slot']] = k
        for k, new in Nt.items():
            old = Pt.get(k)
            same = old is not None and uid(old) == uid(new)
            if same and is_open(old) and is_open(new) and old['slot'] != new['slot']:
                self.bad('slot-moved-while-open', {'thread': k, 'from': old['slot'], 'to': new['slot'], 'cmd': argv})
            if same and is_open(old) and not is_open(new):
                self.freed[old['slot']] = (uid(old), self.now, 'close')
                if new['slot'] != old['slot']:
                    self.bad('closed-thread-forgot-its-slot', {'thread': k})
            if is_open(new) and not (same and is_open(old)):          # took a slot in this step
                last = self.freed.get(new['slot'])
                if last and last[0] != uid(new) and 0 <= self.now - last[1] < cooldown:
                    if last[2] == 'rm':
                        self.note_known('cooldown-skipped-after-rm')
                    elif same and old['slot'] == new['slot']:
                        self.note_known('reopen-into-own-slot-resting-for-another')
                    else:
                        self.bad('resting-slot-given-away', {'thread': k, 'slot': new['slot'], 'freed_by': last[0][0], 'ago_h': (self.now - last[1]) / H, 'cmd': argv})
        # schedule and note rule
        for k, t in Nt.items():
            waits = not is_open(t) or t['state'] != 'done' or pending(t)
            if waits != (t['archive_at'] is None) or (t['archive_at'] is None) != (t['soon_at'] is None):
                self.bad('schedule-wrong', {'thread': k, 'state': t['state'], 'archive_at': t['archive_at']})
            if t['archive_at'] is not None and t['soon_at'] > t['archive_at']:
                self.bad('soon-after-archive', {'thread': k})
            if t['state'] not in threads.STATES:
                self.bad('unknown-state', {'thread': k, 'state': t['state']})
            if is_open(t) and t['state'] == 'on-owner':
                note = t['note']
                if not isinstance(note, str) or not note.strip() or len(note.splitlines()) != 1 or len(note) > 200:
                    self.bad('on-owner-note', {'thread': k, 'note': note, 'cmd': argv})
            # An open question waits for HIS answer: it may sit in a thread an agent is working on (the agent wrote again
            # after asking), never in one that is done, and never in one that is on him only "to read" (that could be put away).
            if t['question'] is not None and (t['state'] == 'done' or (t['state'] == 'on-owner' and t['auto'])):
                self.bad('question-open-in-a-thread-that-is-done-or-only-to-read', {'thread': k, 'state': t['state'], 'auto': t['auto']})
            qs = t.get('questions')
            if not isinstance(qs, list) or len(qs) > threads.QUESTIONS_MAX or (qs[-1] if qs else None) != t['question']:
                self.bad('questions-shape', {'thread': k, 'questions': qs, 'question': t['question']})
            if len(t['note']) > 200 or len(t['note'].splitlines()) > 1:
                self.bad('note-shape', {'thread': k, 'note': t['note']})
        # 7. the turn
        old = Pt.get(tid) if tid else None
        new = Nt.get(tid) if tid else None
        if code == 0 and old is not None and new is not None and uid(old) == uid(new) and is_open(old):
            if cmd == 'say' and argv[3] in AGENTS and '--state' not in argv:
                if new['state'] != 'on-owner':
                    self.bad('plain-agent-message-left-' + new['state'], {'thread': tid})
                if old['state'] == 'on-owner' and not old['auto'] and (new['note'], new['auto'], new['question']) != (old['note'], old['auto'], old['question']):
                    self.bad('explicit-ask-overwritten', {'thread': tid, 'old': old['note'], 'new': new['note']})
            owner = (cmd == 'say' and argv[3] == 'owner') or (op == 'reply' and not json.loads(out).get('dup'))
            # Several questions may be open (suda m508). His reply closes the one it answers and no other: the one he
            # tapped (q), else the one whose message he replied to, else the newest he had on screen (under; a typed
            # reply from an older page that does not say: the newest; under null: none). While one stays open the
            # thread stays on him for it; with none left, the turn goes to the agents.
            opened = lambda t: [q['id'] for q in t['questions']] if isinstance(t.get('questions'), list) else ([t['question']['id']] if t['question'] else [])
            asking = lambda mid: any(m['id'] == mid and m.get('q') for m in old['messages'])
            before, newest = opened(old), (opened(old) or [None])[-1]
            if owner:
                reply_to = body.get('reply_to') if op == 'reply' else None
                if op == 'reply' and 'q' in body:
                    answered, expect = body['q'], body['q']
                elif reply_to and asking(reply_to):
                    answered, expect = (reply_to if reply_to in before else None), reply_to
                elif op != 'reply':
                    answered, expect = newest, newest
                elif 'under' not in body:
                    # an old page that does not say: nothing is closed or named (suda m508: a "yes" must never be
                    # filed as the answer to a question he did not see)
                    answered, expect = None, None
                else:
                    named = body['under']
                    answered = named if named in before else None
                    expect = named if named and asking(named) else None
                left = [q for q in before if q != answered]
                if opened(new) != left:
                    self.bad('owner-reply-closed-the-wrong-questions', {'thread': tid, 'before': before, 'after': opened(new), 'answered': answered})
                if not left and (new['state'], new['question'], new['auto']) != ('working', None, True):
                    self.bad('owner-reply-turn', {'thread': tid, 'state': new['state'], 'question': new['question']})
                if left and answered is None and (new['state'], new['question'], new['note']) != (old['state'], old['question'], old['note']):
                    self.bad('stale-reply-settled-a-question-he-did-not-see', {'thread': tid})
                if left and answered is not None and old['state'] == 'on-owner' and (new['state'], new['auto']) != ('on-owner', False):
                    self.bad('open-question-left-off-him', {'thread': tid, 'state': new['state']})
                if new['messages'][-1].get('re', {}).get('q') != expect:
                    self.bad('reply-not-tied-to-question', {'thread': tid, 'expect': expect, 're': new['messages'][-1].get('re')})
            if op == 'done' and body.get('last') != (old['messages'][-1]['id'] if old['messages'] else ''):
                self.bad('done-on-a-stale-screen', {'thread': tid})
            if op == 'done' and not (old['state'] == 'on-owner' and old['auto']):
                self.bad('done-dismissed-a-real-ask', {'thread': tid, 'state': old['state'], 'auto': old['auto']})
            if op == 'keep' and any(new[key] != old[key] for key in ('state', 'note', 'auto', 'question', 'slot', 'messages')):
                self.bad('keep-changed-the-turn', {'thread': tid})
        # 6. replies
        if op == 'reply':
            result = json.loads(out)
            seen = self.cids.setdefault(uid(old), set()) if old is not None else set()
            if old is None or not is_open(old):
                # A message that is already in the thread is answered as it was the first time (the page sends again
                # when it heard no answer, and the thread may have been closed since), and nothing is written.
                # Anything else into a closed or missing thread is refused.
                if old is not None and body['cid'] in seen:
                    if not (code == 0 and result.get('dup') and raw1 == raw0):
                        self.bad('duplicate-cid-not-idempotent', {'thread': tid, 'result': result})
                elif code == 0:
                    self.bad('reply-into-closed-or-missing', {'thread': tid})
            elif body['cid'] in seen:
                if not (code == 0 and result.get('dup') and raw1 == raw0):
                    self.bad('duplicate-cid-not-idempotent', {'thread': tid, 'result': result})
            else:
                q_ok = 'q' not in body or (old['question'] is not None and old['question']['id'] == body['q'])
                if q_ok != (code == 0):
                    self.bad('reply-q-rule', {'thread': tid, 'q': body.get('q'), 'open': old['question'] and old['question']['id'], 'result': result})
                if code == 0:
                    if result.get('dup') or len(new['messages']) != len(old['messages']) + 1 or new['messages'][-1]['text'] != body['text']:
                        self.bad('reply-not-stored', {'thread': tid, 'result': result})
                    seen.add(body['cid'])

    def run(self, steps):
        for self.step in range(steps):
            self.tick()
            raw0, P = read()
            argv, body = self.pick(P)
            code, out, err = call(argv, self.now, body)
            raw1, N = read()
            self.coverage.setdefault(body['op'] + ' (page)' if body else argv[0], [0, 0])[0 if code == 0 else 1] += 1
            self.trail.append([round((self.now - 1_800_000_000.0) / H, 3), body or argv, code])
            try:
                self.check(argv, body, code, out, raw0, P, raw1, N)
            except Exception as exc:                            # a checker bug must not hide as a pass
                self.bad('checker-error', repr(exc))
        return {'steps': steps, 'violations': self.violations, 'known': self.known, 'coverage': self.coverage}


if __name__ == '__main__':
    print(json.dumps(Fuzz(int(sys.argv[1])).run(int(sys.argv[2])), ensure_ascii=False))
