"""Suda's board in SQLite (suda-connectivity task 16, m16, m17).

One file beside the board's other files, `suda.db`, is the truth: every top-level key of the state, every thread
as the state holds it (with its summary row and its whole conversation record, so a save rebuilds only the threads
that changed), and every change a page may need to catch up from any number. Standard library only (sqlite3).

Tables:
  meta(k, v)                          v: the JSON text of one top-level key of the state (version, policy, notify,
                                      spaces, seq, ...), and the store's own keys (store:*)
  threads(id, hot, closed, body, row, whole)
                                      body: the thread as state.json held it (compact JSON); row: its row in the
                                      summary; whole: its full/<id>.json record; hot: 1 when the summary carries it
                                      (open, or closed a short while ago); closed: when it closed (None when open)
  changes(seq, frm, entry)            entry: one change as changes.json holds it, numbered by the board's number it
                                      leads to and the one it starts from

Writers hold the board's lock (threads.py `locked()`); readers (the server, a look without the lock) read a
consistent snapshot (WAL).
"""
import json
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY, pos INTEGER, hot INTEGER NOT NULL, closed REAL, body TEXT NOT NULL,
                                   row TEXT, whole TEXT);
CREATE INDEX IF NOT EXISTS threads_hot ON threads(hot);
CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY, frm INTEGER NOT NULL, entry TEXT NOT NULL);
"""
STORE_KEYS = ('store:imported',)        # the store's own keys in meta: never a key of the state


class Store:
    def __init__(self, path, readonly=False):
        self.path = Path(path)
        if readonly:
            self.db = sqlite3.connect('file:%s?mode=ro' % self.path, uri=True, timeout=15, isolation_level=None)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
            fresh = not self.path.exists()
            if fresh:
                # one file, a rollback journal: a read changes nothing on disk (WAL keeps -wal and -shm files that a
                # read touches); writers hold the board's lock anyway, and a reader waits a few ms at most
                self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.executescript(SCHEMA)
            cols = [r[1] for r in self.db.execute('PRAGMA table_info(threads)')]
            if 'pos' not in cols:           # a store from before the order was kept
                self.db.execute('ALTER TABLE threads ADD COLUMN pos INTEGER')
                self.db.execute('UPDATE threads SET pos=rowid WHERE pos IS NULL')
            if fresh:
                os.chmod(self.path, 0o600)
        self.db.execute('PRAGMA busy_timeout=15000')

    def close(self):
        self.db.close()

    # ── reading ──
    def empty(self):
        return self.db.execute("SELECT 1 FROM meta WHERE k='version'").fetchone() is None

    def meta(self):
        """The top-level keys of the state (without the store's own)."""
        return {k: json.loads(v) for k, v in self.db.execute('SELECT k, v FROM meta') if not k.startswith('store:')}

    def get(self, key, default=None):
        row = self.db.execute('SELECT v FROM meta WHERE k=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def bodies(self, hot_only=True):
        """[(id, body text)] of the hot threads (or of all)."""
        q = 'SELECT id, body FROM threads' + (' WHERE hot=1' if hot_only else '') + ' ORDER BY pos, id'
        return list(self.db.execute(q))

    def body(self, tid):
        row = self.db.execute('SELECT body FROM threads WHERE id=?', (tid,)).fetchone()
        return row[0] if row else None

    def ids(self, hot=None):
        q = 'SELECT id FROM threads' + ('' if hot is None else ' WHERE hot=%d' % (1 if hot else 0)) + ' ORDER BY pos, id'
        return [r[0] for r in self.db.execute(q)]

    def rows(self):
        """{id: row text} of the hot threads: the threads of the summary as it stands."""
        return {tid: row for tid, row in self.db.execute('SELECT id, row FROM threads WHERE hot=1 ORDER BY pos, id') if row is not None}

    def whole(self, tid):
        row = self.db.execute('SELECT whole FROM threads WHERE id=?', (tid,)).fetchone()
        return row[0] if row else None

    def cold_index(self):
        """[(id, closed, row text)] of the threads the summary no longer carries, the newest closed first."""
        return list(self.db.execute('SELECT id, closed, row FROM threads WHERE hot=0 ORDER BY closed DESC, id'))

    def entries_since(self, n, limit_bytes=None, limit_count=None):
        """The change entries (texts) from number n on, when they make an unbroken chain from n; else None.
        `limit_*`: None when the chain is longer (the caller reads the whole summary instead)."""
        out, size, at = [], 0, n
        for seq, frm, entry in self.db.execute('SELECT seq, frm, entry FROM changes WHERE seq>? ORDER BY seq', (n,)):
            if frm != at:
                return None
            size += len(entry) + 1
            if (limit_bytes is not None and size > limit_bytes) or (limit_count is not None and len(out) >= limit_count):
                return None
            out.append(entry)
            at = seq
        return out

    def condensed_since(self, n):
        """Every change from number n to the board's as ONE entry: the row of each thread that changed since n as
        it stands now (None for a thread the summary no longer carries), the summary's top level as it stands, and
        its mark. For a page far behind (two days away: 1,500 changes add up to more than the summary). None when n
        is not on the chain the store holds. Read in one snapshot."""
        db = self.db
        db.execute('BEGIN')
        try:
            at, seen, last = n, set(), None
            for seq, frm, entry in db.execute('SELECT seq, frm, entry FROM changes WHERE seq>? ORDER BY seq', (n,)):
                if frm != at:
                    return None
                e = json.loads(entry)
                seen.update(e.get('threads') or {})
                seen.update(e.get('edit') or {})
                at = last = seq
            if last is None:
                return None
            rows = {tid: row for tid, row in db.execute('SELECT id, row FROM threads WHERE hot=1 ORDER BY pos, id')}
            meta = {k: json.loads(v) for k, v in db.execute('SELECT k, v FROM meta')}
            cold = db.execute('SELECT COUNT(*) FROM threads WHERE hot=0').fetchone()[0]
        finally:
            db.execute('COMMIT')
        if meta.get('seq') != last:
            return None
        top = {k: v for k, v in meta.items() if not k.startswith('store:') and k != 'seq'}
        top.update(lite=1, cold=cold, mark=meta.get('store:mark'))
        threads = {tid: (json.loads(rows[tid]) if tid in rows else None) for tid in sorted(seen)}
        return {'from': n, 'seq': last, 'threads': threads, 'top': top}

    def last_entries(self, count):
        rows = list(self.db.execute('SELECT entry FROM changes ORDER BY seq DESC LIMIT ?', (count,)))
        return [json.loads(r[0]) for r in reversed(rows)]

    # ── writing (under the board's lock) ──
    def write(self, meta, threads=(), gone=(), entry=None, keep_entries_after=None, store_keys=None):
        """One save, all or nothing. meta: {key: value} of the state's top level (keys not named are removed);
        threads: [(id, hot, closed, body, row, whole)] that changed; gone: ids removed; entry: (seq, frm, text)."""
        db = self.db
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute("DELETE FROM meta WHERE k NOT LIKE 'store:%'")
            db.executemany('INSERT INTO meta(k, v) VALUES(?, ?)',
                           [(k, json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) for k, v in meta.items()])
            for k, v in (store_keys or {}).items():
                db.execute('INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)', (k, json.dumps(v)))
            for t in threads:
                db.execute('INSERT INTO threads(id, pos, hot, closed, body, row, whole) VALUES(?, (SELECT IFNULL(MAX(pos), 0) + 1 FROM threads), ?, ?, ?, ?, ?) '
                           'ON CONFLICT(id) DO UPDATE SET hot=excluded.hot, closed=excluded.closed, body=excluded.body, row=excluded.row, whole=excluded.whole',
                           t)
            db.executemany('DELETE FROM threads WHERE id=?', [(tid,) for tid in gone])
            if entry is not None:
                db.execute('INSERT OR REPLACE INTO changes(seq, frm, entry) VALUES(?, ?, ?)', entry)
            if keep_entries_after is not None:
                db.execute('DELETE FROM changes WHERE seq<=?', (keep_entries_after,))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise

    def replace_all(self, meta, threads, store_keys=None):
        """An import: the whole board anew (the changes too: no page can catch up across it)."""
        db = self.db
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('DELETE FROM meta')
            db.execute('DELETE FROM threads')
            db.execute('DELETE FROM changes')
            db.executemany('INSERT INTO meta(k, v) VALUES(?, ?)',
                           [(k, json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) for k, v in meta.items()])
            for k, v in (store_keys or {}).items():
                db.execute('INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)', (k, json.dumps(v)))
            db.executemany('INSERT INTO threads(id, pos, hot, closed, body, row, whole) VALUES(?, ?, ?, ?, ?, ?, ?)',
                           [(t[0], i + 1, *t[1:]) for i, t in enumerate(threads)])
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
