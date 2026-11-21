"""Where the tests find Suda: APP is the app's folder (suda/), REPO the repository around it. Importing this puts
tests/ and tests/adversarial/ on sys.path, so a test imports another one from either folder however it was started
(python3 tests/test_x.py, python3 tests/adversarial/test_adv_x.py, python3 -m unittest from tests/)."""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if TESTS.name == 'adversarial':         # tests/adversarial/_paths.py runs this file as its own
    TESTS = TESTS.parent
REPO = TESTS.parent
APP = REPO / 'suda'
for _folder in (str(TESTS / 'adversarial'), str(TESTS)):
    if _folder not in sys.path:
        sys.path.insert(0, _folder)

# `node -e <code>`: Linux caps one argument at 128 KB (E2BIG), and the page's pure block alone is more than that.
# Every `node -e` with long code that a test runs goes through a temporary file instead, read and evaluated by a
# short -e: process.argv, stdin, require and 'use strict' stay exactly as they were.
import json as _json
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile

NODE_E_MAX = 64 * 1024

if not getattr(_subprocess.run, 'node_e_by_file', False):
    _run = _subprocess.run

    def _node_e_run(args, *rest, **kw):
        if (isinstance(args, (list, tuple)) and len(args) >= 3 and _os.path.basename(str(args[0])).startswith('node')
                and args[1] == '-e' and isinstance(args[2], str) and len(args[2].encode('utf-8')) > NODE_E_MAX):
            fd, path = _tempfile.mkstemp(prefix='node-e-', suffix='.js')
            try:
                with _os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(args[2])
                loader = "eval(require('fs').readFileSync(%s,'utf8'))" % _json.dumps(path)
                return _run([args[0], '-e', loader, *args[3:]], *rest, **kw)
            finally:
                try:
                    _os.unlink(path)
                except OSError:
                    pass
        return _run(args, *rest, **kw)

    _node_e_run.node_e_by_file = True
    _subprocess.run = _node_e_run
