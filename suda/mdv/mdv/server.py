"""MD Viewer: one Markdown file, read in Suda's style. A small HTTP service on 127.0.0.1 only.

    python3 -m mdv.server [--port 18775] [--allow-host 192.0.2.10,...]

Everything lives under /mdv/ so the gateway can put it beside other services on one port:
  GET  /mdv/?path=<absolute or ~/ path>   the page
  GET  /mdv/api/doc?path=                 the document, its blocks, its saved translation and summary
  GET  /mdv/api/events?path=              server-sent events: "change" when the file or its translation changes
  POST /mdv/api/translate {path, force}   start (or join) a translation; the reply streams it as JSON lines
  GET  /mdv/api/translate?path=           follow a translation already running (never starts one)
  POST /mdv/api/summary {path, force}     the summary (in the installation's language), made once and saved beside the file
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import core, l10n, model

PREFIX = '/mdv'
HERE = Path(__file__).resolve().parent.parent
STATIC = HERE / 'static'
STATIC_FILES = {
    'app.js': 'text/javascript; charset=utf-8',
    'app.css': 'text/css; charset=utf-8',
    'suda.css': 'text/css; charset=utf-8',
    'suda-pure.js': 'text/javascript; charset=utf-8',
    'mdv-pure.js': 'text/javascript; charset=utf-8',
    'l10n.js': 'text/javascript; charset=utf-8',       # (made on each request: the installation's language, mdv/l10n.py)
    'vendor/mermaid.min.js': 'text/javascript; charset=utf-8',
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
MAX_BODY = 64 * 1024
MAX_STREAMS = 48                 # open event streams and translation followers together
MAX_JOBS = 3                     # translations calling the model at once, all files together
MAX_SUMMARIES = 2                # summaries being made at once
SOCKET_TIMEOUT = 30              # a client that sends nothing is let go
MAX_EXISTS = 200                 # links one note may ask about at once
PICTURE_READS = 4                # whole pictures (up to 25 MB each) read into memory at once
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '[::1]'}


class Config:
    def __init__(self, roots_json: Path, extra_roots: list[Path], home: Path, allow_hosts: set[str]):
        self.roots_json = roots_json
        self.extra_roots = extra_roots
        self.home = home
        self.allow_hosts = allow_hosts | LOCAL_HOSTS
        self._roots: list[Path] = []
        self._roots_key = None
        self.lock = threading.Lock()
        self.streams = threading.BoundedSemaphore(MAX_STREAMS)

    def roots(self) -> list[Path]:
        """MDS's roots, read again whenever roots.json changes."""
        try:
            st = self.roots_json.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        with self.lock:
            if key != self._roots_key or not self._roots:
                self._roots = core.load_roots(self.roots_json, self.extra_roots)
                self._roots_key = key
            return list(self._roots)


# ---------- translation jobs: they outlive the request that started them ----------

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.done = False
        self.finished = 0.0

    def push(self, ev: dict):
        with self.lock:
            self.events.append(ev)

    def read(self, at: int):
        with self.lock:
            return self.events[at:], len(self.events), self.done

    def finish(self, ev: dict):
        with self.lock:
            self.events.append(ev)
            self.done = True
            self.finished = time.time()


PICTURE_SLOTS = threading.BoundedSemaphore(PICTURE_READS)
JOBS: dict[tuple, Job] = {}
JOBS_LOCK = threading.Lock()
SUMMARIES = threading.BoundedSemaphore(MAX_SUMMARIES)


def job_key(real: Path) -> tuple:
    """One note, one key: its folder (by inode) and its name. A save that writes a new file and renames it (editors,
    git, MDS) keeps the key; on a disk that ignores case, OK.MD and ok.md are one key."""
    folder = os.stat(real.parent)
    name = real.name
    alt = real.with_name(name.swapcase())
    try:
        same_any_case = alt.name != name and os.path.samefile(alt, real)
    except OSError:
        same_any_case = False
    return (folder.st_dev, folder.st_ino, name.casefold() if same_any_case else name)


def job_of(real: Path) -> Job | None:
    try:
        return JOBS.get(job_key(real))
    except OSError:
        return None


