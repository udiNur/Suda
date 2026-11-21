"""The model calls: Claude through the official SDK, with the key MDS already uses.

The key is read the way MDS reads it (ANTHROPIC_API_KEY, then ~/.config/mds/anthropic_key, then the macOS
keychain item "anthropic") and lives only in this process: it is never printed, logged, sent to the page or
written anywhere.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path

# The model MDS translates with: the saved translation state carries the model's name, and only a state from the
# same model is reused block by block, so the two keep sharing one translation of each note. MDV_MODEL overrides.
MODEL = os.environ.get('MDV_MODEL', '').strip() or 'claude-haiku-4-5'
MAX_TOKENS = 16000
WORKER_IDLE = float(os.environ.get('MDV_WORKER_IDLE', '180'))   # seconds without a line: the worker is stopped
SUMMARY_MAX_TOKENS = 1500
KEY_FILE = Path.home() / '.config' / 'mds' / 'anthropic_key'


def load_key() -> str | None:
    env = os.environ.get('ANTHROPIC_API_KEY')
    if env and env.strip():
        return env.strip()
    try:
        if KEY_FILE.is_file():
            k = KEY_FILE.read_text(encoding='utf-8').strip()
            if k:
                return k
    except OSError:
        pass
    try:
        out = subprocess.run(['security', 'find-generic-password', '-s', 'anthropic', '-w'],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def has_key() -> bool:
    return fake() or load_key() is not None


def fake() -> bool:
    """Tests run the whole path with a stand-in model (no network, no key): MDV_FAKE_MODEL=1."""
    return os.environ.get('MDV_FAKE_MODEL') == '1'


_KEYISH = re.compile(r'sk-ant-[A-Za-z0-9_\-]+')


def clean_error(exc: BaseException) -> str:
    """An error said in a line, without anything that looks like a key."""
    text = ' '.join(str(exc).split())[:300] or exc.__class__.__name__
    return _KEYISH.sub('[key]', text)


def _fake_stream(system: str, messages: list[dict]):
    """The stand-in: each block comes back with ' [EN]' (or ' [HE]') at the end of its first line, in a few
    pieces, so a reply streams like a real one and keeps its Markdown. A block whose text holds MDV-SKIP is left out, as a model sometimes does."""
    body = messages[-1]['content']
    tag = ' [EN]' if 'into English' in system else ' [HE]'
    if '<mdv-block' not in body:
        yield '## Summary\n\n- ' + (body.strip().split('\n')[0][:80] or 'empty')
        return
    for m in re.finditer(r'<mdv-block n="(\d+)">\n(.*?)\n</mdv-block>', body, re.DOTALL):
        if 'MDV-SKIP' in m.group(2):
            continue
        first, _, rest = m.group(2).partition('\n')
        out = '<mdv-block n="%s">\n%s\n</mdv-block>\n\n' % (m.group(1), first + tag + ('\n' + rest if rest else ''))
        delay = float(os.environ.get('MDV_FAKE_DELAY', '0') or 0)
        for k in range(0, len(out), 40):
            if delay:
                import time
                time.sleep(delay)
            yield out[k:k + 40]


def sdk_here() -> bool:
    """Whether this Python has the anthropic SDK (the board server's Homebrew python3 has not)."""
    import importlib.util
    return importlib.util.find_spec('anthropic') is not None


def worker_cmd() -> list[str]:
    """The worker's command: MDV_WORKER_CMD (a JSON list), else uv running mdv.worker with the SDK."""
    raw = os.environ.get('MDV_WORKER_CMD')
    if raw:
        cmd = json.loads(raw)
        if isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd):
            return cmd
    uv = shutil.which('uv') or next((p for p in ('/opt/homebrew/bin/uv', str(Path.home() / '.local/bin/uv'))
                                     if os.access(p, os.X_OK)), 'uv')
    return [uv, 'run', '--quiet', '--no-project', '--with', 'anthropic', 'python', '-m', 'mdv.worker']


def stream(system: str, messages: list[dict], max_tokens: int = MAX_TOKENS):
    """Yield the reply's text as it comes: in this process when it has the SDK (or MDV_FAKE_MODEL), else through
    the worker (MDV_WORKER=1 always uses the worker)."""
    if os.environ.get('MDV_WORKER') == '1' or not (fake() or sdk_here()):
        yield from _worker_stream(system, messages, max_tokens)
        return
    yield from stream_here(system, messages, max_tokens)


def _worker_stream(system: str, messages: list[dict], max_tokens: int):
    """The reply through `python -m mdv.worker`: the request on its stdin, JSON lines back. The worker runs in a
    process group of its own (uv and the python under it), its stderr is read on the side (the last 4 KB kept, so a
    chatty one never blocks), and it is stopped when WORKER_IDLE seconds pass without a line or the stream is
    closed (a job that ends, a page that leaves)."""
    here = str(Path(__file__).resolve().parent.parent)          # the folder that holds the mdv package
    env = dict(os.environ)
    env['PYTHONPATH'] = here + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env.pop('MDV_WORKER', None)
    proc = subprocess.Popen(worker_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=here, start_new_session=True)
    lines: queue.Queue = queue.Queue()
    tail = bytearray()

    def read_out():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def read_err():
        for chunk in iter(lambda: proc.stderr.read(4096), b''):
            tail.extend(chunk)
            del tail[:-4096]

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()
    ended = False
    try:
        try:
            proc.stdin.write(json.dumps({'system': system, 'messages': messages, 'max_tokens': max_tokens}).encode('utf-8'))
            proc.stdin.close()
        except OSError:
            pass
        while True:
            try:
                line = lines.get(timeout=WORKER_IDLE)
            except queue.Empty:
                raise RuntimeError('the model worker went quiet for %d s; it was stopped' % WORKER_IDLE)
            if line is None:
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if 'error' in ev:
                raise RuntimeError(str(ev['error'])[:300])
            if ev.get('end'):
                ended = True
                break
            if isinstance(ev.get('t'), str):
                yield ev['t']
        if not ended:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            last = bytes(tail).decode('utf-8', 'replace').strip().splitlines()
            raise RuntimeError('the model worker stopped' + (': ' + last[-1][:300] if last else ''))
    finally:
        _stop(proc)


def _stop(proc) -> None:
    """The worker and everything it started (uv runs a python of its own): the whole group, then the pipes."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for f in (proc.stdin, proc.stdout, proc.stderr):
        try:
            f.close()
        except (OSError, ValueError):
            pass


def stream_here(system: str, messages: list[dict], max_tokens: int = MAX_TOKENS):
    """The reply from this process: the stand-in, or the SDK."""
    if fake():
        yield from _fake_stream(system, messages)
        return
    key = load_key()
    if not key:
        raise RuntimeError('no API key: set ANTHROPIC_API_KEY or ~/.config/mds/anthropic_key, as for MDS')
    import anthropic  # only a model call needs it
    client = anthropic.Anthropic(api_key=key)
    with client.messages.stream(model=MODEL, max_tokens=max_tokens, system=system, messages=messages) as s:
        for piece in s.text_stream:
            yield piece
        final = s.get_final_message()
        if final.stop_reason == 'refusal':
            raise RuntimeError('the model declined')
