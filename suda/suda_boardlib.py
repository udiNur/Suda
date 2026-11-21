"""The few board helpers Suda needs, for a clone without the html-interview-board skill.

threads.py uses the skill's `boardlib` when it is installed (it is the same contract), else this file:
BOARDS_DIR, file_lock (with LockTimeout) and atomic_write_text.
"""
import contextlib
import fcntl
import os
import pathlib
import stat
import tempfile
import threading
import time

BOARDS_DIR = pathlib.Path(os.environ.get('BOARDS_DIR', str(pathlib.Path.home() / 'Documents/mds/boards')))

_HELD = threading.local()


class LockTimeout(RuntimeError):
    """A board lock stayed held past the timeout (a suspended command, for example)."""


@contextlib.contextmanager
def file_lock(path, timeout=None):
    """An exclusive lock for `path`, held on a sidecar `.<name>.lock` (the data file itself is replaced by every
    save, so a lock on it would guard a file that is gone). flock is per open file, so it serialises the threads
    of one process as well as separate processes. Re-entering it in the same thread raises; waiting longer than
    `timeout` seconds (BOARD_LOCK_TIMEOUT, default 30) raises LockTimeout."""
    path = pathlib.Path(path)
    lock = path.parent / f'.{path.name}.lock'
    held = _HELD.__dict__.setdefault('paths', set())
    if str(lock) in held:
        raise RuntimeError(f'nested lock on {lock}')
    if timeout is None:
        timeout = float(os.environ.get('BOARD_LOCK_TIMEOUT', '30'))
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, 'a') as f:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f'{lock} held for more than {timeout:.0f}s by another process') from None
                time.sleep(0.02)
        held.add(str(lock))
        try:
            yield
        finally:
            held.discard(str(lock))
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path, text):
    """Write `text` to `path` through a temp file in the same folder and os.replace; the file keeps its mode
    (0644 when new)."""
    path = pathlib.Path(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