def start_job(real: Path, root: Path, force: bool) -> Job | None:
    """The running translation of this file, or a new one; None when MAX_JOBS are already running. Two pages
    asking at once share one run and one bill. A new run sends the model only the blocks that changed since the
    saved state; `force` sends them all."""
    key = job_key(real)
    with JOBS_LOCK:
        for k in [k for k, j in JOBS.items() if j.done and time.time() - j.finished > 120]:
            JOBS.pop(k, None)
        job = JOBS.get(key)
        if job is not None and not job.done:
            return job
        if sum(1 for j in JOBS.values() if not j.done) >= MAX_JOBS:
            return None
        folder = core.Folder(real, root)          # held from here: the writes cannot be sent elsewhere
        job = Job()
        JOBS[key] = job
        try:
            threading.Thread(target=run_translation, args=(job, real, root, force, folder), name='translate',
                             daemon=True).start()
        except BaseException:                     # no thread: the slot and the folder are given back
            folder.close()
            JOBS.pop(key, None)
            job.finish({'error': 'busy'})
            raise
    return job


def run_translation(job: Job, real: Path, root: Path, force: bool = False, folder=None):
    folder = folder or core.Folder(real, root)
    try:
        text = core.read_capped(real, core.MAX_DOC_BYTES, folder.fd)
        if text is None:
            job.finish({'error': 'missing'})
            return
        src_mtime = os.stat(real.name, dir_fd=folder.fd).st_mtime
        if len(text) > core.MAX_TRANSLATE_CHARS:
            job.finish({'error': 'too-big'})
            return
        src_lang = core.detect_lang(text)
        tgt = core.other_lang(src_lang)
        sib = core.sibling_path(real, tgt)
        there = core.read_capped(sib, core.MAX_DOC_BYTES * 4, folder.fd)
        if not core.is_ours(there) or (there is None and core._exists(sib.name, folder)):
            job.finish({'error': 'not-ours', 'message': sib.name})
            return
        blocks = core.blocks_of(text)
        state = None if force else core.with_hand_edits(core.load_state(core.state_path(real, tgt), folder.fd), there)
        job.push({'start': True, 'blocks': len(blocks), 'lang': tgt})
        out = core.translate_blocks(blocks, src_lang, tgt, state, model.MODEL, model.stream,
                                    lambda i, t, how: job.push({'i': i, 't': t, 'how': how}))
        core.save_translation(real, root, text, src_mtime, src_lang, tgt, out, model.MODEL, folder)
        job.finish({'done': True, 'sent': out['sent'], 'reused': out['reused'], 'failed': out['failed']})
        print('[translate] %s: %d block(s), %d sent, %d reused, %d failed'
              % (real.name, len(blocks), out['sent'], out['reused'], len(out['failed'])), flush=True)
    except Exception as e:  # noqa: BLE001 - a job always ends
        job.finish({'error': 'failed', 'message': model.clean_error(e)})
        print('[translate] %s failed: %s' % (real.name, model.clean_error(e)), flush=True)
    finally:
        folder.close()


SUMMARY_LOCKS: dict[tuple, threading.Lock] = {}


# ---------- the document as the page wants it ----------

def doc_payload(real: Path, root: Path, home: Path, asked: Path | None = None) -> dict:
    """`asked`: the path as he gave it (it may run through a symlinked folder, as ~/Documents/mds does); shown as
    such, so the head says what the link said. Everything is read from `real`."""
    seen = asked if asked is not None and asked.name == real.name else real
    text = core.read_capped(real, core.MAX_DOC_BYTES)
    if text is None:
        raise OSError('not readable')
    st = real.stat()
    lang = core.detect_lang(text)
    tgt = core.other_lang(lang)
    blocks = core.blocks_of(text)
    sib = core.sibling_path(real, tgt)
    sib_text = core.read_capped(sib, core.MAX_DOC_BYTES * 4)
    view = core.translation_view(blocks, st.st_mtime, sib_text, core.load_state(core.state_path(real, tgt)))
    if sib_text is not None:
        view['file'] = sib.name
        view['mtime'] = sib.stat().st_mtime
    summ = core.load_summary(core.summary_path(real))
    summary = None
    if summ:
        summary = {'text': summ['summary'], 'stale': summ['sha'] != core.content_sha(text), 'ts': summ.get('ts')}
    job = job_of(real)
    return {
        'ok': True, 'path': core.shown(seen, home), 'name': real.name, 'dir': core.shown(seen.parent, home),
        'size': st.st_size, 'mtime': st.st_mtime, 'lang': lang, 'tr_lang': tgt, 'blocks': blocks,
        'translation': view, 'summary': summary, 'can_translate': model.has_key(),
        'translating': bool(job and not job.done), 'version': core.content_sha(text)[:12],
    }


