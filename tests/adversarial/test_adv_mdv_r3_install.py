"""Hostile review, round 3: threads.py install_mdv (copy into a .new folder, write Suda's pieces, chmod, rename).

- copytree follows symlinks and the chmod pass makes every file 0644: a symlink under mdv/ (to a private file, a
  key) is installed as a world-readable copy of its target.
- An install that fails after the copy (suda.html without its sprite, a full disk) leaves its .new.<pid> folder for
  good; every later failure adds one more.
Each case runs install_mdv() alone in a subprocess, from a throwaway copy of the repository's threads.py and mdv/,
with BOARDS_DIR, THREADS_MDV_DIR and THREADS_BOARDLIB_DIR in temp folders (boardlib: MDV_ADV_BOARDLIB when set, else
Suda's own suda_boardlib.py, copied there). Nothing outside the temp folders is written."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = _paths.APP
BOARDLIB = Path(os.environ['MDV_ADV_BOARDLIB']) if os.environ.get('MDV_ADV_BOARDLIB') else None

RUN = '''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("threads_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.install_mdv()
'''


@unittest.skipUnless((BOARDLIB / 'boardlib.py').is_file() if BOARDLIB else (HERE / 'suda_boardlib.py').is_file(), 'no boardlib')
class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self.tmp.name))
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        shutil.copy(HERE / 'threads.py', self.repo / 'threads.py')
        shutil.copy(HERE / 'store.py', self.repo / 'store.py')       # (threads.py loads the board's store beside it, sqlite177)
        shutil.copy(HERE / 'suda.html', self.repo / 'suda.html')
        shutil.copytree(HERE / 'mdv', self.repo / 'mdv',
                        ignore=shutil.ignore_patterns('__pycache__', 'suda.css', 'suda-pure.js', 'icons.svg.html'))
        self.dest = self.base / 'share' / 'mdv'
        (self.base / 'boards').mkdir()
        self.lib = BOARDLIB or self.base / 'lib'
        if not BOARDLIB:
            self.lib.mkdir()
            shutil.copy(HERE / 'suda_boardlib.py', self.lib / 'suda_boardlib.py')

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        env = dict(os.environ, BOARDS_DIR=str(self.base / 'boards'), THREADS_MDV_DIR=str(self.dest),
                   THREADS_BOARDLIB_DIR=str(self.lib), PYTHONDONTWRITEBYTECODE='1', HOME=str(self.base / 'home'))
        (self.base / 'home').mkdir(exist_ok=True)
        return subprocess.run([sys.executable, '-c', RUN, str(self.repo / 'threads.py')], env=env,
                              capture_output=True, text=True, timeout=60)

    def test_a_symlink_in_the_source_is_not_installed_as_a_readable_copy(self):
        private = self.base / 'private-key'
        private.write_text('sk-ant-PRIVATE')
        os.chmod(private, 0o600)
        (self.repo / 'mdv' / 'static' / 'leak.txt').symlink_to(private)
        r = self.install()
        got = self.dest / 'static' / 'leak.txt'
        if r.returncode == 0 and got.is_file() and not got.is_symlink():
            mode = stat.S_IMODE(got.stat().st_mode)
            self.assertFalse(got.read_text() == 'sk-ant-PRIVATE' and mode & 0o044,
                             'a 0600 file behind a symlink was installed as a %o copy' % mode)

    def test_a_failed_install_leaves_no_half_copy(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        (self.repo / 'suda.html').write_text('<p>no style, no pure section, no sprite</p>')
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        left = sorted(p.name for p in self.dest.parent.iterdir() if p.name != 'mdv')
        self.assertEqual(left, [], 'a failed install left %s' % left)
        self.assertTrue((self.dest / 'mdv_web.py').is_file(), 'the working copy is gone')


if __name__ == '__main__':
    unittest.main()
