"""The viewer inside another server (Suda's board server, suda-fixes m149).

The host's handler hands every request under /mdv/ to `handle(self, cfg)` and serves the rest itself:

    from mdv import web                      # (the host guards this import: a failure answers 503 on /mdv/)
    CFG = web.config(allow_hosts={...})      # once
    ...
    def do_GET(self):
        if web.owns(urlparse(self.path).path):
            return web.handle(self, CFG)

The request runs on the host's own socket, with the viewer's own guards (Host allowlist, same-origin JSON writes,
the connection closed after each answer) behind the host's. An exception inside the viewer answers 503 when no
answer has started yet, and closes the connection: the host and its other pages go on.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

from .server import PREFIX, Config, Handler

# what a parsed request of http.server carries; the viewer's handler reads only these
_STATE = ('rfile', 'wfile', 'headers', 'path', 'command', 'request_version', 'requestline', 'raw_requestline',
          'client_address', 'server', 'connection')


def owns(path: str) -> bool:
    """True for the viewer's addresses: /mdv/ and everything under it (not /mdv itself, not /mdvx)."""
    return path == PREFIX + '/' or path.startswith(PREFIX + '/')


def config(roots_json: Path | None = None, extra_roots: list[Path] | None = None, home: Path | None = None,
           allow_hosts: set[str] | None = None) -> Config:
    """The viewer's settings in a host: MDS's roots.json plus ~/Documents/mds, and the host names the host serves
    under (127.0.0.1 and localhost are always in)."""
    home = home or Path.home()
    # MDV_ROOTS_JSON / MDV_EXTRA_ROOTS (':'-separated) stand for the two where they are set: the tests' own folders
    if roots_json is None and os.environ.get('MDV_ROOTS_JSON'):
        roots_json = Path(os.environ['MDV_ROOTS_JSON'])
    if extra_roots is None and os.environ.get('MDV_EXTRA_ROOTS'):
        extra_roots = [Path(p) for p in os.environ['MDV_EXTRA_ROOTS'].split(':') if p]
    return Config(roots_json or home / '.config/mds/roots.json',
                  extra_roots if extra_roots is not None else [home / 'Documents/mds'],
                  home, {h.strip().lower().rstrip('.') for h in (allow_hosts or set()) if h.strip()})


class Request(Handler):
    """The viewer's handler, on a request another server already read the head of."""

    def __init__(self, host, cfg: Config):  # noqa: D107 - never BaseHTTPRequestHandler.__init__ (it would serve)
        for name in _STATE:
            setattr(self, name, getattr(host, name, None))
        self.cfg = cfg
        self.close_connection = True
        self.started = False

    def send_response(self, code, message=None):
        self.started = True
        super().send_response(code, message)


def handle(host, cfg: Config) -> None:
    """Serve one /mdv/ request on `host`'s connection. Never raises. The viewer's whole-request deadline runs
    here too (the host's own timeout counts per read only): a client that drips its body is cut off."""
    req = Request(host, cfg)
    req.timeout = getattr(host, 'timeout', None) or req.timeout
    req.deadline = threading.Timer(max(1, req.timeout), req.cut)
    req.deadline.daemon = True
    req.deadline.start()
    try:
        run = getattr(req, 'do_' + (host.command or ''), None)
        if run is None:
            req.fail(405, 'method')
        else:
            run()
    except Exception:  # noqa: BLE001 - a viewer bug stays a viewer answer
        print('[mdv] error on %s: %s' % (host.command, traceback.format_exc(limit=3).strip().splitlines()[-1]),
              file=sys.stderr, flush=True)
        if not req.started:
            try:
                unavailable(req)
            except Exception:  # noqa: BLE001
                pass
    finally:
        req.request_in()
        host.close_connection = True


def unavailable(h) -> None:
    """503 for /mdv/, the connection closed (also what the host answers when the viewer does not import)."""
    body = b'{"ok": false, "error": "unavailable"}'
    h.close_connection = True
    h.send_response(503)
    h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Content-Length', str(len(body)))
    h.send_header('Connection', 'close')
    h.end_headers()
    h.wfile.write(body)

