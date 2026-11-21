#!/usr/bin/env python3
"""Suda's own board server, for a clone without the html-interview-board skill.

    python3 server.py [--port 8767]        # then open http://127.0.0.1:8767/threads/suda.html

It listens on 127.0.0.1 only. To reach it from a phone, put a gateway in front of it (see SECURITY.md) and name the
gateway's host in SUDA_ALLOWED_HOSTS. What it does:
  GET  /<board>/<file>      a file of the boards folder (no dot-paths, no folder listings, nothing outside it).
                            One byte range (Range: bytes=a-b, a-, -n) is a 206 with Content-Range, a start past the
                            end a 416; several ranges, a malformed one or an If-Range that no longer matches: the
                            whole file. A video seeks, and the page reads the first bytes of summary.json.
                            Never the board's store (suda.db, its journal, backups and locks). changes/<n>.json is
                            answered from the store for ANY number n it keeps (every change since, or one condensed
                            entry when that is smaller), the file of that name being the fallback.
  POST /api/state           {board, state}: stored as <board>/state/state.json, then the board's on-state.sh runs
                            (`threads install` writes it) and its last lines are the answer
  GET  /events?board=<b>    a stream that says "changed" when the board's page (suda.html) or its .pulse changes.
                            When the pulse holds a number (threads.py writes the number of the board's last change
                            there), the SSE standard: "retry: 2000" once, every "changed" carries "id: <number>", a
                            client that says where it was (Last-Event-ID, else ?since=N) hears no first "changed"
                            when that is the number, and a named heartbeat "event: alive" / "data: <number>" goes at
                            once and every 10 s instead of the ": ping". Before a "changed", when it can, the change
                            itself: "event: delta" / "data: {head, run}" (changes/<the number this line told>.json,
                            else the run built from changes.json, else the run from the store, with the first 64
                            bytes of summary.json; one line
                            of at most 32 KB), so the page reads nothing for that update.
  *    /mdv/...             the MD Viewer (mdv/ of this repository, put by `threads install` in THREADS_MDV_DIR, else
                            beside the boards folder when BOARDS_DIR is set, else ~/.local/share/threads/mdv), behind
                            this server's own Host and Origin guards. A viewer that is missing, does not import or
                            raises answers 503 on /mdv/ only; the board goes on.
"""
import argparse
import datetime
import email.utils
import json
import mimetypes
import os
from pathlib import Path
import re
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.dont_write_bytecode = True
sys.path.insert(0, os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board')))
sys.path.insert(1, str(Path(os.path.realpath(__file__)).parent))
try:
    import boardlib as bl
except ImportError:
    import suda_boardlib as bl
import importlib.util  # noqa: E402

HERE = Path(os.path.realpath(__file__)).parent
_STORE = {}


def store_module():
    """Suda's store.py beside this file (the board in SQLite, sqlite177), loaded once; None without it."""
    if 'mod' not in _STORE:
        try:
            spec = importlib.util.spec_from_file_location('suda_store_server', HERE / 'store.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001 - no store: the files answer, as before
            mod = None
        _STORE['mod'] = mod
    return _STORE['mod']

BODY_MAX = 4_000_000            # one request; a bigger text comes in parts (see threads.py, snippet-part)
HOOK_TIMEOUT = 60
SLUG = os.environ.get('THREADS_SLUG') or 'threads'     # the one board this server is for (never the rest of BOARDS_DIR)
NEVER = ('.sh', '.py')                                # the board's hook and code are not pages
STORE = re.compile(r'(^|/)(suda\.db(-wal|-shm|-journal|\.bak-[^/]*)?|[^/]*\.lock)$')   # the board's SQLite store, its journal, backups, locks
STREAMS = threading.BoundedSemaphore(32)              # /events at once
LOCAL = ('127.0.0.1', 'localhost', '[::1]')
SEGMENT = re.compile(r'[A-Za-z0-9_\-][A-Za-z0-9_.\-]*')
STATE_LOCK = threading.Lock()   # one request is stored and handled at a time
CHUNK = 64 * 1024               # a file is sent in pieces of this size (a long video is never read whole)

# /events: how often the files are looked at, the ping of a board without a number, the heartbeat of a board with one,
# the reconnect delay it asks for, the most bytes of a change that ride on the line, and the most of changes.json read
# (threads.py keeps it under 256 KB).
SSE_POLL_S = 1.0
SSE_PING_S = 15.0
SSE_ALIVE_S = 10.0
SSE_RETRY_MS = 2000
SSE_INLINE_MAX = 32768
SSE_CHANGES_READ = 300 * 1024

# The MD Viewer: a viewer that failed to import is tried again after this many seconds (a new install, no restart).
MDV_RETRY = float(os.environ.get('SUDA_MDV_RETRY', '30'))
MDV = {'mod': None, 'cfg': None, 'failed': 0.0}
MDV_LOCK = threading.Lock()


def allowed_hosts():
    extra = os.environ.get('SUDA_ALLOWED_HOSTS', '')
    return {h.strip().lower() for h in extra.split(',') if h.strip()}


def host_name(host):
    host = (host or '').strip().lower()
    if host.startswith('['):
        return host.split(']')[0] + ']'
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


def inside(root, url_path):
    """The file a URL path names inside `root`, or None: every segment a plain name (no '.', '..', dot-files,
    backslashes or NUL), and nothing reached through a link that leaves the folder."""
    parts = unquote(url_path).split('/')[1:]
    if not parts or any(not SEGMENT.fullmatch(p) for p in parts):
        return None
    target = root.joinpath(*parts)
    try:
        real, base = target.resolve(), root.resolve()
    except (OSError, RuntimeError):
        return None
    return target if real == base or base in real.parents else None


def scrub(value):
    """A lone UTF-16 half (a quote cut in the middle of an emoji) cannot be written as UTF-8: it becomes U+FFFD."""
    if isinstance(value, str):
        return re.sub('[\ud800-\udfff]', '�', value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    return value


def byte_range(value, size):
    """The one byte range a Range header asks of a file of `size` bytes: (first, last) inclusive, 'unsatisfiable'
    (a start past the end, or the last 0 bytes), or None for the whole file (no header, another unit, several ranges,
    a malformed one; RFC 9110 lets a server ignore those)."""
    if not value:
        return None
    unit, eq, spec = value.strip().partition('=')
    if not eq or unit.strip().lower() != 'bytes' or ',' in spec:
        return None
    first, dash, last = spec.strip().partition('-')
    digits = lambda text: text.isascii() and text.isdigit()      # (str.isdigit also says yes to other scripts)
    if not dash or not (first or last) or (first and not digits(first)) or (last and not digits(last)):
        return None
    # (a number longer than any file is any number past the end: int() of thousands of digits raises)
    number = lambda text: int(text) if len(text) <= 18 else 10 ** 19
    if not first:                                   # bytes=-N: the last N bytes
        n = number(last)
        return (max(0, size - n), size - 1) if n > 0 and size > 0 else 'unsatisfiable'
    start, end = number(first), (number(last) if last else None)
    if end is not None and end < start:
        return None
    if start >= size:
        return 'unsatisfiable'
    return start, size - 1 if end is None else min(end, size - 1)


def event_number(text):
    """A change number as a client or a pulse file says it: ASCII digits only (at most 16), else None."""
    text = (text or '').strip()
    return int(text) if len(text) <= 16 and text.isascii() and text.isdigit() else None


def read_small(folder, name, cap):
    """Up to `cap` bytes of the plain file `name` (a name, or a path below the folder) of the board's folder, or None:
    never through a link that leaves the folder (a linked file or a linked folder), never a fifo or a device (an open
    that would wait for a writer holds the stream forever)."""
    path = folder / name
    try:
        real, base = path.resolve(), folder.resolve()
        if base not in real.parents:
            return None
        fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks, left = [], cap
        while left > 0:
            got = os.read(fd, left)
            if not got:
                break
            chunks.append(got)
            left -= len(got)
        return b''.join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def pulse_number(folder):
    """The number the board's .pulse holds (threads.py writes its last change there), or None."""
    raw = read_small(folder, '.pulse', 64)
    try:
        return event_number(raw.decode('ascii')) if raw is not None else None
    except ValueError:
        return None


def refuse_constant(name):
    raise ValueError('not JSON: ' + name)


def strict_json(raw):
    """JSON as a browser's JSON.parse reads it: NaN and Infinity (which Python's json takes) are refused."""
    return json.loads(raw, parse_constant=refuse_constant)


def run_of(text, seq):
    """A change file's text when it is one JSON object of its own that leads to `seq` ({"seq": seq, "entries": [...]}),
    on one line, at most SSE_INLINE_MAX bytes; else None."""
    run = text.rstrip(b'\n')
    if len(run) > SSE_INLINE_MAX or b'\n' in run or b'\r' in run or not run.startswith(b'{"seq":%d,' % seq):
        return None
    try:
        parsed = strict_json(run)
    except (ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict) or parsed.get('seq') != seq or not isinstance(parsed.get('entries'), list):
        return None
    return run


def run_from_changes(folder, told, seq):
    """The run from `told` to `seq` built from changes.json (the board's last changes, each naming the number it
    starts from), when they lead there without a gap: a burst that left the page more numbers behind than
    changes/<told>.json covers still comes in one delta. None otherwise."""
    raw = read_small(folder, 'changes.json', SSE_CHANGES_READ + 1)
    if raw is None or len(raw) > SSE_CHANGES_READ:
        return None
    try:
        whole = strict_json(raw)
    except (ValueError, RecursionError):
        return None
    entries = whole.get('entries') if isinstance(whole, dict) else None
    if not isinstance(entries, list):
        return None
    number = lambda v: isinstance(v, int) and not isinstance(v, bool)
    at, run = told, []
    for e in entries:
        if not isinstance(e, dict) or not number(e.get('seq')) or not number(e.get('from')):
            return None
        if e['seq'] <= told:
            continue
        if e['from'] != at or e['seq'] > seq:
            return None
        run.append(e)
        at = e['seq']
        if at == seq:
            break
    if at != seq or not run:
        return None
    try:
        text = ('{"seq":%d,"entries":[%s]}' % (seq, ','.join(json.dumps(e, ensure_ascii=False, separators=(',', ':'), allow_nan=False) for e in run))).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeEncodeError):
        return None
    return run_of(text, seq)


EXACT_MAX = 64 * 1024              # up to this a run from the store is the changes as they were; beyond, one condensed entry
CHANGES_MAX_BYTES = 2 * 1024 * 1024 # a "since n" answer larger than this: the page reads the summary


def run_since(folder, n, limit):
    """{"seq":N,"entries":[...]} as bytes: every change from number n to the board's, from the board's store
    (suda.db), at ANY distance it keeps (sqlite177); the smaller of the changes as they were and one condensed entry.
    None when there is no store, n is not on its chain, or the answer is longer than `limit` bytes."""
    mod, path = store_module(), Path(folder) / 'suda.db'
    if mod is None or not path.is_file():
        return None
    try:
        st = mod.Store(path, readonly=True)
    except Exception:  # noqa: BLE001 - a store that cannot be opened: the files answer
        return None
    try:
        exact = None
        entries = st.entries_since(n, limit_bytes=limit)
        if entries:
            last = json.loads(entries[-1])['seq']
            exact = ('{"seq":%d,"entries":[%s]}' % (last, ','.join(entries))).encode('utf-8')
        if exact is not None and len(exact) <= EXACT_MAX:
            return exact
        one = st.condensed_since(n)          # far behind: one entry, each changed thread as it stands now
    except Exception:  # noqa: BLE001 - a store that breaks on the way: the files answer
        return None
    finally:
        st.close()
    condensed = None if one is None else json.dumps({'seq': one['seq'], 'entries': [one]}, ensure_ascii=False,
                                                    separators=(',', ':'), allow_nan=False).encode('utf-8')
    best = min((x for x in (exact, condensed) if x is not None), key=len, default=None)    # whichever is smaller
    return best if best is not None and len(best) <= limit else None


def inline_delta(folder, told, seq):
    """The `event: delta` a page that holds number `told` can apply to reach `seq` without reading anything:
    changes/<told>.json (threads.py writes it before the pulse), else the run built from changes.json, with the head
    of summary.json at that number; or b'' when there is none that leads exactly to `seq` and fits one line of at most
    SSE_INLINE_MAX bytes."""
    if told is None or seq is None or told >= seq:
        return b''
    head = read_small(folder, 'summary.json', 64)
    if head is None or not head.startswith(b'{"seq":%d,' % seq):        # the summary at that very number
        return b''
    raw = read_small(folder, Path('changes') / ('%d.json' % told), SSE_INLINE_MAX + 1)
    run = run_of(raw, seq) if raw is not None else None
    if run is None:
        run = run_from_changes(folder, told, seq)
    if run is None:                             # a page further behind: the run from the store (sqlite177)
        run = run_since(folder, told, SSE_INLINE_MAX)
        run = run if run is not None and run.startswith(b'{"seq":%d,' % seq) else None
    if run is None:
        return b''
    # (json.dumps escapes every control character and quote: the head stays on one data line)
    return b'event: delta\ndata: {"head":' + json.dumps(head.decode('utf-8', 'ignore')).encode() + b',"run":' + run + b'}\n\n'


def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def mdv_dir():
    """Where `threads install` puts the MD Viewer (threads.py's mdv_dir(), the same rule): THREADS_MDV_DIR, else
    beside the boards folder when BOARDS_DIR is set, else ~/.local/share/threads/mdv."""
    if os.environ.get('THREADS_MDV_DIR'):
        return Path(os.environ['THREADS_MDV_DIR'])
    if os.environ.get('BOARDS_DIR'):
        return Path(os.environ['BOARDS_DIR']).parent / 'threads-mdv'
    return Path.home() / '.local' / 'share' / 'threads' / 'mdv'


def viewer():
    """(mdv_web, its config), or None when the viewer cannot be had now. Never raises. A failed import is tried again
    after MDV_RETRY seconds, with nothing of it left in sys.modules (the next try reads the next install whole)."""
    with MDV_LOCK:
        if MDV['mod'] is not None:
            return MDV['mod'], MDV['cfg']
        if MDV['failed'] and time.monotonic() - MDV['failed'] < MDV_RETRY:
            return None
        where = str(mdv_dir())
        try:
            if not os.path.isfile(os.path.join(where, 'mdv_web.py')):
                raise ImportError('no viewer installed at ' + where)
            import importlib.util
            # mdv_web from that very file (never another mdv_web found on sys.path); the folder goes first on
            # sys.path for its package (mdv)
            spec = importlib.util.spec_from_file_location('mdv_web', os.path.join(where, 'mdv_web.py'))
            mod = importlib.util.module_from_spec(spec)
            if where not in sys.path:
                sys.path.insert(0, where)
            spec.loader.exec_module(mod)
            cfg = mod.config(allow_hosts=set(LOCAL) | allowed_hosts())
        except Exception as e:  # noqa: BLE001 - a viewer that cannot load is a 503, never a dead board
            for name in [n for n in sys.modules if n == 'mdv' or n.startswith('mdv.')]:
                sys.modules.pop(name, None)
            while where in sys.path:
                sys.path.remove(where)
            MDV['failed'] = time.monotonic()
            print(f'[suda] /mdv/ unavailable: {type(e).__name__}: {str(e)[:200]}', file=sys.stderr, flush=True)
            return None
        MDV.update(mod=mod, cfg=cfg, failed=0.0)
        return mod, cfg


class Counted:
    """A connection's writer that counts the bytes it sent."""

    def __init__(self, raw):
        self.raw, self.sent = raw, 0

    def write(self, data):
        n = self.raw.write(data)
        self.sent += len(data)
        return n

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class Handler(BaseHTTPRequestHandler):
    server_version = 'Suda'
    sys_version = ''
    timeout = 30                    # a connection that sends nothing (or half a body) does not hold a thread forever

    def log_message(self, *args):          # quiet: requests carry his words
        pass

    def host_ok(self):
        """Against DNS rebinding: a page on another name that resolves here may not talk to the board."""
        host = (self.headers.get('Host') or '').strip().lower()
        return host_name(host) in LOCAL or host in allowed_hosts() or host_name(host) in allowed_hosts()

    def deny(self, code):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if not self.host_ok():
            return self.deny(403)
        url = urlparse(self.path)
        if url.path.startswith('/mdv/'):            # (after the Host guard: a refused request never reaches the viewer)
            return self.viewer_request()
        if url.path == '/events':
            return self.deny(405) if head else self.events(parse_qs(url.query).get('board', [''])[0])
        target = self.of_board(url.path)
        since = re.fullmatch(r'/%s/changes/(\d{1,16})\.json' % re.escape(SLUG), url.path) if target is not None else None
        run = run_since(bl.BOARDS_DIR / SLUG, int(since.group(1)), CHANGES_MAX_BYTES) if since else None
        if run is not None:                     # every change since any number the store keeps (the file is the fallback)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(run) + 1))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if not head:
                self.wfile.write(run + b'\n')
            return
        try:
            f = os.fdopen(os.open(target, os.O_RDONLY | os.O_NONBLOCK), 'rb') if target is not None and target.is_file() else None
        except (OSError, ValueError):
            f = None
        if f is None:
            return self.deny(404)
        with f:
            try:
                fs = os.fstat(f.fileno())
            except OSError:
                return self.deny(404)
            if not stat.S_ISREG(fs.st_mode):
                return self.deny(404)
            size, modified = fs.st_size, self.date_time_string(int(fs.st_mtime))
            if self.not_modified(fs.st_mtime):          # the page's "changed since?": a 304, no body
                self.send_response(304)
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Last-Modified', modified)
                self.end_headers()
                return
            # A range only of the file as it was when the page asked: an If-Range that names another time is the whole file.
            if_range = self.headers.get('If-Range')
            wanted = byte_range(self.headers.get('Range'), size) if if_range is None or if_range.strip() == modified else None
            kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if kind.startswith('text/') or kind in ('application/json', 'application/javascript'):
                kind += '; charset=utf-8'
            if wanted == 'unsatisfiable':
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                first, length = 0, 0
            elif wanted is not None:
                first, last = wanted
                length = last - first + 1
                self.send_response(206)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Range', f'bytes {first}-{last}/{size}')
                self.send_header('Content-Length', str(length))
            else:
                first, length = 0, size
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(size))
            self.send_header('Accept-Ranges', 'bytes')            # a video seeks (and iPhone Safari plays an mp4 at all)
            self.send_header('Cache-Control', 'no-store')         # the page and the worker read past every cache themselves
            self.send_header('Last-Modified', modified)           # the page's new-build check
            self.send_header('X-Content-Type-Options', 'nosniff')
            if kind.startswith('text/html'):        # no other site may frame the board and steer his taps
                self.send_header('Content-Security-Policy', "frame-ancestors 'self'")
                self.send_header('X-Frame-Options', 'SAMEORIGIN')
            self.end_headers()
            if head or not length:
                return
            # In pieces, from the file as it was opened (a replaced file goes on being the one that was opened); one
            # that was cut meanwhile ends the connection, so no client waits for bytes that never come.
            try:
                f.seek(first)
                while length > 0:
                    chunk = f.read(min(CHUNK, length))
                    if not chunk:
                        self.close_connection = True
                        return
                    self.wfile.write(chunk)
                    length -= len(chunk)
            except OSError:
                self.close_connection = True

    def do_POST(self):
        if not self.host_ok():
            return self.deny(403)
        # Against CSRF: a write comes from a page of this same address (a browser always says where it comes from).
        origin = urlparse(self.headers.get('Origin') or '')
        if origin.scheme not in ('http', 'https') or origin.netloc.lower() != (self.headers.get('Host') or '').strip().lower():
            return self.deny(403)
        if urlparse(self.path).path.startswith('/mdv/'):     # (after both guards: a refused write never reaches the viewer)
            return self.viewer_request()
        if urlparse(self.path).path != '/api/state':
            return self.deny(404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self.deny(400)
        if length <= 0 or length > BODY_MAX:
            return self.deny(413 if length > BODY_MAX else 400)
        try:
            raw = json.loads(self.rfile.read(length))
            board, state = raw.get('board'), raw.get('state')
            state = scrub(state)
        except (ValueError, AttributeError, RecursionError, OSError):
            return self.deny(400)
        if board != SLUG or not isinstance(state, dict):        # this server's one board, nothing else in BOARDS_DIR
            return self.deny(400)
        folder = bl.BOARDS_DIR / SLUG
        if not folder.is_dir():
            return self.deny(404)
        hook = folder / 'on-state.sh'
        with STATE_LOCK:
            (folder / 'state').mkdir(exist_ok=True)
            bl.atomic_write_text(folder / 'state' / 'state.json', json.dumps(state, ensure_ascii=False))
            if not (hook.is_file() and os.access(hook, os.X_OK)):
                return self.answer({'ok': True, 'applied': False})
            try:
                r = subprocess.run([str(hook)], cwd=str(folder), capture_output=True, text=True, timeout=HOOK_TIMEOUT)
                out = (r.stdout + r.stderr).strip().splitlines()[-6:]
                return self.answer({'ok': r.returncode == 0, 'applied': r.returncode == 0, 'code': r.returncode, 'out': out})
            except subprocess.TimeoutExpired:
                return self.answer({'ok': False, 'applied': False, 'code': -1, 'out': ['on-state.sh timed out']}, 500)

    def not_modified(self, when):
        """True when If-Modified-Since names a time at or after the file's (in whole seconds, as Last-Modified says
        it); never when If-None-Match is there (it decides, and this server has no tags)."""
        value = self.headers.get('If-Modified-Since')
        if not value or self.headers.get('If-None-Match') is not None:
            return False
        try:
            since = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return False
        if since is None:
            return False
        if since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)
        try:
            return int(when) <= since.timestamp()
        except (OverflowError, ValueError, OSError):
            return False

    def viewer_request(self):
        """Hand a /mdv/ request to the viewer; 503 when it cannot have it. Always closes the connection."""
        got = viewer()
        try:
            if got is None:
                return self.viewer_unavailable()
            mod, cfg = got
            raw = self.wfile
            self.wfile = Counted(raw)       # (what the viewer wrote: an answer that began gets no second one)
            try:
                mod.handle(self, cfg)
            except Exception as e:  # noqa: BLE001 - the viewer's handle() never raises; if it does, a 503
                print(f'[suda] /mdv/ error: {type(e).__name__}: {str(e)[:200]}', file=sys.stderr, flush=True)
                if not self.wfile.sent:
                    self._headers_buffer = []       # (a status line it began and never sent is not sent before ours)
                    try:
                        self.viewer_unavailable()
                    except Exception:  # noqa: BLE001 - the connection just closes
                        pass
            finally:
                self.wfile = raw
        finally:
            self.close_connection = True

    def viewer_unavailable(self):
        body = b'{"ok": false, "error": "unavailable"}'
        # A small body is read away, so the client gets this answer rather than a reset; within one overall deadline
        # (a body dripped a byte at a time is not waited for).
        try:
            left = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            left = 0
        if 0 < left <= 1 << 20:
            end = time.monotonic() + min(self.timeout or 30, 5)
            try:
                while left > 0 and time.monotonic() < end:
                    self.connection.settimeout(max(0.05, end - time.monotonic()))
                    got = self.rfile.read1(min(left, 65536))
                    if not got:
                        break
                    left -= len(got)
            except OSError:
                pass
            finally:
                try:
                    self.connection.settimeout(self.timeout)
                except OSError:
                    pass
        self.close_connection = True
        self.send_response(503)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def answer(self, value, code=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def of_board(self, url_path):
        """The file of this server's board that a GET names, or None: only under /<SLUG>/, never the hook or the code,
        never the request folder, and nothing an odd path makes the file system choke on."""
        # (on the path as the file system reads it: decoded, and in any letter case, since a Mac's disk ignores it)
        decoded = unquote(url_path)
        parts = decoded.split('/')
        if len(parts) < 3 or parts[1] != SLUG or (len(parts) > 3 and parts[2].lower() == 'state') or decoded.lower().endswith(NEVER) or STORE.search(decoded.lower()):
            return None
        try:
            return inside(bl.BOARDS_DIR, url_path)
        except (OSError, ValueError):
            return None

    def events(self, board):
        if board != SLUG or not (bl.BOARDS_DIR / SLUG).is_dir():
            return self.deny(404)
        if not STREAMS.acquire(blocking=False):
            return self.deny(503)
        try:
            self.stream(bl.BOARDS_DIR / SLUG)
        finally:
            STREAMS.release()

    def stream(self, folder):
        self.timeout = None                 # (a stream only writes; it ends when a write fails)
        self.connection.settimeout(None)
        # .pulse: the state changed. suda.html: `threads install` wrote a new page, so the open ones look for the
        # new build. (The old board page, board.html, was watched here; it is gone, suda m620.)
        watched = (folder / 'suda.html', folder / '.pulse')
        # Where the client was: the header a browser sends when it reconnects by itself, else ?since= from a page
        # that opened anew.
        since = event_number(self.headers.get('Last-Event-ID'))
        if since is None:
            since = event_number(parse_qs(urlparse(self.path).query).get('since', [''])[0])
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        last, wrote = None, time.monotonic()
        seq = None              # the board's number, when its pulse holds one
        alive = None            # when the heartbeat went last
        told = since            # the number this line last told the page (a delta leads from it)
        try:
            while True:
                now = tuple(mtime(p) for p in watched)
                if now != last:
                    first = last is None
                    last = now
                    seq = pulse_number(folder)
                    if seq is None:             # a pulse only touched (an older threads.py): what the stream always said
                        out = b'data: changed\n\n'
                        alive = None            # (a number that comes back is said at once)
                    else:
                        out = b'retry: %d\n\n' % SSE_RETRY_MS if first else b''
                        if not (first and since == seq):        # it has this number already
                            # the change itself first (a page from before it does not listen to it)
                            out += inline_delta(folder, told, seq)
                            out += b'id: %d\ndata: changed\n\n' % seq
                        told = seq
                    self.wfile.write(out)
                    self.wfile.flush()
                    wrote = time.monotonic()
                if seq is not None and (alive is None or time.monotonic() - alive >= SSE_ALIVE_S):
                    # The number as it stands, at once and every few seconds: the page knows it is up to date (and
                    # the write finds a client that is gone). Named, so a page that reads on any message does not hear it.
                    self.wfile.write(b'event: alive\ndata: %d\n\n' % seq)
                    self.wfile.flush()
                    wrote = alive = time.monotonic()
                elif seq is None and time.monotonic() - wrote >= SSE_PING_S:     # a write is the only way to notice the page is gone
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    wrote = time.monotonic()
                time.sleep(SSE_POLL_S)
        except OSError:
            return


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        """As HTTPServer's, without socket.getfqdn(host): a reverse DNS lookup for a name nothing uses, which made the
        server take more than 10 s to start where the resolver is slow (GitHub's macOS runners)."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def more_files():
    """Many pages and streams at once must not run out of file descriptors (launchd starts at 256)."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except (ImportError, ValueError, OSError):
        pass


def main():
    more_files()
    ap = argparse.ArgumentParser(description='Suda board server (127.0.0.1 only)')
    ap.add_argument('--port', type=int, default=int(os.environ.get('SUDA_PORT', '8767')))
    a = ap.parse_args()
    server = Server(('127.0.0.1', a.port), Handler)
    print(f'Suda: http://127.0.0.1:{server.server_address[1]}/ (boards: {bl.BOARDS_DIR})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