def watch_key(real: Path) -> tuple:
    """What changes when the document, its translation or its summary changes. Only looked at (lstat), never read
    and never followed: a note swapped for a link to a FIFO or a huge file costs nothing here."""
    out = []
    for p in (real, core.summary_path(real), core.sibling_path(real, 'en'), core.state_path(real, 'en'),
              core.sibling_path(real, 'he'), core.state_path(real, 'he')):
        try:
            st = os.lstat(p)
            out.append((st.st_mtime_ns, st.st_size, st.st_ino))
        except OSError:
            out.append(None)
    return tuple(out)


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = 'mdv'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    cfg: Config = None  # set by make_server
    timeout = SOCKET_TIMEOUT

    def log_message(self, fmt, *args):  # quiet: no paths or queries in the log
        pass

    # -- one deadline for the whole request: a client that drips its headers or its body a byte at a time is cut
    #    off at `timeout` seconds in all, not at `timeout` seconds per read. It ends once the request is in (the
    #    body read) or its answer starts to stream. --
    def setup(self):
        super().setup()
        self.deadline = threading.Timer(max(1, self.timeout or SOCKET_TIMEOUT), self.cut)
        self.deadline.daemon = True
        self.deadline.start()

    def cut(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def request_in(self):
        if getattr(self, 'deadline', None) is not None:
            self.deadline.cancel()

    def finish(self):
        self.request_in()
        super().finish()

    # -- guard: a second layer behind the gateway (DNS rebinding, cross-site writes) --
    def host_ok(self) -> bool:
        host = (self.headers.get('Host') or '').strip().lower()
        name = host.rsplit(':', 1)[0] if not host.startswith('[') else host.split(']')[0] + ']'
        return bool(host) and (name in self.cfg.allow_hosts or host in self.cfg.allow_hosts)

    def write_ok(self) -> bool:
        if (self.headers.get('Sec-Fetch-Site') or '').lower() in ('cross-site', 'same-site'):
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + (self.headers.get('Host') or ''):
            return False
        return (self.headers.get('Content-Type') or '').split(';')[0].strip().lower() == 'application/json'

    def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        # Every answer ends its connection: a body left unread (a refused POST) is never read as a next request.
        # Up to 1 MB of it is read and dropped first, so the client gets this answer rather than a reset.
        self.close_connection = True
        if not getattr(self, 'body_read', False):
            self.body_read = True
            try:
                left = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                left = 0
            if 0 < left <= 1 << 20:
                try:
                    while left > 0:
                        got = self.rfile.read(min(left, 65536))
                        if not got:
                            break
                        left -= len(got)
                except OSError:
                    pass
        self.request_in()                 # the request is in: the answer is written without the deadline
        self.send_response(code)
        self.send_header('Connection', 'close')
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            # in pieces: the socket timeout bounds one whole sendall, so one 5 MB write to a slow phone would fail
            for at in range(0, len(body), 65536):
                self.wfile.write(body[at:at + 65536])

    def json(self, code: int, obj: dict):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def fail(self, code: int, err: str, message: str = ''):
        self.json(code, {'ok': False, 'error': err, 'message': message})

    def target(self, raw: str):
        try:
            real, root = core.resolve(raw, self.cfg.roots(), self.cfg.home)
        except core.Refused as e:
            code = 404 if e.code in ('missing', 'no-path') else 403 if e.code in ('outside', 'hidden') else 400
            self.fail(code, e.code, str(e))
            return None
        return real, root

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.host_ok():
            return self.fail(403, 'host')
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        p = url.path
        if p in ('/', PREFIX):
            return self.send(302, b'', 'text/plain', {'Location': PREFIX + '/' + ('?' + url.query if url.query else '')})
        if p == PREFIX + '/':
            return self.page()
        if p.startswith(PREFIX + '/static/'):
            name = p[len(PREFIX + '/static/'):]
            if name not in STATIC_FILES:
                return self.fail(404, 'missing')
            body = l10n.script() if name == 'l10n.js' else (STATIC / name).read_bytes()
            extra = {'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}
            if 'gzip' in (self.headers.get('Accept-Encoding') or '') and len(body) > 1024:
                body = gzipped(name, body)
                extra['Content-Encoding'] = 'gzip'
            return self.send(200, body, STATIC_FILES[name], extra)
        if p == PREFIX + '/api/exists':
            return self.exists(parse_qs(url.query).get('p', []))
        if p == PREFIX + '/api/doc':
            got = self.target(q.get('path', ''))
            if not got:
                return
            real, root = got
            orig = core.original_of(real)
            if orig is not None:
                try:
                    core.resolve(str(orig), self.cfg.roots(), self.cfg.home)
                    return self.json(200, {'ok': True, 'original': core.shown(orig, self.cfg.home)})
                except core.Refused:
                    pass
            try:
                asked = Path(os.path.normpath(core.expand(q.get('path', ''), self.cfg.home)))
                return self.json(200, doc_payload(real, root, self.cfg.home, asked))
            except OSError:
                return self.fail(404, 'missing')
        if p == PREFIX + '/api/asset':
            return self.asset(q.get('path', ''))
        if p == PREFIX + '/api/events':
            got = self.target(q.get('path', ''))
            if got:
                self.events(got[0])
            return
        if p == PREFIX + '/api/translate':
            got = self.target(q.get('path', ''))
            if not got:
                return
            job = job_of(got[0])
            if not job:
                return self.fail(404, 'no-job')
            return self.follow(job)
        return self.fail(404, 'missing')

    def do_POST(self):
        if not self.host_ok():
            return self.fail(403, 'host')
        if not self.write_ok():
            return self.fail(403, 'cross-site')
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            return self.fail(413, 'too-big')
        try:
            raw = self.rfile.read(n)
            self.body_read = True
            self.request_in()
            body = json.loads(raw or b'{}')
            assert isinstance(body, dict)
        except Exception:
            return self.fail(400, 'bad-json')
        p = urlsplit(self.path).path
        if p not in (PREFIX + '/api/translate', PREFIX + '/api/summary'):
            return self.fail(404, 'missing')
        got = self.target(body.get('path', ''))
        if not got:
            return
        real, root = got
        if core.original_of(real) is not None:
            return self.fail(400, 'is-translation', 'this file is itself a translation')
        if not model.has_key():
            return self.fail(503, 'no-key', 'no API key')
        try:
            if p == PREFIX + '/api/translate':
                try:
                    job = start_job(real, root, bool(body.get('force')))
                except RuntimeError:
                    return self.fail(503, 'busy', 'the server cannot start more work now')
                if job is None:
                    return self.fail(429, 'busy', 'other translations are running; try again in a moment')
                return self.follow(job)
            if not SUMMARIES.acquire(blocking=False):
                return self.fail(429, 'busy', 'other summaries are being made; try again in a moment')
            try:
                with core.Folder(real, root) as folder:
                    return self.summary(real, folder, bool(body.get('force')))
            finally:
                SUMMARIES.release()
        except OSError:
            return self.fail(409, 'moved', 'the file moved while it was opened')

    def exists(self, raws: list):
        """Which of the notes a note links to open here (task 73: a broken link is marked before the tap). The same
        rules as opening one (core.resolve): a path outside the roots, through a symlink out, hidden, not a .md or
        missing is the same `false`, so this says no more than opening each would. This page's own only."""
        if (self.headers.get('Sec-Fetch-Site') or '').lower() in ('cross-site', 'same-site'):
            return self.fail(403, 'cross-site')
        if len(raws) > MAX_EXISTS or any(len(r) > 4096 for r in raws):
            return self.fail(400, 'too-many')
        here = []
        for raw in raws:
            try:
                core.resolve(raw, self.cfg.roots(), self.cfg.home)
                here.append(True)
            except core.Refused:
                here.append(False)
        return self.json(200, {'ok': True, 'here': here})

    def asset(self, raw: str):
        """A picture a note shows, from the same folders as the notes. Served as a picture only: never sniffed, and
        an SVG opened on its own runs nothing (a sandbox with no script)."""
        # Only this page's own: a picture asked for by another site (its <img>) is refused, and the answer says it
        # is not for other origins either. A picture opened on its own (none) or by the viewer (same-origin) is fine.
        if (self.headers.get('Sec-Fetch-Site') or '').lower() in ('cross-site', 'same-site'):
            return self.fail(403, 'cross-site')
        try:
            real, _root = core.resolve_asset(raw, self.cfg.roots(), self.cfg.home)
        except core.Refused as e:
            code = 404 if e.code in ('missing', 'no-path') else 403 if e.code in ('outside', 'hidden') else 400
            return self.fail(code, e.code, str(e))
        # at most PICTURE_READS whole pictures in memory at once; the others wait their turn (a note's own pictures
        # all arrive), and after a while are told the server is busy
        if not PICTURE_SLOTS.acquire(timeout=20):
            return self.fail(503, 'busy')
        try:
            data = core.read_bytes_capped(real, core.MAX_PICTURE_BYTES)
            if data is None:
                return self.fail(404, 'missing')
            return self.send(200, data, core.picture_type(real.name), {
                'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                'Cross-Origin-Resource-Policy': 'same-origin'})
        finally:
            PICTURE_SLOTS.release()

    def page(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        html = html.replace('<!--@@ICONS@@-->', (STATIC / 'icons.svg.html').read_text(encoding='utf-8'))
        html = html.replace('<html lang="en" dir="ltr">', l10n.html_tag(), 1)      # the installation's language
        self.send(200, html.encode('utf-8'), 'text/html; charset=utf-8', {'Content-Security-Policy': CSP})

    def summary(self, real: Path, folder, force: bool):
        text = core.read_capped(real, core.MAX_DOC_BYTES, folder.fd)
        if text is None:
            return self.fail(404, 'missing')
        if len(text) > core.MAX_TRANSLATE_CHARS:
            return self.fail(413, 'too-big')
        with JOBS_LOCK:
            lock = SUMMARY_LOCKS.setdefault(job_key(real), threading.Lock())
        with lock:
            saved = core.load_summary(core.summary_path(real), folder.fd)
            if saved and not force and saved['sha'] == core.content_sha(text):
                return self.json(200, {'ok': True, 'text': saved['summary'], 'stale': False, 'ts': saved.get('ts'), 'cached': True})
            try:
                out = ''.join(model.stream(l10n.tr(core.SUMMARY_SYSTEM), [{'role': 'user', 'content': text}], model.SUMMARY_MAX_TOKENS)).strip()
                if not out:
                    raise RuntimeError('empty reply')
                obj = core.save_summary(folder, real, text, out, model.MODEL)
            except Exception as e:  # noqa: BLE001
                return self.fail(502, 'failed', model.clean_error(e))
        return self.json(200, {'ok': True, 'text': obj['summary'], 'stale': False, 'ts': obj['ts'], 'cached': False})

    def stream_head(self, ctype: str):
        self.request_in()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def follow(self, job: Job):
        """The translation as JSON lines: everything so far, then each new block. Leaving stops only the reading."""
        if not self.cfg.streams.acquire(blocking=False):
            return self.fail(503, 'busy')
        try:
            self.stream_head('application/x-ndjson; charset=utf-8')
            at = 0
            while True:
                evs, at, done = job.read(at)
                for ev in evs:
                    self.wfile.write((json.dumps(ev, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
                if done and not evs:
                    return
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.cfg.streams.release()

    def events(self, real: Path):
        if not self.cfg.streams.acquire(blocking=False):
            return self.fail(503, 'busy')
        try:
            self.stream_head('text/event-stream; charset=utf-8')
            self.wfile.write(b'retry: 2000\n\n')
            self.wfile.flush()
            last = watch_key(real)
            beat = time.monotonic()
            while True:
                time.sleep(0.4)
                key = watch_key(real)
                if key != last:
                    last = key
                    self.wfile.write(b'event: change\ndata: {}\n\n')
                    self.wfile.flush()
                    beat = time.monotonic()
                elif time.monotonic() - beat > 15:
                    self.wfile.write(b': beat\n\n')
                    self.wfile.flush()
                    beat = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.cfg.streams.release()


GZ: dict[str, tuple[bytes, bytes]] = {}


def gzipped(name: str, body: bytes) -> bytes:
    """A static file compressed once (mermaid is 5.5 MB, a third of that compressed: the phone waits less)."""
    got = GZ.get(name)
    if got is None or got[0] != body:
        got = (body, gzip.compress(body, 6, mtime=0))
        GZ[name] = got
    return got[1]


def make_server(port: int, cfg: Config) -> ThreadingHTTPServer:
    handler = type('H', (Handler,), {'cfg': cfg})
    srv = ThreadingHTTPServer(('127.0.0.1', port), handler)
    srv.daemon_threads = True
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=int(os.environ.get('MDV_PORT', '18775')))
    ap.add_argument('--allow-host', default=os.environ.get('MDV_ALLOW_HOSTS', ''),
                    help='comma-separated host names the gateway serves this under (the Tailscale IP and names)')
    ap.add_argument('--roots-json', default=str(Path.home() / '.config/mds/roots.json'))
    ap.add_argument('--extra-root', action='append', default=None,
                    help='another folder to allow (default: ~/Documents/mds)')
    args = ap.parse_args(argv)
    extra = [Path(os.path.expanduser(p)) for p in (args.extra_root or ['~/Documents/mds'])]
    hosts = {h.strip().lower() for h in args.allow_host.split(',') if h.strip()}
    cfg = Config(Path(os.path.expanduser(args.roots_json)), extra, Path.home(), hosts)
    srv = make_server(args.port, cfg)
    print('[mdv] http://127.0.0.1:%d%s/  roots: %s  model: %s%s'
          % (args.port, PREFIX, ', '.join(map(str, cfg.roots())), model.MODEL, ' (FAKE)' if model.fake() else ''),
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    sys.exit(main())
