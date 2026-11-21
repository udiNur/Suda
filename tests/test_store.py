#!/usr/bin/env python3
"""The board in SQLite and Suda's own server (sqlite177, suda-connectivity task 16, m16, m17).

What is checked: the first command takes the board's state.json in; a save writes only the threads that changed;
the summary carries the open threads and the recently closed ones, the rest are in closed.json and still found by
a command that names them; export-state gives back the whole board; a newer state.json is taken in only into an
empty store or with THREADS_AUTO_IMPORT=1 (an old threads.py must never overwrite the board); the server answers
"every change since n" from any distance, and a page that applies it holds exactly the summary; it never serves
the store, nor another board, nor a foreign Host; its live line sends the change itself.
Temp BOARDS_DIR, loopback only.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / 'suda' / 'threads.py'
SERVER = ROOT / 'suda' / 'server.py'
DAY = 86400


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def a_thread(tid, status='open', closed_days=None, messages=3, now=None):
    now = now or time.time()
    t = {'id': tid, 'title': 'נושא ' + tid, 'context': '', 'status': status, 'created': now - 30 * DAY, 'updated': now - DAY,
         'next': messages + 1, 'slot': None, 'summary': '', 'links': [], 'state': 'working', 'note': 'הערה',
         'state_ts': now - DAY, 'state_by': 'fork', 'auto': False, 'question': None, 'resolved': False,
         'touched': now - DAY, 'soon_at': None, 'archive_at': None, 'tasks': [], 'questions': [],
         'messages': [{'id': 'm%d' % i, 'from': 'fork', 'text': 'הודעה %d' % i, 'ts': now - DAY + i} for i in range(1, messages + 1)]}
    if status != 'open':
        t['closed_ts'] = now - (closed_days or 0) * DAY
        t['closed_by'] = 'auto'
        t['state'] = 'done'
    return t


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.store-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.boards = Path(self.tmp.name) / 'boards'
        self.board = self.boards / 'threads'
        self.env = dict(os.environ, BOARDS_DIR=str(self.boards), THREADS_NOTIFY='0', THREADS_SLUG='threads')
        for key in ('THREADS_EXPORT_STATE', 'THREADS_AUTO_IMPORT', 'THREADS_STORE', 'THREADS_HOT_DAYS', 'TUIOS_PANE_ID'):
            self.env.pop(key, None)

    def cli(self, *args, env=None, ok=True):
        r = subprocess.run([sys.executable, str(CLI), *args], env=env or self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def seed(self, threads):
        self.cli('install')
        self.cli('export-state')
        state = json.loads((self.board / 'state.json').read_text())
        state['threads'] = {t['id']: t for t in threads}
        time.sleep(0.01)
        (self.board / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
        self.cli('import-state')

    def db(self):
        return sqlite3.connect(str(self.board / 'suda.db'))

    def summary(self):
        return json.loads((self.board / 'summary.json').read_text())

    def test_a_command_that_saves_nothing_makes_no_store(self):
        self.cli('install')
        for path in list(self.board.glob('suda.db*')):
            path.unlink()
        (self.board / 'state.json').write_text(json.dumps({'version': 3, 'threads': {}}))     # (the release's version: 2 would migrate, a save)
        self.cli('list', '--json')
        self.assertFalse((self.board / 'suda.db').exists(), 'a command that saves nothing makes no store')

    def test_the_first_command_takes_the_board_in_and_writes_no_state_json_after(self):
        self.cli('install')
        self.cli('new', 'one', 'נושא אחד', '--state', 'working', '--note', 'בודקים', '--by', 't')
        self.assertTrue((self.board / 'suda.db').exists())
        self.assertFalse((self.board / 'state.json').exists(), 'state.json is no longer written')
        self.assertIn('one', self.summary()['threads'])
        self.assertTrue((self.board / 'full' / 'one.json').exists())

    def test_his_real_board_writes_state_json_after_every_save_until_the_server_answers_it(self):
        # The board view (board.html) reads state.json; on his real board it is written after every save again
        # (statefix183), a test's board writes it only with THREADS_EXPORT_STATE=1, and =0 turns it off anywhere.
        probe = ('import importlib.util, sys; spec = importlib.util.spec_from_file_location("t", sys.argv[1]); '
                 't = importlib.util.module_from_spec(spec); spec.loader.exec_module(t); real = sys.argv[2] == "1"; '
                 't.real_board = lambda: real; print(t.export_wanted())')
        def wanted(real, value=None):
            env = dict(self.env)
            if value is not None:
                env['THREADS_EXPORT_STATE'] = value
            r = subprocess.run([sys.executable, '-c', probe, str(CLI), '1' if real else '0'], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()
        self.assertEqual(wanted(True), 'True')
        self.assertEqual(wanted(True, '0'), 'False')
        self.assertEqual(wanted(False), 'False')
        self.assertEqual(wanted(False, '1'), 'True')
        self.cli('install')
        env = dict(self.env, THREADS_EXPORT_STATE='1')
        self.cli('new', 'one', 'נושא אחד', '--state', 'working', '--note', 'בודקים', '--by', 't', env=env)
        self.cli('say', 'one', '--from', 'fork', 'הודעה חדשה עכשיו', '--state', 'working', '--note', 'עוד', env=env)
        state = json.loads((self.board / 'state.json').read_text())
        self.assertEqual(state['threads']['one']['messages'][-1]['text'], 'הודעה חדשה עכשיו')

    def test_a_save_writes_only_the_threads_that_changed(self):
        self.seed([a_thread('a'), a_thread('b'), a_thread('c')])
        before = dict(self.db().execute('SELECT id, body FROM threads'))
        files = {p.name: p.stat().st_mtime_ns for p in (self.board / 'full').iterdir()}
        time.sleep(0.02)
        self.cli('say', 'b', '--from', 'fork', 'חדש', '--state', 'working', '--note', 'עוד')
        after = dict(self.db().execute('SELECT id, body FROM threads'))
        self.assertEqual(before['a'], after['a'])
        self.assertEqual(before['c'], after['c'])
        self.assertNotEqual(before['b'], after['b'])
        now = {p.name: p.stat().st_mtime_ns for p in (self.board / 'full').iterdir()}
        self.assertEqual(now['a.json'], files['a.json'], 'a conversation that did not change is not written again')
        self.assertNotEqual(now['b.json'], files['b.json'])

    def test_closed_long_ago_leaves_the_summary_but_is_listed_and_found(self):
        self.seed([a_thread('open1'), a_thread('recent', 'closed', 2), a_thread('old', 'closed', 40)])
        summary = self.summary()
        self.assertIn('recent', summary['threads'])
        self.assertNotIn('old', summary['threads'])
        self.assertEqual(summary['cold'], 1)
        closed = json.loads((self.board / 'closed.json').read_text())['threads']
        self.assertEqual([r['id'] for r in closed], ['old'])
        full = json.loads((self.board / 'full' / 'old.json').read_text())
        self.assertEqual(full['row']['id'], 'old', 'its file carries its row: the page opens it from that alone')
        shown = json.loads(self.cli('show', 'old', '--json').stdout)
        self.assertEqual(shown['id'], 'old')
        listed = [t['id'] for t in json.loads(self.cli('list', '--json').stdout)]
        self.assertIn('old', listed, 'a listing sees every thread')
        # writing into it brings it back (a thread that archived itself): in the summary again
        self.cli('say', 'old', '--from', 'fork', 'חוזר', '--state', 'working', '--note', 'חוזר')
        summary = self.summary()
        self.assertIn('old', summary['threads'])
        self.assertEqual(summary['cold'], 0)

    def test_export_gives_back_the_whole_board(self):
        threads = [a_thread('x'), a_thread('y', 'closed', 50)]
        self.seed(threads)
        out = Path(self.tmp.name) / 'back.json'
        self.cli('export-state', '--to', str(out))
        back = json.loads(out.read_text())
        self.assertEqual(sorted(back['threads']), ['x', 'y'])
        self.assertEqual([m['text'] for m in back['threads']['y']['messages']], [m['text'] for m in threads[1]['messages']])

    def test_a_newer_state_json_is_not_taken_in_by_itself_on_a_board_in_use(self):
        self.seed([a_thread('keep')])
        self.cli('say', 'keep', '--from', 'fork', 'בטוח', '--state', 'working', '--note', 'x')
        stale = json.loads((self.board / 'state.json').read_text())
        stale['threads'] = {}                                      # an old threads.py wrote an empty board
        time.sleep(0.01)
        (self.board / 'state.json').write_text(json.dumps(stale))
        self.cli('say', 'keep', '--from', 'fork', 'עדיין כאן', '--state', 'working', '--note', 'x')
        self.assertIn('keep', self.summary()['threads'], 'the store stays the truth')
        self.assertIn('not taken in', (self.board / 'notify.log').read_text())
        # with THREADS_AUTO_IMPORT=1 (tests, netlab) it is taken in, and the store it replaced is kept
        time.sleep(0.01)
        (self.board / 'state.json').write_text(json.dumps(stale))
        self.cli('new', 'other', 'אחר', '--state', 'working', '--note', 'x', '--by', 't', env=dict(self.env, THREADS_AUTO_IMPORT='1'))   # (taken in by the first save)
        self.assertNotIn('keep', self.summary()['threads'])
        self.assertTrue(list(self.board.glob('suda.db.bak-*')), 'the store before the import is kept')

    def test_the_file_store_still_works(self):
        env = dict(self.env, THREADS_STORE='file')
        self.cli('install', env=env)
        self.cli('new', 'f', 'קובץ', '--state', 'working', '--note', 'x', '--by', 't', env=env)
        self.assertIn('f', json.loads((self.board / 'state.json').read_text())['threads'])


class Server(Store):
    """Suda's own server on a free port over the same temp board."""

    def start(self):
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', str(self.port)], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.proc.kill)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url('/threads/summary.json'), timeout=1)
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        self.fail('the server did not start')

    def url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.port, path)

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b''

    def test_every_change_since_any_number_and_the_page_holds_the_summary(self):
        self.seed([a_thread('t%d' % i) for i in range(5)])
        old = self.summary()
        for i in range(30):
            self.cli('say', 't%d' % (i % 5), '--from', 'fork', 'עדכון %d' % i, '--state', 'working', '--note', 'n')
        self.start()
        status, body = self.get('/threads/changes/%d.json' % old['seq'])
        self.assertEqual(status, 200)
        run = json.loads(body)
        self.assertEqual(run['seq'], self.summary()['seq'])
        # apply as the page does (its pure catchUp) and compare with the summary on disk
        page = (ROOT / 'suda' / 'suda.html').read_text(encoding='utf-8')
        pure = page.split('// <pure>')[1].split('// </pure>')[0]
        js = Path(self.tmp.name) / 'apply.js'
        js.write_text(pure + "\nconst fs=require('fs');const a=JSON.parse(fs.readFileSync(process.argv[2]));const r=JSON.parse(fs.readFileSync(process.argv[3]));"
                      "const n=catchUp(a,r);process.stdout.write(JSON.stringify(n));", encoding='utf-8')
        (Path(self.tmp.name) / 'old.json').write_text(json.dumps(old))
        (Path(self.tmp.name) / 'run.json').write_text(body.decode())
        out = subprocess.run(['node', str(js), str(Path(self.tmp.name) / 'old.json'), str(Path(self.tmp.name) / 'run.json')],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), self.summary())

    def test_the_store_another_board_and_a_foreign_host_are_refused(self):
        self.seed([a_thread('s')])
        (self.boards / 'other').mkdir()
        (self.boards / 'other' / 'board.html').write_text('x')
        self.start()
        self.assertEqual(self.get('/threads/suda.db')[0], 404)
        self.assertEqual(self.get('/other/board.html')[0], 404)
        self.assertEqual(self.get('/threads/summary.json', {'Host': 'evil.example'})[0], 403)
        status, body = self.get('/threads/summary.json', {'Range': 'bytes=0-63'})
        self.assertEqual((status, len(body)), (206, 64))

    def test_the_line_sends_the_change_itself(self):
        self.seed([a_thread('live')])
        since = self.summary()['seq']
        self.cli('say', 'live', '--from', 'fork', 'על הקו', '--state', 'working', '--note', 'n')
        self.start()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        s.sendall(b'GET /events?board=threads&since=%d HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' % since)
        got, end = b'', time.time() + 5
        while b'data: changed' not in got and time.time() < end:
            got += s.recv(65536)
        s.close()
        self.assertIn(b'event: delta', got)
        self.assertIn('על הקו'.encode(), got)
        self.assertLess(got.index(b'event: delta'), got.index(b'data: changed'))


for _name in [n for n in dir(Store) if n.startswith('test')]:
    if _name not in Server.__dict__:
        setattr(Server, _name, None)

if __name__ == '__main__':
    unittest.main()
